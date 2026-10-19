#!/usr/bin/env python3
"""
把数学知识点切成批次，供盲测重建先修关系用（见 docs/probe-llm-prereq.md）。

为什么不入库：这是 graph.json 的派生产物，760 KB，切法随时会改。
真要固化一个切法，固化的是脚本不是切好的片。

每条给四样东西，缺一不可：
    id / name          节点身份
    book               册次，模型需要知道它出现在哪个阶段
    definition         数据集自己的定义。**不给定义 = 让模型猜教材内容**，
                       那测出来的是模型的教材记忆，不是先修推理能力
    existing_prereq    数据集已记的先修（可能为空）
                       给了不等于让它抄 —— 要不要认同由它自己判，
                       但空着不给，就永远分不清「数据集没记」和「模型没想到」

排序按 (册序, ch, s)，跟教材一致：同一批里前后挨着的知识点
本来就有天然的先后关系，一次输入里能互相看见，比打散喂更接近真实学习顺序。
"""
import json
import pathlib
import sys
from collections import defaultdict

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import books
import order as order_mod

BASE = pathlib.Path(__file__).resolve().parent.parent
GRAPH = BASE / "data" / "normalized" / "graph.json"
OUT = BASE / "data" / "lmm-batches"
SIZE = 60

SUBJ = sys.argv[1] if len(sys.argv) > 1 else "math"
# 习题节点没有先修可言（它是练习不是知识），模型对它们只能编。
# 要过就是 1898 个里的 474 个纯噪声。
SKIP_LABELS = {"Exercise", "Book", "Chapter", "Section"}


def main():
    g = json.loads(GRAPH.read_text())
    nodes = {n["id"]: n for n in g["nodes"]}
    order = order_mod.Order(g["nodes"], g["edges"])

    prereq_of = defaultdict(list)
    for e in g["edges"]:
        if e["type"] == "prerequisites_for":
            prereq_of[e["to"]].append({
                "from": e["from"], "to": e["to"], "type": e["type"],
                "fromName": nodes.get(e["from"], {}).get("name", "?"),
                "toName": nodes.get(e["to"], {}).get("name", "?"),
                "crossBook": e.get("crossBook"),
                "evidence": e.get("evidence"),
                "subject": e.get("subject"),
            })

    cand = [n for n in g["nodes"]
            if n["subject"] == SUBJ and n["label"] not in SKIP_LABELS]
    # 序位先算成字典再排：放进排序键里的话每次比较都要重扫一遍 873 个单元，
    # O(n log n × 873)，1,898 个点能跑几分钟。
    seqpos = {n["id"]: order.seq_pos(n["id"])[0] for n in cand}
    cand.sort(key=lambda n: (books.RANK[n["book"]],
                             seqpos[n["id"]] if seqpos[n["id"]] is not None else 10**9,
                             n["id"]))

    OUT.mkdir(parents=True, exist_ok=True)
    batches = [cand[i:i + SIZE] for i in range(0, len(cand), SIZE)]
    for bi, batch in enumerate(batches, 1):
        rows = [{
            "id": n["id"],
            "name": n["name"],
            "book": n["bookZh"],
            "definition": (n.get("props", {}).get("definition") or "")[:160],
            "existing_prereq": prereq_of.get(n["id"], []),
        } for n in batch]
        p = OUT / f"{SUBJ}-{bi:02d}.json"
        p.write_text(json.dumps(rows, ensure_ascii=False, indent=1))

    labels = defaultdict(int)
    for n in cand:
        labels[n["label"]] += 1
    print(f"{SUBJ} 候选 {len(cand)} 个（跳过 "
          f"{ {k: sum(1 for x in g['nodes'] if x['subject'] == SUBJ and x['label'] == k) for k in SKIP_LABELS} }）")
    print(f"  明细 {dict(labels)}")
    print(f"  切成 {len(batches)} 批 × ≤{SIZE} → {OUT.relative_to(BASE)}")


if __name__ == "__main__":
    main()
