#!/usr/bin/env python3
"""
把从「本章知识结构图」读出来的关系，映射到图谱节点上，并跟现有边比对。

## 它回答三个问题

1. **教材说 A 是 B 的前置，图谱里有没有这条边？**
   → 有 = **教材确认了这条边**（上游的边多了个独立来源，可信度上升）
2. **教材说了 A → B，图谱里没有，这条能补吗？**
   → 能补 = 教材引入路径的**新边**
3. **教材里出现、图谱里根本没有的概念名？**
   → 这是**知识点覆盖缺口** —— 上游数据集漏了什么

## 三类关系要分开

结构图里的边不是都是先修关系：

| kind | 是什么 | 用途 |
|---|---|---|
| `prereq` / `method` | 先修依赖、方法依赖 | **建先修边** |
| `abstract` / `goal` / `verify` | 抽象、目标、检验 | 记下来，但**不是先修边** |
| `other` | 分类/包含、相反变形、并列 | 多数是**上下位关系**，可补 is_a |

**「other」里也可能有金子**：比如「整式的乘法 → 因式分解（相反变形）」
不是先修，但「几何图形 → 平面图形」是**包含关系** ——
上游的 is_a 边只有 1895 条，教材能补上一批。

## 跑法

```bash
python3 src/map_structmaps.py --in /tmp/structmap-raw.json
```
"""
import argparse
import json
import pathlib
import re
import sys
from collections import Counter, defaultdict

BASE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from nameindex import NameIndex   # noqa: E402

GRAPH = BASE / "data" / "normalized" / "graph.json"
SELF = BASE / "data" / "normalized" / "selfbuilt-edges.json"

PREREQ_KINDS = {"prereq", "method"}


def is_formula(s):
    """教材结构图里有些「节点」其实是公式或表达式，不是概念。
    「(√a)²=a(a≥0)」「方程 ax²+bx+c=0 的根 x=(-b±√(b²-4ac))/2a」这类。
    判据：含等号，或含 √ ∫ ∑ ² ³ 这类数学符号。
    """
    if not s:
        return False
    if "=" in s:
        return True
    return any(ch in s for ch in "√∫∑≠≤≥±²³⁴")
NOISE = re.compile(r"[（(].*?[)）]|[，,、；;]")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", required=True, help="子代理给的 JSON 数组")
    ap.add_argument("--out", default="data/normalized/structmap-edges.json")
    args = ap.parse_args()

    g = json.load(open(GRAPH, encoding="utf-8"))
    sb = json.load(open(SELF, encoding="utf-8"))
    idx = NameIndex(g["nodes"])
    nb = {n["id"]: n for n in g["nodes"]}

    have = set()
    for e in g["edges"]:
        if e["type"] == "prerequisites_for":
            have.add((e["from"], e["to"]))
    for e in sb["edges"]:
        if e["type"] == "prerequisites_for":
            have.add((e["from"], e["to"]))

    raw = json.load(open(args.inp, encoding="utf-8"))

    # 教材结构图里的「概念」，很多其实是**教材的小节名**
    # （如「数据的集中趋势」是八下第 20 章的一节），在图谱里是 Section 节点，
    # 不是知识点。NameIndex 不索引 Section，所以 resolve 不到 ——
    # 这**不是缺口**，是教材的概念粒度跟图谱的知识点粒度不一样。
    section_names = {}
    for n in g["nodes"]:
        if n["label"] in ("Section", "Chapter"):
            nm = n.get("name", "")
            section_names.setdefault(nm, []).append(n["id"])
            # 图谱的节名带序号前缀：「第二节 垂线及其性质」
            bare = re.sub(r"^第[一二三四五六七八九十\d]+[节章节]\s*", "", nm).strip()
            if bare and bare != nm:
                section_names.setdefault(bare, []).append(n["id"])

    # 教材的概念名常带公式后缀：
    #   「一元二次方程 ax²+bx+c=0」  → 「一元二次方程」
    #   「二次函数 y=ax²+bx+c」        → 「二次函数」
    #   「函数y=Asin(ωx+φ)」          → 「函数」
    #   「一次函数 y=kx+b (k≠0)」      → 「一次函数」
    MATHY = re.compile(r"[\s=＋+\-±∝≤≥<>^/·()（）\[\]0-9a-zωφπΔ∠⊥∥].*$")

    def strip_formula(t):
        t = (t or "").strip()
        # 先切掉「=」及其后
        if "=" in t:
            t = t.split("=")[0].strip()
        # 再剥尾部连续的数学符号/数字/拉丁字母
        t = MATHY.sub("", t).strip()
        return t

    def resolve(name):
        """教材里的概念名 → 图谱节点 id。返回 (id 或 None, 用的哪档, 候选数)。"""
        n = (name or "").strip()
        if not n:
            return None, "空", 0
        cands_to_try = [n]
        # 拆多条名：「配方法, 公式法, 因式分解法」是三个概念
        for piece in re.split(r"[、，,]|和|与", n):
            piece = piece.strip()
            if piece and len(piece) >= 2 and piece not in cands_to_try:
                cands_to_try.append(piece)
        # 剥公式后缀的版本也要试
        for v0 in list(cands_to_try):
            sf = strip_formula(v0)
            if sf and len(sf) >= 2 and sf not in cands_to_try:
                cands_to_try.append(sf)
        for v0 in cands_to_try:
            # 先剥括号注释：「一元一次方程的解（x=a）」→「一元一次方程的解」
            for v in (v0, NOISE.sub("", v0).strip(),
                      v0.split("（")[0].split("(")[0].strip()):
                if not v or len(v) < 2:
                    continue
                st, nid, cands, how = idx.resolve(v)
                if nid is not None:
                    return nid, st, 1
                if st.startswith("CONTAIN") and len(cands) == 1:
                    return cands[0], "CONTAIN_UNIQUE", 1
        # **双向子串**：结构图写「函数的概念与表示」，图谱写「函数的概念与性质」，
        # 谁也不是谁的前缀 —— 但前 4 个字一样。
        # 只查「结构图名 ⊂ 图谱名」会漏掉反过来的情况。
        for v0 in cands_to_try:
            for v in (v0, strip_formula(v0), NOISE.sub("", v0).strip()):
                if not v or len(v) < 2:
                    continue
                # 取**最长**的匹配（更具体）
                best = None
                for key, ids in idx.by_norm.items():
                    if len(key) < 2:
                        continue
                    if key in v or v in key:
                        if best is None or len(key) > len(best[0]):
                            best = (key, sorted(ids))
                if best:
                    return best[1][0], "SUBSTR", 1
        # 知识点里没有，但教材的小节里有 → 它是「节」，不是知识点
        for v0 in cands_to_try:
            for v in (v0, strip_formula(v0), NOISE.sub("", v0).strip()):
                if v and v in section_names:
                    return None, "是教材的小节(Section)，不是知识点", 0
        return None, "MISS", 0

    stat = Counter()
    confirmed, new_prereq, other_rel, missing_nodes = [], [], [], []
    seen = set()

    for page in raw:
        book = page.get("book", "")
        for e in page.get("edges", []):
            f, t = e.get("from"), e.get("to")
            kind = e.get("kind", "other")
            label = e.get("label", "") or ""
            if not f or not t or f == t:
                stat["跳过(空或自环)"] += 1
                continue
            fid, fhow, _ = resolve(f)
            tid, thigh, _ = resolve(t)
            key = (fid, tid, kind, book)
            if key in seen:
                stat["重复"] += 1
                continue
            seen.add(key)
            if fid is None or tid is None:
                miss_kind = fhow if fid is None else thigh
                if "Section" in miss_kind:
                    stat["教材的小节名，不是知识点节点"] += 1
                    continue
                if is_formula(f) or is_formula(t):
                    stat["教材里的公式/表达式，不是概念"] += 1
                    continue
                stat["图谱里真的没有这个概念"] += 1
                missing_nodes.append({
                    "book": book, "page": page.get("page"),
                    "from": f, "to": t, "label": label, "kind": kind,
                    "missingSide": "from" if fid is None else "to",
                    "fromHow": fhow, "toHow": thigh,
                })
                continue
            rec = {
                "from": fid, "to": tid,
                "fromName": nb[fid].get("name", fid),
                "toName": nb[tid].get("name", tid),
                "label": label, "kind": kind,
                "book": book, "page": page.get("page"),
            }
            if kind in PREREQ_KINDS:
                if (fid, tid) in have:
                    stat["先修边·图谱已有(教材确认)"] += 1
                    confirmed.append(rec)
                else:
                    stat["先修边·图谱没有(可补)"] += 1
                    new_prereq.append(rec)
            else:
                stat[f"其他关系·{kind}"] += 1
                other_rel.append(rec)

    print("=" * 60)
    print("教材结构图 → 图谱节点")
    print("=" * 60)
    for k, v in stat.most_common():
        print(f"  {v:5}  {k}")
    tot = sum(v for k, v in stat.items() if "先修边" in k)
    if tot:
        print(f"\n先修关系里，图谱已有的 {stat['先修边·图谱已有(教材确认)']} 条"
              f"（教材独立确认），可补的新边 {stat['先修边·图谱没有(可补)']} 条")
    if missing_nodes:
        print(f"\n教材里出现、图谱里没有的概念（覆盖缺口）：")
        for m in missing_nodes[:20]:
            side = "前置" if m["missingSide"] == "from" else "后继"
            print(f"  {m['book']} {m['page']}  {side}「{m['from'] if m['missingSide']=='from' else m['to']}」"
                  f"  ({m['kind']})")
        if len(missing_nodes) > 20:
            print(f"  …共 {len(missing_nodes)} 处")

    out = {
        "_comment": "教材「本章知识结构图」读出来的关系，映射到图谱节点后的结果。",
        "confirmed": confirmed,      # 教材确认了图谱已有的先修边
        "new_prereq": new_prereq,    # 教材说了、图谱没有的先修边
        "other_rel": other_rel,      # 非先修关系（分类/包含/检验…）
        "missing_nodes": missing_nodes,
    }
    op = pathlib.Path(args.out)
    if not op.is_absolute():
        op = BASE / op
    op.parent.mkdir(parents=True, exist_ok=True)
    json.dump(out, open(op, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\n已写 {op.relative_to(BASE)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
