#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ISSUE-10: 人教版《小学科学》→ 上游图谱概念匹配 —— `data/concept-vision-kx.jsonl`

这一层解决什么
--------------
上游 K12-KGraph 的图谱里，**小学阶段只有数学**（1,182 个概念），
物理 / 化学 / 生物学在小学一个都没有 —— 这就是上游 issue #10。
所以「小学科学的概念」不可能是「上游的某个节点」。

那些概念去哪了？—— **在上游的初中/高中册次里**。
同一个概念，上游把它标在初中八上（热胀冷缩）、初中九上（保护空气），
但小学科学三上就在教它了。

所以本层做的事（跟上海站同一思路）：
  **教材上的概念 → 挂到上游那个概念上，同时标出它在小学科学哪本书哪一节哪一页。**
  图谱里节点还是那个节点（初中八上的「热胀冷缩」），
  多出来的是「它在小学科学三年级上册第 2 页『磁铁的磁极』」这条教材位置。

这样：
- **图谱结构不变**（没有凭空造节点，先修边还是上游那套）
- **补上了小学阶段的教材位置**（原来这一段是空的）
- 用户看到的是「这个概念小学就该学，书上第几页」

四信号判别
----------
| 信号 | 含义 | 为什么可信 |
|---|---|---|
| **目录** | 概念名出现在这本书自己的目录（单元名/节名）里 | **教材自己写的目录**，是教材对「我教什么」的最直接声明 |
| **目录近似** | 概念名跟某个目录名相似度 ≥ 0.8 | 目录名的变体（「电路」vs「电与电路」） |
| **集中** | 该概念在这本书命中 ≥2 页，且占它在**全部 12 本小学科学**里命中数的 ≥1/3 | 概念在这本书里成片出现，而不是在别的书里 |
| **同册** | 概念的上游册次是**小学段**（1a~6b），且命中 ≥1 页 | 人教版的小学段跟初中段内容有重叠 |

**泛词不单独成立**：「力」「水」「声音」「光」「电」在 12 本书里到处出现，
它们不是「这本书教这个概念」的证据，只是这个概念是个泛词。
必须有目录或集中度撑腰。

**宁可少抽，不抽错** —— 抽错的定义会被当成教材原话。

用法：python3 src/vision_to_concepts_kx.py
"""
from __future__ import annotations

import collections
import difflib
import json
import pathlib
import re
import sys
import unicodedata

BASE = pathlib.Path(__file__).resolve().parent.parent
OCR = BASE / "data" / "kx-ocr.jsonl"
TOC = BASE / "data" / "kx-toc.json"
GRAPH = BASE / "data" / "normalized" / "graph.json"
OUT = BASE / "data" / "concept-vision-kx.jsonl"

MIN_HITS = 2
MIN_SHARE = 0.34
MIN_TOC_RATIO = 0.80

# 小学科学的候选概念来自哪几个学科。
# **K12-KGraph 里没有「科学」这个学科** —— 只有 math/physics/chemistry/biology。
# 小学科学是物理+化学+生物的合流（物质、生物、地球、技术），
# 所以候选集取这三个学科的全集。不这么分，一本都匹配不上。
SUBJECT_CANDIDATES = ["physics", "chemistry", "biology"]

# 小学段册次（上游只有数学占了 1a~6b）
ELEM_BOOKS = {"1a", "1b", "2a", "2b", "3a", "3b", "4a", "4b", "5a", "5b", "6a", "6b"}

# ── 学科特征词 ────────────────────────────────────────────
# **为什么需要**：上游图谱里「质量」有两个节点（物理八上 / 化学必修一），
# 「蛋白质」有三个（化学九下 / 生物七下 / 生物必修一）。
# 小学科学一册里同一个词可能对应好几个上游节点，
# 不消歧就会把「质量」同时挂到物理和化学上 —— 看着像两份证据，其实是一份。
#
# 判据：看**这一页的正文里**哪个学科的特征词多。
# 特征词按教材实际用语挑（小学科学的说法跟初中不一样，
# 比如「电路」在小学就是单元名，初中叫「电路及其应用」）。
SUBJECT_HINTS = {
    "physics": [
        "电路", "电池", "开关", "电流", "电压", "电阻", "导体", "绝缘", "灯泡",
        "磁铁", "磁极", "磁体", "磁力", "指南针", "杠杆", "滑轮", "轮轴", "斜面",
        "浮力", "力", "运动", "速度", "能量", "电能", "电动", "机械", "热",
        "光", "反射", "影子", "声音", "振动", "音调", "噪声", "温度", "热量",
        "燃烧", "能量转化", "风力", "水力", "太阳能",
    ],
    "chemistry": [
        "氧气", "二氧化碳", "空气", "水", "溶液", "溶解", "盐", "糖", "过滤",
        "蒸发", "凝固", "结晶", "酸", "碱", "金属", "生锈", "腐蚀", "燃烧",
        "化学反应", "质量", "体积", "密度", "混合物", "化合物", "物质",
    ],
    "biology": [
        "植物", "根", "茎", "叶", "花", "果实", "种子", "发芽", "光合作用",
        "呼吸", "消化", "吸收", "营养", "细胞", "动物", "昆虫", "鸟", "哺乳",
        "分类", "食物链", "生态", "环境", "人体", "器官", "骨骼", "肌肉",
        "血液", "心脏", "肺", "胃", "感官", "眼睛", "耳朵",
    ],
}

# **泛词**：这些词在任何一本小学科学里都会出现，
# 单独命中不构成「这本书教这个概念」的证据。
GENERIC = {
    "力", "水", "声音", "光", "电", "热", "气", "物体", "材料", "能量", "运动",
    "植物", "动物", "身体", "眼睛", "耳朵", "鼻子", "手", "工具", "自然", "生活",
    "科学", "观察", "实验", "研究", "变化", "性质", "结构", "作用", "方法", "现象",
}


def norm(s: str) -> str:
    """归一化：NFKC、去空白、去标点。"""
    s = unicodedata.normalize("NFKC", s or "")
    s = re.sub(r"[\s　]+", "", s)
    return re.sub(r"[（）()〔〕【】\[\]《》“”\"'’‘,，。.、:：;；!！?？\-—_/\\|]+", "", s)


def page_sections(toc: dict) -> list[tuple[int, int, str, str]]:
    """目录 → (起始页, 结束页, 单元名, 节名) 列表，按起始页排。

    **只收「节」，不收「单元」** ——
    单元也有 startPage（人教版是单元封面页那页），
    把它和节混在一个按页排序的列表里，边界判断会错位。

    **页码基准：印刷页码，不是扫描序号**。
    目录上印的页码（「磁铁的磁极 /2」）是**书里的页码**，
    而页图文件是按**扫描序号**排的（封面、版权、目录占了前几页）。
    3a 的偏移是 5：扫描 p7 = 印刷 2。
    **不换算就会整本错位** —— 目录说「食物的营养 /58」，
    扫描第 58 页其实是上一单元的单元回顾，
    换算后才知道「食物的营养」从扫描第 63 页开始。
    偏移量由 detect_offset() 从页脚数字**实测**得出，不写死。
    """
    off = toc.get("_offset", 0)
    out = []
    for u in (toc.get("units") or []):
        un = u.get("name") or ""
        for s in (u.get("sections") or []):
            p = s.get("startPage")
            if isinstance(p, int):
                # 印刷页码 → 扫描序号
                out.append((p + off, un, s.get("name") or ""))
    out.sort()
    res = []
    for i, (p, un, sn) in enumerate(out):
        end = out[i + 1][0] - 1 if i + 1 < len(out) else 10 ** 6
        res.append((p, end, un, sn))
    return res


def detect_offset(book: str, ocr: dict) -> int:
    """**实测**「扫描序号 - 印刷页码」的偏移量。

    办法：正文页的页脚印着印刷页码，OCR 能读出来。
    统计哪个差值出现得最多，就是这一本的偏移。
    （3a 是 5，4b/5b/6b 是 3 —— **不能写死**，每本的前置页数不一样。）

    `ocr` 是 {book: {page: text}}。
    """
    c = collections.Counter()
    for pg, t in (ocr.get(book) or {}).items():
        if pg < 6 or pg > 60:
            continue
        m = re.search(r"(?:^|\s)(\d{1,3})(?:\s|$)", (t or "")[-70:])
        if not m:
            continue
        v = int(m.group(1))
        if 0 < pg - v < 14:
            c[pg - v] += 1
    if not c:
        return 0
    off, n = c.most_common(1)[0]
    # 票数太少就不信（宁可返回 0 让人来查，也不要瞎猜）
    return off if n >= 5 else 0


def main() -> int:
    for p in (OCR, TOC, GRAPH):
        if not p.exists():
            print(f"缺 {p}")
            return 1

    graph = json.load(open(GRAPH, encoding="utf-8"))
    info = {n["id"]: n for n in graph["nodes"]}

    toc_all = json.load(open(TOC, encoding="utf-8"))
    ocr_pages = collections.defaultdict(dict)
    for line in OCR.open(encoding="utf-8"):
        try:
            r = json.loads(line)
        except Exception:
            continue
        ocr_pages[r["book"]][r["page"]] = r.get("text") or ""
    print(f"OCR 页数 {sum(len(v) for v in ocr_pages.values())}，目录 {len(toc_all)} 本")

    # ── 页码偏移：印刷页码 ↔ 扫描序号 ──────────────────────
    # **必须实测，不能写死** —— 3a 偏移 5，4b/5b/6b 偏移 3。
    # 不换算的话，「食物的营养 /58」会被当成扫描第 58 页，
    # 实际那本从扫描第 63 页才开始 —— 整本错位 5 页。
    print("\n页码偏移（印刷页码 → 扫描序号）：")
    for book in sorted(toc_all):
        off = detect_offset(book, ocr_pages)
        toc_all[book]["_offset"] = off
        print(f"  {book}: +{off}")
    TOC.write_text(json.dumps(toc_all, ensure_ascii=False, indent=1), encoding="utf-8")

    # 候选概念
    cand = []
    for n in graph["nodes"]:
        if n.get("subject") not in SUBJECT_CANDIDATES:
            continue
        nm = norm(n.get("name") or "")
        if len(nm) < 2:
            continue
        cand.append({
            "id": n["id"], "name": n.get("name") or "", "n": nm,
            "subject": n.get("subject"),
            "book": n.get("book") or "", "bookZh": n.get("bookZh") or "",
            "stage": n.get("stage") or "", "grade": n.get("grade") or 0,
            "def": ((n.get("props") or {}).get("definition") or "")[:200],
        })
    print(f"候选概念 {len(cand)} 个")

    # 每本书：页文本 → 概念命中
    # 命中判据：概念名（归一化后）作为**子串**出现在页文本里。
    # 为什么要子串而不是整词匹配：OCR 出来的中文没有词边界，
    # 而且「磁极」出现在「磁铁的磁极」「两个磁极相互吸引」里都是有效证据。
    hits = collections.defaultdict(lambda: collections.defaultdict(set))
    # 命中时的页 → 所属节
    for book, pages in ocr_pages.items():
        if book not in toc_all:
            continue
        secs = page_sections(toc_all[book])
        starts = [s[0] for s in secs]
        import bisect
        for c in cand:
            if len(c["n"]) < 2:
                continue
            for pg, txt in pages.items():
                if c["n"] in txt:
                    hits[book][c["id"]].add(pg)

    # 全书命中总数（算集中度）
    total_hits = collections.Counter()
    for book, m in hits.items():
        for cid, pgs in m.items():
            total_hits[cid] += len(pgs)

    # 目录信号
    toc_names = {}
    for book, toc in toc_all.items():
        names = []
        for u in (toc.get("units") or []):
            names.append(u.get("name") or "")
            for s in (u.get("sections") or []):
                names.append(s.get("name") or "")
        toc_names[book] = [norm(x) for x in names if norm(x)]

    # ── 页 → 学科倾向 ────────────────────────────────────────
    # 用于**同名概念消歧**：上游「质量」有物理/化学两个节点，
    # 「蛋白质」有三个 —— 不消歧就会把一份证据当成两份。
    subj_score = {}
    for book, pages in ocr_pages.items():
        score = collections.Counter()
        for txt in pages.values():
            for sub, words in SUBJECT_HINTS.items():
                score[sub] += sum(1 for w in words if w in txt)
        subj_score[book] = score

    # 先算出每本书每个候选的命中页与信号
    raw = {}
    for book in sorted(toc_all):
        tocset = toc_names[book]
        m = hits.get(book, {})
        for c in cand:
            cid = c["id"]
            pgs = m.get(cid)
            if not pgs:
                continue
            n_hit = len(pgs)
            in_toc = c["n"] in tocset
            near = False
            if not in_toc:
                for tn in tocset:
                    if difflib.SequenceMatcher(None, c["n"], tn).ratio() >= MIN_TOC_RATIO:
                        near = True
                        break
            concentrated = (n_hit >= MIN_HITS and
                            n_hit / max(1, total_hits[cid]) >= MIN_SHARE)
            same_elem = c["book"] in ELEM_BOOKS
            generic = c["n"] in GENERIC

            if in_toc or near:
                sig = "目录"
            elif concentrated:
                sig = "集中"
            elif same_elem and not generic:
                sig = "同册"
            elif generic and n_hit >= 3:
                sig = "泛词弱证据"
            else:
                continue
            raw.setdefault((book, c["name"]), []).append({
                "c": c, "pgs": sorted(pgs), "sig": sig, "n": n_hit,
            })

    # ── 同名消歧 ────────────────────────────────────────────
    # 同一本书里同名但不同上游节点 → 挑**学科最贴**的那个。
    # 判据：命中页里该学科特征词最多。
    kept = []
    for (book, name), lst in raw.items():
        if len(lst) == 1:
            kept.append((book, lst[0]))
            continue
        sc = subj_score[book]
        def aff(item):
            sub = item["c"]["subject"]
            # 该学科的特征词命中页数（用页数占比近似）
            hit_pages = 0
            pages = ocr_pages.get(book, {})
            for pg in item["pgs"]:
                t = pages.get(pg, "")
                best = 0
                for s2, words in SUBJECT_HINTS.items():
                    v = sum(1 for w in words if w in t)
                    best = max(best, v)
                if best > 0 and sum(1 for w in SUBJECT_HINTS[sub] if w in t) >= best * 0.6:
                    hit_pages += 1
            return (hit_pages, sc.get(sub, 0), item["n"])
        lst.sort(key=aff, reverse=True)
        best_sub = lst[0]["c"]["subject"]
        # 只保留学科跟最佳项一致的（其余是真·不同学科的同名概念，扔掉）
        for it in lst:
            if it["c"]["subject"] == best_sub:
                kept.append((book, it))

    # ── 输出（同一节点跨多本书合并）────────────────────────
    merged = collections.defaultdict(list)
    for book, it in kept:
        merged[it["c"]["id"]].append((book, it))

    out_rows = []
    stats = collections.Counter()
    for cid, lst in merged.items():
        c = lst[0][1]["c"]
        books = sorted({b for b, _ in lst})
        allpgs = sorted({p for _, it in lst for p in it["pgs"]})
        # **纯 ASCII 的概念名要更严** ——
        # OCR 的噪声里会混进英文字母串（「mRNAESS xp」「INNRNASNANAS」里都有 RNA），
        # 那是乱码不是教材内容。3b 的「RNA」就是栽在这。
        # 中文概念名不会有这个问题（汉字串在乱码里的概率低得多）。
        # 判据：纯 ASCII 名至少命中 3 页才认。
        if re.fullmatch(r"[A-Za-z0-9 ]+", (c["name"] or "").strip()) and len(allpgs) < 3:
            stats["纯ASCII噪声丢弃"] += 1
            continue
        sechits = []
        units_all, sects_all = set(), set()
        for book, it in lst:
            secs = page_sections(toc_all[book])
            starts = [s[0] for s in secs]
            import bisect
            pages = ocr_pages.get(book, {})
            for pg in it["pgs"]:
                i = bisect.bisect_right(starts, pg) - 1
                if i >= 0:
                    s = secs[i]
                    sechits.append({"book": book, "page": pg,
                                    "unit": s[2], "section": s[3]})
                    units_all.add(s[2])
                    sects_all.add(s[3])
        sigs = {it["sig"] for _, it in lst}
        sig = "目录" if "目录" in sigs else ("集中" if "集中" in sigs else
                                            ("同册" if "同册" in sigs else "泛词弱证据"))
        # **sections / units 要按书分组** —— 跨书合并后如果拉平成一个集合，
        # 会出现「节约用水在 2a 和 4a，它的 section 是『声音的产生』」
        # 这种串台（2a 里根本没有声音那节）。
        # **「单元回顾」这类复习页不算「一节课」** ——
        # 它复习整个单元，概念在那页出现是「回顾里提了一句」，
        # 不是「这一节讲这个」。
        # 不排除的话，「导体/电流/绝缘体/磁体/磁场」全挂到「单元回顾」，
        # 而它们真正在的节是「手电筒的秘密」「检测电路」那些。
        def is_review(sn):
            return (not sn) or ("回顾" in sn) or ("复习" in sn) or ("总结" in sn)

        per_book = {}
        for book, it in lst:
            secs = page_sections(toc_all[book])
            starts = [s[0] for s in secs]
            import bisect
            sec_starts = {}
            off = toc_all[book].get("_offset", 0)
            for u in (toc_all[book].get("units") or []):
                for s2 in (u.get("sections") or []):
                    if isinstance(s2.get("startPage"), int) and s2.get("name"):
                        # 印刷页码 → 扫描序号（跟 page_sections 同一套基准）
                        sec_starts[s2["name"]] = s2["startPage"] + off
            # **单元和节要同源，而且要取「命中最多」的那一节** ——
            # 分开取 units[0] / sects[0] 会串台；
            # 取「第一命中页」也会错：
            # 「杠杆」在 5b 命中好几页，最小的那页是第 3 页（昼夜与四季），
            # 但「杠杆」真正在的是「简单机械 › 杠杆」（第 42 页）。
            # **判据：概念在哪一节出现得最多，就挂哪一节。**
            sec_hits = collections.Counter()
            sec_unit = {}
            units_b = set()
            sects_b = set()
            for pg in it["pgs"]:
                i = bisect.bisect_right(starts, pg) - 1
                if i >= 0:
                    units_b.add(secs[i][2])
                    sects_b.add(secs[i][3])
                    # **复习页不进 sec_hits** —— 「单元回顾」复习整个单元，
                    # 概念在那儿出现不代表「这一节讲它」。
                    # 不排除的话「导体/电流/绝缘体/磁体/磁场」全挂到「单元回顾」。
                    if not is_review(secs[i][3]):
                        sec_hits[secs[i][3]] += 1
                        sec_unit[secs[i][3]] = secs[i][2]
            units_b = sorted(units_b)
            sects_b = sorted(sects_b)

            def _sec_of(pg):
                i = bisect.bisect_right(starts, pg) - 1
                return secs[i][3] if i >= 0 else ""

            first_unit = first_sect = ""
            # **「单元回顾」这类复习页不算「一节课」** ——
            # 它复习整个单元，概念在那页出现是「回顾里提了一句」，
            # 不是「这一节讲这个」。
            # 不排除的话，「导体/电流/绝缘体/磁体/磁场」全挂到「单元回顾」，
            # 而它们真正在的节是「手电筒的秘密」「检测电路」那些。
            # **最强的判据：概念名出现在某一节的标题里 → 直接挂那一节。**
            # 教材的节标题页必然印着这个词（「杠杆 42」那页），
            # 而且这是教材自己声明「这一节讲这个」。
            #
            # **要包含匹配，不能只等号** ——
            # 教材的节名常常多几个字：
            #  「磁铁的磁极」⊃「磁极」｜「植物的光合作用」⊃「光合作用」
            #  「空气的热胀冷缩」⊃「热胀冷缩」
            # 等号匹配的话这三个全落空，会挂到「指南针」「危险的来客」
            # 这种只是「顺带提到」它的节上。
            nm = c["name"]
            for u in (toc_all[book].get("units") or []):
                for s2 in (u.get("sections") or []):
                    sn = norm(s2.get("name") or "")
                    if not sn or is_review(sn):
                        continue
                    hit = sn == nm
                    if not hit and len(nm) >= 3:
                        # **3 字以上才允许任意包含匹配** ——
                        # 「力」「能量」这种 2 字词包含匹配太松
                        # （「力」会落在「电力」「压力」上）。
                        hit = nm in sn
                    if not hit and len(nm) == 2:
                        # **2 字词只认前缀/后缀**：
                        # 「磁铁的磁极」以「磁极」结尾 ✓
                        # 「植物的光合作用」以「光合作用」结尾 ✓
                        # 「能量转化」以「能量」开头 —— 但那是另一个概念（「能量转化」），
                        # 所以**只认后缀**，不认前缀。
                        hit = sn.endswith(nm)
                    if hit:
                        first_sect = s2.get("name") or ""
                        first_unit = u.get("name") or ""
                        break
                if first_sect:
                    break
            if not first_sect and sec_hits:
                # **命中最多的一节**；并列时取**「命中页在该节内位置最靠前」**的那节。
                #
                # **为什么不能用绝对页距**：
                # 「电流」在 3a 命中两页 —— 「开关」节（节起 40，页 43）和
                # 「食物的营养」节（节起 58，页 60）。
                # 绝对距离是 3 对 2，按近的选就选到了「食物的营养」——
                # 电流明显是「家庭用电」单元的东西，不在「消化与呼吸」里。
                # **要看的是「命中页在该节里的相对位置」**：
                # 节的第一页就是这一节要讲的东西，后面是练习和应用，
                # 词还会零星出现（营养那页提到「蛋白质」「导体」做类比）。
                def score(s2):
                    n = sec_hits[s2]
                    # 该节所有命中页里，「相对节首的偏移」最小的那条
                    best_rel = min((pg - sec_starts.get(s2, pg)
                                    for pg in it["pgs"]
                                    if _sec_of(pg) == s2), default=10 ** 6)
                    return (n, -best_rel)
                first_sect = max(sec_hits, key=score)
                first_unit = sec_unit.get(first_sect, "")
            per_book[book] = {"units": units_b, "sections": sects_b,
                              "unit": first_unit, "section": first_sect,
                              "secHits": dict(sec_hits),
                              "secStarts": sec_starts,
                              # 偏移一并带出去 —— build 层显示「印刷页码」时要减回去
                              "offset": toc_all[book].get("_offset", 0)}
        out_rows.append({
            "id": cid, "name": c["name"], "subject": c["subject"],
            "books": books,
            "graphBooks": [b.replace("s6-", "") for b in books],
            "upBook": c["book"], "upBookZh": c["bookZh"],
            "match": sig, "hitPages": allpgs, "nHits": len(allpgs),
            "perBook": per_book,
            "units": sorted({u for v in per_book.values() for u in v["units"]}),
            "sections": sorted({s for v in per_book.values() for s in v["sections"]}),
            "pageSections": sorted(sechits, key=lambda h: (h["book"], h["page"])),
            "def": c["def"],
        })
        stats[sig] += 1

    out_rows.sort(key=lambda r: (r["books"][0], r["name"]))
    OUT.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in out_rows),
                   encoding="utf-8")
    print(f"\n匹配结果 → {OUT}")
    print(f"  命中概念 {len(out_rows)} 个")
    for sig, n in stats.most_common():
        print(f"    {sig}: {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
