#!/usr/bin/env python3
"""
把模型在 dispute 字段里说的「上游这条边不是硬前置」落到具体边上，
再跟教材顺序对撞。

**为什么要做这一步**

盲测的 32 批输出里，每条知识点都带一个 `dispute` 字段 ——
模型对**上游数据集已有边**的异议。1898 条里有 135 条（7.1%）带异议。

但这个字段一直没人系统用过。两种形态：
  - 对象数组：直接点名边的两个端点（只有 9 条）
  - 字符串：「existing_prereq 里的 三角形的高 同理，是建立在三角形之上的
    后续性质，不能反过来当它的前置」—— 126 条，指名的是**概念名**

字符串那 126 条信息量最大也最可惜：模型是**逐条看了概念语义**给出的判断，
跟「教材顺序倒挂」是两条**互相独立**的证据来源。
两边指向同一批边，就不是「可能有点问题」，而是「有两个独立信号都认为它反了」。

## 跑法

```bash
python3 src/dispute_audit.py            # 汇总
python3 src/dispute_audit.py --show 30  # 逐条看
```
"""
import argparse
import glob
import json
import pathlib
import re
import sys
from collections import Counter, defaultdict

BASE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from nameindex import NameIndex, norm   # noqa: E402

LMM = BASE / "data" / "lmm-out"
COLLIDE = BASE / "data" / "normalized" / "order-collide.json"
GRAPH = BASE / "data" / "normalized" / "graph.json"

# 模型质疑上游边时用的措辞。归类用，不是硬匹配。
PATTERNS = [
    ("教学先后≠硬前置", r"先后顺序|教学顺序|是先教|排在.*前|之后发展|并列"),
    ("方向反了",       r"方向.{0,4}反|反了|不能反过来|是.*的(后续|产物|基础)"),
    ("不是唯一路径",   r"并列|同样能|照样|也能|不依赖|并不是硬|不是硬前置|不是必须"),
    ("上位概念当前置", r"是.{0,6}的性质|是.{0,6}的基础|上位|建立.{0,4}之上"),
    ("超出教材范围",   r"出自.{0,3}年级|不是这|用不上|用不到"),
]


def classify(text):
    tags = [name for name, pat in PATTERNS if re.search(pat, text)]
    return tags or ["未归类"]


def load_disputes():
    out = []
    # **不要只读 math-*。** 非数学的盲测也产出 dispute，
    # 而且生物 7 条、化学 1 条，说的都是「组成部分当前置」——
    # 跟数学发现的 ISSUE-12 是同一族，独立验证。
    for f in sorted(glob.glob(str(LMM / "*.json"))):
        for it in json.load(open(f, encoding="utf-8")):
            for d in it.get("dispute", []):
                out.append((it["id"], d))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--show", type=int, default=0)
    ap.add_argument("--out", help="把逐条明细写成 JSON")
    args = ap.parse_args()

    g = json.load(open(GRAPH, encoding="utf-8"))
    idx = NameIndex(g["nodes"])
    disputes = load_disputes()

    # 名字 → id 的最长匹配扫描表（只取长度 ≥3，太短的会满地误匹配）
    keys = sorted((k for k in idx.by_norm if len(k) >= 3),
                  key=len, reverse=True)

    def scan(text):
        """在 dispute 文本里找出提到的所有已知概念名。"""
        t = norm(text)
        hits, used = [], set()
        for k in keys:
            for m in re.finditer(re.escape(k), t):
                span = m.span()
                if any(span[0] < e and span[1] > s for s, e in used):
                    continue
                used.add(span)
                hits.append((k, m.start()))
                break
        return hits

    # 教材倒挂边
    rev = set()
    revname = {}
    if COLLIDE.exists():
        col = json.load(open(COLLIDE, encoding="utf-8"))
        for r in col["rows"]:
            if r["kind"] == "cross":
                rev.add((r["from"], r["to"]))
                revname[(r["from"], r["to"])] = (r["fromName"], r["toName"])

    # 1) 对象形态：直接点名
    obj_edges, str_items = [], []
    for item_id, d in disputes:
        if isinstance(d, dict) and d.get("from") and d.get("to"):
            obj_edges.append((d["from"], d["to"], item_id, d.get("reason", "")))
        else:
            txt = d if isinstance(d, str) else json.dumps(d, ensure_ascii=False)
            str_items.append((item_id, txt))

    # 2) 字符串形态：把提到的名字解析成 id，拼成被争议的边
    #
    # **一句话里提到多个概念时，不能把它们两两连边。**
    # 「existing_prereq 里的 连加 与 连减 是教学先后顺序」这句里有两个概念，
    # 扫出来就会连出「连加→连减」和「连减→连加」两条，其中一条是自环。
    # 277 条里 75 条是这么造出来的伪边（70 条 from==to 自环）——
    # 数字看着像「模型指认了 277 条边」，实际只有 202 条是真的。
    #
    # 正确做法：**只把句子里出现的概念，跟该条知识点连**。
    # 「existing_prereq 里的 X」里 X 才是被质疑的前置。
    named, unresolved = [], 0
    for item_id, txt in str_items:
        # 只取「existing_prereq 里的 …」后面那一句里的概念 ——
        # 争议指向的是**上游已有的边**，也就是这条知识点的前置。
        m = re.search(r"existing_prereq\s*里的\s*([^；;。]+)", txt)
        scope = m.group(1) if m else txt
        for k, _ in scan(scope):
            st, nid, cands, how = idx.resolve(k)
            if nid is None:
                unresolved += 1
                continue
            if nid == item_id:            # 自环，扫出来就是伪边
                continue
            named.append(((nid, item_id), item_id, k, txt, how))

    all_edges = set()
    for f, t, _i, _r in obj_edges:
        all_edges.add((f, t))
    for (f, t), _i, _k, _x, _h in named:
        all_edges.add((f, t))

    both = all_edges & rev
    only_dispute = all_edges - rev
    only_rev = rev - all_edges

    print("=" * 58)
    print("模型 dispute × 教材顺序倒挂")
    print("=" * 58)
    print(f"dispute 条目 {len(disputes)} 条"
          f"（对象 {len(obj_edges)} / 文字 {len(str_items)}）")
    print(f"从文字里解析出的「被争议边」{len(all_edges)} 条"
          f"（名字解析不到 {unresolved} 处）")
    print()
    print(f"两条独立证据都指向 : {len(both)}")
    print(f"只有模型指出       : {len(only_dispute)}")
    print(f"只有教材倒挂       : {len(only_rev)}")

    # 归类
    cats = Counter()
    for item_id, txt in str_items:
        for t in classify(txt):
            cats[t] += 1
    print("\n模型质疑的措辞归类：")
    for k, v in cats.most_common():
        print(f"  {v:4}  {k}")

    if both:
        print(f"\n=== 两条独立证据都指向的边（{len(both)} 条）===")
        for e in sorted(both):
            n = revname.get(e)
            if n:
                print(f"  「{n[0]}」 →「{n[1]}」")

    if args.out:
        rows = []
        for (f, t), item_id, k, txt, how in named:
            rows.append({
                "from": f, "to": item_id,
                "fromName": idx.node_of.get(f, {}).get("name", f),
                "toName": idx.node_of.get(item_id, {}).get("name", item_id),
                "matchedName": k, "how": how,
                "textbookReversed": (f, item_id) in rev,
                "tags": classify(txt),
                "text": txt,
            })
        for f, t, item_id, reason in obj_edges:
            rows.append({
                "from": f, "to": t,
                "fromName": idx.node_of.get(f, {}).get("name", f),
                "toName": idx.node_of.get(t, {}).get("name", t),
                "matchedName": None, "how": "object",
                "textbookReversed": (f, t) in rev,
                "tags": ["结构化指认"],
                "text": reason,
            })
        outp = pathlib.Path(args.out)
        if not outp.is_absolute():
            outp = BASE / outp
        outp.parent.mkdir(parents=True, exist_ok=True)
        json.dump(rows, open(outp, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
        print(f"\n明细 {len(rows)} 条已写 {outp.relative_to(BASE)}")

    if args.show:
        print(f"\n=== 模型指出的边（前 {args.show}）===")
        shown = 0
        for (f, t), item_id, k, txt, how in named:
            if shown >= args.show:
                break
            nf = idx.node_of.get(f, {}).get("name", f)
            nt = idx.node_of.get(item_id, {}).get("name", item_id)
            mark = " ★教材也倒挂" if (f, item_id) in rev else ""
            print(f"  「{nf}」→「{nt}」{mark}")
            print(f"     争议：{txt[:150]}")
            shown += 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
