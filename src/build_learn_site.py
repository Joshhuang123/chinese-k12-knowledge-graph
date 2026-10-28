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

# 公式里的**占位符**（教材练习题的空框）。它们不是公式，是填空的壳。
_PLACEHOLDER = re.compile(r"[⊙□]")
# 数字之间的空格 = OCR 把千分位逗号认成了空格（「30x > 1 200」应为「30x > 1200」）
_DIGIT_SPACE = re.compile(r"(?<=\d)\s+(?=\d)")


def clean_formulas(forms):
    """清洗视觉层转写出来的公式。

    视觉层是**模型读教材页面转写**的，会有三类残骸：
      ① 占位符（□ / ⊙）—— 那是练习题的空框，不是公式
      ② 孤零零的一个字母（「n」）—— 数学记号，不是公式
      ③ 数字间的空格（OCR 把「,」认成「空格」）

    只修**确定是错**的，不猜。剩下的照原样给，页面上会标明来源是「视觉层转写」。
    """
    out = []
    for f in forms:
        s = (f or "").strip()
        if not s:
            continue
        if _PLACEHOLDER.search(s):
            continue
        if re.fullmatch(r"[A-Za-z]", s):
            continue
        s = _DIGIT_SPACE.sub("", s)
        if len(s) < 2:
            continue
        out.append(s)
    return out
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


def pick_rjb_page(texts, pages, name, unit=""):
    """从候选页里挑**真正讲这个概念的那一页**。

    判据（按优先级）：
      ① 页面正文里有**教材单元名**（如「21.1 一元二次方程」），且不是目录页
         —— 这是最准的：概念就属于这一节，这一页就是讲它的那页。
      ② 页面正文里有**概念名**，且不是目录页
      ③ 页面不是目录页（有正文）
      ④ 第一个候选页（兜底）

    ⚠️ 目录页必须排除 —— 目录里每个概念名都出现，
    拿目录页当「教材原页」等于什么都没说。
    ⚠️ 光有「概念名」也不够 —— 「一元二次方程」在「本册导引」里被顺带提了一句，
    但真正的讲解在第二十一章那一节。单元名才认得出「讲解页」。
    """
    if not pages:
        return None
    unit = (unit or "").strip()
    # **去掉单元名的序号前缀** ——
    # 单元名是「第一节 一元二次方程」，而正文页写的是「21.1 一元二次方程」，
    # 整串对不上；只用核心名（「一元二次方程」）两边才都能匹配上。
    unit_core = re.sub(r"^第[0-9一二三四五六七八九十]+[节章]\s*", "", unit).strip()
    # **页首窗口** ——
    # 概念名会在好几页出现，但只有「讲解它的那一页」把它放在**标题位置**（页首）。
    # 顺带提到的那页，概念名出现在页中或页尾
    # （实测「一元二次方程」在「本册导引」里被提到，第 4 页，
    #   真正的讲解在第 8~9 页，概念名在页首）。
    HEAD = 80

    def clean(tx):
        return re.sub(r"目\s*录|\bContents\b", "", tx)

    # ① 页首就出现单元核心名 —— 讲解页
    for p in pages:
        tx = texts.get(p) or ""
        if not tx.strip() or re.search(r"目\s*录|\bContents\b", tx):
            continue
        if unit_core and len(unit_core) >= 3 and unit_core in tx[:HEAD]:
            return p
    # ② 页首出现概念名
    for p in pages:
        tx = texts.get(p) or ""
        if not tx.strip() or re.search(r"目\s*录|\bContents\b", tx):
            continue
        if name and name in tx[:HEAD]:
            return p
    # ③ 页内出现单元核心名
    for p in pages:
        tx = texts.get(p) or ""
        if not tx.strip() or re.search(r"目\s*录|\bContents\b", tx):
            continue
        if unit_core and len(unit_core) >= 3 and unit_core in tx:
            return p
    # ④ 页内出现概念名
    for p in pages:
        tx = texts.get(p) or ""
        if not tx.strip() or re.search(r"目\s*录|\bContents\b", tx):
            continue
        if name and name in tx:
            return p
    for p in pages:
        tx = texts.get(p) or ""
        if tx.strip() and not re.search(r"目\s*录|\bContents\b", tx):
            return p
    return pages[0]


def main() -> int:
    # ── 学习卡 ──
    cards = {}
    for r in read_jsonl(CARDS):
        cards[r["id"]] = r
    print(f"学习卡 {len(cards)} 张")

    # 教材正文（按书 → {扫描页: 文字}）——
    # 用来挑「这个概念真正被讲的那一页」（目录页和序章都不算）。
    # 人教版：读本地 PDF 的文本层，用来**挑真正讲这个概念的那一页**。
    # 概念视觉层给的 pages 是「这个名字在哪些页出现过」，
    # **第一个往往是目录页**（实测「光合作用」→ biology-7a 第 5 页是目录，
    # 真正讲它在第 27 页）。目录页当「教材原页」等于什么都没说。
    pdf_text = {}
    PDFC = BASE / "data" / "pdf-cache"
    if PDFC.exists():
        import fitz
        # ⚠️ **学科缩写两边不一样** ——
        #   PDF 文件名   rjb-bio-7a.pdf   → 'bio'
        #   概念视觉层   subject='biology'  → 'biology'
        # 不转换的话 pdf_text 里全是 'bio-7a'，而查的时候用 'biology-7a'，
        # 于是**每一页都查不到文本**，只能 fallback 到第一页（常常是目录页）。
        SUBJ_ABBR = {"biology": "bio", "chemistry": "chem", "physics": "phys",
                     "math": "math"}
        for f in sorted(PDFC.glob("rjb-*.pdf")):
            bid = f.stem[4:]          # math-7a / bio-7a —— 已含学科（缩写）
            # 反查成视觉层那套命名（biology-7a）
            for full, abbr in SUBJ_ABBR.items():
                if bid.startswith(abbr + "-"):
                    bid = full + bid[len(abbr):]
                    break
            try:
                doc = fitz.open(f)
                # ⚠️ 键要用 **1 起**的页码 ——
                # 概念视觉层给的 pages 是 1 起的页号，
                # 用 0 起的 PDF 索引去查会整体差一页（实测「光合作用」选到了序言页）。
                # ⚠️ **必须 NFKC 归一化** ——
                # 人教社 PDF 的数字是**全角**（`２１．１一元二次方程`），
                # 不归一化就匹配不上「一元二次方程」。
                # 实测：NFKC 后第 9 页命中「21.1一元二次方程」✓
                import unicodedata
                pdf_text[bid] = {
                    i + 1: unicodedata.normalize("NFKC", doc[i].get_text())
                    for i in range(doc.page_count)
                }
                doc.close()
            except Exception:
                continue
        print(f"PDF 文本层 {len(pdf_text)} 本")

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

        # 节点 → 教材单元名（用来挑「真正讲它的那一页」）
        # cns[i] = [单元名, 册次, 学科槽位, 第一个可点概念下标]
        unit_of = {}
        if vtag == "rjb":
            d0 = site_payload(BASE / "index.html")
            cns = d0.get("cns") or []
            for i, n in enumerate(nodes):
                oc = n[14] if len(n) > 14 else -1
                if isinstance(oc, int) and 0 <= oc < len(cns):
                    unit_of[i] = cns[oc][0] or ""

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
                # **上游概念 id** —— 视频索引按 id 挂载时要用
                # （id 在三个版本里是同一套，沪教节点也是人教 id）
                "id": nid,
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
                rec["f"] = clean_formulas(forms)[:6]
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
                for i in order[:6]:
                    tx = (q.get("quotes") or [])[i]
                    kind = (q.get("quoteKinds") or [""])[i]
                    if not tx or len(tx.strip()) <= 3:
                        continue
                    # ⚠️ **剔掉目录行和标题行** ——
                    # 教材的目录页上每个节名都出现，摘录时会被当成「教材提到这个概念」。
                    # 实测：沪教「一元一次不等式」的原话里混着「第7章"一元一次不等式与不等式组"」，
                    # 小学科学还有 268 条整条就是节名（「三倍体无籽西瓜」「两点之间的距离公式」）。
                    # 判据三条（都是硬信号，不是猜）：
                    #   ① quoteKinds == 'title'   —— 数据层已经标明了是标题
                    #   ② 含「……第 N 页」点线      —— 目录条目的样子
                    #   ③ 整条就是一个节名（≤12 字且没有句读）
                    if kind == "title":
                        continue
                    if re.search(r"\.{3,}\s*\d+", tx):
                        continue
                    if len(tx.strip()) <= 12 and not re.search(r"[。；，：？！]", tx):
                        continue
                    reads.append({"t": tx[:220], "b": bk, "k": kind,
                                  "p": (q.get("pages") or [None])[0],
                                  "def": kind == "definition"})
                    if len(reads) >= 3:
                        break
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
            elif vis:
                # ⚠️ 人教版的概念视觉层结构**不一样**：
                #   沪教版 concept-vision-sh.jsonl → books{bid:{pages:[…]}}
                #   人教版 concept-vision.jsonl     → 顶层 book / bookZh / pages:[…]
                # 之前只判了 `vis.get("books")`，
                # 于是人教版的 loc.scan 一直是空的 → 学习页没有「教材原页」。
                #
                # **页码就是本地 PDF 的扫描页号** —— 这意味着从 PDF 渲染出来的图
                # 与页码**天然对齐**，不需要任何偏移校准。
                # pdfBook 用**视觉层那套命名**（biology-7a），
                # 渲染脚本负责转成 PDF 文件名的缩写。
                pbk = (f"{vis.get('subject')}-{vis.get('book')}"
                       if vis.get("subject") and vis.get("book") else "")
                pgs = sorted(set(vis.get("pages") or []))
                pick = pick_rjb_page(pdf_text.get(pbk, {}), pgs, name, unit_of.get(i, ""))
                loc = {"bk": "", "vol": vis.get("bookZh"), "ed": "人教版",
                       "sec": [], "scan": [pick] if pick else [],
                       "pdfBook": pbk}
            elif vtag == "kx" and vis and vis.get("books"):
                # 小学科学：概念视觉层结构又不一样 ——
                #   books: ['s6-1a']（教材册次）· hitPages: [页码]
                bk = (vis.get("books") or [None])[0]
                hp = sorted(set(vis.get("hitPages") or []))
                pick = pick_rjb_page({}, hp, name)
                loc = {"bk": "", "vol": bk, "ed": "小学科学",
                       "sec": [], "scan": [pick] if pick else [],
                       "pdfBook": f"kx/{bk}" if bk else ""}
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
