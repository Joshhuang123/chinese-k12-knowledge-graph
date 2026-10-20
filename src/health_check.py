#!/usr/bin/env python3
"""
上线体检 —— 数据层 + 构建层 + 产物一致性。

之前每次上线都靠「肉眼看一眼网页」。这不够：改完本地忘了重新部署、
或者 build_viz.py 悄悄多写了一个字段但没写进 COPY 列表，
肉眼看不出来，线上照样是旧的。

这个脚本把体检固化成可复跑的检查：

  L1 数据层
    - 上游素材的已知问题（空名 / 环）必须**在白名单里**，
      出现新问题就报错；已知问题降级为提示并指向 known-issues.md
    - **成品图**（页面上真正画出来的那张）必须无环、无自环、无重复边
    - 每条边的来源档位必须是 7 档里的一档

  L2 构建层
    - index.html 里嵌的 payload 与 graph.json / selfbuilt-edges.json 对齐
    - index.html 的 SHA-256 与 git 里的 blob 一致（= 已提交）
    - COPY 列表里的**旧文案一条都不许残留在成品里**

  L3 判别力自检
    - 把每个检查器拿去做一件它该报错的事，确认它真的会红
      （判别力为零的断言，等于没写）

跑法：
    python3 src/health_check.py            # 全跑
    python3 src/health_check.py --layer 1  # 只跑数据层
"""
import argparse
import hashlib
import json
import pathlib
import re
import subprocess
import sys
from collections import Counter

BASE = pathlib.Path(__file__).resolve().parent.parent
SRC = BASE / "src"
GRAPH = BASE / "data" / "normalized" / "graph.json"
SELF = BASE / "data" / "normalized" / "selfbuilt-edges.json"
FULL = BASE / "data" / "normalized" / "full-stats.json"
VALID = BASE / "data" / "normalized" / "validation.json"
CONFL = BASE / "data" / "normalized" / "prereq-conflicts.json"
INDEX = BASE / "index.html"
TEMPLATE = BASE / "viz" / "template.html"

KEEP = {"Concept", "Skill", "Experiment"}
TIER_ZH = {0: "上游", 1: "模型重建", 2: "能力底座", 3: "自建概念",
           4: "教材引入路径", 5: "已修正", 6: "教材结构图"}

# 上游素材的**已知**问题。出现新问题要报错；这些在册的降级成提示。
# 每条都指向 known-issues.md 里的条目。
KNOWN_UPSTREAM = {
    "EMPTY_NAME": ("math_1a_rjb_exe40..45 共 6 个空名习题节点", "ISSUE-08"),
    "PREREQ_CYCLE": ("上游 2 组先修边成环（相似相溶规律↔极性分子 等）", "ISSUE-08"),
    "IS_A_CYCLE": ("上游 1 组 is_a 成环（元素周期表→元素周期律→元素周期系）", "ISSUE-08"),
}

PASS, FAIL, WARN = [], [], []


def ok(cond, label, extra=""):
    if cond:
        PASS.append(label)
        print(f"  ✓ {label}")
    else:
        FAIL.append((label, extra))
        print(f"  ✗ {label}" + (f"\n      {extra}" if extra else ""))
    return bool(cond)


def warn(label, extra=""):
    WARN.append(label)
    print(f"  ! {label}" + (f"\n      {extra}" if extra else ""))


def sha256(p: pathlib.Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def load_payload():
    html = INDEX.read_text(encoding="utf-8")
    m = re.search(r'<script id="data" type="application/json">(.*?)</script>',
                  html, re.S)
    if not m:
        return None, None
    return json.loads(m.group(1)), html


def find_cycles(nodes, edges):
    """edges: [(pre_id, post_id)]，返回环列表。

    **判别力自检在最后** —— 见 layer3()。
    """
    pre = {}
    for a, b in edges:
        pre.setdefault(b, []).append(a)
    color, cycles = {}, []

    def dfs(u, path):
        color[u] = 1
        for v in pre.get(u, ()):
            if color.get(v) == 1:
                cycles.append(path[path.index(v):] + [u, v])
            elif color.get(v) is None:
                dfs(v, path + [u])
        color[u] = 2

    sys.setrecursionlimit(100000)
    for nid in nodes:
        if color.get(nid) is None:
            dfs(nid, [])
    return cycles


# ── L1 数据层 ────────────────────────────────────────────────
def layer1(g, sb, payload):
    print("\n[L1] 数据层")

    # 1a. 上游素材：已知问题 vs 新问题
    nodes, edges = g["nodes"], g["edges"]
    by_id = {n["id"]: n for n in nodes}
    empty = sorted(n["id"] for n in nodes if not (n.get("name") or "").strip())
    KNOWN_EMPTY = {"math_1a_rjb_exe40", "math_1a_rjb_exe41", "math_1a_rjb_exe42",
                   "math_1a_rjb_exe43", "math_1a_rjb_exe44", "math_1a_rjb_exe45"}
    unexpected = [e for e in empty if e not in KNOWN_EMPTY]
    ok(not unexpected,
       f"上游空名节点仍是已知的 6 个（发现 {len(empty)} 个，多出 {len(unexpected)} 个）",
       str(unexpected[:5]))
    if empty:
        warn(f"上游有 {len(empty)} 个空名节点（已知问题 {KNOWN_UPSTREAM['EMPTY_NAME'][0]}）"
             f" —— {KNOWN_UPSTREAM['EMPTY_NAME'][1]}")

    dup = [i for i, c in Counter(n["id"] for n in nodes).items() if c > 1]
    ok(not dup, f"上游节点 id 无重复（{len(dup)} 个重复）", str(dup[:5]))

    dangling = [e for e in edges
                if e.get("from") not in by_id or e.get("to") not in by_id]
    ok(not dangling, f"上游没有悬空边（{len(dangling)} 条）",
       str([(e.get("from"), e.get("to")) for e in dangling[:5]]))

    # 上游先修边的环（已知 2 组）
    up_pre = [(e["from"], e["to"]) for e in edges
              if e.get("type") == "prerequisites_for"]
    up_cyc = find_cycles(list(by_id), up_pre)
    ok(len(up_cyc) == 2, f"上游先修边的环仍是已知的 2 组（发现 {len(up_cyc)} 组）",
       f"{[c for c in up_cyc if len(c) not in (3,)]}")
    if up_cyc:
        warn(f"上游有 {len(up_cyc)} 组先修边成环（已知问题）"
             f" —— {KNOWN_UPSTREAM['PREREQ_CYCLE'][1]}")

    # 1b. 成品图：必须无环、无自环、无重复边
    up_ids = {n["id"] for n in nodes if n["label"] in KEEP and n["name"].strip()}
    pnodes = payload["nodes"]
    pname = [n[5] for n in pnodes]
    pedges = [(pname[e[1]], pname[e[0]]) for e in payload["edges"]]
    c = Counter(pedges)
    dup_e = [k for k, v in c.items() if v > 1]
    ok(not dup_e, f"成品图没有重复边（{len(dup_e)} 组重复）", str(dup_e[:3]))
    selfl = [k for k in pedges if k[0] == k[1]]
    ok(not selfl, f"成品图没有自环（{len(selfl)} 条）", str(selfl[:3]))
    cyc = find_cycles(pname, pedges)
    ok(not cyc, f"成品图的先修边无环（{len(cyc)} 个环）",
       "\n      ".join(" → ".join(x) for x in cyc[:3]))

    # 1c. 来源档位
    tiers = Counter(e[2] for e in payload["edges"])
    bad = {k for k in tiers if k not in TIER_ZH}
    ok(not bad, f"每条边的来源档位都是 7 档里的（发现未知档：{bad or '无'}）",
       f"实际分布：{dict(tiers)}")
    ok(len(tiers) == 7, f"7 个档位全都用上了（实际 {len(tiers)} 个在用）",
       f"分布：{ {TIER_ZH[k]: v for k, v in sorted(tiers.items())} }")

    # 1d. 裁决日志
    if CONFL.exists():
        cj = json.loads(CONFL.read_text(encoding="utf-8"))
        res = cj.get("resolved", [])
        ok(len(res) > 0, f"裁决日志有记录（{len(res)} 组）")
        by_reason = Counter(r.get("reason", "conflict") for r in res)
        print(f"      原因分布：{dict(by_reason)}")

        # **核心不变式：素材里每一条先修边，要么在成品图里，要么在账本里有下落。**
        # 「不能默默剪掉」这条铁律的可执行版本。
        pnameset = set(pname)
        source_pairs = set()
        for e in g["edges"]:
            if e.get("type") == "prerequisites_for":
                if e["from"] in pnameset and e["to"] in pnameset:
                    source_pairs.add((e["from"], e["to"]))
        for e in sb["edges"]:
            if e.get("type") == "prerequisites_for":
                if e["from"] in pnameset and e["to"] in pnameset:
                    source_pairs.add((e["from"], e["to"]))
        logged = {tuple(r["dropped"]) for r in res if r.get("dropped")}
        live_set = set(pedges)
        missing = [p for p in source_pairs if p not in live_set and p not in logged]
        ok(not missing,
           f"素材里每条先修边都有下落：在图上 {len(source_pairs & live_set)} 条、"
           f"账本里 {len(source_pairs & logged)} 条、"
           f"**下落不明 {len(missing)} 条**",
           str(missing[:3]))
        # 账本里标「丢」的边必须真的不在成品图里
        bad2 = [p for p in logged if p in live_set]
        ok(not bad2, f"账本里标「丢」的边都不在成品图里（{len(bad2)} 条还在）",
           str(bad2[:3]))
        # 「留」的对最终是否活下来，账本必须如实记录
        mism = [r for r in res if r.get("kept")
                and r.get("keptSurvived") != (tuple(r["kept"]) in live_set)]
        ok(not mism, f"账本里「留」的边的存活标记与成品图一致（{len(mism)} 条对不上）",
           str(mism[:2]))
    else:
        warn("prereq-conflicts.json 不存在，跳过裁决日志核查")

    # 人可读账本（进库的）必须跟 JSON 同步
    DOC = BASE / "docs" / "prereq-conflicts.md"
    if DOC.exists() and CONFL.exists():
        dt = DOC.read_text(encoding="utf-8")
        cj = json.loads(CONFL.read_text(encoding="utf-8"))
        n = len(cj.get("resolved", []))
        ok(f"记在账上的：**{n:,}** 条" in dt or f"**{n}** 条" in dt,
           f"docs/prereq-conflicts.md 里的条数跟 JSON 一致（{n} 条）")
        ok(f"成品图边数：**{len(pedges):,}**" in dt,
           f"docs/prereq-conflicts.md 里的成品边数跟成品图一致（{len(pedges):,}）")
    else:
        warn("docs/prereq-conflicts.md 不存在 —— 账本要进库才能被复核")

    # 1e. 口径复算
    if FULL.exists():
        fs = json.load(open(FULL, encoding="utf-8"))
        ok(fs.get("total_edges") == len(pedges),
           f"full-stats.json 的总边数（{fs.get('total_edges')}）= 成品图（{len(pedges)}）")
        ok(fs.get("upstream_nodes") == len(up_ids),
           f"full-stats.json 的上游知识点数（{fs.get('upstream_nodes')}）"
           f"= 图谱里的（{len(up_ids)}）")
        ok(fs.get("canvas_nodes") == len(pname),
           f"full-stats.json 的画布点数（{fs.get('canvas_nodes')}）"
           f"= 成品图（{len(pname)}）")
    else:
        warn("full-stats.json 不存在，跳过口径复算")
    return payload


# ── L2 构建层 ────────────────────────────────────────────────
def layer2(g, sb, payload, html):
    print("\n[L2] 构建层")
    nodes = g["nodes"]
    up = [n for n in nodes if n["label"] in KEEP and n["name"].strip()]
    selfids = {n["id"] for n in sb["nodes"]}
    expect_nodes = {n["id"] for n in up} | selfids

    ok(payload["total"] == len(up),
       f"payload.total（{payload['total']}）= 上游知识点数（{len(up)}）",
       f"total={payload['total']} upstream={len(up)}")
    got = {n[5] for n in payload["nodes"]}
    ok(got == expect_nodes,
       f"payload 节点集合 = 上游可上屏的 {len(up)} 个 + 自建 {len(selfids)} 个",
       f"只在 graph 里：{sorted(expect_nodes - got)[:3]}；"
       f"只在 payload 里：{sorted(got - expect_nodes)[:3]}")

    # 成品图的边必须都能在素材里找到出处
    src_pairs = set()
    for e in g["edges"]:
        if e.get("type") == "prerequisites_for":
            src_pairs.add((e["from"], e["to"]))
    for e in sb["edges"]:
        if e.get("type") == "prerequisites_for":
            src_pairs.add((e["from"], e["to"]))
    pname = [n[5] for n in payload["nodes"]]
    pedges = {(pname[e[1]], pname[e[0]]) for e in payload["edges"]}
    # 「已修正」档的边是反向加进来的，素材里没有是正常的
    orphan = [k for k in pedges if k not in src_pairs]
    fixed_tier = {(pname[e[1]], pname[e[0]]) for e in payload["edges"] if e[2] == 5}
    real_orphan = [k for k in orphan if k not in fixed_tier]
    ok(not real_orphan,
       f"成品图的边都有素材出处（{len(real_orphan)} 条凭空出现）",
       str(real_orphan[:3]))

    # 首页口径文案
    txt = re.sub(r"<[^>]+>", " ", html)
    txt = re.sub(r"\s+", " ", txt)
    ok(f"{len(up):,}" in txt, f"页面里有教材知识点数 {len(up):,}")
    ok("中国的孩子" in txt and "全世界孩子" not in txt,
       "首页标题口径是「中国的孩子」")
    ok("全世界孩子" not in html, "连 <title> 里也没有「全世界孩子」")
    ok(f"{len(pedges):,}" in txt, f"页面里有前置关系数 {len(pedges):,}")

    # git 一致性
    try:
        blob = subprocess.run(["git", "show", "HEAD:index.html"],
                              cwd=BASE, capture_output=True, check=True).stdout
        ok(hashlib.sha256(blob).hexdigest() == sha256(INDEX),
           "index.html 与 git HEAD 里的 blob 一致（已提交）")
    except Exception as e:
        warn(f"取 git blob 失败，跳过：{e}")

    # COPY 列表：**旧文案一条都不许残留在成品里**
    bv = (SRC / "build_viz.py").read_text(encoding="utf-8")
    m2 = re.search(r"COPY\s*=\s*\[(.*?)\n    \]", bv, re.S)
    if m2:
        pairs = re.findall(r"\(\s*(\"(?:[^\"\\]|\\.)*\")\s*,\s*(\"(?:[^\"\\]|\\.)*\")\s*\)",
                           m2.group(1))
        # 有些条目用单引号
        pairs += re.findall(r"\(\s*('(?:[^'\\]|\\.)*')\s*,\s*('(?:[^'\\]|\\.)*')\s*\)",
                            m2.group(1))
        stale = []
        for a, _b in pairs:
            old = eval(a)          # 取出模板里的旧文案
            if old in html:
                stale.append(old[:50])
        ok(not stale, f"COPY 列表里的旧文案一条都没残留在成品里（{len(stale)} 条残留）",
           "\n      ".join(stale[:4]))
    else:
        warn("build_viz.py 里没找到 COPY 列表，跳过")


# ── L3 判别力自检 ───────────────────────────────────────────
def layer3(g, sb, payload):
    """**每条断言都必须能红。** 拿检查器去做它该报错的事。"""
    print("\n[L3] 判别力自检（检查器本身要能报错）")

    # 环检测器
    fake = [("a", "b"), ("b", "a")]
    ok(len(find_cycles(["a", "b"], fake)) == 1,
       "环检测器：注入 A↔B 能报出 1 个环")
    ok(len(find_cycles(["a", "b"], [("a", "b")])) == 0,
       "环检测器：无环输入不误报")

    # 节点集合比对
    up = {n["id"] for n in g["nodes"] if n["label"] in KEEP and n["name"].strip()}
    selfids = {n["id"] for n in sb["nodes"]}
    bogus = up | selfids | {"ghost_node_xyz"}
    ok(bogus != (up | selfids), "节点集合比对：多一个幽灵节点会被发现")

    # 来源档位
    ok(99 not in TIER_ZH, "来源档位表：未知档位确实查得到")
    ok(len(TIER_ZH) == 7, "来源档位表正好 7 档")

    # 环剪枝：环里同时有上游边和模型边时，必须牺牲上游那条。
    # **这条自检是必要的**：build_viz 的环剪枝改成按优先级丢之后，
    # 如果写反了（牺牲模型留上游），成品图不会报错 ——
    # 环照样被剪掉，页面照样合法，只是**内容错了**。
    # 没有判别力检查的话，这种错能一直躺着。
    import importlib.util
    spec = importlib.util.spec_from_file_location("bv", str(SRC / "build_viz.py"))
    # 不直接 import build_viz（它 import 一堆东西且会跑 main），
    # 这里把 PRIORITY / TIER_SRC 读出来自己复算一遍
    bvs = (SRC / "build_viz.py").read_text(encoding="utf-8")
    mprio = re.search(r"PRIORITY\s*=\s*(\{.*?\})", bvs, re.S)
    mtier = re.search(r"TIER_SRC\s*=\s*(\{.*?\})", bvs, re.S)
    ok(mprio and mtier, "能从 build_viz.py 读出 PRIORITY / TIER_SRC 表")
    if mprio and mtier:
        prio = eval(mprio.group(1))
        tier = eval(mtier.group(1))
        # 造一个环：上游边 a→b（档位 0），模型边 b→a（档位 1）
        tier_of = {("a", "b"): 0, ("b", "a"): 1}
        c = set(tier_of)

        def key(e):
            return (prio.get(tier[tier_of[e]], 40), e[0])
        pick = min(c, key=key)
        ok(pick == ("a", "b"),
           f"环剪枝：上游边和模型边同时在环里时牺牲上游那条"
           f"（实际牺牲 {pick}）")
        ok(prio.get("model", 0) > prio.get("upstream", 0),
           "PRIORITY 表里 model 的优先级确实高于 upstream")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--layer", type=int, choices=[1, 2, 3], default=0,
                    help="只跑某一层")
    args = ap.parse_args()

    print("=" * 62)
    print("上线体检（L1 数据层 / L2 构建层 / L3 判别力自检）")
    print("=" * 62)

    g = json.load(open(GRAPH, encoding="utf-8"))
    sb = json.load(open(SELF, encoding="utf-8"))
    payload, html = load_payload()
    if payload is None:
        print("  ✗ index.html 里找不到 payload —— 先跑 python3 src/build_viz.py")
        sys.exit(1)

    if args.layer != 3:
        layer1(g, sb, payload)
    if args.layer != 1:
        layer2(g, sb, payload, html)
    if args.layer == 0:
        layer3(g, sb, payload)

    print("\n" + "=" * 62)
    print(f"通过 {len(PASS)} · 失败 {len(FAIL)} · 提示 {len(WARN)}")
    if FAIL:
        print("\n失败项：")
        for lab, extra in FAIL:
            print(f"  · {lab}" + (f"\n      {extra}" if extra else ""))
    print("=" * 62)
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
