#!/usr/bin/env python3
"""
先修边 × 教材顺序 对撞。

**这个脚本做什么**

`verify_order.py` 核的是「图谱推出来的章序对不对」。
这一个反过来问：**已经建好的先修边，跟教材顺序矛盾的有多少**。

## 为什么值得做

先修边一共 3433 条，来源四路：上游标的、模型重建的、能力底座、自建概念。
章序核对只能验「序」这一个维度 —— 序对了，边对不对照样不知道。

而教材顺序是唯一一个**独立于我们数据集**的信号：
它是人教社排版员排的，不经过任何模型。用它当弱先修约束，
能捞出一批值得人眼过一遍的边。

## ⚠️ 「模型边 0 倒挂」是构造出来的，不是发现

跑出来 model 2928 条**一条倒挂都没有**，upstream 3703 条有 188 条。
看起来像「模型重建的先修边比上游可靠得多」—— **这个结论是循环论证，别信。**

`merge_prereq.py` 的四道闸里第二道就是**册序**：

> 2 册序   低册的概念当高册知识点的前置 → 几乎必错，进队列

模型边在建的时候就已经按册序筛过一遍了，
所以它**不可能**出现跨册倒挂。这个 0 只证明闸门生效，
不证明模型比上游对。真正的信号是**上游那 188 条** ——
它们没经过任何筛选，是上游数据集原样带来的。

同样地 ISSUE-09 那 38 条冲突也在这 188 条里，
两边口径不同（那边比的是同名概念，这边比的是教材位置），
**不要把两个数字相加**。

## 这个数字该怎么读 —— 先说不该怎么读

**它不是「错了多少条」。** 教材把 A 排在 B 前面，
不等于学 B 必须先会 A。我们自己定的边界就是：

> 顺序 ≠ 先修。顺序链只是导航，诊断层只能说「哪一环最可能是空的」。

所以这里报的是「**值得看一眼**的条数」，不是错题数。
真错（像 ISSUE-09 那 38 条方向反了的）藏在这批里，
但绝大多数是「教材先介绍、后深挖」这类正常排版。

分两档是刻意的：

- **跨册倒挂** —— 先修知识出现在更晚的册。可信度高，值得先看。
  真的把前置排在后学内容后面，通常是图谱的边错了。
- **同册倒挂** —— 同一册里位置反了。可信度低。
  实测教材自己就大量这么排：小学一上「认识图形（一）」排在
  「6~10 的认识和加减法」之前，但学加减法显然需要图形感。
  拿这个当判据，一半以上会是假阳性。

## 跑法

```bash
python3 src/collide_order.py            # 汇总
python3 src/collide_order.py --top 40   # 列出最可疑的 40 条
python3 src/collide_order.py --out data/normalized/order-collide.json
```
"""
import argparse
import json
import pathlib
import sys
from collections import defaultdict

BASE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from order import Order   # noqa: E402

GRAPH = BASE / "data" / "normalized" / "graph.json"
SELF = BASE / "data" / "normalized" / "selfbuilt-edges.json"


def load():
    g = json.load(open(GRAPH, encoding="utf-8"))
    sb = json.load(open(SELF, encoding="utf-8"))
    return g, sb


def locate(od, extra_nodes, nid):
    """(册序, 章序) 全局可比的位置。取不到返回 None。

    **必须走 seq_slot 走 appears_in 上溯，不能拿 seq_key_of 直接解 id。**
    概念节点的 id 是 `math_1a_rjb_cpt1`，没有 `_chNN` 后缀，
    seq_key_of 返回 None —— 第一版就这么写的，7046 条边一条都定位不到，
    报告上写「可定位 0 条」，看着像数据空，实际是没找对地方。

    自建节点（L0 能力、derived 概念）不在 graph.json 里，
    它们本来就跨册跨阶段，不参与位置比对。
    """
    if nid in extra_nodes:
        return None
    slot = od.seq_slot(nid)
    if slot < 0:
        return None
    # units[slot] = (unit_id, subject, bookZh, name, pos, total)。
    # **位置是第 4 位的 pos，不是前面那几个** —— 第一版把
    # (unit_id, subject, bookZh) 当位置比，比的是字符串，
    # 「math_1a_rjb_ch1」>「math_1b_rjb_ch1」这类字符串序毫无意义，
    # 于是同册的「叶绿体 → 光合作用」被判成跨册倒挂。
    uid, subj, bookZh, uname, pos, total = od.units[slot]
    return (bookZh, pos)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=0, help="列出最可疑的 N 条")
    ap.add_argument("--out", help="把结果写到这个 JSON")
    args = ap.parse_args()

    g, sb = load()
    od = Order(g["nodes"], g["edges"])
    extra = {n["id"] for n in sb["nodes"]}

    # 所有边：上游的 + 自建的。自建边带 source，标清楚是哪一路。
    edges = []
    for e in g["edges"]:
        if e["type"] == "prerequisites_for":
            edges.append((e["from"], e["to"], "upstream", ""))
    for e in sb["edges"]:
        edges.append((e["from"], e["to"], e.get("source", "?"), ""))

    stat = defaultdict(lambda: {"cross": 0, "same": 0, "ok": 0, "nolocate": 0})
    rows = []
    for fr, to, src, why in edges:
        a, b = locate(od, extra, fr), locate(od, extra, to)
        if a is None or b is None:
            stat[src]["nolocate"] += 1
            continue
        if a[1] <= b[1]:
            stat[src]["ok"] += 1
            continue
        # 倒挂：先修在后学之后
        kind = "same" if a[0] == b[0] else "cross"
        stat[src][kind] += 1
        na, nb = od.node_of.get(fr, {}), od.node_of.get(to, {})
        rows.append({
            "kind": kind, "source": src,
            "from": fr, "to": to,
            "fromName": na.get("name", fr), "toName": nb.get("name", to),
            "fromBook": na.get("bookZh", na.get("book", "")),
            "toBook": nb.get("bookZh", nb.get("book", "")),
            "fromBook2": a[0], "toBook2": b[0],
            "fromPos": a[1], "toPos": b[1],
            "why": why,
        })

    # 跨册倒挂排前面：可信度最高
    rows.sort(key=lambda r: (0 if r["kind"] == "cross" else 1,
                             r["toPos"] - r["fromPos"]))

    print("=" * 56)
    print("先修边 × 教材顺序 对撞")
    print("=" * 56)
    print(f"{'来源':<10}{'边数':>8}{'顺序相符':>10}{'同册倒挂':>10}{'跨册倒挂':>10}{'定位不到':>10}")
    tot = defaultdict(int)
    for src in sorted(stat, key=lambda s: -sum(stat[s].values())):
        v = stat[src]
        n = v["ok"] + v["cross"] + v["same"] + v["nolocate"]
        print(f"{src:<10}{n:>8}{v['ok']:>10}{v['same']:>10}{v['cross']:>10}{v['nolocate']:>10}")
        for k in v:
            tot[k] += v[k]
    n_all = sum(tot.values())
    chk = tot["ok"] + tot["same"] + tot["cross"]
    print(f"\n可定位的 {chk} 条里，跨册倒挂 {tot['cross']} 条"
          f"（{tot['cross']/max(chk,1)*100:.1f}%）——这批值得人眼过一遍")
    print(f"同册倒挂 {tot['same']} 条不作为判据：教材自己就大量这么排")

    if args.top:
        print(f"\n{'跨册倒挂' if rows and rows[0]['kind']=='cross' else ''}最可疑的 {min(args.top,len(rows))} 条：")
        for r in rows[:args.top]:
            tag = "跨册" if r["kind"] == "cross" else "同册"
            print(f"  [{tag}/{r['source']}] 「{r['fromName']}」({r['fromBook']})"
                  f" →「{r['toName']}」({r['toBook']})")

    if args.out:
        out = pathlib.Path(args.out)
        if not out.is_absolute():
            out = BASE / out
        out.parent.mkdir(parents=True, exist_ok=True)
        json.dump({"stats": {k: dict(v) for k, v in stat.items()},
                   "rows": rows}, open(out, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
        print(f"\n明细已写 {out.relative_to(BASE)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
