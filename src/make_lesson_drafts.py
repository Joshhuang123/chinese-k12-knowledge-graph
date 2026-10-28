#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
挑出**值得做讲解视频**的概念，并抽出写稿要用的素材。

选片判据（五个都要满足）
------------------------
1. **有教材页图** —— 视频里能真指一页书给学生看。
   没有页图的概念，视频就只剩抽象图形，讲不出「这是教材第几页」。
2. **有教材原话** —— 视频要能引用教材自己的话，不能只有我们的二手转述。
3. **核心概念**（core=1）—— 上游标注的核心，不是边角料。
4. **有前置** —— 「学它之前要先会」是学习页的核心价值，
   没有前置的概念讲不出卡点。
5. **教材自己标过难** —— `data/normalized/textbook-hard.json` 记录了
   教材里的「思考 / 探究」题挂在哪个概念下。**这是第一手依据**：
   不是我们觉得它难，是教材觉得它难。

⚠️ **为什么不能按依赖度 c 直接排**
   `c` = 这个概念被多少别的概念依赖，而**依赖数是图内规模决定的**：
   人教版图谱 8,667 个节点，沪教版 3,503 个 —— 同样一个「一元一次方程」，
   在人教版里的依赖数天然更大。
   实测：按 c 排出来 **36 个人教版 vs 4 个沪教版**，
   而上海才是这个站的主场。所以 c 只能在**版本内**排序，不能跨版本比。

跨版本均衡：每个版本各取一半，学段（小学/初中/高中）轮着取。

⚠️ **不要用「被搜得多」来选** —— 我们没有搜索日志，
别假装有（那正是本项目一贯的纪律：数字要能回一手）。

跑:
    python3 src/make_lesson_drafts.py --n 40
    python3 src/make_lesson_drafts.py --n 40 --out data/lesson-drafts
"""
import argparse
import collections
import json
import pathlib
import sys

BASE = pathlib.Path(__file__).resolve().parent.parent
DATA = BASE / "data"


def load(tag):
    t = (DATA / f"learn-{tag}.js").read_text(encoding="utf-8")
    return json.loads(t[t.index("=") + 1:].rstrip().rstrip(";"))


def stage_of(g):
    if not g:
        return "其他"
    if g <= 6:
        return "小学"
    if g <= 9:
        return "初中"
    return "高中"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=40, help="挑几个概念")
    ap.add_argument("--out", default="data/lesson-drafts", help="素材包输出目录")
    ap.add_argument("--versions", default="sh,rjb", help="要考虑的版本")
    ap.add_argument("--no-hard", action="store_true",
                    help="不要求教材标过难（放宽到全部候选）")
    args = ap.parse_args()

    outdir = BASE / args.out
    outdir.mkdir(parents=True, exist_ok=True)

    # 教材自己标的难题（第一手）
    hard = {}
    hf = DATA / "normalized" / "textbook-hard.json"
    if hf.exists():
        hard = json.loads(hf.read_text(encoding="utf-8")).get("concepts") or {}

    # 印刷页码偏移 —— 写稿的人要的是**书上印的页码**，不是 PDF 扫描页。
    # （差 4–7 页，学生按扫描页翻书会翻到下一节）
    off_rjb = {}
    off_sh = {}
    # 沪教版**没有本地页图**（项目版权决定：沪教走平台官方外链，仓库不存教材内容），
    # 视频里那一页只能是**平台的直链**。
    platform_pages = {}
    pf = DATA / "page-images.json"
    if pf.exists():
        platform_pages = json.loads(pf.read_text(encoding="utf-8"))
    for fn, dest in (("page-offsets.json", "rjb"), ("page-offsets-sh.json", "sh")):
        p = DATA / fn
        if p.exists():
            d = json.loads(p.read_text(encoding="utf-8"))
            (off_rjb if dest == "rjb" else off_sh).update(d)

    def printed_page(loc):
        """→ (印刷页码 or None, 描述)"""
        scan = (loc.get("scan") or [None])[0]
        if not scan:
            return None, ""
        if loc.get("pdfBook"):
            o = off_rjb.get(loc["pdfBook"])
            if o is None:
                return None, ""
            return scan + o, f"{loc.get('ed') or ''}{loc.get('vol') or ''}"
        o = off_sh.get(loc.get("bk") or "")
        if o is None:
            return None, ""
        return scan + o, f"{loc.get('ed') or ''}{loc.get('vol') or ''}"

    cands = []
    for tag in args.versions.split(","):
        D = load(tag)
        # 版本内的依赖度排名（c 只能版本内比）
        rank = {n["id"]: i for i, n in
                enumerate(sorted(D["nodes"], key=lambda x: -(x.get("c") or 0)))}
        for n in D["nodes"]:
            loc = n.get("loc") or {}
            if not loc.get("scan"):
                continue
            if not n.get("rd") or not n.get("core"):
                continue
            # 前置**或**后继至少有一个 ——
            # 样板前置被数据层滤掉了（ISSUE-53），大部分概念的 pre 是空的，
            # 视频的第四场改画「接下来会学」，所以两个有一个就够。
            if not n.get("pre") and not n.get("suc"):
                continue
            h = hard.get(n["id"])
            if not args.no_hard and not h:
                continue
            pp, pdesc = printed_page(loc)
            if pp is None:
                continue        # 算不出印刷页码 → 不选（页码错了比没有更糟）
            if pp <= 0:
                # ⚠️ **印刷页 ≤ 0 = 选到前言页了**（封面 / 本册导引 / 目录）——
                # 那些页书上**根本没印页码**，offset 一加就成负数。
                # 实测：反比例函数选到「本册导引」（扫描页 3）→ 印刷页 -3。
                # 前言页当「教材原页」等于没指到那一节。
                continue
            cands.append({
                "id": n["id"], "version": tag, "name": n["n"],
                "book": n.get("b"), "grade": n.get("g"),
                "stage": stage_of(n.get("g")),
                "definition": n.get("d") or "",
                "c": round(n.get("c") or 0, 4),
                "c_rank_in_version": rank.get(n["id"], 9999),
                "src": n.get("src") or "",
                # 教材标的难题 —— 写稿时可以用它当「学生到底卡在哪儿」的线索
                "hard_count": (h or {}).get("count", 0),
                "hard_items": [{"type": it.get("type"), "stem": it.get("stem")}
                               for it in ((h or {}).get("items") or [])][:4],
                "quotes": [{"text": r.get("t"), "def": r.get("def"), "page": r.get("p")}
                           for r in (n.get("rd") or [])][:4],
                "formulas": (n.get("f") or [])[:6],
                "figures": [{"cap": g.get("c"), "text": (g.get("t") or "")[:120]}
                            for g in (n.get("fg") or [])][:3],
                "prereq": [{"name": nm} for _, nm in (n.get("pre") or [])][:6],
                "successor": [{"name": nm} for _, nm in (n.get("suc") or [])][:6],
                # 第四场画什么：**有像样前置就画前置，没有就画后继**。
                # 样板前置已被数据层滤掉（见 ISSUE-53），所以这里拿到的
                # 前置都是真的（浮力 → 重力/力/液体压强）。
                "chain_title": "学它之前要先会" if n.get("pre") else "接下来会学",
                "chain_label": "这几样要先会" if n.get("pre") else "顺着往下学",
                "exercises": (n.get("pr") or [])[:3],
                "page": {
                    "pdfBook": loc.get("pdfBook"), "bk": loc.get("bk"),
                    "scan": loc["scan"][0],
                    # 页图来源：**人教版**从本地 PDF 渲染的页图；
                    # **沪教版**是平台官方外链（仓库里不存教材内容）。
                    "image": (f"data/pages/{loc['pdfBook']}/{loc['scan'][0]}.webp"
                              if loc.get("pdfBook")
                              else ((platform_pages.get(loc.get("bk") or "") or {}).get("base", "")
                                    + f"/{loc['scan'][0]}.jpg")),
                    # ⚠️ **printed 是书上印的页码**，scan 是 PDF/平台扫描序号。
                    # 写稿一律用 printed（学生拿着纸书翻）。
                    "printed": pp,
                    "where": f"{pdesc} · 印刷页 {pp}",
                    "vol": loc.get("vol"), "ed": loc.get("ed"),
                },
            })

    # ── 跨版本 + 跨学段均衡 ──
    # 组：(版本, 学段)。组内按「教材标的难题数」降序，再按版本内依赖度排名。
    groups = collections.defaultdict(list)
    for c in cands:
        groups[(c["version"], c["stage"])].append(c)
    for k in groups:
        groups[k].sort(key=lambda c: (-c["hard_count"], c["c_rank_in_version"]))

    keys = sorted(groups, key=lambda k: (k[0], ["小学", "初中", "高中", "其他"].index(k[1])))
    picked = []
    round_i = 0
    while len(picked) < args.n and any(groups[k] for k in keys):
        for k in keys:
            if len(picked) >= args.n:
                break
            if groups[k]:
                picked.append(groups[k].pop(0))
    # 组内取完再轮

    # ⚠️ 文件名必须带版本 —— 上游的 id **跨版本共享**：
    #   math_7a_rjb_cpt58 在沪教版是「立体图形」，在人教版是另一本教材里的东西。
    #   只按 id 命名会互相覆盖（清单里实测有 9 个 id 重复）。
    manifest = []
    for c in picked:
        key = f"{c['version']}_{c['id']}"
        p = outdir / f"{key}.json"
        p.write_text(json.dumps(c, ensure_ascii=False, indent=1), encoding="utf-8")
        manifest.append(key)

    (outdir / "_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"候选 {len(cands)} 个 → 挑了 {len(picked)} 个")
    print(f"素材包 → {outdir}/（{len(manifest)} 份）\n")
    print("按版本:", dict(collections.Counter(c["version"] for c in picked)))
    print("按学段:", dict(collections.Counter(c["stage"] for c in picked)))
    print("按学科:", dict(collections.Counter(
        (c["book"] or "").split("·")[0][:4] or "?" for c in picked)))
    print()
    for c in picked:
        print(f"  {c['id']:32s} {c['name'][:16]:18s} {c['book'] or '':14s} "
              f"难{c['hard_count']} c={c['c']:.3f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
