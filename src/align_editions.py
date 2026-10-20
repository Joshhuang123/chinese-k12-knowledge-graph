#!/usr/bin/env python3
"""
把图谱的概念映射到**其他出版社教材**的章节位置。

## 做什么

图谱的教材顺序是按人教版排的（`books.py` 的 `RANK` 只排人教）。
一个用湘教版的学生查「二次函数」，页面上写的「九上 22.2」对他没意义。

这个脚本做**节 → 节**的对齐：
    人教「5.1 相交线」  ←→  冀教「1.1 正数和负数」…（同位置的节）
然后概念就跟着走：
    概念「正数和负数」→ 人教七上 1.1 → 湘教七上 第X章 1.1

## 为什么按「节」对齐而不是按「章」

数学各出版社的**内容顺序其实很接近**（同一份课标），
但**章的切法不同**：人教七上 4 章，冀教七上 4 章，但边界不一样。
按节对齐才准。

## 匹配靠不靠得住

各出版社的节名**不总一样**：
人教「1.3 绝对值」 vs 冀教「1.3 绝对值与相反数」——大同小异，
用 difflib 的相似度能对上。但「1.1 正数和负数」vs「1.1 有理数」这种就地对不上。

所以本脚本**报出匹配率**，匹配不上的**老老实实标 unmatched**，
不硬凑。匹配率低于阈值的版本直接说「这套教材对不上」。

## 跑法

```bash
python3 src/align_editions.py
python3 src/align_editions.py --out data/alt-align.json
"""
import argparse
import difflib
import json
import pathlib
import re
import sys
from collections import Counter, defaultdict

BASE = pathlib.Path(__file__).resolve().parent.parent
ALT = BASE / "data" / "alt-editions.json"
GRAPH = BASE / "data" / "normalized" / "graph.json"
OUT = BASE / "data" / "alt-align.json"

# 节的编号是「1.1」这种，它本身就有信息量 —— 先按编号对齐，再按名字
NOISE = re.compile(r"[\s　·、，,。．.（）()【】\[\]—－\-_/\\]+")

# manifest 里的册次名（从文件名认出来的）→ 图谱里的册次码
BOOKMAP = {
    "七上": "7a", "七下": "7b", "八上": "8a", "八下": "8b",
    "九上": "9a", "九下": "9b",
    "六上": "6a", "六下": "6b", "五上": "5a", "五下": "5b",
    "四上": "4a", "四下": "4b", "三上": "3a", "三下": "3b",
    "二上": "2a", "二下": "2b", "一上": "1a", "一下": "1b",
    "必修一": "bx1", "必修二": "bx2",
    "选必一": "xzxbx1", "选必二": "xzxbx2", "选必三": "xzxbx3",
}


def norm(s):
    return NOISE.sub("", s or "")


def chap_only(s):
    """章名去掉「第N章」前缀，只留名字。"""
    return norm(re.sub(r"^第[一二三四五六七八九十\d\.]+章", "", s or ""))


def book_of(node_id):
    """从节点 id 里取册次码：math_7b_rjb_cpt1 → 7b"""
    m = re.match(r"[a-z]+_([0-9a-z]+)_", node_id or "")
    return m.group(1) if m else ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out")
    ap.add_argument("--min-sim", type=float, default=0.55)
    args = ap.parse_args()

    if not ALT.exists():
        print("! 先跑 src/extract_editions.py")
        return 1
    alt = json.load(open(ALT, encoding="utf-8"))
    g = json.load(open(GRAPH, encoding="utf-8"))

    # ── 人教基准：图谱里的 Section 节点 ──
    # Section 的 id 形如 math_7b_rjb_ch5_s1，book 从 id 取
    # **键必须是 (学科, 册)，不能只用册。**
    # `book` 码是**跨学科复用**的：7a 既是数学七上、也是生物七上、还是物理八上。
    # 只按 book 键，生物的概念会被混进数学的对照里 ——
    # 症状是「光合作用」这种生物概念也标上了「冀教版七下 7.2 相交线」。
    base_secs = defaultdict(list)      # (subject, book) → [{no, name, chapter}]
    sec_of_ch = {}
    for n in g["nodes"]:
        if n.get("label") != "Section":
            continue
        bk = book_of(n["id"])
        m = re.search(r"_ch(\d+)_s(\d+)$", n["id"])
        if not m:
            continue
        base_secs[(n.get("subject"), bk)].append({
            "no": f"{m.group(1)}.{m.group(2)}",
            "name": re.sub(r"^第[一二三四五六七八九十]+节\s*", "", n["name"]).strip(),
            "chapter": n["name"],
            "id": n["id"],
        })
    # 章名：Chapter 节点
    ch_name = {}
    for n in g["nodes"]:
        if n.get("label") == "Chapter":
            m = re.search(r"_ch(\d+)$", n["id"])
            if m:
                ch_name[((n.get("subject"), book_of(n["id"])), m.group(1))] = n["name"]

    # 概念 → 它挂在哪个 Section（**按册分开**）
    # **必须按册分开。** 「有理数」这类概念同时 appears_in 七上「第二节 有理数」
    # 和七下「第三节 实数」（七下那一章是复习）——
    # 不分册的话，七上的概念会被映射到七下的节，跨册串掉。
    concept_secs = defaultdict(lambda: defaultdict(list))
    for e in g["edges"]:
        if e["type"] != "appears_in":
            continue
        tgt = next((x for x in g["nodes"] if x["id"] == e["to"]), None)
        if tgt and tgt.get("label") == "Section":
            src = next((x for x in g["nodes"] if x["id"] == e["from"]), None)
            if src and src.get("label") in ("Concept", "Skill"):
                bk = (tgt.get("subject"), book_of(e["to"]))
                concept_secs[bk][e["from"]].append(e["to"])

    print("=" * 72)
    print("多版本教材对齐")
    print("=" * 72)

    result = {}
    skipped = []
    for ed, books in sorted(alt.items()):
        for bk, data in sorted(books.items()):
            # **质量闸**：章名不可信的书不进对照表。
            # 扫描质量差的教材 OCR 出来是「个单位」「CTCU$:VWA%8XBC!」这种东西，
            # 拿它做多版本对照，用户只会觉得这个项目在瞎搞。
            if not data.get("reliable"):
                skipped.append((ed, bk, data.get("why", "")))
                continue
            gbk = BOOKMAP.get(bk, bk)
            subj = "math"          # 目前只下了初中数学
            secs = []
            for c in data.get("chapters", []):
                for s in c.get("secs", []):
                    secs.append({"no": s["no"], "name": s["name"],
                                 "chapter": c["ch"], "page": s.get("page")})
            if not secs:
                continue
            bsec = base_secs.get((subj, gbk), [])
            if not bsec:
                print(f"  {ed}/{bk}: 图谱里没有这一册的 Section（册次码 {gbk}），跳过")
                continue
            # 逐个人教节，找最像的
            pairs = []
            for bs in bsec:
                bn, bno = norm(bs["name"]), bs["no"]
                best, sim = None, 0.0
                for s in secs:
                    sn = norm(s["name"])
                    # ── 名字是主判据；编号只在**两版章界一致**时才作数 ──
                    #
                    # 两版教材把一章切成几节，往往不一样：
                    #   人教七上 第三章 = 从算式到方程，4 节
                    #   沪科七上 第三章 = 一次方程与方程组，5 节
                    # 这种情况下「都是 3.4」**不代表同一节** ——
                    # 人教 3.4 是「实际问题与一元一次方程」，
                    # 沪科 3.4 是「二元一次方程组的应用」，完全两回事。
                    #
                    # 但如果两版的**章名**是对得上的（切法一致），
                    # 编号就非常可靠：
                    #   人教 1.2「有理数」（这一节含数轴/相反数/绝对值）
                    #   沪科 1.2「数轴、相反数和绝对值」—— 名字对不上，编号对得上，那是对的。
                    #
                    # 所以：**章名像 → 编号可以作数；章名不像 → 只听名字。**
                    sc = difflib.SequenceMatcher(None, bn, sn).ratio()
                    if s["no"] == bno:
                        # **比较章名时要去掉「第N章」前缀** ——
                        # 两版的章号本来就不同（人教七下第五章、冀教七下第七章），
                        # 带着编号比会把相似度拖到 0.5 以下，
                        # 于是「编号可以作数」这条规则永远不生效。
                        ch_sim = difflib.SequenceMatcher(
                            None, chap_only(bs["chapter"]),
                            chap_only(s["chapter"])).ratio()
                        if ch_sim >= 0.5:
                            sc = max(sc, 0.75)
                    if sc > sim:
                        best, sim = s, sc
                pairs.append((bs, best, sim))
            matched = [p for p in pairs if p[2] >= args.min_sim]
            rate = len(matched) / len(pairs) if pairs else 0
            # 概念映射：**只取同一册的 section**
            cmap = {}
            for cid, sl in concept_secs.get((subj, gbk), {}).items():
                for sid in sl:
                    for bs, best, sim in pairs:
                        if bs["id"] == sid and best and sim >= args.min_sim:
                            cmap[cid] = {"base": f"{bs['no']} {bs['name']}",
                                         "alt": f"{best['no']} {best['name']}",
                                         "chapter": best["chapter"],
                                         "sim": round(sim, 2)}
                            break
            result.setdefault(ed, {})[bk] = {
                "sections": len(secs), "baseSections": len(pairs),
                "matchRate": round(rate, 3), "matched": len(matched),
                "concepts": len(cmap), "conceptPos": cmap,
                "unmatched": [f"{p[0]['no']} {p[0]['name']}" for p in pairs
                              if p[2] < args.min_sim],
            }
            print(f"  {ed}/{bk:<8} 人教 {len(pairs):>3} 节 ←→ 该版 {len(secs):>3} 节"
                  f"  匹配 {len(matched):>3}（{rate*100:5.1f}%）  概念 {len(cmap):>4}")
    if skipped:
        print(f"\n  跳过 {len(skipped)} 册（提取不可信，不进对照表）：")
        for ed, bk, why in skipped:
            print(f"    {ed}/{bk}  {why}")

    op = pathlib.Path(args.out) if args.out else OUT
    if not op.is_absolute():
        op = BASE / op
    # 按概念聚合：一个概念在各个版本里分别在哪儿
    by_concept = defaultdict(list)
    for ed, books in result.items():
        for bk, r in books.items():
            for cid, m in r.get("conceptPos", {}).items():
                by_concept[cid].append({
                    "edition": ed, "book": bk,
                    "label": f"{ed.replace('初中数学', '')} {bk}",
                    "alt": m["alt"], "chapter": m["chapter"], "sim": m["sim"],
                })
    json.dump({"_comment": ("人教节 → 其他出版社节的对应。匹配靠 difflib 相似度"
                            "（编号相同直接算 1.0），低于阈值的标 unmatched，不硬凑。"),
               "minSim": args.min_sim, "align": result,
               "byConcept": {k: v for k, v in by_concept.items()}},
              open(op, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\n→ {op.relative_to(BASE)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
