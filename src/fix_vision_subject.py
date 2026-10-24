#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
把视觉层记录里的 **subject 字段归一成图谱口径的英文码**。

为什么需要这一步
----------------
视觉层的 `subject` 字段有**两套口径**在打架：

- 图谱（`data/normalized/graph.json`）用的是**英文码**：math / physics /
  chemistry / biology
- 教材清单（`data/shanghai-textbooks.json`）用的是**中文名**：数学 / 物理 / …

写视觉层的时候顺手把清单里的中文名抄进去了，
下游 `vision_to_concepts_sh.py` 按图谱口径取候选集 ——
`by_subj.get("物理")` 是空的，**14 本物理书一本都没匹配上概念**，
而且不报错，只是静悄悄地全是 0。

这种错最难查：页面能开、数字看着正常，就是内容空的。
所以单独一个归一步骤，让口径只有一处说了算。

跑法：python3 src/fix_vision_subject.py
"""
from __future__ import annotations

import json
import pathlib
import sys

BASE = pathlib.Path(__file__).resolve().parent.parent
VFILE = BASE / "data" / "vision-pages-sh.jsonl"
STJ = BASE / "data" / "shanghai-textbooks.json"

SUBJ_EN = {"数学": "math", "物理": "physics", "化学": "chemistry",
           "生物": "biology", "科学": "science",
           "math": "math", "physics": "physics", "chemistry": "chemistry",
           "biology": "biology", "science": "science"}


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", default=str(VFILE))
    args = ap.parse_args()
    vfile = pathlib.Path(args.file)
    if not vfile.exists():
        print(f"没有 {vfile}")
        return 1
    book_subj = {}
    if STJ.exists():
        for b in json.load(open(STJ, encoding="utf-8"))["books"]:
            book_subj[b["bookId"]] = SUBJ_EN.get(b.get("subject", ""), b.get("subject", ""))

    lines = []
    fixed = 0
    total = 0
    for line in vfile.open(encoding="utf-8"):
        if not line.strip():
            continue
        r = json.loads(line)
        total += 1
        want = SUBJ_EN.get(r.get("subject", ""), r.get("subject", ""))
        # 清单优先 —— 清单是按 contentId 对上的，比书名可靠
        want = book_subj.get(r.get("book", ""), want)
        if r.get("subject") != want:
            r["subject"] = want
            fixed += 1
        lines.append(json.dumps(r, ensure_ascii=False))
    vfile.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"{total} 条记录，改了 {fixed} 条的学科字段")
    from collections import Counter
    c = Counter()
    for l in lines:
        c[json.loads(l).get("subject")] += 1
    print("学科分布：" + " · ".join(f"{k} {v}" for k, v in c.most_common()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
