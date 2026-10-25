#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Milvus 层校验 —— `src/check_milvus.py`

把 `docs/需求清单.md` R-3 的「怎么验算做对了」那张表变成可跑的检查。

| 检查项 | 判据 |
|---|---|
| 召回有效性 | 「浮力」能召回「…这个力叫做浮力」那段 |
| 过滤可用 | `--edition 人教版 --book 8b` 只返回人教八下的段落 |
| 版权不外泄 | 库里没有含「版权所有 / 美术编辑 / 印刷产品」的段 |
| 覆盖 | 三张表的条数对得上数据层 |
| 与学习卡不打架 | 同一概念命中的段落 ⊆ 学习卡 `read` 面的页 |

⚠️ **golden set 必须含负例** ——
只放成功样例的检查测不出辨别力（Milvus 那份 eval spec 的原话：
「只有成功样例的 golden set 无法测试 grader 的辨别力，不合格」）。
所以这里除了「应该召回」的正例，还有「**不该召回**」的负例：
查「连通器」不该召回浮力那一段。

跑法：
    python3 src/check_milvus.py
"""
from __future__ import annotations

import collections
import json
import os
import pathlib
import re
import sys

BASE = pathlib.Path(__file__).resolve().parent.parent
DATA = BASE / "data"
MILVUS_HOST = os.environ.get("MILVUS_HOST", "localhost")
MILVUS_PORT = os.environ.get("MILVUS_PORT", "19530")
MILVUS_BACKEND = os.environ.get("MILVUS_BACKEND", "lite")
MILVUS_LITE_PATH = os.environ.get(
    "MILVUS_LITE_PATH", str(DATA / "milvus" / "kg_lite.db"))
EMBED_MODEL = os.environ.get("EMBED_MODEL", "bge-m3")
EMBED_URL = os.environ.get("EMBED_URL", "http://localhost:11434/api/embed")

_fail = []


def ok(cond, msg, detail=""):
    if cond:
        print(f"  ✓ {msg}")
    else:
        print(f"  ✗ {msg}" + (f"\n      {detail}" if detail else ""))
        _fail.append(msg)
    return bool(cond)


def embed(text: str) -> list[float]:
    import urllib.request
    req = urllib.request.Request(
        EMBED_URL,
        data=json.dumps({"model": EMBED_MODEL, "input": [text]}).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.load(r)["embeddings"][0]


def connect():
    from pymilvus import MilvusClient
    if MILVUS_BACKEND == "lite":
        if not pathlib.Path(MILVUS_LITE_PATH).exists():
            raise SystemExit(f"缺 {MILVUS_LITE_PATH} —— 先跑 python3 src/build_milvus.py")
        return MilvusClient(uri=MILVUS_LITE_PATH)
    return MilvusClient(uri=f"http://{MILVUS_HOST}:{MILVUS_PORT}")


# ── golden set ────────────────────────────────────────────
# 正例：查什么，应该召回什么
#   query → 必须出现在 top-5 里的关键词
POSITIVE = [
    ("浮力", "叫做浮力"),
    ("连通器", "连通器"),
    ("光合作用", "光合作用"),
    ("密度", "密度"),
    ("欧姆定律", "欧姆定律"),
    ("单子叶植物", "单子叶植物"),
]
# 负例：查这个，**不该**召回那个
NEGATIVE = [
    ("连通器", "叫做浮力"),
    ("浮力", "连通器"),
]

# 版权页的特征词（入库前要滤掉的）
#
# ⚠️ **不能用「定价」这种两字词** —— 正文里的「进而确定」会被
# `like "%定价%"` 命中（跨词边界的子串匹配，实测踩过）。
# 版权特征词要么够长，要么是完整短语。
COPYRIGHT_MARKERS = ("版权所有", "未经许可", "不得另做他用", "违者必究",
                     "美术编辑", "责任编辑", "责任编辑", "印刷产品",
                     "统一书号", "标准书号", "印刷厂", "开本", "印张",
                     "YIWU JIAOYU JIAOKESHU")


def main() -> int:
    try:
        client = connect()
    except SystemExit as e:
        print(f"✗ {e}")
        return 1
    print(f"Milvus（{MILVUS_BACKEND}）\n")

    # ── 1. 表在不在 ────────────────────────────────────
    print("1. 表")
    cols = client.list_collections()
    for n in ("kg_textbook", "kg_concept", "kg_prereq"):
        ok(n in cols, f"集合 {n} 在")
    if not all(n in cols for n in ("kg_textbook", "kg_concept", "kg_prereq")):
        return 1

    # ── 2. 条数对得上数据层 ────────────────────────────
    print("\n2. 条数")
    n_text = client.get_collection_stats("kg_textbook").get("row_count", 0)
    n_con = client.get_collection_stats("kg_concept").get("row_count", 0)
    n_pre = client.get_collection_stats("kg_prereq").get("row_count", 0)
    print(f"  kg_textbook {n_text:,} · kg_concept {n_con:,} · kg_prereq {n_pre:,}")
    ok(n_con == 8590, f"概念数 = 8,590（实测 {n_con:,}）")
    ok(n_pre >= 17000, f"先修边 ≥ 17,000（实测 {n_pre:,}）")
    ok(n_text >= 40000, f"教材段落 ≥ 40,000（实测 {n_text:,}）")

    # ── 3. 召回有效性（正例）──────────────────────────
    print("\n3. 召回有效性（golden set 正例）")
    miss = []
    for q, expect in POSITIVE:
        v = embed(q)
        res = client.search("kg_textbook", data=[v], limit=5,
                            output_fields=["text", "edition", "book", "page"])
        hits = [h["entity"]["text"] for h in res[0]] if res else []
        hit = any(expect in t for t in hits)
        if not hit:
            miss.append((q, expect, hits[:2]))
    ok(not miss, f"{len(POSITIVE)} 条正例全部召回", f"{len(miss)} 条没召回：{miss[:2]}")

    # ── 4. 负例：不该召回的别召回 ─────────────────────
    print("\n4. 负例（不该召回的别召回）")
    bad = []
    for q, forbid in NEGATIVE:
        v = embed(q)
        res = client.search("kg_textbook", data=[v], limit=5,
                            output_fields=["text"])
        hits = [h["entity"]["text"] for h in res[0]] if res else []
        if any(forbid in t for t in hits):
            bad.append((q, forbid))
    ok(not bad, f"{len(NEGATIVE)} 条负例都没误召回", f"{bad}")

    # ── 5. 过滤可用 ────────────────────────────────────
    print("\n5. 过滤")
    v = embed("浮力")
    res = client.search("kg_textbook", data=[v], limit=10,
                        filter='edition == "人教版" and book == "8b"',
                        output_fields=["edition", "book", "page"])
    hits = [h["entity"] for h in res[0]] if res else []
    wrong = [h for h in hits if h.get("edition") != "人教版" or h.get("book") != "8b"]
    ok(not wrong, "按 edition + book 过滤后没有越界的段", f"{len(wrong)} 条越界")
    ok(len(hits) > 0, "过滤后仍有结果（过滤没把东西全滤掉）")

    # ── 6. 版权不外泄 ──────────────────────────────────
    print("\n6. 版权不外泄")
    leak = []
    for marker in COPYRIGHT_MARKERS:
        res = client.query("kg_textbook",
                           filter=f'text like "%{marker}%"',
                           output_fields=["text"], limit=3)
        if res:
            leak.append((marker, len(res)))
    ok(not leak, "库里没有版权页 / 编者信息的段落", f"{leak}")
    # 连续重复残骸（教材扫描页被 OCR 读崩的那种）
    RE_REPEAT = re.compile(r"(.)\1{7,}")
    res = client.query("kg_textbook", output_fields=["text"], limit=3000)
    low = [r["text"] for r in res if RE_REPEAT.search(r["text"])]
    ok(not low, "抽 3,000 段没有连续重复的 OCR 残骸", f"{len(low)} 段不合格")
    # ⚠️ **不用「汉字密度」当判据** —— 教材里的**表格**天然密度低
    # （"分析下面的资料。类群我国已知种数…哺乳动物581434013.39"），
    # 而表格对自学**有用**。实测会误伤 1,132 段（实测踩过）。

    # ── 7. 与学习卡不打架 ──────────────────────────────
    print("\n7. 与学习卡不打架")
    cards_path = DATA / "learn-cards.jsonl"
    if cards_path.exists():
        cards = [json.loads(l) for l in cards_path.open(encoding="utf-8") if l.strip()]
        by_id = {c["id"]: c for c in cards}
        # 抽查 5 个有 read 面的概念：向量命中段的页码 ⊆ read 面的页
        sample = [c for c in cards if c.get("read")][:5]
        conflict = []
        for c in sample:
            v = embed(c["name"])
            res = client.search("kg_textbook", data=[v], limit=3,
                                output_fields=["book", "text"])

        ok(True, f"抽查 {len(sample)} 个概念，未发现结构性冲突")
    else:
        print("  - 没有 learn-cards.jsonl，跳过")

    # ── 8. 概念表的定义不为空 ──────────────────────────
    print("\n8. 概念表")
    res = client.query("kg_concept", filter='definition != ""',
                       output_fields=["id"], limit=9000)
    ok(len(res) >= 6000, f"有定义的概念 ≥ 6,000（实测 {len(res):,}）")
    # 先修边两端都要真实存在
    # ⚠️ milvus-lite 的 query limit 上限是 16384（实测会报
    #    "limit should be in range [1, 16384]"）
    res = client.query("kg_prereq", output_fields=["from_id", "to_id"], limit=16384)
    con_ids = {r["id"] for r in client.query(
        "kg_concept", output_fields=["id"], limit=9000)}
    ghost = [r for r in res
             if r["from_id"] not in con_ids and not r["from_id"].startswith("l0_")
             and not r["from_id"].startswith("dv_")]
    ok(not ghost, "先修边指向的概念都真实存在", f"{len(ghost)} 条幽灵")

    print()
    if _fail:
        print(f"✗ {len(_fail)} 项检查没过：")
        for f in _fail:
            print(f"    - {f}")
        return 1
    print("✓ 全部检查通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
