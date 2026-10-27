#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
漏匹配的 1,123 个概念，具体卡在哪一条判据上？

`src/vision_to_concepts_sh.py` 的匹配判据（对每本书 × 每个概念）：
  ① 目录    概念名出现在目录条目里
  ② 目录近似 difflib ≥ 0.80 与某目录条目近似
  ③ 集中    命中页数 ≥2 且 份额 ≥0.34 且「它在这本书里命中最多」
  ④ 同册    人教图的册次 == 这本书的册次 且 命中 ≥1 页

本脚本对每个漏匹配的概念算出这四条各自的结果，
看是哪一条把它挡掉的 —— 定位到具体判据才能改。

顺带对比两套教材的规模（节数），
验证「沪教版教得少」这个假设到底成不成立。

跑:  python3 src/probe_match_criteria.py
"""
import collections
import difflib
import json
import pathlib
import re
import sys

BASE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE / "src"))

from shanghai_taught import get_corpus, strip_paren      # noqa: E402
from vision_to_concepts_sh import topical_blob            # noqa: E402

MIN_HITS = 2
MIN_SHARE = 0.34
MIN_TOC_RATIO = 0.80

SUBJECT_CANDIDATES = {
    "数学": ["math"], "物理": ["physics"], "化学": ["chemistry"],
    "生物": ["biology"], "科学": ["physics", "chemistry", "biology"],
}


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


def toc_of_book(toc_books, bid):
    b = toc_books.get(bid) or {}
    entries = []
    for ch in b.get("chapters") or []:
        cno, cn = ch.get("no") or "", ch.get("name") or ""
        secs = ch.get("sections") or []
        for s in secs:
            entries.append((cno, cn, s.get("no") or "", s.get("name") or "",
                            s.get("startPage"), ch.get("startPage")))
        if not secs:
            entries.append((cno, cn, "", "", ch.get("startPage"), ch.get("startPage")))
    return entries


def main() -> int:
    corpus = get_corpus()
    toc_books = json.loads((BASE / "data" / "shanghai-toc.json").read_text(encoding="utf-8"))["books"]

    # ── 教材规模对比 ──
    print("=== 教材规模 ===")
    sh_secs = 0
    for bid, b in toc_books.items():
        sh_secs += len(toc_of_book(toc_books, bid))
    g = json.loads((BASE / "data" / "normalized" / "graph.json").read_text(encoding="utf-8"))
    rjb_secs = 0
    rjb_books = set()
    for n in g["nodes"]:
        for bid, b in (n.get("books") or {}).items():
            rjb_books.add(bid)
            rjb_secs += len(b.get("sections") or [])
    # 人教教材的节数（去重）
    seen = set()
    for n in g["nodes"]:
        for bid, b in (n.get("books") or {}).items():
            for s in (b.get("sections") or []):
                seen.add((bid, s.get("section"), s.get("sectionName")))
    print(f"  沪教教材：{len(toc_books)} 本 · 目录条目 {sh_secs} 条")
    print(f"  人教教材：{len(rjb_books)} 本 · 教材节 {len(seen)} 条")
    print(f"  上游图谱拆出的概念：{len([n for n in g['nodes'] if n.get('label') in ('Concept','Skill','Experiment')])} 个")

    # ── 页面命中统计 ──
    by_book = collections.defaultdict(list)
    for r in read_jsonl(BASE / "data" / "vision-pages-sh.jsonl"):
        b, d = r.get("book"), r.get("data")
        if not isinstance(b, str) or not isinstance(d, dict):
            continue
        by_book[b].append(topical_blob(d))
    tops_by_book = {b: tops for b, tops in by_book.items()}

    up = [n for n in g["nodes"] if n.get("label") in ("Concept", "Skill", "Experiment")]
    sv_ids = {r["id"] for r in read_jsonl(BASE / "data" / "concept-vision-sh.jsonl")}

    # 只算漏匹配的概念
    missed = [n for n in up
              if n["id"] not in sv_ids and corpus.teaches(n.get("subject") or "math", n.get("name") or "")]
    print(f"\n=== 漏匹配 {len(missed)} 个，逐条判据 ===")

    hits = collections.defaultdict(collections.Counter)
    for bid, tops in tops_by_book.items():
        subj = by_book and None
        blob_pages = [i for i, t in enumerate(tops) if t]
        for n in missed:
            nm = n.get("name") or ""
            core = strip_paren(nm) or nm
            c = 0
            for i in blob_pages:
                t = tops[i]
                if nm in t or (core and core in t):
                    c += 1
            if c:
                hits[bid][n["id"]] = c
    total_hits = collections.Counter()
    best_book = {}
    for bid, cnt in hits.items():
        for cid, c in cnt.items():
            total_hits[cid] += c
            if c > hits.get(best_book.get(cid, ""), {}).get(cid, -1):
                best_book[cid] = bid

    blocker = collections.Counter()
    detail = collections.defaultdict(list)
    for n in missed:
        nm = n.get("name") or ""
        core = strip_paren(nm) or nm
        cid = n["id"]
        reasons = []
        toc_hit = False
        near = False
        same = False
        conc = False
        for bid, tops in tops_by_book.items():
            entries = toc_of_book(toc_books, bid)
            toc_names = [x for (_c, cn, _s, sn, _p, _cp) in entries for x in (cn, sn) if x]
            if not toc_names:
                b = toc_books.get(bid) or {}
                toc_names = [c.get("name") for c in (b.get("chapters") or []) if c.get("name")]
            for (_c, cn, _s, sn, _p, _cp) in entries:
                for label in (cn, sn):
                    if not label:
                        continue
                    if (nm and nm in label) or (core and core in label):
                        toc_hit = True
                        break
                if toc_hit:
                    break
            if not toc_hit:
                for label in toc_names:
                    if difflib.SequenceMatcher(None, core, label).ratio() >= MIN_TOC_RATIO:
                        near = True
                        break
            gvol = (toc_books.get(bid) or {}).get("graphBook", "")
            h = hits[bid].get(cid, 0)
            share = h / total_hits[cid] if total_hits.get(cid) else 0.0
            bb = best_book.get(cid)
            if h >= MIN_HITS and share >= MIN_SHARE and (bb is None or bb == bid):
                conc = True
            if n.get("book") == gvol and h >= 1:
                same = True
        if toc_hit:
            blocker["目录（其实过了？）"] += 1
        elif near:
            blocker["目录近似"] += 1
        elif conc:
            blocker["集中"] += 1
        elif same:
            blocker["同册"] += 1
        else:
            # 一个都没过 → 看差在哪
            h = hits[best_book.get(cid, "")].get(cid, 0)
            share = h / total_hits[cid] if total_hits.get(cid) else 0.0
            if h == 0:
                why = "blob 里一个页都没命中"
            elif h < MIN_HITS:
                why = f"只命中 {h} 页（要 ≥{MIN_HITS}）"
            elif share < MIN_SHARE:
                why = f"命中 {h} 页但份额只有 {share:.2f}（要 ≥{MIN_SHARE}）"
            else:
                why = f"册次不匹配（人教 {n.get('book')} vs 沪教 {gvol}）"
            blocker["全不通过：" + why.split("（")[0].split("但")[0][:12]] += 1
            detail[why.split("（")[0].split("但")[0][:12]].append((n.get("name"), n.get("book"), h, round(share, 2)))

    for k, v in blocker.most_common():
        print(f"  {k}: {v}")

    print("\n=== 全不通过的典型原因（细节）===")
    for why, lst in sorted(detail.items(), key=lambda kv: -len(kv[1])):
        print(f"  {why} —— {len(lst)} 个")
        for nm, bk, h, sh in lst[:5]:
            print(f"      {nm[:30]:32s} 人教册 {bk:8s} 命中 {h:3d} 页 份额 {sh}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
