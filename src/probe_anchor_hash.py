#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测一件事：**dHash 能不能在平台的扫描本里找出「章首页」**。

为什么重要
----------
平台的书里，扫描页 N 的页脚印着印刷页 P。
要把「我们 PDF 的页」对应到「平台的页」，就需要 **偏移 = 扫描页 − 印刷页**。
偏移每本书不同（前置页数不一样），只能逐本求。

**章首页是最好的锚点**：
  · 视觉特征极强（整页大标题 + 大量留白）→ dHash 应该能认出来
  · 而且它的印刷页号从目录里读得到（目录里有「第一章 XXX …… N」）

这一条走不通，整条路就走不通 —— 所以先单独验它。

跑:  python3 src/probe_anchor_hash.py <subject> <vol>
"""
import collections
import io
import json
import pathlib
import re
import sys

BASE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE / "src"))

from verify_page_alignment import (DETAIL, GRADE_CN, SUBJ_ZH, VOL_CN,  # noqa: E402
                                  candidates, dhash_bytes, get, ham, load_index, title_of)


def dhash_pdf_page(pdf_path, page_idx, dpi=40):
    import fitz
    doc = fitz.open(pdf_path)
    if page_idx >= doc.page_count:
        doc.close()
        return None
    data = doc[page_idx].get_pixmap(dpi=dpi).tobytes("png")
    doc.close()
    return dhash_bytes(data)


def chapter_pages(pdf_path):
    """从 PDF 文本层找出章首页（整页只有「第N章 XXX」那种大标题）。"""
    import fitz
    doc = fitz.open(pdf_path)
    hits = []
    for i in range(doc.page_count):
        t = doc[i].get_text().strip()
        if not t:
            continue
        lines = [x for x in t.split("\n") if x.strip()]
        # 章首页特征：页面上有一个「第N章 XXX」的行，且整页行数很少
        chap = [x for x in lines if re.match(r"^第[0-9一二三四五六七八九十]+章", x.strip())]
        if chap and len(lines) <= 6:
            hits.append((i, " | ".join(lines[:3])[:60]))
    doc.close()
    return hits


def main() -> int:
    subj = sys.argv[1] if len(sys.argv) > 1 else "math"
    vol = sys.argv[2] if len(sys.argv) > 2 else "7a"
    pdf = BASE / "data" / "pdf-cache" / f"rjb-{subj}-{vol}.pdf"
    if not pdf.exists():
        print(f"没有 {pdf}")
        return 1

    caps = chapter_pages(pdf)
    print(f"我们 PDF 里的章首页（扫描页 0 起）：{len(caps)} 个")
    for i, t in caps[:6]:
        print(f"   扫描页 {i:3d}  {t}")
    if not caps:
        print("没找到章首页")
        return 1

    idx = load_index()
    cands = candidates(idx, SUBJ_ZH[subj], vol)
    print(f"\n平台候选 {len(cands)} 个")

    our = {i: dhash_pdf_page(pdf, i) for i, _ in caps[:3]}
    for x in cands[:4]:
        try:
            d = json.loads(get(DETAIL.format(cid=x["id"])).decode("utf-8"))
        except Exception:
            continue
        pv = (d.get("custom_properties") or {}).get("preview") or {}
        if not pv:
            continue
        base = re.sub(r"/\d+\.jpg.*$", "", pv[sorted(pv, key=lambda s: int("".join(c for c in s if c.isdigit()) or 0))[0]])
        # 平台前 49 页里找我们章首页的最佳匹配
        best = []
        for p in range(1, 50):
            try:
                data = get(base + f"/{p}.jpg", timeout=25)
            except Exception:
                continue
            h2 = dhash_bytes(data)
            for i, h in our.items():
                if h is None:
                    continue
                best.append((ham(h, h2), i, p))
        best.sort()
        if best:
            b = best[0]
            print(f"  {x['id'][:8]} 最佳: 我们扫描页{b[1]} ↔ 平台扫描页{b[2]}  距离{b[0]}"
                  f"   {title_of(x)[:34]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
