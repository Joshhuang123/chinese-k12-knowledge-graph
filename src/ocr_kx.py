#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OCR 人教版《小学科学》12 本的页图，抽出每页的汉字正文。

为什么需要
----------
匹配「上游概念 ↔ 小学科学教材页」要的是**页级证据**：
  「磁极间的作用」这一节里到底讲了哪些概念？
节名只是活动标题（「磁极间的作用」），概念名是「磁极」「磁力」——
**节名 ≠ 概念名**。实测 233 个节名里只有 11 个能精确对上上游概念名，
所以必须读页面本身。

产出
----
`data/kx-ocr.jsonl`：每行一页
    {"book": "s6-3a", "page": 12, "text": "……这一页的汉字正文……"}

**只用汉字正文**，不含版面结构 —— 这一层只用来搜概念名。

跑法：python3 src/ocr_kx.py --jobs 6
"""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import pathlib
import re
import subprocess
import sys
import time

BASE = pathlib.Path(__file__).resolve().parent.parent
IMG = BASE / "data" / "pdf-cache" / "kx"
OUT = BASE / "data" / "kx-ocr.jsonl"
TESSERACT = "/opt/homebrew/bin/tesseract"

# OCR 出来会混进一堆非汉字（页码、符号、英文残片），只留汉字和数字
RE_KEEP = re.compile(r"[一-鿿0-9A-Za-z]+")


def ocr_page(path: pathlib.Path) -> str:
    try:
        # **--psm 6**（按块）比默认的 psm 3（自动分页）多抽 ~20% 的字
        # （实测 p012：134 vs 107 字）。小学科学的页是「插图 + 大字」，
        # 自动分页容易把大字块当噪声丢掉。
        r = subprocess.run(
            [TESSERACT, str(path), "stdout", "-l", "chi_sim", "--psm", "6"],
            capture_output=True, text=True, timeout=180)
        return r.stdout or ""
    except Exception:
        return ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--jobs", type=int, default=6)
    ap.add_argument("--resume", action="store_true")
    args = ap.parse_args()

    done = set()
    if args.resume and OUT.exists():
        for line in OUT.open(encoding="utf-8"):
            try:
                r = json.loads(line)
                done.add((r["book"], r["page"]))
            except Exception:
                pass
        print(f"resume: 已有 {len(done)} 页")

    tasks = []
    for d in sorted(IMG.iterdir()):
        if not d.is_dir():
            continue
        for p in sorted(d.glob("p*.jpg")):
            try:
                n = int(p.stem[1:])
            except ValueError:
                continue
            if (d.name, n) in done:
                continue
            tasks.append((d.name, n, p))
    print(f"待处理 {len(tasks)} 页", flush=True)
    if not tasks:
        return 0

    fh = OUT.open("a" if args.resume else "w", encoding="utf-8")
    t0 = time.time()
    ok = fail = 0
    lock = __import__("threading").Lock()

    def work(t):
        book, page, path = t
        txt = ocr_page(path)
        # 只留汉字/数字/字母，压掉空白
        clean = " ".join(RE_KEEP.findall(txt))
        return book, page, clean

    with concurrent.futures.ThreadPoolExecutor(args.jobs) as ex:
        for book, page, clean in ex.map(work, tasks):
            fh.write(json.dumps({"book": book, "page": page, "text": clean},
                                ensure_ascii=False) + "\n")
            ok += 1
            if ok % 100 == 0:
                fh.flush()
                print(f"  {ok}/{len(tasks)}  {time.time()-t0:.0f}s", flush=True)
    fh.close()
    print(f"完成 {ok} 页 → {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
