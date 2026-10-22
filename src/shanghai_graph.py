#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
构建**上海版图谱** —— 「上海的孩子学什么」独立站点要用的数据层。

节点集
------
**只收沪教版/沪科版教材页面上真实出现的概念**（`data/concept-vision-sh.jsonl`，
由 `src/vision_to_concepts_sh.py` 匹配出来，判据是教材自己的目录 + 页面命中集中度）。

先修边
------
**继承自人教版图谱 + 本项目的自建层**。
教材不会明写「这个要先学那个」；但概念之间的依赖跟教材版本无关 ——
沪教的学生学的也是「二次函数要先会一次函数」。

**自建层必须一起接进来**
------------------------
上游图谱里「二次函数」这条节点**一条前置都没有** ——
它的前置（函数、一次函数）全是本项目**自建层**补的
（`data/normalized/selfbuilt-edges.json`，13,461 条，其中 18 条是
「教材引入路径」—— 教材自己说明的前置，证据最硬）。
只接上游的话，「二次函数卡在哪」这个问题**根本没法回答**。

**先修闭包要补进来**
--------------------
人教图谱里，沪教概念自己的前置常常**不在沪教概念集合里** ——
沪教版叫「分式的运算」，人教版叫「分式运算」，两边是同一个东西。
只取交集的话，「卡在哪」面板会大面积空白。
所以把沪教概念的**先修闭包**也纳入节点集，
它们**标成灰色「前置补充」**，跟沪教教材里出现的概念分开显示。

年级 / 学段
------------
**册次码不能直接当年级用** —— 上海有两套学制：

| 版别 | 学制 | 小学 | 初中 |
|---|---|---|---|
| 沪教版 | 五四学制 | 一~五年级 | 六~九年级 |
| 沪科版 | 六三制 | 一~六年级 | 七~九年级 |

「五四学制」= 小学五年 + 初中四年，所以**沪教版六年级已经是初中一年级**
（沪教版六上第一课是「有理数」，初中内容）。
同样的册次码在两套学制里指向不同的学段 ——
所以 `stage` 必须**逐节点**算，不能拿年级号去比大小。

产出 data/shanghai-graph.json
"""
from __future__ import annotations

import collections
import json
import pathlib
import re
import sys

BASE = pathlib.Path("/Users/huangjunhai/Documents/个人/项目/中文知识图谱")
TOC = BASE / "data" / "shanghai-toc.json"
CVIS = BASE / "data" / "concept-vision-sh.jsonl"
GRAPH = BASE / "data" / "normalized" / "graph.json"
OUT = BASE / "data" / "shanghai-graph.json"

STAGE_ZH = ["小学", "初中", "高中"]

# 册次码 → (年级层, 学期名)
# 义务教育：年级号就是年级层（1..9）
# 高中：**沿用上游图谱的约定**（bx1=10 / bx2=11 / bx3=12 / xzxbx1=11 /
# xzxbx2=12 / xzxbx3=12）—— 上海的人教前置补充节点也用这套刻度，
# 两边不能各用一套，否则同一个高度上混着两个年级。
VOL_HIGH = {
    "bx1": (10, "必修一"), "bx2": (11, "必修二"),
    "bx3": (12, "必修三"), "bx4": (12, "必修四"),
    "xzxbx1": (11, "选必一"), "xzxbx2": (12, "选必二"),
    "xzxbx3": (12, "选必三"),
}
VOL_CN = {f"{i}{v}": f"{c}{'上' if v == 'a' else '下'}"
          for i, c in enumerate("一二三四五六七八九", 1) for v in "ab"}
VOL_CN.update({f"{i}": f"{c}" for i, c in enumerate("一二三四五六七八九", 1)})
VOL_CN.update({k: v[1] for k, v in VOL_HIGH.items()})
# 高中册次的教学先后（必修一~四 → 选必一~三）
HIGH_ORDER = {k: i for i, k in enumerate(
    ["bx1", "bx2", "bx3", "bx4", "xzxbx1", "xzxbx2", "xzxbx3"])}


def grade_of_vol(vol: str, system: str):
    """册次码 → (年级层, 显示名, 学段)。

    **学段必须看学制** —— 沪教版五四制六年级是初中，沪科版六三制六年级是小学。
    """
    if vol in VOL_HIGH:
        g, nm = VOL_HIGH[vol]
        return g, nm, 2
    m = re.match(r"^(\d)([ab]?)$", vol or "")
    if not m:
        return 0, vol or "", 0
    g = int(m.group(1))
    nm = VOL_CN.get(vol, vol)
    # 小学的年级上限：五四制 5 年（1-5），六三制 6 年（1-6）
    max_pri = 5 if system == "w" else 6
    stage = 0 if g <= max_pri else 1
    return g, nm, stage


def main() -> int:
    if not CVIS.exists():
        print(f"没有 {CVIS}，先跑 src/vision_to_concepts_sh.py")
        return 1
    toc = json.load(open(TOC, encoding="utf-8"))["books"] if TOC.exists() else {}
    print(f"有目录的书 {len(toc)} 本")

    # ── 1. 每本书的「页 → 节」映射 ────────────────────────────
    # 目录里每节有起始页，节的页范围 = [本页, 下一节起始页)
    page_section = {}
    book_units = {}
    for bid, b in toc.items():
        secs = []
        for c in b.get("chapters", []):
            for s in c.get("sections", []):
                pg = s.get("startPage")
                if pg is None:
                    pg = s.get("page")
                if pg is None:
                    continue
                secs.append({
                    "chapter": c.get("no", ""), "chapterName": c.get("name", ""),
                    "section": s.get("no", ""), "sectionName": s.get("name", ""),
                    "page": int(pg),
                })
        secs.sort(key=lambda x: x["page"])
        book_units[bid] = secs
        n_pages = b.get("totalPages") or 0
        for i, s in enumerate(secs):
            if i + 1 < len(secs):
                end = secs[i + 1]["page"]
            elif n_pages:
                end = n_pages + 1
            else:
                end = s["page"] + 40
            for p in range(s["page"], min(end, s["page"] + 400)):
                page_section[(bid, p)] = s
    print(f"节链 {sum(len(v) for v in book_units.values())} 节 · "
          f"页→节映射 {len(page_section)} 页")

    # ── 2. 沪教版概念 ──────────────────────────────────────────
    recs = {}
    for line in CVIS.open(encoding="utf-8"):
        if not line.strip():
            continue
        c = json.loads(line)
        recs[c["id"]] = c
    print(f"沪教概念 {len(recs)} 个")

    nodes = {}
    for cid, c in recs.items():
        books = {}
        for bid, b in (c.get("books") or {}).items():
            gvol = b.get("graphBook", "")
            system = "w" if "-w-" in bid else "s"
            grade, volnm, stage = grade_of_vol(gvol, system)
            secs = []
            for p in (b.get("pages") or []):
                s = page_section.get((bid, p))
                if s and s not in secs:
                    secs.append(s)
            th = b.get("tocHit")
            if th and th not in secs:
                secs.insert(0, {
                    "chapter": th.get("chapter", ""),
                    "chapterName": th.get("chapterName", ""),
                    "section": th.get("section", ""),
                    "sectionName": th.get("sectionName", ""),
                    "page": th.get("page"),
                })
            books[bid] = {
                "bookId": bid, "title": b.get("bookZh", ""),
                "edition": b.get("edition", ""), "system": system,
                "graphBook": gvol, "volName": volnm, "grade": grade,
                "stage": stage,
                "evidence": b.get("evidence", []),
                "pages": sorted(b.get("pages") or []),
                "sections": secs,
                "formulas": (b.get("formulas") or [])[:12],
                "figures": (b.get("figures") or [])[:6],
                "exercises": (b.get("exercises") or [])[:8],
            }
        if not books:
            continue
        # 一个概念可能在多本书里（沪教版 + 沪科版）→ 取**年级最早**的那本当主位置；
        # 同年级时**沪教版优先** —— 上海的主教材是沪教版（上海教育出版社，五四学制），
        # 沪科版（六三制）只在部分学校用。
        main_bid = min(books, key=lambda b: (
            books[b]["grade"],
            0 if books[b]["edition"] == "沪教版" else 1,
            books[b]["system"]))
        mb = books[main_bid]
        nodes[cid] = {
            "id": cid, "name": c["name"], "subject": c.get("subject") or "math",
            "kind": "sh",
            "grade": mb["grade"], "stage": mb["stage"],
            "mainBook": main_bid,
            "books": books,
            "bookTitles": [b["title"] for b in books.values()],
            "editions": sorted({b["edition"] for b in books.values()}),
            "sections": mb["sections"],
            "pages": sorted(mb["pages"]),
            "evidence": mb["evidence"],
        }
    print(f"入图概念 {len(nodes)} 个")

    # ── 3. 先修边（人教版图谱 + 自建层，限制在子集内）─────────
    g = json.load(open(GRAPH, encoding="utf-8"))
    info = {n["id"]: n for n in g["nodes"]}
    # 来源码必须跟 build_viz.py 的 SRC 一致，页面上才能显示对徽标
    SRC = {"dataset": 0, "model": 1, "l0": 2, "derived": 3, "intro": 4,
           "fix": 5, "structmap": 6}
    pre = collections.defaultdict(set)
    adj = collections.defaultdict(set)
    for e in g["edges"]:
        if e.get("type") != "prerequisites_for":
            continue
        pre[e["to"]].add(e["from"])
        adj[e["to"]].add(e["from"])

    # **自建层**：上游图谱里「二次函数」一条前置都没有，
    # 它的前置全是自建层补的。不接这一层，核心问题没法回答。
    SELF = BASE / "data" / "normalized" / "selfbuilt-edges.json"
    self_nodes = {}
    self_edges = []
    if SELF.exists():
        sb = json.load(open(SELF, encoding="utf-8"))
        self_nodes = {n["id"]: n for n in sb["nodes"]}
        for e in sb["edges"]:
            if e.get("type") != "prerequisites_for":
                continue
            self_edges.append(e)
            adj[e["to"]].add(e["from"])
    print(f"上游先修边 + 自建边 {len(self_edges)} 条")

    # ── 4. 先修闭包（补进来，标成「前置补充」）─────────────────
    closure, q = set(), list(nodes)
    while q:
        x = q.pop()
        for p in adj.get(x, ()):
            if p not in closure:
                closure.add(p)
                q.append(p)
    added = 0
    for cid in closure:
        if cid in nodes:
            continue
        if cid in self_nodes:
            n = self_nodes[cid]
            # 自建节点不属于任何一册 —— 标自己的层，不标册次
            kind = "l0" if n.get("label") == "Ability" else "pre"
            dz = {"Ability": "能力底座", "derived": "自建概念",
                  "textbook": "教材缺口"}.get(n.get("source") or n.get("label"), "自建")
            nodes[cid] = {
                "id": cid, "name": n["name"],
                "subject": n.get("subject") or "math", "kind": kind,
                "grade": 0, "stage": 0, "mainBook": "", "books": {},
                "bookTitles": [], "editions": [],
                "sections": [], "pages": [], "evidence": [],
                "preNote": "本项目补的能力底座/自建概念（不在沪教版页面上）",
                "volName": dz, "dz": dz,
                "desc": n.get("definition") or "",
            }
            added += 1
            continue
        n = info.get(cid)
        if not n:
            continue
        grade = n.get("grade") or 0
        stage = {"小学": 0, "初中": 1, "高中": 2}.get(n.get("stage"), 1)
        vol = n.get("book") or ""
        nodes[cid] = {
            "id": cid, "name": n["name"], "subject": n.get("subject") or "math",
            "kind": "pre",
            "grade": grade, "stage": stage,
            "mainBook": "", "books": {},
            "bookTitles": [n.get("bookZh") or ""],
            "editions": ["人教版"],
            "sections": [], "pages": [], "evidence": [],
            "preNote": "人教版图谱里的对应概念（沪教版页面上没单独出现）",
            "volName": VOL_CN.get(vol, vol),
            "desc": (n.get("props") or {}).get("definition") or "",
        }
        added += 1
    print(f"先修闭包补充 {added} 个（灰点）")

    ids = set(nodes)
    edges = []
    for a in ids:
        for b in pre.get(a, ()):
            if b in ids:
                edges.append([a, b, 0])
    for e in self_edges:
        if e["from"] in ids and e["to"] in ids:
            edges.append([e["from"], e["to"], SRC.get(e.get("source"), 1)])
    edges.sort()
    print(f"子集内先修边 {len(edges)} 条")

    # ── 5. 单元（节）链 ────────────────────────────────────────
    # **必须按教学顺序排，不能按 bookId 字典序排** ——
    # 字典序会把「必修四」排在「小学一年级」前面（s- 开头 vs w- 开头），
    # 于是「上一单元」会从「整式」（七上）跳到「中国的能源生产与消费」（必修四）。
    def book_order_key(bid):
        b = toc.get(bid) or {}
        gvol = b.get("graphBook", "") or ""
        system = "w" if "-w-" in bid else "s"
        if gvol.startswith("bx") or gvol.startswith("xzxbx"):
            return (2, HIGH_ORDER.get(gvol, 99))
        m = re.match(r"^(\d)([ab]?)$", gvol)
        if not m:
            return (1, 99, 0)
        g = int(m.group(1))
        sem = 0 if m.group(2) in ("a", "") else 1
        # 学段：沪教版五四制小学 1-5、初中 6-9；沪科版六三制小学 1-6、初中 7-9
        max_pri = 5 if system == "w" else 6
        return (0 if g <= max_pri else 1, g, sem)

    units = []
    for bid in sorted(book_units, key=book_order_key):
        secs = book_units[bid]
        b = toc[bid]
        for i, s in enumerate(secs):
            units.append({
                "bookId": bid, "edition": b.get("edition", ""),
                "bookTitle": b.get("title", ""),
                "graphBook": b.get("graphBook", ""),
                "index": i, **s,
            })

    OUT.write_text(json.dumps({
        "_source": "上海教材（沪教版/沪科版）页图 → 概念/节链/先修边",
        "_note": "节点集=沪教教材页面上出现的概念（目录+集中度判别）+ 它们的先修闭包；"
                 "先修边继承自人教版图谱（教材不写「这个要先学那个」）",
        "_gradeRule": "学段按学制算：沪教版五四制小学1-5/初中6-9，沪科版六三制小学1-6/初中7-9",
        "nodes": [nodes[k] for k in sorted(nodes, key=lambda k: nodes[k]["name"])],
        "units": units, "edges": edges,
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    n_sh = sum(1 for v in nodes.values() if v["kind"] == "sh")
    print(f"\n{n_sh} 沪教概念 + {len(nodes)-n_sh} 前置补充 = {len(nodes)} 节点 · "
          f"{len(units)} 单元 · {len(edges)} 边 → {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
