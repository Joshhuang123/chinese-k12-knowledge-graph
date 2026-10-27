#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
逐页验证：平台上的电子教材和我们本地的 PDF **是不是同一本、页码是不是对齐的**。

为什么必须逐页验
----------------
同名书在平台上有一堆（人教社 / 北京社 / 河北社 / 聋校实验教科书…），
而且**同名不同版**：
「义务教育教科书•数学一年级上册」
  · 我们本地 PDF（2022 审定版）：目录是「准备课 / 位置 / 5以内数的认识和加减法 / 认识图形（一）」
  · 平台上（2024 审定版）：      目录是「数学游戏 / 5以内数的认识和加、减法 / 认识立体图形 / 复习与关联」
**页数一样（118）但内容不同** —— 页码对不上，显示出来就是错的页。

**判据**：同一本扫描件，逐页的感知哈希应当**逐页都对得上**。
  · 取样本页（封面 / 中间几页 / 结尾）
  · 每页算 dHash，比较汉明距离
  · **多页都对得上**才算同一本（单页撞哈希不说明问题）

跑:  python3 src/verify_page_alignment.py <bookId> [--probe]
"""
import argparse
import collections
import io
import json
import pathlib
import re
import sys
import urllib.request

BASE = pathlib.Path(__file__).resolve().parent.parent
PDF_CACHE = BASE / "data" / "pdf-cache"
DETAIL = "https://bdcs-file-1.ykt.cbern.com.cn/zxx/ndrv2/resources/tch_material/details/{cid}.json"
INDEX_PARTS = [
    "https://bdcs-file-2.ykt.cbern.com.cn/zxx/ndrs/resources/tch_material/part_100.json",
    "https://bdcs-file-1.ykt.cbern.com.cn/zxx/ndrs/resources/tch_material/part_101.json",
    "https://bdcs-file-1.ykt.cbern.com.cn/zxx/ndrs/resources/tch_material/part_102.json",
    "https://bdcs-file-2.ykt.cbern.com.cn/zxx/ndrs/resources/tch_material/part_103.json",
]
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

GRADE_CN = {"1": "一年级", "2": "二年级", "3": "三年级", "4": "四年级",
            "5": "五年级", "6": "六年级", "7": "七年级", "8": "八年级", "9": "九年级"}
VOL_CN = {"a": "上册", "b": "下册"}
SUBJ_ZH = {"math": "数学", "phys": "物理", "chem": "化学", "bio": "生物"}


def get(url, timeout=60):
    return opener.open(url, timeout=timeout).read()


def dhash_bytes(data):
    from PIL import Image
    im = Image.open(io.BytesIO(data)).convert("L").resize((9, 8), Image.LANCZOS)
    px = list(im.getdata())
    bits = []
    for row in range(8):
        off = row * 9
        for col in range(8):
            bits.append(1 if px[off + col] > px[off + col + 1] else 0)
    v = 0
    for b in bits:
        v = (v << 1) | b
    return v


def dhash_pdf_page(pdf_path, page_idx, dpi=40):
    import fitz
    doc = fitz.open(pdf_path)
    if page_idx >= doc.page_count:
        doc.close()
        return None
    pix = doc[page_idx].get_pixmap(dpi=dpi)
    data = pix.tobytes("png")
    doc.close()
    return dhash_bytes(data)


def ham(a, b):
    return bin(a ^ b).count("1")


def title_of(x):
    t = x.get("global_title")
    return t.get("zh-CN", "") if isinstance(t, dict) else str(t or "")


def load_index():
    idx = []
    for u in INDEX_PARTS:
        try:
            d = json.loads(get(u).decode("utf-8"))
        except Exception:
            continue
        if isinstance(d, list):
            idx += d
        elif isinstance(d, dict):
            for v in d.values():
                if isinstance(v, list):
                    idx += v
    return idx


def candidates(idx, subj_zh, vol):
    out = []
    for x in idx:
        pt = title_of(x)
        if not pt or subj_zh not in pt:
            continue
        if vol.startswith("m"):
            if "必修" not in pt:
                continue
        elif vol.startswith("x"):
            if "选择性必修" not in pt:
                continue
        else:
            g = GRADE_CN.get(vol[0])
            if not g or g not in pt or VOL_CN[vol[1]] not in pt:
                continue
        out.append(x)
    return out


def base_of(cid):
    d = json.loads(get(DETAIL.format(cid=cid)).decode("utf-8"))
    pv = (d.get("custom_properties") or {}).get("preview") or {}
    if not pv:
        return None, None
    k = sorted(pv, key=lambda s: int("".join(c for c in s if c.isdigit()) or 0))[0]
    return re.sub(r"/\d+\.jpg.*$", "", pv[k]), d


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("book", help="book id，如 math-7a / 1a")
    ap.add_argument("--samples", type=int, default=5)
    args = ap.parse_args()

    full = args.book if "-" in args.book else f"math-{args.book}"
    subj, vol = full.split("-", 1)
    subj_zh = SUBJ_ZH[subj]

    pdf = PDF_CACHE / f"rjb-{subj}-{vol}.pdf"
    if not pdf.exists():
        hits = list(PDF_CACHE.glob(f"*{vol}.pdf"))
        pdf = hits[0] if hits else None
    if not pdf:
        print(f"没有 {full} 的本地 PDF")
        return 1

    import fitz
    doc = fitz.open(pdf)
    npages = doc.page_count
    doc.close()
    print(f"《{full}》本地 PDF {npages} 页  ({pdf.name})\n")

    idx = load_index()
    cands = candidates(idx, subj_zh, vol)
    print(f"平台候选 {len(cands)} 个\n")

    # 样本页：封面 + 均匀分布的中间页
    sample_pages = [0] + [int((npages - 1) * (i + 1) / (args.samples + 1))
                          for i in range(args.samples)]
    sample_pages = sorted(set(p for p in sample_pages if 0 <= p < npages))
    print("样本页（PDF 页号 0 起）:", sample_pages, "\n")

    our = {p: dhash_pdf_page(pdf, p) for p in sample_pages}

    results = []
    for x in cands:
        cid = x["id"]
        try:
            base, d = base_of(cid)
        except Exception:
            continue
        if not base:
            continue
        dists = []
        for p in sample_pages:
            try:
                data = get(base + f"/{p + 1}.jpg", timeout=30)
                dists.append(ham(our[p], dhash_bytes(data)))
            except Exception:
                dists.append(None)
        ok = [v for v in dists if v is not None]
        results.append((sum(ok) / len(ok) if ok else 999,
                        sum(1 for v in ok if v <= 10), cid, title_of(x), dists))

    results.sort()
    for avg, nmatch, cid, t, dists in results[:6]:
        mark = " ✓" if nmatch >= max(3, len(sample_pages) - 1) else ""
        print(f"  平均距离 {avg:5.1f} · 多页吻合 {nmatch}/{len(sample_pages)}  {cid[:8]}  {t[:44]}{mark}")
        print(f"      逐页: {dists}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
