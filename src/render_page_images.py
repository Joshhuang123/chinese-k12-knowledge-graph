#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
把**本地教材 PDF** 渲染成页图，给学习页的「教材原页」板块用。

为什么从本地 PDF 渲染，而不是用平台的电子教材
--------------------------------------------
调查过平台（国家中小学智慧教育平台）的官方扫描本，结论是**对不上**：
  · 平台上的小学数学只有 **2024 审定新版**（目录是「认识立体图形」「复习与关联」），
    我们数据对应的是 **2022 旧版**（目录是「认识图形（一）」「数学乐园」）——
    **内容都不一样**
  · 初中也不对齐：同一本第一章，平台第 31 页是第二章首页，
    我们第 31 页是第一章末的习题
  · 平台的 PDF 直接下载走防盗链（403）

而**本地 PDF 就是我们数据的来源** —— 概念位置、原话、公式、例题
全部从它抽出来。所以从它渲染出来的图，**页码天然对齐、图文自洽**。

输出
----
    data/pages/<册次>/<页码>.webp      页图（WebP，比 JPEG 小一半）
    data/page-images-rjb.json          索引：册次 → {页码: 文件名}

体积：1,100 多页 × 44 KB ≈ 48 MB。

跑:  python3 src/render_page_images.py [--dpi 140] [--quality 70]
"""
import argparse
import collections
import json
import pathlib
import re
import sys
import unicodedata

BASE = pathlib.Path(__file__).resolve().parent.parent
PDFC = BASE / "data" / "pdf-cache"
PAGES_DIR = BASE / "data" / "pages"
OUT_JSON = BASE / "data" / "page-images-rjb.json"
# ⚠️ **页面加载的是 .js，不是 .json** ——
#   learn.html 里 `loadScript('data/page-images-rjb.js')` → window.PAGE_IMAGES_RJB。
#   而体检（src/check_learn_site.py）读的是 .json。
#   以前**只有 .json 有脚本生成**，.js 是手工产物，
#   两份内容对不上（实测 1,018 条重合，各有 100 多条独有），
#   于是「门禁校验的文件」和「页面真正加载的文件」是两份不同的东西
#   —— 真坏了看不见，假坏了报警。
#   现在**两个文件都由这个脚本写**，同一份索引，不会再分叉。
OUT_JS = BASE / "data" / "page-images-rjb.js"

SUBJ_ABBR = {"biology": "bio", "chemistry": "chem", "physics": "phys", "math": "math"}


def load_js(p):
    t = pathlib.Path(p).read_text(encoding="utf-8")
    return json.loads(t[t.index("=") + 1:].rstrip().rstrip(";"))


# 高中册次码：**图谱的码 ≠ PDF 文件名的码**
#   图谱   bx1 / bx2 / xzxbx1 / xzxbx2 / xzxbx3
#   文件   m1  / m2  / x1       / x2       / x3
# 不映射的话这 5 本一个页都渲染不出来（实测「找不到 PDF，跳过」）。
HIGH_VOL = {"bx1": "m1", "bx2": "m2", "bx3": "m3",
            "xzxbx1": "x1", "xzxbx2": "x2", "xzxbx3": "x3"}


def pdf_path(pdf_book: str):
    """pdfBook（biology-7a）→ 本地 PDF 路径"""
    if not pdf_book:
        return None
    head, rest = pdf_book.split("-", 1)
    rest = HIGH_VOL.get(rest, rest)
    p = PDFC / f"rjb-{SUBJ_ABBR.get(head, head)}-{rest}.pdf"
    return p if p.exists() else None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dpi", type=int, default=140)
    ap.add_argument("--quality", type=int, default=70)
    ap.add_argument("--dry", action="store_true")
    args = ap.parse_args()

    # ── 收集要渲染的页 ──
    D = load_js(BASE / "data/learn-rjb.js")
    want = collections.defaultdict(set)     # pdfBook → {页码}
    for n in D["nodes"]:
        loc = n.get("loc") or {}
        if not loc.get("scan") or not loc.get("pdfBook"):
            continue
        want[loc["pdfBook"]].add(loc["scan"][0])
    total = sum(len(v) for v in want.values())
    print(f"要渲染 {total} 页，涉及 {len(want)} 册")

    # 小学科学（另一套目录结构）
    kx = load_js(BASE / "data/learn-kx.js")
    kx_want = collections.defaultdict(set)
    kx_pages = 0
    for n in kx["nodes"]:
        loc = n.get("loc") or {}
        if not loc.get("scan"):
            continue
        bk = loc.get("pdfBook") or ""
        if bk:
            kx_want[bk].add(loc["scan"][0])
            kx_pages += 1
    if kx_want:
        print(f"小学科学：{kx_pages} 个节点有页码，涉及 {len(kx_want)} 册")

    if args.dry:
        for bk, pgs in list(want.items())[:5]:
            print(f"  {bk}: {sorted(pgs)[:8]}")
        return 0

    # ── 渲染 ──
    import fitz
    from PIL import Image
    import io

    index = {}
    done = 0
    for bk, pgs in sorted(want.items()):
        pp = pdf_path(bk)
        if not pp:
            print(f"  {bk}: 找不到 PDF，跳过")
            continue
        outdir = PAGES_DIR / bk
        outdir.mkdir(parents=True, exist_ok=True)
        doc = fitz.open(pp)
        entry = {}
        for pg in sorted(pgs):
            if pg < 1 or pg > doc.page_count:
                continue
            dst = outdir / f"{pg}.webp"
            if not dst.exists():
                pix = doc[pg - 1].get_pixmap(dpi=args.dpi)
                img = Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGB")
                img.save(dst, format="WEBP", quality=args.quality)
            entry[str(pg)] = f"data/pages/{bk}/{pg}.webp"
            done += 1
        doc.close()
        index[bk] = entry
        print(f"  {bk}: {len(entry)} 页")

    # 小学科学
    for bk, pgs in sorted(kx_want.items()):
        pp = PDFC / "kx" / bk / f"{bk}.pdf"
        if not pp.exists():
            hits = list((PDFC / "kx" / bk).glob("*.pdf"))
            pp = hits[0] if hits else None
        if not pp:
            print(f"  kx {bk}: 找不到 PDF，跳过")
            continue
        outdir = PAGES_DIR / "kx" / bk
        outdir.mkdir(parents=True, exist_ok=True)
        doc = fitz.open(pp)
        entry = {}
        for pg in sorted(pgs):
            if pg < 1 or pg > doc.page_count:
                continue
            dst = outdir / f"{pg}.webp"
            if not dst.exists():
                pix = doc[pg - 1].get_pixmap(dpi=args.dpi)
                img = Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGB")
                img.save(dst, format="WEBP", quality=args.quality)
            entry[str(pg)] = f"data/pages/kx/{bk}/{pg}.webp"
            done += 1
        doc.close()
        index[f"kx/{bk}"] = entry
        print(f"  kx {bk}: {len(entry)} 页")

    # ⚠️ **索引以磁盘上的实际文件为准**，不只收「这一轮渲染的」——
    #   有些册次的 PDF 拿不到（镜像里缺那一版），但**页图早就在磁盘上**：
    #   math-bx1（人教 A 版必修第一册，镜像里没有，56 张页图是之前渲染的）
    #   就是这样漏掉的 —— 索引少一册 → 学习页上 92 个节点没有「教材原页」。
    #   索引的职责是「这个文件在哪」，那**文件系统就是真相**。
    on_disk = 0
    for d in sorted(PAGES_DIR.rglob("*")):
        if not d.is_dir():
            continue
        bk = d.relative_to(PAGES_DIR).as_posix()
        entry = index.setdefault(bk, {})
        for f in sorted(d.glob("*.webp")):
            key = f.stem
            if key not in entry:
                entry[key] = f.relative_to(BASE).as_posix()
                on_disk += 1
    if on_disk:
        print(f"  补索引：磁盘上有但这轮没渲染的 {on_disk} 页")

    OUT_JSON.write_text(json.dumps(index, ensure_ascii=False, indent=1), encoding="utf-8")
    # 页面加载的 .js —— 同一份索引，只是包成 window 赋值
    OUT_JS.write_text("window.PAGE_IMAGES_RJB=" +
                      json.dumps(index, ensure_ascii=False, separators=(",", ":")) + ";\n",
                      encoding="utf-8")
    total_bytes = sum(f.stat().st_size for f in PAGES_DIR.rglob("*.webp"))
    print(f"\n渲染 {done} 页 · {total_bytes/1024/1024:.1f} MB → {PAGES_DIR.relative_to(BASE)}")
    print(f"索引 → {OUT_JSON.relative_to(BASE)} · {OUT_JS.relative_to(BASE)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
