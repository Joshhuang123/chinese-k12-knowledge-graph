#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
教材原文段落召回 —— `data/page-index.json`

R-1（docs/需求清单.md）要「每个知识点都能召回对应内容」。
但**内容本身是按页存的**（lessons 层 2.3 万页），
要按概念召回，就得有「概念 → 哪一页讲它」的索引。

## 页码基准的坑（踩过）

- `lessons.jsonl` 的 `page` 是 **PDF 扫描序号**（1..163）
- `concept-text.jsonl` 的 `pages` 是 **印刷页码**
- 两者**不是一套**，差多少每册都不同

所以这里**不用页码换算**，改用**引文反查**：
概念的原话（引文）是教材原文的一段，
在页文本里找这段字，就知道它在第几页 —— **这比页码换算准**。

## 产出

`data/page-index.json`

    {
      "_pages":   {"<学科>-<册次>-p<扫描页>": ["<conceptId>", ...]},
      "_byConcept": {"<conceptId>": [{"book":..., "page":..., "text":...}]}
    }

`_byConcept` 里带 `text` —— 那就是**教材原文段落**，
学习卡的「在书里」这一面直接用它。

跑法：python3 src/build_page_index.py
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
GRAPH = BASE / "data" / "normalized" / "graph.json"
LESSONS = BASE / "data" / "lessons.jsonl"          # 人教
LESSONS_SH = BASE / "data" / "lessons-sh.jsonl"    # 沪教
CT_RJB = BASE / "data" / "concept-text.jsonl"
CT_SH = BASE / "data" / "concept-text-sh.jsonl"
OUT = BASE / "data" / "page-index.json"

# 一页取多少字做「原文段落」
SNIPPET_LEN = 600
# 一个概念最多存几页的原文（再多就是噪声）
MAX_PAGES_PER_CONCEPT = 3


def load(p):
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


def norm(s: str) -> str:
    """归一：去空白 + 标点全角转半角 —— 用来做字面比对。"""
    s = re.sub(r"\s+", "", s or "")
    for a, b in [("，", ","), ("。", "."), ("；", ";"), ("：", ":"),
                 ("（", "("), ("）", ")"), ("？", "?"), ("！", "!"),
                 ("、", ","), ("“", '"'), ("”", '"')]:
        s = s.replace(a, b)
    return s


def snippet(text: str, probe: str, length: int = SNIPPET_LEN) -> str:
    """从页文本里截出**包含 probe 的那一段**。

    找不到就返回页首 —— 宁可给一段相关的，也不要空。
    """
    if not text:
        return ""
    t = text.strip()
    p = norm(probe)
    if not p:
        return t[:length]
    # 页文本没归一过，直接找会因标点差异找不到 → 先试归一后的定位
    i = norm(t).find(p)
    if i < 0:
        return t[:length]
    # 把归一位置映射回原文字符位置（归一不改长度，只改字符）
    # ⚠️ 归一是 1:1 替换，位置不变 → 直接用
    start = max(0, i - length // 3)
    end = min(len(t), i + len(p) + length // 3)
    return t[start:end].strip()


def quality_ok(sn: str) -> bool:
    """这段原文**能不能给人看**。

    OCR 的残骸（"1+2HO (NH),SO,+2NaoH"、"MNNN"、"ET"）看着像乱码，
    给自学的人看等于给噪声。判据：
    - **汉字占比**要够（教材正文是汉字为主）
    - **乱码行**不能太多（单字母行、单符号行是公式残骸）

    ⚠️ 公式本身就有 LaTeX 和符号，不能一刀切 ——
    这里看的是**整段**的汉字密度，不是逐行。
    """
    if not sn:
        return False
    han = sum(1 for c in sn if "一" <= c <= "鿿")
    if han / len(sn) < 0.35:
        return False
    lines = [l for l in sn.split("\n") if l.strip()]
    if not lines:
        return False
    junk = 0
    for l in lines:
        s = l.strip()
        lh = sum(1 for c in s if "一" <= c <= "鿿")
        if len(s) >= 3 and lh / len(s) < 0.3:
            junk += 1
    if junk / len(lines) > 0.4:
        return False
    return True


def main() -> int:
    g = json.load(open(GRAPH, encoding="utf-8"))
    by_name = collections.defaultdict(list)
    for n in g["nodes"]:
        if n.get("label") in ("Concept", "Skill", "Experiment"):
            by_name[n.get("name") or ""].append(n["id"])

    # ── 人教：lessons 的 concepts 字段（页 → 概念名）──────────
    index = collections.defaultdict(set)
    rjb_pages = 0
    for r in load(LESSONS):
        pg = r.get("page")
        if not isinstance(pg, int):
            continue
        key = r["id"]                    # ← 直接用 lessons 的 id
        names = r.get("concepts") or []
        if names:
            rjb_pages += 1
        for nm in names:
            for cid in by_name.get(nm, []):
                index[key].add(cid)
    print(f"人教：{rjb_pages:,} 页有关联概念")

    # ── 沪教：引文反查（lessons-sh 的 concepts 字段是 None）────
    sh_rows = load(LESSONS_SH)
    sh_by_id = {r["id"]: r for r in sh_rows}
    sh_hit = sh_miss = 0
    for r in load(CT_SH):
        quotes = [q for q in (r.get("quotes") or []) if q and len(q) >= 6]
        if not quotes:
            continue
        books = r.get("books") or []
        for bk in books:
            page_ids = sorted((pid for pid in sh_by_id if pid.startswith(bk + "-p")),
                              key=lambda x: int(x.rsplit("-p", 1)[1]))
            if not page_ids:
                continue
            for q in quotes[:3]:
                probe = norm(q)[:10]
                if not probe:
                    continue
                found = False
                for pid in page_ids:
                    if probe in norm(sh_by_id.get(pid, {}).get("text") or ""):
                        index[pid].add(r["id"])
                        found = True
                if found:
                    sh_hit += 1
                    break
            else:
                sh_miss += 1
    print(f"沪教：引文反查命中 {sh_hit:,} / 未命中 {sh_miss:,}")

    # ── 概念 → 教材原文段落 ────────────────────────────────
    # 用**引文**在页文本里定位，截出那一段。
    #
    # ⚠️ 不能写成「每个概念遍历所有页」—— 那是 8,590 × 2.3 万 = 2 亿次比对，
    #    跑不完。这里改成：把每页归一后的文本拼成**一个大字符串 + 位置表**，
    #    然后每条引文在大字符串里 `find` 一次就定位到页。
    all_lessons = {r["id"]: r for r in load(LESSONS)}
    all_lessons.update(sh_by_id)
    # 只保留有人教 concepts 关联的页（沪教那层靠引文反查，页多）
    # —— 但沪教也要能反查，所以全部页都进大字符串
    big = []          # 归一后的全文
    pos_page = []     # big 里每个字符属于哪一页
    page_text = {}    # 页 id → 原文（未归一）
    for pid, page in all_lessons.items():
        t = page.get("text") or ""
        if not t:
            continue
        page_text[pid] = t
        nt = norm(t)
        big.append(nt)
        pos_page.extend([pid] * len(nt))
    big_s = "".join(big)
    del big, pos_page
    # 位置 → 页：建前缀偏移表
    offsets = []
    acc = 0
    for pid, page in all_lessons.items():
        t = page.get("text") or ""
        if not t:
            continue
        offsets.append((acc, pid, len(norm(t))))
        acc += len(norm(t))
    offsets.sort()

    def page_at(pos: int) -> str:
        lo, hi = 0, len(offsets) - 1
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if offsets[mid][0] <= pos:
                lo = mid
            else:
                hi = mid - 1
        return offsets[lo][1]

    by_concept = collections.defaultdict(list)
    n_snip = 0
    n_junk = 0
    for r in load(CT_RJB) + load(CT_SH):
        cid = r["id"]
        quotes = [q for q in (r.get("quotes") or []) if q and len(q) >= 6]
        if not quotes:
            continue
        seen_pages = set()
        for q in quotes:
            probe = norm(q)[:10]
            if not probe:
                continue
            start = 0
            while len(by_concept[cid]) < MAX_PAGES_PER_CONCEPT:
                i = big_s.find(probe, start)
                if i < 0:
                    break
                pid = page_at(i)
                start = i + len(probe)
                if pid in seen_pages:
                    continue
                seen_pages.add(pid)
                t = page_text.get(pid) or ""
                sn = snippet(t, q)
                if sn and quality_ok(sn):
                    by_concept[cid].append({
                        "book": pid.rsplit("-p", 1)[0],
                        "page": int(pid.rsplit("-p", 1)[1]),
                        "pageId": pid,
                        "text": sn[:SNIPPET_LEN],
                    })
                    n_snip += 1
                elif sn:
                    n_junk += 1
            if len(by_concept[cid]) >= MAX_PAGES_PER_CONCEPT:
                break

    # 去重（同一页可能命中多条引文）
    for cid, lst in list(by_concept.items()):
        seen = set()
        out = []
        for x in sorted(lst, key=lambda y: (y["book"], y["page"])):
            if x["pageId"] in seen:
                continue
            seen.add(x["pageId"])
            out.append(x)
        by_concept[cid] = out[:MAX_PAGES_PER_CONCEPT]

    # ── 落盘 ────────────────────────────────────────────────
    idx = {k: sorted(v) for k, v in sorted(index.items()) if v}
    out = {"_pages": idx,
           "_byConcept": {k: v for k, v in sorted(by_concept.items())}}
    OUT.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    print(f"\n页索引 {len(idx):,} 条，涉及概念 {len(by_concept):,}")
    print(f"教材原文段落 {n_snip:,} 段（OCR 残骸重、丢弃 {n_junk:,} 段）")
    print(f"→ {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
