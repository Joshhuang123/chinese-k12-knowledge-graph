#!/usr/bin/env python3
"""
找「被跳过的中间站」：模型说 A 是 B 的前置，但教材上 A 和 B 隔了好几个单元。

## 为什么需要这个

ISSUE-13 发现模型给的先修边是**概念逻辑依赖**（51% 跨 5 个以上教材单元），
而学生卡住的是**教学序列上的中间站**。数学教材里「我们学过 X」这类回指句
能自动提取引入路径（见 extract_links.py），但**生物化学教材没有这种句式**
（散文式回指只有个位数），所以这条路是数学专用的。

这个脚本**不依赖教材措辞**，各科通用：

1. 拿模型边 A → B
2. 查 A 和 B 在教材序列上隔了几个单元
3. 隔得远（≥3 个单元）说明中间有一堆节点被跳过了
4. 那些中间节点里，**谁既在 A 之后又在 B 之前**，谁就是候选中间站

## 输出是什么

**候选**，不是结论。中间站 C 要成立，得满足：
- C 在教材上位于 A 和 B 之间
- C 在图谱里确实跟 A、B 有关联（不是纯粹位置上的过客）

所以这里只报「位置在中间 + 有边连着 A 或 B」的候选，
真正的边要人确认或有别的证据。

## 跟 ISSUE-13 的区别

| | ISSUE-13（extract_links.py） | 本脚本 |
|---|---|---|
| 证据 | **教材原文明说** | 教材位置 + 图谱边 |
| 强度 | 强（教材自己说的） | 弱（位置推断） |
| 适用 | 数学（生物化学没回指句） | 各科通用 |

本脚本的输出要人工过一遍才能建边，跟 ISSUE-13 那 20 条不是一回事。

## 跑法

```bash
python3 src/find_midpoints.py
python3 src/find_midpoints.py --top 30
python3 src/find_midpoints.py --out data/normalized/midpoints.json
```
"""
import argparse
import json
import pathlib
import sys
from collections import Counter, defaultdict

BASE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from order import Order   # noqa: E402

GRAPH = BASE / "data" / "normalized" / "graph.json"
SELF = BASE / "data" / "normalized" / "selfbuilt-edges.json"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=0)
    ap.add_argument("--out")
    ap.add_argument("--min-gap", type=int, default=3,
                    help="教材上至少隔几个单元才算「跳过了中间站」")
    args = ap.parse_args()

    g = json.load(open(GRAPH, encoding="utf-8"))
    sb = json.load(open(SELF, encoding="utf-8"))
    od = Order(g["nodes"], g["edges"])
    name = {n["id"]: n.get("name", "") for n in g["nodes"]}
    for n in sb["nodes"]:
        name[n["id"]] = n.get("name", "")

    # 每个节点在教材序列上的位置（全局位次，学科内）
    slot = {}
    for n in g["nodes"]:
        if n["label"] in ("Concept", "Skill", "Experiment"):
            s = od.seq_slot(n["id"])
            if s >= 0:
                slot[n["id"]] = s

    # 模型边
    model = [(e["from"], e["to"]) for e in sb["edges"]
             if e.get("source") == "model" and e["type"] == "prerequisites_for"]
    # 全部边（用来判断中间节点是否跟 A/B 有关联）
    all_edges = defaultdict(set)
    for e in g["edges"]:
        if e["type"] == "prerequisites_for":
            all_edges[e["from"]].add(e["to"])
            all_edges[e["to"]].add(e["from"])
    for e in sb["edges"]:
        if e["type"] == "prerequisites_for":
            all_edges[e["from"]].add(e["to"])
            all_edges[e["to"]].add(e["from"])

    # 位置 → 节点
    by_slot = defaultdict(list)
    for nid, s in slot.items():
        by_slot[s].append(nid)

    cands = []
    for f, t in model:
        a, b = slot.get(f), slot.get(t)
        if a is None or b is None or a >= b:
            continue
        gap = b - a
        if gap < args.min_gap:
            continue
        # 中间的节点：位置上在 (a, b) 之间，且跟 a 或 b 有边
        mids = []
        for s in range(a + 1, b):
            for nid in by_slot.get(s, ()):
                if nid in (f, t):
                    continue
                if all_edges.get(nid) and (nid in all_edges.get(f, ()) or
                                           nid in all_edges.get(t, ())):
                    mids.append(nid)
        if mids:
            cands.append({
                "from": f, "to": t,
                "fromName": name.get(f, f), "toName": name.get(t, t),
                "fromBook": od.node_of[f].get("bookZh", ""),
                "toBook": od.node_of[t].get("bookZh", ""),
                "fromSubj": od.node_of[f].get("subject", ""),
                "toSubj": od.node_of[t].get("subject", ""),
                "gap": gap,
                "mids": [{"id": m, "name": name.get(m, m),
                           "book": od.node_of[m].get("bookZh", "")} for m in mids],
            })

    # **跨学科的先修边**：数学概念 → 生物概念 这种。
    # 校验层只查了「自建边 0 跨学科」，模型边（4340 条）从没查过跨学科。
    cross = [(f, t) for f, t in model
             if od.node_of.get(f, {}).get("subject") !=
                od.node_of.get(t, {}).get("subject")]
    if cross:
        cc = Counter((od.node_of[f]["subject"], od.node_of[t]["subject"])
                     for f, t in cross)
        print(f"⚠ 模型边里跨学科的 {len(cross)} 条：")
        for k, v in cc.most_common(8):
            print(f"     {k[0]} → {k[1]}：{v}")
        for f, t in cross[:6]:
            print(f"     「{name.get(f,f)}」({od.node_of[f]['bookZh']})"
                  f" →「{name.get(t,t)}」({od.node_of[t]['bookZh']})")
        print()

    cands.sort(key=lambda c: -c["gap"])
    print("=" * 58)
    print("被跳过的中间站 · 候选")
    print("=" * 58)
    print(f"模型边 {len(model)} 条，其中教材跨度 ≥{args.min_gap} 个单元的 "
          f"{sum(1 for f,t in model if slot.get(f) is not None and slot.get(t) is not None and slot.get(t,0)-slot.get(f,0)>=args.min_gap)} 条")
    print(f"其中找到中间节点候选的 {len(cands)} 条")
    print()
    print("按学科：")
    # **按学科分，不能按 bookZh** —— 数学七上和生物七上 bookZh 都是「七上」，
    # 按 bookZh 分会把两个学科混成一堆。跨学科的边是另一回事，要单独看。
    c = Counter(x["fromSubj"] for x in cands)
    for k, v in c.most_common():
        print(f"  {k:<6} {v:5}")
    print()
    if args.top:
        print(f"跨度最大的 {min(args.top, len(cands))} 条：")
        for x in cands[:args.top]:
            print(f"  「{x['fromName']}」({x['fromBook']}) →「{x['toName']}」({x['toBook']})"
                  f"  隔 {x['gap']} 个单元")
            for m in x["mids"][:4]:
                print(f"      候选中间站：{m['name']}（{m['book']}）")
    if args.out:
        out = pathlib.Path(args.out)
        if not out.is_absolute():
            out = BASE / out
        out.parent.mkdir(parents=True, exist_ok=True)
        json.dump(cands, open(out, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
        print(f"\n明细 {len(cands)} 条已写 {out.relative_to(BASE)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
