#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
查「我们的教材原话到底出自哪个出版社」。

为什么需要这个
--------------
`data/pdf-cache/alt/` 里存着**同一个年级段的多个出版社版本**（人教/冀教/北京/
华东师大/沪科/浙教/湘教/苏科/青岛），每套都正好覆盖初中数学七上–九下这 6 册。
而**我们的人教版数据也正好是这 6 册的初中数学**。

两边册次范围完全重合，光看目录名极容易认错册 —— 一旦认错，
「教材原页」挂的就是别的出版社的书。

判据（独立于被测对象）
--------------------
不查「PDF 里写没写人民教育出版社」（扫描件没有文本层，查不了），
而是拿**教材原话本身**去撞文本：

    命中率(版本) = 该版本 PDF 全文里能原样找到的教材原话条数 / 总条数

- 我们的 PDF 命中率必须 **≥ 50%**
- 且必须 **≥ 3 ×** 所有其他出版社版本的最高命中率

之所以要加第二道：像「在同一平面直角坐标系中描出下列各组点」这种句子，
人教版和青岛版都有（**1%–2% 的偶然撞词**）。只看「我们的命中高」不够，
得看「我们的是压倒性地高」。

判别力自检：把青岛版 PDF 冒充成人教版喂进去，本脚本必须报红。

跑:  python3 src/check_publisher.py
"""
import json
import pathlib
import re
import sys
import unicodedata

BASE = pathlib.Path(__file__).resolve().parent.parent
PDFC = BASE / "data" / "pdf-cache"
ALT = PDFC / "alt"

# 我们的册次码 ↔ 教材里的中文册名
VOLS = {"7a": "七上", "7b": "七下", "8a": "八上",
        "8b": "八下", "9a": "九上", "9b": "九下"}
VOLS_ZH = {v: k for k, v in VOLS.items()}

# 概念原话文件里 subject=math / book=7a…9b 的条目才参与比对
SUBJ = "math"
MIN_QUOTE_LEN = 10     # 太短的句子到处都撞词，没有判别力


def nfkc(s: str) -> str:
    """全角数字/字母归一化 —— 人教 PDF 文本层里数字是全角的。"""
    s = unicodedata.normalize("NFKC", s or "")
    return re.sub(r"\s+", "", s)


def pdf_text(pdf: pathlib.Path, ocr: pathlib.Path) -> str:
    """先试 PDF 文本层；扫描件（无文本层）回落到 OCR 文本。"""
    if pdf.exists():
        try:
            import fitz
            try:
                fitz.TOOLS.mupdf_display_errors(False)   # 扫描件里的坏 XObject，别刷屏
            except Exception:
                pass
            doc = fitz.open(pdf)
            t = "".join(doc[i].get_text() for i in range(doc.page_count))
            doc.close()
            if t.strip():
                return nfkc(t)
        except Exception:
            pass
    if ocr.exists():
        return nfkc(ocr.read_text(encoding="utf-8", errors="replace"))
    return ""


def ours_text(vol: str) -> str:
    return pdf_text(PDFC / f"rjb-math-{vol}.pdf",
                    PDFC / f"rjb-math-{vol}.ocr.txt")


def alt_texts(vol: str):
    """→ [(版本名, 全文)]，各出版社版本。"""
    zh = VOLS[vol]
    out = []
    for d in sorted(ALT.iterdir()) if ALT.exists() else []:
        if not d.is_dir():
            continue
        pdf = d / f"{zh}.pdf"
        if not pdf.exists():
            continue
        out.append((d.name, pdf_text(pdf, d / f"{zh}.txt")))
    return out


def quotes_by_vol():
    """→ {册次: [教材原话…]}"""
    res = {v: [] for v in VOLS}
    f = BASE / "data" / "concept-text.jsonl"
    for line in f.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        if r.get("subject") != SUBJ or r.get("book") not in res:
            continue
        for q in (r.get("quotes") or []):
            qn = nfkc(q)
            if len(qn) >= MIN_QUOTE_LEN:
                res[r["book"]].append(qn)
    return res


def main() -> int:
    qb = quotes_by_vol()
    bad = []
    print(f"教材原话来源核查：{SUBJ} 初中 {len(VOLS)} 册 × 各出版社版本\n")
    for vol in VOLS:
        quotes = qb[vol]
        if not quotes:
            print(f"{VOLS[vol]}  没有可比对的原话，跳过")
            continue
        ours = ours_text(vol)
        if not ours:
            print(f"{VOLS[vol]}  读不到我们自己的 PDF/OCR 文本")
            bad.append((vol, "no-text"))
            continue
        our_rate = sum(1 for q in quotes if q in ours) / len(quotes)

        alts = alt_texts(vol)
        rates = []
        for name, txt in alts:
            if not txt:
                rates.append((name, None))
                continue
            r = sum(1 for q in quotes if q in txt) / len(quotes)
            rates.append((name, r))

        # ⚠️ `alt/初中数学人教版` 是**同一本书**（另存的一份），
        # 拿它当对照组会让比值恒等于 1 —— 它只能是阳性对照，不参与「最高」计算。
        SELF = "初中数学人教版"
        known = [(n, r) for n, r in rates if r is not None and n != SELF]
        best_alt = max((r for _, r in known), default=0.0)
        best_name = max(known, key=lambda x: x[1])[0] if known else "—"

        ok = our_rate >= 0.50 and our_rate >= 3 * best_alt
        mark = "✓" if ok else "✗"
        self_rate = next((r for n, r in rates if n == SELF), None)
        self_note = f"  阳性对照(alt人教版)={self_rate*100:.1f}%" if self_rate is not None else ""
        print(f"{mark} {VOLS[vol]}（{vol}）"
              f"  我们={our_rate*100:5.1f}%"
              f"   其他版本最高={best_alt*100:4.1f}%（{best_name}）"
              f"   比值={our_rate/max(best_alt,1e-9):6.1f}×"
              f"   原话 {len(quotes)} 条{self_note}")
        for n, r in sorted(rates, key=lambda x: -(x[1] or 0)):
            if n == SELF:
                continue
            print(f"      · {n:22s} {(r*100 if r is not None else 0):5.1f}%")
        if not ok:
            bad.append((vol, f"我们={our_rate:.1%} 其他最高={best_alt:.1%}"))

    print()
    if bad:
        print(f"❌ 判据未通过：{bad}")
        return 1
    print("✅ 全部通过：教材原话出自人教版本地 PDF，未混入其他出版社版本")
    return 0


if __name__ == "__main__":
    sys.exit(main())
