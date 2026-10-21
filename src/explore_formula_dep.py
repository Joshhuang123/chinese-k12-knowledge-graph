#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
探索：**公式依赖** —— 从「一节的公式里出现了某个概念的公式」推断隐性前置。

为什么这个信号硬
----------------
前面试过「概念名出现在正文里」当隐性前置的信号，**不行**：
泛用词（三角形/体积/时间/化学）满篇都是，噪声压倒信号。

但**公式**不一样：
- 公式是**具体**的（`y = kx + b`），不会误伤
- 教材在一节里用某个概念的公式，说明**它真的在依赖那个概念**
- 这是**一手**数据（公式从扫描页直接读出来的，不是模型推断的先修边）

怎么算
------
① 每个概念 X 有一组公式（concept-vision.jsonl）
② 每节课有一组公式（vision-pages.jsonl，按页归到节）
③ 若 X 的公式在 S 的公式里**大量出现**（且不是巧合）→ S 依赖 X

「不是巧合」怎么判：
- X 的公式数 ≥ 2（一条公式撞车不算数）
- 命中的比例 ≥ 0.5

跑法：python3 src/explore_formula_dep.py
"""
from __future__ import annotations

import collections
import json
import pathlib
import re
import sys

BASE = pathlib.Path(__file__).resolve().parent.parent
GRAPH = BASE / "data" / "normalized" / "graph.json"
VISION = BASE / "data" / "vision-pages.jsonl"
CVISION = BASE / "data" / "concept-vision.jsonl"
OUT = BASE / "data" / "normalized" / "formula-dep.json"

SEC = re.compile(r"_ch(\d+)_s(\d+)$")


def norm_formula(f: str) -> str:
    """归一化：去掉空格和 LaTeX 修饰，让比较只看结构。"""
    f = re.sub(r"\\(left|right|displaystyle|quad|qquad|,|;)", "", f or "")
    f = re.sub(r"\s+", "", f)
    f = f.replace("\\{", "{").replace("\\}", "}")
    return f


def main() -> int:
    g = json.load(open(GRAPH, encoding="utf-8"))
    byid = {n["id"]: n for n in g["nodes"]}
    secid = {i for i in byid if SEC.search(i)}

    app = collections.defaultdict(list)
    for e in g["edges"]:
        if e.get("type") == "appears_in":
            app[e["from"]].append(e["to"])
    concept_unit, concept_name, concept_book = {}, {}, {}
    for n in g["nodes"]:
        if n.get("label") not in ("Concept", "Skill", "Experiment"):
            continue
        concept_name[n["id"]] = n.get("name", "")
        concept_book[n["id"]] = n.get("book")
        # **概念↔节是多对多的**（同一个「三角形」出现在很多章里）。
        # 优先取**概念自己那册**的节 —— 别的册里的节是「同一概念在别处也出现」，
        # 不是它的归属章节。
        cands = []
        for t in app.get(n["id"], []):
            if t in secid:
                m = SEC.search(t)
                cands.append((byid[t].get("book") != n.get("book"),
                              t, int(m.group(1)), int(m.group(2))))
        if cands:
            cands.sort()
            _same, _t, ch, sm = cands[0]
            concept_unit[n["id"]] = (n.get("subject"), n.get("book"), ch, sm)
    unit_name = {}
    for i, n in byid.items():
        m = SEC.search(i)
        if m:
            unit_name[(n.get("subject"), n.get("book"),
                        int(m.group(1)), int(m.group(2)))] = n.get("name", "")

    # ── 概念的公式组 ────────────────────────────────────────────
    con_formulas = {}                     # 概念 id → 归一化公式集合
    for line in CVISION.open(encoding="utf-8"):
        cv = json.loads(line)
        fs = {norm_formula(f) for f in cv.get("formulas", []) if f and len(f) > 3}
        if len(fs) >= 2:
            con_formulas[cv["id"]] = fs
    print(f"有 ≥2 条公式的概念：{len(con_formulas)}")

    # 公式 → 概念倒排（一个公式可能被多个概念共用）
    f2c = collections.defaultdict(set)
    for cid, fs in con_formulas.items():
        for f in fs:
            f2c[f].add(cid)

    # ── 节的公式组 ──────────────────────────────────────────────
    # 页 → 单元：用该页的概念反查
    page_units = collections.defaultdict(list)
    unit_formulas = collections.defaultdict(collections.Counter)
    for line in VISION.open(encoding="utf-8"):
        vr = json.loads(line)
        if not vr.get("ok"):
            continue
        gb = vr.get("graphBook") or (vr["book"].split("-", 1)[1]
                                     if "-" in vr["book"] else vr["book"])
        subj, bk, pg = vr.get("subject"), gb, vr.get("page")
        fs = {norm_formula(f.get("latex", ""))
              for f in (vr["data"].get("formulas") or [])
              if isinstance(f, dict) and f.get("latex")}
        if not fs:
            continue
        page_units[(subj, bk, pg)] = fs

    # 页 → 单元：借用 concept-text.jsonl 里的 concepts 字段？OCR 层才有
    # 这里用另一条路：**章名 + 页码**。OCR 层每页有 chapter（页眉），
    # 视觉层没有。那就反过来：先按概念反查 —— 视觉层的公式里若含某概念的公式，
    # 该页就属于那个概念所在的节。但那正是我们要算的东西（循环）。
    #
    # 换个干净的办法：**用节级的公式组** = 该节所有页的公式，
    # 而节 → 页靠「该页的公式与该节概念的公式有重叠」——
    # 同样是循环。
    #
    # 最干净：**用图谱的教材顺序链**（src/order.py）拿 节→概念，
    # 再用 OCR 层的页 → 概念 映射把页归到节。OCR 层每页有 concepts 列表。
    print("改走 OCR 层的页→概念 映射…")

    page_concepts = {}
    for line in (BASE / "data" / "lessons.jsonl").open(encoding="utf-8"):
        lr = json.loads(line)
        if lr.get("isToc"):
            continue
        page_concepts[(lr.get("subject"), lr.get("book"), lr.get("page"))] = lr.get("concepts") or []
    name_ids = collections.defaultdict(list)
    for cid, nm in concept_name.items():
        name_ids[(concept_book.get(cid), nm)].append(cid)

    page_unit = {}
    for key, nms in page_concepts.items():
        for nm in nms:
            ids = name_ids.get((key[1], nm))
            if ids and ids[0] in concept_unit:
                page_unit[key] = concept_unit[ids[0]]
                break
    print(f"页能归到节：{len(page_unit)}")

    for (subj, bk, pg), fs in page_units.items():
        u = page_unit.get((subj, bk, pg))
        if u is None:
            continue
        for f in fs:
            unit_formulas[u][f] += 1

    # ── 单元的全局顺序（跨册）────────────────────────────────────
    sys.path.insert(0, str(BASE / "src"))
    from books import rank                       # noqa: E402
    book_rank = {}
    for bk in {u[1] for u in concept_unit.values()}:
        try:
            book_rank[bk] = rank(bk)
        except Exception:
            book_rank[bk] = 999
    unit_key = lambda u: (book_rank.get(u[1], 999), u[0], u[1], u[2], u[3])   # noqa: E731
    all_units = sorted({u for u in concept_unit.values()}, key=unit_key)
    unit_index = {u: i for i, u in enumerate(all_units)}

    # ── 图谱所标前置 ────────────────────────────────────────────
    prereq = collections.defaultdict(list)
    for e in g["edges"]:
        if e.get("type") == "prerequisites_for":
            # **边是 from=先修 → to=后继**（实测：from=正比例函数 to=一次函数）
            prereq[e["to"]].append(e["from"])

    # ── 算依赖 ──────────────────────────────────────────────────
    # 概念 X 的公式组，在节 S 的公式组里命中的比例
    deps = []
    for u, counter in unit_formulas.items():
        sfs = set(counter)
        if len(sfs) < 3:
            continue
        for cid, cfs in con_formulas.items():
            if concept_unit.get(cid) is None:
                continue
            # 同一册或更早的册（前置不该来自更晚的册）
            cu = concept_unit.get(cid)
            if cu is None:
                continue
            # **必须跨节** —— 同一节里用自己引入的概念不是依赖，是同义反复
            if unit_index.get(cu, 10**9) >= unit_index.get(u, -1):
                continue
            hit = cfs & sfs
            if len(hit) < 2:
                continue
            if len(hit) / len(cfs) < 0.5:
                continue
            deps.append({
                "unit": list(u),
                "unitName": unit_name.get(u, ""),
                "bookZh": byid.get(next((i for i in secid
                                         if SEC.search(i)
                                         and byid[i].get("subject") == u[0]
                                         and byid[i].get("book") == u[1]
                                         and int(SEC.search(i).group(1)) == u[2]
                                         and int(SEC.search(i).group(2)) == u[3]), ""),
                                    {}).get("bookZh", ""),
                "concept": cid,
                "conceptName": concept_name.get(cid, ""),
                "hit": len(hit), "of": len(cfs),
                "examples": sorted(hit)[:3],
            })
    print(f"\n公式依赖对：{len(deps)}")
    # 与图谱所标前置对账
    unit_concepts = collections.defaultdict(list)
    for cid, u in concept_unit.items():
        unit_concepts[u].append(cid)
    for d in deps:
        u = tuple(d["unit"])
        gp = set()
        for c in unit_concepts.get(u, []):
            stack, seen = list(prereq.get(c, [])), set()
            while stack:
                x = stack.pop()
                if x in seen:
                    continue
                seen.add(x)
                gp.add(x)
                stack.extend(prereq.get(x, []))
        d["inGraph"] = d["concept"] in gp
    n_in = sum(1 for d in deps if d["inGraph"])
    print(f"\n跨节公式依赖 {len(deps)} 对：图谱也标了 {n_in}（{n_in/max(len(deps),1):.0%}）"
          f" · 图谱没标 {len(deps)-n_in}")
    print("\n图谱没标的（隐性前置）样本：")
    for d in [x for x in deps if not x["inGraph"]][:14]:
        print(f"  {d['bookZh']:>4s} {d['unitName'][:20]:22s} → {d['conceptName'][:16]:18s} "
              f"({d['hit']}/{d['of']} 条公式)  例: {d['examples'][0][:34]}")

    grp = collections.defaultdict(list)
    for d in deps:
        grp[(d["bookZh"], d["unitName"])].append(d)
    print("\n依赖最密的节（教材在这一节里用到了谁）：")
    for (b, n), ds in sorted(grp.items(), key=lambda kv: -len(kv[1]))[:18]:
        names = []
        for d in ds:
            if d["conceptName"] not in names:
                names.append(d["conceptName"])
        print(f"  {b:>4s} {n[:22]:24s} ← {names[:6]}")

    OUT.write_text(json.dumps({"deps": deps}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n→ {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
