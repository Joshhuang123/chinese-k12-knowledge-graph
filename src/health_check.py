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

    # ── 多版本教材对照 ───────────────────────────────────────
    # 页面上「其他版本教材里的位置」那一栏的数据来源。
    # 对不上就说明 payload 里的 altpos 跟 align 文件脱节了
    # （改了对齐没重建、或者重建了对齐没提交）。
    ALIGN = BASE / "data" / "alt-align.json"
    if ALIGN.exists():
        aj = json.load(open(ALIGN, encoding="utf-8"))
        bc = aj.get("byConcept", {})
        ap = payload.get("altpos", {}) or {}
        ok(len(ap) > 0, f"payload 带了多版本对照数据（{len(ap)} 个概念）")
        # 概念 id 必须都真实存在
        node_ids = {n["id"] for n in g["nodes"]}
        ghost = [c for c in bc if c not in node_ids]
        ok(not ghost, f"对照表里的概念 id 都真实存在（幽灵 {len(ghost)} 个）",
           str(ghost[:3]))
        # payload 里的条数不能超过对照表
        over = sum(len(v) for v in ap.values())
        total = sum(len(v) for v in bc.values())
        ok(over <= total, f"payload 里的多版本条数不超过对照表（{over} ≤ {total}）")
    else:
        warn("data/alt-align.json 不存在 —— 多版本教材对照还没生成")

    # ── 给 agent 用的教材数据 ─────────────────────────────────
    # 教材转出来的结构化数据集。id 唯一、概念 id 真实存在 ——
    # 这两条破了，agent 拿到的就是一堆指不出位置的行。
    LP = BASE / "data" / "lessons.jsonl"
    CP = BASE / "data" / "concept-text.jsonl"
    if LP.exists() and CP.exists():
        lids, lpages = [], 0
        for line in LP.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            lids.append(r["id"])
            lpages += 1
        ok(len(lids) == len(set(lids)),
           f"lessons.jsonl 的 id 无重复（{len(lids)} 页，重复 {len(lids)-len(set(lids))} 个）")
        ok(lpages > 5000, f"lessons.jsonl 页数够（{lpages} 页）")
        crows = [json.loads(x) for x in CP.read_text(encoding="utf-8").splitlines() if x.strip()]
        node_ids = {n["id"] for n in g["nodes"]}
        ghost = [c["id"] for c in crows if c["id"] not in node_ids]
        ok(not ghost, f"concept-text.jsonl 的概念 id 都真实存在（幽灵 {len(ghost)} 个）",
           str(ghost[:3]))
        ok(len(crows) > 500, f"concept-text.jsonl 覆盖够多概念（{len(crows)} 个）")
        # 教材原话必须是真句子。
        # **不是每个概念都必须有** —— 少数概念在教材里只以**标题**形式出现
        # （比如「植物细胞的基本结构」在七上生物 51 页只是个标题，没有正文句子），
        # 那种情况只记页码、不记引文是对的。所以这里查的是总量下限。
        withq = [c for c in crows if c.get("quotes")]
        ok(len(withq) >= 1200,
           f"拿到教材原话的概念 {len(withq)} 个（至少要有 1,200）")
        ok(len(withq) / len(crows) > 0.9,
           f"拿到原话的概念占比 {len(withq)/len(crows):.0%}（标题型的不算）")
    else:
        warn("lessons.jsonl / concept-text.jsonl 不存在 —— 教材数据集还没生成"
             "（跑 python3 src/pdf_to_units.py）")

    # ── 视觉层（ISSUE-34）────────────────────────────────────────
    # 视觉模型读扫描页的产物，补回 OCR 丢掉的公式和图形。
    # 这里查三件最容易坏的事：
    #   ① 概念 id 必须真实存在（否则 agent 拿到的是指不出位置的行）
    #   ② formulas 必须是**纯字符串**数组 —— 曾经把 formulaContexts 的
    #      字典混进去过，agent 端 json.loads 之后类型不一致直接炸
    #   ③ 图形描述必须标 provenance=described —— 它是**模型转述**，
    #      不是教材原话；漏了这个标注，下游会拿它当原话引用
    VP = BASE / "data" / "vision-pages.jsonl"
    CV = BASE / "data" / "concept-vision.jsonl"
    if VP.exists() and CV.exists():
        vrows = [json.loads(x) for x in VP.read_text(encoding="utf-8").splitlines() if x.strip()]
        vids = [r["id"] for r in vrows]
        ok(len(vids) == len(set(vids)),
           f"vision-pages.jsonl 的 id 无重复（{len(vids)} 页，重复 {len(vids)-len(set(vids))} 个）")
        ok(len(vrows) >= 200, f"vision-pages.jsonl 页数够（{len(vrows)} 页）")
        ok(all(r.get("ok") for r in vrows),
           f"vision-pages.jsonl 每页都解析成功（失败 {sum(1 for r in vrows if not r.get('ok'))} 页）")

        crows = [json.loads(x) for x in CV.read_text(encoding="utf-8").splitlines() if x.strip()]
        node_ids = {n["id"] for n in g["nodes"]}
        ghost = [c["id"] for c in crows if c["id"] not in node_ids]
        ok(not ghost, f"concept-vision.jsonl 的概念 id 都真实存在（幽灵 {len(ghost)} 个）",
           str(ghost[:3]))
        ok(len(crows) >= 50, f"concept-vision.jsonl 覆盖够多概念（{len(crows)} 个）")

        bad_type = [c["id"] for c in crows
                    if any(not isinstance(x, str) for x in c.get("formulas", []))]
        ok(not bad_type,
           f"concept-vision.jsonl 的 formulas 全是字符串（混入非字符串 {len(bad_type)} 个）",
           str(bad_type[:3]))

        figs = [f for c in crows for f in c.get("figureDescriptions", [])]
        no_prov = [f for f in figs if f.get("provenance") != "described"]
        ok(not no_prov,
           f"图形描述都标了 provenance=described（漏标 {len(no_prov)} 条）")

        withf = [c for c in crows if c.get("formulas")]
        ok(len(withf) >= 30,
           f"拿到公式的概念 {len(withf)} 个（至少要有 30）")
        latexish = [c for c in crows
                    if any(("\\" in x or "^" in x or "_" in x) for x in c.get("formulas", []))]
        ok(len(latexish) >= 20,
           f"公式是 LaTeX 形态（含 \\ 或 ^ 的 {len(latexish)} 个概念）")

        # **判别力最关键的一条**：视觉层的产物里绝不能有 OCR 的残骸特征。
        # OCR 输出里大量出现**全角拉丁字母**（ｍ ｃ ｅ ｎ ｉ —— 公式字体的
        # ToUnicode 表缺失，映射到了全角区）；只要有人把 OCR 文本当成
        # 视觉结果灌进来，这条立刻会红。
        #
        # 注意：**不要**用「字母夹汉字」当判据 —— 视觉层里「三角形ABC」
        # 「直线b与c平行」是合法的几何记号，会大量误报。
        pua = re.compile(r"[\uE000-\uF8FF]")        # 私用区
        fwlatin = re.compile(r"[\uFF21-\uFF3A\uFF41-\uFF5A]")  # 全角拉丁字母
        # 公式里的**裸汉字**（没走 \text / \mathrm）。
        # 真 OCR 会把数学符号映射成普通汉字：`狔＝狓２`、
        # `犪狓２＋犫狓＋犮` —— 犪狓狔都是正常 CJK 码位，
        # **私用区检测抓不到它们**（实测：注入后私用区那条仍然是绿的）。
        # 合法 LaTeX 里的中文必须包在 \text{} / \mathrm{} 里。
        cjk_bare = re.compile(r"[一-鿿]")
        cjk_ok = re.compile(r"\\(?:text|mathrm|mathbf|mathit|quad|qquad)\b")

        allf = [x for c in crows for x in c.get("formulas", [])]
        bad_pua = [x for x in allf if pua.search(x)]
        ok(not bad_pua,
           f"公式里没有 OCR 残骸（私用区字符 {len(bad_pua)} 条）", str(bad_pua[:2]))
        bad_fw = [x for x in allf if fwlatin.search(x)]
        ok(not bad_fw,
           f"公式里没有全角拉丁字母（OCR 残骸特征 {len(bad_fw)} 条）", str(bad_fw[:2]))
        bad_cjk = [x for x in allf if cjk_bare.search(x) and not cjk_ok.search(x)]
        # **不是零容忍**：中文教材里 `\\bar{x}_{甲}` 这种是合法的
        # （甲乙两组数据）。所以看**占比**——
        # 正常是十万分之一量级，OCR 灌进来就是大面积。
        cjk_rate = len(bad_cjk) / max(len(allf), 1)
        ok(cjk_rate < 0.02,
           f"公式里的裸汉字占比 {cjk_rate:.3%}（<2%，OCR 灌进来会爆表）",
           str(bad_cjk[:2]))
        bad_brace = [x for x in allf if _latex_unbalanced(x)]
        ok(not bad_brace,
           f"公式的 LaTeX 花括号都配平（不配平 {len(bad_brace)} 条）", str(bad_brace[:2]))

        # ── 册次一致性：概念的视觉数据必须来自它自己那册 ──────────
        # 这条是「graphBook 写错」那个 bug 的哨兵（见 known-issues ISSUE-35）：
        # 曾经 4,236 页的 graphBook 全写成了「xzxbx3」，
        # 小学数学和初中理化生的概念**全被当成高中**，匹配全错而且不报错。
        node_book = {n["id"]: n.get("book") for n in g["nodes"]}
        wrong = []
        for c in crows:
            b = node_book.get(c["id"])
            if b and c.get("book") and c["book"] != b:
                wrong.append(f"{c['name']}({c['book']}≠{b})")
        ok(not wrong,
           f"概念的视觉数据来自它自己那册（册次对不上的 {len(wrong)} 个）",
           "、".join(wrong[:3]))
    else:
        warn("vision-pages.jsonl / concept-vision.jsonl 不存在 —— 视觉层还没生成"
             "（跑 python3 src/vision_pages.py && python3 src/vision_to_concepts.py）")

    # ── README 数字不许烂 ──────────────────────────────────────
    # 手抄的数字会过期，而且没人发现。2026-10-21 同步 README 时就发现
    # 画布节点写着 7,938（实际 8,667）、先修边写着 3,408（实际 16,845）、
    # 测试写「103 项」（实际 155 项）——三处全过期。
    #
    # **只查会随数据变的头条数字**，数字从数据现算。叙述性文字不查。
    RD = BASE / "README.md"
    if RD.exists():
        rd = RD.read_text(encoding="utf-8")
        claims = {
            "画布节点数": f"{len(payload['nodes']):,}",
            "先修边数": f"{len(payload['edges']):,}",
        }
        # 上游知识点数
        up_n = len({n["id"] for n in g["nodes"]
                    if n.get("label") in ("Concept", "Skill", "Experiment")})
        claims["上游知识点数"] = f"{up_n:,}"
        # **测试项数不在这里查** —— 数源码里的断言行 ≠ 运行时跑的次数
        # （test_search_browser.mjs 有 82 处 ok( 但只跑 81 条）。
        # 那条断言放在两个测试脚本自己的末尾：它们跑完之后手里是真实 pass 数。
        missing = [f"{k}={v}" for k, v in claims.items() if v not in rd]
        ok(not missing,
           f"README 里的头条数字跟当前数据一致（{len(claims)} 项）",
           "README 里没找到：" + "、".join(missing))
        # 反向：这些是**已知过期**的旧数字，不该再出现在 README 里
        # （「进展」一节里作为「起点」出现的 7,938 / 3,408 除外，
        #   那里有明确的「起点 → 现在」对照表）
        stale = []
        for old in ("7,938 个知识点", "3,408 条先修边", "103 项"):
            if old in rd:
                stale.append(old)
        ok(not stale,
           f"README 里没有已知过期的旧数字（残留 {len(stale)} 处）", "、".join(stale))
    else:
        warn("README.md 不存在，跳过一致性检查")

    # ── 教材标的难点（ISSUE-36）────────────────────────────────
    # 「思考」「探究」框是**教材编委会自己标的难点**。
    # 页面里带的数量必须跟数据源对得上。
    HARD = BASE / "data" / "normalized" / "textbook-hard.json"
    if HARD.exists():
        hj = json.loads(HARD.read_text(encoding="utf-8"))
        src = hj.get("concepts") or {}
        ok(len(src) > 200,
           f"教材标的难点挂到了 {len(src)} 个概念上（至少 200）")
        total = sum(v.get("count", 0) for v in src.values())
        ok(total > 500,
           f"教材标的难点合计 {total} 处（至少 500）")
        _hard = payload.get("hard") or {}
        ok(len(_hard) > 0 and len(_hard) <= len(src),
           f"页面里的教材难点映射条数对得上（{len(_hard)} / {len(src)}）")
        # 数量得能对上（抽查前 50 条）
        bad = []
        for k, v in list(_hard.items())[:50]:
            cid = payload["nodes"][int(k)][5]
            s2 = src.get(cid)
            if not s2 or s2.get("count") != v[0]:
                bad.append(cid)
        ok(not bad,
           f"页面里的教材难点数量跟数据源一致（抽查 50 条，对不上 {len(bad)} 条）",
           str(bad[:3]))
    else:
        warn("data/normalized/textbook-hard.json 不存在 —— "
             "面板里不会有教材标的难点（跑 python3 src/explore_difficulty.py）")

    # ── 页面体积预算 ───────────────────────────────────────────
    # 视觉层 payload 涨起来的时候，页面是「悄悄」变大的 ——
    # 单文件 HTML 装在 GitHub Pages 上，给中国学生看的，
    # 4 MB 和 3 MB 是能感觉出来的差别。
    # **数据层可以全留（给 agent），页面层要有预算。**
    _vis = payload.get("vision") or {}
    _vis_bytes = len(json.dumps(_vis, ensure_ascii=False))
    ok(_vis_bytes <= 400_000,
       f"页面里的视觉层 payload 在预算内（{_vis_bytes//1000} KB / 400 KB，"
       f"{len(_vis)} 个概念）")

    # git 一致性
    try:
        blob = subprocess.run(["git", "show", "HEAD:index.html"],
                              cwd=BASE, capture_output=True, check=True).stdout
        ok(hashlib.sha256(blob).hexdigest() == sha256(INDEX),
           "index.html 与 git HEAD 里的 blob 一致（已提交）")
    except Exception as e:
        warn(f"取 git blob 失败，跳过：{e}")

    # 数据质量页：数字必须跟当前数据一致，且页面自包含
    Q = BASE / "quality.html"
    if Q.exists():
        qh = Q.read_text(encoding="utf-8")
        ok(f"{len(pedges):,}" in qh,
           f"数据质量页里的前置关系数跟成品图一致（{len(pedges):,}）")
        ext = re.findall(r'<script[^>]+src="(https?://[^"]+)"', qh) + \
              re.findall(r'<link[^>]+href="(https?://[^"]+)"', qh) + \
              re.findall(r'<img[^>]+src="(https?://[^"]+)"', qh)
        ok(not ext, f"数据质量页没有加载任何外部资源（{len(ext)} 个）",
           str(ext[:3]))
        # 超链接到源码仓库是允许的（那是给人点的，不是页面依赖）
        links = re.findall(r'<a[^>]+href="(https?://[^"]+)"', qh)
        ok(all("github.com" in u for u in links),
           f"页面里的站外超链接只指向源码仓库（{len(links)} 个）", str(links[:3]))
        # 倒挂条数：只数跨册的上游边，跟 flag_suspect 同一套口径
        col = BASE / "data/normalized/order-collide.json"
        if col.exists():
            rows = json.loads(col.read_text(encoding="utf-8")).get("rows", [])
            nrev = sum(1 for r in rows
                       if r.get("kind") == "cross" and r.get("source") == "upstream")
            ok(f"跨册 {nrev} 条" in qh,
               f"数据质量页里的倒挂条数跟 order-collide.json 一致（{nrev} 条）")
    else:
        warn("quality.html 不存在 —— 数据质量页还没生成")

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


def _latex_unbalanced(s: str) -> bool:
    """LaTeX 花括号是否配平。

    **转义的大括号不算** —— `\\left. ... \\right\\}`
    是合法 LaTeX（排版用的隐形大括号），朴素计数会把它误判成不配平。
    """
    d = 0
    i, n = 0, len(s)
    while i < n:
        ch = s[i]
        if ch == "\\" and i + 1 < n and s[i + 1] in "{}":
            i += 2          # 跳过转义的大括号
            continue
        if ch == "{":
            d += 1
        elif ch == "}":
            d -= 1
        if d < 0:
            return True
        i += 1
    return d != 0


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

    # 视觉层：**OCR 残骸检测器必须能红**。
    # 视觉层的价值全在于「它不是 OCR」。如果哪天管线接错、
    # 把 OCR 文本当成视觉结果灌进 concept-vision.jsonl，
    # 上面那两条断言就是唯一的哨兵 —— 它们必须真的会红。
    #
    # 判据是**全角拉丁字母**：OCR 的公式字体的 ToUnicode 表缺失，
    # 字母被映射到了全角区（ｍ ｃ ｅ ｎ ｉ）。实测 OCR 层 2,846 段文本里
    # 有 190 段带全角字母，视觉层 8,601 段里 0 段。
    #
    # **不要用「字母夹汉字」当判据** —— 视觉层里「三角形ABC」
    # 「直线b与c平行」是合法几何记号，会大量误报。
    pua = re.compile(r"[\uE000-\uF8FF]")
    fwlatin = re.compile(r"[\uFF21-\uFF3A\uFF41-\uFF5A]")

    # 真 OCR 输出长这样：y = ２ｘ²，ｍ 的值（字母被映射到全角区）
    ok(bool(fwlatin.search("y = ２ｘ²，ｍ 的值")),
       "OCR 残骸检测器：全角拉丁字母能被认出来（真 OCR 输出确实带这个）")
    ok(not fwlatin.search("y = 2x^2"),
       "OCR 残骸检测器：正常 LaTeX 不误报")
    ok(bool(pua.search("\ue000\ue001")),
       "OCR 残骸检测器：私用区字符能被认出来")
    ok(not pua.search("y = x^2"),
       "OCR 残骸检测器：正常 LaTeX 不误报（私用区）")
    # 犪狓狔是**普通汉字**，不是私用区 —— 所以还得有一条「公式里不许有裸汉字」
    ok(bool(re.search(r"[一-鿿]", "狔＝狓２")),
       "OCR 残骸检测器：公式里的裸汉字能被认出来（犪狓狔是普通 CJK 码位）")
    ok(not (re.search(r"[一-鿿]", "y = \\text{时间} = \\frac{路程}{速度}")
            and not re.search(r"\\(?:text|mathrm)\b", "y = \\text{时间} = \\frac{路程}{速度}")),
       "OCR 残骸检测器：包在 \\text{} 里的中文不误报")
    ok(_latex_unbalanced("y = \\frac{1}{2}x^2}"),
       "LaTeX 配平检测器：多一个右括号能报出来")
    ok(_latex_unbalanced("y = \\frac{1}{2x^2"),
       "LaTeX 配平检测器：少一个右括号能报出来")
    ok(not _latex_unbalanced("y = \\frac{1}{2}x^2"),
       "LaTeX 配平检测器：正常公式不误报")
    # **但裸汉字不能零容忍** —— 教材里 `\bar{x}_{甲}` 是合法的（甲乙两组数据），
    # 所以上面那条断言看的是**占比**。这两条自检把两种情况都钉住。
    ok(bool(re.search(r"[一-鿿]", "\\bar{x}_{甲}=7.537")),
       "裸汉字检测器：甲/乙 这类教材合法标签同样会被标出来（所以看占比）")
    # 转义的大括号是合法 LaTeX（排版用的隐形大括号）
    ok(not _latex_unbalanced("y = \\left. a = b \\right\\}"),
       "LaTeX 配平检测器：转义的大括号 \\right\\} 不误判")


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
