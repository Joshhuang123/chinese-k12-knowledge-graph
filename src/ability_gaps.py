#!/usr/bin/env python3
"""
模型替我们指出来的**知识覆盖缺口**。

## 为什么有这个东西

盲测的时候，模型对每个知识点说出它认为的先修。
其中 `type=ability` 的那些，**大部分其实是知识**，只是模型归类归错了
（「距离」「传感器」「小磁针」「光屏」「接触面」……）。

但这不全是模型的错 —— **图谱里真的没有这些概念**。
模型说「要会光屏才能做 XX」，而图谱里压根没有「光屏」这个节点。

**换句话说：模型的能力类输出，是一份免费的覆盖缺口清单。**
它比结构图挖出来的 21 处更细，因为它覆盖了四科 8,590 个知识点。

## 三类落不进的，分别怎么处理

| 类别 | 判据 | 处置 |
|---|---|---|
| **能挂到 L0 桶** | 在 `l0-abilities.json` 的别名表里 | 已接住 |
| **图谱里有对应知识点** | 知识点索引能解析 | 模型归类归错了，<br>`merge_prereq` 会回退成知识边处理 |
| **图谱里也没有** | 两边都接不住 | **真·覆盖缺口** —— 就是这份清单 |

第三类分两种：
- **该进 L0 的**（描述一种心智能力，如「归纳推理」「记录数据」）→ 补进 L0 别名表
- **该补进图谱的**（是一个具体概念，如「光屏」「传感器」「压强计」）→ 补成知识点

本脚本把两者的候选都列出来，但**只标出来，不自动建节点** ——
建教材节点要有教材出处，不能凭模型的一个词就建。

## 跑法

```bash
python3 src/ability_gaps.py
python3 src/ability_gaps.py --out data/normalized/ability-gaps.json
```
"""
import argparse
import collections
import glob
import json
import pathlib
import sys

BASE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from nameindex import NameIndex   # noqa: E402

GRAPH = BASE / "data" / "normalized" / "graph.json"
L0 = BASE / "data" / "l0-abilities.json"
LMM = BASE / "data" / "lmm-out"

SUBJ_ZH = {"math": "数学", "physics": "物理",
           "chemistry": "化学", "biology": "生物"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out")
    args = ap.parse_args()

    g = json.load(open(GRAPH, encoding="utf-8"))
    idx = NameIndex(g["nodes"])
    l0 = json.load(open(L0, encoding="utf-8"))
    alias2l0 = {}
    for a in l0["abilities"]:
        for x in [a.get("name")] + list(a.get("aliases") or []):
            if x:
                alias2l0[x.strip()] = a["id"]

    # 模型说的 ability 表述：按说法聚合，记住出现在哪科、哪些知识点上
    cnt = collections.Counter()
    where = collections.defaultdict(list)
    subjects = collections.defaultdict(collections.Counter)
    for f in sorted(glob.glob(str(LMM / "*.json"))):
        s = pathlib.Path(f).stem.split("-")[0]
        for row in json.load(open(f, encoding="utf-8")):
            nm = (row.get("prereq") or [])
            for p in nm:
                if p.get("type") != "ability":
                    continue
                w = p.get("name", "").strip()
                if not w:
                    continue
                cnt[w] += 1
                subjects[w][s] += 1
                if len(where[w]) < 6:
                    where[w].append(row.get("id", ""))

    rows = []
    for w, n in cnt.most_common():
        if w in alias2l0:
            kind, how = "l0", alias2l0[w]
        else:
            st, nid, c, how2 = idx.resolve(w)
            if st in ("EXACT", "NORM", "CORE", "TAIL"):
                kind, how = "knowledge-mislabel", st
            else:
                kind, how = "gap", "MISS"
        rows.append({
            "name": w, "count": n, "kind": kind, "how": how,
            "subjects": dict(subjects[w]),
            "askedBy": where[w],
        })

    gaps = [r for r in rows if r["kind"] == "gap"]
    mis = [r for r in rows if r["kind"] == "knowledge-mislabel"]
    l0ok = [r for r in rows if r["kind"] == "l0"]
    tot = sum(cnt.values())

    print("=" * 62)
    print("模型能力类输出 → 落位情况")
    print("=" * 62)
    print(f"模型说的能力类前置 {tot} 次，{len(rows)} 种说法")
    print(f"  能挂到 L0 能力桶      {sum(r['count'] for r in l0ok):>5} 次 "
          f"（{100*sum(r['count'] for r in l0ok)/tot:.1f}%）· {len(l0ok)} 种")
    print(f"  图谱里有对应知识点      {sum(r['count'] for r in mis):>5} 次 "
          f"（{100*sum(r['count'] for r in mis)/tot:.1f}%）· {len(mis)} 种"
          f"  ← 模型归类归错了")
    print(f"  **图谱里也没有**        {sum(r['count'] for r in gaps):>5} 次 "
          f"（{100*sum(r['count'] for r in gaps)/tot:.1f}%）· {len(gaps)} 种"
          f"  ← 真·覆盖缺口")
    print()
    bysub = collections.Counter()
    for r in gaps:
        for s, c in r["subjects"].items():
            bysub[s] += c
    print("真缺口的分科分布：" + "  ".join(
        f"{SUBJ_ZH.get(s, s)} {c}" for s, c in bysub.most_common()))
    print()
    print("缺口里出现最多的 30 个：")
    for r in gaps[:30]:
        subs = "、".join(SUBJ_ZH.get(s, s) for s in r["subjects"])
        print(f"  {r['count']:>3}  {r['name']:<16} {subs}")
    print()
    print("按学科展开（各科自己最缺的）：")
    for s in sorted({s for r in gaps for s in r["subjects"]}):
        sub = [r for r in gaps if s in r["subjects"]]
        sub.sort(key=lambda r: -r["subjects"][s])
        print(f"  {SUBJ_ZH.get(s, s)}：" + "、".join(
            f"{r['name']}({r['subjects'][s]})" for r in sub[:14]))

    if args.out:
        out = pathlib.Path(args.out)
        if not out.is_absolute():
            out = BASE / out
        out.parent.mkdir(parents=True, exist_ok=True)
        json.dump({
            "_comment": ("模型能力类输出的落位情况。第三类 kind=gap 是"
                         "**图谱里真的没有的概念** —— 模型替我们指出来的覆盖缺口。"),
            "totals": {"says": tot, "distinct": len(rows),
                       "l0": sum(r["count"] for r in l0ok),
                       "knowledge_mislabel": sum(r["count"] for r in mis),
                       "gap": sum(r["count"] for r in gaps)},
            "rows": rows,
        }, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print(f"\n明细 {len(rows)} 条已写 {out.relative_to(BASE)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
