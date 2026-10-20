#!/usr/bin/env python3
"""
把自建的三层东西合成一份边集，交给 build_viz 打进页面。

三层分开、来源分开标，是这套东西能不能被信任的前提：

    L0  能力底座   16 个节点，data/l0-abilities.json 手工定
                   不属于任何一册，任何一册都考它
    L1  自建概念   模型跑出来、图谱里确实没有的概念（画图表示 / 满十进一…）
                   独立成节点，打 source=derived，**不并进上游节点集**
    L1' 模型边     2,970 条已解析到具体节点的先修边，打 source=model

为什么 derived 不并进上游节点集：
  上游 K12-KGraph 是别人的数据（CC BY-NC-SA）。我们加进去的东西如果混在
  同一个 id 空间里，以后分不清哪些是它的、哪些是我们猜的；它以后补上
  「画图表示」时我们就有了两个 id，诊断会给出两条不一致的答案。
  混在一起的代价是永久的，分开的代价只是多一张映射表。

输出 data/normalized/selfbuilt-edges.json，build_viz 读它。
"""
import json
import pathlib
import sys
from collections import Counter, defaultdict

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import books

BASE = pathlib.Path(__file__).resolve().parent.parent
GRAPH = BASE / "data" / "normalized" / "graph.json"
L0_FILE = BASE / "data" / "l0-abilities.json"
MERGED = BASE / "data" / "normalized" / "lmm-merged.json"
L1_FILE = BASE / "data" / "normalized" / "l1-names.json"
INTRO_FILE = BASE / "data" / "intro-links.json"
OUT = BASE / "data" / "normalized" / "selfbuilt-edges.json"

# 这些「概念」其实是方法/能力，建成知识节点会把 L0 的东西混进 L1
NOT_CONCEPTS = {"摆一摆", "动手操作", "观察和发现规律", "分类与整理"}


SUBJ_ZH = {"math": "数学", "physics": "物理", "chemistry": "化学",
           "biology": "生物", "common": "通用"}


def main():
    g = json.loads(GRAPH.read_text())
    nodes = {n["id"]: n for n in g["nodes"]}
    tax = json.loads(L0_FILE.read_text())
    merged = json.loads(MERGED.read_text())
    l1 = json.loads(L1_FILE.read_text())
    merged["_upstream"] = [e for e in g["edges"] if e["type"] == "prerequisites_for"]

    l0 = {a["id"]: a for a in tax["abilities"]}
    alias2l0 = {al: a["id"] for a in tax["abilities"] for al in a["aliases"]}

    out_nodes, out_edges = [], []
    stat = Counter()

    # ── L0 能力节点 ────────────────────────────────────────
    for a in tax["abilities"]:
        # **能力按学科分桶。**
        # 现有 16 个是按人教版**数学**核心素养手排的，非数学学科的能力需求
        # 是另一套：抽样盲测里化学的 ability 前置有 24 条「规范操作」、
        # 18 条「安全意识」，生物有「观察力」，这些在 16 个数学能力里
        # 都没有对应桶（命中率只有 78%，数学是 100%）。
        # subject="common" 的能力各科都能用，其余是某科专用。
        a_subj = a.get("subject", "common")
        out_nodes.append({
            "id": a["id"], "name": a["name"], "label": "Ability",
            # 画布分组仍用 math（跟 derived 自建概念一致），
            # 学科分桶的信息放在 scope 字段。
            # 能力**不属于任何单一学科**，之前标 math 只是画布分组的需要，
            # 学科分布统计里自建节点本来就不计入（「能力底座 0」是对的）。
            "subject": "math", "subjectZh": "数学",
            "scope": a_subj,               # common / 具体学科
            "book": "", "bookZh": "—", "stage": "能力底座",
            "definition": a["def"], "blocks": a["blocks"],
            "core": a.get("core", ""), "aliases": a["aliases"],
            "source": "l0",
        })
    stat["l0_nodes"] = len(out_nodes)

    # ── derived 概念节点 ───────────────────────────────────
    newnames = [e for e in l1["entries"] if e["status"] == "NEW" and e["name"] not in NOT_CONCEPTS]
    for i, e in enumerate(newnames, 1):
        nid = f"dv_{i:02d}"
        out_nodes.append({
            "id": nid, "name": e["name"], "label": "Concept",
            "subject": "math", "subjectZh": "数学",
            "book": "", "bookZh": "—", "stage": "自建概念",
            "definition": "", "usedBy": sorted(e["books"]),
            "source": "derived",
        })
        # 模型给的那些前置，接到这个新节点上
        for tgt in e["targets"]:
            if tgt in nodes:
                out_edges.append({
                    "from": nid, "to": tgt, "type": "prerequisites_for",
                    "fromName": e["name"], "toName": nodes[tgt]["name"],
                    "source": "derived",
                    "evidence": "",
                })
                stat["derived_edges"] += 1
    stat["derived_nodes"] = len(out_nodes) - stat["l0_nodes"]

    # ── L0 → 知识点 ────────────────────────────────────────
    # 从原始批次里重读，因为 lmm-merged.json 只留了 queue 的样本
    # **不要只读 math-*.json** —— 非数学的盲测结果也要接上，
    # 否则非数学的能力边一条都建不出来（数学 415 条，非数学 419 条，
    # 占了四成）。
    for f in sorted((BASE / "data" / "lmm-out").glob("*.json")):
        for row in json.loads(f.read_text()):
            tgt = row.get("id")
            if tgt not in nodes:
                continue
            for p in row.get("prereq", []):
                if p.get("type") != "ability":
                    continue
                lid = alias2l0.get((p.get("name") or "").strip())
                if not lid:
                    stat["ability_unmapped"] += 1
                    continue
                out_edges.append({
                    "from": lid, "to": tgt, "type": "prerequisites_for",
                    "fromName": l0[lid]["name"], "toName": nodes[tgt]["name"],
                    "source": "l0", "evidence": p.get("why") or "",
                })
                stat["l0_edges"] += 1

    # ── 模型边（已解析的）──────────────────────────────────
    for r in merged["resolved"]:
        if r["kind"] != "new":
            continue
        out_edges.append({
            "from": r["from"], "to": r["to"], "type": "prerequisites_for",
            "fromName": r["fromName"], "toName": r["toName"],
            "source": "model", "evidence": r.get("why") or "",
        })
        stat["model_edges"] += 1

    # ── 教材引入路径边 ─────────────────────────────────────
    # 盲测问的是「硬前置」，教材讲的是「引入路径」，两者不是一回事。
    # 人教九上 22.1.2 原话：「在八年级下册，我们学习了一次函数的概念，
    # 研究了它的图象和性质。像研究一次函数一样，现在我们来研究二次函数的
    # 图象和性质。」—— 教材自己声明了「一次函数 → 二次函数」，
    # 而模型给的是「函数 → 二次函数」，中间站被跳过。
    #
    # 这类边必须**有教材原文**才建，不做语义推断。
    # 清单在 data/intro-links.json，每条带原文出处。
    if INTRO_FILE.exists():
        for il in json.loads(INTRO_FILE.read_text(encoding="utf-8"))["links"]:
            if il.get("status") != "confirmed":
                stat["intro_pending"] += 1     # 待人工确认的先不建
                continue
            f, t = il["from"], il["to"]
            if f not in nodes or t not in nodes:
                stat["intro_skip_missing_node"] += 1
                continue
            if any(e["from"] == f and e["to"] == t for e in out_edges):
                stat["intro_dup"] += 1
                continue
            # 「教材引入路径」有两种出处，页面上要能分开看：
            #   via=structmap → 来自「本章知识结构图」（教材画的网络）
            #   其他         → 来自正文回指句（「像研究一次函数一样」）
            out_edges.append({
                "from": f, "to": t, "type": "prerequisites_for",
                "fromName": nodes[f]["name"], "toName": nodes[t]["name"],
                "source": "structmap" if il.get("via") == "structmap" else "intro",
                "evidence": il.get("evidence", ""),
                "evidenceSource": il.get("source", ""),
            })
            stat["intro_edges"] += 1

    # ── 跟上游边撞车：方向相反的同一条关系 ──────────────────
    # 2,928 条模型边里有 41 条跟上游边方向相反。逐条看过，**模型那边是对的**：
    #   上游：对数函数 → 对数函数的定义域与值域
    #        证据却是「函数 y = log_a x 的定义域是 (0, +∞)」——
    #        这只是正文里的一句话，不是说「要先懂定义域才懂对数函数」。
    #   模型：对数函数的定义域与值域 → 对数函数   ← 对
    # 同一类问题的第七种形态（ISSUE-01~07 已记六种）。
    #
    # 不能默默剪掉一条：build_viz 剪环边时留哪条取决于遍历顺序，
    # 也就是说「对」和「错」谁活下来是随机的。
    # 这里把冲突全部记下来交给人判，图上先按「上游优先」处理 ——
    # 上游是已发表的数据集，我们不静默改它，但账要记下来。
    upstream = {}
    for e in merged.get("_upstream", []):
        upstream[(e["from"], e["to"])] = e
    conflicts = []
    for e in out_edges:
        if e["source"] != "model":
            continue
        rev = (e["to"], e["from"])
        if rev in upstream:
            conflicts.append({
                "model": {"from": e["fromName"], "to": e["toName"],
                          "why": e.get("evidence", "")},
                "upstream": {"from": upstream[rev]["from"], "to": upstream[rev]["to"],
                             "evidence": upstream[rev].get("evidence", "")},
            })
    stat["conflicts"] = len(conflicts)

    # ── 去重 ───────────────────────────────────────────────
    seen, uniq = set(), []
    for e in out_edges:
        k = (e["from"], e["to"])
        if k in seen:
            stat["dedup"] += 1
            continue
        seen.add(k)
        uniq.append(e)

    # derived 节点自己也要有出边指向真实知识点之外的知识边吗？—— 不加。
    # derived 只作为前置出现，不主动连边。图谱里我们不知道它跟谁互为前置，
    # 猜出来的边比没有边更糟。

    OUT.write_text(json.dumps({
        "nodes": out_nodes, "edges": uniq, "stats": dict(stat),
        "conflicts": conflicts,
    }, ensure_ascii=False, indent=1))

    print("═══ 自建层 ═══")
    print(f"  L0 能力节点   {stat['l0_nodes']:>4} 个（手工定，不落册）")
    print(f"  derived 概念  {stat['derived_nodes']:>4} 个（模型跑出、图谱没有的）")
    print(f"    └ 剔除方法/能力类 {len(NOT_CONCEPTS)} 个：{'、'.join(NOT_CONCEPTS)}")
    print(f"\n  L0 → 知识点   {stat['l0_edges']:>4} 条")
    print(f"  derived → 知识点 {stat['derived_edges']:>4} 条")
    print(f"  教材引入路径    {stat['intro_edges']:>4} 条")
    print(f"  模型边        {stat['model_edges']:>4} 条")
    print(f"  去重掉        {stat['dedup']:>4} 条")
    print(f"  合计          {len(uniq):>4} 条")
    if stat.get("ability_unmapped"):
        # **这多数不是「漏了」，是「模型把知识标成了能力」。**
        # 全量跑完后的 328 次未归入里，排在前面的是「比例运算」「图像识读」
        # 「光屏」「小磁针」「椭圆」—— 这些是**知识**，模型归类错了。
        # merge_prereq 已经处理过：ability 归不进 L0 时再当知识试一次，
        # 能落位的走 model 边（已计入 model_edges）。
        # 这里报的只是「没有对应 L0 桶的次数」。
        print(f"  ⚠ 有 {stat['ability_unmapped']} 次能力前置没能归入 L0"
              f"（多是模型把知识标成了能力，merge_prereq 已回退成知识边处理）")
    bysrc = Counter(e["source"] for e in uniq)
    print(f"\n  按来源：{dict(bysrc)}")
    if stat["conflicts"]:
        print(f"\n  ⚠ 跟上游边方向相反：{stat['conflicts']} 条")
        print("    逐条看过，模型这边是对的（见 conflicts 字段）。")
        print("    这类「证据只是正文里一句话、不是前置理由」的边，")
        print("    跟 ISSUE-01~07 是同一族问题，值得给上游提。")
    print(f"\n→ {OUT.relative_to(BASE)}")


if __name__ == "__main__":
    main()
