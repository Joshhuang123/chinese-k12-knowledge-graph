#!/usr/bin/env python3
"""
从模型跑出来的名字里长出 L1 概念层规范名表。

背景：盲测 v2 跑下来，知识类前置 47% 能直接落位，剩下的一半里
最大的一块是「模型说的名字，图谱里没有 / 不这么叫」。
不是模型推理不行 —— DUP 那批（模型独立说出、数据也记了的边）
抽检 12 条全部语义站得住 —— 是两套词汇表没对齐。
对齐要有规范名，这个脚本就是长规范名的第一版。

产出三种状态，必须分开看：
  EXISTS  模型的名字对上了图谱里的某个节点      → 可以直接连边
  ALIAS   对不上，但明确是同一个概念的另一种叫法 → 登记别名，以后能连
  NEW     图谱里确实没有这个概念                → 要新建节点，人拍

判 ALIAS 还是 NEW 不靠猜：
    名字在图谱里存在，且去掉限定语后完全重合      → ALIAS
    名字在图谱里根本不存在                        → NEW
「表内乘法」和「乘法」不是 ALIAS —— 前者带限定语，缩小了概念。
这类只会落在 CONTAIN 档，由人判断，脚本不自动升级。
"""
import json
import pathlib
import re
import sys
from collections import Counter, defaultdict

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import nameindex
import order as order_mod

BASE = pathlib.Path(__file__).resolve().parent.parent
OUT_DIR = BASE / "data" / "lmm-out"
OUT = BASE / "data" / "normalized" / "l1-names.json"

# 限定语：出现在前面就把概念缩小了，不能跟后面的部分划等号。
QUALIFIER = re.compile(r"^(表内|有余|数位|个位|十位|百位|千位|万位|小数|大数|负数|真分数|假分数|带分数|最简|繁分数)")


def main():
    g = json.loads((BASE / "data" / "normalized" / "graph.json").read_text())
    nodes = {n["id"]: n for n in g["nodes"]}
    order = order_mod.Order(g["nodes"], g["edges"])
    ix = nameindex.NameIndex(g["nodes"])

    # name → [用到它的知识点]
    uses = defaultdict(list)
    tcount = Counter()
    for f in sorted(OUT_DIR.glob("math-*.json")):
        for row in json.loads(f.read_text()):
            for p in row.get("prereq", []):
                if p.get("type") == "ability":
                    continue
                uses[(p.get("name") or "").strip()].append(row["id"])
                tcount[p.get("name") or ""] += 1

    entries = []
    for name, tgts in sorted(uses.items(), key=lambda kv: -len(kv[1])):
        # 用得最多的那个目标节点的册次，作为消歧的偏好
        books = Counter(nodes[t]["book"] for t in tgts if t in nodes)
        prefer = books.most_common(1)[0][0] if books else None
        st, tid, cands, how = ix.resolve(name, prefer_book=prefer)
        if st in nameindex.AUTO and tid:
            status = "EXISTS"
        elif st == "CONTAIN":
            status = "CONTAIN"
        else:
            status = "NEW"
        e = {
            "name": name, "status": status, "hits": len(tgts),
            "targets": sorted(set(tgts))[:8],
            "books": sorted({nodes[t]["bookZh"] for t in tgts if t in nodes}),
        }
        if status == "EXISTS":
            e["node"] = tid
            e["nodeName"] = nodes[tid]["name"]
            e["nodeBook"] = nodes[tid]["bookZh"]
            e["stage"] = st
        elif status == "CONTAIN":
            e["candidates"] = [{"id": c, "name": nodes[c]["name"],
                                "book": nodes[c]["bookZh"]} for c in cands[:5]]
        else:
            e["qualified"] = bool(QUALIFIER.match(name))
        entries.append(e)

    by = Counter(e["status"] for e in entries)
    total_hits = sum(len(v) for v in uses.values())

    # 同一概念被叫成几个名字：对 EXACT/NORM 命中的，看有多少别的写法指向同一节点
    alias = defaultdict(set)
    for e in entries:
        if e["status"] == "EXISTS":
            alias[e["node"]].add(e["name"])
    multi = {k: v for k, v in alias.items() if len(v) > 1}

    OUT.write_text(json.dumps({
        "batches": len(list(OUT_DIR.glob("math-*.json"))),
        "distinct_names": len(entries), "total_hits": total_hits,
        "by_status": dict(by),
        "multi_alias_nodes": {nodes[k]["name"] + "[" + nodes[k]["bookZh"] + "]": sorted(v)
                              for k, v in multi.items()},
        "entries": entries,
    }, ensure_ascii=False, indent=1))

    print(f"═══ L1 规范名表 · {by['EXISTS'] + by['NEW'] + by['CONTAIN']} 个不同名字 ═══")
    print(f"来自 {len(list(OUT_DIR.glob('math-*.json')))} 批，"
          f"被引用 {total_hits} 次\n")
    for k in ("EXISTS", "CONTAIN", "NEW"):
        n = by[k]
        h = sum(e["hits"] for e in entries if e["status"] == k)
        print(f"  {k:<9}{n:>4} 个名字  被引用 {h:>4} 次  {100*h/total_hits:5.1f}%")

    print(f"\n同一概念被叫成不同写法的（图谱节点 → 模型给过的所有写法）：")
    for nm, vs in sorted(multi.items(), key=lambda kv: -len(kv[1]))[:12]:
        print(f"  {nm[:26]:<28} ← {'、'.join(vs)}")

    print(f"\n真·新概念（{by['NEW']} 个，被引用 {sum(e['hits'] for e in entries if e['status']=='NEW')} 次）：")
    for e in sorted([x for x in entries if x["status"] == "NEW"],
                    key=lambda x: -x["hits"])[:18]:
        q = "（带限定语）" if e.get("qualified") else ""
        print(f"  {e['hits']:>3} 次  {e['name']:<16} {sorted(e['books'])[:2]} {q}")

    print(f"\n→ {OUT.relative_to(BASE)}")


if __name__ == "__main__":
    main()
