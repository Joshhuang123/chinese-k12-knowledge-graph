#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
查 Milvus —— `optional/milvus/query_milvus.py`

朋友（Milvus 生态负责人）用这个项目来自学时，主要问三类问题：

    # 1. 「浮力」在教材里怎么讲的？        → 语义检索教材原文段落
    python3 optional/milvus/query_milvus.py "浮力"

    # 2. 只看人教版物理八下的             → 加过滤
    python3 optional/milvus/query_milvus.py "浮力" --edition 人教版 --book 8b

    # 3. 这个概念的前置是什么？           → 查先修关系
    python3 optional/milvus/query_milvus.py --prereq 浮力

    # 4. 精确查一个概念                   → 按名字过滤
    python3 optional/milvus/query_milvus.py --name 浮力

**为什么不能只有精确匹配**：
上游概念名大量是改写过的（「ATP（能量储存形式）」「DNA（遗传信息载体）」），
教材里根本不这么写 —— 精确字面匹配只覆盖 4.6%。
向量检索就是补这一段。
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import sys
import urllib.request

BASE = __import__("pathlib").Path(__file__).resolve().parent.parent.parent
MILVUS_HOST = os.environ.get("MILVUS_HOST", "localhost")
MILVUS_PORT = os.environ.get("MILVUS_PORT", "19530")
# 两种后端：lite（本地单文件，不需要 Docker）/ server（Standalone）
MILVUS_BACKEND = os.environ.get("MILVUS_BACKEND", "lite")
MILVUS_LITE_PATH = os.environ.get(
    "MILVUS_LITE_PATH", str(BASE / "data" / "milvus" / "kg_lite.db"))
EMBED_MODEL = os.environ.get("EMBED_MODEL", "bge-m3")
EMBED_DIMS = int(os.environ.get("EMBED_DIMS", "1024"))
EMBED_URL = os.environ.get("EMBED_URL", "http://localhost:11434/api/embed")


def connect():
    """连 Milvus。两种后端同一个接口。"""
    from pymilvus import MilvusClient
    if MILVUS_BACKEND == "lite":
        if not pathlib.Path(MILVUS_LITE_PATH).exists():
            print(f"缺 {MILVUS_LITE_PATH} —— 先跑 python3 optional/milvus/build_milvus.py")
            sys.exit(1)
        return MilvusClient(uri=MILVUS_LITE_PATH)
    return MilvusClient(uri=f"http://{MILVUS_HOST}:{MILVUS_PORT}")


def embed(text: str) -> list[float]:
    req = urllib.request.Request(
        EMBED_URL,
        data=json.dumps({"model": EMBED_MODEL, "input": [text]}).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.load(r)["embeddings"][0]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("query", nargs="?", help="想查什么")
    ap.add_argument("--name", help="按概念名精确查（查定义和教材位置）")
    ap.add_argument("--prereq", help="查这个概念的前置")
    ap.add_argument("--edition", help="过滤：人教版 / 沪教版")
    ap.add_argument("--book", help="过滤：册次码，如 8b")
    ap.add_argument("--subject", help="过滤：学科（physics / biology / math / chemistry）")
    ap.add_argument("--topk", type=int, default=5)
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    args = ap.parse_args()

    client = connect()

    # ── 查前置关系 ────────────────────────────────────
    if args.prereq:
        rows = client.query("kg_prereq",
                            filter=f'from_name like "%{args.prereq}%" '
                                   f'or to_name like "%{args.prereq}%"',
                            output_fields=["from_name", "to_name", "evidence"],
                            limit=30)
        if not args.json:
            print(f"「{args.prereq}」的先修关系（{len(rows)} 条）：")
            for r in rows:
                print(f"  {r['from_name']}  →  {r['to_name']}")
                if r.get("evidence"):
                    print(f"      理由：{r['evidence'][:80]}")
        else:
            print(json.dumps(rows, ensure_ascii=False, indent=1))
        return 0

    # ── 按概念名精确查 ────────────────────────────────
    if args.name:
        rows = client.query("kg_concept",
                            filter=f'name like "%{args.name}%"',
                            output_fields=["id", "name", "definition", "book_zh",
                                           "subject_zh", "grade", "importance"],
                            limit=10)
        if not args.json:
            print(f"概念「{args.name}」匹配 {len(rows)} 个：")
            for r in rows:
                print(f"\n  {r['name']}（{r.get('book_zh')}·{r.get('subject_zh')}）")
                if r.get("definition"):
                    print(f"    图谱定义：{r['definition'][:150]}")
        else:
            print(json.dumps(rows, ensure_ascii=False, indent=1))
        return 0

    if not args.query:
        ap.print_help()
        return 2

    # ── 语义检索教材原文 ──────────────────────────────
    filt = []
    if args.edition:
        filt.append(f'edition == "{args.edition}"')
    if args.book:
        filt.append(f'book == "{args.book}"')
    if args.subject:
        filt.append(f'subject == "{args.subject}"')
    expr = " and ".join(filt) if filt else ""

    v = embed(args.query)
    res = client.search("kg_textbook", data=[v], limit=args.topk,
                        output_fields=["seg_id", "text", "edition", "book",
                                       "subject", "page", "chapter", "concepts"],
                        filter=expr or None)
    hits = res[0] if res else []
    if not args.json:
        print(f"「{args.query}」在教材原文里最相关的 {len(hits)} 段"
              + (f"（过滤：{expr}）" if expr else "") + "：\n")
        for h in hits:
            e = h["entity"]
            meta = f"{e.get('edition')}·{e.get('book')} p{e.get('page')}"
            print(f"── {meta}  相似度 {h['distance']:.3f}")
            if e.get("chapter"):
                print(f"   {e['chapter']}")
            t = e.get("text", "").replace("\n", " ")
            print(f"   {t[:180]}")
            if e.get("concepts"):
                print(f"   命中概念：{', '.join(e['concepts'][:6])}")
            print()
    else:
        out = [{"score": h["distance"], **h["entity"]} for h in hits]
        print(json.dumps(out, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
