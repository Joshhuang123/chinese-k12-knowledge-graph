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

BASE = pathlib.Path(__file__).resolve().parent.parent
TPL = BASE / "viz" / "template.html"
SG = BASE / "data" / "shanghai-graph.json"
OUT = BASE / "shanghai.html"

# **按「学科 × 版别」分色**。
#
# 为什么不再按学科分：上海的教材是**两套并行**的 ——
# 沪教版（上海教育出版社，五四学制）和沪科版（上海科学技术出版社，六三制）。
# 同一个「数学七上」，两边的章号和内容都不一样，
# 画成同一个颜色就看不出「这是哪套教材的树」。
#
# 「前置补充」是灰的 —— 那些概念上海教材页面上没单独出现，
# 它们只是沪教概念的前置，标成灰色才不冒充「上海教材里学的」。
SUBJECTS = [
    ("math-hj", "数学·沪教版", "#7fd3ff"),
    ("math-hk", "数学·沪科版", "#6bb7ff"),
    ("physics-hk", "物理·沪科版", "#ff9d6b"),
    ("chemistry-hj", "化学·沪教版", "#7fd3a0"),
    ("chemistry-hk", "化学·沪科版", "#b9d67f"),
    ("biology-hj", "生物·沪教版", "#c9a0ff"),
    ("biology-hk", "生物·沪科版", "#a0c8ff"),
    ("science-hk", "科学·沪科版", "#ffd166"),
    ("pre", "前置补充", "#8b93a7"),
]
# 教材的中文学科 → 配色键的前缀
SUBJ_KEY = {"数学": "math", "物理": "physics", "化学": "chemistry",
            "生物": "biology", "科学": "science"}
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
        chs.append([f"{u['chapter']} {name}".strip(),
                    f"{u['edition']}·{u.get('volName') or u['graphBook']}"])
    print(f"章 {len(chs)} 个")

    # ── 2. 单元链（节）─────────────────────────────────────────
    # 模板契约（viz/template.html 里 UNITS 按 cns[i][2] 分组）：
    #   cns[i] = [单元名, 册次, **学科下标**, 里面第一个可点的概念下标]
    # **第三位必须是学科下标**，不是版别 —— 拿版别当学科下标的话
    # 「上一/下一单元」会在两套教材之间乱跳，第四位的可点下标也会指错。
    cns = []
    unit_index = {}
    # 学科下标：**学科 × 版别**。教材顺序链按这个分组，
    # 所以「上一/下一单元」永远在同一套教材里走，
    # 不会从沪教版七上跳到沪科版七上。
    def subj_ix(bid: str) -> int:
        parts = (bid or "").split("-")
        subj = parts[2] if len(parts) > 2 else ""
        ed = "hj" if (len(parts) > 1 and parts[1] == "hj") else "hk"
        key = f"{SUBJ_KEY.get(subj, subj)}-{ed}"
        for i, (k, _, _) in enumerate(SUBJECTS):
            if k == key:
                return i
        return len(SUBJECTS) - 1        # 前置补充

    def chain_key(bid: str) -> str:
        """**教材顺序链的分组键：学科 × 版别 × 学制**。

        为什么学制也要进键：沪科版物理**六三制和五四学制两套都有**
        （8a/8b/9a/9b 各两本），是**两套并行的课程**。
        只按「学科+版别」分组的话，「上一单元」会从六三制的八上
        跳到五四学制的八上 —— 那是两本完全不同的书。
        """
        parts = (bid or "").split("-")
        subj = parts[2] if len(parts) > 2 else ""
        ed = "hj" if (len(parts) > 1 and parts[1] == "hj") else "hk"
        sys_ = parts[3] if len(parts) > 3 else "s"
        return f"{SUBJ_KEY.get(subj, subj)}-{ed}-{sys_}"
    first_concept = {}
    for i, u in enumerate(units):
        unit_index[(u["bookId"], u["section"], u["sectionName"], u["page"])] = i
        name = u["sectionName"] or u["chapterName"]
        # 第三位是**链组键**（字符串），不是学科下标 ——
        # 模板拿它给「上一/下一单元」分组，节点的颜色另走 n.s。
        cns.append([name, f"{u['edition']}·{u.get('volName') or u['graphBook']}",
                    chain_key(u["bookId"]), -1])
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
            si = len(SUBJECTS) - 1
        else:
            si = subj_ix(n["mainBook"])
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
        # 描述行：**这个概念是什么**（上游定义）+ **教材原书上的位置**
        #
        # 两个都要。位置在下面的「教材顺序」栏里也有，但那儿是节与节相邻，
        # 这里给的是「这个概念在哪本书哪一节第几页」—— 翻书的时候用。
        desc = n.get("desc") or n.get("def") or ""
        if desc:
            desc = "图谱定义：" + desc
        if sec:
            bits = [b for b in (sec.get("chapter"), sec.get("chapterName"),
                                sec.get("section"), sec.get("sectionName")) if b]
            ed = n["books"][n["mainBook"]]["edition"] if n.get("mainBook") else "教材"
            pos = f"{ed}教材位置：" + " ".join(bits)
            if sec.get("page"):
                pos += f"（第 {sec['page']} 页）"
            desc = (desc + "　｜　" + pos) if desc else pos
        payload_nodes.append([
            i, n["name"], "", si, dz, nid,
            grade, grade,
            0.0,                              # cen → 被依赖度（下面回填）
            1 if stage == 1 else 0, desc, "—",
            [], [], slot, stage,
        ])
    # ── 4. 边 ────────────────────────────────────────────────
    # payload 边的约定是 **[后继, 先修]** —— 模板里
    # `pre.get(e[0]).push(e[1])` 表示「e[0] 的前置是 e[1]」。
    # 主站 `build_viz.py` 的 `payload_edges = [[b, a, ...]]` 就是这个顺序。
    #
    # ⚠️⚠️ **这里原来写反了**（2026-10-26 修）：
    #   `shanghai-graph.json` 的边是 **[前置, 后继]**
    #   （`src/shanghai_graph.py` 里 `pre[e["to"]].add(e["from"])` →
    #    `pre[后继].add(前置)` → 边写成 [前置, 后继]）
    #   原来直接 `edges.append([a, b])` 原样透传 —— **6,567 条边方向全反了**。
    #
    #   症状（用户报的）：在「上海的孩子学什么」里点开「二次函数」，
    #   右侧「后继 1 层」列的是「函数」「一次函数」——
    #   八上的函数是九上二次函数的**前置**，不是后继。
    #   左侧「先修 1 层」列的是「二次函数 y=ax²的图象」「二次函数模型」
    #   「二次函数一般式」—— 这些是学完二次函数**之后**才有的。
    #
    #   实测（浏览器里查 KG.pre / KG.unlocks）：
    #   修之前 pre[二次函数] = {二次函数y=ax²的图象, 二次函数一般式, 二次函数模型}
    #                    unlocks[二次函数] = {函数, 一次函数, 二次函数与一元二次方程的联系}
    #   修之后 pre[二次函数] = {函数, 一次函数}   ✓
    #          unlocks[二次函数] = {二次函数y=ax²的图象, ...} ✓
    #
    #   **方向反了是最难发现的 bug** —— 页面照常渲染，
    #   只是每一句话都在说反，而且「看着还挺通顺」。
    edges = []
    indeg = collections.Counter()
    for e in sg["edges"]:
        pre_id, suc_id = e[0], e[1]
        pre, suc = idx_of.get(pre_id), idx_of.get(suc_id)
        if pre is None or suc is None:
            continue
        # sg 的 [0] 是前置、[1] 是后继 → payload 要 [后继, 前置]
        edges.append([suc, pre, e[2] if len(e) > 2 else 0, 0])
        # 被依赖度：前置被这个后继依赖
        indeg[pre_id] += 1
    print(f"边 {len(edges)} 条")

    # ── 被依赖度（cen）回填 ────────────────────────────────
    # 模板里 `r = (1.5 + n.cen*7.5) / k * 0.52` ——
    # **cen 直接决定点的大小**（被依赖得多的概念画得大）。
    # 上海站原来硬编码 0.0 → 所有点都是最小半径（0.78px），
    # 视觉上「点几乎看不见」，
    # 实测圆点像素占比只有 1.48%（主站 30.67%）——
    # 一半的原因是节点少，一半是点太小。
    #
    # 算法跟主站一致（`build_viz.py` 的 indeg）：
    # 主站是 `prereq[后继].add(前置)` 然后 `indeg[前置] += 1`
    # —— **indeg 统计的是「前置」的入度**（被多少个后继依赖）。
    mx = max(indeg.values()) if indeg else 1
    for i, (nid, _v) in enumerate(ordered):
        payload_nodes[i][8] = round(indeg.get(nid, 0) / mx, 4)


    # ── 5. 教材公式 / 图 / 难点（沪教版的）────────────────────
    # **按 (书, 页) 存** —— 按书存的话每个节点会挂上整本书的公式。
    # **公式/图/习题去概念层取**（data/concept-vision-sh.jsonl），
    # 不从图谱文件里抄 —— 抄一份就大一倍，两份还可能对不上。
    CVIS = BASE / "data" / "concept-vision-sh.jsonl"
    cvis = {}
    if CVIS.exists():
        for line in CVIS.open(encoding="utf-8"):
            if not line.strip():
                continue
            r = json.loads(line)
            cvis[r["id"]] = r
    node_vision = {}
    node_hard = {}
    for n in nodes_src:
        fs, gs, bz = [], [], ""
        hn, hstem = 0, ""
        cv = cvis.get(n["id"]) or {}
        for bid, b in (n.get("books") or {}).items():
            cb = (cv.get("books") or {}).get(bid) or {}
            for f in (cb.get("formulas") or []):
                p = to_plain(f)
                if p and p not in fs:
                    fs.append(p)
            for g in (cb.get("figures") or []):
                d = to_plain((g.get("description") or "").strip())
                if d:
                    if len(d) > 160:
                        d = d[:158] + "…"
                    gs.append([g.get("caption", ""), d, g.get("provenance", "described")])
            for ex in (cb.get("exercises") or []):
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

    # ── 5b. 教材原话（OCR 原文层）────────────────────────────────
    #
    # **教材自己写的定义句** —— 最硬的一手材料。
    # 人教站有 401 个概念带着它，上海站原来一个都没有。
    #
    # **有预算**：原话是句子，一个概念能有好几句，全放进去 payload 就爆了。
    # 先放定义句（最值钱），再放定理句，放到 500 KB 为止。
    TEXT_BUDGET = 500_000
    text = {}
    CTXT = BASE / "data" / "concept-text-sh.jsonl"
    if CTXT.exists():
        cands = []
        for line in CTXT.open(encoding="utf-8"):
            if not line.strip():
                continue
            r = json.loads(line)
            j = idx_of.get(r.get("id", ""))
            if j is None:
                continue
            q = r.get("quotes") or []
            if not q:
                continue
            # 定义句排最前
            q = sorted(q, key=lambda x: 0 if r.get("hasDefinition") else 1)
            cands.append((j, [x[:180] for x in q[:2]]))
        # **按值填**：先放有定义句的
        cands.sort(key=lambda c: 0 if c[1] else 1)
        used = 0
        for j, q in cands:
            if not q:
                continue
            sz = sum(len(x.encode("utf-8")) for x in q) + 12
            if used + sz > TEXT_BUDGET:
                continue
            used += sz
            text[j] = q
    print(f"教材原话 {len(text)} 个概念 · {used//1024} KB / 预算 {TEXT_BUDGET//1024} KB")

    # ── 6. payload ────────────────────────────────────────────
    by_subject = collections.Counter()
    for x in payload_nodes:
        by_subject[x[3]] += 1
    n_sh = sum(1 for n in nodes_src if n["kind"] == "sh")
    # ── 上下位：图谱里 855 对落在上海节点集内 ─────────────────
    # 不接的话卡片上「更一般的概念」永远是空的。
    isa = []
    for a, b in (sg.get("isa") or []):
        ja, jb = idx_of.get(a), idx_of.get(b)
        if ja is not None and jb is not None:
            isa.append([ja, jb])
    print(f"上下位 {len(isa)} 对")

    # ── 人教版对照位 ──────────────────────────────────────────
    # 「这个概念在沪教版是第几节，在人教版是第几节」——
    # 上海的孩子手上是沪教版，但参考书、习题册常常按人教版编。
    alt_pos = {}
    for nid, i in idx_of.items():
        n = node_units[nid][0]
        if n.get("kind") != "sh":
            continue        # 前置补充本身就是人教概念，不用再对照自己
        if n.get("rjbBook"):
            alt_pos[i] = [["人教版", n["rjbBook"], ""]]
    print(f"人教版对照位 {len(alt_pos)} 个")

    payload = {
        "nodes": payload_nodes,
        "edges": edges,
        "isa": isa,
        "chs": chs,
        "cns": cns,
        "altpos": alt_pos,
        "text": text,
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
    # **payload 有预算** —— 数据层全留，页面层精选。
    # 概念一多，公式和图描述是按节点堆起来的，页面会越滚越大。
    # 超预算就是「该少塞点东西了」的信号，不是「硬盘装得下就没事」。
    # **2.6 MB** —— 主站的 payload 已经 2.3 MB、成品页 3.6 MB，
    # 上海站比主站小，没有理由卡在 1.6 MB。
    # 真正的约束是「单文件、不加载外部资源」，不是文件大小。
    BUDGET = 2_600_000
    if len(blob) > BUDGET:
        raise SystemExit(f"payload {len(blob)//1024} KB 超过预算 {BUDGET//1024} KB —— "
                         f"先查是不是公式/图描述没截够")
    print(f"payload {len(blob)//1024} KB / 预算 {BUDGET//1024} KB")
    html = TPL.read_text(encoding="utf-8").replace("__DATA__", blob)

    # ── 7. 文案：换成上海口径 ──────────────────────────────────
    # **替换失配即中止** —— 一条文案没命中就报出来，不让它静默留在页面上。
    GRADE_MAP = ("const GRADE_ZH=" + json.dumps(GRADE_ZH, ensure_ascii=False) + ";\n"
                 # **挂到 window** —— 学习路径面板在 IIFE 外面，够不着 IIFE 里的常量。
                 "window.GRADE_ZH=GRADE_ZH;\n")
    COPY = [
        ("美英课程标准 · ", "按上海教材排序 · "),
        # **GRADE_ZH 要在全局** —— 卡片眉标和轴标签两处都要用它，
        # 塞进画轴的函数里的话卡片那边就 ReferenceError。
        ("const SUBJ = D.subjects, ACC = D.acc;",
         "const SUBJ = D.subjects, ACC = D.acc;\n" + GRADE_MAP),
        ("<h1>全世界孩子<br>在<em>学什么。</em></h1>",
         "<h1>上海的孩子<br>在<em>学什么。</em></h1>"),
        ("<title>全世界孩子在学什么 · ", "<title>【上海版】上海孩子在学什么 · "),
        ("这根锥形从 4 岁长到 15 岁——越往上，概念越大越抽象。",
         "这根锥形从小学一年级长到高三——越往上，概念越大越抽象。"),
        ("高度是年龄", "高度是年级"),
        ("共 <b>__N_TOPIC__</b> 个知识点（另有 <b>__N_SELF__</b> 个我们补的能力节点与自建概念），其中 <b>__N_CORE__</b> 个属于 9–10 岁核心",
         "上海教材里出现的 <b>__N_TOPIC__</b> 个知识点，我们另外补了 <b>__N_SELF__</b> 个它们的前置概念（灰点），其中 <b>__N_CORE__</b> 个是初中"),
        ("只看 9–10 岁", "只看初中"),
        ("<span class=\"hi\">9–10 岁核心</span>", "<span class=\"hi\">初中</span>"),
        ("<span>低年级基础</span>", "<span>其他学段</span>"),
        # ⚠️ 模板里是 `kgEsc(n.evn)` —— 0834c38（ISSUE-45 的 XSS 修复）
        #    给 innerHTML 插值补了转义，但**漏改了这里的 COPY 列表**，
        #    于是这个构建脚本从那次提交起就构建不出来（实测：文案未命中 → 构建中止）。
        ("'<span>' + kgEsc(n.evn) + ' 条掌握证据</span><span>重要度 '",
         "'<span>课程要求：' + n.evn + '</span><span>被依赖度 '"),
        ("ctx.fillText('age ' + age, sx, sy);",
         "ctx.fillText(GRADE_ZH[age] || age, sx, sy);"),
        # **出处**：人教版那一页写的是「人教版教材排序」，上海版得说清楚是沪教版。
        ("K12-KGraph 本身是跨国的知识点集，这里按<b>人教版</b>教材排序 —— 两套是分开的，留着做对照。",
         "K12-KGraph 本身是跨国的知识点集，这里按<b>沪教版/沪科版</b>教材排序 —— 节点、页码、公式全部来自上海教材本身。"),
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
