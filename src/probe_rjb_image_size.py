#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""量「从本地 PDF 渲染人教版页图」的最小体积 —— 每个概念只出它自己的主页。"""
import collections
import json
import pathlib

BASE = pathlib.Path(__file__).resolve().parent.parent


def load_js(path):
    txt = pathlib.Path(path).read_text(encoding="utf-8")
    return json.loads(txt[txt.index("=") + 1:].rstrip().rstrip(";"))


for tag, label in (("rjb", "人教版"), ("kx", "小学科学")):
    D = load_js(BASE / f"data/learn-{tag}.js")
    nodes = D["nodes"]
    with_scan = [n for n in nodes if n.get("loc") and n["loc"].get("scan")]
    # 每个概念只取第一页
    pages = set()
    for n in with_scan:
        pages.add((n["loc"].get("bk") or n.get("book"), n["loc"]["scan"][0]))
    # 有公式或图的概念（视觉价值高的）
    rich = [n for n in with_scan if n.get("f") or n.get("fg")]
    rich_pages = {(n["loc"].get("bk") or n.get("book"), n["loc"]["scan"][0]) for n in rich}
    print(f"[{tag}] {label}")
    print(f"  节点 {len(nodes)} | 有页码 {len(with_scan)} | 其中有公式/图 {len(rich)}")
    print(f"  不同页数：全部 {len(pages)} · 只算有公式/图的 {len(rich_pages)}")
    for kb in (40, 58, 82):
        print(f"    {kb}KB/页 → 全部 {len(pages)*kb//1024} MB · 只算有图 {len(rich_pages)*kb//1024} MB")
    print()
