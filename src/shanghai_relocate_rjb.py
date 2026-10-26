#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
给**保留下来的���教版前置节点**标注它在沪教教材里的真实位置。

问题
----
`src/shanghai_graph.py` 按「沪教教材教不教」过滤后，975 个人教版节点剩 314 个。
但这 314 个的标签还写着「人教版·必修二」——
**内容是对的（沪教高中确实教 DNA 复制、B细胞），标签是错的**
（上海的孩子学的是沪科版，不是人教版）。

而且它们的 id 还是人教版的（`biology_bx2_rjb_cpt25`），
跟沪教节点集里的 id 不是一套 —— 所以它们无法跟沪教节点合并。

本脚本做两件事
--------------
① 用**跟沪教节点集同一套判据**（「目录」/「集中」档，见
   `src/vision_to_concepts_sh.py`）给这 314 个节点算沪教教材位置，
   于是标签能改成「沪科版·必修二 第 X 章 …（第 N 页）」。

② 顺带**收紧保留判据**：只有「目录」或「集中」档的才算沪教真的教，
   「同册」档（只是同一本书里出现过这个词）不算。

   —— 「同册」档太松：「DNA复制」在沪科版必修二确实出现，
   但沪教教材的知识点节点集里并没有它单列。
   保留它 → 用户看到「DNA复制 · 人教版·必修二」，仍然困惑。

跑:  python3 src/shanghai_relocate_rjb.py
输出: data/shanghai-rjb-positions.json
"""
import collections
import difflib
import json
import pathlib
import re
import sys

BASE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE / "src"))

VPAGES_SH = BASE / "data" / "vision-pages-sh.jsonl"
TOC = BASE / "data" / "shanghai-toc.json"
GRAPH = BASE / "data" / "normalized" / "graph.json"
SG = BASE / "data" / "shanghai-graph.json"
OUT = BASE / "data" / "shanghai-rjb-positions.json"

# 跟 vision_to_concepts_sh.py 保持一致
MIN_HITS = 2
MIN_SHARE = 0.34
MIN_TOC_RATIO = 0.80

SUBJECT_CANDIDATES = {
    "数学": ["math"], "物理": ["physics"], "化学": ["chemistry"],
    "生物": ["biology"], "科学": ["physics", "chemistry", "biology"],
}


def strip_paren(nm: str) -> str:
    return re.sub(r"[（(].*?[）)]", "", nm).strip()


def de_num(nm: str) -> str:
    """去掉末尾数字：「不等式的性质1」→「不等式的性质」"""
    return re.sub(r"[0-9０-９]+$", "", nm).strip()


def topical_blob(d: dict) -> str:
    """把一页里所有会被视觉模型认出来的文本拼起来。"""
    out = []
    for it in (d.get("items") or []):
        t = it.get("type")
        if t in ("text", "title", "caption"):
            out.append(it.get("text") or it.get("content") or "")
        elif t == "formula":
            out.append(it.get("context") or "")
    for k in ("formulas", "figures", "exercises"):
        for x in (d.get(k) or []):
            if isinstance(x, str):
                out.append(x)
            elif isinstance(x, dict):
                out.append(x.get("context") or x.get("caption") or "")
    return "\n".join(out)


def toc_of_book(toc_books: dict, bid: str):
    b = toc_books.get(bid) or {}
    entries = []
    for ch in b.get("chapters") or []:
        cno = ch.get("no") or ""
        cn = ch.get("name") or ""
        for s in ch.get("sections") or []:
            entries.append((cno, cn, s.get("no") or "", s.get("name") or "",
                            s.get("startPage"), ch.get("startPage")))
        if not ch.get("sections"):
            entries.append((cno, cn, "", "", ch.get("startPage"), ch.get("startPage")))
    return entries


def main() -> int:
    if not VPAGES_SH.exists():
        print(f"没有 {VPAGES_SH}")
        return 1

    sg = json.loads(SG.read_text(encoding="utf-8"))
    rjb = [n for n in sg["nodes"]
           if n["kind"] == "pre" and n.get("editions") == ["人教版"]]
    print(f"待定位的人教版前置节点：{len(rjb)}")

    # ── 页面 ──
    by_book = collections.defaultdict(list)
    for line in VPAGES_SH.open(encoding="utf-8"):
        if not line.strip():
            continue
        try:
            r = json.loads(line)
        except Exception:
            continue
        if not r.get("ok") or not r.get("data"):
            continue
        by_book[r["book"]].append(r)
    print(f"上海教材页 {sum(len(v) for v in by_book.values())} 页 · {len(by_book)} 本")

    toc_books = json.loads(TOC.read_text(encoding="utf-8"))["books"]

    # ── 每本书 × 每个待定位节点：命中页数 ──
    tops_by_book = {}
    hits = collections.defaultdict(lambda: collections.Counter())
    for bid, pgs in by_book.items():
        tops = [topical_blob(r["data"]) for r in pgs]
        tops_by_book[bid] = tops
        subj = pgs[0].get("subject", "math")
        cands = [n for n in rjb if n.get("subject") in SUBJECT_CANDIDATES.get(subj, [subj])]
        blob_pages = [i for i, t in enumerate(tops) if t]
        for n in cands:
            nm = n["name"]
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
        for cid, n in cnt.items():
            total_hits[cid] += n
            if n > hits.get(best_book.get(cid, ""), {}).get(cid, -1):
                best_book[cid] = bid
    print(f"命中统计完成（{sum(total_hits.values())} 对）")

    # ── 逐本匹配 ──
    result = {}
    stats = collections.Counter()
    for bid, pgs in sorted(by_book.items()):
        p0 = pgs[0]
        subj = p0.get("subject", "math")
        gvol = p0.get("graphBook", "")
        edition = p0.get("edition", "")
        tops = tops_by_book[bid]
        entries = toc_of_book(toc_books, bid)
        toc_names = [x for (_c, cn, _s, sn, _p, _cp) in entries for x in (cn, sn) if x]
        if not toc_names:
            b = toc_books.get(bid) or {}
            toc_names = [c.get("name") for c in (b.get("chapters") or [])
                         if c.get("name")]
        for n in rjb:
            cid = n["id"]
            if n.get("subject") not in SUBJECT_CANDIDATES.get(subj, [subj]):
                continue
            if hits[bid].get(cid, 0) == 0:
                continue
            nm = n["name"]
            core = strip_paren(nm) or nm
            dv = de_num(core)          # 去末尾数字的变体（用于目录匹配）
            toc_hit = None
            # **概念名至少 3 字才当目录命中** ——
            # 「体积」会子串命中「如何测定气体摩尔体积」，
            # 「单位1」会命中「常用的单位及其符号」——
            # 概念名太短时子串匹配没有意义（��字命中一长串）。
            MIN_TOC_NAME = 3
            if len(core) >= MIN_TOC_NAME:
                for (cno, cn, sno, sn, sp, cp) in entries:
                    for label in (cn, sn):
                        if not label:
                            continue
                        if ((nm and nm in label) or (core and core in label)
                                or (dv and dv in label)):
                            toc_hit = {"chapter": cno, "chapterName": cn,
                                       "section": sno, "sectionName": sn,
                                       "page": sp, "chapterPage": cp}
                            break
                    if toc_hit:
                        break
            near = False
            if not toc_hit:
                for label in toc_names:
                    if difflib.SequenceMatcher(None, core, label).ratio() >= MIN_TOC_RATIO:
                        near = True
                        break
            h = hits[bid][cid]
            share = h / total_hits[cid] if total_hits.get(cid) else 0.0
            bb = best_book.get(cid)
            conc = (h >= MIN_HITS and share >= MIN_SHARE and (bb is None or bb == bid))
            same = n.get("volName") == gvol and h >= 1
            ev = []
            if toc_hit:
                ev.append("目录")
            elif near:
                ev.append("目录近似")
            if conc:
                ev.append("集中")
            if same:
                ev.append("同册")
            if not ev:
                continue
            # **只保留「目录」或「集中」** —— 这两档才代表
            # 「教材真的把它当一个知识点教」。「同册」只是同本书里出现过这个词。
            if not (toc_hit or conc):
                stats["仅同册（剔除）"] += 1
                continue
            stats["保留"] += 1
            cur = result.get(cid)
            # 取证据最强的一档
            rank = {"目录": 3, "目录近似": 2, "集中": 2}
            score = max(rank.get(x, 1) for x in ev)
            if cur is None or score > cur["_score"]:
                result[cid] = {
                    "id": cid, "name": nm, "subject": n.get("subject"),
                    "edition": edition, "volName": gvol,
                    "book": f"{edition}·{gvol}",
                    "evidence": ev, "score": score,
                    "tocHit": toc_hit, "hits": h, "share": round(share, 3),
                    "_score": score,
                }

    # ── 输出 ──
    for v in result.values():
        v.pop("_score", None)
        v["evidence"] = [e for e in v["evidence"] if e != "同册"]
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n{stats}")
    print(f"→ {OUT.relative_to(BASE)}  ({len(result)} 个节点拿到沪教位置)")

    # ── 报告 ──
    kept = [v for v in result.values()]
    print("\n=== 证据档分布 ===")
    for k, v in collections.Counter(v["evidence"][0] for v in kept).most_common():
        print(f"  {k}: {v}")
    print("\n=== 样例 ===")
    for v in kept[:12]:
        t = v.get("tocHit") or {}
        where = f"{t.get('chapter','')}{t.get('chapterName','')} {t.get('section','')}{t.get('sectionName','')}"
        print(f"  {v['name'][:24]:26s} → {v['book']:14s} {v['evidence']} {where[:34]}")

    # 定位不到的（该剔的）
    miss = [n for n in rjb if n["id"] not in result]
    print(f"\n=== 定位不到、应剔除的人教版节点：{len(miss)} ===")
    for n in miss[:15]:
        print(f"  {n['name'][:30]:32s} g{n.get('grade')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
