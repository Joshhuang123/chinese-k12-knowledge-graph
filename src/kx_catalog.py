#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
把小学科学（人教版）12 本的**核实过的事实**固化成清单文件。

为什么要有这一步
----------------
平台的 `provider_list` 只写「人民教育出版社」，
但**封面底下印着「湖北教育出版社」** —— 这是人教社授权湖北版，
教材是「人民教育出版社」编写、**湖北教育出版社**出版。

两处都对，所以两个都要记：
- `edition` = 「人教版」  ← 编写单位 / 教材版本
- `publisher` = 「湖北教育出版社」 ← 出版单位（封面印刷体）

**平台元数据不能直接当「印刷体出版社」用** ——
这是本项目「数字回一手」原则的一个新实例：
metadata 说人教版，封面印刷体是湖北教育出版社。
12 本封面都用视觉模型逐本读过（2024 课标版，12/12 一致）。

跑法：python3 src/kx_catalog.py
"""
from __future__ import annotations

import json
import pathlib
import re

BASE = pathlib.Path(__file__).resolve().parent.parent
WORK = BASE / "data" / "pdf-cache" / "work"
OUT = BASE / "data" / "kx-textbooks.json"

# **核实过的事实**（2026-10-23，12 本封面用视觉模型逐本读过）
EDITION = "人教版"
PUBLISHER = "湖北教育出版社"
# 2024 课标版：封面印「教育部审定义 2024」
STD = "2024"

CN_NUM = "一二三四五六"


def grade_of(title: str):
    m = re.search(r"([一二三四五六])年级\s*[·•]?\s*(上|下)册", title)
    if not m:
        return None
    g = CN_NUM.index(m.group(1)) + 1
    return f"{g}{'a' if m.group(2) == '上' else 'b'}"


def main():
    src = WORK / "kx-rjb-details.json"
    if not src.exists():
        raise SystemExit(f"缺 {src}，先跑 src/kx_fetch.py --list --force")
    rows = json.load(open(src, encoding="utf-8"))
    rjb = [r for r in rows if r["publisher"] == "人民教育出版社"]

    out = []
    for r in rjb:
        g = grade_of(r["title"])
        if not g:
            continue
        out.append({
            "book": g,
            "subject": "science",
            "bookZh": f"{CN_NUM[int(g[0]) - 1]}年级{'上册' if g[1] == 'a' else '下册'}",
            "title": r["title"],
            "edition": EDITION,
            "publisher": PUBLISHER,
            "std": STD,
            "contentId": r["id"],
            "pages": r["pages"],
            "imgBase": r["base"],
            "system": "六年制",
        })
    out.sort(key=lambda x: x["book"])
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    total = sum(x["pages"] for x in out)
    print(f"小学科学（{EDITION}·{PUBLISHER}·{STD}课标版）：{len(out)} 本 / {total} 页")
    for x in out:
        print(f"  {x['book']}  {x['bookZh']:6s}  {x['pages']:4d} 页")
    print(f"清单 → {OUT}")


if __name__ == "__main__":
    main()
