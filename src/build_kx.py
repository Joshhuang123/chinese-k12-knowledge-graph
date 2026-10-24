#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
人教版《小学科学》独立站点 —— `kx.html`

这是**基于一手教材数据自建**的第三站：
- 主站      人教版教材，初中到高中（上游 K12-KGraph）
- 上海站    沪教版/沪科版，67 本（上游 + 上海教材）
- **本站在这里** 人教版《小学科学》1上~6下 12 本，**小学阶段**
  —— 上游图谱小学段只有数学，物化生一个都没有（上游 issue #10），
  所以这一站的节点**不是**从上游来的，是从**教材自己的目录 + 正文**来的。

跟另外两站的关系
----------------
**互补，不是重复**：主站给初中到高中，这一站给小学。
小学科学的 68 个概念里，11 个能对齐上游（同一个知识点在两套教材里都有），
那 11 个显示上游的册次；57 个是小学特有，上游没有。

边的来源码必须能区分
--------------------
| 来源码 | 含义 | 页面上 |
|---|---|---|
| 0 上游 | 上游图谱的先修关系 | 硬数据徽标 |
| **8 教材序** | **教材编者排的教学先后** | **独立徽标，不能冒充先修关系** |

「教材顺序 ≠ 先修关系」是这个项目自己的结论（s5 那期视频专门讲了这事），
页面上的边不能把两者混为一谈 —— 否则就是在自己拆自己的台。

跑法：python3 src/build_kx.py
"""
from __future__ import annotations

import collections
import json
import pathlib
import re
import sys

BASE = pathlib.Path("/Users/huangjunhai/Documents/个人/项目/中文知识图谱")
TPL = BASE / "viz" / "template.html"
KG = BASE / "data" / "kx-graph.json"
SECTIONS = BASE / "data" / "kx-sections.json"
TOC = BASE / "data" / "kx-toc.json"
KXVIS = BASE / "data" / "vision-pages-kx.jsonl"
KXTXT = BASE / "data" / "kx-ocr.jsonl"
OUT = BASE / "kx.html"

# 学科配色（跟主站/上海站同一套视觉语言）
SUBJECTS = [
    ("science", "小学科学", "#ffd166"),
]
GRADE_ZH = {i: f"{c}年级" for i, c in enumerate("一二三四五六", 1)}
ACC = 0.6


def mention(concept: str, sent: str) -> bool:
    """这句话有没有提到这个概念。

    概念名常带修饰：「植物的生命周期」的核心词是「生命周期」，
    「相互依存的生命世界」的核心词是「生命」。
    所以除了全名，还要拿**去掉修饰语的核心词**去卡。
    """
    if concept in sent:
        return True
    # 核心词：去掉「……的」前面的修饰语
    core = concept.split("的")[-1] if "的" in concept else concept
    if len(core) >= 2 and core in sent:
        return True
    # 再退一步：取最后两个字（「生命周期」→「周期」不太行，得 3 字以上）
    if len(core) >= 3 and core[-3:] in sent:
        return True
    return False


def longest_han(s: str) -> str:
    """取最长的**连续汉字串**（可含中文标点与空格）。

    为什么不用「汉字占比」：OCR 出来的一句可能是
    「人民力床站社 人 拓展活动 人 习 下 使用推力和拉力 站 区 人 下 1 推力和拉力是生活中 常见的力」——
    汉字占比不低，但前半段全是**版式噪声**（页眉页脚 + 拼音 + 插图标注）。
    取最长连续汉字串才能拿到真正的正文那句。
    """
    best = ""
    cur = ""
    for ch in s:
        if "一" <= ch <= "鿿" or ch in "，。、；：？！「」《》（）":
            cur += ch
            if len(cur) > len(best):
                best = cur
        else:
            cur = ""
    return best.strip("，。、；：？！「」《》（） ")


def pages_of_section(toc: dict, book: str, section: str) -> list[int]:
    """某一节覆盖的**扫描页序号**列表。

    节的页范围 = 目录里这一节的起始页 → 下一节起始页 - 1
    （**印刷页码**，转扫描序号时要加偏移）。

    「单元回顾」也算一节 —— 它有自己的页（复习页），
    排除掉会让某些概念的正文页找不到。
    """
    off = toc[book].get("_offset", 0)
    seq = []
    for u in toc[book]["units"]:
        for s in u["sections"]:
            p = s.get("startPage")
            if isinstance(p, int):
                seq.append((p, s.get("name") or ""))
    seq.sort()
    out = []
    for i, (p, nm) in enumerate(seq):
        if nm != section:
            continue
        end = seq[i + 1][0] - 1 if i + 1 < len(seq) else p + 12
        out.extend(range(p + off, end + 1 + off))
        break
    return out


def main() -> int:
    kg = json.load(open(KG, encoding="utf-8"))
    sections = json.load(open(SECTIONS, encoding="utf-8"))
    toc = json.load(open(TOC, encoding="utf-8"))

    src_nodes = kg["nodes"]
    print(f"源节点 {len(src_nodes)}")

    # ── 教材位置（每个节点的节/页）────────────────────────────
    # 上海站用「units」结构（每本书的单元链），
    # 这里是**教材的节**（一节一个知识点），粒度更细。
    units = []
    for bk in sorted(toc):
        off = toc[bk].get("_offset", 0)
        for u in toc[bk]["units"]:
            for s in u["sections"]:
                units.append({
                    "bookId": bk, "chapter": "", "chapterName": "",
                    "section": s.get("name") or "", "sectionName": s.get("name") or "",
                    "page": s.get("startPage"), "unit": u.get("name") or "",
                    "unitName": u.get("name") or "",
                    "scanPage": (s.get("startPage") or 0) + off,
                })
    print(f"教材节 {len(units)}")

    # ── 节点 ────────────────────────────────────────────────
    # 节点槽位（跟上海站一致，模板按这个契约读）：
    # [i, 名称, 英文, 学科下标, 教材位置串, id, 年级层, 年级层, 依赖度,
    #  核心标记, 描述, 课程要求, 前置章下标, 后继章下标, 单元下标, 学段]
    #
    # **依赖度 cen = 被多少条边指向（归一化）** ——
    # 全 0 的话点会小到看不见（图上就只剩虚线，没有点）。
    # 跟主站同一口径：被依赖多的点更大更亮。
    indeg = collections.Counter()
    for e in kg["edges"]:
        indeg[e["to"]] += 1
    mx = max(indeg.values()) if indeg else 1

    idx_of = {}
    payload_nodes = []
    for i, n in enumerate(src_nodes):
        idx_of[n["id"]] = i
        kx = n["kxSections"][0] if n["kxSections"] else {}
        bookZh = kx.get("bookZh", "")
        unit = kx.get("unit", "")
        section = kx.get("section", "")
        # 教材位置串：卡片眉标显示用
        dz = f"{bookZh}·{unit} › {section}" if unit and section else \
             (f"{bookZh}·{section}" if section else bookZh)
        desc = n.get("summary") or ""
        if n["kind"] == "up":
            # 对齐上游的：**两个位置都要显示** ——
            # 「上游标在七上，但小学科学一上就在教」正是这一站最该让人看见的事。
            # 所以写成「一上·家养动物 › 更多的家养动物（上游：七上）」——
            # 上游册次放括号里当注脚，主位是小学的位置。
            dz = f"{dz}（上游：{n['upBookZh']}）"
        payload_nodes.append([
            i, n["name"], "", 0, dz, n["id"],
            n["grade"], n["grade"], round(indeg[n["id"]] / mx, 4),
            1 if n["kind"] == "kx" else 0,   # core = 小学特有（「只看小学特有」筛选用）
            desc, "—",
            [], [], -1, 0,
        ])
    print(f"节点 {len(payload_nodes)} 个")

    # ── 边 ──────────────────────────────────────────────────
    # [后继, 先修, 来源, 可疑]
    #
    # **方向别搞反** —— 模板是 `pre.get(t).push([p])`，
    # 也就是 **e[0] = 后继，e[1] = 前置**。
    # 我这份数据文件里写的是 {"from": 前置, "to": 后继}（语义更清楚），
    # 所以这里要**交换一下**再塞进 payload。
    # 方向反了的话，磁力的前置（推力和拉力）会跑到它的后继槽里 ——
    # 症状是「学习路径」面板说「往回 4 层没找到任何前置」，
    # 而明明有一个教材序前置在那儿。
    edges = []
    for e in kg["edges"]:
        a = idx_of.get(e["from"])       # 前置
        b = idx_of.get(e["to"])         # 后继
        if a is None or b is None:
            continue
        edges.append([b, a, e["src"], 0])
    print(f"边 {len(edges)} 条")

    # ── 单元链（chs / cns）─────────────────────────────────
    # 模板契约：cns[i] = [单元名, 册次, 学科下标, 里面第一个可点的概念下标]
    # 这里的「单元」= 教材的一节（粒度比章细）
    chs = []      # [章名, 册次]
    cns = []      # [单元名, 册次, 学科下标, 首个概念下标]
    first_concept = {}
    for u in units:
        key = (u["bookId"], u["section"])
        # 这一节里有没有我们的节点
        ids_in = [idx_of[n["id"]] for n in src_nodes
                  if any(r["book"] == u["bookId"] and r["section"] == u["section"]
                         for r in n["kxSections"])]
        first = ids_in[0] if ids_in else -1
        if first >= 0:
            first_concept.setdefault((u["bookId"], u["section"]), first)
        cns.append([u["unit"] or u["section"], u["bookId"].replace("s6-", ""), 0, first])
        chs.append([u["section"], f"{u['bookId'].replace('s6-','')}·{u['unit']}"])
    print(f"单元链 {len(cns)}")

    # ── 教材原话层（小学科学的 OCR 原文）─────────────────────
    # 概念原话：从 OCR 里找这个概念第一次出现的那句话
    #
    # **页码基准**：OCR 文件里存的是**扫描序号**，
    # 而 kx-sections 的 page 是**印刷页码** —— 两者差一个偏移
    # （3a 是 +5，4b/5b/6b 是 +3）。不换算就一条都查不到。
    text = {}
    ocr = {}
    if KXTXT.exists():
        for line in KXTXT.open(encoding="utf-8"):
            try:
                r = json.loads(line)
            except Exception:
                continue
            ocr[(r["book"], r["page"])] = r.get("text") or ""
    for n in src_nodes:
        # **在该节的页里找最干净的一句**，不是只看第一节页 ——
        # 第一节页常常是扉页/活动页，OCR 不一定干净。
        # 节的页范围 = 目录里这一节的起始页 → 下一节起始页 - 1
        cands = []
        for rec in n["kxSections"]:
            bk = rec["book"]
            off = toc[bk].get("_offset", 0)
            pgs = pages_of_section(toc, bk, rec["section"])
            for scan in pgs:
                t = ocr.get((bk, scan), "")
                if not t:
                    continue
                for sent in re.split(r"[。；\n]", t):
                    if n["name"] not in sent or len(sent) <= 6:
                        continue
                    # **教材给汉字注了拼音**，OCR 会把拼音一起读出来
                    # （「tai yang shsng」「ren shi chuan」…）。
                    # 那些片段要剔掉 —— 只留汉字和中英文字。
                    clean = re.sub(r"[A-Za-z]+(?:\s+[A-Za-z]+)*", " ", sent)
                    clean = re.sub(r"\s+", " ", clean).strip()
                    # **页眉页脚**（「人民教育出版社」+ 单元名 + 节名 + 页码）
                    # 会被 OCR 粘在正文前面 —— 「人民力床站社 人 拓展活动 人 习 下」。
                    # 这些是**版式噪声不是正文**，剔掉。
                    # **只清开头** ——「拓展活动」这类词出现在句中可能是真的小标题。
                    clean = re.sub(r"人民[力床证证折折杠杠]{0,3}出版社", "", clean)
                    clean = re.sub(
                        r"^(拓展活动|学习反思|学以致用|单元回顾|科学概念|思考|讨论|练习|观察|实验)"
                        r"[\s人习下]*", "", clean)
                    clean = re.sub(r"\s+", " ", clean).strip(" 　")
                    # **取最长的连续汉字片段** ——
                    # 「人民力床站社 人 拓展活动 人 习 下 使用推力和拉力 站 区 人 下 1 推力和拉力是生活中 常见的力」
                    # 整句汉字占比不低，但前半段全是版式噪声。
                    # 按汉字占比排序会选中这种**含噪声的长句**；
                    # 按「最长的连续汉字串」才能拿到真正的正文那句。
                    seg = longest_han(clean)
                    if len(seg) <= 6:
                        continue
                    # **原话必须提到这个概念** ——
                    # 「最长汉字串」会选到同页但不属于该概念的句子
                    # （「自然物」那节选到「我们可以任意制造大量的人造物吗」，
                    #  那是下一节「人工产品」的内容）。
                    # 拿概念名（或它的核心词）去卡一下，选中的才是**这一节的正文**。
                    if not mention(n["name"], seg):
                        continue
                    cands.append((len(seg), seg))
        if cands:
            # 汉字占比最高的那句
            cands.sort(key=lambda x: -x[0])
            text[idx_of[n["id"]]] = [cands[0][1][:180]]
    print(f"教材原话 {len(text)} 个概念")

    # ── 视觉层（小学科学的公式/图）──────────────────────────
    vision = {}
    if KXVIS.exists():
        for line in KXVIS.open(encoding="utf-8"):
            try:
                r = json.loads(line)
            except Exception:
                continue
            if not r.get("ok"):
                continue
            d = r.get("data") or {}
            fs = [f for f in (d.get("formulas") or []) if f][:6]
            gs = []
            for g in (d.get("figures") or [])[:1]:
                desc = (g.get("description") or "").strip()[:160]
                if desc:
                    gs.append([g.get("caption", ""), desc])
            # **视觉层的 book 是完整书号**（rjb-science-s6-1a），
            # 节点的 kxSections.book 是短名（s6-1a）—— 要用 graphBook 对齐。
            book = r.get("graphBook", "")      # 1a / 3b / 6b
            if not book:
                continue
            scan = r.get("page")          # **扫描序号**
            bk = f"s6-{book}"
            # 挂到该页所属概念上
            for n in src_nodes:
                for rec in n["kxSections"]:
                    if rec["book"] != bk:
                        continue
                    off = toc[bk].get("_offset", 0)
                    if rec["page"] + off != scan:
                        continue
                    j = idx_of[n["id"]]
                    if fs or gs:
                        cur = vision.setdefault(j, [[], [], ""])
                        for f in fs:
                            if f not in cur[0]:
                                cur[0].append(f)
                        for g in gs:
                            if g not in cur[1]:
                                cur[1].append(g)
                        cur[2] = r.get("bookZh", "")[:6]
    print(f"视觉层 {len(vision)} 个概念")

    # ── 学科（模板要的是对象：en / zh / c / n）────────────────
    # **不是三元组** —— 三元组的话图例会渲染成「undefined undefined」。
    by_subject = collections.Counter()
    for i, n in enumerate(payload_nodes):
        by_subject[n[3]] += 1
    subjects = [{"en": s[0], "zh": s[1], "c": s[2], "n": by_subject.get(i, 0)}
                for i, s in enumerate(SUBJECTS)]

    # ── payload ─────────────────────────────────────────────
    payload = {
        "nodes": payload_nodes,
        "edges": edges,
        "isa": [],          # 小学科学这一层没有上下位数据（不编）
        "chs": chs,
        "cns": cns,
        "altpos": {},
        "vision": vision,
        "visionAlt": {},
        "hard": {},
        "text": text,
        "kx": {},
        "subjects": subjects,
        "core": 0,
        "total": len(payload_nodes),
        "drawn": len(payload_nodes),
        "acc": ACC,
        "abi": [],
        "srczh": kg["srczh"],
        "selfbuilt": {"nodes": 0, "edges": 0},
        "aliases": {},
    }

    blob = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    BUDGET = 2_600_000
    if len(blob) > BUDGET:
        raise SystemExit(f"payload {len(blob)//1024} KB 超过预算 {BUDGET//1024} KB")
    print(f"payload {len(blob)//1024} KB / 预算 {BUDGET//1024} KB")
    html = TPL.read_text(encoding="utf-8").replace("__DATA__", blob)

    # ── 文案：换成小学科学口径 ───────────────────────────────
    # **替换失配即中止** —— 一条没命中就报出来。
    GRADE_MAP = ("const GRADE_ZH=" + json.dumps(GRADE_ZH, ensure_ascii=False) + ";\n"
                 "window.GRADE_ZH=GRADE_ZH;\n")
    COPY = [
        # eyebrow：**整行替换，必须排在片段替换之前** ——
        # 下面那条 COPY 会先把「美英课程标准 · 」改成「按人教版小学科学排序 · 」，
        # 顺序反了的话整行就匹配不上了（失配即中止，这是对的）。
        ("美英课程标准 · __N_TOPIC__ 个知识点 · __N_EDGE__ 条前置关系",
         "按人教版小学科学排序 · __N_TOPIC__ 个知识点 · __N_EDGE__ 条连线"
         "（__N_ORDER__ 条教材序 + __N_PRE__ 条真正的先修关系）"),
        ("const SUBJ = D.subjects, ACC = D.acc;",
         "const SUBJ = D.subjects, ACC = D.acc;\n" + GRADE_MAP),
        ("<h1>全世界孩子<br>在<em>学什么</em>。</h1>",
         "<h1>小学的孩子<br>在<em>学什么</em>。</h1>"),
        ("<title>全世界孩子在学什么 · ", "<title>【小学科学】小学孩子在学什么 · "),
        ("下面这根锥形从 4 岁长到 15 岁——越往上，概念越大越抽象。",
         "下面这根锥形从小学一年级长到六年级——越往上，概念越大越抽象。"),
        ("高度是年龄", "高度是年级"),
        ("共 <b>__N_TOPIC__</b> 个知识点（另有 <b>__N_SELF__</b> 个我们补的能力节点与自建概念），其中 <b>__N_CORE__</b> 个属于 9–10 岁核心",
         "人教版《小学科学》里出现的 <b>__N_TOPIC__</b> 个知识点，"
         "其中 <b>__N_CORE__</b> 个是小学特有、上游图谱里没有的<br>"
         "<b>虚线是「教材序」，不是先修关系</b> —— 编者先教哪个后教哪个"),
        ("只看 9–10 岁", "只看小学特有"),
        # 卡片眉标的两档：这一站是「小学特有 / 对齐上游」。
        # **只替换文字本身**（上面两条）—— 整句替换会跟它们打架：
        # 先改了文字，再去匹配整句就匹配不上了（失配即中止）。
        ("<span class=\"hi\">9–10 岁核心</span>", "<span class=\"hi\">小学特有</span>"),
        ("<span>低年级基础</span>", "<span>对齐上游</span>"),
        ("'<span>' + n.evn + ' 条掌握证据</span><span>重要度 '",
         "'<span>课程要求：' + n.evn + '</span><span>被依赖度 '"),
        ("ctx.fillText('age ' + age, sx, sy);",
         "ctx.fillText(GRADE_ZH[age] || age, sx, sy);"),
        ("s.zh + ' · ' + n.dz + ' · ' + n.a1 + '–' + n.a2 + ' 岁'",
         "s.zh + ' · ' + n.dz + ' · ' + GRADE_ZH[n.a1]"),
        ("> 数据来自中文 K12 知识图谱（人教版教材排序），每条边可查来源。",
         "> 数据来自人教版《小学科学》教材本身（12 本 / 1,036 页），每条边可查来源。"),
        ("K12-KGraph 本身是跨国的知识点集，这里按<b>人教版</b>教材排序 —— 两套是分开的，留着做对照。",
         "这一站<b>不依赖</b> K12-KGraph 的小学数据 —— 上游小学段只有数学，物化生一个都没有。"
         "节点全部来自人教版《小学科学》教材的目录与正文。"),
        # ── 这一站特有的说明：教材序 ≠ 先修关系 ──
        # **放在署名区（#attr），不塞进页头正文** ——
        # 页头是固定高度的区域，正文加长会把搜索框和署名顶到重叠
        # （第一版就撞了）。而且这段本来就是「数据来源」的说明，
        # 署名区才是它的位置。
        ("<span class=\"attr2\">边上的徽标分得出哪条来自数据集、哪条是我们补的。<br>",
         "<span class=\"attr2\">虚线的连线是<b>教材序</b>：编者先教哪个后教哪个，"
         "<b>不是先修关系</b>（教材大量回顾旧例，那是衔接不是前置）。"
         "实线才是真正的先修关系。<br>"
         "边上的徽标分得出哪条来自数据集、哪条是我们补的。<br>"),
        # **#attr 改成随内容流** ——
        # 它默认是 position:fixed; bottom:192px（固定在离底 192px）。
        # 主站/上海站的 #head 内容短，够不着它；
        # 这一站的 count 行多了一行「虚线是教材序」，head 变高就**撞上了**，
        # 搜索框被署名文字压住。
        # 改成 static 后它跟着内容走，不会撞。
        ("#attr{position:fixed;bottom:192px;left:38px;",
         "#attr{position:static;margin-top:14px;left:38px;"),
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
        raise SystemExit(f"构建中止：{len(missed)} 条文案没匹配上")

    n_self = len(payload_nodes) - payload["total"]
    n_kx = sum(1 for n in payload_nodes if n[9] == 1)   # core=1 = 小学特有
    n_order = sum(1 for e in edges if e[2] == 8)
    n_pre = len(edges) - n_order
    html = (html.replace("__N_TOPIC__", f"{payload['total']:,}")
                .replace("__N_SELF__", f"{n_self:,}")
                .replace("__N_EDGE__", f"{len(edges):,}")
                .replace("__N_ORDER__", f"{n_order:,}")
                .replace("__N_PRE__", f"{n_pre:,}")
                .replace("__N_CORE__", f"{n_kx:,}"))
    OUT.write_text(html, encoding="utf-8")
    print(f"\n{payload['total']} 小学科学知识点 · {len(edges)} 边 · {len(cns)} 节")
    print(f"→ {OUT}（{len(html)//1024} KB）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
