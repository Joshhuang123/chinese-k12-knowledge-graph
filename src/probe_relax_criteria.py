#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
只针对**漏匹配的 1,123 个概念**，测各种判据组合能救回多少。

比 `probe_match_layers.py` 快得多：只扫这 1,123 个，
而不是全部 8,590（后者是 8,590×67×150 ≈ 8,600 万次字符串搜索）。

要回答的问题：**沪教版知识点到底有没有少？**
如果放宽判据就能把大部分救回来 → 是管道问题，能修。
如果救不回来 → 是「上游只按人教版拆过概念」的结构性问题。

跑:  python3 src/probe_relax_criteria.py
"""
import collections
import json
import pathlib
import sys

BASE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE / "src"))

from shanghai_taught import get_corpus, strip_paren      # noqa: E402
from vision_to_concepts_sh import topical_blob            # noqa: E402

SUBJ_ZH = {"math": "数学", "physics": "物理", "chemistry": "化学",
            "biology": "生物", "science": "科学"}


def read_jsonl(path):
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
    g = json.loads((BASE / "data" / "normalized" / "graph.json").read_text(encoding="utf-8"))
    up = [n for n in g["nodes"] if n.get("label") in ("Concept", "Skill", "Experiment")]
    sv_ids = {r["id"] for r in read_jsonl(BASE / "data" / "concept-vision-sh.jsonl")}

    # 只留「沪教教材确实教、但没进站」的
    missed = [n for n in up
              if n["id"] not in sv_ids
              and corpus.teaches(n.get("subject") or "math", n.get("name") or "")]
    print(f"漏匹配的概念：{len(missed)} 个\n")

    # 每本书：视觉 blob（每页一条）+ OCR 正文（整本一条）
    blob_pages = collections.defaultdict(list)
    for r in read_jsonl(BASE / "data" / "vision-pages-sh.jsonl"):
        b, d = r.get("book"), r.get("data")
        if isinstance(b, str) and isinstance(d, dict):
            blob_pages[b].append(topical_blob(d))
    ocr = collections.defaultdict(str)
    for r in read_jsonl(BASE / "data" / "lessons-sh.jsonl"):
        b = r.get("book")
        if isinstance(b, str):
            ocr[b] += r.get("text") or ""

    # 按学科分桶，只看同学科的书
    by_subj = collections.defaultdict(list)
    for b in blob_pages:
        by_subj[SUBJ_ZH.get("math", "")].append(b)   # 占位，下面用真值覆盖
    book_subject = {}
    toc = json.loads((BASE / "data" / "shanghai-toc.json").read_text(encoding="utf-8"))["books"]
    for b in blob_pages:
        book_subject[b] = (toc.get(b) or {}).get("subject")

    # 统计每个概念在各书的命中页数（blob）与是否出现在 OCR 整本
    blob_hits = collections.defaultdict(collections.Counter)
    ocr_hit = collections.defaultdict(set)
    for b, pages in blob_pages.items():
        subj = book_subject.get(b)
        cands = [n for n in missed if SUBJ_ZH.get(n.get("subject") or "", "") == subj]
        if not cands:
            continue
        nonempty = [i for i, t in enumerate(pages) if t]
        for n in cands:
            nm = n.get("name") or ""
            core = strip_paren(nm) or nm
            c = 0
            for i in nonempty:
                t = pages[i]
                if nm in t or (core and core in t):
                    c += 1
            if c:
                blob_hits[b][n["id"]] = c
            o = ocr.get(b, "")
            if o and (nm in o or (core and core in o)):
                ocr_hit[n["id"]].add(b)

    total = collections.Counter()
    best = {}
    for b, cnt in blob_hits.items():
        for cid, c in cnt.items():
            total[cid] += c
            if c > blob_hits.get(best.get(cid, ""), {}).get(cid, -1):
                best[cid] = b

    # 判据组合
    def evaluate(min_hits, use_ocr, min_share=0.34):
        got = set()
        for n in missed:
            cid = n["id"]
            bb = best.get(cid)
            for b in blob_pages:
                if book_subject.get(b) != SUBJ_ZH.get(n.get("subject") or "", ""):
                    continue
                h = blob_hits[b].get(cid, 0)
                if use_ocr and cid in ocr_hit and b in ocr_hit[cid]:
                    h += 1                       # OCR 整本算 1 页
                if h < min_hits:
                    continue
                share = h / total[cid] if total.get(cid) else 0.0
                if use_ocr:
                    # 加了 OCR 之后分母也要算上
                    share = h / (total[cid] + len(ocr_hit.get(cid, ())))
                if share < min_share:
                    continue
                if best.get(cid) not in (None, b) and not use_ocr:
                    continue
                got.add(cid)
                break
        return got

    print("判据组合 → 能匹配上的漏概念数：")
    for mh in (1, 2):
        for uo in (False, True):
            g = evaluate(mh, uo)
            print(f"  MIN_HITS={mh}  {'用' if uo else '不用'}OCR正文层 → {len(g):5d} / {len(missed)}")

    print("\n（再加「放宽份额门槛 0.34 → 0.10」）")
    for mh in (1, 2):
        for uo in (False, True):
            g = evaluate(mh, uo, 0.10)
            print(f"  MIN_HITS={mh}  {'用' if uo else '不用'}OCR正文层 → {len(g):5d} / {len(missed)}")

    # 加上原有 2,258，上海站会变成多少
    orig = len(sv_ids)
    best_combo = max(evaluate(1, True, 0.10), evaluate(2, True, 0.10),
                     evaluate(1, True), evaluate(2, True),
                     key=len)
    print(f"\n上海站概念数：现在 {orig} → 最优放宽后 {orig + len(best_combo)}")
    print(f"主站（人教版）：{len(up)}")

    print("\n=== 放宽后仍匹配不上的（沪教版用了别的说法）===")
    byid = {n["id"]: n for n in missed}
    for cid in list(best_combo)[:0]:
        pass
    rest = [byid[c] for c in best_combo]
    for n in rest[:12]:
        print(f"  {n.get('name','')[:30]:32s} {n.get('subject'):9s} g{n.get('grade')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
