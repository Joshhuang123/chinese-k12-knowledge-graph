#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
先修边方向自查 —— `src/check_edge_direction.py`

## 为什么要有这个检查

2026-10-26 用户在上海站（`shanghai.html`）发现：
**「二次函数」的后继列的是「函数」「一次函数」** ——
八上的函数是九上二次函数的**前置**，不是后继。

查出来是**上海站的 6,567 条边方向全反了**：
`shanghai-graph.json` 的边是 `[前置, 后继]`，
而 payload 约定是 `[后继, 前置]`（模板里 `pre.get(e[0]).push(e[1])`），
`build_shanghai.py` 当时**原样透传**了。

**方向反了是最难发现的 bug** —— 页面照常渲染，
每一句话都在说反，而且「看着还挺通顺」。

## 判据：前置在教材里不该比后继更晚

教材是按学习顺序排的 —— 「细胞」在第二章，「生物」在第一章，
所以「生物」不可能是「细胞」的**后继**。

于是：**前置的教材位置 ≤ 后继的教材位置**。
违反的边就是方向可疑的。

⚠️ **这不是零容忍的检查**：
- 同一册里的概念，章内顺序不完全等于学习顺序
- 跨版本对照的节点（「函数（Function）」）位置没法直接比
- 教材本身偶尔把综合概念放在前面

实测基线：
- 主站 2.3%（344 条）
- 上海站 4.0%（242 条）
- **方向全反时是 31.5%** —— 差一个数量级

所以阈值定在 **10%**：超过就是**方向反了**，不是「有几条例外」。

## 跑法

    python3 src/check_edge_direction.py
"""
from __future__ import annotations

import json
import pathlib
import re
import sys

BASE = pathlib.Path(__file__).resolve().parent.parent

# 册次的学习顺序（跨学科统一编号）
# ⚠️ 必须跟 `src/build_viz.py` 的 GRADE 口径一致 —— 顺序错了判据就废了
BOOK_ORDER = {
    "1a": 1, "1b": 2, "2a": 3, "2b": 4, "3a": 5, "3b": 6,
    "4a": 7, "4b": 8, "5a": 9, "5b": 10, "6a": 11, "6b": 12,
    "7a": 13, "7b": 14, "8a": 15, "8b": 16, "9a": 17, "9b": 18,
    "m1": 19, "m2": 20, "x1": 21, "x2": 22, "x3": 23,
    "bx1": 30, "bx2": 31, "bx3": 32, "bx4": 33,
    "xzxbx1": 40, "xzxbx2": 41, "xzxbx3": 42,
}

# 超过这个比例就是「方向反了」，不是「有几条例外」
THRESHOLD = 0.10

SITES = [
    ("主站", "index.html"),
    ("上海站", "shanghai.html"),
    ("小学站", "kx.html"),
]


def load_payload(path: pathlib.Path):
    html = path.read_text(encoding="utf-8")
    m = re.search(r'<script id="data"[^>]*>(.*?)</script>', html, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except Exception:
        return None


def build_chapter_index(g: dict) -> dict:
    """概念 → 它在教材里出现的**最早那一章**。

    ⚠️ **不能靠字符串前缀猜章序** —— `math_9a_rjb_cpt16` 和
    `math_9a_rjb_ch22` 前缀相同，靠猜会把所有概念都算成章 22，
    同册内的先后就分不出来了（实测可疑率从 3% 虚高到 15%）。

    正解：用 `appears_in` 边（概念 → 它出现的节/章），
    取**最小**的章号 —— 一个概念可能出现在多章里，最早的那章才是它的位置。

    覆盖 9,764 / 10,685 个节点（91%）。
    """
    ch = {}
    for e in g.get("edges", []):
        if e.get("type") != "appears_in":
            continue
        cid, t = e.get("from"), e.get("to") or ""
        if "_ch" not in t:
            continue
        tail = t.split("_ch", 1)[1]
        num = tail.split("_")[0]
        if num.isdigit():
            n = int(num)
            if cid not in ch or n < ch[cid]:
                ch[cid] = n
    return ch


def book_order(nodes_by_id: dict, nid: str, ch_index: dict):
    """节点的教材位置（册次序, 章序）。取不到就返回 None。"""
    n = nodes_by_id.get(nid)
    if not n:
        return None
    b = n.get("book") or ""
    base = BOOK_ORDER.get(b)
    if base is None:
        return None
    ch = ch_index.get(nid, 0)
    return (base, ch)


def main() -> int:
    # 节点元信息从 graph.json 取（上海站/小学站的 payload 里没有 book 字段）
    g = json.load(open(BASE / "data" / "normalized" / "graph.json", encoding="utf-8"))
    nodes_by_id = {n["id"]: n for n in g["nodes"]}
    ch_index = build_chapter_index(g)

    print("先修边方向自查")
    print("判据：前置的教材位置不该比后继更晚")
    print(f"阈值：可疑边超过 {THRESHOLD*100:.0f}% 就是方向反了\n")

    bad_any = False
    for label, fn in SITES:
        path = BASE / fn
        if not path.exists():
            print(f"  {label}: 缺 {fn}，跳过")
            continue
        d = load_payload(path)
        if not d or "edges" not in d:
            print(f"  {label}: payload 里没有 edges，跳过")
            continue
        idx = {n[0]: n for n in d["nodes"]}
        id2idx = {n[5]: n[0] for n in d["nodes"]}
        bad = []
        tot = 0
        for e in d["edges"]:
            t, p = e[0], e[1]
            # 模板约定：pre.get(t).push(p) → p 是 t 的前置
            nt, np_ = idx.get(t), idx.get(p)
            if not nt or not np_:
                continue
            ot = book_order(nodes_by_id, nt[5], ch_index)
            op = book_order(nodes_by_id, np_[5], ch_index)
            if not ot or not op:
                continue
            tot += 1
            if op > ot:
                bad.append((nt[1], np_[1]))
        rate = len(bad) / tot if tot else 0
        flag = "✗" if rate > THRESHOLD else "✓"
        print(f"  {flag} {label:6s} 边 {len(d['edges']):>6,} 条"
              f"（可比教材顺序 {tot:,} 条）"
              f"  可疑 {len(bad):>4,} = {rate*100:.1f}%")
        if rate > THRESHOLD:
            bad_any = True
            print(f"      ⚠️ 超过 {THRESHOLD*100:.0f}% —— 边方向很可能整个反了")
            for a, b in bad[:5]:
                print(f"      「{a}」的前置「{b}」反而在教材更后")
        elif bad:
            for a, b in bad[:3]:
                print(f"      · 「{a}」的前置「{b}」在教材更后（例外）")

    print()
    if bad_any:
        print("✗ 有站点的边方向反了")
        return 1
    print("✓ 三个站的边方向都对")
    return 0


if __name__ == "__main__":
    sys.exit(main())
