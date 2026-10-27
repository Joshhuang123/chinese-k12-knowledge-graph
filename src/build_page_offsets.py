#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
算每册教材的**印刷页码偏移**：书上印的页码 = PDF 扫描页 + offset。

为什么需要它
------------
「教材原页」面板原来只显示**扫描页码**（PDF 的第几页）。
但学生手里的是**纸书**，书上印的是**印刷页码** —— 两者差着封面、版权页、
本册导引、目录的页数（实测 4–7 页）。

实测差多少：

    math-7a/50  → 书上印 43   （差 7）
    math-9a/110 → 书上印 103  （差 7）
    chem-9a/99  → 书上印 94   （差 5）
    phys-8b/53  → 书上印 49   （差 4）

按扫描页号去翻书，**翻到的不是那一页**。

怎么算
------
**两种教材，两条路**：

1. **矢量 PDF（28 册里的 15 册）** —— 页脚有印刷页码。
   ⚠️ **不能用 `get_text()` 取尾部**：人教 PDF 里页码的字符是**反序**的，
   `20` 会提成 `02`、`103` 会提成 `301`（实测）。
   正确做法是取 `rawdict` 的**字符级 bbox**，按 x 坐标排序后重排 —— 反序就还原了。
   再按位置（页脚带 = 页面底部 10%）过滤掉正文里的数字。

2. **扫描件 PDF（其余册，无文本层）** —— 走已有的 OCR 文本
   （`data/pdf-cache/rjb-*.ocr.txt`，`<<<PAGE n>>>` 分页）。
   取每页正文**末尾 40 字**里的独立数字当作页脚页码。

**取众数当 offset**，并且要求一致性达标：

- 至少 20 页给出候选
- 众数占比 ≥ 85%

达不到就**不写这一册**（宁可少抽，不抽错）—— 页面上就退回显示扫描页码。

跑:  python3 src/build_page_offsets.py
"""
import collections
import json
import pathlib
import re
import sys
import unicodedata

BASE = pathlib.Path(__file__).resolve().parent.parent
PDFC = BASE / "data" / "pdf-cache"
OUT_JSON = BASE / "data" / "page-offsets.json"
OUT_JS = BASE / "data" / "page-offsets.js"

# 学科缩写：PDF 文件名用缩写，视觉层/图谱用全名
SUBJ_ABBR = {"biology": "bio", "chemistry": "chem", "physics": "phys", "math": "math"}
# 高中册次码：图谱 bx1/bx2/xzxbx1… ↔ 文件名 m1/m2/x1…
HIGH_VOL = {"bx1": "m1", "bx2": "m2", "bx3": "m3",
            "xzxbx1": "x1", "xzxbx2": "x2", "xzxbx3": "x3"}

MIN_CANDIDATES = 20      # 少于这个页数就当没算出来
MIN_AGREE = 0.85         # 众数占比门槛


def nfkc(s: str) -> str:
    """全角 → 半角。人教 PDF 文本层里数字是全角的（２１．１）。"""
    return unicodedata.normalize("NFKC", s or "")


def _footer_rows(page):
    """页面底部 10% / 顶部 8% 里，按字符 x 坐标重排后的行文本。

    ⚠️ 必须用 rawdict 的字符级 bbox —— `get_text()` 会把页码字符**反序**输出。
    """
    r = page.rect
    h = r.height
    rows = []
    raw = page.get_text("rawdict")
    for blk in raw.get("blocks", []):
        if blk.get("type") != 0:      # 0 = 文本块
            continue
        for ln in blk.get("lines", []):
            for band, top in ((0.10, False), (0.08, True)):
                chars = []
                for sp in ln.get("spans", []):
                    for ch in sp.get("chars", []):
                        y0, y1 = ch["bbox"][1], ch["bbox"][3]
                        hit = (y0 >= h * (1 - band)) if not top else (y1 <= h * band)
                        if hit:
                            chars.append((ch["bbox"][0], ch["c"]))
                if chars:
                    chars.sort(key=lambda c: c[0])
                    rows.append(nfkc("".join(c[1] for c in chars)).strip())
                break    # 一行只归属一个带，别重复收
    return rows


def pdf_footer_numbers(doc):
    """矢量 PDF → {扫描页: 印刷页码}"""
    out = {}
    for i in range(doc.page_count):
        nums = [int(s) for s in _footer_rows(doc[i]) if re.fullmatch(r"\d{1,4}", s)]
        if len(nums) == 1:            # 页脚只有一个数字时才认
            out[i + 1] = nums[0]
    return out


def ocr_footer_numbers(txt: str):
    """扫描件 OCR 文本 → {扫描页: 印刷页码}"""
    parts = re.split(r"<<<PAGE (\d+)>>>", txt)
    out = {}
    for i in range(1, len(parts) - 1, 2):
        pg = int(parts[i])
        body = parts[i + 1]
        tail = nfkc(body[-40:])
        nums = re.findall(r"\d{1,3}", tail)
        if len(nums) == 1:
            out[pg] = int(nums[0])
    return out


def book_files(pdf_book: str):
    """视觉层的册次码（biology-7a）→ (PDF 路径, OCR 文本路径)"""
    head, rest = pdf_book.split("-", 1)
    rest = HIGH_VOL.get(rest, rest)
    stem = f"rjb-{SUBJ_ABBR.get(head, head)}-{rest}"
    return PDFC / f"{stem}.pdf", PDFC / f"{stem}.ocr.txt"


def main() -> int:
    import fitz
    try:
        fitz.TOOLS.mupdf_display_errors(False)
    except Exception:
        pass

    # 册次清单：从视觉层拿，别手抄
    books = []
    for line in (BASE / "data" / "concept-vision.jsonl").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        if r.get("subject") and r.get("book"):
            books.append(f"{r['subject']}-{r['book']}")
    books = sorted(set(books))

    offsets = {}
    report = {}
    for bk in books:
        pdf, ocr = book_files(bk)
        if not pdf.exists():
            continue
        doc = fitz.open(pdf)
        has_text = bool(doc[min(10, doc.page_count - 1)].get_text().strip())
        if has_text:
            nums = pdf_footer_numbers(doc)
            src = "pdf"
        else:
            doc.close()
            doc = None
            nums = {}
            if ocr.exists():
                nums = ocr_footer_numbers(ocr.read_text(encoding="utf-8", errors="replace"))
                src = "ocr"
            else:
                src = "none"
        if doc:
            doc.close()

        diffs = collections.Counter()
        for pg, printed in nums.items():
            diffs[printed - pg] += 1
        if not diffs:
            report[bk] = "无候选"
            continue
        off, cnt = diffs.most_common(1)[0]
        total = sum(diffs.values())
        agree = cnt / total
        if total < MIN_CANDIDATES or agree < MIN_AGREE:
            report[bk] = f"弃用（{cnt}/{total} = {agree:.0%} < 门槛）"
            continue
        offsets[bk] = off
        report[bk] = f"offset={off:+d}  {cnt}/{total} ({agree:.0%})  来源={src}"

    OUT_JSON.write_text(json.dumps(offsets, ensure_ascii=False, indent=1), encoding="utf-8")
    OUT_JS.write_text("window.PAGE_OFFSETS=" +
                      json.dumps(offsets, ensure_ascii=False, separators=(",", ":")) + ";\n",
                      encoding="utf-8")

    print(f"算出 {len(offsets)}/{len(books)} 册的印刷页码偏移\n")
    for bk in books:
        if bk in report:
            print(f"  {bk:16s} {report[bk]}")
    print(f"\n→ {OUT_JSON.relative_to(BASE)}")
    print(f"→ {OUT_JS.relative_to(BASE)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
