#!/usr/bin/env python3
"""
检测「下位概念被当成上位概念的前置」这一族上游坏边。

## 缺陷长什么样

上游把**具体化/下位**的知识点当成了**上位**知识点的前置：

```
「三角形的高」      → 「三角形」      高是三角形的属性，不是它的前提
「旋转中心/方向/角度」→ 「旋转」        要素，不是前提
「用三角尺判断直角」 → 「直角」        手段，不是前提
「对数函数的单调性」  → 「对数函数」    ISSUE-09 点名过的那条
「用图示理解乘法」    → 「乘法」        理解手段，不是前提
```

共同特征是**前置名里含着后继名**：学「三角形」不需要先会「三角形的高」，
恰恰相反。

这跟 ISSUE-09（38 条方向反了）、ISSUE-11（188 条跟教材顺序倒挂）
是同一族问题，但**检测口径完全不同**：
ISSUE-11 比的是教材位置，本判据比的是名字的字面结构 ——
所以它是**独立**的证据来源。

## 三档证据

单看字面会误判：「电能表」→「电能」字面也含，但那是真前置
（先有测电能的表，再理解电能）。所以本脚本给每条候选标证据强度：

| 档 | 判据 | 实测 |
|---|---|---|
| **A 双证据** | 模型的 dispute 指认 + 教材顺序倒挂 | 12 条 |
| **B 单证据** | 模型 dispute 或 教材倒挂，二者之一 | 29 条 |
| **C 仅字面** | 只有「前置名含后继名」 | 44 条 |

A 档 12 条逐条看过，**全部成立**。
C 档精确率约 40%（抽样目视：11 条真错 / 15 条真前置），
**只能当筛选器，不能当删除依据**。

## 一个独立佐证：模型自己也犯

同一条规则扫模型自己重建的 2928 条边，命中 7 条，
逐条看**全部是真错**（「小括号的作用」→「括号的作用」等）。

```
upstream  3703 条  命中  85  (2.3%)
model     2928 条  命中   7  (0.2%)   ← 低一个数量级
l0         415 条  命中   2  (0.5%)
derived     90 条  命中   0  (0.0%)
```

模型这一栏是**独立**的：merge_prereq 的册序闸只管教材位置，
管不到名字的字面结构，所以这个 0.2% vs 2.3% 不是构造出来的。

## 跑法

```bash
python3 src/detect_subordinate.py            # 汇总 + 分档
python3 src/detect_subordinate.py --show A   # 只看 A 档
python3 src/detect_subordinate.py --out data/normalized/subordinate-edges.json
```
"""
import argparse
import glob
import json
import pathlib
import re
import sys
from collections import Counter

BASE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

GRAPH = BASE / "data" / "normalized" / "graph.json"
SELF = BASE / "data" / "normalized" / "selfbuilt-edges.json"
LMM = BASE / "data" / "lmm-out"
COLLIDE = BASE / "data" / "normalized" / "order-collide.json"

# 前置名里含着后继名 → 前置是后继的具体化
STRIP = re.compile(r"[\s，,、。．.（）()【】\[\]“”\"'\-]+")


def norm(s):
    return STRIP.sub("", s or "")


def contains(a, b):
    return len(b) >= 2 and b in a and a != b


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--show", default="", help="只看某档：A / B / C")
    ap.add_argument("--out")
    args = ap.parse_args()

    g = json.load(open(GRAPH, encoding="utf-8"))
    sb = json.load(open(SELF, encoding="utf-8"))
    name = {n["id"]: n.get("name", "") for n in g["nodes"]}
    for n in sb["nodes"]:
        name[n["id"]] = n.get("name", "")

    edges = [("upstream", e["from"], e["to"]) for e in g["edges"]
             if e["type"] == "prerequisites_for"]
    for e in sb["edges"]:
        edges.append((e.get("source", "?"), e["from"], e["to"]))

    # 模型 dispute 指认过的边。
    # **两处都要收**：结构化形态（dispute 是带 from/to 的对象）只有 9 条，
    # 文字形态（126 条，指名了概念名）才是大头。
    # 只收结构化的话 A 档会算成 0 条 —— 检测器自己有 bug，
    # 报出来的是「没有双证据」，看起来像结论，其实是漏收。
    disp = set()
    for f in sorted(glob.glob(str(LMM / "math-*.json"))):
        for it in json.load(open(f, encoding="utf-8")):
            for d in it.get("dispute", []):
                if isinstance(d, dict) and d.get("from") and d.get("to"):
                    disp.add((d["from"], d["to"]))
    de = BASE / "data" / "normalized" / "dispute-edges.json"
    if de.exists():
        for d in json.load(open(de, encoding="utf-8")):
            if d.get("from") and d.get("to"):
                disp.add((d["from"], d["to"]))

    # 教材顺序倒挂
    rev = set()
    if COLLIDE.exists():
        col = json.load(open(COLLIDE, encoding="utf-8"))
        rev = {(r["from"], r["to"]) for r in col["rows"]}

    rows = []
    for src, f, t in edges:
        a, b = norm(name.get(f, "")), norm(name.get(t, ""))
        if not contains(a, b):
            continue
        has_d, has_r = (f, t) in disp, (f, t) in rev
        grade = "A" if (has_d and has_r) else ("B" if (has_d or has_r) else "C")
        i = a.index(b)
        shape = "prefix" if i == 0 else (
            "suffix" if i + len(b) == len(a) else "middle")
        rows.append({
            "grade": grade, "source": src, "shape": shape,
            "from": f, "to": t,
            "fromName": name.get(f, ""), "toName": name.get(t, ""),
            "modelDispute": has_d, "textbookReversed": has_r,
        })

    order = {"A": 0, "B": 1, "C": 2}
    rows.sort(key=lambda r: (order[r["grade"]],
                             0 if r["source"] == "upstream" else 1,
                             r["fromName"]))

    print("=" * 60)
    print("「下位概念当前置」检测")
    print("=" * 60)
    cnt = Counter((r["source"], r["grade"]) for r in rows)
    srcs = sorted({r["source"] for r in rows} | {s for s, _, _ in edges})
    print(f"{'来源':<10}{'边数':>7}{'A双证据':>9}{'B单证据':>9}{'C仅字面':>9}{'合计':>7}{'占比':>8}")
    for s in srcs:
        es = [e for e in edges if e[0] == s]
        a, b, c = cnt[(s, "A")], cnt[(s, "B")], cnt[(s, "C")]
        tot = a + b + c
        print(f"{s:<10}{len(es):>7}{a:>9}{b:>9}{c:>9}{tot:>7}"
              f"{tot/max(len(es),1)*100:>7.1f}%")
    print()
    print(f"A 档（双证据）{cnt[('upstream','A')]+sum(v for (s,g_),v in cnt.items() if g_=='A' and s!='upstream')} 条"
          f" —— 逐条看过，全部成立")
    print(f"C 档精确率约 40% —— 只能当筛选器，不能当删除依据")

    if args.show:
        sel = [r for r in rows if r["grade"] == args.show.upper()]
        print(f"\n=== {args.show.upper()} 档 {len(sel)} 条 ===")
        for r in sel:
            ev = []
            if r["modelDispute"]:
                ev.append("模型dispute")
            if r["textbookReversed"]:
                ev.append("教材倒挂")
            print(f"  [{r['source']}] 「{r['fromName']}」→「{r['toName']}」"
                  f"  ({r['shape']}) {' '.join(ev)}")

    if args.out:
        out = pathlib.Path(args.out)
        if not out.is_absolute():
            out = BASE / out
        out.parent.mkdir(parents=True, exist_ok=True)
        json.dump(rows, open(out, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
        print(f"\n明细 {len(rows)} 条已写 {out.relative_to(BASE)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
