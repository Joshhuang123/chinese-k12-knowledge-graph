#!/usr/bin/env python3
"""
全库最终统计：四科跑完之后的总账。

之前所有数字都是**中间态**，分散在好几轮对话里：
  - 数学 32 批盲测跑完时的 70% 落位率
  - 补自建边之前的 69.6% 0 前置
  - 非数学只跑完 2 批时的抽样结论（后来被证明是照抄图谱名换来的）
这个脚本把**当前真实的全库状态**一次性算出来，
每个数字都能复算，结论只以这里为准。

## 跑法

```bash
python3 src/full_stats.py
python3 src/full_stats.py --out data/normalized/full-stats.json
```
"""
import argparse
import glob
import json
import pathlib
import sys
from collections import Counter, defaultdict

BASE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from nameindex import NameIndex   # noqa: E402

GRAPH = BASE / "data" / "normalized" / "graph.json"
SELF = BASE / "data" / "normalized" / "selfbuilt-edges.json"
LMM = BASE / "data" / "lmm-out"

SUBJ_ZH = {"math": "数学", "physics": "物理",
           "chemistry": "化学", "biology": "生物"}
KEEP = {"Concept", "Skill", "Experiment"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out")
    args = ap.parse_args()

    g = json.load(open(GRAPH, encoding="utf-8"))
    sb = json.load(open(SELF, encoding="utf-8"))
    idx = NameIndex(g["nodes"])
    nb = {n["id"]: n for n in g["nodes"]}
    selfids = {n["id"] for n in sb["nodes"]}

    # ── 1. 规模 ────────────────────────────────────────────
    up = [n for n in g["nodes"] if n["label"] in KEEP]
    print("=" * 62)
    print("全库总账")
    print("=" * 62)
    print(f"上游知识点 {len(up)}（Concept+Skill+Experiment）"
          f" + 自建 {len(selfids)} = 画布 {len(up) + len(selfids)}")
    by_subj = Counter(n["subject"] for n in up)
    print("  " + "  ".join(f"{SUBJ_ZH[s]} {by_subj[s]}" for s in sorted(by_subj)))

    # ── 2. 盲测覆盖 ────────────────────────────────────────
    done = Counter()
    batches = Counter()
    for f in glob.glob(str(LMM / "*.json")):
        s = pathlib.Path(f).stem.split("-")[0]
        batches[s] += 1
        done[s] += len(json.load(open(f, encoding="utf-8")))
    print(f"\n盲测覆盖 {sum(done.values())} 个知识点 / {sum(batches.values())} 批")
    for s in sorted(batches):
        print(f"  {SUBJ_ZH[s]:<4} {done[s]:>5} 个 / {batches[s]:>3} 批")

    # ── 3. 边的来源 ────────────────────────────────────────
    src_cnt = Counter()
    for e in g["edges"]:
        if e["type"] == "prerequisites_for":
            src_cnt["上游"] += 1
    for e in sb["edges"]:
        if e["type"] == "prerequisites_for":
            src_cnt[{"model": "模型重建", "l0": "能力底座",
                     "derived": "自建概念", "intro": "教材引入路径",
                     "fix": "已修正"}.get(e.get("source"), "自建")] += 1
    print(f"\n先修边来源（共 {sum(src_cnt.values())} 条）：")
    for k, v in src_cnt.most_common():
        print(f"  {v:>6}  {k}")

    # ── 4. 0 前置 ──────────────────────────────────────────
    pre = defaultdict(set)
    for e in g["edges"]:
        if e["type"] == "prerequisites_for":
            pre[e["to"]].add(e["from"])
    for e in sb["edges"]:
        if e["type"] == "prerequisites_for":
            pre[e["to"]].add(e["from"])
    zero = [n for n in up if not pre.get(n["id"])]
    print(f"\n0 前置知识点 {len(zero)} / {len(up)} = {len(zero)/len(up)*100:.1f}%")
    z_by = Counter(n["subject"] for n in zero)
    for s in sorted(by_subj):
        print(f"  {SUBJ_ZH[s]:<4} {z_by[s]:>5} / {by_subj[s]:<5} = "
              f"{z_by[s]/by_subj[s]*100:5.1f}%")
    z_lab = Counter(n["label"] for n in zero)
    print(f"  按标签：{dict(z_lab)}")

    # ── 5. 链深 ────────────────────────────────────────────
    # 排除环后再算（Tarjan 太重，这里用迭代剪枝）
    adj = {n["id"]: set(pre.get(n["id"], ())) for n in up}
    depth = {}
    def dep(nid, stack):
        if nid in depth:
            return depth[nid]
        if nid in stack:
            return 0
        stack.add(nid)
        d = 0
        for p in adj.get(nid, ()):
            d = max(d, dep(p, stack) + 1)
        stack.discard(nid)
        depth[nid] = d
        return d
    for n in up:
        dep(n["id"], set())
    ds = [depth.get(n["id"], 0) for n in up]
    print(f"\n链深（最长前置链）：中位 {sorted(ds)[len(ds)//2]}  均值 {sum(ds)/len(ds):.2f}")
    print(f"  深度 ≥4 的 {sum(1 for d in ds if d >= 4)} 个 "
          f"({sum(1 for d in ds if d>=4)/len(ds)*100:.1f}%)")

    # ── 6. 盲测落位率（分科）────────────────────────────────
    print("\n盲测落位率（分科，EXACT/NORM/CORE/TAIL 算能自动连边）：")
    stat = defaultdict(Counter)
    for f in glob.glob(str(LMM / "*.json")):
        s = pathlib.Path(f).stem.split("-")[0]
        for it in json.load(open(f, encoding="utf-8")):
            for p in it.get("prereq", []):
                t = p.get("type")
                st, nid, c, how = idx.resolve(p.get("name"))
                stat[s][t + "_total"] += 1
                if st in ("EXACT", "NORM", "CORE", "TAIL"):
                    stat[s][t + "_hit"] += 1
                if t == "knowledge":
                    stat[s]["raw_in_graph"] += (p.get("name", "").strip()
                                                in idx.exact)
    for s in sorted(stat):
        v = stat[s]
        for t in ("knowledge", "method", "ability"):
            tot = v[t + "_total"]
            if tot:
                print(f"  {SUBJ_ZH[s]:<4} {t:<9} {v[t+'_hit']:>5}/{tot:<5} "
                      f"= {v[t+'_hit']/tot*100:5.1f}%")
        ki = v["knowledge_total"]
        if ki:
            print(f"       └ knowledge 里名字原样在图谱的占 "
                  f"{v['raw_in_graph']/ki*100:.0f}%（照抄图谱名会让落位率虚高）")

    out = {
        "upstream_nodes": len(up), "selfbuilt_nodes": len(selfids),
        "by_subject": dict(by_subj),
        "blind_batches": dict(batches), "blind_covered": dict(done),
        "edge_sources": dict(src_cnt),
        "zero_prereq": len(zero), "zero_by_subject": dict(z_by),
        "zero_by_label": dict(z_lab),
        "chain_depth_median": sorted(ds)[len(ds)//2],
        "chain_depth_mean": round(sum(ds)/len(ds), 2),
        "chain_depth_ge4": sum(1 for d in ds if d >= 4),
    }
    if args.out:
        op = pathlib.Path(args.out)
        if not op.is_absolute():
            op = BASE / op
        op.parent.mkdir(parents=True, exist_ok=True)
        json.dump(out, open(op, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
        print(f"\n已写 {op.relative_to(BASE)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
