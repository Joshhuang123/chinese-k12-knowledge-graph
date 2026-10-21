#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
把《2024年秋季上海市编写教学用书目录》抽成结构化数据。

这份目录是**上海市教育委员会官方发布**的（沪教委基〔2024〕24号 附件2），
逐册列出上海本地编写的教学用书：准用号 / 学科 / 书名 / 版别 / 使用时间 / 备注。

它解决的是这个项目一直缺的一块：
  - 我们知道「上海的数学是沪教版（上海教育出版社）」，但**没有官方的逐册清单**
  - 「沪科版」和「沪教版」经常被混为一谈 ——
    官方版别码把它们分得很清：**沪教育 = 上海教育出版社**，
    **沪科技 = 上海科学技术出版社**，还有沪科教/沪远东/沪外教/沪音乐/沪书画/牛津…
  - 「五四学制」在书名里明写

解析用 PyMuPDF 的表格识别（`find_tables`）——
这份 PDF 是**带框线的真表格**，按框线切比按坐标猜可靠得多。

跑法：python3 src/shanghai_catalog.py
"""
from __future__ import annotations

import collections
import json
import pathlib
import re
import sys

import fitz

BASE = pathlib.Path(__file__).resolve().parent.parent
PDF = BASE / "data" / "gov" / "sh-2024-autumn-textbook-catalog.pdf"
OUT = BASE / "data" / "shanghai-textbook-catalog.json"

# 官方「版别」码 → 出版社全称
EDITIONS = {
    "人教社": "人民教育出版社",
    "沪教育": "上海教育出版社",
    "沪科技": "上海科学技术出版社",
    "沪科教": "上海科技教育出版社",
    "沪远东": "上海远东出版社",
    "沪外教": "上海外语教育出版社",
    "沪外音": "上海音乐出版社",
    "沪音乐": "上海音乐出版社",
    "沪书画": "上海书画出版社",
    "华师大社": "华东师范大学出版社",
    "沪少儿": "上海少年儿童出版社",
    "牛津": "牛津大学出版社（上海牛津外语教育）",
    "上教社": "上海教育出版社",
    "上科社": "上海科学技术出版社",
    "上外教": "上海外语教育出版社",
    "沪教社": "上海教育出版社",
}

RE_NUM = re.compile(r"^(?:Ⅱ|SD)[－\-][A-Z]{1,2}[－\-]\d{7}$")
RE_TERM = re.compile(
    r"(小学[一二三四五六七八九十]年级第[一二]学期|"
    r"[一二三四五六七八九十]年级第[一二]学期|"
    r"高[一二三]第[一二]学期|"
    r"高[一二三]年级第[一二]学期|"
    r"[一二三四五六七八九十]年级)")

# 学科列在 PDF 里是竖排的（一个字一行），拼起来才有意义
SUBJECT_FIX = {
    "数学": "数学", "科学": "科学", "物理": "物理", "化学": "化学",
    "生物学": "生物", "语文": "语文", "英语": "英语", "历史": "历史",
    "地理": "地理", "道德与法治": "道德与法治", "美术": "美术",
    "音乐": "音乐", "信息科技": "信息科技", "劳动技术": "劳动技术",
    "体育与健身": "体育与健身", "艺术": "艺术", "书法": "书法",
}


def clean(s: str) -> str:
    return re.sub(r"\s+", "", s or "")


def main() -> int:
    if not PDF.exists():
        print(f"没有 {PDF}")
        return 1
    doc = fitz.open(PDF)

    out = []
    for pno in range(doc.page_count):
        page = doc[pno]
        for tab in page.find_tables().tables:
            for row in tab.extract():
                if len(row) < 5:
                    continue
                num = clean(row[0])
                if not RE_NUM.match(num):
                    continue
                subject = clean(row[1])
                title = clean(row[2])
                ed = clean(row[3])
                term = clean(row[4])
                note = clean(row[5]) if len(row) > 5 else ""
                out.append({
                    "num": num,
                    "subject": SUBJECT_FIX.get(subject, subject),
                    "title": title,
                    "editionCode": ed,
                    "publisher": EDITIONS.get(ed, ""),
                    "term": term,
                    "pending": "待审" in note,
                    "note": note,
                })

    OUT.write_text(json.dumps({
        "_source": "上海市教育委员会《2024年秋季上海市编写教学用书目录》"
                   "（沪教委基〔2024〕24号 附件2），2024-08-13 发布",
        "_url": "https://edu.sh.gov.cn/xxgk2_zdgz_jcjy_04/20240801/"
                "bb522c1b161b441281dba8bfe9296b36.html",
        "_pdf": "https://edu.sh.gov.cn/cmsres/97/9705ef64871d45cf984f73d79cae5fd9/"
                "d5352cc408d180944636941826a5cdd3.pdf",
        "_editionCodes": EDITIONS,
        "entries": out,
    }, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"抽出 {len(out)} 条 → {OUT}")
    print("版别分布:", dict(collections.Counter(r["editionCode"] for r in out).most_common()))
    print("学科分布:", dict(collections.Counter(r["subject"] for r in out).most_common(8)))

    print("\n=== 沪教育（沪教版）数学 ===")
    for r in out:
        if r["editionCode"] == "沪教育" and "数学" in r["title"]:
            print(f"  {r['num']:20s} {r['title'][:46]:48s} {r['term']}"
                  + ("  [待审]" if r["pending"] else ""))
    print("\n=== 沪少儿（小学二年级数学）===")
    for r in out:
        if r["editionCode"] == "沪少儿":
            print(f"  {r['num']:20s} {r['title'][:46]:48s} {r['term']}")
    print("\n=== 沪科技（沪科版）===")
    for r in out:
        if r["editionCode"] == "沪科技":
            print(f"  {r['num']:20s} {r['title'][:50]:52s} {r['term']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
