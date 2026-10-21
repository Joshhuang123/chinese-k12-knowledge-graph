#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ISSUE-34: 把视觉层的页面数据挂到图谱概念上 —— data/concept-vision.jsonl

为什么要有这一层
----------------
`data/lessons.jsonl` 是 OCR 的产物：汉字能读，公式和图形是残骸。
`data/vision-pages.jsonl` 是视觉模型读扫描页的产物：公式 LaTeX 完整、
图形语义完整。两者互补：
  - OCR  → 教材**说了什么话**（原话，可直接引用）
  - 视觉 → 教材**画了什么 / 写了什么式子**（式子可直接引用，图形是转述）

**严格区分两类内容**（这是本项目的史实铁律）：
  - 公式 LaTeX、例题题干、表格数据 = 从页面上抄下来的原文，可直接引用
  - 图形描述 = 视觉模型对图**转述**的话，不是教材原话，引用时必须标注来源

匹配规则
--------
1. 概念名**去掉括号注释**后再匹配（上游概念名大量带括号）
2. **必须限定同册 + 同学科** —— book 码跨学科复用（7a 既是数学七上也是生物七上）
3. 先精确（字面出现），再模糊（二元字组 + 相似度 ≥ 0.72）
4. 匹配不上宁可没有，不硬凑

用法：python3 src/vision_to_concepts.py
"""
from __future__ import annotations

import collections
import difflib
import json
import pathlib
import re
import sys

BASE = pathlib.Path(__file__).resolve().parent.parent
GRAPH = BASE / "data" / "normalized" / "graph.json"
VPAGES = BASE / "data" / "vision-pages.jsonl"
OUT = BASE / "data" / "concept-vision.jsonl"

SUBJ_ZH = {"math": "数学", "biology": "生物", "chemistry": "化学", "physics": "物理"}

# 其他版本的册次名是「七上」这种，图谱里是「7a」—— 不映射的话
# alt 的 8,529 页一个概念都匹配不上（跟 book 码跨学科复用是同一类坑）。
VOL_MAP = {
    "七上": "7a", "七下": "7b",
    "八上": "8a", "八下": "8b",
    "九上": "9a", "九下": "9b",
}


def strip_paren(nm: str) -> str:
    return re.sub(r"[（(][^）)]*[）)]", "", nm or "").strip()


def bigrams(s: str):
    s = re.sub(r"[^一-鿿A-Za-z0-9]", "", s)
    return {s[i:i + 2] for i in range(len(s) - 1)} or {s}


def page_blob(d: dict) -> str:
    """一页里所有可检索的文字。"""
    out = []
    for f in d.get("formulas") or []:
        if isinstance(f, dict):
            out.append(str(f.get("latex", "")))
            out.append(str(f.get("context", "")))
        else:
            out.append(str(f))
    for f in d.get("figures") or []:
        if isinstance(f, dict):
            out.append(str(f.get("caption", "")))
            out.append(str(f.get("description", "")))
        else:
            out.append(str(f))
    for t in d.get("tables") or []:
        if isinstance(t, dict):
            out.append(str(t.get("caption", "")))
            for row in t.get("rows") or []:
                out.append(" ".join(str(c) for c in row))
    for e in d.get("exercises") or []:
        if isinstance(e, dict):
            out.append(str(e.get("stem", "")))
            for s in e.get("steps") or []:
                out.append(str(s))
    return "\n".join(out)


def topical_blob(d: dict) -> str:
    """页面**自己给出的结构性文本**：图号、表题、题干、步骤。

    **不含公式的 context** —— 那是模型写的描述，
    不是教材上的字。模型会顺手用上页面上的任何词当占位
    （「表示直线**变量**」），把泛用词的概念匹配到不相干的页。
    公式的 context 只保留在 `formulaContexts` 里做展示，不参与匹配。
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
            for s in e.get("steps") or []:
                out.append(str(s))
    return "\n".join(out)


def collect(rec: dict):
    """把一页拆成「可直接引用」和「模型转述」两桶。"""
    d = rec.get("data") or {}
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


def main() -> int:
    if not VPAGES.exists():
        print(f"没有 {VPAGES}，先跑 src/vision_pages.py")
        return 1

    # ---- 读视觉页 ----
    pages = []
    for line in VPAGES.open(encoding="utf-8"):
        try:
            r = json.loads(line)
        except Exception:
            continue
        if not r.get("ok") or not r.get("data"):
            continue
        pages.append(r)
    print(f"视觉页 {len(pages)} 页（可解析）")

    # ---- 按 (学科, 册次) 分组 ----
    def book_of(r):
        # 优先用 vision_pages.py 写下来的**图谱册次码**（graphBook）。
        # 教材自己的叫法和图谱的叫法不是一回事：
        #   教材 m1（高中必修一）-> 图谱 bx1
        #   教材 x1（选择性必修一）-> 图谱 xzxbx1
        #   alt 的「七上」-> 图谱 7a
        # 册次是跨学科复用的维度，这个项目在它上面踩过三次。
        gb = r.get("graphBook")
        if gb:
            return r.get("subject", "unknown"), gb
        bk = r["book"]
        if bk.startswith("alt:"):
            _, pub, vol = bk.split(":", 2)
            subj = ("math" if "数学" in pub else "biology" if "生物" in pub
                    else "chemistry" if "化学" in pub else "physics" if "物理" in pub
                    else r.get("subject", "unknown"))
            return subj, VOL_MAP.get(vol, vol)
        if "-" in bk:
            subj, vol = bk.split("-", 1)
            return subj, vol
        return r.get("subject", "unknown"), bk

    by_book = collections.defaultdict(list)
    for r in pages:
        subj, vol = book_of(r)
        by_book[(subj, vol)].append(r)

    # ---- 概念索引 ----
    g = json.load(open(GRAPH, encoding="utf-8"))
    concepts = []
    for n in g["nodes"]:
        if n.get("label") not in ("Concept", "Skill", "Experiment"):
            continue
        nm = (n.get("name") or "").strip()
        if len(nm) < 2 or len(nm) > 24:
            continue
        concepts.append((n["id"], nm, n.get("subject"), n.get("book"), n.get("bookZh")))

    # 概念名 → 候选（去掉括号注释后）
    name_to_c = collections.defaultdict(list)
    for cid, nm, subj, book, bookZh in concepts:
        name_to_c[nm].append((cid, nm, subj, book, bookZh))
        core = strip_paren(nm)
        if len(core) >= 2 and core != nm:
            name_to_c[core].append((cid, nm, subj, book, bookZh))

    # ── OCR 层的汉字正文：教材自己说的话 ────────────────────────
    # 数学页的变量在 OCR 里是乱码，但汉字是好的 ——
    # 「叫做二次函数」照样读得出来。这是比模型自述强得多的信号。
    LESSONS = BASE / "data" / "lessons.jsonl"
    ocr_text = {}
    if LESSONS.exists():
        for line in LESSONS.open(encoding="utf-8"):
            try:
                lr = json.loads(line)
            except Exception:
                continue
            if lr.get("isToc"):
                continue          # 目录页会把所有概念名都「命中」一次
            ocr_text[(lr.get("subject"), lr.get("book"), lr.get("page"))] = \
                lr.get("text", "") or ""
    print(f"OCR 正文页 {len(ocr_text)}（已排除目录页）")

    out_f = OUT.open("w", encoding="utf-8")
    n_c = 0
    n_exact = 0
    stats = collections.Counter()

    for (subj, vol), pgs in sorted(by_book.items()):
        # 该册所有页的可检索文本 + 倒排
        #
        # **两桶，这是精度关键**：
        #   topical —— 公式的 context、图号、表题、题干。
        #              这些是**页面自己给出的结构性文本**，概念名出现在
        #              这里，说明这一页**在讲这个概念**。
        #   broad   —— 只有图形描述（模型转述）里出现了概念名。
        #              模型写图形描述时会提到页面上**任何**名词，
        #              包括偶然出现的「正五边形的顶点」——
        #              这种页跟这个概念**没关系**。
        #
        # 差别有多大：概念「顶点」在全文里命中 177 页，
        # 在 topical 里只命中 57 页。混在一起的话，
        # 「顶点」会挂上黄金分割例题的公式（x = (-1±√5)/2）——
        # 那些公式跟二次函数的顶点**毫无关系**。
        tops = [topical_blob(r["data"]) for r in pgs]
        fulls = [page_blob(r["data"]) for r in pgs]
        # **强信号 = 教材自己说的话**：
        #   ① 视觉层的题干原文 / 图号 / 表题（抄下来的）
        #   ② OCR 层的汉字正文（教材的正文）
        # 弱信号（模型自己写的公式 context 和图形描述）**不参与匹配**。
        otexts = [ocr_text.get((subj, vol, r["page"]), "") for r in pgs]
        inv = collections.defaultdict(list)
        for i, b in enumerate(tops):
            for g2 in bigrams(b):
                inv[g2].append(i)
        for i, b in enumerate(otexts):
            for g2 in bigrams(b):
                inv[g2].append(i)

        # 这一册能对上的概念（**同册 + 同学科**）
        cands = [c for c in concepts if c[2] == subj and c[3] == vol]
        for cid, nm, s, b, bz in cands:
            core = strip_paren(nm)
            hit_top, hit_broad = [], []
            for i, bt in enumerate(tops):
                if nm in bt or (core and core in bt):
                    hit_top.append(i)
            # OCR 正文命中也算 —— 教材自己提到这个概念的页
            for i, ot in enumerate(otexts):
                if i not in hit_top and (nm in ot or (core and core in ot)):
                    hit_top.append(i)
            for i, bf in enumerate(fulls):
                if i not in hit_top and (nm in bf or (core and core in bf)):
                    hit_broad.append(i)
            hits = list(hit_top)
            match = "exact" if hits else ""
            if not hits:
                # 模糊：取最罕见的字组定位候选页（**只在 topical 桶里找**）
                gs = sorted(bigrams(core or nm), key=lambda g2: len(inv.get(g2, ())))
                cand = collections.Counter()
                for g2 in gs[:3]:
                    for i in inv.get(g2, ()):
                        cand[i] += 1
                best = (0.0, None)
                for i, _n in cand.most_common(25):
                    r = difflib.SequenceMatcher(None, core or nm, tops[i]).ratio()
                    if r > best[0]:
                        best = (r, i)
                if best[1] is not None and best[0] >= 0.72:
                    hits = [best[1]]
                    match = "fuzzy"
            if not hits and not hit_broad:
                continue

            # 公式/表格/题目**只从 topical 页取**（broad 页跟这概念没关系）
            formulas, formula_ctx, exs, tables = [], [], [], []
            figs = []

            def _rel(text):
                """跟概念的相关度：context/图号里提到概念名的排前面。"""
                if not text:
                    return 1
                if nm and nm in text:
                    return 0
                if core and core in text:
                    return 0
                return 1

            by_src: dict[str, dict] = {}
            for i in sorted(set(hits))[:12]:
                r = pgs[i]
                src = r["book"]
                s2 = by_src.setdefault(src, {"publisher": r.get("publisher", ""),
                                             "bookZh": r.get("bookZh", ""),
                                             "pages": []})
                s2["pages"].append(r["page"])
                f1, fc1, g1, e1, t1 = collect(r)
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
            # broad 页：只贡献图形描述，并且标 tier
            for i in hit_broad[:6]:
                r = pgs[i]
                src = r["book"]
                s2 = by_src.setdefault(src, {"publisher": r.get("publisher", ""),
                                             "bookZh": r.get("bookZh", ""),
                                             "pages": []})
                s2["pages"].append(r["page"])
                _f, _fc, g1, _e, _t = collect(r)
                for x in g1:
                    x = dict(x)
                    x["tier"] = "broad"
                    if x not in figs:
                        figs.append(x)
            for x in figs:
                x.setdefault("tier", "topical")

            # ── 按相关度排序 ──────────────────────────────────────
            # 公式：context 里提到概念名的排前面
            formula_ctx.sort(key=lambda fc: _rel(fc.get("context", "")))
            formulas = []
            for fc in formula_ctx:
                if fc["latex"] not in formulas:
                    formulas.append(fc["latex"])
            # 图：图号或描述里提到概念名的排前面
            figs.sort(key=lambda f: (_rel(f.get("caption", "") + " " + f.get("description", "")),
                                     f.get("tier") != "topical"))

            rec = {
                "id": cid,
                "name": nm,
                "subject": subj,
                "book": vol,
                "bookZh": bz,
                "match": match or "broad",
                "pages": sorted(set(pgs[i]["page"] for i in set(hits))),
                "broadPages": sorted(set(pgs[i]["page"] for i in hit_broad)),
                "bySource": {k: {"publisher": v["publisher"],
                                 "bookZh": v["bookZh"],
                                 "pages": sorted(set(v["pages"]))}
                             for k, v in sorted(by_src.items())},
                "formulas": formulas[:30],
                "formulaContexts": formula_ctx[:30],
                "figureDescriptions": figs[:12],
                "exercises": exs[:12],
                "tables": tables[:6],
                "counts": {
                    "formulas": len(formulas),
                    "figures": len(figs),
                    "exercises": len(exs),
                    "tables": len(tables),
                },
            }
            out_f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            n_c += 1
            if match == "exact":
                n_exact += 1
            stats[subj] += 1

    out_f.close()
    print(f"\nconcept-vision.jsonl  {n_c} 个概念（精确 {n_exact} · 模糊 {n_c - n_exact}）")
    print("按学科：" + " · ".join(f"{SUBJ_ZH.get(k, k)} {v}" for k, v in stats.most_common()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
