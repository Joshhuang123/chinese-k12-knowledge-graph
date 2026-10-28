#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
生成数据清单 —— `data/DATASETS.json`

## 为什么要有这个

这个仓库有 **17 个入库的数据文件 + 2 个不可再生的例外**，共 142 MB，
**字段结构有 7 种以上**（jsonl / 嵌套 json / 数组 / 字典）。

问题不在于数据少，而在于**别人不知道怎么找**：

- `docs/agent-data.md` 讲了「四个产物」，但实际已经有**六个**
  （学习卡、页索引都是后加的）
- `data/normalized/selfbuilt-edges.json`（**13,461 条自建先修边** ——
  比上游那 3,703 条可信得多）在所有文档里**一次都没出现过**
- `data/l0-abilities.json`（能力底座）、`data/normalized/confirmed-wrong.json`
  （人工逐条裁决的账本）同样没人提

agent 拿到这个仓库，第一件事是「读 README 找数据」——
但 README 里的文件树是**按脚本组织的**，不是按「这个文件能回答什么问题」组织的。

## 这个清单解决什么

**一个文件回答「这个项目有什么数据、每份是什么、怎么取」。**

机器可读（agent 直接读），也给人读（README 里有一张从它生成的表）。

## 关键：清单是**现算**的

条数、体积、字段、样本行 —— 全部从真实文件读出来，
不是手写的常量。**所以它不会漂移**：
改了数据重跑一次就同步了。

## 跑法

    python3 src/build_datasets_catalog.py
"""
from __future__ import annotations

import collections
import json
import pathlib
import re
import subprocess
import sys

BASE = pathlib.Path(__file__).resolve().parent.parent
DATA = BASE / "data"
OUT = DATA / "DATASETS.json"

# ── 每个数据集的「人话说明」 ──────────────────────────────
# 这一栏是**唯一手写**的部分 —— 机器算不出来「这个文件能回答什么问题」。
# 其余（条数 / 体积 / 字段 / 样本）全部现算。
DESC = {
    "lessons.jsonl": (
        "教材正文，**一页一条**（人教版）",
        "agent 想读「第 22 章第 2 节这一课到底讲了什么」，读一条就行",
        "按 id 直接取：math-9a-p102",
    ),
    "lessons-sh.jsonl": (
        "教材正文，**一页一条**（沪教版/沪科版）",
        "上海的孩子按沪教版教材看，正文层是这一份",
        "按 id 直接取：sh-hk-物理-w-8b-p52",
    ),
    "concept-text.jsonl": (
        "概念的**教材原话**，**一个概念一条**（人教版）",
        "写视频稿要「教材原话 + 页码 + 第几节」，直接拿这条",
        "按 id 或 name 取；quotes 里有原话，quoteKinds 标了哪句是定义句",
    ),
    "learn-questions.jsonl": (
        "**可自动判分的练习题**（从教材原话 / 图谱定义反推）",
        "学习页「练一练」的题库。每道题都逐字来自教材，可以自己回教材对",
        "按 concept 字段取概念名；type=choice 时 options + answer 是可判分的选项",
    ),
    "learn-videos.json": (
        "**讲解视频索引**（按知识点挂载外部视频）",
        "学生自学时的讲解视频。键是概念 id 或概念名，值是 {yt}/{bv}/{url}",
        "改完不用重建数据层 —— 学习页运行时读这个文件",
    ),
    "page-images.json": (
        "**教材原页图的直链基址**（67 本沪教教材）",
        "学习页「教材原页」板块的图片地址。页码是**扫描序号**",
        "按 bookId 取；拼图地址 = base + '/' + 扫描页码 + '.jpg'",
    ),
    "page-images-rjb.json": (
        "**人教版教材原页图索引**（31 册 / 1,128 页）",
        "页图是**从本地教材 PDF 渲染**的（WebP）。页码就是 PDF 的扫描页，"
        "与我们的数据源天然对齐",
        "按册次取：{[册次]: {扫描页: 'data/pages/…/N.webp'}}；"
        "本体在 data/pages/（**入库**，82.1 MB）",
    ),
    "page-offsets.json": (
        "人教版每册的**印刷页码偏移**",
        "书上印的页码 = PDF 扫描页 + offset。学生手里是纸书，"
        "面板必须写纸上那个页号才翻得到",
        "按册次取：{册次: 负数}。矢量册从 PDF 页脚取页码，"
        "扫描件走 OCR（脚本 src/build_page_offsets.py）",
    ),
    "page-offsets-sh.json": (
        "沪教版每册的**印刷页码偏移**",
        "同上。平台的扫描本扫描序号 ≠ 书上印的页码，"
        "差 4–7 页 —— 写错的话学生按页码翻书翻到的是下一节",
        "按沪教书号取：{sh-hj-数学-w-7b: -7}。从平台 OCR 的页脚行取页码，"
        "并用「印刷页码随扫描页单调递增」兜底（src/build_page_offsets_sh.py）",
    ),
    "rjb-book-candidates.json": (
        "平台上**同名教材的候选清单**（人教版 31 册）",
        "平台目录里同名书一堆（数学一上 9 个、必修 38 个，含盲校/聋校/培智/"
        "其他出版社）。这是「按标题匹配 = 按出版社赌运气」的证据",
        "按册次取：{册次: {ours: 本地 PDF, candidates: 平台候选}}",
    ),
    "shanghai-rjb-positions.json": (
        "人教版前置节点在**沪教教材里的真实位置**",
        "上海站要挡住人教版节点，就得先知道这些概念沪教教材到底在哪儿教的",
        "按上游概念 id 取：给出沪教版别、册次、证据档",
    ),
    "concept-text-sh.jsonl": (
        "概念的**教材原话**，**一个概念一条**（沪教版）",
        "同上，沪教那套",
        "按 id 取；这层用 books + pages 记位置（**印刷页码**，不是扫描页码）",
    ),
    "concept-vision.jsonl": (
        "概念的**公式 / 图形语义 / 例题**（人教版）",
        "OCR 丢掉的公式和图形，这一层用多模态模型捞回来了",
        "按 id 取；formulas 是 LaTeX，figureDescriptions 是据图转述，exercises 是题干",
    ),
    "concept-vision-sh.jsonl": (
        "概念的**公式 / 图形语义 / 例题**（沪教版）",
        "同上，沪教那套",
        "按 id 取；字段同上",
    ),
    "vision-pages.jsonl": (
        "页面的**视觉层**（人教版）—— 一页一条",
        "公式和图形的**页面级**原始记录（概念层是从这里聚合出来的）",
        "按 id 取",
    ),
    "vision-pages-sh.jsonl": (
        "页面的**视觉层**（沪教版）",
        "同上",
        "按 id 取",
    ),
    "vision-pages-alt.jsonl": (
        "页面的**视觉层**（其他出版社版本）",
        "沪教/冀教/北京/华东师大等版本教材的公式图形",
        "按 id 取，id 里的出版社前缀要分清",
    ),
    "vision-pages-kx.jsonl": (
        "页面的**视觉层**（小学科学）",
        "人教版《小学科学》12 本的视觉层",
        "按 id 取",
    ),
    "kx-ocr.jsonl": (
        "小学科学教材的**OCR 正文**",
        "人教版《小学科学》1上~6下，1,036 页",
        "按 id 取",
    ),
    "concept-vision-kx.jsonl": (
        "小学科学概念的**公式 / 图形 / 例题**",
        "146 个概念定位到小学科学的书/节/页",
        "按 id 取",
    ),
    "learn-cards.jsonl": (
        "知识点**自学卡**，**一个概念一张**",
        "**给「我要自学这个概念」用的** —— 六个面一次给全，每段带来源标记",
        "按 id 或 name 取；what/how/practice/prereq/where/read 六个面",
    ),
    "page-index.json": (
        "**概念 → 教材页**反查表",
        "想知道「这个概念在哪几页」时用；页文本已经切好了",
        "_byConcept[概念id] → [{book,page,pageId,text}]",
    ),
    "quote-repairs.json": (
        "引文的**最终判定缓存**",
        "教材 PDF 抽取时把词切断了（“有机物”→“机物中的…”），"
        "这一份是回原文补全后的结果",
        "顶层是 {缓存键: {q, kind, ev}}；缓存键 = “版本#概念id#引文序号”",
    ),
    "shanghai-graph.json": (
        "上海版**图谱**（节点 / 单元链 / 先修边）",
        "上海教材的版本（沪教版/沪科版），跟主站同一套前置关系",
        "nodes / edges / units 三段",
    ),
    "shanghai-toc.json": (
        "上海教材的**目录**（26 本 / 521 节）",
        "教材自己的章节顺序，用来核对图谱的章序对不对",
        "按 book 取",
    ),
    "shanghai-textbook-catalog.json": (
        "上海教材**清单**",
        "哪些版本、哪几册",
        "顶层是数组",
    ),
    "shanghai-textbooks.json": (
        "上海教材的**元信息**",
        "册次、出版社、版本",
        "顶层是数组",
    ),
    "alt-align.json": (
        "**跨版本对照**（人教节 ↔ 其他版本节）",
        "同一节在不同出版社教材里叫什么",
        "byConcept[概念id] → [{label, alt, chapter}]",
    ),
    "alt-editions.json": (
        "其他版本教材的**视觉层**",
        "沪教/冀教/北京等的公式图形",
        "顶层是数组",
    ),
    "alt-editions-manifest.json": (
        "其他版本教材的**清单**",
        "版本、来源、覆盖情况",
        "顶层是数组",
    ),
    "textbook-editions.json": (
        "教材**版本指纹**",
        "我们引用的到底是哪一代教材",
        "顶层是数组",
    ),
    "intro-links.json": (
        "教材的**引入路径**（概念 → 首次出现的那一课）",
        "「这个概念是从哪节课冒出来的」",
        "顶层是数组",
    ),
    "cover-gaps.json": (
        "**封面缺口**清单",
        "哪些书的封面图没拿到（不影响正文）",
        "顶层是数组",
    ),
    "l0-abilities.json": (
        "**能力底座**（L0 层）",
        "跨学科的基础能力（注意力、读图、计算…），"
        "先修图谱里最底层那一层",
        "顶层是数组",
    ),
    "kx-graph.json": (
        "小学科学**独立图谱**（67 节点 / 25 边）",
        "小学科学站的图谱 —— **节点不来自上游**，"
        "是自己从教材目录+正文建的",
        "nodes / edges",
    ),
    "kx-sections.json": (
        "小学科学的**节判定**（105 节）",
        "哪一节是概念、哪一节是活动 —— 视觉模型逐节读的",
        "顶层是数组",
    ),
    "kx-toc.json": (
        "小学科学的**目录**（含页码偏移实测值）",
        "12 本的目录，_offset 字段是印刷页码→扫描页码的实测偏移",
        "按 book 取",
    ),
    "kx-textbooks.json": (
        "小学科学**教材清单**（12 本）",
        "出版社、版本、册次",
        "顶层是数组",
    ),
    "vision-cover.json": (
        "教材**封面**图（人教版）",
        "封面不在库里（教材 PDF 有版权），这里存的是提取出来的封面信息",
        "顶层是数组",
    ),
    "vision-cover-alt.json": (
        "教材**封面**图（其他版本）",
        "同上",
        "顶层是数组",
    ),
    "kx-visual-books.json": (
        "小学科学**视觉层用到的书**",
        "哪些书跑了视觉层",
        "顶层是数组",
    ),
}

# ── 不可再生的例外 ────────────────────────────────────────
# 这些在 data/normalized/ 里（那个目录整个 gitignore 了），
# 但它们**是人工/模型的一次性产出，丢了就永久没了** ——
# 所以在 .gitignore 里开了白名单，也必须列进清单。
EXCEPTIONS = {
    "normalized/selfbuilt-edges.json": (
        "**自建先修边**（13,461 条，模型重建）",
        "上游只给了 3,703 条先修边、70.1% 的概念零前置 —— "
        "这一层是补上的那部分（实测比上游准：上游 38 条争议里模型全对）",
        "edges 数组；source 字段标来源（model / derived / intro）",
        "在 .gitignore 里有白名单 —— **不可再生**，删了构建会永久降级",
    ),
    "normalized/confirmed-wrong.json": (
        "**人工逐条裁决的账本**",
        "哪些上游边被判定为错、错在哪 —— 这是「我们不盲信上游」的证据",
        "顶层数组，每条记了裁决理由",
        "在 .gitignore 里有白名单 —— **不可再生**，人工裁决一次就一次",
    ),
}


def count_records(path: pathlib.Path):
    """数条数。jsonl 数行；json 看顶层结构。"""
    try:
        if path.suffix == ".jsonl":
            n = 0
            with path.open(encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        n += 1
            return n, "行（jsonl，一行一条）"
        d = json.load(path.open(encoding="utf-8"))
        if isinstance(d, list):
            return len(d), "条（顶层数组）"
        if isinstance(d, dict):
            # 顶层是 {key: value}。value 可能是数组（取最大的那个），
            # 也可能是对象（那就报键的数量 —— 像 quote-repairs.json：
            # 顶层是 {缓存键: {q,kind,ev}}，键数才是条数）
            arr_best, arr_key = 0, ""
            obj_best = 0
            for k, v in d.items():
                if isinstance(v, list) and len(v) > arr_best:
                    arr_best, arr_key = len(v), k
                elif isinstance(v, dict):
                    # ⚠️ **别用「内层 dict 的键数」当条数** ——
                    # quote-repairs.json 的值是 {q, kind, ev}（3 个键），
                    # 但它有 15,282 条。
                    # 判据：**子表的键数以 `_` 开头**（page-index 的 _byConcept）
                    if k.startswith("_") and len(v) > arr_best:
                        arr_best, arr_key = len(v), k
                    obj_best = max(obj_best, len(v))
            if arr_best:
                return arr_best, f"条（顶层对象，主数据在 `{arr_key}`）"
            if obj_best:
                # 值全是对象 → 顶层键数就是条数
                return len(d), "条（顶层对象：键 → 对象）"
            return len(d), "个键（顶层对象）"
        return 0, "未知"
    except Exception as e:
        return None, f"读不了（{type(e).__name__}）"


def fields_of(path: pathlib.Path) -> list:
    """取字段名（jsonl 取第一条的键；json 取顶层结构）。

    ⚠️ **顶层是 dict 时，别把键当字段** ——
    `quote-repairs.json` 的顶层是 {缓存键: {q,kind,ev}}，
    15,282 个缓存键被当成字段名，字段列表瞬间涨到 455 KB
    （占整个清单的 95%）。这种情况要报**值的结构**。
    """
    try:
        if path.suffix == ".jsonl":
            with path.open(encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        return list(json.loads(line).keys())
            return []
        d = json.load(path.open(encoding="utf-8"))
        if isinstance(d, dict):
            # 顶层键是**子表名**（page-index 的 _pages/_byConcept）还是**数据行**？
            # 判据：值是 dict 且它的键看起来像字段名（短、不是 id）→ 子表
            # 值是 dict 且键是长串 id → 数据行，报值的结构
            subtables = {k: v for k, v in d.items() if k.startswith("_")}
            if subtables:
                return list(d.keys())
            # 所有值都是 dict → 报第一个值的结构
            for v in d.values():
                if isinstance(v, dict) and v:
                    return list(v.keys())
            return list(d.keys())
        if isinstance(d, list) and d and isinstance(d[0], dict):
            return list(d[0].keys())
        return []
    except Exception:
        return []


def sample_of(path: pathlib.Path):
    """取一条样本（截断长文本）。"""
    try:
        if path.suffix == ".jsonl":
            with path.open(encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        return json.loads(line)
            return None
        d = json.load(path.open(encoding="utf-8"))
        if isinstance(d, list) and d:
            return d[0]
        if isinstance(d, dict):
            for k, v in d.items():
                if isinstance(v, list) and v:
                    return {k: v[0]}
            return {k: (v if not isinstance(v, (dict, list)) else f"<{type(v).__name__}>")
                    for k, v in d.items()}
        return None
    except Exception:
        return None


def trim(obj, limit=260):
    """截断长字符串，让样本行能一眼看完。"""
    if isinstance(obj, dict):
        return {k: trim(v, limit) for k, v in list(obj.items())[:14]}
    if isinstance(obj, list):
        return [trim(v, limit) for v in obj[:3]]
    if isinstance(obj, str) and len(obj) > limit:
        return obj[:limit] + f"…（共 {len(obj)} 字）"
    return obj


def git_tracked(rel: str) -> bool:
    r = subprocess.run(["git", "ls-files", "--error-unmatch", rel],
                       cwd=BASE, capture_output=True)
    return r.returncode == 0


def build() -> dict:
    entries = []
    for path in sorted(DATA.glob("*.jsonl")) + sorted(DATA.glob("*.json")):
        if path.name in ("DATASETS.json",):
            continue
        if path.name == "quote-repairs.json" and False:
            continue
        rel = f"data/{path.name}"
        n, unit = count_records(path)
        desc = DESC.get(path.name)
        entries.append({
            "file": rel,
            "name": path.name,
            "what": desc[0] if desc else "",
            "use_for": desc[1] if desc else "",
            "how_to_use": desc[2] if desc else "",
            "records": n,
            "unit": unit,
            "bytes": path.stat().st_size,
            "format": "jsonl（每行一条）" if path.suffix == ".jsonl" else "json",
            "fields": fields_of(path),
            "sample": trim(sample_of(path)),
            "in_git": git_tracked(rel),
            "kind": "data",
            "critical_note": "",
        })

    for rel, (what, use_for, how_to_use, note) in EXCEPTIONS.items():
        path = BASE / "data" / rel
        if not path.exists():
            continue
        n, unit = count_records(path)
        entries.append({
            "file": f"data/{rel}",
            "name": rel.split("/")[-1],
            "what": what,
            "use_for": use_for,
            "how_to_use": how_to_use,
            "records": n,
            "unit": unit,
            "bytes": path.stat().st_size,
            "format": "json",
            "fields": fields_of(path),
            "sample": trim(sample_of(path)),
            "in_git": git_tracked(f"data/{rel}"),
            "kind": "不可再生（gitignore 白名单）",
            "critical_note": note,
        })

    entries.sort(key=lambda e: (e["kind"] != "data", -e["bytes"]))
    return {
        "generated_by": "src/build_datasets_catalog.py",
        "note": ("这份清单是**现算**的 —— 条数 / 体积 / 字段 / 样本 "
                 "都从真实文件读出来，改了数据重跑一次就同步。"
                 "人话说明（what / use_for / how_to_use）是唯一手写的部分。"),
        "how_to_pick": [
            "「我要某节课讲了什么」→ lessons.jsonl（人教）/ lessons-sh.jsonl（沪教）",
            "「我要这个概念的教材原话」→ concept-text.jsonl（人教）/ concept-text-sh.jsonl（沪教）",
            "「我要公式和图形」→ concept-vision*.jsonl",
            "「我要自学一个概念」→ learn-cards.jsonl（**六个面一次给全**）",
            "「这个概念在教材哪几页」→ page-index.json",
            "「这个概念前面该学什么」→ learn-cards.jsonl 的 prereq 面"
            "（跟站点「学习路径」面板同源）",
            "「用自己的话问教材」→ Milvus 层（可选，见 README 九之四）",
        ],
        "datasets": entries,
    }


def render_markdown(cat: dict) -> str:
    """生成给人看的「数据一览」表（贴进 README）。"""
    lines = []
    lines.append("| 数据集 | 是什么 | 条数 | 体积 | 怎么取 |")
    lines.append("|---|---|---|---|---|")
    for e in cat["datasets"]:
        what = e["what"].replace("**", "")
        how = e["how_to_use"].replace("**", "")
        if len(what) > 42:
            what = what[:42] + "…"
        if len(how) > 40:
            how = how[:40] + "…"
        rec = f"{e['records']:,}" if isinstance(e["records"], int) else "?"
        kb = e["bytes"] / 1024
        size = f"{kb/1024:.0f} MB" if kb >= 1024 else f"{kb:.0f} KB"
        lines.append(f"| `{e['file']}` | {what} | {rec} | {size} | {how} |")
    return "\n".join(lines)


def main() -> int:
    out = build()
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    MD = BASE / "docs" / "data-catalog.md"
    md = ["# 数据一览（自动生成）", "",
          "> 由 `python3 src/build_datasets_catalog.py` 生成 —— "
          "**别手改**，改数据后重跑一次。",
          "> 机器可读版：`data/DATASETS.json`（含样本行和字段表）。", "",
          render_markdown(out), "",
          "## 按需求查", ""]
    md += [f"- {x}" for x in out["how_to_pick"]]
    md += ["", "## 不可再生的那两个", "",
           "这两个在 `data/normalized/` 里（那个目录整个 gitignore 了），",
           "但它们**是一次性产出，丢了就永久没了** —— 所以 .gitignore 里开了白名单。", ""]
    for e in out["datasets"]:
        if e.get("critical_note"):
            md.append(f"- **`{e['file']}`** —— {e['critical_note']}")
    md.append("")
    MD.write_text("\n".join(md), encoding="utf-8")
    print(f"人读版 → {MD}")
    n = len(out["datasets"])
    total = sum(e["bytes"] for e in out["datasets"])
    print(f"数据清单 → {OUT}（{n} 个数据集，合计 {total/1024/1024:.0f} MB）")
    print()
    for e in out["datasets"]:
        rec = f"{e['records']:,}" if isinstance(e["records"], int) else "?"
        flag = "✓" if e["in_git"] else "·"
        print(f"  {flag} {e['file']:44s} {rec:>10s}  {e['bytes']/1024:8.0f}K")
    missing = [e["file"] for e in out["datasets"] if not e["what"]]
    if missing:
        print(f"\n！有 {len(missing)} 个文件没有说明（补进 DESC）：")
        for m in missing:
            print(f"    {m}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
