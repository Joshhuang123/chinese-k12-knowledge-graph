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
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import books
from collections import Counter, defaultdict

BASE = pathlib.Path(__file__).resolve().parent.parent
RAW = BASE / "data" / "raw" / "subject_specific_KG"
OUT = BASE / "data" / "normalized"

# 册次编码 → (学段, grade, 显示名) 与全局顺序，统一由 books.py 提供。
# 原来这份映射就写在本文件里，用 list(BOOKS) 的插入顺序当排名，
# 导致「九年级」(整年本) 排在「九上」之前 —— 单学科看不出来，
# 引入跨学科边之后会大面积误报册次倒挂。
BOOKS = books.BOOKS
BOOK_RANK = books.RANK
BOOK_ORDER = books.GLOBAL_ORDER

SUBJECT_ZH = {"math": "数学", "physics": "物理", "chemistry": "化学", "biology": "生物"}


def split_id(node_id):
    """math_5a_rjb_cpt1 → ('math', '5a')"""
    parts = node_id.split("_")
    return parts[0], parts[1]


def build_node(n, subject):
    _, book = split_id(n["id"])
    try:
        stage, grade, book_zh = books.lookup(book)
    except KeyError:
        # 未登记的册次不能静默塞进数据里 —— 那会让后面所有按册次的统计失真
        sys.exit(f"节点 {node_id} 的册次 {book!r} 未登记，见 src/books.py")
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
        "bookRank": books.rank(book),
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
        "bookReversed": books.is_reversed(s_book, d_book,
                                          src.split("_")[0] == dst.split("_")[0]),
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

    all_by_id = {}
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
        all_by_id.update(by_id)

        pre = [e for e in edges if e["type"] == "prerequisites_for"]
        report[subject] = {
            "nodes": len(nodes),
            "edges": len(edges),
            "books": sorted({n["book"] for n in nodes}, key=books.rank),
            "nodeLabels": dict(Counter(n["label"] for n in nodes)),
            "edgeTypes": dict(Counter(e["type"] for e in edges)),
            "prereqEdges": len(pre),
            "prereqWithEvidence": sum(1 for e in pre if e["evidence"]),
            "prereqCrossBook": sum(1 for e in pre if e["crossBook"]),
            "prereqBookReversed": sum(1 for e in pre if e["bookReversed"]),
            "rawEdgeSchemas": dict(stats),
        }

    # ── global_KG：跨学科章节进阶线 ──
    # 这个目录以前从来没被任何代码打开过。里面 187 条 leads_to 边
    # （数学某章 → 物理某章）整个没进管线，而 README 三处并列印着
    # global_KG 的 23,278 和合计的 23,091，却没人解释这个差。
    #
    # 它们全是 Chapter 之间的章节衔接，不是先修边：不影响 DAG、不参与
    # traceBack、build_viz 只画 prerequisites_for 所以也不进画面。
    # 补进来是纯数据完整性修复，视觉零变化。
    all_ids = set(all_by_id)
    gp = RAW.parent / "global_KG" / "edges.json"
    gstats = Counter()
    if gp.exists():
        graw = json.load(open(gp, encoding="utf-8"))
        # global_KG 的边绝大多数和 subject_specific 重叠 —— 真正缺的只有一小部分。
        # 不去重会把 23,091 条边全部复制一份（图文件从 13.4MB 涨到 19.6MB 就是这么来的）。
        seen = {(e["from"], e["to"], e["type"]) for e in all_edges}
        for e in graw:
            src, dst = e.get("source"), e.get("target")
            if not src or not dst:
                gstats["dropped_no_endpoint"] += 1
                continue
            if src not in all_ids or dst not in all_ids:
                gstats["dropped_unknown_endpoint"] += 1
                continue
            if (src, dst, e["type"]) in seen:
                gstats["already_present"] += 1
                continue
            seen.add((src, dst, e["type"]))
            _emit(all_edges, gstats, src, dst, None, e["type"], "",
                  None, None, all_by_id, src.split("_")[0])
            gstats["added"] += 1
        gstats["raw_total"] = len(graw)
    else:
        print(f"  跳过 global_KG: {gp} 不存在")

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
    all_books = set()
    for s, r in report.items():
        tn += r["nodes"]; te += r["edges"]; tp += r["prereqEdges"]
        all_books |= set(r["books"])
        print(f"{SUBJECT_ZH[s]:<12}{r['nodes']:>7}{r['edges']:>7}{len(r['books']):>6}"
              f"{r['prereqEdges']:>8}{r['prereqWithEvidence']:>8}{r['prereqCrossBook']:>7}"
              f"{r['prereqBookReversed']:>9}")
    print("-" * 78)
    # 册次别再写死 48：48 是各学科册次相加，跨学科共用的册次代码被重复计了
    # （必修一/必修二/选必一二三 四科共用）。真正不同的教材只有 25 本。
    # 两个数都对，口径不同，所以两个都打出来，免得再被当成「册次就是 48」。
    tb = sum(len(r["books"]) for r in report.values())
    # global_KG 补进来的跨学科边不属于任何一科，别让合计行少算它们
    print(f"{'学科合计':<10}{tn:>7}{te:>7}{tb:>6}{tp:>8}   ← 册次是各学科相加")
    if gstats.get("added"):
        print(f"{'+跨学科':<10}{'':>7}{gstats['added']:>7}")
        print(f"{'总计':<10}{tn:>7}{te + gstats['added']:>7}"
              f"{'':>6}{'':>8}   ← 与 global_KG/edges.json 的 {gstats['raw_total']:,} 条一致")
    print(f"{'(去重)':<12}{'':>7}{'':>7}{len(all_books):>6}{'':>8}   ← 实际不同的教材本数")
    print()
    # 原来这里想过滤掉 dropped_no_endpoint，但那个 Counter 的 key 是学科名，
    # 永远不等于 'dropped_no_endpoint' —— 过滤器形同虚设，真丢了边也不会提示。
    # 改成直接从 schema 计数里取，不再假装在过滤。
    print("原始边 schema 拆分:", {k: sum(d["rawEdgeSchemas"].get(k, 0) for d in report.values())
                                   for k in ("schema_A", "schema_B", "schema_C", "schema_D")})
    if gstats:
        print(f"global_KG 补充: 读入 {gstats['raw_total']} 条，新增跨学科边 "
              f"新增 {gstats['added']} 条（已存在 {gstats['already_present']} 条，"
              f"丢弃 {gstats['dropped_no_endpoint'] + gstats['dropped_unknown_endpoint']} 条）")
    print(f"输出: {OUT/'graph.json'}")
    print(f"      {(OUT/'graph.json').stat().st_size/1024/1024:.1f} MB")


if __name__ == "__main__":
    main()
