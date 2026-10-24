#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
人教版《小学科学》站的数据体检 —— `data/kx-graph.json` + `kx.html`

跟别的站一样，**数据层要有自己的校验**，不能靠页面看着对就算对。
逐条查：

1. **节点与目录对得上** —— 每个节点的教材位置（册/单元/节/页）必须在目录里存在
2. **页码基准统一** —— 目录是印刷页码，页图是扫描序号，偏移量必须实测出来
3. **教材序边在单元内** —— 跨单元连边是错的（并列的单元没有先后）
4. **来源码合法** —— 0 上游 / 8 教材序，不能有别的
5. **教材原话必须提到概念名** —— 否则那是同页别处的句子
6. **节点名不重复** —— 同名节点会让搜索和「上一/下一单元」乱跳
7. **payload 里没有占位符残留**
8. **教材序 ≠ 先修关系** —— 页面上必须分开标，不能混

跑法：python3 src/check_kx.py
"""
from __future__ import annotations

import json
import pathlib
import re
import sys

BASE = pathlib.Path(__file__).resolve().parent.parent
KG = BASE / "data" / "kx-graph.json"
TOC = BASE / "data" / "kx-toc.json"
SEC = BASE / "data" / "kx-sections.json"
HTML = BASE / "kx.html"

OK, BAD = [], []


def chk(cond: bool, label: str):
    (OK if cond else BAD).append(label)
    print(("  ✓ " if cond else "  ✗ ") + label)


def main() -> int:
    for p in (KG, TOC, SEC, HTML):
        if not p.exists():
            print(f"缺 {p}")
            return 1
    kg = json.load(open(KG, encoding="utf-8"))
    toc = json.load(open(TOC, encoding="utf-8"))
    sec = json.load(open(SEC, encoding="utf-8"))
    html = HTML.read_text(encoding="utf-8")

    print("── 1. 节点与目录对得上 ──")
    sec_index = set()
    for bk in toc:
        for u in toc[bk]["units"]:
            for s in u["sections"]:
                sec_index.add((bk, u["name"], s["name"], s.get("startPage")))
    miss = []
    for n in kg["nodes"]:
        for r in n["kxSections"]:
            key = (r["book"], r["unit"], r["section"], r["page"])
            if key not in sec_index:
                miss.append(f"{n['name']} {key}")
    chk(not miss, f"全部 {len(kg['nodes'])} 个节点的教材位置都在目录里"
        + (f"（不对的有 {len(miss)} 个：{miss[:3]}）" if miss else ""))

    print("\n── 2. 页码基准（印刷页码 ↔ 扫描序号）──")
    # 目录里的节起始页 + 偏移 必须 ≤ 该书页数
    bad_off = []
    for bk in toc:
        off = toc[bk].get("_offset", 0)
        npages = len([f for f in (BASE / "data" / "pdf-cache" / "kx" / bk).glob("p*.jpg")])
        last = max((s.get("startPage") or 0)
                   for u in toc[bk]["units"] for s in u["sections"])
        if last + off > npages:
            bad_off.append(f"{bk}: 末页 {last}+{off}>{npages}")
    chk(not bad_off, "每个册的偏移量都在页数范围内"
        + (f"（越界：{bad_off}）" if bad_off else ""))
    offs = {bk: toc[bk].get("_offset", 0) for bk in toc}
    chk(len(set(offs.values())) <= 3, f"偏移量实测值：{offs}")

    print("\n── 3. 教材序边在单元内 ──")
    unit_of = {}
    for bk in toc:
        for u in toc[bk]["units"]:
            for s in u["sections"]:
                unit_of[(bk, s["name"])] = u["name"]
    node_unit = {}
    for n in kg["nodes"]:
        for r in n["kxSections"]:
            node_unit[n["id"]] = (r["book"], r["unit"])
    cross = []
    for e in kg["edges"]:
        if e["src"] != 8:
            continue
        a, b = node_unit.get(e["from"]), node_unit.get(e["to"])
        if a and b and a[0] == b[0] and a[1] != b[1]:
            cross.append(f"{e['from']}→{e['to']} 跨单元 {a[1]}→{b[1]}")
    chk(not cross, "教材序边没有跨单元"
        + (f"（跨了 {len(cross)} 条：{cross[:3]}）" if cross else ""))

    print("\n── 4. 来源码合法 ──")
    srcs = {e["src"] for e in kg["edges"]}
    chk(srcs <= {0, 8}, f"边只用 0（上游先修）和 8（教材序）：实际 {sorted(srcs)}")
    chk(len(kg.get("srczh", [])) > 8, f"来源码释义表覆盖到 8：{kg.get('srczh', [''])[8:9]}")

    print("\n── 5. 教材原话必须提到概念名 ──")
    m = re.search(r'<script id="data" type="application/json">(.*?)</script>', html, re.S)
    if not m:
        chk(False, "页面里找得到 payload")
    else:
        d = json.loads(m.group(1))
        tx = d.get("text") or {}
        bad_q = []
        for j, v in tx.items():
            name = d["nodes"][int(j)][1]
            core = name.split("的")[-1] if "的" in name else name
            if name not in v[0] and not (len(core) >= 2 and core in v[0]):
                bad_q.append(f"{name} → {v[0][:30]}")
        chk(not bad_q, f"{len(tx)} 条教材原话都提到了对应概念"
            + (f"（不对：{bad_q[:3]}）" if bad_q else ""))

        print("\n── 6. 节点名不重复 ──")
        names = [n["name"] for n in kg["nodes"]]
        dup = [x for x, c in collections_counter(names).items() if c > 1]
        chk(not dup, f"节点名无重复" + (f"（重复：{dup}）" if dup else ""))

    print("\n── 7. 页面占位符残留 ──")
    residue = [t for t in ("__DATA__", "__N_TOPIC__", "__N_EDGE__", "__N_CORE__",
                           "__N_SELF__", "__N_ORDER__", "__N_PRE__", "__TIMELINE__")
               if t in html]
    chk(not residue, "没有未替换的占位符" + (f"（残留：{residue}）" if residue else ""))

    print("\n── 8. 教材序 ≠ 先修关系，页面上分开标 ──")
    chk("教材序" in html, "页面上出现「教材序」这个说法")
    chk(".sg8" in html, "来源码 8 有专门的样式（虚线边框）")
    chk("不是先修关系" in html, "页面上明说「教材序不是先修关系」")
    # 教材序(8) 跟上海教材(7) 是**两档不同的来源** ——
    # 上海站的 srczh 有 8 档，这一站加了第 8 档「教材序」，
    # 两档不能是同一个说法（否则徽标分不出来源）。
    sz = kg.get("srczh", [])
    chk(len(sz) > 8 and sz[7] != sz[8],
        f"来源码 7 和 8 是两档不同的说法：{sz[7:9]}")

    print("\n" + "=" * 60)
    print(f"通过 {len(OK)} · 失败 {len(BAD)}")
    if BAD:
        for b in BAD:
            print("  ✗ " + b)
        return 1
    return 0


def collections_counter(lst):
    import collections
    return collections.Counter(lst)


if __name__ == "__main__":
    sys.exit(main())
