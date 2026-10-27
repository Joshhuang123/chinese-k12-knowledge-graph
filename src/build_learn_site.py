#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
构建**学习站**的数据层。

产出三个版本，每个一个 .js 文件（不是 .json）：
    data/learn-rjb.js   人教版（初中高中）
    data/learn-sh.js    沪教版 / 沪科版（上海）
    data/learn-kx.js    人教版小学科学

**为什么是 .js 不是 .json**：页面要按需加载（三个版本的数据加起来不小），
而 `fetch()` 读本地 json 在 `file://` 下会被 CORS 挡掉。
`<script src>` 不受这个限制 —— 实测 file:// 下动态注入 script 能正常加载，
所以学习页双击就能打开，不用起服务器。

**数据从哪来**
  · 六面学习卡（data/learn-cards.jsonl）—— 定义/公式/图/先修/位置/教材原话/练习
  · 沪教图谱（data/shanghai-graph.json）—— 沪教版的位置（册次/章/节/**扫描页码**）
  · 概念视觉层（data/concept-vision*.jsonl）—— 公式、图、页码
  · 页图基址（data/page-images.json）—— 教材原页图的直链底座
  · 视频索引（data/learn-videos.json）—— 用户自己做的讲解视频

⚠️ **页码有两套，别混**：
  · `pages`（来自概念视觉层）= **扫描序号** → 页图 URL 直接拼这个
  · `sections[].page`（来自教材目录）= **印刷页码** → 给人看的「第 51 页」

跑:  python3 src/build_learn_site.py
"""
import collections
import json
import pathlib
import re
import sys

BASE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE / "src"))

from latex_plain import to_plain        # noqa: E402  公式转纯文本（不引 KaTeX）

CARDS = BASE / "data" / "learn-cards.jsonl"
SH_GRAPH = BASE / "data" / "shanghai-graph.json"
KX_GRAPH = BASE / "data" / "kx-graph.json"
CV_RJB = BASE / "data" / "concept-vision.jsonl"
CV_SH = BASE / "data" / "concept-vision-sh.jsonl"
CV_KX = BASE / "data" / "concept-vision-kx.jsonl"
PAGE_IMG = BASE / "data" / "page-images.json"
VIDEOS = BASE / "data" / "learn-videos.json"
OUTDIR = BASE / "data"

SUBJ_ZH = {"math": "数学", "physics": "物理", "chemistry": "化学",
            "biology": "生物", "science": "科学", "kxscience": "小学科学"}

# 教材原话层：**按版本各用各的**
#   人教版 → concept-text.jsonl（PDF 文本层，带章名）
#   沪教版 → concept-text-sh.jsonl（页图 OCR，带 bookId + 印刷页码）
# ⚠️ 千万别用学习卡里的 read 串版 ——
#   那是跨版本合并过的，实测沪教节点会拿到「初中数学人教版-math-七下」的原文，
#   拿另一套教材的话冒充这一套。
CT_RJB = BASE / "data" / "concept-text.jsonl"
CT_SH = BASE / "data" / "concept-text-sh.jsonl"


def read_jsonl(path):
    out = []
    p = pathlib.Path(path)
    if not p.exists():
        return out
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line[0] != "{":
            continue
        try:
            r = json.loads(line)
        except Exception:
            continue
        if isinstance(r, dict):
            out.append(r)
    return out


def norm(s):
    return re.sub(r"\s+", "", re.sub(r"[（(].*?[）)]", "", s or ""))


def site_payload(path):
    """从站点的 HTML 里取 payload（站点是单文件，payload 内嵌在 script 里）"""
    h = pathlib.Path(path).read_text(encoding="utf-8")
    m = re.search(r'<script id="data" type="application/json">(.*?)</script>', h, re.S)
    if not m:
        return None
    return json.loads(m.group(1))


def main() -> int:
    # ── 学习卡 ──
    cards = {}
    for r in read_jsonl(CARDS):
        cards[r["id"]] = r
    print(f"学习卡 {len(cards)} 张")

    # 教材正文（按书 → {扫描页: 文字}）——
    # 用来挑「这个概念真正被讲的那一页」（目录页和序章都不算）。
    ocr = collections.defaultdict(dict)
    for r in read_jsonl(BASE / "data" / "lessons-sh.jsonl"):
        b = r.get("book")
        if isinstance(b, str):
            ocr[b][r.get("page")] = r.get("text") or ""
    print(f"教材正文层 {len(ocr)} 本")

    quotes = {"rjb": {}, "sh": {}, "kx": {}}
    for tag, path in (("rjb", CT_RJB), ("sh", CT_SH)):
        for r in read_jsonl(path):
            quotes[tag][r["id"]] = r
    print(f"教材原话层：人教 {len(quotes['rjb'])} · 沪教 {len(quotes['sh'])}")

    page_img = json.loads(PAGE_IMG.read_text(encoding="utf-8")) if PAGE_IMG.exists() else {}
    videos = json.loads(VIDEOS.read_text(encoding="utf-8")) if VIDEOS.exists() else {}
    print(f"页图基址 {len(page_img)} 本 · 视频索引 {len(videos)} 条")

    # ── 视觉层：公式/图/页码 ──
    vision = {}
    for tag, p in (("rjb", CV_RJB), ("sh", CV_SH), ("kx", CV_KX)):
        for r in read_jsonl(p):
            vision.setdefault(tag, {})[r["id"]] = r
    print("视觉层：" + " · ".join(f"{k} {len(v)}" for k, v in vision.items()))

    # ── 三站定义 ──
    versions = []

    # 人教版
    d = site_payload(BASE / "index.html")
    versions.append(("rjb", "人教版 · 初中高中", d["nodes"], d["edges"], "rjb", None))

    # 沪教版
    sg = json.loads(SH_GRAPH.read_text(encoding="utf-8"))
    shg_by_id = {n["id"]: n for n in sg["nodes"]}
    d2 = site_payload(BASE / "shanghai.html")
    versions.append(("sh", "沪教版 / 沪科版 · 上海", d2["nodes"], d2["edges"], "sh", sg))

    # 小学科学
    d3 = site_payload(BASE / "kx.html")
    versions.append(("kx", "人教版《小学科学》", d3["nodes"], d3["edges"], "kx", None))

    for tag, label, nodes, edges, vtag, shg in versions:
        # 边：[后继, 前置]
        pre_of = collections.defaultdict(list)
        suc_of = collections.defaultdict(list)
        for e in edges:
            a, b = e[0], e[1]
            pre_of[a].append(b)
            suc_of[b].append(a)

        out = []
        idx_of = {}
        for n in nodes:
            idx_of[n[1]] = len(out)

        for n in nodes:
            i, name, _en, subj, dz, nid = n[0], n[1], n[2], n[3], n[4], n[5]
            grade, cen, core, desc, evn = n[6], n[8], n[9], n[10], n[11]
            card = cards.get(nid)
            vis = vision.get(vtag, {}).get(nid)

            rec = {
                "i": i,
                "n": name,
                "s": subj,
                "g": grade,
                "b": dz,
                "c": round(cen, 3),
                "core": core,
                "src": evn,
            }
            # 定义
            d0 = desc or ""
            if d0.startswith("图谱定义："):
                d0 = d0[len("图谱定义："):]
            d0 = d0.split("　｜　")[0].strip()
            if d0:
                rec["d"] = to_plain(d0)   # 定义里也有 LaTeX（\overrightarrow{...}）

            # 公式 / 图
            forms, figs = [], []
            if vis:
                for f in (vis.get("formulas") or []):
                    t = f if isinstance(f, str) else (f.get("latex") or f.get("text") or "")
                    # **公式转纯文本** —— 不引 KaTeX（外链字体 + payload 暴涨，
                    # 历史上算过：内联 SVG 要 24~60 MB）。
                    # 转换器跟主站用的是同一个 latex_plain.to_plain。
                    if t:
                        t = to_plain(t)
                    if t and len(t) < 120:
                        forms.append(t)
                for g in (vis.get("figureDescriptions") or []):
                    cap = g.get("caption") or ""
                    tx = g.get("text") or g.get("description") or ""
                    # 图注里也有 LaTeX（「横轴为时间 $t/\text{时}$」）—— 一样要转
                    if cap:
                        cap = to_plain(cap)
                    if tx:
                        tx = to_plain(tx)
                    if cap or tx:
                        figs.append({"c": cap[:60], "t": tx[:160]})
            if card:
                for f in (card.get("how") or {}).get("formulas") or []:
                    t = f.get("text") if isinstance(f, dict) else str(f)
                    if t:
                        t = to_plain(t)
                    if t and t not in forms and len(t) < 120:
                        forms.append(t)
                for g in (card.get("how") or {}).get("figures") or []:
                    if isinstance(g, dict):
                        figs.append({"c": to_plain(g.get("caption") or "")[:60],
                                     "t": to_plain(g.get("text") or "")[:160]})
            if forms:
                rec["f"] = forms[:6]
            if figs:
                rec["fg"] = figs[:4]

            # 教材原话（**按版本取**，不串版）
            reads = []
            q = quotes.get(vtag, {}).get(nid)
            if q:
                # 定义句排前面
                order = sorted(range(len(q.get("quotes") or [])),
                               key=lambda i: 0 if (q.get("quoteKinds") or [None] * 99)[i] == "definition" else 1)
                bks = q.get("books") or []
                bk = bks[0] if bks else (q.get("book") or "")
                for i in order[:3]:
                    tx = (q.get("quotes") or [])[i]
                    if tx and len(tx.strip()) > 3:
                        reads.append({"t": tx[:220], "b": bk,
                                      "p": (q.get("pages") or [None])[0],
                                      "def": (q.get("quoteKinds") or [""])[i] == "definition"})
            if reads:
                rec["rd"] = reads

            # 教材位置
            loc = None
            if shg:
                sn = shg_by_id.get(nid)
                if sn and sn.get("mainBook"):
                    b = sn["books"].get(sn["mainBook"]) or {}
                    secs = [{"c": s.get("chapter", ""), "cn": s.get("chapterName", ""),
                             "s": s.get("section", ""), "sn": s.get("sectionName", ""),
                             "p": s.get("page")} for s in (b.get("sections") or [])[:4]]
                    # **只取主教材那一本书的页** ——
                    # 原来把 9 本书的页混在一起取最小的几个，
                    # 结果给的是**目录页**（谁都能在目录里看到概念名）。
                    mb = sn["mainBook"]
                    scan = sorted(set(((vis or {}).get("books") or {}).get(mb, {}).get("pages") or []))
                    # 再挑「正文里真的出现这个概念」的那一页
                    nm = name or ""
                    pgs = ocr.get(mb, {})
                    hit = [p for p in scan if nm and nm in (pgs.get(p) or "")]
                    # 有正文命中的，取最早那页（概念通常在首次出现处讲）
                    pick = hit[0] if hit else (scan[0] if scan else None)
                    loc = {"bk": mb, "vol": b.get("volName"),
                           "ed": b.get("edition"), "sec": secs,
                           "scan": [p for p in ([pick] if pick else []) ],
                           "all": scan[:8],
                           "hit": len(hit)}
            elif vis and vis.get("books"):
                bb0 = list(vis["books"].values())[0]
                loc = {"bk": "", "vol": vis.get("bookZh"), "ed": "人教版",
                       "sec": [], "scan": sorted(set(bb0.get("pages") or []))[:6]}
            elif card and card.get("where"):
                w = card["where"][0]
                loc = {"bk": "", "vol": w.get("bookZh"), "ed": w.get("edition"),
                       "sec": [], "scan": [],
                       "unit": w.get("chapter") or w.get("unit")}
            if loc:
                rec["loc"] = loc

            # 先修 / 后继
            pr = []
            for p in pre_of.get(i, []):
                pr.append([p, nodes[p][1]])
            su = []
            for s in suc_of.get(i, []):
                su.append([s, nodes[s][1]])
            if pr:
                rec["pre"] = pr[:12]
            if su:
                rec["suc"] = su[:12]

            # 练习（教材例题原文）
            if card and card.get("practice"):
                # **题干里也有 LaTeX**（「$\frac{2+x}{2}\geqslant...$」）——
                # 页面上不能出现源码。
                rec["pr"] = [to_plain(x.get("text") or "")[:180] for x in card["practice"][:6]]

            # 视频
            v = videos.get(nid) or videos.get(norm(name))
            if v:
                rec["v"] = v

            out.append(rec)

        # 视频表（按 id / 名字查）
        blob = {
            "version": tag,
            "label": label,
            "nodes": out,
        }
        js = "window.LEARN_DATA=" + json.dumps(blob, ensure_ascii=False, separators=(",", ":")) + ";\n"
        outp = OUTDIR / f"learn-{tag}.js"
        outp.write_text(js, encoding="utf-8")
        print(f"  {outp.name:16s} {len(out):6d} 节点  {len(js)/1024/1024:.2f} MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
