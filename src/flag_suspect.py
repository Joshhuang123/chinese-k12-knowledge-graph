#!/usr/bin/env python3
"""
给上游先修边打「可疑」标记。

## 为什么不直接删

上游数据是 K12-KGraph（CC BY-NC-SA 4.0）的事实来源。
本项目的铁律是「不静默改上游数据」：发现问题逐条记 known-issues，
原件只读。所以这个脚本**不删任何边**，只标。

而且删了也没地方删 —— 上游数据在 `data/raw/` 里是只读的，
我们只持有派生副本。真正的清理要么走上游 issue，要么在自己这层做覆盖。

## 标记的用处

1. 诊断层读到这条边时，明确告诉用户「这条前置边本身可疑」，
   而不是拿一条可能反了的边去推「你卡在哪」。
2. 页面上给这条边一个标记（见 build_viz）。
3. known-issues 里有一份可核的清单。

## 六条检测规则

| 规则 | 判据 | 为什么可疑 |
|---|---|---|
| 册序倒挂 | 前置所在册比后继更晚 | 学后学内容要先修更晚册的内容 |
| 下位当前置 | 前置名里含后继名 | 前置是后继的具体化/属性/要素 |
| 重复节点 | 两端名字归一后相同 | 同一个概念建了两个节点 |
| 空名占位 | 节点名形如 `node_12` | 明显的占位符 |
| 应用/实例当前置 | 前置名含「应用/举例/实例/例子」 | 举例不是前提 |
| 方法当前置 | 前置名以「方法/做法/步骤/过程」结尾 | 手段不是前提 |

**每条规则单独成立才算命中** —— 命中越多条越可疑，
但任何一条都只是「值得看一眼」，不是「确定错」。
上游的证据常常只是正文里的一句话（ISSUE-09），不是前置理由。

## 跑法

```bash
python3 src/flag_suspect.py
python3 src/flag_suspect.py --out data/normalized/suspect-edges.json
"""
import argparse
import json
import pathlib
import re
import sys
from collections import Counter, defaultdict

BASE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from nameindex import norm   # noqa: E402
from books import RANK       # noqa: E402

GRAPH = BASE / "data" / "normalized" / "graph.json"
COLLIDE = BASE / "data" / "normalized" / "order-collide.json"

APP_WORDS = ("应用", "举例", "实例", "例子", "举例说明", "例题")
METHOD_TAIL = ("方法", "做法", "步骤", "过程", "技巧")
PLACEHOLDER = re.compile(r"^(node|Node|NODE)_\d+$")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out")
    args = ap.parse_args()

    g = json.load(open(GRAPH, encoding="utf-8"))
    nodes = {n["id"]: n for n in g["nodes"]}

    # 册序倒挂：复用 collide_order 的结果
    reversed_pairs = set()
    if COLLIDE.exists():
        col = json.load(open(COLLIDE, encoding="utf-8"))
        for r in col["rows"]:
            if r["kind"] == "cross":
                reversed_pairs.add((r["from"], r["to"]))

    rows = []
    for e in g["edges"]:
        if e["type"] != "prerequisites_for":
            continue
        f, t = e["from"], e["to"]
        nf, nt = nodes.get(f, {}), nodes.get(t, {})
        name_f, name_t = nf.get("name", ""), nt.get("name", "")
        hits = []
        bf, bt = nf.get("book"), nt.get("book")
        # **册序倒挂和教材顺序倒挂是同一条规则**（都基于 RANK 册序），
        # 分成两条记会让「命中 ≥2 条规则」这个门槛失效 ——
        # 一条规则被数了两遍，凭空凑出双证据。
        # 真正的独立证据只有两类：**教材顺序** 和 **名字的字面结构**。
        if (bf and bt and RANK.get(bf, 0) > RANK.get(bt, 0)) or \
                (f, t) in reversed_pairs:
            hits.append("册序倒挂")
        a, b = norm(name_f), norm(name_t)
        if len(b) >= 2 and b in a and a != b:
            hits.append("下位当前置")
        if a and a == b:
            hits.append("重复节点")
        if PLACEHOLDER.match(name_f.strip()) or PLACEHOLDER.match(name_t.strip()):
            hits.append("空名占位")
        if any(w in name_f for w in APP_WORDS):
            hits.append("应用/实例当前置")
        if name_f.rstrip().endswith(METHOD_TAIL):
            hits.append("方法当前置")
        if hits:
            rows.append({
                "from": f, "to": t,
                "fromName": name_f, "toName": name_t,
                "fromBook": nf.get("bookZh", ""), "toBook": nt.get("bookZh", ""),
                # level = 独立证据源的个数：
            #   1 = 教材顺序（或字面）单证据
            #   2 = 教材顺序 + 字面（两个独立来源）
            # 3 = 三类证据
            "hits": hits,
            "level": (1 if "册序倒挂" in hits else 0) +
                     (1 if any(h in hits for h in
                               ("下位当前置", "方法当前置",
                                "应用/实例当前置", "重复节点",
                                "空名占位")) else 0) +
                     (1 if "模型dispute" in hits else 0),
                "evidence": e.get("evidence", "") or "",
            })

    rows.sort(key=lambda r: (-r["level"], r["fromName"]))
    print("=" * 58)
    print("上游先修边 · 可疑标记")
    print("=" * 58)
    print(f"上游先修边 {sum(1 for e in g['edges'] if e['type']=='prerequisites_for')} 条，"
          f"标出可疑 {len(rows)} 条 ({len(rows)/3703*100:.1f}%)")
    print()
    print("按命中规则：")
    c = Counter(h for r in rows for h in r["hits"])
    for k, v in c.most_common():
        print(f"  {v:5}  {k}")
    print()
    print("按证据条数（命中越多越可疑）：")
    lv = Counter(r["level"] for r in rows)
    for k in sorted(lv, reverse=True):
        print(f"  {lv[k]:5}  命中 {k} 条")
    print()
    print("命中 ≥2 条的（前 15 条，这些最该先看）：")
    for r in [x for x in rows if x["level"] >= 2][:15]:
        print(f"  「{r['fromName']}」({r['fromBook']}) →"
              f"「{r['toName']}」({r['toBook']})  {'/'.join(r['hits'])}")

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
