#!/usr/bin/env python3
"""
把每一个数学知识点机械地过一遍，回答一个问题：

    图谱现在能不能对这个知识点「定位」？

为什么先做这个，不先上模型：
  diagnose.py 只能沿着**已有的先修边**往回走。数据里 66% 的数学知识点
  零先修，模型那 32 批补出来的边如果没有统一标尺，就只是 1898 份
  互不可比的自由文本。先把「当前状态」量出来，模型结果才有地方落。

本脚本只读，不写 data/raw/，不修改图谱。输出：
    data/normalized/sweep-math.json   每个知识点一行的机械体检记录
    stdout                           分布统计 + 最严重的一批

四种定位能力，按从强到弱：
    LOCATED   能沿先修边走到至少一个根（有人教它）
    ANCHORED  自己没先修，但教材上排在它前面的东西教它（章序）
    ISOLATED  既没先修，教材里也没人能教它 —— 图谱对它无话可说
    ORPHAN    有先修但全是假的（来自后面的册 / 跨学科跳跃 / 无证据）
"""
import json
import pathlib
import sys
from collections import defaultdict, Counter

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import books
import order as order_mod

BASE = pathlib.Path(__file__).resolve().parent.parent
GRAPH = BASE / "data" / "normalized" / "graph.json"
OUT = BASE / "data" / "normalized" / "sweep-math.json"

SUBJ = sys.argv[1] if len(sys.argv) > 1 else "math"
PREREQ_TYPES = {"prerequisites_for"}
# 章级 leads_to：不是知识点的先修，是教材里「这一章接着那一章」
CHAPTER_HINT = {"leads_to"}


def evidence_text(e):
    """77 条边的 evidence 是 dict 不是字符串（known-issues 记过）。
    这里不当成「有证据」—— 一个读不出字的 evidence 等于没有。"""
    v = e.get("evidence")
    if isinstance(v, dict):
        return ""
    return (v or "").strip()


def main():
    g = json.loads(GRAPH.read_text())
    nodes = {n["id"]: n for n in g["nodes"]}
    rank = books.RANK
    order = order_mod.Order(g["nodes"], g["edges"])

    pre = defaultdict(list)   # node -> [(other, edge)]
    post = defaultdict(list)
    for e in g["edges"]:
        a, b, t = e["from"], e["to"], e["type"]
        if t in PREREQ_TYPES:
            pre[b].append((a, e))
            post[a].append((b, e))
        elif t in CHAPTER_HINT:
            pre[b].append((a, e))
            post[a].append((b, e))

    def depth_of(nid, _seen=None):
        """最长先修链。数据里有环（ISSUE-08），用递归栈截断。"""
        seen = _seen or set()
        if nid in seen:
            return 0
        best = 0
        for other, _ in pre.get(nid, ()):
            best = max(best, 1 + depth_of(other, seen | {nid}))
        return best

    rows = []
    buckets = Counter()
    for n in g["nodes"]:
        if n["subject"] != SUBJ:
            continue
        nid = n["id"]
        ps = pre.get(nid, [])
        qs = post.get(nid, [])
        d = depth_of(nid)
        slot = order.seq_slot(nid)
        pos, total = order.seq_pos(nid)
        flags = []

        # 边是否可信
        for other, e in ps:
            ob = nodes.get(other)
            if ob is None:
                flags.append("DANGLING")
                continue
            if rank[ob["book"]] > rank[n["book"]]:
                flags.append("BOOK_REVERSED")     # 被后面的东西教
            elif ob["subject"] != n["subject"]:
                flags.append("CROSS_SUBJECT")     # 跨学科先修，data 里 0 例，出现即异常
            ev = evidence_text(e)
            if not ev:
                flags.append("NO_EVIDENCE")
            elif isinstance(e.get("evidence"), dict):
                flags.append("EVIDENCE_IS_DICT")
            oslot = order.seq_slot(other)
            if slot >= 0 and oslot >= 0 and oslot > slot:
                flags.append("OUT_OF_ORDER")      # 教材顺序在后，却算先修

        if not ps:
            buckets["NO_PREREQ"] += 1
            # 没有任何先修边。只知道它自己的教材位置不算定位 ——
            # 至少要知道「它所在的章，得先走过哪一章」。
            if any(order.book_order(nid)):
                kind = "ANCHORED"
            else:
                kind = "ISOLATED"
        else:
            kind = "LOCATED" if d >= 1 else "ORPHAN"

        if not qs and not ps:
            kind = "ISOLATED"

        buckets[kind] += 1
        for f in set(flags):
            buckets["flag:" + f] += 1

        rows.append({
            "id": nid,
            "name": n["name"],
            "label": n["label"],
            "book": n["book"],
            "bookZh": n["bookZh"],
            "seq": slot,                      # 教材序列全局下标，-1 = 定不出
            "seqPos": pos,                    # 学科内位次
            "seqPct": round(100 * pos / total, 1) if pos is not None else None,
            "unit": [order.units[slot][4], order.units[slot][5], order.units[slot][3]]
                    if slot >= 0 else None,
            "depth": d,
            "preN": len(ps),
            "postN": len(qs),
            "preNames": [nodes.get(o, {}).get("name", "?") for o, _ in ps][:6],
            "flags": sorted(set(flags)),
            "kind": kind,
        })

    rows.sort(key=lambda r: (r["seq"] if r["seq"] >= 0 else 10**9, r["id"]))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(
        {"subject": SUBJ, "total": len(rows), "buckets": dict(buckets), "rows": rows},
        ensure_ascii=False, indent=1))

    # ── 报告 ──
    n = len(rows)
    print(f"═══ {SUBJ} 机械全扫 · {n} 个节点 ═══\n")
    print("定位能力分布：")
    for k in ("LOCATED", "ANCHORED", "ISOLATED", "ORPHAN"):
        if buckets.get(k):
            print(f"  {k:<9} {buckets[k]:>5}  {100*buckets[k]/n:5.1f}%")
    print("\n异常标记：")
    for k, v in sorted(buckets.items()):
        if k.startswith("flag:") and v:
            print(f"  {k[5:]:<16} {v:>5}")

    d_hist = Counter(r["depth"] for r in rows)
    print("\n链深分布（最长先修链层数）：")
    for d in sorted(d_hist):
        print(f"  {d} 层  {d_hist[d]:>5}  {100*d_hist[d]/n:5.1f}%")

    seqs = [r for r in rows if r["seq"] >= 0]
    print(f"\n能定出教材位置的：{len(seqs)}/{n} = {100*len(seqs)/n:.1f}%")

    # 习题节点本来就不该有前置（它是练习不是知识），混进来会把
    # 「图谱定位不了什么」说得比实际更严重。分开报。
    print("\n按 label 拆开看：")
    print(f"  {'label':<12}{'个数':>6}{'LOCATED':>9}{'ANCHORED':>10}{'ISOLATED':>10}{'有教材位':>9}")
    for lab in sorted({r["label"] for r in rows}):
        rs = [r for r in rows if r["label"] == lab]
        c = Counter(r["kind"] for r in rs)
        print(f"  {lab:<12}{len(rs):>6}{c['LOCATED']:>9}{c['ANCHORED']:>10}"
              f"{c['ISOLATED']:>10}{sum(1 for r in rs if r['seq'] >= 0):>9}")

    cs = [r for r in rows if r["label"] in ("Concept", "Skill")]
    print("\n按册拆开（只算 Concept+Skill，习题不算）：")
    print(f"  {'册':<8}{'知识点':>7}{'能定位':>7}{'占比':>7}{'平均链深':>9}{'≥2层':>7}")
    for bk in sorted({r["book"] for r in cs}, key=lambda b: books.RANK[b]):
        rs = [r for r in cs if r["book"] == bk]
        loc = sum(1 for r in rs if r["kind"] in ("LOCATED", "ANCHORED"))
        d2 = sum(1 for r in rs if r["depth"] >= 2)
        avg = sum(r["depth"] for r in rs) / len(rs)
        print(f"  {rs[0]['bookZh']:<8}{len(rs):>7}{loc:>7}{100*loc/len(rs):>6.0f}%"
              f"{avg:>9.2f}{d2:>7}")

    iso = [r for r in cs if r["kind"] == "ISOLATED"]
    print(f"\nConcept/Skill 里完全孤立的 {len(iso)} 个，前 25：")
    for r in iso[:25]:
        print(f"  {r['bookZh']}  {r['name'][:26]:<28} {r['id']}")

    # 最该先补的：有教材位置、有名字、却完全孤立 —— 这些是页面上
    # 用户点进去只能看到「数据里没记前置」的点。
    top = [r for r in iso if r["seqPct"] is not None]
    top.sort(key=lambda r: r["seqPct"])
    print(f"\n按教材顺序，中段最先塌掉的位置（每 10% 一格）：")
    for i in range(10):
        lo, hi = i * 10, (i + 1) * 10
        cell = [r for r in cs if r["seqPct"] is not None and lo <= r["seqPct"] < hi]
        if not cell:
            continue
        loc = sum(1 for r in cell if r["kind"] in ("LOCATED", "ANCHORED"))
        print(f"  {lo:>3}–{hi:>3}%  {len(cell):>4} 个知识点  能定位 {loc:>4} "
              f"({100*loc/len(cell):3.0f}%)")

    print(f"\n→ {OUT.relative_to(BASE)}")


if __name__ == "__main__":
    main()
