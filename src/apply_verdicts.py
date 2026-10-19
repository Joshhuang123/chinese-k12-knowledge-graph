#!/usr/bin/env python3
"""
把 M3 逐条裁决的**A 档（双证据高置信）**落成可执行的修正。

## 为什么只落 A 档

裁决 341 条争议边（`/tmp/dispute-verdict2.md`）的结论是 96.5% 真错，
但证据强度分两档：

- **A 档 19 条**：模型指认 **且** 教材顺序倒挂，两条独立证据同时指向
  → 可以直接改
- **B 档 310 条**：只有模型 dispute 一条证据
  → 标为「已确认可疑」，但**不改方向** ——
  拿一条证据就改 310 条边，跨过了「宁可少抽，不抽错」的线

B 档那些边在页面上会有「可疑」徽标（`src/flag_suspect.py` 出的那批），
但处置要等人复核。

## 处置有三种

| 处置 | 做什么 |
|---|---|
| 反向 | 剔除原边，加入反向边（来源标 fix） |
| 删除 | 剔除原边，不加反向 |
| 重指 | 剔除原边，指向另一个节点（本次没有） |

**上游数据本身不动**（`data/raw/` 只读，铁律）——
剔的是**页面用的派生边集**，并且每一笔都记在
`selfbuilt-edges.json` 的 `fixes` 字段里，来路清楚。

## 跑法

```bash
python3 src/apply_verdicts.py                       # 汇总
python3 src/apply_verdicts.py --apply               # 写 data/normalized/confirmed-wrong.json
"""
import argparse
import json
import pathlib
import re
import sys

BASE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from nameindex import NameIndex   # noqa: E402

GRAPH = BASE / "data" / "normalized" / "graph.json"
VERDICT = pathlib.Path("/tmp/dispute-verdict2.md")
OUT = BASE / "data" / "normalized" / "confirmed-wrong.json"


def parse_a_danzhang(md):
    """从裁决报告的 A 档表格里抽出 (fromName, toName, 处置)。"""
    out = []
    # 表格行：| 24 | 根据水解产物对糖类进行分类 → 单糖 | 反向 |
    for m in re.finditer(r"^\|\s*(\d+)\s*\|\s*(.+?)\s*→\s*(.+?)\s*\|\s*(\S+)\s*\|$",
                         md, re.M):
        out.append((m.group(2).strip(), m.group(3).strip(), m.group(4).strip()))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="写出 confirmed-wrong.json")
    args = ap.parse_args()

    if not VERDICT.exists():
        print(f"找不到裁决报告 {VERDICT}")
        return 1
    md = VERDICT.read_text(encoding="utf-8")
    # 只取 A 档那一节
    i = md.find("### A 档")
    j = md.find("### B 档", i)
    sec = md[i:j] if i >= 0 and j > i else md
    rows = parse_a_danzhang(sec)
    print(f"A 档条目 {len(rows)} 条")

    g = json.load(open(GRAPH, encoding="utf-8"))
    idx = NameIndex(g["nodes"])

    resolved, unresolved = [], []
    for fn, tn, action in rows:
        sf, fid, cf, hf = idx.resolve(fn)
        st, tid, ct, ht = idx.resolve(tn)
        if fid is None or tid is None:
            unresolved.append((fn, tn, action, "名字解析不到"))
            continue
        resolved.append({
            "from": fid, "to": tid,
            "fromName": idx.node_of[fid].get("name", fid),
            "toName": idx.node_of[tid].get("name", tid),
            "action": action,
            "fromMatch": hf, "toMatch": ht,
            "grade": "A", "basis": "模型 dispute + 教材顺序倒挂（两条独立证据）",
        })

    print(f"解析成功 {len(resolved)}，失败 {len(unresolved)}")
    for fn, tn, a, why in unresolved:
        print(f"  ✗ 「{fn}」→「{tn}」{a}：{why}")
    print()
    by = {}
    for r in resolved:
        by[r["action"]] = by.get(r["action"], 0) + 1
    print("处置分布：", by)
    for r in resolved:
        print(f"  {r['action']:<4} 「{r['fromName']}」→「{r['toName']}」")

    if args.apply:
        out = {
            "_comment": "M3 逐条裁决的 A 档（双证据高置信）。"
                        "只在 build_viz 里用于剔除/反向**派生边集**，"
                        "上游数据本身不动。",
            "verdicts": resolved,
        }
        OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1),
                       encoding="utf-8")
        print(f"\n已写 {OUT.relative_to(BASE)}（{len(resolved)} 条）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
