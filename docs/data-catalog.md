# 数据一览（自动生成）

> 由 `python3 src/build_datasets_catalog.py` 生成 —— **别手改**，改数据后重跑一次。
> 机器可读版：`data/DATASETS.json`（含样本行和字段表）。

| 数据集 | 是什么 | 条数 | 体积 | 怎么取 |
|---|---|---|---|---|
| `data/concept-vision-sh.jsonl` | 概念的公式 / 图形语义 / 例题（沪教版） | 3,453 | 20 MB | 按 id 取；字段同上 |
| `data/learn-cards.jsonl` | 知识点自学卡，一个概念一张 | 8,590 | 17 MB | 按 id 或 name 取；what/how/practice/prereq/w… |
| `data/vision-pages-alt.jsonl` | 页面的视觉层（其他出版社版本） | 7,784 | 16 MB | 按 id 取，id 里的出版社前缀要分清 |
| `data/vision-pages-sh.jsonl` | 页面的视觉层（沪教版） | 9,009 | 15 MB | 按 id 取 |
| `data/concept-vision.jsonl` | 概念的公式 / 图形语义 / 例题（人教版） | 2,012 | 14 MB | 按 id 取；formulas 是 LaTeX，figureDescriptio… |
| `data/lessons.jsonl` | 教材正文，一页一条（人教版） | 12,939 | 14 MB | 按 id 直接取：math-9a-p102 |
| `data/lessons-sh.jsonl` | 教材正文，一页一条（沪教版/沪科版） | 9,009 | 12 MB | 按 id 直接取：sh-hk-物理-w-8b-p52 |
| `data/vision-pages.jsonl` | 页面的视觉层（人教版）—— 一页一条 | 4,390 | 8 MB | 按 id 取 |
| `data/shanghai-graph.json` | 上海版图谱（节点 / 单元链 / 先修边） | 5,552 | 8 MB | nodes / edges / units 三段 |
| `data/page-index.json` | 概念 → 教材页反查表 | 11,052 | 7 MB | _byConcept[概念id] → [{book,page,pageId,te… |
| `data/concept-text-sh.jsonl` | 概念的教材原话，一个概念一条（沪教版） | 2,114 | 1 MB | 按 id 取；这层用 books + pages 记位置（印刷页码，不是扫描页码… |
| `data/vision-pages-kx.jsonl` | 页面的视觉层（小学科学） | 1,036 | 1 MB | 按 id 取 |
| `data/quote-repairs.json` | 引文的最终判定缓存 | 15,282 | 1 MB | 顶层是 {缓存键: {q, kind, ev}}；缓存键 = “版本#概念id#… |
| `data/concept-text.jsonl` | 概念的教材原话，一个概念一条（人教版） | 1,361 | 1 MB | 按 id 或 name 取；quotes 里有原话，quoteKinds 标了哪… |
| `data/kx-ocr.jsonl` | 小学科学教材的OCR 正文 | 1,036 | 646 KB | 按 id 取 |
| `data/learn-questions.jsonl` | 可自动判分的练习题（从教材原话 / 图谱定义反推） | 397 | 275 KB | 按 concept 字段取概念名；type=choice 时 options +… |
| `data/concept-vision-kx.jsonl` | 小学科学概念的公式 / 图形 / 例题 | 146 | 252 KB | 按 id 取 |
| `data/shanghai-toc.json` | 上海教材的目录（26 本 / 521 节） | 2 | 192 KB | 按 book 取 |
| `data/alt-align.json` | 跨版本对照（人教节 ↔ 其他版本节） | 4 | 140 KB | byConcept[概念id] → [{label, alt, chapter}… |
| `data/alt-editions.json` | 其他版本教材的视觉层 | 8 | 101 KB | 顶层是数组 |
| `data/vision-cover-alt.json` | 教材封面图（其他版本） | 4 | 100 KB | 顶层是数组 |
| `data/rjb-book-candidates.json` | 平台上同名教材的候选清单（人教版 31 册） | 23 | 86 KB | 按册次取：{册次: {ours: 本地 PDF, candidates: 平台候… |
| `data/shanghai-textbook-catalog.json` | 上海教材清单 | 298 | 85 KB | 顶层是数组 |
| `data/vision-cover.json` | 教材封面图（人教版） | 4 | 57 KB | 顶层是数组 |
| `data/kx-graph.json` | 小学科学独立图谱（67 节点 / 25 边） | 67 | 48 KB | nodes / edges |
| `data/page-images-rjb.json` | 人教版教材原页图索引（31 册 / 1,128 页） | 31 | 45 KB | 按册次取：{[册次]: {扫描页: 'data/pages/…/N.webp'}… |
| `data/page-images.json` | 教材原页图的直链基址（67 本沪教教材） | 67 | 33 KB | 按 bookId 取；拼图地址 = base + '/' + 扫描页码 + '.… |
| `data/shanghai-textbooks.json` | 上海教材的元信息 | 67 | 33 KB | 顶层是数组 |
| `data/kx-sections.json` | 小学科学的节判定（105 节） | 105 | 31 KB | 顶层是数组 |
| `data/kx-toc.json` | 小学科学的目录（含页码偏移实测值） | 12 | 27 KB | 按 book 取 |
| `data/alt-editions-manifest.json` | 其他版本教材的清单 | 1 | 20 KB | 顶层是数组 |
| `data/textbook-editions.json` | 教材版本指纹 | 8 | 17 KB | 顶层是数组 |
| `data/l0-abilities.json` | 能力底座（L0 层） | 20 | 12 KB | 顶层是数组 |
| `data/intro-links.json` | 教材的引入路径（概念 → 首次出现的那一课） | 25 | 11 KB | 顶层是数组 |
| `data/cover-gaps.json` | 封面缺口清单 | 17 | 10 KB | 顶层是数组 |
| `data/shanghai-rjb-positions.json` | 人教版前置节点在沪教教材里的真实位置 | 34 | 9 KB | 按上游概念 id 取：给出沪教版别、册次、证据档 |
| `data/kx-visual-books.json` | 小学科学视觉层用到的书 | 12 | 6 KB | 顶层是数组 |
| `data/kx-textbooks.json` | 小学科学教材清单（12 本） | 12 | 6 KB | 顶层是数组 |
| `data/page-offsets-sh.json` | 沪教版每册的印刷页码偏移 | 44 | 1 KB | 按沪教书号取：{sh-hj-数学-w-7b: -7}。从平台 OCR 的页脚行取… |
| `data/learn-videos.json` | 讲解视频索引（按知识点挂载外部视频） | 4 | 1 KB | 改完不用重建数据层 —— 学习页运行时读这个文件 |
| `data/page-offsets.json` | 人教版每册的印刷页码偏移 | 31 | 1 KB | 按册次取：{册次: 负数}。矢量册从 PDF 页脚取页码，扫描件走 OCR（脚本… |
| `data/normalized/selfbuilt-edges.json` | 自建先修边（13,461 条，模型重建） | 13,461 | 4 MB | edges 数组；source 字段标来源（model / derived / … |
| `data/normalized/confirmed-wrong.json` | 人工逐条裁决的账本 | 25 | 8 KB | 顶层数组，每条记了裁决理由 |

## 按需求查

- 「我要某节课讲了什么」→ lessons.jsonl（人教）/ lessons-sh.jsonl（沪教）
- 「我要这个概念的教材原话」→ concept-text.jsonl（人教）/ concept-text-sh.jsonl（沪教）
- 「我要公式和图形」→ concept-vision*.jsonl
- 「我要自学一个概念」→ learn-cards.jsonl（**六个面一次给全**）
- 「这个概念在教材哪几页」→ page-index.json
- 「这个概念前面该学什么」→ learn-cards.jsonl 的 prereq 面（跟站点「学习路径」面板同源）
- 「用自己的话问教材」→ Milvus 层（可选，见 README 九之四）

## 不可再生的那两个

这两个在 `data/normalized/` 里（那个目录整个 gitignore 了），
但它们**是一次性产出，丢了就永久没了** —— 所以 .gitignore 里开了白名单。

- **`data/normalized/selfbuilt-edges.json`** —— 在 .gitignore 里有白名单 —— **不可再生**，删了构建会永久降级
- **`data/normalized/confirmed-wrong.json`** —— 在 .gitignore 里有白名单 —— **不可再生**，人工裁决一次就一次
