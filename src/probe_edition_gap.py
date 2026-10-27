#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
查清一件事：**沪教版知识点为什么比人教版少？**

用户的直觉是对的 —— 两套教材都按同一套课程标准，
**知识点应该基本一样，最多顺序和册次划分不同**。

所以要分清两种可能：
  A. 沪教版真的教得少        → 数据事实，无法反驳
  B. 上游图谱/匹配管道有缺口 → **工程问题，能修**

本脚本把上游 8,590 个人教版概念放进四个象限：

  已匹配进上海站 且 沪教教材有   ← 正常
  已匹配进上海站 但 沪教教材没有  ← 可能是误匹配
  没匹配       但 沪教教材有    ← **匹配管道漏掉的**
  没匹配       且 沪教教材也没有  ← 沪教版确实不教

并逐层对比**匹配管道的输入层**：
  · 视觉层 topical blob（`vision-pages-sh.jsonl` 的图注/表题/题干）
  · OCR 原文层（`lessons-sh.jsonl`）
两层的覆盖差异就是缺口的所在。

跑:  python3 src/probe_edition_gap.py
"""
import collections
import json
import pathlib
import sys

BASE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE / "src"))

from shanghai_taught import get_corpus                    # noqa: E402
from vision_to_concepts_sh import topical_blob            # noqa: E402


def read_jsonl(path):
    """逐行读，容错（非 dict / 坏行跳过）。"""
    out = []
    p = pathlib.Path(path)
    if not p.exists():
        return out
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line[0] != "{":
            continue
        try:
            r = json.loads(line)
        except Exception:
            continue
        if isinstance(r, dict):
            out.append(r)
    return out


def main() -> int:
    corpus = get_corpus()

    # ── 上游人教版概念 ──
    g = json.loads((BASE / "data" / "normalized" / "graph.json").read_text(encoding="utf-8"))
    up = [n for n in g["nodes"] if n.get("label") in ("Concept", "Skill", "Experiment")]

    # ── 上海站已匹配的概念 id ──
    sv_ids = {r["id"] for r in read_jsonl(BASE / "data" / "concept-vision-sh.jsonl")}

    # ── 四象限 ──
    quad = collections.Counter()
    per = collections.defaultdict(collections.Counter)
    missed = []
    for n in up:
        s = n.get("subject") or "math"
        matched = n["id"] in sv_ids
        taught = corpus.teaches(s, n.get("name") or "")
        quad[(matched, taught)] += 1
        per[s][(matched, taught)] += 1
        if taught and not matched:
            missed.append((n.get("name") or "", s, n.get("grade") or 0))

    tot = len(up)
    print(f"上游人教版可画概念 {tot} 个\n")
    print("四象限：")
    print(f"  已匹配 且 沪教教材有    {quad[(True, True)]:5d}  ← 正常进来的")
    print(f"  已匹配 但 沪教教材没有  {quad[(True, False)]:5d}  ← 疑似误匹配")
    print(f"  没匹配 但 沪教教材有    {quad[(False, True)]:5d}  ← **匹配管道漏掉的**")
    print(f"  没匹配 且 沪教教材没有  {quad[(False, False)]:5d}  ← 沪教版确实不教")

    print("\n按学科：")
    print(f"  {'学科':<10s} {'上游':>6s} {'正常':>6s} {'误匹配':>7s} {'漏匹配':>7s} {'漏匹配率':>9s}")
    for s in sorted(per):
        d = per[s]
        t = sum(d.values())
        mm = d[(False, True)]
        print(f"  {s:<10s} {t:6d} {d[(True, True)]:6d} {d[(True, False)]:7d} "
              f"{mm:7d} {mm / t * 100:8.0f}%")

    # ── 输入层覆盖对比 ──
    print("\n输入层覆盖（匹配管道用的 vs 判据用的）：")
    blob_len = collections.Counter()
    ocr_len = collections.Counter()
    pages = collections.Counter()
    blob_by_book = collections.defaultdict(str)
    ocr_by_book = collections.defaultdict(str)
    for r in read_jsonl(BASE / "data" / "vision-pages-sh.jsonl"):
        b, d = r.get("book"), r.get("data")
        if not isinstance(b, str) or not isinstance(d, dict):
            continue
        pages[b] += 1
        blob_by_book[b] += topical_blob(d)
    for r in read_jsonl(BASE / "data" / "lessons-sh.jsonl"):
        b = r.get("book")
        if isinstance(b, str):
            ocr_by_book[b] += r.get("text") or ""
    for b in pages:
        blob_len[b] = len(blob_by_book[b].strip())
        ocr_len[b] = len(ocr_by_book[b].strip())

    empty = [b for b in pages if blob_len[b] == 0]
    thin = [b for b in pages if 0 < blob_len[b] < 200]
    print(f"  沪教教材 {len(pages)} 本")
    print(f"  blob 完全为空的书：{len(empty)} 本")
    for b in sorted(empty):
        print(f"      {b}  {pages[b]} 页 · OCR 原文 {ocr_len[b]} 字")
    print(f"  blob 极薄（<200 字）的书：{len(thin)} 本 → {sorted(thin)[:8]}")

    # ── 漏匹配的概念分别落在哪些书上 ──
    print("\n漏匹配的概念，其人教版册次分布：")
    gv = collections.Counter()
    for n in up:
        s = n.get("subject") or "math"
        if n["id"] in sv_ids or not corpus.teaches(s, n.get("name") or ""):
            continue
        gv[n.get("book") or "?"] += 1
    for k, v in gv.most_common(14):
        print(f"  {k:>8s}  {v:5d}")

    print("\n=== 漏匹配样例 ===")
    for nm, s, gr in missed[:20]:
        print(f"  {nm[:34]:36s} {s:9s} g{gr}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
