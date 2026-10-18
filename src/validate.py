#!/usr/bin/env python3
"""
中文课程知识图谱 — 校验层

这张图谱要在科普视频里指向给观众，所以它自己必须先经得起查。
这个脚本就是那个「查」的动作。

设计原则（来自对 withmarbleapp/os-taxonomy 的三个 issue 的复盘）：

  硬错误（必须为零，否则数据不可用）
    1. 先修边成环        —— 环意味着「学 A 前要先会 B，学 B 前要先会 A」
    2. 悬空边            —— 边指向不存在的节点
    3. id 重复 / 空名

  提示（不是错误，列出来供人工核对）
    4. 册次倒挂          —— 先修知识首次出现在更晚的册次。
                            「毫米」(3a) → 「厘米」(2a) 是对的：
                            教材册次不是难度排序，教材会回顾旧概念。
                            真正该测的是成环，不是册次。

跑:  python3 src/validate.py [--json]
"""
import json
import pathlib
import sys
from collections import Counter, defaultdict

BASE = pathlib.Path(__file__).resolve().parent.parent
GRAPH = BASE / "data" / "normalized" / "graph.json"
REPORT = BASE / "data" / "normalized" / "validation.json"

STAGE_ZH = {"小学": "小学", "初中": "初中", "高中": "高中"}


def find_cycles(nodes_by_id, prereq):
    """先修边必须构成 DAG。用三色标记。返回环列表（每条一个可读路径）。"""
    color = {}
    cycles = []

    def dfs(u, path):
        color[u] = 1                      # 1 = 在栈中
        for v in prereq.get(u, ()):
            if color.get(v) == 1:
                cycles.append(path + [u, v])
            elif color.get(v) is None:
                dfs(v, path + [u])
        color[u] = 2                      # 2 = 已完成

    sys.setrecursionlimit(100000)
    for nid in nodes_by_id:
        if color.get(nid) is None:
            dfs(nid, [])
    return cycles


def name_of(nid, nodes_by_id):
    n = nodes_by_id.get(nid)
    return f"{n['name']}({n['bookZh']})" if n else nid


def main():
    g = json.load(open(GRAPH, encoding="utf-8"))
    nodes, edges = g["nodes"], g["edges"]
    nodes_by_id = {n["id"]: n for n in nodes}

    errors, warnings, info = [], [], []

    # ── 硬错误 1：先修边成环 ──
    prereq = defaultdict(list)
    for e in edges:
        if e["type"] == "prerequisites_for":
            prereq[e["from"]].append(e["to"])
    cycles = find_cycles(nodes_by_id, prereq)
    if cycles:
        for c in cycles[:20]:
            errors.append(("PREREQ_CYCLE",
                           " → ".join(name_of(x, nodes_by_id) for x in c)))
    info.append(("PREREQ_DAG", f"先修边 {sum(len(v) for v in prereq.values())} 条，环 {len(cycles)} 个"))

    # ── 硬错误 1b：is_a（属种关系）成环 ──
    # is_a 是严格层级：A 是 B 的种，那 B 就不可能是 A 的种，成环必错。
    # 原来只查 prerequisites_for，漏掉了这一类。实测真的漏了一个：
    # 元素周期表 → 元素周期律 → 元素周期系 → 元素周期表。
    #
    # deliberately 不查 relates_to：它是「相关」语义，本身对称，
    # 成环没有语义错误（实测 17 个环，全是这种）。
    isA = defaultdict(list)
    for e in edges:
        if e["type"] == "is_a":
            isA[e["from"]].append(e["to"])
    isa_cycles = find_cycles(nodes_by_id, isA)
    if isa_cycles:
        for c in isa_cycles[:20]:
            errors.append(("IS_A_CYCLE",
                           " → ".join(name_of(x, nodes_by_id) for x in c)))
    info.append(("IS_A_DAG", f"属种边 {sum(len(v) for v in isA.values())} 条，环 {len(isa_cycles)} 个"))

    # ── 硬错误 2：悬空边 ──
    dangling = [e for e in edges if e["from"] not in nodes_by_id or e["to"] not in nodes_by_id]
    if dangling:
        for e in dangling[:20]:
            errors.append(("DANGLING_EDGE", f"{e['from']} → {e['to']}"))
    info.append(("DANGLING", f"{len(dangling)} 条边指向不存在的节点"))

    # ── 硬错误 3：id 重复 / 空名 ──
    dup = [i for i, c in Counter(n["id"] for n in nodes).items() if c > 1]
    for i in dup[:20]:
        errors.append(("DUP_ID", i))
    unnamed = [n for n in nodes if not n["name"].strip()]
    for n in unnamed[:20]:
        errors.append(("EMPTY_NAME", f"{n['id']} ({n['label']})"))
    info.append(("DUP_ID", f"{len(dup)} 个重复 id"))
    info.append(("EMPTY_NAME", f"{len(unnamed)} 个空名节点"))

    # ── 硬错误 4：自环 ──
    selfloop = [e for e in edges if e["from"] == e["to"]]
    for e in selfloop[:20]:
        errors.append(("SELF_LOOP", f"{e['from']}"))
    info.append(("SELF_LOOP", f"{len(selfloop)} 条"))

    # ── 提示 1：册次倒挂（不是错误）──
    pre_edges = [e for e in edges if e["type"] == "prerequisites_for"]
    rev = [e for e in pre_edges if e["bookReversed"]]
    for e in rev[:30]:
        warnings.append(("BOOK_REVERSED",
                         f"{name_of(e['from'], nodes_by_id)} → {name_of(e['to'], nodes_by_id)}"))
    info.append(("BOOK_REVERSED", f"{len(rev)}/{len(pre_edges)} 条先修边的先修方册次更晚"))

    # ── 提示 2：先修边缺出处 ──
    no_ev = [e for e in pre_edges if not e["evidence"]]
    info.append(("PREREQ_NO_EVIDENCE", f"{len(no_ev)}/{len(pre_edges)} 条先修边没有教材原文引用"))

    # ── 提示 3：跨册先修边占比 ──
    cross = [e for e in pre_edges if e["crossBook"]]
    info.append(("PREREQ_CROSSBOOK", f"{len(cross)}/{len(pre_edges)} 条跨册"))

    # ── 信息：各学段的学科覆盖 ──
    cover = defaultdict(set)
    for n in nodes:
        cover[n["stage"]].add(n["subjectZh"])
    for stage in ["小学", "初中", "高中"]:
        subs = cover.get(stage, set())
        cnt = sum(1 for n in nodes if n["stage"] == stage and n["label"] in ("Concept", "Skill"))
        info.append((f"COVER_{stage}", f"{len(subs)} 科（{'/'.join(sorted(subs)) or '无'}），知识点+技能 {cnt} 个"))

    # ── 信息：枢纽 ──
    fanin = Counter()
    for e in pre_edges:
        fanin[e["to"]] += 1
    top = ", ".join(f"{name_of(k, nodes_by_id)}×{v}" for k, v in fanin.most_common(5))
    info.append(("TOP_FANIN", f"最吃紧的 5 个知识点：{top}"))

    # ── 输出 ──
    out = {"errors": [{"code": c, "detail": d} for c, d in errors],
           "warnings": [{"code": c, "detail": d} for c, d in warnings],
           "info": [{"code": c, "detail": d} for c, d in info],
           "passed": len(errors) == 0}

    if "--json" in sys.argv:
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0 if out["passed"] else 1

    W = 78
    print("=" * W)
    print(f"中文课程知识图谱 · 校验   （{len(nodes)} 节点 / {len(edges)} 边）")
    print("=" * W)

    print("\n【硬错误】")
    if not errors:
        print("  ✓ 全部通过")
    else:
        for c, d in errors:
            print(f"  ✗ {c:<22} {d}")
        if len(errors) > 20:
            print(f"  … 还有 {len(errors)-20} 条")

    print("\n【提示 · 不是错误，供人工核对】")
    if not warnings:
        print("  （无）")
    else:
        for c, d in warnings:
            print(f"  · {c:<22} {d}")
        if len(warnings) > 10:
            print(f"  … 还有 {len(warnings)-10} 条")

    print("\n【指标】")
    for c, d in info:
        print(f"  {c:<22} {d}")

    print("\n" + "=" * W)
    print("结论: " + ("✓ 通过，可以对外发布" if out["passed"] else "✗ 有硬错误，先修"))
    print("=" * W)

    REPORT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if out["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
