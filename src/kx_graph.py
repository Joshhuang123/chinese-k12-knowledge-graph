#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
人教版《小学科学》图谱 —— `data/kx-graph.json`

这一层是什么
------------
上游 K12-KGraph 的图谱**小学阶段只有数学**（1,182 个概念），
物理 / 化学 / 生物学在小学一个都没有（上游 issue #10）。
但小学科学教材是有的 —— 人教版《小学科学》1上~6下 12 本 / 1,036 页。

这个文件是**基于一手教材数据自建**的一层图谱：

- **节点**：小学科学的知识点。
  来源是**教材自己的目录** + **视觉模型读教材正文页判定**（`data/kx-sections.json`）——
  105 个待判节里，68 个判定为「可教的知识概念」，37 个是活动/回顾/制作（不做节点）。
  判据不靠节名猜：节名筛不出概念（「不倒翁」是对象、「蚕出生了」是过程），
  **读了正文才知道这一节实际在讲什么**。
- **边**：
  - `教材序`（来源码 8）—— 同一册里相邻概念的先后。
    **这是教材编者排的教学顺序，不是先修关系**，页面上必须分开标。
  - `上游先修`（来源码 0）—— 能对齐上游概念的那些，**照搬上游的先修边**。
    那是硬数据，不是我推的。

节点分两类
----------
| 类 | 数量 | 含义 |
|---|---|---|
| `kx` | 54 | 小学科学特有，上游没有 → **新节点** |
| `up` | 14 | 上游有对应概念 → **同一个节点，多一处小学教材位置** |

「上游有对应概念」这 14 个的判据：
1. 概念名**精确**等于上游概念名（5 个：溶解/空气/光的色散/视觉的形成/电动机）
2. 或者教材的**单元名/节名**里出现了上游那个概念（9 个，靠目录信号，不是靠正文）

第 2 类要看一眼 —— 别把「土壤资源 ≈ 稀土资源」这种贴错了。

跑法：python3 src/kx_graph.py
"""
from __future__ import annotations

import collections
import difflib
import json
import pathlib
import re
import sys
import unicodedata

BASE = pathlib.Path("/Users/huangjunhai/Documents/个人/项目/中文知识图谱")
TOC = BASE / "data" / "kx-toc.json"
SECTIONS = BASE / "data" / "kx-sections.json"
KXV = BASE / "data" / "concept-vision-kx.jsonl"
GRAPH = BASE / "data" / "normalized" / "graph.json"
OUT = BASE / "data" / "kx-graph.json"

# 来源码。**必须跟 build_viz.py 的 SRC 对齐**，页面上才能显示对徽标。
#   0 upstream 上游 · 1 model 模型重建 · 2 l0 能力底座 · 3 derived 自建概念
#   4 intro 教材引入路径 · 5 fix 已修正 · 6 structmap 教材结构图
#   7 —— 空着（上海站在用）
#   8 textbookorder 教材序 ← 新增：**教材编排的教学顺序，不是先修关系**
SRC = {"upstream": 0, "model": 1, "l0": 2, "derived": 3, "intro": 4,
       "fix": 5, "structmap": 6, "sh": 7, "textbookorder": 8}

# 学科：小学科学是物理+化学+生物+地球科学的合流。
# **上游 schema 里没有「科学」** —— 这里按内容归到三科（跟上海站同一思路）。
SUBJ_OF = "science"

# 人工确认的「近似匹配」白名单。
# **不做模糊自动匹配** —— 「土壤资源 ≈ 稀土资源」这种贴错了，
# 错挂比不挂更糟（页面上的教材位置会被当真）。
ALIGN = {
    # concept 名 → 上游概念名（必须是**同一个知识点**，不是形近）
    "动物的感觉器官": "感觉器官",
    "空气的热胀冷缩": "热胀冷缩",
    "生物与非生物": "生物与非生物的区分",
    "能的转化": "能量的转化",
    "动物对环境的适应": "生物对环境的适应",
    "动物的共同特征": "生物的共同特征",
}


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "")
    s = re.sub(r"[\s　]+", "", s)
    return re.sub(r"[（）()〔〕【】\[\]《》“”\"'’‘,，。.、:：;；!！?？\-—_/\\|]+", "", s)


def main() -> int:
    toc = json.load(open(TOC, encoding="utf-8"))
    sections = json.load(open(SECTIONS, encoding="utf-8"))
    graph = json.load(open(GRAPH, encoding="utf-8"))
    info = {n["id"]: n for n in graph["nodes"]}

    # 上游概念名 → 节点
    up_by_name = collections.defaultdict(list)
    for n in graph["nodes"]:
        if n.get("label") in ("Concept", "Skill", "Experiment"):
            up_by_name[n.get("name") or ""].append(n)

    # ── 1. 收集教材上「已挂上游概念」的节 ──────────────────
    # 这些节的概念上游已经有了 → 同一节点，多一处小学位置
    kxv = [json.loads(l) for l in KXV.open(encoding="utf-8")]
    up_by_section = collections.defaultdict(list)
    for r in kxv:
        for bk, v in r["perBook"].items():
            if v.get("section"):
                up_by_section[(bk, v["section"])].append(r["id"])

    # ── 2. 新概念节点（视觉模型判定 isConcept 的 68 个）──────
    con = [x for x in sections if x.get("isConcept")]
    nodes = {}
    edges = []
    stats = collections.Counter()

    # 教材位置（从 kx-sections 的页 + 目录的节起始页）
    # —— 印刷页码，已减去扫描偏移
    def book_label(bk):
        return f"{toc[bk]['units'][0]['name'][:0]}"  # 占位，下面用 bookZh

    VOL_CN = {f"{i}{v}": f"{c}{'上' if v == 'a' else '下'}"
              for i, c in enumerate("一二三四五六", 1) for v in "ab"}

    for x in con:
        bk = x["book"]
        sec = x["section"]
        cname = x["concept"]
        gbook = bk.replace("s6-", "")
        # 教材位置：节起始页
        page = x["page"]
        unit = x["unit"]
        # 教材原话（从 OCR 页里找这一节的第一句）
        summary = x.get("summary") or ""

        # ── 判断这个概念在不在上游 ──
        up_ids = []
        align_reason = ""
        # (a) 教材目录里已经挂上的节 → 上游概念
        for cid in up_by_section.get((bk, sec), []):
            up_ids.append(cid)
        # (b) 概念名精确等于上游概念名
        if not up_ids:
            for n in up_by_name.get(cname, []):
                up_ids.append(n["id"])
                align_reason = "同名"
        # (c) 人工确认的白名单
        if not up_ids and cname in ALIGN:
            for n in up_by_name.get(ALIGN[cname], []):
                up_ids.append(n["id"])
                align_reason = "人工确认同一知识点"

        if up_ids:
            # ── 已有上游节点 → 不新建，只记小学位置 ──
            for cid in up_ids:
                nid = f"up:{cid}"
                if nid not in nodes:
                    n = info[cid]
                    nodes[nid] = {
                        "id": nid, "name": n.get("name") or "",
                        "subject": n.get("subject") or "physics",
                        "kind": "up", "upId": cid,
                        "upBook": n.get("book") or "", "upBookZh": n.get("bookZh") or "",
                        "stage": n.get("stage") or "", "grade": n.get("grade") or 0,
                        "def": ((n.get("props") or {}).get("definition") or "")[:200],
                        "kxBooks": [], "kxSections": [], "kxPages": [],
                        "alignReason": align_reason,
                    }
                nd = nodes[nid]
                if bk not in nd["kxBooks"]:
                    nd["kxBooks"].append(bk)
                rec = {"book": bk, "bookZh": VOL_CN.get(gbook, gbook),
                       "unit": unit, "section": sec, "page": page,
                       "concept": cname}
                nd["kxSections"].append(rec)
                if page not in nd["kxPages"]:
                    nd["kxPages"].append(page)
            stats["对齐上游"] += 1
        else:
            # ── 真新节点 ──
            # **同名要合并** —— 「月相」在二下「月亮」节和四下「月相的变化」节都教，
            # 是同一个概念在两册里。建成两个节点的话：
            #   · 搜索「月相」出两条，分不清
            #   · 「上一/下一单元」会在两个同名点之间乱跳
            # 所以按**概念名**去重，多余的教材位置挂到同一个节点上。
            nid = f"kx:{bk}:{sec}"
            same = next((x for x in nodes.values()
                         if x["kind"] == "kx" and x["name"] == cname), None)
            if same is not None:
                same["kxBooks"].append(bk)
                same["kxSections"].append({
                    "book": bk, "bookZh": VOL_CN.get(gbook, gbook),
                    "unit": unit, "section": sec, "page": page,
                    "concept": cname})
                if page not in same["kxPages"]:
                    same["kxPages"].append(page)
                stats["同名合并"] += 1
                continue
            nodes[nid] = {
                "id": nid, "name": cname,
                "subject": SUBJ_OF, "kind": "kx",
                "upId": "", "upBook": "", "upBookZh": "",
                "stage": "小学", "grade": int(gbook[0]) if gbook[0].isdigit() else 0,
                "def": "",
                "kxBooks": [bk], "kxSections": [
                    {"book": bk, "bookZh": VOL_CN.get(gbook, gbook),
                     "unit": unit, "section": sec, "page": page,
                     "concept": cname}],
                "kxPages": [page],
                "summary": summary,
                "alignReason": "",
            }
            stats["新节点"] += 1

    # ── 3. 边 ────────────────────────────────────────────
    # (a) 教材序边：**同一单元内**相邻的概念
    #
    # **不能按整册相邻** —— 那样会跨单元连边：
    # 1a 的「感觉器官」单元结束就直接跳到「家养动物」单元，
    # 连出「动物的身体特征 → 工具的作用」这种语义上不连贯的边。
    # 教材编排的粒度是单元，单元之间是并列的（并列的单元不该有先后边）。
    by_unit = collections.defaultdict(list)
    for nid, n in nodes.items():
        if n["kind"] != "kx":
            continue
        for rec in n["kxSections"]:
            by_unit[(rec["book"], rec["unit"])].append((rec["page"], nid))
    for (bk, un), lst in by_unit.items():
        lst.sort()
        for i in range(len(lst) - 1):
            a, b = lst[i][1], lst[i + 1][1]
            edges.append({"from": a, "to": b, "src": SRC["textbookorder"],
                          "why": f"教材顺序：{un} 单元内（编者排的教学先后，不是先修关系）"})
            stats["教材序边"] += 1

    # (b) 上游先修边：照搬上游的（只保留两端都在本图谱里的）
    ids = {n["upId"] for n in nodes.values() if n["kind"] == "up"}
    for e in graph["edges"]:
        if e.get("type") != "prerequisites_for":
            continue
        if e["from"] in ids and e["to"] in ids:
            edges.append({"from": f"up:{e['from']}", "to": f"up:{e['to']}",
                          "src": SRC["upstream"], "why": "上游图谱的先修关系（硬数据）"})
            stats["上游先修边"] += 1

    # ── 4. 落盘 ───────────────────────────────────────────
    out = {
        "_source": {
            "教材": "人教版《义务教育教科书·科学》1上~6下（2024年课标版）",
            "publisher": "湖北教育出版社",
            "edition": "人教版",
            "pages": 1036,
            "platform": "国家中小学智慧教育平台（教材页图）",
            "todo": "教材目录 + 视觉模型读正文页判定（data/kx-sections.json）",
            "srcNote": "教材序边是教材编排的教学顺序，**不是先修关系**",
        },
        "srczh": ["上游", "模型重建", "能力底座", "自建概念", "教材引入路径",
                  "已修正", "教材结构图", "上海教材", "教材序"],
        "nodes": list(nodes.values()),
        "edges": edges,
        "books": [{"id": bk, "book": bk.replace("s6-", ""),
                   "bookZh": VOL_CN.get(bk.replace("s6-", ""), bk),
                   "pages": sum(1 for _ in (TOC and [])) or None}
                  for bk in sorted(toc)],
    }
    # 补上每本的页数
    for b in out["books"]:
        b["pages"] = len([u for u in toc[b["id"]]["units"] for s in u["sections"]])
        b["units"] = [u["name"] for u in toc[b["id"]]["units"]]
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")

    nup = sum(1 for n in nodes.values() if n["kind"] == "up")
    nkx = sum(1 for n in nodes.values() if n["kind"] == "kx")
    print(f"节点 {len(nodes)}（新节点 {nkx} · 对齐上游 {nup}）")
    print(f"边 {len(edges)}")
    for k, v in stats.most_common():
        print(f"  {k}: {v}")
    print(f"→ {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
