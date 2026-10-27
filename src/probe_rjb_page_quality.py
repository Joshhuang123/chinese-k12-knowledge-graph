#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""验人教版学习页挑的「教材原页」质量。"""
import collections
import json
import pathlib
import re

import fitz

BASE = pathlib.Path(__file__).resolve().parent.parent
SUBJ_ABBR = {"biology": "bio", "chemistry": "chem", "physics": "phys", "math": "math"}


def load_js(p):
    t = pathlib.Path(p).read_text(encoding="utf-8")
    return json.loads(t[t.index("=") + 1:].rstrip().rstrip(";"))


D = load_js(BASE / "data/learn-rjb.js")
ns = [n for n in D["nodes"] if n.get("loc", {}).get("scan")]

books = {}
for f in pathlib.Path(BASE / "data/pdf-cache").glob("rjb-*.pdf"):
    bid = f.stem[4:]
    d = fitz.open(f)
    books[bid] = {i + 1: d[i].get_text() for i in range(d.page_count)}
    d.close()


def pdf_key(bk):
    if not bk:
        return ""
    head, rest = bk.split("-", 1)
    return f"{SUBJ_ABBR.get(head, head)}-{rest}"


stat = collections.Counter()
for n in ns:
    bk = n["loc"].get("pdfBook")
    p = n["loc"]["scan"][0]
    t = (books.get(pdf_key(bk)) or {}).get(p, "")
    if not t.strip():
        stat["空页(图片页，无文本层)"] += 1
        continue
    if re.search(r"目\s*录|\bContents\b", t):
        stat["目录页 ✗"] += 1
        continue
    stat["正文 ✓"] += 1

print("人教版学习页的教材原页质量：")
print(" ", dict(stat))
tot = len(ns)
ok = stat["正文 ✓"]
print(f"  确认是正文页：{ok}/{tot} = {ok/tot*100:.0f}%")

pages = {(n["loc"].get("pdfBook"), n["loc"]["scan"][0]) for n in ns}
print(f"  需要渲染的不同页：{len(pages)}")
for kb in (40, 58, 82):
    print(f"    {kb}KB/页 → {len(pages)*kb//1024} MB")

print("\n抽查：")
for nm in ("光合作用", "一元二次方程", "浮力", "细胞", "压强", "动能", "化学方程式"):
    m = [n for n in ns if n["n"] == nm]
    if not m:
        continue
    n = m[0]
    bk, p = n["loc"].get("pdfBook"), n["loc"]["scan"][0]
    t = (books.get(pdf_key(bk)) or {}).get(p, "")
    mark = "✓" if t.strip() and not re.search(r"目\s*录", t) else "✗"
    print(f"  {mark} {nm:12s} {pdf_key(bk):12s} 第{p:3d}页 | {t[:46].replace(chr(10), ' ')}")
