#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
构建「上海的孩子学什么」独立站点 → `shanghai.html`。

为什么能复用同一个模板
----------------------
`viz/template.html` 里所有东西都从 `window.__kg` 读：
节点、边、章节链、单元链、教材公式、教材难点……
**它不知道数据是人教还是沪教** —— 只要 payload 的形状一样，页面就一样。

所以这里做的事是：**造一个沪教版的 payload**，喂给同一个模板。

沪教版 payload 跟人教版的差别
----------------------------
| | 人教版 | 沪教版 |
|---|---|---|
| 节点集 | 上游图谱 8,590 个概念 | 沪教教材页面上真实出现的 569 个 + 120 个先修补充 |
| 章节链 | 上游节点 id 的 `_chNN_sMM` 推的 | **教材自己的目录**（视觉模型读的） |
| 单元链 | 873 个（`src/order.py` 推的） | **521 个**（教材目录的每一节） |
| 教材公式 | 人教 PDF 抽的 | **沪教 PDF 页图抽的** |
| 教材难点 | 人教视觉层 | **沪教视觉层** |
| 学段 | 按年级号推 | **逐节点按学制算**（五四制六年级已经是初中） |

先修边要说清楚：**是从人教版图谱继承的**（284 条，限制在沪教版覆盖的概念子集内）。
教材不会明写「这个要先学那个」，但**概念之间的依赖跟教材版本无关** ——
沪教版的学生学的也是「二次函数要先会一次函数」。

跑法：python3 src/build_shanghai.py
"""
from __future__ import annotations

import collections
import json
import pathlib
import re
import sys

BASE = pathlib.Path("/Users/huangjunhai/Documents/个人/项目/中文知识图谱")
TPL = BASE / "viz" / "template.html"
SG = BASE / "data" / "shanghai-graph.json"
OUT = BASE / "shanghai.html"

# **学科分三个**：沪教版 / 沪科版 / 前置补充。
# 上海的孩子手上主要是沪教版，沪科版（六三制）是另一套。
# 「前置补充」是灰的 —— 那些概念沪教版页面上没单独出现，
# 它们只是沪教概念的前置，标成灰色才不冒充「上海教材里学的」。
SUBJECTS = [
    ("math-hj", "数学·沪教版", "#7fd3ff"),
    ("math-hk", "数学·沪科版", "#6bb7ff"),
    ("math-pre", "前置补充", "#8b93a7"),
    ("physics", "物理", "#ff9d6b"),
    ("chemistry", "化学", "#b9d67f"),
    ("biology", "生物", "#c9a0ff"),
]
ACC = "#ff3d7f"
STAGE_ZH = ["小学", "初中", "高中"]

# 上海的册次 → 图上的年级标签。
# 小学/初中按**年级名**（上海两套学制里年级名是一样的），
# 高中按年级。**不写「岁」** —— 教材是按年级分的。
GRADE_ZH = {0: "基础"}
GRADE_ZH.update({i: f"{c}年级" for i, c in enumerate("一二三四五六七八九", 1)})
GRADE_ZH.update({10: "高一", 11: "高二", 12: "高三"})


def to_plain(s: str) -> str:
    sys.path.insert(0, str(BASE / "src"))
    from latex_plain import to_plain as f
    return f(s)


def main() -> int:
    if not SG.exists():
        print(f"没有 {SG}，先跑 src/shanghai_graph.py")
        return 1
    sg = json.load(open(SG, encoding="utf-8"))
    nodes_src = sg["nodes"]
    units = sg["units"]

    # ── 1. 章节链：每本书的章 ──────────────────────────────────
    # 模板契约：chs[i] = [章名, 册次]
    chs, ch_index = [], {}
    for u in units:
        key = (u["bookId"], u["chapter"])
        if key in ch_index:
            continue
        ch_index[key] = len(chs)
        name = u["chapterName"] or u["sectionName"]
        chs.append([f"{u['chapter']} {name}".strip(), u["bookTitle"][:18]])
    print(f"章 {len(chs)} 个")

    # ── 2. 单元链（节）─────────────────────────────────────────
    # 模板契约（viz/template.html 里 UNITS 按 cns[i][2] 分组）：
    #   cns[i] = [单元名, 册次, **学科下标**, 里面第一个可点的概念下标]
    # **第三位必须是学科下标**，不是版别 —— 拿版别当学科下标的话
    # 「上一/下一单元」会在两套教材之间乱跳，第四位的可点下标也会指错。
    cns = []
    unit_index = {}
    # 学科下标：沪教版 / 沪科版 / 前置补充
    def subj_ix(bid: str) -> int:
        if bid.startswith("sh-hj-"):
            return 0
        if bid.startswith("sh-hk-"):
            return 1
        return 2
    first_concept = {}
    for i, u in enumerate(units):
        unit_index[(u["bookId"], u["section"], u["sectionName"], u["page"])] = i
        name = u["sectionName"] or u["chapterName"]
        cns.append([name, u["bookTitle"][:18], subj_ix(u["bookId"]), -1])
    print(f"单元 {len(cns)} 个")

    # ── 3. 节点 ────────────────────────────────────────────────
    node_units = {}
    for n in nodes_src:
        best = None
        if n.get("mainBook"):
            bid = n["mainBook"]
            b = n["books"][bid]
            best = (bid, b["sections"][0] if b["sections"] else None)
        node_units[n["id"]] = (n, best)

    payload_nodes = []
    idx_of = {}
    ordered = sorted(node_units.items(), key=lambda kv: (kv[1][0]["name"], kv[0]))
    for i, (nid, (n, best)) in enumerate(ordered):
        idx_of[nid] = i
        if n["kind"] == "pre":
            si = 2
        else:
            si = 0 if n["mainBook"].startswith("sh-hj-") else 1
        # 册次显示：沪教版·七上 / 沪科版·八下 / 人教版·七上（前置补充）
        if n["kind"] == "sh":
            b = n["books"][n["mainBook"]]
            dz = f"{b['edition']}·{b['volName']}"
        else:
            dz = n.get("dz") or f"人教版·{n.get('volName') or ''}"
        # **0 是合法值**（能力底座层，在小学一年级之下）——
        # `n["grade"] or 1` 会把 0 变成 1，能力底座就跑到一年级去了。
        grade = n["grade"] if n.get("grade") is not None else 1
        stage = n["stage"]
        # 教材单元下标
        slot = -1
        sec = None
        if best and best[1]:
            key = (best[0], best[1]["section"], best[1]["sectionName"], best[1]["page"])
            slot = unit_index.get(key, -1)
            sec = best[1]
            if slot >= 0 and cns[slot][3] < 0:
                cns[slot][3] = i
        # 描述行：沪教概念写「教材原书上的位置」，前置补充写它的定义
        desc = n.get("desc") or ""
        if not desc and sec:
            bits = [b for b in (sec.get("chapter"), sec.get("chapterName"),
                                sec.get("section"), sec.get("sectionName")) if b]
            ed = n["books"][n["mainBook"]]["edition"] if n.get("mainBook") else "教材"
            desc = f"{ed}教材位置：" + " ".join(bits)
            if sec.get("page"):
                desc += f"（第 {sec['page']} 页）"
        payload_nodes.append([
            i, n["name"], "", si, dz, nid,
            grade, grade, 0.0, 1 if stage == 1 else 0, desc, "—",
            [], [], slot, stage,
        ])
    print(f"节点 {len(payload_nodes)} 个")

    # ── 4. 边 ────────────────────────────────────────────────
    # 边是 [后继, 先修, 来源] —— 方向别搞反，反了前置闭包全空。
    edges = []
    for e in sg["edges"]:
        a, b = idx_of.get(e[0]), idx_of.get(e[1])
        if a is None or b is None:
            continue
        edges.append([a, b, e[2] if len(e) > 2 else 0, 0])
    print(f"边 {len(edges)} 条")

    # ── 5. 教材公式 / 图 / 难点（沪教版的）────────────────────
    # **按 (书, 页) 存** —— 按书存的话每个节点会挂上整本书的公式。
    node_vision = {}
    node_hard = {}
    for n in nodes_src:
        fs, gs, bz = [], [], ""
        hn, hstem = 0, ""
        for bid, b in (n.get("books") or {}).items():
            for pg in (b.get("pages") or []):
                for f in (b.get("formulas") or []):
                    p = to_plain(f)
                    if p and p not in fs:
                        fs.append(p)
                for g in (b.get("figures") or []):
                    d = to_plain((g.get("description") or "").strip())
                    if d:
                        if len(d) > 160:
                            d = d[:158] + "…"
                        gs.append([g.get("caption", ""), d, g.get("provenance", "described")])
            for ex in (b.get("exercises") or []):
                t = ex.get("type") or ""
                if any(k in t for k in ("思考", "探究", "讨论")):
                    hn += 1
                    if not hstem:
                        hstem = to_plain(ex.get("stem", ""))[:90]
            if not bz:
                bz = b.get("title", "")
        if fs or gs:
            node_vision[idx_of[n["id"]]] = [fs[:6], gs[:1], bz]
        if hn:
            node_hard[idx_of[n["id"]]] = [hn, hstem, bz, ""]
    print(f"节点带教材数据 {len(node_vision)} 个 · 带难点 {len(node_hard)} 个")

    # ── 6. payload ────────────────────────────────────────────
    by_subject = collections.Counter()
    for x in payload_nodes:
        by_subject[x[3]] += 1
    n_sh = sum(1 for n in nodes_src if n["kind"] == "sh")
    payload = {
        "nodes": payload_nodes,
        "edges": edges,
        "isa": [],
        "chs": chs,
        "cns": cns,
        "altpos": {},
        "vision": node_vision,
        "visionAlt": {},
        "hard": node_hard,
        "subjects": [{"en": s[0], "zh": s[1], "c": s[2], "n": by_subject.get(i, 0)}
                     for i, s in enumerate(SUBJECTS)],
        "core": sum(1 for x in payload_nodes if x[9]),
        "total": n_sh,
        "drawn": len(payload_nodes),
        "acc": ACC,
        "abi": [],
        "srczh": ["上游", "模型重建", "能力底座", "自建概念",
                  "教材引入路径", "已修正", "教材结构图"],
        "selfbuilt": {"nodes": len(payload_nodes) - n_sh, "edges": 0},
        "aliases": {},
    }

    blob = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    html = TPL.read_text(encoding="utf-8").replace("__DATA__", blob)

    # ── 7. 文案：换成上海口径 ──────────────────────────────────
    # **替换失配即中止** —— 一条文案没命中就报出来，不让它静默留在页面上。
    GRADE_MAP = ("const GRADE_ZH=" + json.dumps(GRADE_ZH, ensure_ascii=False) + ";\n")
    COPY = [
        ("美英课程标准 · ", "按沪教版教材排序 · "),
        # **GRADE_ZH 要在全局** —— 卡片眉标和轴标签两处都要用它，
        # 塞进画轴的函数里的话卡片那边就 ReferenceError。
        ("const SUBJ = D.subjects, ACC = D.acc;",
         "const SUBJ = D.subjects, ACC = D.acc;\n" + GRADE_MAP),
        ("<h1>全世界孩子<br>在<em>学什么</em>。</h1>",
         "<h1>上海的孩子<br>在<em>学什么</em>。</h1>"),
        ("<title>全世界孩子在学什么 · ", "<title>【上海版】上海孩子在学什么 · "),
        ("下面这根锥形从 4 岁长到 15 岁——越往上，概念越大越抽象。",
         "下面这根锥形从小学一年级长到高三——越往上，概念越大越抽象。"),
        ("高度是年龄", "高度是年级"),
        ("共 <b>__N_TOPIC__</b> 个知识点（另有 <b>__N_SELF__</b> 个我们补的能力节点与自建概念），其中 <b>__N_CORE__</b> 个属于 9–10 岁核心",
         "沪教版教材里出现的 <b>__N_TOPIC__</b> 个知识点，我们另外补了 <b>__N_SELF__</b> 个它们的前置概念（灰点），其中 <b>__N_CORE__</b> 个是初中"),
        ("只看 9–10 岁", "只看初中"),
        ("<span class=\"hi\">9–10 岁核心</span>", "<span class=\"hi\">初中</span>"),
        ("<span>低年级基础</span>", "<span>其他学段</span>"),
        ("'<span>' + n.evn + ' 条掌握证据</span><span>重要度 '",
         "'<span>课程要求：' + n.evn + '</span><span>被依赖度 '"),
        ("ctx.fillText('age ' + age, sx, sy);",
         "ctx.fillText(GRADE_ZH[age] || age, sx, sy);"),
        # **出处**：人教版那一页写的是「人教版教材排序」，上海版得说清楚是沪教版。
        ("K12-KGraph 本身是跨国的知识点集，这里按<b>人教版</b>教材排序 —— 两套是分开的，留着做对照。",
         "K12-KGraph 本身是跨国的知识点集，这里按<b>沪教版</b>教材排序 —— 节点、页码、公式全部来自上海教材本身。"),
        # 卡片眉标：原来拼的是「· 3–3 岁」
        # 教材按年级分，不按岁数。
        ("s.zh + ' · ' + n.dz + ' · ' + n.a1 + '–' + n.a2 + ' 岁'",
         "s.zh + ' · ' + n.dz + ' · ' + GRADE_ZH[n.a1]"),
        # 选题卡与卡片里的「教材原书」—— 这一版就是沪教版
        ("## 教材原书（人教版）", "## 教材原书（沪教版）"),
        ("> 数据来自中文 K12 知识图谱（人教版教材排序），每条边可查来源。",
         "> 数据来自中文 K12 知识图谱（沪教版教材排序），每条边可查来源。"),
        ("'教材原书上的公式：'", "'沪教版教材原书上的公式：'"),
        ("'教材原书上的图（据图，模型转述）：'", "'沪教版教材原书上的图（据图，模型转述）：'"),
        ("<div class=\"vh\">教材原书上的公式</div>", "<div class=\"vh\">沪教版教材原书上的公式</div>"),
        ("<div class=\"vh\">教材原书上的图</div>", "<div class=\"vh\">沪教版教材原书上的图</div>"),
        # 「沪教版怎么写」这一块在本版是空的（这里就是沪教版），
        # 但文本留着的话将来填了人教数据也不会说错。
        ("<div class=\"vh\">沪教版怎么写</div>", "<div class=\"vh\">人教版怎么写</div>"),
        ("<div class=\"vh\">沪教版的图</div>", "<div class=\"vh\">人教版的图</div>"),
    ]
    missed = []
    for a, b in COPY:
        if a not in html:
            missed.append(a)
            continue
        html = html.replace(a, b)
    if missed:
        for a in missed:
            print(f"  ✗ 文案未命中: {a[:70]}")
        raise SystemExit(f"构建中止：{len(missed)} 条文案没匹配上，先修模板或规则")

    # ── 8. 占位符：最后替换 ───────────────────────────────────
    n_self = len(payload_nodes) - payload["total"]
    html = (html.replace("__N_TOPIC__", f"{payload['total']:,}")
                .replace("__N_SELF__", f"{n_self:,}")
                .replace("__N_EDGE__", f"{len(edges):,}")
                .replace("__N_CORE__", f"{payload['core']:,}"))

    OUT.write_text(html, encoding="utf-8")
    print(f"\n{payload['total']} 沪教知识点 + {n_self} 前置补充 = {len(payload_nodes)} 节点 · "
          f"{len(edges)} 边 · {len(cns)} 单元 · {len(chs)} 章")
    print(f"→ {OUT}  ({OUT.stat().st_size//1024} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
