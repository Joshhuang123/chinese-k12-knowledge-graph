#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
给**其他出版社**的教材跑 OCR。产物只留在 data/pdf-cache/（已 gitignore）。

为什么要
--------
`src/ocr_books.py` 只管人教那 11 册。ChinaTextbook 里还有 45 册其他版本
（沪科/浙教/湘教/冀教/苏科/北京/华东师大/青岛），其中 18 册是**纯扫描件**
（pdftotext 抽出来不到 2 万字节），没有正文。

而正文是「概念 ↔ 教材原话」这一层的**唯一原料**：
  - 概念名在正文里出现 → 这一页真的在讲这个概念
  - 教材的定义句（「叫做二次函数」）→ 写稿最值钱的引用

没有 OCR，这些版本就只剩视觉层的公式和图，**没有一句话**。

产物命名
--------
`data/pdf-cache/alt/<出版社>/<册次>.txt` —— **正是 `pdf_to_units.py`
第 341 行期待的那个路径**（它扫 `alt/*/<bk>.txt`）。
OCR 完直接重跑 `pdf_to_units.py` 就能接上，不用改下游。

标记
----
用 `<<<PAGE n>>>` 分页，跟人教那套一致（`pdf_to_units.pages_of` 认这个）。

质量（人教七下第 12 页实测）
-----------------------------
正文和小节标题 **可靠**；**公式不可靠**（「∠C=90°」→「C=90」，
分数和小数点会丢）。所以这套 OCR 只用来定位「哪个概念在第几页、正文怎么说」，
**绝不拿它当公式来源**——公式有视觉层管。

跑法
----
    python3 src/ocr_alt.py                  # 只跑没有文本层的
    python3 src/ocr_alt.py --jobs 4
    python3 src/ocr_alt.py --only 初中数学湘教版
"""
from __future__ import annotations

import argparse
import glob
import os
import pathlib
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

BASE = pathlib.Path(__file__).resolve().parent.parent
CACHE = BASE / "data" / "pdf-cache"
ALT = CACHE / "alt"
PDFTOPPM = "/opt/homebrew/bin/pdftoppm"
TESSERACT = "/opt/homebrew/bin/tesseract"
DPI = 200
# 有文本层的判据：pdftotext 抽出来不到这个字节数就当扫描件
MIN_TEXT_BYTES = 20000

print_lock = __import__("threading").Lock()


def pages_of(pdf) -> int:
    out = subprocess.run(["pdfinfo", str(pdf)], capture_output=True, text=True)
    for line in out.stdout.splitlines():
        if line.startswith("Pages:"):
            return int(line.split()[1])
    return 0


def has_text_layer(pdf) -> bool:
    """用 pdftotext 试一下。抽得出足够文字就不是扫描件。"""
    try:
        r = subprocess.run(["pdftotext", "-f", "1", "-l", "30", str(pdf), "-"],
                           capture_output=True, timeout=120)
        return len(r.stdout) >= MIN_TEXT_BYTES
    except Exception:
        return False


def ocr_book(pdf: pathlib.Path, txt: pathlib.Path, force: bool) -> tuple[str, int, int]:
    """OCR 一本书。返回 (名字, 页数, 用时秒)。"""
    if txt.exists() and not force:
        return (pdf.parent.name + "/" + pdf.stem, -1, 0)
    n = pages_of(pdf)
    if not n:
        return (pdf.parent.name + "/" + pdf.stem, 0, 0)
    t0 = time.time()
    buf = []
    with tempfile.TemporaryDirectory() as td:
        for p in range(1, n + 1):
            subprocess.run([PDFTOPPM, "-f", str(p), "-l", str(p),
                            "-r", str(DPI), "-png", str(pdf), f"{td}/pg"],
                           capture_output=True)
            pngs = sorted(pathlib.Path(td).glob("pg*.png"))
            if not pngs:
                continue
            r = subprocess.run([TESSERACT, str(pngs[0]), "stdout",
                                "-l", "chi_sim", "--psm", "3"],
                               capture_output=True, text=True)
            buf.append(f"\n<<<PAGE {p}>>>\n{r.stdout}")
            pngs[0].unlink()
    txt.write_text("".join(buf), encoding="utf-8")
    return (pdf.parent.name + "/" + pdf.stem, n, int(time.time() - t0))


def _sha(p) -> str:
    import hashlib
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def find_duplicate_ocr(pdf: pathlib.Path) -> pathlib.Path | None:
    """**同 SHA-256 的书，别重跑 OCR。**

    ChinaTextbook 的 `alt/初中数学人教版/七下.pdf` 和 `rjb-math-7b.pdf`
    是同一个文件（逐字节相同），而人教那套的 OCR 早就跑过了。
    重复跑一遍 437 页纯属浪费 —— 而且两边的 OCR 结果本来就应该一样。
    """
    try:
        h = _sha(pdf)
    except Exception:
        return None
    for cand in CACHE.glob("*.ocr.txt"):
        # 人教的 OCR 文件名是 rjb-math-7b.ocr.txt，对应的 pdf 是 rjb-math-7b.pdf
        base = cand.name[:-len(".ocr.txt")]
        other = CACHE / f"{base}.pdf"
        if not other.exists() or other == pdf:
            continue
        try:
            if _sha(other) == h:
                return cand
        except Exception:
            continue
    return None


def copy_duplicate(pdf: pathlib.Path, txt: pathlib.Path, src: pathlib.Path) -> tuple[str, int]:
    """复制已有的 OCR 结果。返回 (名字, 页数)。"""
    body = src.read_text(encoding="utf-8")
    txt.write_text(body, encoding="utf-8")
    return (pdf.parent.name + "/" + pdf.stem, pages_of(pdf))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--jobs", type=int, default=3, help="并发 OCR 几本书")
    ap.add_argument("--only", help="只跑某个出版社目录名（子串匹配）")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--dry-run", action="store_true", help="只列计划，不跑")
    args = ap.parse_args()

    pdfs = sorted(glob.glob(str(ALT / "*" / "*.pdf")))
    todo = []
    for p in pdfs:
        pdf = pathlib.Path(p)
        txt = pdf.with_suffix(".txt")
        if txt.exists() and not args.force:
            continue
        if args.only and args.only not in str(pdf.parent):
            continue
        todo.append((pdf, txt))

    print(f"扫描件 {len(todo)} 本（{sum(pages_of(p) for p, _ in todo)} 页）")
    for pdf, txt in todo:
        mark = "扫描件" if not has_text_layer(pdf) else "有文本层"
        print(f"  {pdf.parent.name}/{pdf.stem}  {pages_of(pdf):>4} 页  {mark}")
    if args.dry_run:
        return 0
    if not todo:
        print("没���要跑的")
        return 0

    t0 = time.time()
    done = 0
    with ThreadPoolExecutor(max_workers=args.jobs) as ex:
        # 先挑出「跟人教正本重复」的，直接复制 OCR 结果，不重跑
        futs = {}
        for pdf, txt in todo:
            dup = None if args.force else find_duplicate_ocr(pdf)
            if dup is not None:
                try:
                    name, n = copy_duplicate(pdf, txt, dup)
                    done += 1
                    with print_lock:
                        print(f"  ✓ {name}  {n} 页  复用 {dup.name}（同一本书，"
                              f"不重跑）  [{done}/{len(todo)}]", flush=True)
                    continue
                except Exception as e:
                    with print_lock:
                        print(f"  ! {pdf.parent.name}/{pdf.stem} 复用失败：{e}", flush=True)
            futs[ex.submit(ocr_book, pdf, txt, args.force)] = (pdf, txt)
        for fu in as_completed(futs):
            pdf, txt = futs[fu]
            try:
                name, n, el = fu.result()
            except Exception as e:
                with print_lock:
                    print(f"  ✗ {pdf.parent.name}/{pdf.stem}  {str(e)[:120]}", flush=True)
                continue
            done += 1
            with print_lock:
                if n < 0:
                    print(f"  · {name} 已有，跳过", flush=True)
                else:
                    print(f"  ✓ {name}  {n} 页  {el}s  "
                          f"→ {txt.name}（{txt.stat().st_size//1024} KB）"
                          f"  [{done}/{len(todo)}]", flush=True)
    print(f"\n总用时 {int(time.time()-t0)}s")
    print("下一步：python3 src/pdf_to_units.py  # 重新生成教材数据集")
    return 0


if __name__ == "__main__":
    sys.exit(main())
