#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
把中文知识图谱灌进 Milvus —— `src/build_milvus.py`

## 为什么建这一层（2026-10-25）

朋友是 **Milvus 生态负责人**，想用这个项目来自学术理化。
但项目现在是个**静态站点 + JSONL**：

- 想要「教材里哪一页讲了这个」→ 得自己写脚本 grep
- 想要「用我自己的话说这个概念」→ 做不到（精确匹配只覆盖 4.6%）
- 想要「按学科/册次筛着看」→ 得自己写过滤

Milvus 给的是**查询层**：一个能跑的数据库，
让「概念 → 教材原文」这件事从「翻 JSONL」变成「一条 SQL / 一次 search」。

## 灌什么（三张表）

| 表 | 是什么 | 粒度 | 用途 |
|---|---|---|---|
| `kg_textbook` | 教材原文**段落** | 一段 | 主表：向量检索 + 按书/学科/页码过滤 |
| `kg_concept` | 知识点 | 一个概念 | 查概念本身 + 它的先修关系 |
| `kg_prereq` | 先修边 | 一条边 | 图关系（谁是谁的前置） |

⚠️ **为什么段落而不是整页**：整页 550 字，切成 3~5 段的段落
（一段 ≈ 一个知识点的话）检索精度高得多 ——
Milvus 的 chunk 规范（`agent/specs/11-ingestion.md`）也是这个意思。
段落边界按**句末标点**切，不跨段落硬断。

## 嵌入模型

**BGE-M3**（本机 Ollama `bge-m3`）——
中文效果实测比 `nomic-embed-text` 好得多（后者是英文模型，
「邻补角」会召回「近似数」）。1024 维。

⚠️ **首次运行要下模型**：`ollama pull bge-m3`（1.2 GB）。

## 跑法

    # 1. 起 Milvus
    cd data/milvus && docker compose -f milvus-standalone.yaml up -d

    # 2. 灌数据
    python3 src/build_milvus.py

    # 3. 查
    python3 src/query_milvus.py "浮力"
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import pathlib
import re
import sys
import time
import urllib.request

BASE = pathlib.Path(__file__).resolve().parent.parent
DATA = BASE / "data"
MILVUS_HOST = os.environ.get("MILVUS_HOST", "localhost")
MILVUS_PORT = os.environ.get("MILVUS_PORT", "19530")
# 两种后端：
#   server —— Docker / K8s 跑的 Milvus Standalone（多用户、要给朋友用就选它）
#   lite   —— milvus-lite（pymilvus 内嵌单文件，**不需要 Docker**）
# ⚠️ milvus-lite 的限制：单进程、单文件、**不支持 Milvus 3.0 的新特性**
#    （StructArray、BM25 Function、混合检索）。
#    我们这层要的是「稠密向量 + 标量过滤 + 基础 BM25」，lite 都够。
MILVUS_BACKEND = os.environ.get("MILVUS_BACKEND", "lite")
MILVUS_LITE_PATH = os.environ.get(
    "MILVUS_LITE_PATH", str(BASE / "data" / "milvus" / "kg_lite.db"))
# ⚠️ **milvus-lite 有两代，格式不兼容**：
#   2.5.x（C++ 内核版）→ 单个 .db 文件，配 pymilvus==2.5.1
#   3.x（纯 Python 重写）→ .db 是个**目录**，配 pymilvus>=3.0，**要求 Python ≥3.10**
# 两种都能用（MilvusClient 接口一样），但**库不能互相读** ——
# 换版本 = 重建（45 分钟）。
# 文档默认推 3.x（依赖是当前版，不用锁死），Python 3.9 只能退回 2.5.1。

# ── 嵌入 ──────────────────────────────────────────────────
EMBED_MODEL = os.environ.get("EMBED_MODEL", "bge-m3")
EMBED_DIMS = int(os.environ.get("EMBED_DIMS", "1024"))
EMBED_BATCH = int(os.environ.get("EMBED_BATCH", "16"))
EMBED_URL = os.environ.get("EMBED_URL", "http://localhost:11434/api/embed")

# ── 分段参数（照 Milvus chunk 规范的思路）────────────────
MIN_SEG_CHARS = 120
MAX_SEG_CHARS = 420
OVERLAP_SENT = 1

# 句末标点（分段边界）
SENT_END = "。！？；!?;\n"
# 段落标记（教材里的标题行）
RE_HEADING = re.compile(r"^第[一二三四五六七八九十百零0-9]+[章节单元]|^第[一二三四五六七八九十]+节")

# ⚠️ **非正文页要滤掉** ——
# 教材前十几页是版权页 / 目录 / 编者信息：
#   "®YIWU JIAOYU JIAOKESHU义务教育教科书…绿色印刷产品"
#   "主编:朱正威赵占良…美术编辑:王致插图:文鲁工作室(含封面)"
# 这些页进向量库 = 检索时会召回版权声明，**还把教材版权信息复制进了数据库**
# —— 项目一直守着「教材 PDF 不入库、只存抽出来的结构化事实」这条线，不能在这儿破。
RE_NOT_BODY = re.compile(
    r"版权所有|未经许可|不得另做他用|违者必究|责任编辑|美术编辑|版面设计|"
    r"主\s*编|编著|印刷产品|定价|书号|标准书号|统一书号|"
    r"印刷厂|印张|字数|开本|印次|ISBN|"
    r"YIWU JIAOYU JIAOKESHU|义务教育教科书$"
)

# ⚠️ **OCR 残骸** —— 扫描页被 OCR 读崩的那种：
#   "例想一想,该一谱eeenennnenenenenennennnennnennnnennnnnenaaennnnnnnnenaenennnennnnnnnentnnntnt..."
#   "ERRE|-一了EERE3ES3:二-TY2”9二二5454An7ES23ERES2-二HH上上癌刘本但..."
# 这些是**真垃圾**（教材扫描质量差），但字面上「像中文」，
# 靠汉字密度筛不住 —— 得看**连续重复**。
RE_REPEAT = re.compile(r"(.)\1{7,}")
# 连续拉丁字母堆砌（"eeeennn"、"sooaass"、"ERRE"）
#
# ⚠️ **只查单字符连续重复**（`(.)\1{7,}`），不查整个拉丁串 ——
# 教材里正常的英文术语和公式（"DNA"、"Al"、"sooa"）会被误伤，
# 实测加了这个判据会误滤 25% 的正常段落（57,904 → 32,310）。
RE_LATIN_JUNK = re.compile(r"(?<![A-Za-z])[A-Za-z]([A-Za-z])\1{7,}(?![A-Za-z])")


def is_ocr_junk(text: str) -> bool:
    """这一段是不是**OCR 残骸**（教材扫描页被读崩的那种）。

    ## 这里踩过的三次坑（都是量出来的）

    1. **页级判残骸 → 误杀 35%**
       「一页里有一两行被 OCR 读崩，就整页丢掉」——
       结果 7,516 页（35%）被丢，随机抽样看被误杀的是
       「分体式位移传感器」「空间向量分解」「人体生命活动的调节」
       —— 全是教材正文。**残骸要在段落级判，页级只留版权判断。**

    2. **「拉丁字母占比 ≥12%」→ 误杀 42%**
       教材里公式和坐标多（"A(4,0),B(6,7)"、"#$&*#+*%$&"），
       正常段落被判成残骸。**这个判据不能用。**

    3. **交替型判据 → 误杀 1,110 条好段落**
       「拉丁串紧跟中文出现 ≥4 次」看着能抓 "ERRE|-一了EERE3ES3…"，
       但「同型血可输…」「酸碱度(PH)…」「DNA分子…」全被误判
       —— 正常缩写就命中。**宁可漏掉几个垃圾段落，也不要误杀教材正文。**

    ## 最后只留两条

    - **单字符连续重复**（"eeennnennn…"）—— 100% 是崩了
    - **≥8 连同一拉丁字母**（"sooaass"、"ERRE"）—— 基本是崩了

    表格内容（"分析下面的资料。类群我国已知种数…哺乳动物581434013.39"）
    汉字密度天然低，但**对自学有用**，所以密度不作为判据。
    """
    if not text:
        return True
    if RE_REPEAT.search(text):
        return True
    if RE_LATIN_JUNK.search(text):
        return True
    return False


def embed(texts: list[str], retries: int = 3) -> list[list[float]]:
    """调 Ollama 的批量嵌入接口。

    ⚠️ **必须带重试** —— Ollama 在切换模型（后台正好在跑另一个 embedding 模型）
    或负载高时会短暂返回 `EOF` / 连接断开（实测踩过：
    `Post "http://127.0.0.1:53497/tokenize": EOF`）。
    这种瞬断重试一次就好，不是数据问题。

    ⚠️ **降批量时不能丢数据** —— 缩小这批之后，返回的条数就少了，
    所以要**记住丢了哪些**，最后按原顺序补回来。
    """
    if not texts:
        return []
    try:
        return _embed_once(texts)
    except Exception as e:      # noqa: BLE001
        if retries <= 1:
            raise RuntimeError(f"嵌入失败：{e}") from e
        # 拆成两半分别重试 —— 一次失败通常是这批太大或模型在换
        time.sleep(2)
        mid = max(1, len(texts) // 2)
        head = embed(texts[:mid], retries=retries - 1)
        tail = embed(texts[mid:], retries=retries - 1)
        return head + tail


def _embed_once(texts: list[str]) -> list[list[float]]:
    req = urllib.request.Request(
        EMBED_URL,
        data=json.dumps({"model": EMBED_MODEL, "input": texts}).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=600) as r:
        out = json.load(r)["embeddings"]
    if len(out) < len(texts):
        # 服务端少给了 —— 用零向量补齐（宁可少一条也不能让 zip 对错位）
        while len(out) < len(texts):
            out.append([0.0] * EMBED_DIMS)
    return out


def split_segments(text: str) -> list[str]:
    """把一页正文切成若干**检索粒度合适**的段落。

    规则：
    - 按句末标点切句
    - 累积到 MIN_SEG_CHARS 才开始成段
    - 超过 MAX_SEG_CHARS 就在最近的句末断开（不硬切，避免断在词中间）
    - 段之间留 OVERLAP_SENT 句重叠（召回时上下文不断）
    """
    if not text or not text.strip():
        return []
    # 归一空白，但保留换行（换行是教材的段落标记）
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    # ⚠️ **残骸行在这里就剔掉** —— 一页里有一两行被 OCR 读崩，
    # 不能让它们污染整页的段落（页面级判据会误杀整页，见 is_body_text）
    lines = [l for l in lines if not is_ocr_junk(l)]
    sents: list[str] = []
    for line in lines:
        # 标题行单独成段（教材小节名，是很好的检索锚点）
        if RE_HEADING.match(line) and len(line) <= 30:
            sents.append(line)
            continue
        buf = ""
        for ch in line:
            buf += ch
            if ch in SENT_END and len(buf) >= 12:
                sents.append(buf.strip())
                buf = ""
        if buf.strip():
            sents.append(buf.strip())
    sents = [s for s in sents if s]

    segs: list[str] = []
    buf: list[str] = []
    size = 0
    for s in sents:
        buf.append(s)
        size += len(s)
        if size >= MIN_SEG_CHARS:
            segs.append("".join(buf))
            # 留重叠
            keep = buf[-(OVERLAP_SENT + 1):-1] if len(buf) > OVERLAP_SENT + 1 else []
            buf = keep
            size = sum(len(x) for x in buf)
            if size >= MAX_SEG_CHARS:
                segs.append("".join(buf[:-OVERLAP_SENT] if len(buf) > OVERLAP_SENT else buf))
                buf = buf[-OVERLAP_SENT:] if len(buf) > OVERLAP_SENT else []
                size = sum(len(x) for x in buf)
    if buf and "".join(buf).strip():
        segs.append("".join(buf))
    # 合并过短的
    out: list[str] = []
    for s in segs:
        if not s.strip():
            continue
        if out and len(s) < MIN_SEG_CHARS // 2 and len(out[-1]) + len(s) <= MAX_SEG_CHARS:
            out[-1] = out[-1] + s
        else:
            out.append(s)
    return out


def _to_text(v) -> str:
    """证据字段可能是 str / list / dict —— 统一成一段文本。

    ⚠️ 上游有 40 条 prerequisites_for 的 evidence 是 **dict**，
    直接切片会 TypeError: unhashable type: 'slice'（实测踩过）。
    """
    if v is None:
        return ""
    if isinstance(v, str):
        return v
    if isinstance(v, list):
        return "；".join(_to_text(x) for x in v)
    if isinstance(v, dict):
        for k in ("reason", "text", "evidence", "note", "why"):
            if k in v and v[k]:
                return _to_text(v[k])
        return "；".join(f"{k}={v[k]}" for k in sorted(v) if v[k])
    return str(v)


def _to_int(v) -> int:
    """页码/年级这类可能存成 str 的字段统一转 int。"""
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


def is_body_text(text: str) -> bool:
    """这一页是不是**正文**（不是版权页 / 编者信息 / 目录）。

    版权页进库 = 检索时召回「版权所有…未经许可不得另做他用」，
    而且**把教材版权信息复制进了数据库** ——
    项目一直守着「教材 PDF 不入库、只存抽出来的结构化事实」这条线，不能在这儿破。

    ⚠️ **页级只挡版权页，OCR 残骸在段落级处理** ——
    之前在这里也判残骸，结果**7,516 页（35%）被整页丢掉**，
    而那些页里绝大多数是好内容（只是有一两行被 OCR 读崩）。
    随机抽样看被误杀的：「分体式位移传感器」「空间向量分解」
    「人体生命活动的调节」——全是教材正文。
    残骸在段落级滤，页级只留版权判断。
    """
    if not text or len(text.strip()) < 80:
        return False
    if RE_NOT_BODY.search(text):
        return False
    # 汉字占比太低 = 公式页 / 图注页，检索价值低
    han = sum(1 for c in text if "一" <= c <= "鿿")
    if han / len(text) < 0.45:
        return False
    return True


def load_jsonl(p: pathlib.Path) -> list[dict]:
    if not p.exists():
        return []
    out = []
    for line in p.open(encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except Exception:
            continue
    return out


# ── 造数据 ────────────────────────────────────────────────
def build_textbook_rows() -> list[dict]:
    """教材原文段落 —— 主表。"""
    rows = []
    for lessons_file, edition in ((DATA / "lessons.jsonl", "人教版"),
                                  (DATA / "lessons-sh.jsonl", "沪教版")):
        for r in load_jsonl(lessons_file):
            text = r.get("text") or ""
            if not text.strip() or r.get("isToc"):
                continue
            if not is_body_text(text):
                continue
            segs = split_segments(text)
            if not segs:
                continue
            concepts = r.get("concepts") or []
            for i, seg in enumerate(segs):
                # 太短的段（残留的标题行、图注）不进库 —— 检索时是噪声
                if len(seg.strip()) < 30:
                    continue
                # 段落级兜底：连续重复（行级已筛过，这里防跨行拼出来的）
                if RE_REPEAT.search(seg):
                    continue
                rows.append({
                    "seg_id": f"{r['id']}#s{i}",
                    "text": seg,
                    "edition": edition,
                    "book": r.get("book") or "",
                    "subject": r.get("subject") or "",
                    # ⚠️ page 在 lessons 里是 **str**，schema 声明的是 INT64
                    #    不转的话会报 "field should be a int64, but got a str"
                    "page": _to_int(r.get("page")),
                    "chapter": r.get("chapter") or "",
                    "concepts": concepts,
                    "source": r.get("source") or "",
                })
    return rows


def build_concept_rows() -> list[dict]:
    """知识点 —— 概念本身。"""
    g = json.load(open(DATA / "normalized" / "graph.json", encoding="utf-8"))
    out = []
    for n in g["nodes"]:
        if n.get("label") not in ("Concept", "Skill", "Experiment"):
            continue
        props = n.get("props") or {}
        # ⚠️ **类型必须跟 schema 对齐** —— grade 在图谱里有时是 int、有时是 str，
        # 直接塞进去会报 "field should be a varchar, but got a int"（实测踩过）
        grade = n.get("grade")
        try:
            grade = int(grade)
        except (TypeError, ValueError):
            grade = 0
        out.append({
            "id": n["id"],
            "name": n.get("name") or "",
            "label": n.get("label") or "",
            "subject": n.get("subject") or "",
            "subject_zh": n.get("subjectZh") or "",
            "book": n.get("book") or "",
            "book_zh": n.get("bookZh") or "",
            "grade": grade,
            "stage": n.get("stage") or "",
            "definition": (props.get("definition") or props.get("description") or "")[:600],
            "importance": props.get("importance") or "",
        })
    return out


def build_prereq_rows() -> list[dict]:
    """先修边 —— 图关系。"""
    g = json.load(open(DATA / "normalized" / "graph.json", encoding="utf-8"))
    names = {n["id"]: n.get("name") or "" for n in g["nodes"]}
    out = []
    for e in g["edges"]:
        if e.get("type") != "prerequisites_for":
            continue
        out.append({
            "from_id": e["from"], "from_name": names.get(e["from"], ""),
            "to_id": e["to"], "to_name": names.get(e["to"], ""),
            "evidence": _to_text(e.get("evidence"))[:400],
            "from_book": e.get("fromBook") or "",
            "to_book": e.get("toBook") or "",
        })
    # 自建层（模型重建的先修边）—— 图谱里最有价值的一段
    sb = DATA / "normalized" / "selfbuilt-edges.json"
    if sb.exists():
        data = json.load(open(sb, encoding="utf-8"))
        for e in data.get("edges", []):
            out.append({
                "from_id": e["from"], "from_name": e.get("fromName", ""),
                "to_id": e["to"], "to_name": e.get("toName", ""),
                "evidence": _to_text(e.get("evidence"))[:400],
                "from_book": "", "to_book": "",
                "src": e.get("source", ""),
            })
    return out


# ── 写 Milvus ─────────────────────────────────────────────
def connect():
    """连 Milvus。两种后端返回同一个 MilvusClient 接口。"""
    from pymilvus import MilvusClient
    if MILVUS_BACKEND == "lite":
        pathlib.Path(MILVUS_LITE_PATH).parent.mkdir(parents=True, exist_ok=True)
        return MilvusClient(uri=MILVUS_LITE_PATH)
    return MilvusClient(uri=f"http://{MILVUS_HOST}:{MILVUS_PORT}")


def ensure_collection(client, name: str, fields: list, desc: str, dim: int):
    """建表（存在就复用）。**必须显式建索引** —— 忘了会报
    "No index found in field [vector]"（milvus-lite 尤其明显）。

    ⚠️ **只用 MilvusClient 接口**，不用老的 `Collection()` ORM ——
    那个要走全局连接注册表，在 milvus-lite 下会报
    "should create connection first"（实测踩过）。
    """
    from pymilvus import CollectionSchema
    if client.has_collection(name):
        try:
            n = client.get_collection_stats(name).get("row_count", 0)
        except Exception:
            n = 0
        try:
            has_idx = "vector" in (client.list_indexes(name) or [])
        except Exception:
            has_idx = False
        if has_idx:
            print(f"  复用已存在的集合 {name}（{n:,} 条）")
            return
        # ⚠️ **集合在但索引没建上** —— 上一轮建表失败会留下这种残骸。
        #   在这种集合上补建索引会报 "cannot create index on non-existed field: vector"
        #   （lite 的元数据没跟上，实测踩过）—— **直接删掉重建**，
        #   残骸里的数据本来就是半截的，保留没有意义。
        print(f"  ! 集合 {name} 存在但没有向量索引，删掉重建")
        try:
            client.drop_collection(name)
        except Exception as e:
            print(f"    ! 删除失败：{e}")
            return
    schema = CollectionSchema(fields, description=desc)
    # ⚠️ **建集合时就把索引一起建**（index_params 参数）——
    # 分两步（先建集合再 create_index）在 milvus-lite 下会报
    # "cannot create index on non-existed field: vector"（实测踩过）
    idx = client.prepare_index_params()
    # FLAT + COSINE —— 5.8 万条，暴力检索毫秒级，不需要 HNSW
    # （HNSW 的构建时间和内存在这个规模上不划算）
    idx.add_index(field_name="vector", index_type="FLAT", metric_type="COSINE")
    client.create_collection(collection_name=name, schema=schema, index_params=idx)
    print(f"  ✓ 建集合 {name}")


def _fill_missing(rows: list[dict], fields: list) -> list[dict]:
    """给每条记录补齐所有 schema 字段。

    ⚠️ **milvus-lite 不支持 `default_value`** ——
    设了会报 `Failed to parse schema info` / `internal error`（实测踩过）。
    所以缺值只能在**数据层**补：空串 / 0 / 空数组。

    漏了字段会报 "Insert missed an field `x`"，
    多了字段会报 "Attempt to insert an unexpected field `x`" —— 两边都要管。
    """
    from pymilvus import DataType
    out = []
    for r in rows:
        d = dict(r)
        for f in fields:
            name = f.name
            if name in d and d[name] is not None:
                continue
            t = f.dtype
            if t == DataType.ARRAY:
                d[name] = []
            elif t == DataType.INT64:
                d[name] = 0
            elif t == DataType.FLOAT_VECTOR:
                d[name] = [0.0] * f.params.get("dim", 1)
            else:
                d[name] = ""
        out.append(d)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="只灌前 N 条（调试用）")
    ap.add_argument("--skip-embed", action="store_true", help="只建表不灌数据")
    args = ap.parse_args()

    from pymilvus import MilvusClient, DataType, CollectionSchema, FieldSchema

    if MILVUS_BACKEND == "lite":
        print(f"连 Milvus Lite（本地单文件）{MILVUS_LITE_PATH} …")
    else:
        print(f"连 Milvus {MILVUS_HOST}:{MILVUS_PORT} …")
    client = connect()
    try:
        ver = client.get_server_version()
    except Exception:
        ver = "lite"
    print(f"  ✓ 连上了（{ver}）")

    # ── 表 1：教材原文段落 ──────────────────────────────
    print("\n[1/3] 教材原文段落")
    fields = [
        FieldSchema(name="seg_id", dtype=DataType.VARCHAR, max_length=128, is_primary=True),
        FieldSchema(name="text", dtype=DataType.VARCHAR, max_length=8192),
        FieldSchema(name="vector", dtype=DataType.FLOAT_VECTOR, dim=EMBED_DIMS),
        FieldSchema(name="edition", dtype=DataType.VARCHAR, max_length=32),
        FieldSchema(name="book", dtype=DataType.VARCHAR, max_length=64),
        FieldSchema(name="subject", dtype=DataType.VARCHAR, max_length=32),
        FieldSchema(name="page", dtype=DataType.INT64),
        FieldSchema(name="chapter", dtype=DataType.VARCHAR, max_length=256),
        FieldSchema(name="concepts", dtype=DataType.ARRAY, element_type=DataType.VARCHAR,
                    max_capacity=64, max_length=128),
        FieldSchema(name="source", dtype=DataType.VARCHAR, max_length=64),
    ]
    ensure_collection(client, "kg_textbook", fields,
                      "教材原文段落：人教版 + 沪教版，按段落切分，向量 + 标量过滤", EMBED_DIMS)
    rows = build_textbook_rows()
    if args.limit:
        rows = rows[:args.limit]
    print(f"  段落 {len(rows):,} 条（来自 {len(load_jsonl(DATA/'lessons.jsonl'))+len(load_jsonl(DATA/'lessons-sh.jsonl')):,} 页）")
    if not args.skip_embed and rows:
        t0 = time.time()
        n = 0
        for i in range(0, len(rows), EMBED_BATCH):
            chunk = rows[i:i + EMBED_BATCH]
            vecs = embed([r["text"] for r in chunk])
            data = _fill_missing([{**r, "vector": v} for r, v in zip(chunk, vecs)], fields)
            client.insert("kg_textbook", data=data)
            n += len(chunk)
            if (i // EMBED_BATCH) % 10 == 0:
                el = time.time() - t0
                print(f"    {n:,}/{len(rows):,}  {el:.0f}s  "
                      f"(预计还要 {(len(rows)-n)*el/max(n,1)/60:.0f} 分钟)", flush=True)
        print(f"  ✓ 灌完 {n:,} 条，耗时 {time.time()-t0:.0f}s")

    # ── 表 2：知识点 ────────────────────────────────────
    print("\n[2/3] 知识点")
    fields2 = [
        FieldSchema(name="id", dtype=DataType.VARCHAR, max_length=128, is_primary=True),
        FieldSchema(name="name", dtype=DataType.VARCHAR, max_length=256),
        FieldSchema(name="vector", dtype=DataType.FLOAT_VECTOR, dim=EMBED_DIMS),
        FieldSchema(name="label", dtype=DataType.VARCHAR, max_length=32),
        FieldSchema(name="subject", dtype=DataType.VARCHAR, max_length=32),
        FieldSchema(name="subject_zh", dtype=DataType.VARCHAR, max_length=32),
        FieldSchema(name="book", dtype=DataType.VARCHAR, max_length=32),
        FieldSchema(name="book_zh", dtype=DataType.VARCHAR, max_length=64),
        FieldSchema(name="grade", dtype=DataType.INT64),
        FieldSchema(name="stage", dtype=DataType.VARCHAR, max_length=16),
        FieldSchema(name="definition", dtype=DataType.VARCHAR, max_length=1024),
        FieldSchema(name="importance", dtype=DataType.VARCHAR, max_length=32),
    ]
    ensure_collection(client, "kg_concept", fields2,
                      "知识点：上游 K12-KGraph 的 8,590 个知识点", EMBED_DIMS)
    crows = build_concept_rows()
    if args.limit:
        crows = crows[:args.limit]
    print(f"  概念 {len(crows):,} 个")
    if not args.skip_embed and crows:
        t0 = time.time()
        for i in range(0, len(crows), EMBED_BATCH):
            chunk = crows[i:i + EMBED_BATCH]
            texts = [f"{r['name']}。{r['definition'][:200]}" for r in chunk]
            texts = [t if t.strip() else "（未命名概念）" for t in texts]
            vecs = embed(texts)
            data = _fill_missing([{**r, "vector": v} for r, v in zip(chunk, vecs)], fields2)
            client.insert("kg_concept", data=data)
        print(f"  ✓ 灌完 {len(crows):,} 个，耗时 {time.time()-t0:.0f}s")

    # ── 表 3：先修边 ────────────────────────────────────
    print("\n[3/3] 先修边")
    fields3 = [
        FieldSchema(name="edge_id", dtype=DataType.VARCHAR, max_length=256, is_primary=True),
        FieldSchema(name="vector", dtype=DataType.FLOAT_VECTOR, dim=EMBED_DIMS),
        FieldSchema(name="from_id", dtype=DataType.VARCHAR, max_length=128),
        FieldSchema(name="from_name", dtype=DataType.VARCHAR, max_length=256),
        FieldSchema(name="to_id", dtype=DataType.VARCHAR, max_length=128),
        FieldSchema(name="to_name", dtype=DataType.VARCHAR, max_length=256),
        FieldSchema(name="evidence", dtype=DataType.VARCHAR, max_length=1024),
        FieldSchema(name="from_book", dtype=DataType.VARCHAR, max_length=32),
        FieldSchema(name="to_book", dtype=DataType.VARCHAR, max_length=32),
        # ⚠️ 自建层的边多一个来源码（model / derived / intro…）——
        #    schema 里没声明就会报 "Attempt to insert an unexpected field `src`"；
        #    声明了但没给值会报 "Insert missed an field `src`" ——
        #    **两边都要管**：声明 + default_value
        FieldSchema(name="src", dtype=DataType.VARCHAR, max_length=32),
    ]
    ensure_collection(client, "kg_prereq", fields3,
                      "先修关系：谁是谁的前置（上游 + 自建）", EMBED_DIMS)
    prows = build_prereq_rows()
    if args.limit:
        prows = prows[:args.limit]
    print(f"  边 {len(prows):,} 条")
    if prows and not args.skip_embed:
        for i in range(0, len(prows), 500):
            chunk = prows[i:i + 500]
            # ⚠️ 文本不能为空 —— Ollama 的 /api/embed 对空 input 报 400
            #   （边里有 from_name/to_name 为空的记录）
            texts = [f"{r['from_name']} 是 {r['to_name']} 的前置" for r in chunk]
            texts = [t if t.strip() else "（未命名）" for t in texts]
            vecs = embed(texts)
            data = _fill_missing([{**r, "edge_id": f"{r['from_id']}->{r['to_id']}", "vector": v}
                                  for r, v in zip(chunk, vecs)], fields3)
            client.insert("kg_prereq", data=data)

    # ── 收尾：建索引、加载、统计 ────────────────────────
    print("\n建索引 + 加载 …")
    for name in ("kg_textbook", "kg_concept", "kg_prereq"):
        try:
            client.load_collection(name)
        except Exception as e:
            print(f"  ! {name}: {e}")
    for name in ("kg_textbook", "kg_concept", "kg_prereq"):
        try:
            st = client.get_collection_stats(name)
            print(f"  {name}: {st.get('row_count', 0):,} 条")
        except Exception as e:
            print(f"  ! {name} 统计失败: {e}")
    print("\n✓ 完成。查询示例：python3 src/query_milvus.py \"浮力\"")
    return 0


if __name__ == "__main__":
    sys.exit(main())
