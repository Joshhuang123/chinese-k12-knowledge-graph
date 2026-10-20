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
INDEX = BASE / "index.html"

SUBJ_ZH = {"math": "数学", "physics": "物理",
           "chemistry": "化学", "biology": "生物"}
KEEP = {"Concept", "Skill", "Experiment"}

# 页面上的 7 档来源徽标（跟 build_viz.py 的 SRC_ZH 一致）
TIER_ZH = {0: "上游", 1: "模型重建", 2: "能力底座", 3: "自建概念",
           4: "教材引入路径", 5: "已修正", 6: "教材结构图"}


def load_payload():
    """读成品 index.html 里嵌的 payload。

    **为什么总账要从 payload 算，而不是从 graph.json + selfbuilt-edges.json 算：**
    那两个文件是**裁决前**的素材。build_viz 还会做两件事：
      1. 按来源优先级裁掉 247 组方向冲突的边（每组丢 1 条）
      2. 环检测剪掉 56 条
    所以素材里的 16,631 条 ≠ 用户看到的 16,320 条。
    链深、0 前置率这些**只在成品图上算得准** ——
    素材里还挂着 247 条方向相反的边，算出来的深度是假的。
    """
    import re
    html = INDEX.read_text(encoding="utf-8")
    m = re.search(r'<script id="data" type="application/json">(.*?)</script>',
                  html, re.S)
    if not m:
        raise SystemExit("在 index.html 里找不到 payload —— 先跑 python3 src/build_viz.py")
    return json.loads(m.group(1))


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

    # ── 3. 边的来源（**按成品 payload 算**）──────────────────
    # payload 的边格式：[后继下标, 先修下标, 来源档位, 可疑档位]
    payload = load_payload()
    pnodes = payload["nodes"]
    # 边的 [0]/[1] 是**节点下标**，不是 id —— 下标取 id 要走 pnodes
    pname = [n[5] for n in pnodes]
    src_cnt = Counter()
    for e in payload["edges"]:
        src_cnt[TIER_ZH.get(e[2], "?")] += 1
    print(f"\n先修边来源（共 {sum(src_cnt.values())} 条，**成品图口径**）：")
    for k, v in src_cnt.most_common():
        print(f"  {v:>6}  {k}")

    # ── 4. 0 前置 ──────────────────────────────────────────
    pre = defaultdict(set)
    for e in payload["edges"]:
        pre[pname[e[0]]].add(pname[e[1]])
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
    # **ability 类要用 L0 别名表算，不能用知识点索引。**
    # L0 能力节点**不在 graph.json 里** —— 它们是自建层（selfbuilt-edges.json）。
    # 拿 ability 表述去查知识点索引，命中必然是 0，
    # 于是报出来「ability 落位率 0~11%」，看着像能力层完全没建起来。
    # 真实口径是「能不能挂到某个 L0 能力桶上」——那个是 88%。
    #
    # 这个指标一开始是错的，而且**错得很有说服力**：
    # 「能力层只接住了 8%」听起来像结论，其实只是查错了表。
    l0 = json.load(open(BASE / "data" / "l0-abilities.json", encoding="utf-8"))
    alias2l0 = {}
    for a in l0["abilities"]:
        for x in [a.get("name")] + list(a.get("aliases") or []):
            if x:
                alias2l0[x.strip()] = a["id"]
    stat = defaultdict(Counter)
    for f in glob.glob(str(LMM / "*.json")):
        s = pathlib.Path(f).stem.split("-")[0]
        for it in json.load(open(f, encoding="utf-8")):
            for p in it.get("prereq", []):
                t = p.get("type")
                if t == "ability":
                    # 能力类：查 L0 别名表
                    stat[s][t + "_total"] += 1
                    if p.get("name", "").strip() in alias2l0:
                        stat[s][t + "_hit"] += 1
                    continue
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
        # **成品图口径的边数。** 之前只有 edge_sources 的分档，没有总数 ——
        # 体检脚本只能去 JSON 文本里搜数字，搜不到就报错（假警报）。
        "total_edges": sum(src_cnt.values()),
        "canvas_nodes": len(payload["nodes"]),
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
