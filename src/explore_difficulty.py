#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
把三个探索合成一张**内容缺口地图**：教材难度 × 图谱覆盖。

三个信号（都是一手的，不是模型推断）
--------------------------------------
① **教材标的难度**
   教材每节的「思考」「探究」框 —— 那是**教材编委会自己标的难点**。
   人教 31 册实测 2,784 处。这是本项目一直没用过的一手信号。

② **教材的跨节引用**
   一节的公式里出现了更早的节的概念的公式 → 教材自己说「这节跟前面有联系」。
   （注意：多数是**教学衔接**——回顾旧例引新课，**不等于严格的前置**。）

③ **图谱的覆盖**
   该节概念在图谱里的前置闭包有多大，其中有多少是「0 前置」（数据空白）。

交叉起来看
----------
  教材标了难点 ∧ 图谱前置薄 → **最该补内容的地方**
  教材跨节引用 ∧ 图谱没标   → 图谱漏掉的关联（教材自己划的，图谱没跟着划）

产出
----
data/normalized/textbook-difficulty.json   机器读
docs/textbook-difficulty.md                人读（跟 prereq-conflicts.md 一个套路）

跑法：python3 src/explore_difficulty.py
"""
from __future__ import annotations

import collections
import json
import pathlib
import re
import sys

BASE = pathlib.Path(__file__).resolve().parent.parent
GRAPH = BASE / "data" / "normalized" / "graph.json"
LESSONS = BASE / "data" / "lessons.jsonl"
VISION = BASE / "data" / "vision-pages.jsonl"
CVISION = BASE / "data" / "concept-vision.jsonl"
OUT = BASE / "data" / "normalized" / "textbook-difficulty.json"
MD = BASE / "docs" / "textbook-difficulty.md"

SEC = re.compile(r"_ch(\d+)_s(\d+)$")


def norm_formula(f: str) -> str:
    f = re.sub(r"\\(left|right|displaystyle|quad|qquad|,|;)", "", f or "")
    return re.sub(r"\s+", "", f).replace("\\{", "{").replace("\\}", "}")


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
    unit_concepts = collections.defaultdict(list)
    for cid, u in concept_unit.items():
        unit_concepts[u].append(cid)
    unit_name, unit_zh = {}, {}
    for i, n in byid.items():
        m = SEC.search(i)
        if m:
            u = (n.get("subject"), n.get("book"), int(m.group(1)), int(m.group(2)))
            unit_name[u] = n.get("name", "")
            unit_zh[u] = n.get("bookZh", "")

    # ── 册序 ───────────────────────────────────────────────────
    sys.path.insert(0, str(BASE / "src"))
    from books import rank                       # noqa: E402
    book_rank = {}
    for bk in {u[1] for u in unit_concepts}:
        try:
            book_rank[bk] = rank(bk)
        except Exception:
            book_rank[bk] = 999
    # 键是 (subject, book, ch, s)
    unit_key = lambda u: (book_rank.get(u[1], 999), u[0], u[1], u[2], u[3])   # noqa: E731
    all_units = sorted(unit_concepts, key=unit_key)
    unit_index = {u: i for i, u in enumerate(all_units)}

    # ── 图谱先修 ───────────────────────────────────────────────
    prereq = collections.defaultdict(list)
    for e in g["edges"]:
        if e.get("type") == "prerequisites_for":
            # **边是 from=先修 → to=后继**（实测：from=正比例函数 to=一次函数）
            prereq[e["to"]].append(e["from"])

    def closure(concepts):
        # **要 return seen，不是 out** —— out 从头到尾没被填过，
        # 所以前置闭包一直是空集，「前置覆盖」全是 0。
        stack, seen = [], set()
        for c in concepts:
            stack.extend(prereq.get(c, []))
        while stack:
            x = stack.pop()
            if x in seen:
                continue
            seen.add(x)
            stack.extend(prereq.get(x, []))
        return seen

    # ── OCR 层：页 → 概念名（用来把页归到节）────────────────────
    page_concepts = {}
    for line in LESSONS.open(encoding="utf-8"):
        lr = json.loads(line)
        if lr.get("isToc"):
            continue
        page_concepts[(lr.get("subject"), lr.get("book"), lr.get("page"))] = lr.get("concepts") or []
    name_ids = collections.defaultdict(list)
    for cid, nm in concept_name.items():
        name_ids[(concept_book.get(cid), nm)].append(cid)

    # 页 → 单元：**多数投票**。
    # 不能取「第一个匹配到的」—— OCR 层的 concepts 列表没按主题排序，
    # 第一个未必是这一页的主题。实测七上「第二章 了解生物圈」会吃掉 32 页
    # （它其实只有 8 页），把别章的思考题算成它的。
    page_unit = {}
    for key, nms in page_concepts.items():
        votes = collections.Counter()
        for nm in nms:
            for cid in name_ids.get((key[1], nm), []):
                u = concept_unit.get(cid)
                if u is not None:
                    votes[u] += 1
        if votes:
            page_unit[key] = votes.most_common(1)[0][0]

    # ── 视觉层：每页的公式 + 「思考/探究」──────────────────────
    page_formulas, page_hard, page_harditems = {}, {}, {}
    for line in VISION.open(encoding="utf-8"):
        vr = json.loads(line)
        if not vr.get("ok"):
            continue
        gb = vr.get("graphBook") or (vr["book"].split("-", 1)[1]
                                     if "-" in vr["book"] else vr["book"])
        key = (vr.get("subject"), gb, vr.get("page"))
        page_formulas[key] = {norm_formula(f.get("latex", ""))
                              for f in (vr["data"].get("formulas") or [])
                              if isinstance(f, dict) and f.get("latex")}
        items = []
        for e in vr["data"].get("exercises") or []:
            if not isinstance(e, dict):
                continue
            t = e.get("type") or ""
            if any(k in t for k in ("思考", "探究", "讨论")):
                items.append((t, (e.get("stem") or "")[:110]))
        page_hard[key] = len(items)
        page_harditems[key] = items

    # ── 节的公式组 + 难度 ──────────────────────────────────────
    unit_formulas = collections.defaultdict(set)
    unit_hard = collections.Counter()
    unit_hitems = collections.defaultdict(list)
    for key, u in page_unit.items():
        unit_formulas[u] |= page_formulas.get(key, set())
        unit_hard[u] += page_hard.get(key, 0)
        unit_hitems[u].extend(page_harditems.get(key, []))

    # ── 概念的公式组 → 跨节引用 ────────────────────────────────
    con_formulas = {}
    for line in CVISION.open(encoding="utf-8"):
        cv = json.loads(line)
        fs = {norm_formula(f) for f in cv.get("formulas", []) if f and len(f) > 3}
        if len(fs) >= 2:
            con_formulas[cv["id"]] = fs

    rows = []
    cross_total = cross_in_graph = 0
    for u in all_units:
        concs = unit_concepts[u]
        sfs = unit_formulas.get(u, set())
        hardn = unit_hard.get(u, 0)
        gp = closure(concs)
        # 跨节引用：更早的节的概念，其公式大量出现在本节
        cross = []
        for cid, cfs in con_formulas.items():
            cu = concept_unit.get(cid)
            if cu is None or unit_index.get(cu, 10**9) >= unit_index[u]:
                continue
            hit = cfs & sfs
            if len(hit) >= 2 and len(hit) / len(cfs) >= 0.5:
                cross.append({"concept": cid, "name": concept_name.get(cid, ""),
                              "hit": len(hit), "of": len(cfs),
                              "inGraph": cid in gp})
        cross_total += len(cross)
        cross_in_graph += sum(1 for c in cross if c["inGraph"])
        roots = [c for c in concs if not prereq.get(c)]
        rows.append({
            "unit": list(u),
            "bookZh": unit_zh.get(u, ""),
            "name": unit_name.get(u, ""),
            "concepts": len(concs),
            "hard": hardn,
            "hardItems": unit_hitems.get(u, [])[:5],
            "graphPre": len(gp),
            "rootConcepts": len(roots),
            "coverage": round(len(gp) / max(len(concs), 1), 2),
            "crossRefs": cross[:12],
            "crossRefCount": len(cross),
            "crossInGraph": sum(1 for c in cross if c["inGraph"]),
        })

    # 缺口分：教材标了难点 + 图谱前置薄
    def gap_score(r):
        hard = r["hard"]
        thin = 1 / (1 + r["coverage"])        # 覆盖越薄分越高
        root = 1 + r["rootConcepts"] / max(r["concepts"], 1)
        return round(hard * thin * root, 2)

    for r in rows:
        r["gapScore"] = gap_score(r)

    rows.sort(key=lambda x: -x["gapScore"])
    print(f"单元 {len(rows)} 个 · 教材标的难点合计 {sum(r['hard'] for r in rows)}")
    print(f"跨节引用 {cross_total} 对，其中图谱也标了 {cross_in_graph} "
          f"（{cross_in_graph/max(cross_total,1):.0%}）")
    print("\n「教材觉得难 + 我们数据薄」的前 20 节：")
    for r in rows[:20]:
        print(f"  {r['bookZh']:>4s} {r['name'][:20]:22s} 难点 {r['hard']:>3d} · "
              f"概念 {r['concepts']:>3d} · 前置覆盖 {r['coverage']:>4.1f} · "
              f"0前置 {r['rootConcepts']:>3d} · 缺口分 {r['gapScore']:>6.1f}")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"rows": rows}, ensure_ascii=False, indent=1), encoding="utf-8")

    # ── 「教材标的难点」按概念导出 ──────────────────────────────
    # 面板上要显示「教材在这里标了 N 处思考/探究」，
    # 就得知道每个概念在教材里被标了几处 —— 一个概念可能跨好几节。
    hard_by_concept = {}
    unattributed = 0
    for u in all_units:
        urow = next((r for r in rows if tuple(r["unit"]) == u), None)
        if not urow or not urow["hard"]:
            continue
        # 本节的概念名（去掉括号注释），用来在题干里认领
        local = []
        for cid in unit_concepts[u]:
            nm = concept_name.get(cid, "")
            core = re.sub(r"[（(][^）)]*[）)]", "", nm).strip()
            local.append((cid, nm, core))
        # 用**全部**题目（urow 里只留了前 5 道，归属要用全量）
        for kind, stem in unit_hitems.get(u, []):
            owner = None
            for cid, nm, core in local:
                if len(nm) >= 2 and nm in stem:
                    owner = cid
                    break
                if len(core) >= 2 and core and core in stem:
                    owner = cid
                    break
            if owner is None:
                unattributed += 1
                continue
            h = hard_by_concept.setdefault(owner, {
                "count": 0, "items": [], "units": [],
                "unitName": unit_name.get(u, ""), "bookZh": unit_zh.get(u, "")})
            h["count"] += 1
            if len(h["items"]) < 4:
                h["items"].append({"type": kind, "stem": stem[:110]})
            h["units"].append({"unit": list(u), "name": unit_name.get(u, ""),
                               "count": h["count"]})
    # 挑出「教材标了难点最多的」那些概念
    top_hard = sorted(hard_by_concept.items(), key=lambda kv: -kv[1]["count"])[:40]
    HARD = BASE / "data" / "normalized" / "textbook-hard.json"
    HARD.write_text(json.dumps({
        "concepts": {k: v for k, v in hard_by_concept.items()},
        "top": [{"id": k, "name": concept_name.get(k, ""), **v} for k, v in top_hard],
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n教材标的难点挂到 {len(hard_by_concept)} 个概念上"
          f"（{unattributed} 道题干没指名任何概念，不计）→ {HARD}")
    print("最难的 12 个概念（教材自己标的）：")
    for k, v in top_hard[:12]:
        print(f"  {concept_name.get(k,''):14s} {v['count']:>3d} 处 · {v['bookZh']} {v['unitName'][:18]}")

    # ── 人读的账本 ─────────────────────────────────────────────
    L = ["# 教材难度 × 图谱覆盖 —— 内容缺口地图", "",
         "> 三个信号都是**一手**的：教材自己标的「思考/探究」框、教材自己的跨节引用、"
         "图谱自己的前置标注。", "",
         "## 怎么读", "",
         "- **缺口分** = 教材标的难点数 × (1 ÷ 前置覆盖度) × (1 + 0前置概念占比)。",
         "  教材说难、而我们又说不清它靠什么 —— 那种地方最该补内容。",
         "- **跨节引用** = 一节的公式里出现了更早的节的概念的公式。",
         "  ⚠️ 多数是**教学衔接**（回顾旧例引新课），**不等于严格的前置**。",
         "  它的价值是：这是**教材自己划的关联**，图谱的先修边没覆盖。", "",
         "## 缺口最大的 40 节", "",
         "| 册 | 节 | 难点 | 概念 | 前置覆盖 | 0前置 | 缺口分 |",
         "|---|---|---|---|---|---|---|"]
    for r in rows[:40]:
        L.append(f"| {r['bookZh']} | {r['name']} | {r['hard']} | {r['concepts']} | "
                 f"{r['coverage']} | {r['rootConcepts']} | {r['gapScore']} |")
    L += ["", "## 教材跨节引用、但图谱没标的", "",
          "| 节 | 引用了 | 命中公式 | 图谱标了吗 |", "|---|---|---|---|"]
    n = 0
    for r in rows:
        for c in r["crossRefs"]:
            if c["inGraph"]:
                continue
            L.append(f"| {r['bookZh']} {r['name']} | {c['name']} | {c['hit']}/{c['of']} | 否 |")
            n += 1
            if n >= 40:
                break
        if n >= 40:
            break
    L += ["", "---", "",
          f"生成自 `src/explore_difficulty.py`。跨节引用 {cross_total} 对，"
          f"图谱也标了 {cross_in_graph} 对。"]
    MD.write_text("\n".join(L), encoding="utf-8")

    print(f"\n→ {OUT}\n→ {MD}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
