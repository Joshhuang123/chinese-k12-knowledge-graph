#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
上海版的数据质量公开页 + **内容缺口地图**（上海教材的）。

跟人教版的 `quality.html` 是一对，但**查的不是同一批东西**：

人教版那页查的是**上游图谱本身**的问题（环、倒挂、覆盖缺口、裁决账本）——
那批问题在主站和上海站是**同一批**（上海站继承的是人教图谱）。

这页查的是**上海教材这一层**的问题：
- 教材数据到底接进来多少（位置 / 公式 / 原话 / 难点）
- 哪些概念在教材上找不到对应（**覆盖缺口**）
- 教材标了难点、而图谱前置薄的地方（**最该补内容的地方**）

**教材标难点 ∧ 图谱前置薄 = 内容缺口。**
人教版那版已经证明过这个交叉有用（七下「相交线」：教材标了 32 处思考题，
图谱里那 7 个概念一个前置都没有）。上海版再算一遍。

跑法：python3 src/build_shanghai_quality.py
"""
from __future__ import annotations

import collections
import html
import json
import pathlib
import re
import sys

BASE = pathlib.Path("/Users/huangjunhai/Documents/个人/项目/中文知识图谱")
SG = BASE / "data" / "shanghai-graph.json"
CVIS = BASE / "data" / "concept-vision-sh.jsonl"
CTXT = BASE / "data" / "concept-text-sh.jsonl"
VPAGES = BASE / "data" / "vision-pages-sh.jsonl"
STJ = BASE / "data" / "shanghai-textbooks.json"
GRAPH = BASE / "data" / "normalized" / "graph.json"
OUT = BASE / "shanghai-quality.html"
MD = BASE / "docs" / "shanghai-difficulty.md"
JOUT = BASE / "data" / "normalized" / "shanghai-difficulty.json"

HARD_KINDS = ("思考", "探究", "讨论")


def esc(s):
    return html.escape(str(s), quote=True)


def table(headers, rows, cls=""):
    h = "".join(f"<th>{esc(x)}</th>" for x in headers)
    body = ""
    for r in rows:
        body += "<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>"
    if not rows:
        body = f'<tr><td colspan="{len(headers)}" class="empty">（无）</td></tr>'
    return (f'<table class="{cls}"><thead><tr>{h}</tr></thead>'
            f"<tbody>{body}</tbody></table>")


def main() -> int:
    sg = json.load(open(SG, encoding="utf-8"))
    nodes = {n["id"]: n for n in sg["nodes"]}
    units = sg["units"]
    ids = set(nodes)

    # ── 1. 教材数据接进来多少 ─────────────────────────────────
    n_pos = sum(1 for n in sg["nodes"] if n.get("sections"))
    n_formula = 0
    n_fig = 0
    n_quote = 0
    n_hard = 0
    cvis = {}
    if CVIS.exists():
        for line in CVIS.open(encoding="utf-8"):
            if not line.strip():
                continue
            c = json.loads(line)
            cvis[c["id"]] = c
    for cid, c in cvis.items():
        for bid, b in (c.get("books") or {}).items():
            if b.get("formulas"):
                n_formula += 1
            if b.get("figures"):
                n_fig += 1
            if any(any(k in (e.get("type") or "") for k in HARD_KINDS)
                   for e in (b.get("exercises") or [])):
                n_hard += 1
    quotes = set()
    if CTXT.exists():
        for line in CTXT.open(encoding="utf-8"):
            if not line.strip():
                continue
            r = json.loads(line)
            if r.get("hasDefinition"):
                quotes.add(r["id"])
    n_quote = len(quotes & ids)

    # ── 2. 图谱的先修覆盖 ─────────────────────────────────────
    g = json.load(open(GRAPH, encoding="utf-8"))
    pre = collections.defaultdict(set)
    for e in g["edges"]:
        if e.get("type") == "prerequisites_for":
            pre[e["to"]].add(e["from"])
    # 自建层也接上（上海站的边就是两层的并）
    sb = BASE / "data" / "normalized" / "selfbuilt-edges.json"
    if sb.exists():
        for e in json.load(open(sb, encoding="utf-8"))["edges"]:
            if e.get("type") == "prerequisites_for":
                pre[e["to"]].add(e["from"])

    def closure(seed):
        seen, q = set(), list(seed)
        while q:
            x = q.pop()
            for p in pre.get(x, ()):
                if p not in seen:
                    seen.add(p)
                    q.append(p)
        return seen

    # ── 3. 教材标的难点 → 按单元归集 ──────────────────────────
    # 单元 → 页 → 教材标难点的处数
    unit_pages = collections.defaultdict(set)
    for u in units:
        unit_pages[u["bookId"]].add(u["page"])
    # 页 → 单元
    page_unit = {}
    for u in units:
        page_unit[(u["bookId"], u["page"])] = u

    hard_by_unit = collections.Counter()
    concept_pages = collections.defaultdict(set)
    for cid, c in cvis.items():
        for bid, b in (c.get("books") or {}).items():
            for pg in (b.get("pages") or []):
                concept_pages[bid].add(pg)
    n_hard_pages = 0
    if VPAGES.exists():
        for line in VPAGES.open(encoding="utf-8"):
            if not line.strip():
                continue
            r = json.loads(line)
            if not r.get("ok"):
                continue
            d = r.get("data") or {}
            n = sum(1 for e in (d.get("exercises") or [])
                    if isinstance(e, dict)
                    and any(k in (e.get("type") or "") for k in HARD_KINDS))
            if not n:
                continue
            n_hard_pages += 1
            u = page_unit.get((r["book"], r["page"]))
            if u:
                hard_by_unit[u["bookId"] + "|" + u["section"] + "|" + u["sectionName"]] += n

    # ── 4. 交叉：教材标难点 × 图谱前置覆盖 ─────────────────────
    #
    # **两种缺口要分开**：
    # ① 前置数据空白 —— 教材标了难点，图谱里这个概念**有**，但一个前置都没有
    # ② 概念覆盖缺口 —— 教材标了难点，图谱里**一个概念都没有**
    #    （教材教了，图谱根本没有这个东西）
    # 混在一起的话，「认出 0 个概念」会被算成「前置覆盖率 0」，
    # 而它其实是另一回事 —— 前者是没标前置，后者是压根没这个概念。
    #
    # **非内容节不算**：「本章复习」「内容提要」「小结·评价」「词汇索引」
    # 这些不是知识节，教材在那儿标思考题是复习题，不是「这一节难」。
    NON_CONTENT = ("复习", "小结", "内容提要", "索引", "词汇", "附录",
                   "本章小结", "单元小结")
    rows = []
    gap_noconcept = []
    for u in units:
        key = u["bookId"] + "|" + u["section"] + "|" + u["sectionName"]
        hard = hard_by_unit.get(key, 0)
        if not hard:
            continue
        # 这一节涉及的概念（在它的页上）
        cids = []
        for cid, c in cvis.items():
            b = (c.get("books") or {}).get(u["bookId"])
            if b and u["page"] in (b.get("pages") or []):
                cids.append(cid)
        nm = u["sectionName"] or u["chapterName"]
        if any(k in nm for k in NON_CONTENT):
            continue
        if not cids:
            gap_noconcept.append({"bookId": u["bookId"], "edition": u["edition"],
                                  "book": u.get("graphBook", ""), "name": nm,
                                  "hard": hard, "concepts": 0})
            continue
        zero = 0
        for cid in cids:
            cl = closure([cid])
            if not cl:
                zero += 1
        cov = 1 - zero / len(cids)
        rows.append({"bookId": u["bookId"], "edition": u["edition"],
                     "book": u.get("graphBook", ""), "name": nm,
                     "hard": hard, "concepts": len(cids), "zero": zero,
                     "cov": round(cov, 3)})
    # **排序按「教材难 × 前置薄」** —— 只按难点数排的话，
    # 排在最前面的全是「教材难、但图谱覆盖很好」的节（那不用补）。
    # 真正该补的是「教材难 **且** 前置薄」的交集。
    rows.sort(key=lambda r: (-(r["hard"] * (1 - r["cov"])), -r["hard"]))
    gap_noconcept.sort(key=lambda r: -r["hard"])

    JOUT.parent.mkdir(parents=True, exist_ok=True)
    JOUT.write_text(json.dumps({"rows": rows}, ensure_ascii=False, indent=1),
                    encoding="utf-8")

    # ── 5. 教材层面的缺口：哪些书认出来的概念特别少 ──────────────
    per_book = collections.Counter()
    for cid, c in cvis.items():
        for bid in (c.get("books") or {}):
            per_book[bid] += 1
    books = json.load(open(STJ, encoding="utf-8"))["books"]
    thin = []
    for b in books:
        n = per_book.get(b["bookId"], 0)
        if n < 20:
            thin.append((b["title"], b["edition"], b["subject"], n, b.get("pages")))
    thin.sort(key=lambda x: x[3])

    # ── 6. 人读账本 ───────────────────────────────────────────
    L = ["# 上海版内容缺口地图", "",
         "教材标了难点、而图谱前置薄的地方 —— **最该补内容的地方**。", "",
         "两个信号都是一手的：",
         "",
         "- **教材标的难点**：教材每节的「思考」「探究」框 —— 教材编委会自己标的。",
         "- **图谱的先修覆盖**：该节概念在图谱里的前置闭包有多大，"
         "其中多少是「0 前置」（数据空白）。", "",
         "| 册 | 节 | 教材标难点 | 概念 | 0前置 | 前置覆盖 |",
         "|---|---|---|---|---|---|"]
    for r in rows[:30]:
        L.append(f"| {r['book']} | {r['name'][:22]} | {r['hard']} | {r['concepts']} | "
                 f"{r['zero']} | {r['cov']:.2f} |")
    L += ["", f"合计 {len(rows)} 个有难点的单元，教材标的难点 {sum(r['hard'] for r in rows)} 处。", ""]
    if gap_noconcept:
        L += ["## 概念覆盖缺口：教材标了难点，图谱里一个概念都没有", "",
              "| 册 | 节 | 教材标难点 |", "|---|---|---|"]
        for r in gap_noconcept[:20]:
            L.append(f"| {r['book']} | {r['name'][:24]} | {r['hard']} |")
        L.append("")
    if thin:
        L += ["## 认出来特别少的书", "",
              "| 书 | 版别 | 学科 | 认出概念 | 页数 |", "|---|---|---|---|---|"]
        for t, e, s, n, p in thin:
            L.append(f"| {t[:40]} | {e} | {s} | **{n}** | {p} |")
        L.append("")
    MD.write_text("\n".join(L), encoding="utf-8")

    # ── 7. 页面 ────────────────────────────────────────────────
    n_sh = sum(1 for n in sg["nodes"] if n.get("kind") == "sh")
    cards = [
        ("沪教概念", f"{n_sh:,}", "教材页面上认出来的"),
        ("教材位置", f"{n_pos:,}", "能定位到章/节/页"),
        ("带教材公式", f"{n_formula:,}", "书-概念对"),
        ("带教材原话", f"{n_quote:,}", "教材自己写的定义句"),
        ("带教材难点", f"{n_hard:,}", "书-概念对"),
        ("图谱 0 前置", f"{len(rows):,}", "有教材难点的单元"),
    ]
    chtml = "".join(
        f'<div class="c"><div class="lab">{esc(l)}</div>'
        f'<div class="num">{esc(n)}</div><div class="sub">{esc(s)}</div></div>'
        for l, n, s in cards)

    gap_rows = []
    for r in rows[:40]:
        bar = (f'<span class="bar"><i style="width:{int(r["cov"]*100)}%"></i></span> '
               f'{r["cov"]:.2f}')
        gap_rows.append([
            esc(r["edition"] + " " + r["book"]),
            esc(r["name"][:24]),
            f'<b style="color:#ff9db8">{r["hard"]}</b>',
            str(r["concepts"]),
            str(r["zero"]),
            bar,
        ])
    thin_rows = [[esc(t[:44]), esc(e), esc(s), f'<b>{n}</b>', str(p or 0)]
                 for t, e, s, n, p in thin]
    noc_rows = [[esc(r["edition"] + " " + r["book"]), esc(r["name"][:24]),
                 f'<b style="color:#ff9db8">{r["hard"]}</b>', "0"]
                for r in gap_noconcept[:30]]

    page = f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>上海版 · 数据质量</title>
<style>
:root{{--bg:#0b0c10;--panel:#14171e;--line:#242a35;--fg:#e8ebf2;--muted:#8b93a7}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--fg);
  font:15px/1.7 -apple-system,BlinkMacSystemFont,"PingFang SC","Hiragino Sans GB","Microsoft YaHei",sans-serif}}
.wrap{{max-width:1080px;margin:0 auto;padding:38px 22px 70px}}
h1{{font-size:30px;margin:0 0 6px;font-weight:700}}
.sub{{color:var(--muted);font-size:13.5px;margin:0 0 26px}}
a{{color:#7fd3ff}}
.nav{{margin-bottom:26px;font-size:13px}}
.nav a{{margin-right:16px;text-decoration:none;color:#7fd3ff}}
.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:11px;margin-bottom:34px}}
.c{{background:var(--panel);border:1px solid var(--line);border-radius:11px;padding:14px 16px}}
.c .lab{{font-size:11.5px;color:var(--muted)}}
.c .num{{font:700 27px/1.25 ui-monospace,SFMono-Regular,Menlo,monospace;color:#ff3d7f}}
.c .sub{{font-size:11px;margin:3px 0 0}}
h2{{font-size:19px;margin:34px 0 6px;padding-top:18px;border-top:1px solid var(--line)}}
.note{{color:var(--muted);font-size:12.5px;margin:0 0 13px;line-height:1.75}}
table{{width:100%;border-collapse:collapse;font-size:12.5px;margin-bottom:8px}}
th{{text-align:left;font-weight:600;color:#9fb0c8;border-bottom:1px solid var(--line);
  padding:7px 9px;font-size:11.5px;white-space:nowrap}}
td{{padding:6px 9px;border-bottom:1px solid #191d25;vertical-align:top}}
td.empty{{color:#6b7488;text-align:center;padding:16px}}
tr:hover td{{background:rgba(255,255,255,.025)}}
.bar{{display:inline-block;width:70px;height:5px;background:#22262f;border-radius:3px;overflow:hidden;margin-right:7px;vertical-align:1px}}
.bar i{{display:block;height:100%;background:#7fd3ff}}
.foot{{margin-top:40px;padding-top:18px;border-top:1px solid var(--line);
  color:var(--muted);font-size:12px;line-height:1.9}}
code{{background:#191d25;padding:1px 5px;border-radius:4px;font-size:11.5px}}
</style></head>
<body><div class="wrap">
<h1>上海版 · 数据质量</h1>
<p class="sub">这个站的数据是<b>从上海教材本身长出来的</b>（国家中小学智慧教育平台的页图 +
视觉模型 + 视觉层读的目录）。这一页把它的账摊开。</p>
<div class="nav">
  <a href="./shanghai.html">← 上海版站点</a>
  <a href="./index.html">主站</a>
  <a href="./quality.html">主站数据质量</a>
</div>

<div class="cards">{chtml}</div>

<h2>内容缺口地图：教材标了难点，而图谱前置薄</h2>
<p class="note">
两个信号都是一手的：<b>教材标的难点</b>是教材编委会自己标的「思考」「探究」框；
<b>图谱的先修覆盖</b>是那个概念在图谱里的前置闭包里有多少是「0 前置」——
图谱在这一片是空的。<br>
<b>教材标了难点、图谱前置薄 = 最该补内容的地方。</b>
排序按教材标的难点数从多到少。
</p>
{table(["册", "节", "教材标难点", "概念", "0前置", "前置覆盖"], gap_rows)}

<h2>概念覆盖缺口：教材标了难点，图谱里一个概念都没有</h2>
<p class="note">
这是<b>另一回事</b>：不是「这个概念的前置没标」，是<b>图谱里根本没有这个概念</b> ——
教材教了，数据里没有。往回看三行：先补概念，再谈前置。
</p>
{table(["册", "节", "教材标难点", "认出概念"], noc_rows)}

<h2>认出来特别少的书</h2>
<p class="note">
这些书在平台上，但**图谱里没有对应的概念**，所以认不出来。
不是我们没做，是<b>上游的覆盖范围到不了那么细</b> ——
比如小学科学的「水的三态」「植物的根」「磁铁」，K12-KGraph 里查不到。
</p>
{table(["书", "版别", "学科", "认出概念", "页数"], thin_rows)}

<div class="foot">
这一页的数字全部现算，脚本在 <code>src/build_shanghai_quality.py</code>；
人读账本在 <code>docs/shanghai-difficulty.md</code>。<br>
原始数据一个字节未改，问题逐条记在 <code>known-issues.md</code>。
</div>
</div></body></html>"""
    OUT.write_text(page, encoding="utf-8")
    print(f"→ {OUT}")
    print(f"→ {MD}")
    print(f"→ {JOUT}")
    print(f"单元 {len(rows)} 个 · 教材标难点 {sum(r['hard'] for r in rows)} 处 · "
          f"认出来少的书 {len(thin)} 本")
    return 0


if __name__ == "__main__":
    sys.exit(main())
