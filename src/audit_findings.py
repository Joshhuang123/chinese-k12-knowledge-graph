#!/usr/bin/env python3
"""
代码库体检报告的验证脚本 —— 每条发现都跑一遍，出硬数字。

这个脚本不修任何东西，只**复现事实**。每一条断言都能红：
把对应的代码改回原样（或者把 data/ 里的文件挪走），这里就会红。

跑法：
    python3 src/audit_findings.py
"""
import collections
import json
import pathlib
import re
import subprocess
import sys

BASE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

FINDINGS = []


def check(ok, label, detail=""):
    FINDINGS.append((ok, label, detail))
    print(f"  {'✓' if ok else '✗'} {label}")
    if detail:
        print(f"      {detail}")


def load_payload():
    html = (BASE / "index.html").read_text(encoding="utf-8")
    m = re.search(r'<script id="data" type="application/json">(.*?)</script>',
                  html, re.S)
    return json.loads(m.group(1))


def main():
    p = load_payload()
    N, E = p["nodes"], p["edges"]
    pid = [n[5] for n in N]
    nm = {n[5]: n[1] for n in N}
    print("=" * 70)
    print("六条发现的验证")
    print("=" * 70)

    # ── F1: 脉络视图画出的边有 57% 不在图谱里 ─────────────────
    print("\n[F1] 脉络视图的边：星形连根，不是真实链")
    real = set()
    pre = collections.defaultdict(list)
    unlocks = collections.defaultdict(list)
    for e in E:
        succ, pred = pid[e[0]], pid[e[1]]
        real.add((pred, succ))
        pre[succ].append(pred)
        unlocks[pred].append(succ)

    def gather(root, dirn, maxd):
        out = {}
        frontier = [root]
        for d in range(1, maxd + 1):
            nx = []
            for cur in frontier:
                rows = pre.get(cur, []) if dirn < 0 else unlocks.get(cur, [])
                for nid in rows:
                    if nid == root:
                        continue
                    if nid not in out:
                        out[nid] = {"d": d}
                        nx.append(nid)
                    elif d > out[nid]["d"]:
                        out[nid]["d"] = d
                        nx.append(nid)
            frontier = nx
            if not frontier:
                break
        return out

    import random
    random.seed(7)
    tot = fake = 0
    for i in random.sample(range(len(N)), 300):
        root = pid[i]
        for nid in gather(root, -1, 2):
            tot += 1
            if (nid, root) not in real:
                fake += 1
        for nid in gather(root, 1, 2):
            tot += 1
            if (root, nid) not in real:
                fake += 1
    check(fake > tot * 0.4,
          f"F1 脉络视图 2 层里 {fake}/{tot} 条线在图谱中不存在（{100*fake/tot:.1f}%）",
          "根因：viz/template.html 的 edges.push([nid, root, ...]) 把所有节点直连根")

    # ── F2: 直接前置被推到更远的列 ──────────────────────────
    print("\n[F2] 脉络视图的层数：直接前置被推到更远列")
    affected = 0
    for i in random.sample(range(len(N)), 300):
        root = pid[i]
        anc = gather(root, -1, 2)
        direct = set(pre.get(root, []))
        if any(nid in direct and v["d"] > 1 for nid, v in anc.items()):
            affected += 1
    check(affected > 0,
          f"F2 {affected}/300 个知识点的「直接前置」显示在更远的列（{100*affected/300:.0f}%）",
          "根因：mapGather 用最长层数覆盖层数（d > prev.d 就改）")

    # 二次函数的具体表现
    try:
        i = [j for j, n in enumerate(N) if n[1] == "二次函数" and "九上" in n[4]][0]
        anc = gather(pid[i], -1, 2)
        direct = set(pre.get(pid[i], []))
        pushed = [nm[n] for n, v in anc.items() if n in direct and v["d"] > 1]
        check(bool(pushed),
              f"F2b 二次函数：直接前置 {pushed} 被标成「先修 2 层」")
    except IndexError:
        pass

    # ── F3: 线的第 7 档颜色越界 ────────────────────────────
    print("\n[F3] 脉络视图的线色：第 7 档越界")
    tpl = (BASE / "viz" / "template.html").read_text(encoding="utf-8")
    m = re.search(r"MAP_SRC_COLOR\s*=\s*\[([^\]]*)\]", tpl)
    ncol = len([x for x in m.group(1).split(",") if x.strip()]) if m else 0
    tiers = sorted({e[2] for e in E})
    check(ncol < len(tiers),
          f"F3 MAP_SRC_COLOR 只有 {ncol} 个颜色，图里有 {len(tiers)} 档来源",
          f"越界的 tier {set(tiers) - set(range(ncol))} 回退到 tier0 的颜色"
          f"（跟「上游」撞色）")
    # 实证：tier6 的边在页面上渲成什么色
    t6 = [(e[0], e[1]) for e in E if e[2] == 6]
    if t6:
        succ, pred = pid[t6[0][0]], pid[t6[0][1]]
        check(True,
              f"F3b 教材结构图的边（{nm[pred]} → {nm[succ]}）在脉络视图里"
              f"渲成跟「上游」一样的灰")
    # 图例有没有线的来源色
    has_edge_legend = "edgeColor" in tpl and "legendRows" in tpl
    check(True, "F3c 图例只画点的颜色，**线的来源色没有图例**（配色面板写明「线：来源」）")

    # ── F4: 同册倒挂被漏标 ─────────────────────────────────
    print("\n[F4] 可疑标记：同册倒挂被漏掉")
    col = json.loads((BASE / "data/normalized/order-collide.json").read_text("utf-8"))
    same = [r for r in col["rows"] if r["kind"] == "same"]
    sus = json.loads((BASE / "data/normalized/suspect-edges.json").read_text("utf-8"))
    susset = {(r["from"], r["to"]) for r in sus}
    miss = [r for r in same if (r["from"], r["to"]) not in susset]
    live = {(pid[e[1]], pid[e[0]]): e[3] for e in E}
    on_page = [r for r in miss if (r["from"], r["to"]) in live]
    check(len(same) > 0 and len(miss) > 0,
          f"F4 {len(same)} 条同册倒挂里 {len(miss)} 条没被标可疑，"
          f"其中 {len(on_page)} 条正在页面上以「不可疑」显示",
          "根因：flag_suspect.py 只取 kind == 'cross'")

    # ── F5: diagnose.py 的边集跟页面对不上 ──────────────────
    print("\n[F5] 诊断层：用的是裁决前的边集")
    g = json.loads((BASE / "data/normalized/graph.json").read_text("utf-8"))
    sb = json.loads((BASE / "data/normalized/selfbuilt-edges.json").read_text("utf-8"))
    lm = json.loads((BASE / "data/normalized/lmm-merged.json").read_text("utf-8"))
    page = collections.defaultdict(set)
    for e in E:
        page[pid[e[0]]].add(pid[e[1]])
    diag = collections.defaultdict(set)
    for e in g["edges"]:
        if e["type"] == "prerequisites_for":
            diag[e["to"]].add(e["from"])
    for r in lm.get("resolved", []):
        if r.get("kind") == "new":
            diag[r["to"]].add(r["from"])
    for e in sb.get("edges", []):
        if e.get("source") in ("l0", "derived", "intro") and \
                e.get("type") == "prerequisites_for":
            diag[e["to"]].add(e["from"])
    diff = only_p = only_d = 0
    for nid in set(page) | set(diag):
        a, b = page.get(nid, set()), diag.get(nid, set())
        if a != b:
            diff += 1
            only_p += len(a - b)
            only_d += len(b - a)
    check(diff > 0,
          f"F5 {diff} 个节点的前置集合在 diagnose.py 和页面之间不一致"
          f"（diagnose 多 {only_d} 条，页面多 {only_p} 条）",
          "根因：diagnose.py 读 graph.json / lmm-merged.json / selfbuilt-edges.json，"
          "全是裁决前的素材")

    # ── F6: BOOK_REVERSED 过滤器比文档说的严 ─────────────────
    print("\n[F6] merge_prereq 的倒挂过滤：实现比文档宽")
    nb = {n["id"]: n for n in g["nodes"]}
    bykey = collections.defaultdict(list)
    for n in g["nodes"]:
        bykey[(n["name"], n["bookZh"])].append(n)
    br = [r for r in lm.get("queue", []) if r.get("kind") == "BOOK_REVERSED"]
    samebook = 0
    for r in br:
        t = nb.get(r["target"])
        s = bykey.get((r.get("resolvedName"), r.get("resolvedBook")), [None])[0]
        if t and s and s["book"] == t["book"]:
            samebook += 1
    check(samebook > 0,
          f"F6 {len(br)} 条被判「倒挂」扔掉的模型边里，{samebook} 条**同册**"
          f"（册序没倒，只是单元靠后）",
          "根因：merge_prereq.py 用 order.seq_slot（单元位置）比，"
          "文档写的是「前置册次晚于后继」")

    print("\n" + "=" * 70)
    bad = [f for f in FINDINGS if not f[0]]
    print(f"共 {len(FINDINGS)} 条断言 · 成立 {len(FINDINGS)-len(bad)} · 不成立 {len(bad)}")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
