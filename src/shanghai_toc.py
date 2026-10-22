#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OCR 上海教材的**目录页**，抽出章/节结构。

为什么
----
要做一个「上海孩子学什么」的独立站点，就得知道：
  - 沪教版有哪几章、每章有哪几节（**顺序链**）
  - 每节讲哪些概念（**节点集**）
  - 每节是教材自己标的难点（**思考/探究**）

人教版那套是从上游图谱的节点 id（`_chNN_sMM`）推出来的，
**沪教版没有上游图谱** —— 顺序链只能从教材自己的目录来。

目录页在哪
----------
**不是**「视觉层抽不出东西的页」—— 那个判据把白页和版权页选中了，
真正的目录页（有彩色底、只有文字）反而被排除。

改成：**每本书第 2~10 页全部 OCR**，再从解析结果里挑章最多的那几页。

目录长这样（沪教版七上）：
    第10章  整式的加减
       10.1  整式            2
       10.2  合并同类项       5
    第11章  整式的乘除
    ...
跑法：python3 src/shanghai_toc.py
"""
from __future__ import annotations

import collections
import concurrent.futures
import json
import pathlib
import re
import subprocess
import sys

BASE = pathlib.Path("/Users/huangjunhai/Documents/个人/项目/中文知识图谱")
IMG = BASE / "data" / "pdf-cache" / "hujiao"
OUT = BASE / "data" / "shanghai-toc.json"
TESSERACT = "/opt/homebrew/bin/tesseract"
SCAN_FROM, SCAN_TO = 2, 10

# 章：第10章 整式的加减 / 第十章 整式的加减
RE_CHAPTER = re.compile(r"第\s*([0-9一二三四五六七八九十百]+)\s*章\s*([^\s，,。；;]{1,20})")
# 节：10.1 整式   /  10.1.1 整式的概念
RE_SECTION = re.compile(r"(\d+)\.(\d+)(?:\.(\d+))?\s+([^\s，,。；;]{1,24})")
# 目录里常见的非节条目
RE_ITEM = re.compile(r"^\s*([^\s，,。；;]{2,12})\s+(\d{1,3})\s*$")
NOISE = re.compile(r"^[\d\s·.．、第章节页码版一二三四五六七八九十]+$")
# 目录行末尾的页码：「10.1  整式            2」→ 2
RE_TAILPAGE = re.compile(r"(\d{1,3})\s*$")


def ocr(img: pathlib.Path) -> str:
    r = subprocess.run([TESSERACT, str(img), "stdout", "-l", "chi_sim", "--psm", "6"],
                       capture_output=True, text=True, timeout=180)
    return r.stdout


def parse_toc(text: str):
    """从 OCR 文本里抽 (章 → 节)。返回 (chapters, 条目数)。"""
    chapters = collections.OrderedDict()
    items = 0
    for ln in text.split("\n"):
        ln = ln.strip()
        if not ln or NOISE.match(ln):
            continue
        mc = RE_CHAPTER.search(ln)
        if mc:
            num, name = mc.group(1), mc.group(2)
            chapters.setdefault(num, {"chapter": name, "sections": []})
            items += 1
            continue
        hit = False
        # 一节右边跟着**页码**（目录的最后一列）——
        # 那是顺序链的关键：有了起始页才能把「页 → 节」映射出来。
        tail = RE_TAILPAGE.search(ln)
        pg = int(tail.group(1)) if tail else None
        for ms in RE_SECTION.finditer(ln):
            a, b, c, name = ms.groups()
            key = f"{a}.{b}" + (f".{c}" if c else "")
            ch = chapters.setdefault(a, {"chapter": "", "sections": []})
            ch["sections"].append({"no": key, "name": name, "page": pg})
            items += 1
            hit = True
        if hit:
            continue
        # 「内容提要 14」「复习题 15」这类非编号条目
        mi = RE_ITEM.match(ln)
        if mi and chapters:
            name = mi.group(1)
            if name in ("内容提要", "复习题", "本章小结", "综合与实践", "小结",
                        "本章小结与测试", "阅读材料", "数学活动"):
                last = list(chapters.values())[-1]
                last["sections"].append({"no": "", "name": name, "kind": "item"})
                items += 1
    return chapters, items


def main() -> int:
    books = json.load(open(BASE / "data" / "shanghai-textbooks.json",
                           encoding="utf-8"))["books"]
    # **subject 存的是中文**（「数学」），不是英文 math
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
    print(f"扫描 {len(jobs)} 页（{len(by_slug)} 本 × p{SCAN_FROM}-{SCAN_TO}）", flush=True)

    def one(j):
        b, p, f = j
        try:
            return (b, p, ocr(f))
        except Exception:
            return (b, p, "")

    per_book = collections.defaultdict(list)
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as ex:
        for b, p, t in ex.map(one, jobs):
            if t and t.strip():
                per_book[b["bookId"]].append((p, t))

    result = {}
    for bid, lst in per_book.items():
        b = next(x for x in math_books if x["bookId"] == bid)
        # **目录跨好几页**（沪教版七上：p5 是第 10~12 章，p6 是第 13~14 章），
        # 所以要把所有页解析结果**合并**，不能只取「章最多」的那一页。
        chapters = collections.OrderedDict()
        toc_pages = []
        for p, t in sorted(lst):
            ch, items = parse_toc(t)
            if not ch:
                continue
            toc_pages.append(p)
            for num, c in ch.items():
                if num not in chapters:
                    chapters[num] = {"chapter": c["chapter"], "sections": []}
                elif not chapters[num]["chapter"] and c["chapter"]:
                    chapters[num]["chapter"] = c["chapter"]
                have = {s["no"] for s in chapters[num]["sections"] if s["no"]}
                for sec in c["sections"]:
                    if sec["no"] and sec["no"] in have:
                        continue
                    chapters[num]["sections"].append(sec)
        nsec = sum(len(c["sections"]) for c in chapters.values())
        if not chapters:
            print(f"  ! {bid:26s} 没解析出目录")
            continue
        p = toc_pages[0] if toc_pages else 0
        result[bid] = {
            "title": b["title"], "edition": b["edition"], "subject": b["subject"],
            "graphBook": b.get("graphBook"), "bookId": bid, "tocPage": p,
            "chapters": chapters,
        }
        print(f"  {bid:26s} {len(chapters)} 章 {nsec:>3d} 节  (目录在 p{p})  {b['title'][:36]}")

    OUT.write_text(json.dumps({
        "_source": "上海教材目录页 OCR（tesseract chi_sim，p%d-%d 扫描）" % (SCAN_FROM, SCAN_TO),
        "books": result,
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n{len(result)} 本有目录 → {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
