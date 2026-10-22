#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ISSUE-40: 沪教版/沪科版教材的概念匹配 —— `data/concept-vision-sh.jsonl`

为什么要单独一个文件
--------------------
`data/concept-vision.jsonl` 里，人教版和上海教材**被并进同一个册次桶**
（两边都用图谱的册次码 7a/8a…）。这带来两个问题：

1. **人教页把沪教页的名额吃掉。** 匹配时取前 12 个命中页，
   人教七上和沪教七上抢同一批名额 → 有些概念明明在沪教版页上，
   却因为名额被占而没挂上沪教版。
2. **候选集按「同册」限死是错的。** 沪教版七上从「第 10 章 整式的加减」起，
   人教版七上从「第 1 章 有理数」起 —— **同一个册次，两版内容对不上**。
   沪教版七上教「因式分解」「分式」「轴对称」，这些概念在人教版里的家是
   八上/七下/八下，按「同册」筛就永远匹配不上。
   （这是「book 码跨学科复用」那类坑的版本版。）

所以上海这一侧**单独一层数据**，不跟人教混。

三信号判别（谁更适合当「这本教材教这个概念」的证据）
--------------------------------------------------------
| 信号 | 含义 | 为什么可信 |
|---|---|---|
| **目录** | 概念名出现在这本书自己的目录（章名/节名）里 | **教材自己写的目录**，是教材对「我教什么」的最直接声明 |
| **目录近似** | 概念名跟某个目录名相似度 ≥ 0.8 | 目录名的变体（「分式的运算」vs「分式运算」） |
| **集中** | 该概念在这本书的页面里命中 ≥2 页，且占它在**全部 26 本沪教书**里命中数的 ≥1/3 | 概念在这本书里成片出现，而不是在别的书里 |
| **同册** | 概念在人教图谱里的册次 == 这本书的册次，且命中 ≥1 页 | 同一册两版共同覆盖的内容（沪教七上也讲有理数复习） |

**只靠「页面里出现过」是不够的**：
概念名「小数」「分子」「等式」在 20 本书的题干里都出现过 ——
它们不是「这本书教这个概念」的证据，只是这个概念是个泛词。
所以泛词不单独成立，**必须有目录或集中度撑腰**。

**宁可少抽，不抽错** —— 抽错的定义会被当成教材原话。

用法：python3 src/vision_to_concepts_sh.py
"""
from __future__ import annotations

import collections
import difflib
import json
import pathlib
import re
import sys

BASE = pathlib.Path(__file__).resolve().parent.parent
VPAGES_SH = BASE / "data" / "vision-pages-sh.jsonl"
TOC = BASE / "data" / "shanghai-toc.json"
GRAPH = BASE / "data" / "normalized" / "graph.json"
OUT = BASE / "data" / "concept-vision-sh.jsonl"

# 「集中」信号的阈值：命中页数下限 + 占全书命中数的份额下限
MIN_HITS = 2
MIN_SHARE = 0.34
# 「目录近似」的相似度下限
MIN_TOC_RATIO = 0.80


def strip_paren(nm: str) -> str:
    return re.sub(r"[（(][^）)]*[）)]", "", nm or "").strip()


def topical_blob(d: dict) -> str:
    """页面**自己给出的结构性文本**：图号、表题、题干、步骤。

    **不含公式的 context** —— 那是模型写的描述，不是教材上的字。
    模型会顺手用上页面上的任何词当占位（「表示直线**变量**」），
    把泛用词的概念匹配到不相干的页。
    """
    out = []
    for f in d.get("figures") or []:
        if isinstance(f, dict):
            out.append(str(f.get("caption", "") or ""))
    for t in d.get("tables") or []:
        if isinstance(t, dict):
            out.append(str(t.get("caption", "") or ""))
    for e in d.get("exercises") or []:
        if isinstance(e, dict):
            out.append(str(e.get("stem", "") or ""))
            for s in (e.get("steps") or []):
                out.append(str(s))
    return "\n".join(out)


def collect(d: dict):
    """把一页拆成「可直接引用」和「模型转述」两桶。"""
    formulas, formula_ctx = [], []
    for f in d.get("formulas") or []:
        if isinstance(f, dict):
            latex = (f.get("latex") or "").strip()
            if latex:
                formulas.append(latex)
                if f.get("context"):
                    formula_ctx.append({"latex": latex, "context": str(f["context"])})
        elif isinstance(f, str) and f.strip():
            formulas.append(f.strip())
    figs = []
    for f in d.get("figures") or []:
        if isinstance(f, dict):
            figs.append({
                "caption": (f.get("caption") or "").strip(),
                "kind": (f.get("kind") or "").strip(),
                "description": (f.get("description") or "").strip(),
                "provenance": "described",   # ← 模型转述，不是教材原话
            })
        elif isinstance(f, str) and f.strip():
            figs.append({"caption": "", "kind": "", "description": f.strip(),
                         "provenance": "described"})
    exs = []
    for e in d.get("exercises") or []:
        if isinstance(e, dict):
            exs.append({
                "type": (e.get("type") or "").strip(),
                "stem": (e.get("stem") or "").strip(),
                "steps": [str(s) for s in (e.get("steps") or [])],
                "provenance": "page",
            })
    tables = []
    for t in d.get("tables") or []:
        if isinstance(t, dict):
            tables.append({"caption": (t.get("caption") or "").strip(),
                           "rows": t.get("rows") or [],
                           "provenance": "page"})
    return formulas, formula_ctx, figs, exs, tables


def toc_of_book(toc_books: dict, bid: str):
    """一本书的目录条目：[(章号, 章名, 节号, 节名, 起始页, 章起始页)]"""
    b = toc_books.get(bid)
    if not b:
        return []
    out = []
    for c in b.get("chapters") or []:
        for s in c.get("sections") or []:
            out.append((c.get("no", ""), c.get("name", ""),
                        s.get("no", ""), s.get("name", ""),
                        s.get("startPage"), c.get("startPage")))
    return out


def main() -> int:
    if not VPAGES_SH.exists():
        print(f"没有 {VPAGES_SH}")
        return 1

    # ── 1. 读页面 ────────────────────────────────────────────────
    by_book = collections.defaultdict(list)
    for line in VPAGES_SH.open(encoding="utf-8"):
        if not line.strip():
            continue
        try:
            r = json.loads(line)
        except Exception:
            continue
        if not r.get("ok") or not r.get("data"):
            continue
        by_book[r["book"]].append(r)
    n_pages = sum(len(v) for v in by_book.values())
    print(f"上海教材页 {n_pages} 页 · {len(by_book)} 本")

    # ── 2. 概念索引（��学科）────────────────────────────────────
    g = json.load(open(GRAPH, encoding="utf-8"))
    concepts = []
    for n in g["nodes"]:
        if n.get("label") not in ("Concept", "Skill", "Experiment"):
            continue
        nm = (n.get("name") or "").strip()
        if len(nm) < 2 or len(nm) > 24:
            continue
        concepts.append({"id": n["id"], "name": nm, "subject": n.get("subject"),
                         "vol": n.get("book"), "bookZh": n.get("bookZh")})
    by_subj = collections.defaultdict(list)
    for c in concepts:
        by_subj[c["subject"]].append(c)

    # ── 3. 目录 ────────────────────────────────────────────────
    toc_books = json.load(open(TOC, encoding="utf-8"))["books"] if TOC.exists() else {}

    # ── 4. 先算「每本书 × 每个概念」的命中页数 ──────────────────
    # 这一步要跨全部 26 本书（集中度信号的分母），所以先扫一遍。
    tops_by_book = {}
    hits = collections.defaultdict(lambda: collections.Counter())   # bid -> cid -> 页数
    for bid, pgs in by_book.items():
        tops = [topical_blob(r["data"]) for r in pgs]
        tops_by_book[bid] = tops
        subj = pgs[0].get("subject", "math")
        blob_pages = [i for i, t in enumerate(tops) if t]
        for c in by_subj.get(subj, []):
            nm = c["name"]
            core = strip_paren(nm) or nm
            n = 0
            for i in blob_pages:
                t = tops[i]
                if nm in t or (core and core in t):
                    n += 1
            if n:
                hits[bid][c["id"]] = n
    total_hits = collections.Counter()
    for bid, cnt in hits.items():
        for cid, n in cnt.items():
            total_hits[cid] += n
    print(f"命中统计完成（{sum(total_hits.values())} 个 book×concept 命中对）")

    # ── 5. 逐本匹配 ────────────────────────────────────────────
    recs = {}          # cid -> {id, name, subject, books:{bid:{...}}}
    stats = collections.Counter()
    for bid, pgs in sorted(by_book.items()):
        p0 = pgs[0]
        subj = p0.get("subject", "math")
        gvol = p0.get("graphBook", "")
        edition = p0.get("edition", "")
        bookZh = p0.get("bookZh", "")
        tops = tops_by_book[bid]
        entries = toc_of_book(toc_books, bid)
        toc_names = []
        for (_c, cn, _s, sn, _p, _cp) in entries:
            if cn:
                toc_names.append(cn)
            if sn:
                toc_names.append(sn)
        # 小学书没有小节，章名就是目录条目
        if not toc_names:
            b = toc_books.get(bid) or {}
            for c in b.get("chapters") or []:
                if c.get("name"):
                    toc_names.append(c["name"])

        picked = []
        for c in by_subj.get(subj, []):
            nm = c["name"]
            core = strip_paren(nm) or nm
            h = hits[bid].get(c["id"], 0)
            # ① 目录：概念名出现在目录条目里
            toc_hit = None
            for (cno, cn, sno, sn, sp, cp) in entries:
                for label in (cn, sn):
                    if not label:
                        continue
                    if (nm and nm in label) or (core and core in label):
                        toc_hit = {"chapter": cno, "chapterName": cn,
                                   "section": sno, "sectionName": sn,
                                   "page": sp, "chapterPage": cp}
                        break
                if toc_hit:
                    break
            # ② 目录近似
            near = False
            if not toc_hit:
                for label in toc_names:
                    if difflib.SequenceMatcher(None, core, label).ratio() >= MIN_TOC_RATIO:
                        near = True
                        break
            # ③ 集中：这本书里成片出现，且占它全部命中的份额够大
            share = h / total_hits[c["id"]] if total_hits.get(c["id"]) else 0.0
            conc = h >= MIN_HITS and share >= MIN_SHARE
            # ④ 同册：人教图谱里的家 == 这本书的册次
            same = c["vol"] == gvol and h >= 1
            ev = []
            if toc_hit:
                ev.append("目录")
            elif near:
                ev.append("目录近似")
            if conc:
                ev.append("集中")
            if same:
                ev.append("同册")
            if not ev:
                continue
            picked.append((c, h, share, ev, toc_hit))

        # ── 5b. 取页面数据 ──────────────────────────────────────
        by_id = {c["id"]: c for c, *_ in picked}
        for (c, h, share, ev, toc_hit) in picked:
            cid = c["id"]
            nm = c["name"]
            core = strip_paren(nm) or nm
            hit_pages = []
            for i, t in enumerate(tops):
                if t and (nm in t or (core and core in t)):
                    hit_pages.append(pgs[i])
            formulas, formula_ctx, figs, exs, tables = [], [], [], [], []
            for r in hit_pages[:12]:
                f1, fc1, g1, e1, t1 = collect(r["data"])
                for x in f1:
                    if x not in formulas:
                        formulas.append(x)
                for x in fc1:
                    if x not in formula_ctx:
                        formula_ctx.append(x)
                for x in g1:
                    if x not in figs:
                        figs.append(x)
                for x in e1:
                    if x not in exs:
                        exs.append(x)
                for x in t1:
                    if x not in tables:
                        tables.append(x)
            # 公式按「context 提到概念名」排前面
            def rel(x):
                c2 = x.get("context", "")
                if nm in c2 or (core and core in c2):
                    return 0
                return 1
            formula_ctx.sort(key=rel)
            formulas = []
            for fc in formula_ctx:
                if fc["latex"] not in formulas:
                    formulas.append(fc["latex"])
            figs.sort(key=lambda x: rel({"context": x.get("caption", "") + " " +
                                         x.get("description", "")}))

            rec = recs.setdefault(cid, {
                "id": cid, "name": nm, "subject": c["subject"], "books": {}})
            rec["books"][bid] = {
                "bookZh": bookZh, "edition": edition, "graphBook": gvol,
                "evidence": ev,
                "match": "目录" if toc_hit else ("集中" if conc else "同册"),
                "share": round(share, 3),
                "tocHit": toc_hit,
                "pages": sorted(r["page"] for r in hit_pages),
                "formulas": formulas[:24],
                "formulaContexts": formula_ctx[:24],
                "figures": figs[:8],
                "exercises": exs[:12],
                "tables": tables[:6],
            }
            stats[tuple(ev)] += 1

        print(f"  {bid:26s} 页{len(pgs):4d} → 概念 {len(picked):3d}")

    # ── 6. 写盘 ─────────────────────────────────────────────────
    with OUT.open("w", encoding="utf-8") as f:
        for cid in sorted(recs, key=lambda k: recs[k]["name"]):
            f.write(json.dumps(recs[cid], ensure_ascii=False) + "\n")

    n_books = sum(len(r["books"]) for r in recs.values())
    print(f"\n概念 {len(recs)} 个 · 书-概念对 {n_books} 个")
    print("证据组合：" + " · ".join(
        f"{'+'.join(k)} {v}" for k, v in stats.most_common()))
    print(f"→ {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
