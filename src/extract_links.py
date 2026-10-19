#!/usr/bin/env python3
"""
从教材正文里抽「引入路径」：教材自己说「以前学过 X，现在学 Y」，
但图谱里没有 X→Y 这条边。

## 为什么要有这个脚本

盲测协议问的是「这个概念的**硬前置**是什么」——
模型给的是**概念逻辑上**的必要条件。
但学生卡住的地方，往往是**教学序列上的中间站**。

人教九上 22.1.2 开宗第一句（PDF 原文，全角数字已转半角）：

> 在八年级下册，我们学习了一次函数的概念，研究了它的图象和性质。
> 像研究一次函数一样，现在我们来研究二次函数的图象和性质。

22.2 第一句：

> 以前我们从一次函数的角度看一元一次方程，认识了一次函数与一元一次方程的联系。
> 本节我们从二次函数的角度看一元二次方程，认识二次函数与一元二次方程的联系。

**教材自己声明了「一次函数 → 二次函数」这条先修关系。**
而图谱里「二次函数」的前置只有模型给的「函数」——
中间站「一次函数」被跳过了。

模型没错：它只拿到「二次函数」这个名字和它在九上 22.1 的位置，
不知道学生在八下学过什么，也不知道教材是用一次函数引入的。
**这是盲测协议的信息边界，不是模型的错。**

## 判据

只认教材**明说**的四种回指句，不做语义推断：

```
在八年级下册，我们学习了 X          ← 明说年级
以前我们从 X 的角度看                ← 明说旧路径
像研究 X 一样，现在我们来研究 Y      ← 明说类比
前面我们学过 X
```

抽出来的 X 拿去做名字解析（`nameindex.py`），
Y 取回指句所在那一节的标题概念。

**然后查：图谱里有没有 X→Y 这条边？**
没有 = 漏边候选。

## 漏边不等于错边

「教材提到了 X」只说明 X 在这个位置**相关**，
不说明 X 是 Y 的**硬前置**。所以输出的是**候选**，
每条都带教材原文，人看一眼再决定建不建边。

## 跑法

```bash
python3 src/extract_links.py              # 汇总
python3 src/extract_links.py --show 30    # 逐条看
python3 src/extract_links.py --out data/normalized/intro-links.json
```
"""
import argparse
import json
import pathlib
import re
import sys
from collections import Counter

BASE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from nameindex import NameIndex, core as core_of   # noqa: E402
from books import RANK   # noqa: E402

GRAPH = BASE / "data" / "normalized" / "graph.json"
CACHE = BASE / "data" / "pdf-cache"

# 全角数字/字母转半角
FW = str.maketrans("０１２３４５６７８９（）．：，；　",
                   "0123456789().:;, ")


def fw2half(s):
    return s.translate(FW)


# 回指句模式。group(1) 是被回指的前置概念。
# **pdftotext 的中文标点会被转成半角**：
# 「在八年级下册，我们学习了一次函数的概念」出来是
# 「在八年级下册;我们学习了一次函数的概念」—— 逗号变**分号**，句号变**点**。
# 所以标点类要同时收 全角/半角逗号/分号，全角/半角句号。
# 句子还会跨行（「像\n研究一次函数一样」），所以用 re.S。
# **pdftotext 的中文标点会被转成半角**：
# 「在八年级下册，我们学习了一次函数的概念」出来是
# 「在八年级下册;我们学习了一次函数的概念」—— 逗号变**分号**，句号变**点**。
# 所以标点类要同时收 全角/半角逗号/分号，全角/半角句号。
# 句子还会跨行（「像\n研究一次函数一样」），所以用 re.S。
#
# 「我们+动词」的实测分布（23 册数学全文）：
#   学过/学习过 60 次 · 认识了/研究过/知道了 各 4 次 · 其余是噪声
#   （我们通了/我们希望通了/我们一共堆了 —— 这些不是回指）
PATS = [
    (r"在[一二三四五六七八九十\d]+年级[上下]册[，,;；]\s*我们(?:已经|以前|还|曾经)?(?:学习|学)(?:过|了)?了?([^，,;；。．.；\n]{2,24})", "明说年级"),
    (r"以前我们从([^。．.；;\n]{2,30})的角度", "以前从…角度"),
    (r"像研究([\s\S]{2,25}?)一样[，,;；]?\s*现在我们来", "像研究…一样"),
    (r"(?:前|上)面我们(?:已经)?(?:学习|学|认识|研究)(?:过|了)?了?([^。．.；;\n]{2,24})", "前面学过"),
    (r"我们(?:已经|以前|还|曾经)?(?:学习|学|认识|研究|知道)(?:过|了)?了?([^，,;；。．.；\n]{2,24})", "我们学过…"),
]

# 册次码 → 文件名册码（跟 verify_order 同一套）
BOOK = {"bx1": "m1", "bx2": "m2",
        "xzxbx1": "x1", "xzxbx2": "x2", "xzxbx3": "x3"}

# 名字里常见的「的X」后缀，抽取时剥掉 —— 「一次函数的概念」→ 「一次函数」
TAIL_NOISE = re.compile(
    r"(的(?:概念|性质|图象|图像|图形|定义|意义|知识|方法|内容|特征|公式|原理|表示|"
    r"解法|判别式|求法|意义|关系|结构|过程|步骤))+")

# 章节标题：`22.1.2 二次函数 y=ax^2 的图象和性质` 或 `22.1 二次函数的图象和性质`
SEC = re.compile(r"^\s*(\d{1,2}(?:\.\d{1,2}){0,2})\s*[　 ]\s*(\S.*?)\s*$")


def sections(text):
    """把正文按小节切成 [(节号, 标题, 正文), …]。

    **目录里也有节标题**，而且长得跟正文节标题一模一样
    （「22.1 二次函数的图象和性质  28」—— 末尾的 28 是页码）。
    切分时两处都处理掉：
      1. 标题行末尾跟纯数字 → 是目录条目，页码不是标题的一部分
      2. 同一个节号在全文出现两次（目录一次、正文一次）→ 留正文最长的那个
    """
    lines = text.split("\n")
    out = []
    cur = None
    for ln in lines:
        s = fw2half(ln).strip()
        m = SEC.match(s)
        if m and len(s) <= 40 and not re.search(r"[。；]", s) and \
                re.search(r"[一-鿿]", m.group(2)):
            title = m.group(2)
            if re.search(r"\d{1,3}$", title):
                title = re.sub(r"\s*\d{1,3}$", "", title).strip()
            if cur:
                out.append(cur)
            cur = [m.group(1), title, []]
            continue
        if cur is not None:
            cur[2].append(ln)
    if cur:
        out.append(cur)

    # 同节号去重：留正文最长的
    best = {}
    for n, ti, body in out:
        b = "\n".join(body)
        if n not in best or len(b) > len(best[n][2]):
            best[n] = (n, ti, b)
    return [best[k] for k in sorted(best, key=lambda x: [int(p) for p in x.split(".")])]


# 「我们学过 X」里的 X 经常不是干净的单个概念名：
#     我们学过 整数加法的运算律          → 图谱里叫「加法运算律」
#     我们学过 加法交换律、结合律        → 两个概念
#     我们学过 有理数的加、减、乘、除和乘方运算  → 四个概念
#     我们学过 最基本的方程———一元一次方程  → 破折号分隔
# 直接整句去 resolve，54 次命中里 50 次解析不到。
#
# 切分策略：按顿号/逗号/和/与/以及/破折号切，逐段再剥尾部「的X」，
# 取**第一个能解析**的。
SPLIT = re.compile(r"[、，,和与及以及\-—－:：;；]+")


def candidates_of(raw):
    """把一句捕获文本拆成可能的概念名候选，按优先级排。"""
    raw = raw.strip().strip("：:；;，,。．.、 ")
    out, seen = [], set()
    for piece in SPLIT.split(raw):
        piece = piece.strip()
        if not piece or len(piece) > 20:
            continue
        for v in (piece, TAIL_NOISE.sub("", piece).strip()):
            if v and len(v) >= 2 and v not in seen:
                seen.add(v)
                out.append(v)
    # 整句也作为一个候选（「整数加法的运算律」这种整体就是节点名的）
    if raw and len(raw) <= 20 and raw not in seen:
        out.insert(0, raw)
    return out


def resolve_loose(idx, raw):
    """宽松解析一个教材提到的概念名 → (node_id 或 None, 用的哪一档, 原样候选)。

    CONTAIN 档**只在唯一候选时接受**。
    nameindex 自己不把 CONTAIN 当结论（「表内乘法」⊃「乘法」），
    那是因为连边时指错比不指更糟；这里同样。
    但「教材提到的一个词」要落到图谱节点上，CONTAIN 是唯一出路 ——
    所以只在**没有歧义**时用：候选唯一，或最长候选比次长候选明显更具体。
    """
    for cand in candidates_of(raw):
        st, nid, cands, how = idx.resolve(cand)
        if nid is not None:
            return nid, st, cand
        if st.startswith("CONTAIN") and len(cands) == 1:
            return cands[0], "CONTAIN_UNIQUE", cand
    return None, "NONE", raw


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--show", type=int, default=0)
    ap.add_argument("--out")
    ap.add_argument("--glob", default="rjb-math-*.txt",
                    help="扫哪些 PDF 的文本层。化学/生物是 rjb-chem-*.txt / rjb-bio-*.txt")
    args = ap.parse_args()

    g = json.load(open(GRAPH, encoding="utf-8"))
    idx = NameIndex(g["nodes"])

    # Section → 它的概念子节点。
    # **后继不能靠节标题去解析名字** —— 节标题是「二次函数y=ax2的图象和性质」，
    # 图谱里的节点叫「二次函数 y = ax^2 的图象」，正则化后才对得上，
    # 但中间隔着 PDF 的假名（狔犪狓），靠名字匹配很脆。
    # 图谱本来就知道「哪个概念属于哪一节」，直接用它。
    sec_kids, chap_kids = {}, {}
    for e in g["edges"]:
        if e["type"] == "appears_in":
            tgt = g["nodes"][[n["id"] for n in g["nodes"]].index(e["to"])] \
                if False else None
    node_by_id = {n["id"]: n for n in g["nodes"]}
    for e in g["edges"]:
        if e["type"] == "appears_in":
            t = node_by_id.get(e["to"], {})
            if t.get("label") == "Section":
                sec_kids.setdefault(e["to"], []).append(e["from"])
            elif t.get("label") == "Chapter":
                chap_kids.setdefault(e["to"], []).append(e["from"])

    # 图谱已有的边
    have = set()
    for e in g["edges"]:
        if e["type"] == "prerequisites_for":
            have.add((e["from"], e["to"]))

    rows = []
    stats = Counter()
    # **不要只扫 rjb-math-*.txt。** 引入路径检测对化学/生物同样适用，
    # 而它们的教材文件名是 rjb-chem-9b / rjb-bio-7a。
    # 册次码 → 学科前缀的映射（跟 verify_order 的 FILE 表同源）。
    for pdf in sorted(CACHE.glob(args.glob)):
        if pdf.name.endswith(".ocr.txt"):
            continue
        book = pdf.stem.replace("rjb-math-", "")
        for pre in ("rjb-chem-", "rjb-bio-", "rjb-phys-"):
            if pdf.stem.startswith(pre):
                book = pdf.stem.replace(pre, "")
                break
        text = fw2half(pdf.read_text(encoding="utf-8", errors="replace"))
        for secno, sectitle, body in sections(text):
            b = fw2half(body)
            for pat, tag in PATS:
                for m in re.finditer(pat, b, re.S):
                    if m.groups():
                        pre_raw = m.group(1)
                    else:
                        pre_raw = m.group(0)
                    pre_raw = re.sub(r"^.*?我们", "", pre_raw)
                    # 本节（按章号）名下的概念，作为后继候选池
                    chap0 = secno.split(".")[0]
                    want0 = f"_ch{chap0}_s"
                    sec_ids = set()
                    for sid, kids in sec_kids.items():
                        if want0 in sid and sid.split("_")[1] == BOOK.get(book, book):
                            sec_ids |= set(kids)
                    # **小学的知识点直接挂在 Chapter 上，没有 Section。**
                    # order.py 的注释里写了这件事（小学 819 条 appears_in 指向
                    # Chapter，初中/高中才指向 Section），我这次只查 Section，
                    # 于是小学 11 次「本节没对上 Section」全丢了。
                    chap_node = f"math_{book}_rjb_ch{chap0}"
                    sec_ids |= set(chap_kids.get(chap_node, ()))
                    pre_raw = re.sub(r"[的了是在，,。．\s]+$", "", pre_raw)
                    pre_raw = TAIL_NOISE.sub("", pre_raw).strip()
                    if not pre_raw or len(pre_raw) > 24:
                        continue
                    pid, how, matched = resolve_loose(idx, pre_raw)
                    if pid is None:
                        stats[f"{tag}/名字解析不到"] += 1
                        continue
                    stats[f"{tag}/前置OK({how})"] += 1
                    # 后继 = 本节（按章号定位 Section）名下的概念节点
                    # 后继 = 本节标题对应的那个知识点。
                    # 早先用「整章的所有概念」当后继，54 条候选里一大半是牵强的
                    # （一次函数 → 抛物线 / 顶点 / 配方法 …）——
                    # 回指句在 22.1.2，说的是这一小节，不是整章。
                    # 图谱只到二级 Section（ch22_s1），22.1.2 没法直接定位，
                    # 所以用**节标题**跟概念名做双向包含匹配。
                    tcore = re.sub(r"(和|与|的)?(性质|图象和性质|内容|知识)$", "",
                                    sectitle).strip()
                    posts = []
                    for nid in sec_ids:
                        nm = idx.node_of[nid].get("name", "")
                        cn = core_of(nm)
                        if not cn or len(cn) < 3:
                            continue
                        if cn in tcore or (len(tcore) >= 4 and tcore in cn):
                            posts.append(nid)
                    if not posts:
                        # 退一步：本节正文里**第一次出现**的概念
                        for nm in sorted(idx.by_norm, key=len, reverse=True):
                            if len(nm) < 3:
                                continue
                            if nm in re.sub(r"\s+", "", b):
                                cands = idx.by_norm[nm]
                                for c in cands:
                                    if c in sec_ids:
                                        posts.append(c)
                                if posts:
                                    break
                    posts = [x for x in dict.fromkeys(posts) if x != pid]
                    if not posts:
                        stats[f"{tag}/本节没对上 Section"] += 1
                        continue
                    for tid in posts:
                        # **倒挂的直接扔掉**：前置的教材位置不能晚于后继。
                        # 「全等三角形」(八上) →「角的平分线」(七上) 这种
                        # 出现了 3 条 —— 回指句是真的，但切分切错了段
                        # （原句里两个概念挨着，匹配到了后一个）。
                        # 引入路径讲的是「先学 A 再学 B」，位置反了就自相矛盾。
                        na_, nb_ = idx.node_of.get(pid, {}), idx.node_of.get(tid, {})
                        ra, rb = na_.get("book"), nb_.get("book")
                        if ra and rb and RANK.get(ra, 0) > RANK.get(rb, 0):
                            stats[f"{tag}/倒挂丢弃"] += 1
                            continue
                        # **下位当前置的排除掉**。
                        # 8a 14.3 原文说「我们学过因式分解」，指向的是
                        # 「识别多项式结构进行因式分解」—— 后者包含前者，
                        # 是**具体化**不是前置。学「因式分解」不需要先会
                        # 「识别多项式结构进行因式分解」。
                        # 这跟 ISSUE-12 是同一族判据（前置名含后继名的反面）。
                        pn = re.sub(r"[\s，,。．.、（）()]+", "", na_.get("name", ""))
                        qn = re.sub(r"[\s，,。．.、（）()]+", "", nb_.get("name", ""))
                        if len(pn) >= 2 and pn in qn and pn != qn:
                            stats[f"{tag}/下位当前置丢弃"] += 1
                            continue
                        exists = (pid, tid) in have
                        stats[f"{tag}/{'已有边' if exists else '缺边'}"] += 1
                        rows.append({
                            "book": book, "section": secno, "title": sectitle,
                            "pattern": tag,
                            "preText": pre_raw, "preMatched": matched,
                        "preHow": how, "preId": pid,
                            "preName": idx.node_of[pid].get("name", pid),
                            "preBook": idx.node_of[pid].get("bookZh") or
                                      idx.node_of[pid].get("book", ""),
                            "postId": tid,
                            "postName": idx.node_of[tid].get("name", tid),
                            "postBook": idx.node_of[tid].get("bookZh") or
                                       idx.node_of[tid].get("book", ""),
                            "exists": exists,
                            "quote": " ".join(b[max(0, m.start() - 30):
                                                 m.end() + 60].split()),
                        })

    # 同一对边可能被多个模式命中，去重
    seen, uniq = set(), []
    for r in rows:
        k = (r["preId"], r["postId"], r["section"])
        if k in seen:
            continue
        seen.add(k)
        uniq.append(r)

    miss = [r for r in uniq if not r["exists"]]
    print("=" * 60)
    print("教材回指句 → 引入路径")
    print("=" * 60)
    print(f"抽出 {len(uniq)} 条教材明说的引入路径")
    print(f"  图谱里已有这条边 : {len(uniq) - len(miss)}")
    # 丢在哪一头 —— 召回低的时候先看这个，别瞎改
    if stats:
        print("  丢失原因：")
        for k, v in sorted(stats.items(), key=lambda kv: -kv[1]):
            print(f"    {v:4}  {k}")
    print(f"  **图谱里缺这条边** : {len(miss)}")
    print()
    by_tag = Counter(r["pattern"] for r in miss)
    for k, v in by_tag.most_common():
        print(f"    {v:3}  {k}")
    print()
    print("缺边里，跨册的（前置在更早的册）最值得看：")
    cross = [r for r in miss if r["preBook"] != r["postBook"]]
    print(f"  {len(cross)} 条")
    for r in cross[:15]:
        print(f"    「{r['preName']}」({r['preBook']}) →"
              f"「{r['postName']}」({r['postBook']})  [{r['pattern']}]")

    if args.show:
        print(f"\n=== 逐条（{min(args.show, len(miss))}）===")
        for r in miss[:args.show]:
            print(f"  「{r['preName']}」→「{r['postName']}」"
                  f"  ({r['book']} {r['section']} {r['pattern']})")
            print(f"     {r['quote'][:160]}")

    if args.out:
        out = pathlib.Path(args.out)
        if not out.is_absolute():
            out = BASE / out
        out.parent.mkdir(parents=True, exist_ok=True)
        json.dump(uniq, open(out, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
        print(f"\n明细 {len(uniq)} 条已写 {out.relative_to(BASE)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
