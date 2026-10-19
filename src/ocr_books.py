#!/usr/bin/env python3
"""
给没有文本层的教材跑 OCR。产物只留在 data/pdf-cache/（已 gitignore）。

为什么要 OCR：
  11 册初高中人教里，7b/8b/9b 是**纯扫描件**（pdffonts 一行都没有，
  每页一张 JPEG），x1/m1 大部分页也是图 —— 这 6 册 pdftotext 只能抽出
  几百到两千字节。而定义重写要靠正文，没正文就没法核对。

  剩下 5 册（7a/8a/9a/m2/x3）有完整文本层，走 pdftotext 就够。

OCR 质量说明（人教七下第 12 页实测）：
  正文和小节标题 **可靠** —— 「5.1.3 同位角、内错角、同旁内角」原样抽出
  公式 **不可靠** —— 「∠C=90°」变成「C=90」，分数和小数点会丢
所以这套 OCR 只用来定位「哪个概念在第几页、正文怎么说」，
**绝不拿它当公式或者计算题的答案来源**。定义重写也要人过一眼。

跑法：
    python3 src/ocr_books.py            # 只跑没做过的
    python3 src/ocr_books.py --books 7b --force
"""
import argparse
import pathlib
import subprocess
import sys
import tempfile
import time

BASE = pathlib.Path(__file__).resolve().parent.parent
CACHE = BASE / "data" / "pdf-cache"
PDFTOPPM = "/opt/homebrew/bin/pdftoppm"
TESSERACT = "/opt/homebrew/bin/tesseract"

# 没有文本层的册次（pdftotext 抽出来不到 2 万字节的）
SCANNED = ["7b", "8b", "9b", "x1", "m1", "m2"]
DPI = 200


def pages_of(pdf):
    out = subprocess.run(["pdfinfo", str(pdf)], capture_output=True, text=True)
    for line in out.stdout.splitlines():
        if line.startswith("Pages:"):
            return int(line.split()[1])
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--books", help="逗号分隔，如 7b,8b")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    books = args.books.split(",") if args.books else SCANNED

    for bk in books:
        pdf = CACHE / f"rjb-math-{bk}.pdf"
        txt = CACHE / f"rjb-math-{bk}.ocr.txt"
        if txt.exists() and not args.force:
            print(f"  {bk} 已有 OCR（{txt.stat().st_size//1024} KB），跳过")
            continue
        n = pages_of(pdf)
        if not n:
            print(f"  {bk} 读不出页数，跳过")
            continue
        print(f"  {bk} {n} 页 → OCR，预计 {int(n*1.8/60)} 分钟", flush=True)
        t0 = time.time()
        buf = []
        with tempfile.TemporaryDirectory() as td:
            for p in range(1, n + 1):
                subprocess.run([PDFTOPPM, "-f", str(p), "-l", str(p),
                                "-r", str(DPI), "-png", str(pdf),
                                f"{td}/pg"], capture_output=True)
                pngs = sorted(pathlib.Path(td).glob("pg*.png"))
                if not pngs:
                    continue
                r = subprocess.run([TESSERACT, str(pngs[0]), "stdout",
                                    "-l", "chi_sim", "--psm", "3"],
                                   capture_output=True, text=True)
                buf.append(f"\n<<<PAGE {p}>>>\n{r.stdout}")
                pngs[0].unlink()
                if p % 20 == 0:
                    print(f"    {p}/{n}  {int(time.time()-t0)}s", flush=True)
        txt.write_text("".join(buf), encoding="utf-8")
        print(f"  {bk} ✓ {txt.stat().st_size//1024} KB  用时 {int(time.time()-t0)}s")


if __name__ == "__main__":
    sys.exit(main())
