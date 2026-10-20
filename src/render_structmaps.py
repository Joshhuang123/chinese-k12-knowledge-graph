#!/usr/bin/env python3
"""
把每本教材里的「本章知识结构图」渲染成 PNG。

## 为什么

人教教材每一章的小结第一项都是「一、本章知识结构图」——
**那是教材自己画的知识网络**：节点是概念，边带方向、边上还有文字标注
（「归纳/抽象」「解方程」「检验」「降次」…）。

这些图是**图片**，文本层里是空白，`pdftotext` 一个字都抽不出来。
但它们比回指句强得多：

- **每章都有**（九上 10 章，23 册数学约 90 张）
- 节点和边都明确，还有边的语义
- 是**人教社编的**先修关系，不是我们猜的

## 定位办法

- **有文本层的册**（`pdftotext -layout` 每页找「知识结构图」）
- **扫描件**（7b/8b/9b/m1/m2/x1/x2）文本层是空的，
  改用 OCR 出来的 `.ocr.txt`（带 `<<<PAGE n>>>` 标记）定位页码

## 跑法

```bash
python3 src/render_structmaps.py              # 全部，输出到 /tmp/kgimg
python3 src/render_structmaps.py --books 9a    # 只某几册
python3 src/render_structmaps.py --out data/pdf-cache/structmaps
```
"""
import argparse
import pathlib
import re
import subprocess
import sys

BASE = pathlib.Path(__file__).resolve().parent.parent
CACHE = BASE / "data" / "pdf-cache"
MARK = "<<<PAGE "

BOOKS = ["1a", "1b", "2a", "2b", "3a", "3b", "4a", "4b", "5a", "5b",
         "6a", "6b", "7a", "7b", "8a", "8b", "9a", "9b",
         "m1", "m2", "x1", "x2", "x3"]
# 图谱册次码 → PDF 文件名码
FILE = {"bx1": "m1", "bx2": "m2",
        "xzxbx1": "x1", "xzxbx2": "x2", "xzxbx3": "x3"}


def pages_of(pdf):
    out = subprocess.run(["pdfinfo", str(pdf)], capture_output=True, text=True).stdout
    m = re.search(r"Pages:\s+(\d+)", out)
    return int(m.group(1)) if m else 0


def find_by_textlayer(pdf, n):
    """有文本层：逐页找「知识结构图」。"""
    hits = []
    for p in range(1, n + 1):
        t = subprocess.run(["pdftotext", "-layout", "-f", str(p), "-l", str(p),
                            str(pdf), "-"], capture_output=True, text=True).stdout
        if "知识结构" in t:      # 高中没有「图」字，只认「知识结构」
            hits.append(p)
    return hits


def find_by_ocr(pdf, n):
    """扫描件：用 .ocr.txt 的页标记定位（OCR 文本里能搜到「知识结构图」）。"""
    ocr = pdf.with_suffix(".ocr.txt")
    if not ocr.exists():
        return []
    txt = ocr.read_text(encoding="utf-8", errors="replace")
    pages = txt.split(MARK)
    hits = []
    for i, seg in enumerate(pages[1:], start=1):
        # 只认「知识结构图」这一个词。
        # 原来还兜底匹配「小…结…本章」，OCR 里「小结」两个字经常被拆到
        # 不同行或不同页上，于是连续三四页全被圈进来（7b 21 处 vs 9a 5 处）。
        # 高中教材写的是「一、本章知识结构」（**没有「图」字**），
        # 初中才是「本章知识结构图」。两个都要认。
        if "知识结构" in seg:
            hits.append(i)
    return hits


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--books", default="")
    ap.add_argument("--out", default="/tmp/kgimg")
    ap.add_argument("--dpi", type=int, default=150)
    args = ap.parse_args()

    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    books = [b.strip() for b in args.books.split(",") if b.strip()] or BOOKS

    total = 0
    for bk in books:
        pdf = CACHE / f"rjb-math-{FILE.get(bk, bk)}.pdf"
        if not pdf.exists():
            print(f"  {bk}: 没有 PDF")
            continue
        n = pages_of(pdf)
        if not n:
            print(f"  {bk}: 读不出页数")
            continue
        has_text = pdf.with_suffix(".txt")
        has_text = has_text.exists() and has_text.stat().st_size > 20000
        hits = find_by_textlayer(pdf, n) if has_text else find_by_ocr(pdf, n)
        # OCR 定位不额外多取页 —— 「知识结构图」这个词本身够准，
        # 多取反而把小结的正文页也圈进来。
        for p in hits:
            dst = out / f"{bk}-p{p:03d}"
            if not list(dst.parent.glob(f"{bk}-p{p:03d}*.png")):
                subprocess.run(["pdftoppm", "-f", str(p), "-l", str(p),
                                "-r", str(args.dpi), "-png", str(pdf), str(dst)],
                               capture_output=True)
        total += len(hits)
        print(f"  {bk}: {len(hits)} 处（{'文本层' if has_text else 'OCR'}）→ {hits}")
    print(f"\n合计 {total} 处，输出目录 {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
