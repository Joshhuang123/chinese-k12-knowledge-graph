#!/usr/bin/env python3
"""
把 K12-KGraph 的四科原始图归一化成一种边 schema。

为什么要归一化：原数据里边的 JSON 结构有四种并存的样子

  A 2634 条  {source, source_name, target, target_name, type}
  B 1529 条  A + properties
  C  635 条  {source, source_stem, target_name_to_ids, type}     ← 一对多
  D  475 条  {source, source_stem, target, target_name, type}

C 那种是「一道习题考多个概念」：边只有一条，目标是数组。
不展开就没法建反向索引、没法做入度统计、没法画图。

输出 data/normalized/graph.json（全学科合并）与每科一份的本科文件。

数据来源: K12-KGraph (arXiv:2605.09635) · PKU-DCAI
许可: CC BY-NC-SA 4.0 — 署名 + 相同方式共享 + 非商用
"""
import json
import pathlib
from collections import Counter, defaultdict

BASE = pathlib.Path(__file__).resolve().parent.parent
RAW = BASE / "data" / "raw" / "subject_specific_KG"
OUT = BASE / "data" / "normalized"

# 册次编码 → (学段, 年级, 显示名)
BOOKS = {
    "1a": ("小学", 1, "一上"), "1b": ("小学", 1, "一下"),
    "2a": ("小学", 2, "二上"), "2b": ("小学", 2, "二下"),
    "3a": ("小学", 3, "三上"), "3b": ("小学", 3, "三下"),
    "4a": ("小学", 4, "四上"), "4b": ("小学", 4, "四下"),
    "5a": ("小学", 5, "五上"), "5b": ("小学", 5, "五下"),
    "6a": ("小学", 6, "六上"), "6b": ("小学", 6, "六下"),
    "7a": ("初中", 7, "七上"), "7b": ("初中", 7, "七下"),
    "8a": ("初中", 8, "八上"), "8b": ("初中", 8, "八下"),
    "9":  ("初中", 9, "九年级"), "9a": ("初中", 9, "九上"), "9b": ("初中", 9, "九下"),
    "bx1": ("高中", 10, "必修一"), "bx2": ("高中", 11, "必修二"), "bx3": ("高中", 12, "必修三"),
    "xzxbx1": ("高中", 11, "选必一"), "xzxbx2": ("高中", 12, "选必二"), "xzxbx3": ("高中", 12, "选必三"),
}
BOOK_ORDER = list(BOOKS)          # 教材的自然顺序
BOOK_RANK = {b: i for i, b in enumerate(BOOK_ORDER)}

SUBJECT_ZH = {"math": "数学", "physics": "物理", "chemistry": "化学", "biology": "生物"}


def split_id(node_id):
    """math_5a_rjb_cpt1 → ('math', '5a')"""
    parts = node_id.split("_")
    return parts[0], parts[1]


def build_node(n, subject):
    _, book = split_id(n["id"])
    stage, grade, book_zh = BOOKS.get(book, ("未知", 0, book))
    return {
        "id": n["id"],
        "name": n.get("name") or "",
        "label": n.get("label"),
        "subject": subject,
        "subjectZh": SUBJECT_ZH[subject],
        "book": book,
        "bookZh": book_zh,
        "stage": stage,
        "grade": grade,
        "bookRank": BOOK_RANK.get(book, 99),
        "props": n.get("properties") or {},
    }


def normalize_edges(raw_edges, nodes_by_id, subject):
    """四种 schema → 一种。每条边都带上教材原文引用（如果有）。"""
    out = []
    stats = Counter()
    for e in raw_edges:
        etype = e.get("type")
        props = e.get("properties") or {}
        evidence = props.get("evidence") or props.get("reason") or props.get("relations") or ""
        # 原始边的 source 端可能是习题，没有 name 只有题干
        src = e.get("source")
        src_name = e.get("source_name") or nodes_by_id.get(src, {}).get("name", "")
        src_stem = e.get("source_stem", "")

        # ── schema C：一对多，展开 ──
        targets = e.get("target_name_to_ids")
        if targets is not None:
            for t in targets:
                _emit(out, stats, src, t.get("target"), t.get("target_name", ""),
                      etype, evidence, src_name, src_stem, nodes_by_id, subject)
            stats["schema_C"] += 1
            continue

        _emit(out, stats, src, e.get("target"), e.get("target_name", ""),
              etype, evidence, src_name, src_stem, nodes_by_id, subject)
        if "properties" in e:
            stats["schema_B"] += 1
        elif "source_stem" in e:
            stats["schema_D"] += 1
        else:
            stats["schema_A"] += 1
    return out, stats


def _emit(out, stats, src, dst, dst_name, etype, evidence, src_name, src_stem,
          nodes_by_id, subject):
    if not src or not dst:
        stats["dropped_no_endpoint"] += 1
        return
    s_book = split_id(src)[1]
    d_book = split_id(dst)[1]
    out.append({
        "from": src,
        "to": dst,
        "type": etype,
        "fromBook": s_book,
        "toBook": d_book,
        "crossBook": s_book != d_book,
        # 教材顺序倒挂：先修知识首次出现得比后继更晚。这不是错误（教材会回顾旧概念），
        # 但值得单独标出来供人核对。真正的硬错误是成环，见 validate.py。
        "bookReversed": BOOK_RANK.get(s_book, 99) > BOOK_RANK.get(d_book, 99),
        "fromName": src_name,
        "toName": dst_name or nodes_by_id.get(dst, {}).get("name", ""),
        "stem": src_stem,
        "evidence": evidence,
        "subject": subject,
    })


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    all_nodes, all_edges = [], []
    report = {}

    for subject in ["math", "physics", "chemistry", "biology"]:
        p = RAW / f"{subject}.json"
        if not p.exists():
            print(f"  跳过 {subject}: 文件不存在")
            continue
        raw = json.load(open(p, encoding="utf-8"))
        nodes = [build_node(n, subject) for n in raw["nodes"]]
        by_id = {n["id"]: n for n in nodes}
        edges, stats = normalize_edges(raw["edges"], by_id, subject)

        all_nodes += nodes
        all_edges += edges

        pre = [e for e in edges if e["type"] == "prerequisites_for"]
        report[subject] = {
            "nodes": len(nodes),
            "edges": len(edges),
            "books": sorted({n["book"] for n in nodes}, key=lambda b: BOOK_RANK.get(b, 99)),
            "nodeLabels": dict(Counter(n["label"] for n in nodes)),
            "edgeTypes": dict(Counter(e["type"] for e in edges)),
            "prereqEdges": len(pre),
            "prereqWithEvidence": sum(1 for e in pre if e["evidence"]),
            "prereqCrossBook": sum(1 for e in pre if e["crossBook"]),
            "prereqBookReversed": sum(1 for e in pre if e["bookReversed"]),
            "rawEdgeSchemas": dict(stats),
        }

    # 反向索引：被谁依赖
    dependents = defaultdict(list)
    for e in all_edges:
        dependents[e["to"]].append(e["from"])

    for n in all_nodes:
        n["prereqCount"] = sum(
            1 for e in all_edges
            if e["to"] == n["id"] and e["type"] == "prerequisites_for")

    graph = {
        "meta": {
            "name": "中文课程知识图谱（归一化版）",
            "source": "K12-KGraph · arXiv:2605.09635 · PKU-DCAI",
            "sourceLicense": "CC BY-NC-SA 4.0",
            "note": "原始数据版权归原作者，本文件为归一化再发布，同样以 CC BY-NC-SA 4.0 提供",
            "nodeCount": len(all_nodes),
            "edgeCount": len(all_edges),
        },
        "nodes": all_nodes,
        "edges": all_edges,
    }
    (OUT / "graph.json").write_text(json.dumps(graph, ensure_ascii=False), encoding="utf-8")
    (OUT / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2),
                                     encoding="utf-8")

    # ── 控制台报告 ──
    print("=" * 78)
    print(f"{'学科':<12}{'节点':>7}{'边':>7}{'册次':>6}{'先修边':>8}{'带出处':>8}{'跨册':>7}{'册次倒挂':>9}")
    print("-" * 78)
    tn = te = tp = 0
    for s, r in report.items():
        tn += r["nodes"]; te += r["edges"]; tp += r["prereqEdges"]
        print(f"{SUBJECT_ZH[s]:<12}{r['nodes']:>7}{r['edges']:>7}{len(r['books']):>6}"
              f"{r['prereqEdges']:>8}{r['prereqWithEvidence']:>8}{r['prereqCrossBook']:>7}"
              f"{r['prereqBookReversed']:>9}")
    print("-" * 78)
    print(f"{'合计':<12}{tn:>7}{te:>7}{48:>6}{tp:>8}")
    print()
    print("原始边 schema 拆分:", {k: v for k, v in
          Counter({s: d["rawEdgeSchemas"].get("schema_A", 0) for s, d in report.items()}
                  ).items() if k != "dropped_no_endpoint"})
    print(f"输出: {OUT/'graph.json'}")
    print(f"      {(OUT/'graph.json').stat().st_size/1024/1024:.1f} MB")


if __name__ == "__main__":
    main()
