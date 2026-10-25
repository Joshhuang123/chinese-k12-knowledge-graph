#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
教材原话修复 —— 把被 PDF 抽取切断的句子接回去。

R-1（docs/需求清单.md）的「关键约束」第 2 条要的是**教材自己的定义句**，
而现在 `concept-text.jsonl` 里的引文有 9.9% 开头残缺，
自学的人看到「物,它们的身体只有一个细胞,称为单细胞生物」会懵。

## 残缺是怎么来的（2026-10-25 实测定位）

`src/pdf_to_units.py` 的分句器：

    RE_SENT = re.compile(r"[^。！？；!?;\\n]+[。！？；!?;]?")

**`\\n` 被排除在句子字符类外面** —— 换行即句末。
但教材 PDF 的文本层是**按版面宽度硬换行**的，
一句话经常被拆到两三行：

    氧,将有机物分解成二氧化碳和水,并且将储存在
    有机物中的能量释放出来,供给生命活动的需要,
    这个过程叫做呼吸作用(respiration)。

分句器看到第一行末尾就断句，于是「有机物中的能量释放出来」前面
那行尾巴的「有」字被留在了上一句里 ——
**引文就从词的中间开始了**（"机物中的能量…"）。

不是页边界、不是 OCR、不是教材本身的问题，
是**我们自己切句切错了**。

## 怎么修

**不补字**（补了就成伪造教材原文），只做两件事：

1. **接回硬换行**：行末是汉字/字母数字、行首也是汉字/字母数字时，
   把这两行接起来。PDF 在词中间断行时就是这么断的，接回去是还原。
2. **重新切句**：接回之后再按 `。！？；` 切，拿到完整句。

⚠️ **两栏干扰**：教材正文旁边常有「小资料」侧栏，
PDF 文本层把两栏**按行交错**输出（同一行里左边正文、右边侧栏）。
直接接行会把两栏粘成一句（「…可运到植株通过叶绿素捕获太阳光…」）。
判据是**行内出现 ≥6 个连续空格** → 那是跨栏的行，
这类行不能直接接，只接不跨栏的部分。

**沪教版没有文本层**（页图 OCR），OCR 的行断得更碎，
而且看不出版面栏位 —— 这种情况**不修**，
宁可保留原样，也不能把 OCR 的碎片粘成假句子。

跑法：python3 src/quote_repair.py            # 自检
      python3 src/quote_repair.py --dump     # 打印修复前后对照
"""
from __future__ import annotations

import collections
import json
import pathlib
import re
import sys

# **脚本相对路径** —— 写死开发机的绝对路径，换机器就全废
# （ISSUE-45：远端已把 14 个脚本统一改成这个写法）
BASE = pathlib.Path(__file__).resolve().parent.parent

# ── 版面判据 ──────────────────────────────────────────────
# 行内 ≥6 个连续空格 = 这行跨了栏（正文 + 侧栏）
COLUMN_GAP = 6
# 一行最多向右接多少字（接太多容易吃进别的栏）
MAX_JOIN = 120

# 分句器：**不把换行当句末**（这是修根因的那一处）
RE_SENT = re.compile(r"[^。！？；!?;]+[。！？；!?;]?")

# 句末标点（接行时用来判断"这句完了没"）
SENT_END = "。！？；!?"

CJK = r"一-鿿"


def split_line_columns(line: str) -> list[str]:
    """把一行按 ≥COLUMN_GAP 个空格拆成若干栏内片段。

    返回的每一段都是**同一栏内**的内容。
    """
    if not line:
        return [""]
    parts = re.split(r" {%d,}" % COLUMN_GAP, line)
    return [p for p in parts if p.strip()] or [""]


# 图注行：以「图X-Y」「图X.」「表X-Y」开头，或含大段数字+标点的编号串。
# 这些是**插图的说明文字**，插在正文中间，
# 接行时会把它们粘进正文句子
# （实测："…叫做分生组织。" 前面粘上了 "图2-17油菜植株及其六大器官第二章细胞怎样构成生物体植物的几种主要组织在成熟的植物体内…"）。
RE_FIGCAP = re.compile(r"^(图|表)\s*\d+\s*[-.．]\s*\d*|^\d{1,3}\s*[”\"』]|PAGE\s*\d+")


def _is_caption(line: str) -> bool:
    """判断是不是图注/页眉页脚行（不该进正文流）。"""
    s = line.strip()
    if not s:
        return False
    if RE_FIGCAP.match(s):
        return True
    # 「第X章」「第X节」这种是章节标题，接行时会粘进上一句
    if re.match(r"^第[一二三四五六七八九十百0-9]+[章节单元部分]", s):
        return True
    return False


def _strip_trailing_columns(line: str) -> str:
    """跨栏行只取**第一栏**（正文栏通常在左）。

    ⚠️ 「小资料」侧栏在教材里排在右边，所以第一栏才是正文。
    副作用：侧栏的内容就丢了 —— 但那是**另一栏的内容**，
    粘进正文才是错（"…可运到植株通过叶绿素捕获太阳光…"就是这么来的）。
    丢的是侧栏的补充说明，不是正文的一部分。
    """
    segs = split_line_columns(line)
    return segs[0] if segs else line


def _dedupe_adjacent(lines: list[str]) -> list[str]:
    """去掉**相邻重复行**。

    PDF 文本层对同一块内容（尤其是右侧栏）会抽取两次，
    两行文字几乎一样，只有列偏移差几个空格
    （实测 rjb-bio-7a.txt 第 4426/4427 行就是同一条）。
    不去掉，接行后同一句话会被粘两遍
    （"这个过程就是人们常说的光能，储存在有机物中，这个过程就是人们常说的光合作用"）。
    """
    out: list[str] = []
    for line in lines:
        s = line.strip()
        if out:
            prev = out[-1].strip()
            # 完全相同，或者一方是另一方的前缀（差几个空格）
            if s and prev and (s == prev or
                               (len(s) > 6 and len(prev) > 6 and
                                (s in prev or prev in s))):
                # 保留更长的那个（信息更多）
                if len(s) > len(prev):
                    out[-1] = line
                continue
        out.append(line)
    return out


def join_hard_wrap(text: str) -> str:
    """把 PDF 硬换行接回去。

    规则：
    - 行末是汉字/字母数字/右括号，行首是汉字/字母数字/左括号 → 接
    - 行末是句末标点 → 不接（这句真的完了）
    - 行内跨栏（≥6 空格）→ 只取该行的**第一栏**（正文栏通常在左），
      跨栏行的内容不参与接行，避免把侧栏粘进正文
    - **相邻重复行先去掉** —— PDF 抽取层会把同一块内容抽两遍
    """
    lines = text.split("\n")
    lines = _dedupe_adjacent(lines)
    out: list[str] = []
    for raw in lines:
        line = raw.rstrip()
        if not line.strip():
            out.append("")
            continue
        if _is_caption(line):
            # 图注/章节标题单独成行，不参与接行 ——
            # 但它自己也要断句（避免跟前后正文粘成一句）
            out.append("")
            continue
        out.append(_strip_trailing_columns(line))
    # 逐行接
    joined: list[str] = []
    for line in out:
        if not joined:
            joined.append(line)
            continue
        prev = joined[-1]
        if not prev or not line:
            joined.append(line)
            continue
        if prev[-1] in SENT_END:
            joined.append(line)          # 上句完了，不接
            continue
        if re.search(r"[%sA-Za-z0-9）)\]]$" % CJK, prev) and \
           re.match(r"[%sA-Za-z0-9（(\[]" % CJK, line):
            if len(prev) + len(line) <= MAX_JOIN * 4:
                joined[-1] = prev + line   # 硬换行接上
                continue
        joined.append(line)
    return "\n".join(joined)


def sentences(text: str) -> list[str]:
    """切句。**换行不当句末** —— 只认真正的句末标点。"""
    out: list[str] = []
    for s in RE_SENT.findall(text):
        s = re.sub(r"\s+", "", s)
        s = re.sub(r"^[0-9．.、]+", "", s)
        if len(s) >= 6:
            out.append(s)
    return out


def repair_text(text: str) -> list[str]:
    """对一段页文本做「接硬换行 + 重新切句」。"""
    return sentences(join_hard_wrap(text))


def han(s: str) -> str:
    return re.sub(r"[^%s]" % CJK, "", s)


def _load_jsonl(p: pathlib.Path) -> list[dict]:
    if not p.exists():
        return []
    out = []
    for line in p.open(encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except Exception:
            continue
    return out


def build_book_sentences() -> dict:
    """人教版每册的修复后句子表 + 原文（归一后）。

    源：`data/pdf-cache/rjb-*.txt`（PDF 文本层）。
    **只有文本层能修** —— `.ocr.txt` 是 OCR 出来的，
    断行位置跟版面无关，接回去是瞎接。

    ⚠️ **pdf-cache 不入库**（教材 PDF 有版权），
    所以修复结果必须**落盘成缓存**，否则换台机器 clone 下来
    跑出来的学习卡跟入库的不一样（实测差 129 张卡）。
    缓存是**从里面抽出来的文本**，不是教材原件 —— 可以入库。
    """
    import glob
    cache = BASE / "data" / "pdf-cache"
    cand: dict[tuple, list] = collections.defaultdict(list)
    for f in sorted(glob.glob(str(cache / "rjb-*.txt"))):
        stem = pathlib.Path(f).stem[4:]
        if stem.endswith(".ocr"):
            stem = stem[:-4]
        fsubj, _, bk = stem.partition("-")
        subj = {"bio": "biology", "phys": "physics",
                "chem": "chemistry", "math": "math"}.get(fsubj, fsubj)
        if not bk:
            continue
        p = pathlib.Path(f)
        try:
            body = p.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        size = len(re.sub(r"\s", "", body))
        if size < 1000:
            continue          # 空壳（如 rjb-phys-8b.txt 是 0 字节）
        cand[(subj, bk)].append((size, body))
    out = {}
    for k, v in cand.items():
        v.sort(reverse=True, key=lambda x: x[0])
        out[k] = repair_text(v[0][1])
        # 原文（归一后）单独存 —— 回溯校验要用
        out[(k[0], k[1], "raw")] = norm_punct(v[0][1])
    return out


# ── 修复结果缓存 ──────────────────────────────────────────
# 为什么要缓存（ISSUE-45 的可复现性）：
#
# `data/pdf-cache/` **不入库**（教材 PDF 有版权）。
# 没有它就补不了引文 —— 那学习卡的产物就依赖开发机，
# 换台机器 clone 下来跑出来的东西跟入库的不一样（实测差 129 张卡）。
#
# 缓存里存的是**从教材里抽出来的句子**，不是教材原件 —— 可以入库。
CACHE = BASE / "data" / "quote-repairs.json"


def save_cache(pairs: dict) -> None:
    """把补全成功的 (概念id, 原引文) → 完整句 存成缓存。"""
    if not pairs:
        return
    old = {}
    if CACHE.exists():
        try:
            old = json.loads(CACHE.read_text(encoding="utf-8"))
        except Exception:
            old = {}
    old.update(pairs)
    CACHE.write_text(json.dumps(old, ensure_ascii=False), encoding="utf-8")
    print(f"修复缓存 → {CACHE.name}（累计 {len(old):,} 条）")


def load_cache() -> dict:
    if not CACHE.exists():
        return {}
    try:
        return json.loads(CACHE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def repair_quote(quote: str, book_sents: list[str],
                 raw_flat: str | None = None) -> str | None:
    """在修复后的句表里找回引文对应的**完整句**。

    找不到就返回 None —— **宁可没有，不拿相邻的句子凑**。

    ## 锚点怎么选（踩过的坑）

    一开始用「引文前 10 个汉字」做锚，结果选错句：
    旧引文 "●在一定的空间范围内,生物与环境形成的统一整体就是生态系统。"
    前 10 字是 "在一定的空间范围内生"，它同时命中
    「…所形成的统一的整体叫做生态系统」和「…形成的统一整体就是生态系统」，
    `min(len)` 挑了**短的**那个 —— 正好是残缺版。

    **引文开头恰恰是最不可靠的部分**（残缺就发生在开头）。
    所以锚点要用**尾部**：尾部几乎总是完整的。
    而且尾部要够长（≥8 字）才够独特。

    ## 为什么要原文回溯

    修复句是从整本书重切出来的，理论上每个字都来自原文。
    但两栏截断、重复行去重都可能造出**原文里没有的组合**。
    所以最后一步拿原文（去空白、标点归一）逐字验一遍 ——
    **验不过就丢弃，不拿它冒充教材原话**。
    """
    if not book_sents:
        return None
    qh = han(quote)
    if len(qh) < 6:
        return None
    # 尾部锚点：从尾部往前取 12 字，取最长的那个能在句表里找到的
    tail = qh[-12:]
    cands = [s for s in book_sents if tail and tail in han(s)]
    if not cands:
        # 尾部太长没命中 → 缩短再试（8 字 / 6 字）
        for n in (8, 6):
            tail = qh[-n:]
            cands = [s for s in book_sents if tail and tail in han(s)]
            if cands:
                break
    if not cands:
        return None
    # 取**最短**的包含句 —— 最短的通常就是原句本身，
    # 更长的往往是把上一句也粘进来了
    best = min(cands, key=len)
    if not han(best):
        return None
    # 原文回溯：逐字（去空白 + 标点归一）必须在原文里命中
    if raw_flat is not None and norm_punct(best) not in raw_flat:
        return None
    return best


PAIRS = [("，", ","), ("。", "."), ("；", ";"), ("：", ":"),
         ("（", "("), ("）", ")"), ("？", "?"), ("！", "!"),
         ("、", ","), ("“", '"'), ("”", '"'), ("‘", "'"), ("’", "'")]


def norm_punct(s: str) -> str:
    """标点归一 + 去空白 —— 用来跟原文逐字比对。

    教材 PDF 文本层里同一句话可能出现半角和全角两种标点
    （引文来自去空白后的分句结果，原文是带版面的），
    不归一就没法逐字比。
    """
    s = re.sub(r"\s+", "", s)
    for a, b in PAIRS:
        s = s.replace(a, b)
    return s


def main() -> int:
    dump = "--dump" in sys.argv
    book_sents = build_book_sentences()
    nbooks = len([k for k in book_sents if len(k) == 2])
    print(f"人教文本层修复：{nbooks} 册")

    ct = _load_jsonl(BASE / "data" / "concept-text.jsonl")
    stat = collections.Counter()
    samples = []
    for r in ct:
        key = (r.get("subject"), r.get("book"))
        ss = book_sents.get(key)
        if not ss:
            stat["无该册文本"] += 1
            continue
        raw = book_sents.get((key[0], key[1], "raw"))
        for q, k in zip(r.get("quotes") or [], r.get("quoteKinds") or []):
            if k not in ("definition", "theorem"):
                continue
            stat["引文总数"] += 1
            fixed = repair_quote(q, ss, raw)
            if fixed is None:
                stat["修不了（保持原样）"] += 1
                continue
            if han(fixed) == han(q):
                stat["本来就是完整的"] += 1
            else:
                stat["已补全"] += 1
                if len(samples) < 12:
                    samples.append((r["name"], q, fixed))
    print("\n修复统计：")
    for k, v in stat.most_common():
        print(f"  {k}: {v:,}")
    done = stat["已补全"] + stat["本来就是完整的"]
    if done:
        print(f"  → 可用率 {done/max(stat['引文总数'],1)*100:.1f}%"
              f"（补全率 {stat['已补全']/max(done,1)*100:.1f}%）")
    if dump:
        print("\n修复前后对照：")
        for nm, old, new in samples:
            print(f"\n【{nm}】\n  旧: {old[:80]}\n  新: {new[:110]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
