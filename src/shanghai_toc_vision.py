#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
用**视觉模型**读上海教材的目录页，抽章/节/起始页。

为什么不用 OCR
--------------
tesseract 在彩色底、装饰性排版的目录上很脏（实测）：
  - 章名单独一行，没有「第N章」前缀（「 整式的加减」）
  - 节号带噪声前缀（「、 12.1」「1132 分式的运算」）
  - 页码被读成汉字（「本」）
  - 章名前面粘着别的字（「泛上荆汪 因式分解」）

**视觉模型是看版面的**，这些都能读对。而且教材只有 26 本、每本 2 页目录，
总共 50 来页，跑一遍 API 只要两分钟。

产出的东西是**顺序链的骨架**：
    第10章 整式的加减  → 10.1 整式(p2)  10.2 合并同类项(p5) …
有了起始页，就能把「页 → 节」映射出来，把每个概念挂到它该在的节上。

跑法：python3 src/shanghai_toc_vision.py
"""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import pathlib
import re
import sys
import time

BASE = pathlib.Path("/Users/huangjunhai/Documents/个人/项目/中文知识图谱")
sys.path.insert(0, str(BASE / "src"))
import vision_pages as V          # noqa: E402

IMG = BASE / "data" / "pdf-cache" / "hujiao"
OUT = BASE / "data" / "shanghai-toc.json"
SCAN_FROM, SCAN_TO = 2, 10

PROMPT = """这是一页中国教材的**目录页**。请把目录结构读出来，只输出 JSON：

{"chapters":[
  {"no":"第10章","name":"整式的加减","startPage":1,
   "sections":[{"no":"10.1","name":"整式","startPage":2},
               {"no":"10.2","name":"合并同类项","startPage":5}]}]}

规则：
- "no" 是章号，原样写（第10章 / 第十章 都行）
- "name" 是章名或节名，**只写名称本身**，不要带噪声
- "startPage" 是这一章/这一节**开始的页码**（目录右边那一列的数字）
- 目录里的"内容提要""复习题""阅读材料""综合与实践"这类条目，
  放在 sections 里，no 写空字符串，startPage 写它们的页码
- 页码看不清就写 null，**不要猜**
- 这一页不是目录页就输出 {"chapters":[]}"""


def ocr_dir_page(img: pathlib.Path) -> dict:
    """用视觉模型读一页目录。"""
    url = V.upload(img)
    bodies = V.describe([url], PROMPT, accept=lambda b: _parse(b) is not None)
    return _parse(bodies[0]) or {"chapters": []}


def _parse(body):
    if not body:
        return None
    return V.parse_json_loose(body)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args()

    books = json.load(open(BASE / "data" / "shanghai-textbooks.json",
                           encoding="utf-8"))["books"]
    math_books = [b for b in books if b["subject"] in ("数学", "math")]

    by_slug = {}
    for b in math_books:
        slug = re.sub(r"[^\w一-鿿]+", "_", b["title"])[:30] + "_" + b["contentId"][:8]
        by_slug[slug] = b

    jobs = []
    for slug, b in by_slug.items():
        d = IMG / slug
        if not d.exists():
            continue
        for p in range(SCAN_FROM, SCAN_TO + 1):
            f = d / f"p{p:03d}.jpg"
            if f.exists():
                jobs.append((b, p, f))
    print(f"目录候选页 {len(jobs)} 张（{len(by_slug)} 本）", flush=True)

    def one(j):
        b, p, f = j
        try:
            return (b, p, ocr_dir_page(f))
        except Exception:
            return (b, p, {"chapters": []})

    # 每本书的所有页结果
    per_book = {}
    t0 = time.time()
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as ex:
        for b, p, r in ex.map(one, jobs):
            chs = (r or {}).get("chapters") or []
            if chs:
                per_book.setdefault(b["bookId"], []).append((p, chs))
            print(f"  {b['bookId']:26s} p{p} → {len(chs)} 章", flush=True)

    # 合并同一本书的多页目录
    result = {}
    for bid, lst in per_book.items():
        b = next(x for x in math_books if x["bookId"] == bid)
        chapters = []
        index = {}
        for p, chs in sorted(lst):
            for c in chs:
                no = (c.get("no") or "").strip()
                key = no or (c.get("name") or "")
                if key in index:
                    # 同一章在下一页续着 → 把节并进去
                    old = chapters[index[key]]
                    have = {s.get("no") for s in old.get("sections", [])}
                    for sec in c.get("sections") or []:
                        if sec.get("no") in have:
                            continue
                        old.setdefault("sections", []).append(sec)
                    continue
                index[key] = len(chapters)
                chapters.append({"no": no, "name": (c.get("name") or "").strip(),
                                 "startPage": c.get("startPage"),
                                 "sections": c.get("sections") or []})
        nsec = sum(len(c.get("sections") or []) for c in chapters)
        result[bid] = {
            "title": b["title"], "edition": b["edition"], "subject": b["subject"],
            "graphBook": b.get("graphBook"), "bookId": bid,
            "tocPages": [p for p, _ in sorted(lst)],
            "chapters": chapters,
        }
        print(f"  ✓ {bid:26s} {len(chapters)} 章 {nsec:>3d} 节  {b['title'][:36]}")

    pathlib.Path(args.out).write_text(json.dumps({
        "_source": "上海教材目录页 —— 视觉模型读版式（不是 OCR，tesseract 在彩色目录上太脏）",
        "books": result,
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n{len(result)} 本 → {args.out}  用时 {int(time.time()-t0)}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
