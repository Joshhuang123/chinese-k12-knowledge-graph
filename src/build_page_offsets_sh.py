#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
算**沪教版**每册的印刷页码偏移：书上印的页码 = 平台扫描页 + offset。

为什么需要它
------------
平台给的页图是**扫描序号**，书上印的是**印刷页码**。
实测沪教版七下数学：面板写「第 16 页」，图上页脚印的是 **9** ——
差 7 页。学生按 16 去翻书，翻到的是下一节。

（人教版那边已经用本地 PDF 页脚算好了，见 src/build_page_offsets.py。
 沪教没有 PDF，只有平台的 OCR 文本，所以走另一条路。）

怎么取页码
----------
沪教平台的 OCR 文本长这样（沪教版数学七下，扫描页 16）：

    …所以，不等式 5x一]亿2z十5 的解集是 z2.
    9                          ← 印刷页码，单独一行
    15.2 ”一元一次不等式          ← 书眉（章名）
    上海教育出版社                 ← OCR 认出来的水印

所以判据是：**正文末尾附近，单独成行的 1–3 位数字**。

⚠️ 不能用「末尾 45 字里找数字」这种糊法 —— 末尾经常是章节号、
公式里的数字、页眉，会认错（实测那样做只有 8–14% 一致性）。

定偏移的两道判据
----------------
光靠「众数占比 ≥ 85%」会把**少数册**误杀（沪科版部分册 OCR 覆盖很低，
只有 10–30 页有候选）。但那些册的众数其实是对的 —— 只是证据少。

所以加一道**独立的硬判据：印刷页码必须随扫描页单调递增**。
扫描页 +1 → 印刷页也应 +1。offset 猜错时，印刷页会乱跳。

- 一致性 ≥ 85% 且候选 ≥ 20 页 → 直接采用
- 一致性低但**单调性判据通过** → 也采用（证据少但结构对）
- 两者都不通过 → **不写这一册**（宁可少抽，不抽错），页面退回显示扫描页码

实测：沪教版（sh-hj）**每一册**的众数都是 -7（前言页数固定），
沪科版多数是 -5 / -7 —— 跟「封面 + 版权页 + 本册导引 + 目录」的页数对得上。

跑:  python3 src/build_page_offsets_sh.py
"""
import collections
import json
import pathlib
import re
import sys
import unicodedata

BASE = pathlib.Path(__file__).resolve().parent.parent
DATA = BASE / "data"
OUT_JSON = DATA / "page-offsets-sh.json"
OUT_JS = DATA / "page-offsets-sh.js"

MIN_CANDIDATES = 20
MIN_AGREE = 0.85
# 单调性判据：至少要有这么多对「相邻扫描页 → 印刷页也 +1」
MIN_MONO_PAIRS = 3
# 正文末尾这么多行里找页码行（页码行后面通常跟着书眉 + 水印）
TAIL_LINES = 8


def nfkc(s: str) -> str:
    return unicodedata.normalize("NFKC", s or "")


def printed_page(text: str):
    """从一页的 OCR 文本里取印刷页码，取不到返回 None。"""
    lines = [nfkc(x).strip() for x in (text or "").splitlines()]
    lines = [x for x in lines if x]
    for ln in reversed(lines[-TAIL_LINES:]):
        if re.fullmatch(r"\d{1,3}", ln):
            return int(ln)
    return None


def main() -> int:
    # book → {扫描页: [印刷页, …]}
    pairs = collections.defaultdict(lambda: collections.defaultdict(list))
    for line in (DATA / "lessons-sh.jsonl").read_text(encoding="utf-8").splitlines():
        if not line.strip() or line[0] != "{":
            continue
        try:
            d = json.loads(line)
        except Exception:
            continue
        bk = d.get("book")
        pg = d.get("page")
        if not isinstance(bk, str) or not isinstance(pg, int):
            continue
        p = printed_page(d.get("text") or "")
        if p is None:
            continue
        pairs[bk][pg].append(p)

    offsets = {}
    print(f"沪教版印刷页码偏移（{len(pairs)} 本有候选）\n")
    for bk in sorted(pairs):
        diffs = collections.Counter()
        for pg, ps in pairs[bk].items():
            for p in ps:
                diffs[p - pg] += 1
        if not diffs:
            continue
        off, c = diffs.most_common(1)[0]
        tot = sum(diffs.values())
        agree = c / tot

        # ── 单调性判据 ──
        # 扫描页 +1 → 印刷页也应 +1。offset 猜错时印刷页会乱跳。
        seq = {}
        for pg, ps in pairs[bk].items():
            cand = [p for p in ps if p - pg == off]
            if cand:
                seq[pg] = min(cand)
        mono = 0
        keys = sorted(seq)
        for a, b in zip(keys, keys[1:]):
            # ⚠️ 不能要求 b - a == 1 —— OCR 会漏掉某些页的页码，
            # 于是「相邻的两个候选页」可能隔了好几页。
            # 正确的约束是：**印刷页的增量 = 扫描页的增量**。
            if seq[b] - seq[a] == b - a:
                mono += 1

        by_agree = tot >= MIN_CANDIDATES and agree >= MIN_AGREE
        by_mono = mono >= MIN_MONO_PAIRS
        ok = by_agree or by_mono
        if ok:
            offsets[bk] = off
        why = []
        if by_agree:
            why.append("一致性")
        if by_mono:
            why.append(f"单调性 {mono} 对")
        print(f"  {'✓' if ok else '·'} {bk:26s} offset={off:+3d}  "
              f"一致 {c}/{tot}={agree:4.0%}  单调 {mono} 对"
              f"{'   ← ' + '＋'.join(why) if ok else ''}")

    OUT_JSON.write_text(json.dumps(offsets, ensure_ascii=False, indent=1), encoding="utf-8")
    OUT_JS.write_text("window.PAGE_OFFSETS_SH=" +
                      json.dumps(offsets, ensure_ascii=False, separators=(",", ":")) + ";\n",
                      encoding="utf-8")
    print(f"\n算出 {len(offsets)}/{len(pairs)} 册")
    print(f"→ {OUT_JSON.relative_to(BASE)}")
    print(f"→ {OUT_JS.relative_to(BASE)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
