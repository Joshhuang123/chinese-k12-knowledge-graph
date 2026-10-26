#!/usr/bin/env python3
"""判据选型：怎么判断「这个概念沪教教材教不教」。

用户选定的方向：**严格守住上海教材** ——
人教版节点只保留「真沪教也教」的，其余从站里移除。

判据不能拍脑袋，得比。三种候选：

  A. **全文出现**：概念名在沪教教材 9,009 页原文里出现过
     （含去括号的短名）
     优点：覆盖最广。缺点：单词命中容易假阳性（「脑」在初中生物里
     是解剖名词，不是高一的「脑」概念）。

  B. **节名命中**：概念名等于某个沪教教材的节名或章名
     优点：最精确 —— 教材确实用这个名字开了一节。
     缺点：节名往往是知识点集合（「B、T淋巴细胞参与特异性免疫应答」），
     命中率只有 6/975 —— 太严，会误杀大量真前置。

  C. **A + 册次约束**：全文命中，且命中位置在**该概念的合理册次**里
     （不早于概念本身的最小年级）。
     优点：兼顾覆盖与准确。

本脚本把三种判据的结果并排打出来，并给出**抽样人工核对**，
让判据的选择有据可依，而不是拍脑袋。

跑:  python3 src/align_edition_probe.py
"""
import json
import pathlib
import re
import collections

BASE = pathlib.Path(__file__).resolve().parent.parent
SG = BASE / "data" / "shanghai-graph.json"
TOC = BASE / "data" / "shanghai-toc.json"
LESSONS = BASE / "data" / "lessons-sh.jsonl"


def strip_paren(s: str) -> str:
    """去掉括号里的补充说明 —— 「光合作用色素」→ 概念主体是「光合作用色素」，
    但「ATP（腺苷三磷酸）」→ 主体是「ATP」。"""
    return re.sub(r"[（(].*?[）)]", "", s).strip()


def book_grade(bid: str):
    m = re.search(r"-(\d+)([ab])$", bid)
    if m:
        return int(m.group(1))
    for tag, g in (("bx1", 10), ("bx2", 11), ("bx3", 12), ("bx4", 12),
                   ("xzxbx1", 10), ("xzxbx2", 11), ("xzxbx3", 12)):
        if tag in bid:
            return g
    return None


def main() -> int:
    sg = json.loads(SG.read_text(encoding="utf-8"))
    toc = json.loads(TOC.read_text(encoding="utf-8"))

    # ── 沪教原文：book → 文本 ──
    by_book = collections.defaultdict(list)
    for line in LESSONS.open(encoding="utf-8"):
        if not line.strip():
            continue
        d = json.loads(line)
        by_book[d["book"]].append((d["page"], d.get("text", "")))

    # ── 沪教节名/章名 ──
    sec_names = set()
    for bid, b in toc["books"].items():
        for ch in b.get("chapters", []):
            if ch.get("name"):
                sec_names.add(ch["name"])
            for s in ch.get("sections", []):
                if s.get("name"):
                    sec_names.add(s["name"])

    # ── 逐册文本（判据 C 要用）──
    book_text = {bid: "\n".join(t for _, t in sorted(pages)) for bid, pages in by_book.items()}
    book_grade_map = {bid: book_grade(bid) for bid in book_text}

    # ── 待判的人教版 pre 节点 ──
    pre_rjb = [n for n in sg["nodes"]
               if n["kind"] == "pre" and n.get("editions") == ["人教版"]]

    # 沪教节点各自的年级（用真教材年级）
    sh_grade = {}
    for n in sg["nodes"]:
        if n["kind"] != "sh" or not n.get("mainBook"):
            continue
        b = n["books"].get(n["mainBook"])
        if b:
            sh_grade[n["id"]] = b.get("grade") or 0

    rows = []
    for n in pre_rjb:
        nm = n["name"]
        core = strip_paren(nm) or nm
        grade = n.get("grade") or 0

        # A：全文出现
        hit_books = []
        for bid, txt in book_text.items():
            if nm in txt or (core and core in txt):
                hit_books.append(bid)

        # B：节名命中
        sec_hit = nm in sec_names or (core and core in sec_names)

        # C：全文命中 + 册次不早于概念年级
        ok_books = [b for b in hit_books
                    if (book_grade_map.get(b) or 0) >= grade or grade == 0]
        # 「不早于」太严时放宽：允许命中在**任意**沪教册（人教初中概念可能
        # 在沪教初中另一册出现，年级相同即可）
        ok_books_same = [b for b in hit_books
                         if (book_grade_map.get(b) or 0) == grade or grade == 0]

        rows.append({
            "name": nm, "grade": grade, "subject": n.get("subject"),
            "A": len(hit_books) > 0,
            "A_books": sorted(set(hit_books))[:3],
            "B": sec_hit,
            "C": len(ok_books) > 0,
            "C_same": len(ok_books_same) > 0,
        })

    tot = len(rows)
    print(f"待判人教版 pre 节点：{tot} 个\n")
    print(f"  A 全文出现          {sum(r['A'] for r in rows):4d}  ({sum(r['A'] for r in rows)/tot*100:.1f}%)")
    print(f"  B 节名命中          {sum(r['B'] for r in rows):4d}  ({sum(r['B'] for r in rows)/tot*100:.1f}%)")
    print(f"  C 全文+册次不早于   {sum(r['C'] for r in rows):4d}  ({sum(r['C'] for r in rows)/tot*100:.1f}%)")
    print(f"  C' 全文+同年级      {sum(r['C_same'] for r in rows):4d}  ({sum(r['C_same'] for r in rows)/tot*100:.1f}%)")
    print(f"  A∧B                 {sum(r['A'] and r['B'] for r in rows):4d}")
    print(f"  A∧¬B（A 命中但节名没有）{sum(r['A'] and not r['B'] for r in rows):4d}")
    print(f"  ¬A（A 也没命中）    {sum(not r['A'] for r in rows):4d}")

    print("\n=== A 命中但节名没命中的（要看这些是不是真沪教概念）===")
    n = 0
    for r in rows:
        if r["A"] and not r["B"]:
            n += 1
            if n <= 25:
                print(f"  {r['name'][:34]:36s} g{r['grade']:<3d} {r['subject'] or '':9s} {r['A_books']}")
    print(f"  （共 {n} 个）")

    print("\n=== A 也没命中的（这些要被剔除）——抽样 25 个===")
    miss = [r for r in rows if not r["A"]]
    for r in miss[:25]:
        print(f"  {r['name'][:34]:36s} g{r['grade']:<3d} {r['subject'] or ''}")
    print(f"  （共 {len(miss)} 个）")

    print("\n=== 按年级看 A 的命中率 ===")
    per = collections.defaultdict(lambda: [0, 0])
    for r in rows:
        per[r["grade"]][1] += 1
        if r["A"]:
            per[r["grade"]][0] += 1
    for g in sorted(per):
        hit, tot_g = per[g]
        print(f"  grade {g:2d}: {hit:4d}/{tot_g:<4d} ({hit/tot_g*100:.1f}%)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
