# 给 agent 用的教材数据

> 中文 K12 教材（人教版为主，含沪科/冀教/北京/华东师大/青岛等版本）
> 转成结构化数据。**10,045 页 · 1,347 个概念拿到教材原话 · 291 个概念拿到教材的定义句。**
> 另有**视觉层**：让多模态模型直接读扫描页，把 OCR 丢掉的**公式和图形**捞回来。

## 先看这个：`data/DATASETS.json`

**这个仓库有 35 个数据集、142 MB，字段结构有 7 种以上。**
不知道该用哪个的话，**读这一个文件就够** —— 它列了每个数据集：

- 是什么（`what`）、能回答什么问题（`use_for`）、怎么取（`how_to_use`）
- 多少条、什么字段、一条样本长什么样
- 顶层还有 `how_to_pick`：**按你的需求直接查表**

```python
import json
cat = json.load(open("data/DATASETS.json", encoding="utf-8"))
for d in cat["datasets"]:
    if "公式" in d["what"]:
        print(d["file"], d["records"], d["fields"])
```

它是**现算**的（`src/build_datasets_catalog.py` 从真实文件读条数/字段/样本），
所以不会跟实际数据漂移。

## 下面按层讲

OCR 层两个（`lessons.jsonl` + `concept-text.jsonl`），
视觉层两个（`vision-pages.jsonl` + `concept-vision.jsonl`）。
后面还有学习卡（⑥）、页索引、Milvus 层（可选）——
**完整清单看上面的 `data/DATASETS.json`。**

### 为什么不是「把 PDF 抽成文本」

抽文本对人眼够用、对 agent 不够。实测人教七下的 OCR：

- 汉字占比只有 **64.8%**
- **公式是不可恢复的**：`S=ah` 被抽成「S一ah」，`am` 成「已m」
- **图形整个丢了**：正文里全是「如图」「下图」，图在哪、什么形状，一个字都没留下

所以「全文」这条路做不出高质量。但有一件事**可以**做到高质量：
**图谱里已经有 8,590 个概念名和它们的教材位置** ——
拿这些名字当锚点，就能回答「教材在这个概念周围到底说了什么」。

公式丢了不要紧。视频稿要的是**「教材的原话 + 第几页 + 第几节」**，那部分是可以拿回来的。

### ① `data/lessons.jsonl` —— 一页一条（教材的「课」）

agent 想读「第 22 章第 2 节这一课到底讲了什么」，读一条就行。

```json
{"id":"math-9a-p102","book":"9a","subject":"math","page":102,
 "chapter":"第二十二章 二次函数","text":"…这一页的正文…",
 "sentences":23,"concepts":["二次函数","抛物线","顶点"],
 "quality":0.97,"cjkRatio":0.81,"isToc":false,
 "source":"rjb-math-9a.txt"}
```

| 字段 | 含义 |
|---|---|
| `id` | `<出版社>-<学科>-<册次>-p<页码>`，**全局唯一**（册次码跨学科复用，必须带学科） |
| `chapter` | 从**页眉**认出的章名（教材每页页眉都写着第几章） |
| `concepts` | 这一页提到的概念 id 对应的**名字** |
| `quality` | 0~1，**噪声率**（不是汉字占比 —— 数学书的公式本来就该是拉丁字符） |
| `cjkRatio` | 汉字占比，只作参考 |
| `isToc` | 是不是目录页 —— 目录里概念名全都会「出现」，但那不是正文 |

### ② `data/concept-text.jsonl` —— 一个概念一条（按概念索引）

agent 想写「二次函数的视频稿」，直接拿这条就有**教材原话 + 页码 + 第几节**。

```json
{"id":"biology_7b_rjb_cpt66","name":"呼吸道对空气的处理",
 "subject":"biology","book":"7b","bookZh":"七下",
 "chapter":"", "pages":[3,44,46], "mentions":6,
 "quotes":["第一节”呼吸道对空气的处理"],
 "quoteKinds":["text"], "hasDefinition":false,
 "match":"exact","quality":0.748,"source":"rjb-bio-7b.ocr.txt"}
```

| 字段 | 含义 |
|---|---|
| `quotes` | 教材原话，按**类型**排序（定义句 → 定理句 → 正文 → 例题 → 习题） |
| `quoteKinds` | 与 `quotes` 一一对应：`definition` / `theorem` / `text` / `example` / `question` / `title` |
| `hasDefinition` | **有没有教材自己的定义句** —— 写稿最值钱的就是这个 |
| `match` | `exact`（名字字面出现在教材里）/ `fuzzy`（相似度 ≥0.72 的近似句） |
| `pages` | 这个概念出现在哪几页 |
| `mentions` | 一共提到多少次 |

## 视觉层：把公式和图形捞回来

### 为什么需要这一层

OCR 的物理上限是硬的。人教九上 PDF 的**文本层本身就是坏的** ——
公式字体的 ToUnicode 表缺失，取出来是 `!"#$%&'"()*` 和私用区字符：

```
OCR 版:   狔＝狓２   犪狓２＋犫狓＋犮   →  变量、上下标、公式全废
视觉版:   y = x^2    ax^2 + bx + c      →  LaTeX 完整
```

而且图形整个丢了 —— 正文里只剩「如图」「下图」，图里画了什么一个字都没留下。

**但这些扫描件本身是清楚的**。把页面渲染成图，让多模态模型直接看，
公式、坐标系、几何图形、表格都能读出来。这不是「把 PDF 抽成文本」，
是**换一条信息通道**：OCR 读的是编码，视觉读的是版面。

实测人教九上 p45（顶点式），同一页：

| | OCR | 视觉 |
|---|---|---|
| 公式 | `狔＝狓２` 之类残骸 | `y = \frac{1}{2}(x-6)^2 + 3`、`y = a(x-h)^2 + k` |
| 顶点 | 无 | `(6, 3)` |
| 对称轴 | 无 | `x = 6`（图上的天蓝色虚线） |
| 表格 | 无 | x=3..9 对应 y=7.5, 5, 3.5, 3, 3.5, 5, 7.5 |
| 练习 | 无 | 探究栏目「讨论 y = -2x²-4x+1 的图象和性质」 |

几何页同样管用。八下 p30（图 17.1-6 赵爽弦图）视觉能读出：
四个全等直角三角形（红色）+ 正方形（黄色）、(1)(2)(3) 三步割补、
带旋转平移弧线箭头、面积关系 a²+b²=c²；练习第 2 题的勾股树
（A/B/C/D 四个正方形挂在直角边上、最大正方形 E 在最下方）也认出来了。

### ③ `data/vision-pages.jsonl` —— 一页一条（视觉层的「课」）

```json
{"id":"math-9a-p45","book":"math-9a","subject":"math","bookZh":"九年级上册",
 "publisher":"人教版","page":45,"ok":true,
 "data":{
   "formulas":[{"latex":"y = \\frac{1}{2}x^2 - 6x + 21","context":"直接画图的二次函数解析式"},
               {"latex":"y = a(x - h)^2 + k","context":"二次函数的顶点式形式"}],
   "figures":[{"caption":"图 22.1-10","kind":"坐标系",
               "description":"平面直角坐标系…开口向上的粉红色抛物线，并标注了顶点 (6, 3)…"}],
   "tables":[{"caption":"先利用图象的对称性列表",
              "rows":[["x","3","4","5","6","7","8","9"],["y = \\frac{1}{2}(x-6)^2+3","7.5","5","3.5","3","3.5","5","7.5"]]}],
   "exercises":[{"type":"探究","stem":"你能用上面的方法讨论二次函数 y = -2x^2 - 4x + 1 的图象和性质吗？","steps":[]}]}}
```

| 字段 | 含义 |
|---|---|
| `formulas[].latex` | **页面上抄下来的公式**，LaTeX，可直接引用 |
| `formulas[].context` | 这条公式在页面上的位置/用途（模型写的定位说明） |
| `figures[].description` | **模型对图的转述**，不是教材原话 —— 引用必须标来源 |
| `tables[].rows` | 表格数据，抄自页面 |
| `exercises[].stem` | 例题/思考/探究/练习的题干，抄自页面 |

### ④ `data/concept-vision.jsonl` —— 一个概念一条（按概念索引）

```json
{"id":"math_9a_rjb_cpt48","name":"二次函数","subject":"math","book":"9a","bookZh":"九年级上册",
 "match":"exact","pages":[36,37,38,...],
 "bySource":{"math-9a":{"publisher":"人教版","bookZh":"九年级上册","pages":[36,37,38,...]}},
 "formulas":["y = ax^2","y = a(x - h)^2 + k","y = ax^2 + bx + c","x = -\\frac{b}{2a}"],
 "figureDescriptions":[{"caption":"图 22.1-10","kind":"坐标系","description":"…","provenance":"described"}],
 "exercises":[{"type":"探究","stem":"…","provenance":"page"}],
 "counts":{"formulas":4,"figures":12,"exercises":7,"tables":0}}
```

| 字段 | 含义 |
|---|---|
| `bySource` | **哪个出版社哪一册的第几页** —— 页码不能脱离来源看 |
| `formulas` | 该概念周围的 LaTeX 公式（**页面原文**） |
| `figureDescriptions` | 图形描述，带 `provenance:"described"` —— **模型转述，不是教材原话** |
| `exercises` | 题目原文，带 `provenance:"page"` |
| `match` | `exact`（名字字面出现在页里）/ `fuzzy`（相似度 ≥0.72） |

### 一个原则：原文和转述必须分开标

这个项目的史实铁律是「数字回一手」。视觉层里两类东西混在一起会出事：

- **公式 LaTeX、例题题干、表格数据** —— 从页面上抄下来的，**可以直接引用**
- **图形描述** —— 模型用文字**转述**图里画了什么，**不是教材原话**
  （教材只印了图，压根没有这段文字）

所以每条都有 `provenance` 字段。agent 要写「教材说…」时只能用 `page` 的；
要描述「图上是什么」时用 `described` 的，并且要写明「据图」。



## 怎么用

```python
import json

# 写视频稿：拿概念 + 教材定义句
for line in open("data/concept-text.jsonl", encoding="utf-8"):
    r = json.loads(line)
    if r["name"] == "二次函数":
        for q, k in zip(r["quotes"], r["quoteKinds"]):
            if k == "definition":
                print("教材原话：", q, "（", r["bookZh"], r["chapter"], "）")
```

```python
# 写视频稿：再补上教材的公式和图（视觉层）
for line in open("data/concept-vision.jsonl", encoding="utf-8"):
    r = json.loads(line)
    if r["name"] == "二次函数":
        for f in r["formulas"]:
            print("教材公式：", f)          # ← 页面原文，可直接引用
        for fig in r["figureDescriptions"]:
            print("据图：", fig["description"])   # ← 模型转述，引用要标「据图」
        for src, info in r["bySource"].items():
            print("出处：", info["publisher"], info["bookZh"], info["pages"][:8])
```

```bash
# 查某个概念在教材里出现在哪几页
grep '"name":"二次函数"' data/concept-text.jsonl | python3 -m json.tool

# 查某个概念周围的公式
grep '"name":"二次函数"' data/concept-vision.jsonl | python3 -c \
  "import json,sys; print(json.load(sys.stdin)['formulas'])"
```

---

## ⑤ `data/learn-cards.jsonl` —— 一个概念一张「自学卡」

> **这是给「我要自学这个概念」用的**，不是给「我要查这个概念」用的。
>
> 前面四层是**按页存、按概念索引**的原始素材 ——
> 拿到「浮力」这个概念，能翻出 10 条图描述、12 道例题、5 句教材原话，
> **哪个该用、哪个是噪声，得自己判断**。
> 这一层把判断做在数据里：一次拿一张卡，五个面都齐，
> 每段都带来源标记。

需求清单见 `docs/需求清单.md` 的 R-1。

### 一张卡长什么样

```json
{
  "id": "physics_8b_rjb_cpt51",
  "name": "浮力",
  "subjectZh": "八下", "bookZh": "八下", "label": "八下·概念",
  "what": [
    {"text": "浸在液体或气体中的物体受到向上的力，浮力大小等于…",
     "kind": "图谱定义", "source": "图谱定义", "edition": "上游 K12-KGraph"},
    {"text": "上端开口、下端连通的容器叫做连通器…",
     "kind": "教材定义句", "source": "教材原话·人教版", "edition": "人教版"}
  ],
  "how": {
    "formulas": [{"text": "F_浮 = G_排", "source": "教材原书上的公式"}],
    "figures":  [{"caption": "图10.1-2 测量铝块所受的浮力",
                  "text": "包含甲、乙两幅图：甲图展示…",
                  "source": "教材原书上的图（据图）", "tier": "topical"}]
  },
  "practice": [{"text": "…", "source": "教材例题·人教版"}],
  "prereq":   [{"id": "physics_8b_rjb_cpt16", "name": "重力",
                "bookZh": "八下", "grade": 8, "src": "模型重建"}],
  "where":    [{"edition": "人教版", "bookZh": "八下",
                "chapter": "第十章 浮力", "pages": [48, 49, 50]}],
  "read":     [{"book": "physics-8b", "page": 52, "pageId": "physics-8b-p52",
                "text": "…教材原页上印着的那一段…",
                "source": "教材原页文字"}],
  "layers":   ["教材定义句", "图谱定义", "教材原书公式图", "教材例题"]
}
```

### 六个面分别是什么

| 面 | 是什么 | 来源标记 | 覆盖 |
|---|---|---|---|
| `what` | 「这是什么」 | 每段各带 `source` | 93.1% |
| `how` | 「怎么算」——公式 + 图形语义 | `教材原书上的公式` / `…（据图）` | 22.3% |
| `practice` | 「练一练」——例题题干 | `教材例题·人教版` | 20.7% |
| `prereq` | 「先补这些」——**直接前置** | 每条带 `src`（上游/模型重建/…） | 95.0% |
| `where` | 「在书里」——哪本书哪一页 | `edition` 字段 | 100% |
| `read` | 「读这段」——**教材原页上的那段话** | `教材原页文字` | 32.2% |

### `read` 这一面是怎么定位到页的

**不用页码换算** —— `lessons.jsonl` 的 `page` 是 **PDF 扫描序号**（1..163），
`concept-text.jsonl` 的 `pages` 是 **印刷页码**，两者不是一套，差多少每册都不同。

改用**引文反查**：概念的原话是教材原文的一段，
在页文本里找这段字，就知道它在第几页 —— 这比页码换算准。

⚠️ OCR 层有残骸（`1+2HO (NH),SO,+2NaoH` 这种），
建索引时按**汉字密度 ≥35%** 筛掉了 614 段。
给自学的人看等于给噪声，宁可不给。

### `source` 怎么读 —— **这一层最重要的事**

每个文本片段都有 `source`，**读的时候必须看**：

| `source` | 是什么 | 能当教材原文引用吗 |
|---|---|---|
| `教材原话·人教版` / `教材原话·沪教版` | **教材自己印的句子** | 能（标出处即可） |
| `图谱定义` | **数据集里的转述**，不是教材原话 | **不能** |
| `教材原书上的公式` | 教材原页上的公式（LaTeX） | 能 |
| `教材原书上的图（据图）` | **模型看图转述**的图形语义 | **不能**，要标「据图」 |
| `教材例题·人教版` | 教材上的例题题干 | 能 |

`what` 里的 `kind` 还分三级证据强度：

- `教材定义句` —— 教材**在给这个概念下定义**（证据最强）
- `教材提及句` —— 教材提到了它，但不是定义句
- `图谱定义` —— 数据集转述（证据最弱，但覆盖最全）

⚠️ **「图谱定义」不是教材原话。**
项目里上游定义跟教材印的经常不是一个说法（ISSUE-15 查过），
混起来就是在拿二手货冒充一手。

### `prereq` 为什么可信

「先补这些」**直接读站点已构建好的 payload**（`index.html` 的
`<script id="data">`），不是自己重算的。

站点的前置边表是「上游边 + 自建边合并 → 双向边对按来源优先级裁决
→ 环检测截断」的结果，跟 `data/normalized/graph.json` 里的原始边**不是一回事**。
自己重算一遍 = 两份实现 = 迟早对不上。

所以 `src/check_learn_cards.py` 的做法是：
**在真浏览器里加载站点页面，调它自己的 `pathRows()`，把输出跟学习卡逐条比。**
站点逻辑一改，这条检查立刻红。

### 空卡

591 个概念（6.9%）一层内容都没有。这时卡里有：

```json
"layers": [],
"emptyNote": "这一版没有这个概念的内容。教材原话、公式、例题三层都没召回 —— 不拿相邻概念的内容凑。"
```

⚠️ **空就说空** —— 不拿相邻概念的内容凑数。
上游概念名大量是改写过的（「ATP（能量储存形式）」），
教材里根本不这么写，所以有些概念真的召不回来。

### 怎么用

```python
import json

def card(name_or_id):
    for line in open("data/learn-cards.jsonl", encoding="utf-8"):
        r = json.loads(line)
        if r["name"] == name_or_id or r["id"] == name_or_id:
            return r
    return None

c = card("浮力")
if c and c["layers"]:
    for w in c["what"]:
        print(f"[{w['source']}] {w['text']}")
    for f in c["how"]["formulas"]:
        print(f"[{f['source']}] {f['text']}")
    for p in c["prereq"]:
        print(f"先补：{p['name']}（{p['src']}）")
else:
    print(c["emptyNote"] if c else "没这个概念")
```

```bash
# 全库统计：各面覆盖率
python3 src/check_learn_cards.py

# 重建（改完内容层之后）
python3 src/build_learn_cards.py
```

### 这层做过什么修正（2026-10-25）

四个问题都是**实测定位**的，不是猜的：

1. **前置链跟站点对不上** —— 原来只读 `graph.json` 的上游边（3,703 条），
   而站点用的是上游边 + 自建边（13,461 条）合并过环检测的结果，
   「浮力」的前置是空的（站点上明明有 3 个）。
   → 改成直接读站点 payload。
2. **例题一条都召不回来** —— 视觉层的例题字段叫 `stem`，不叫 `text`，
   按 `text` 取了 8,590 个空。
3. **教材原话答非所问** —— 「电阻」召回的是「内电阻」「电阻率」「电阻箱」。
   引文确实带 `definition` 标记，但**定义的对象不是这个概念**。
   → 改成按「定义对象 == 概念名（且独立成词）」筛，分三级证据强度。
4. **图/公式噪声** —— 视觉层的图描述带 `tier` 分级：
   `topical` = 这一页在讲这个概念；`broad` = 只有模型转述里提到概念名，
   页面本身跟它没关系。`broad` 的一律不要。

还有一件：教材原话里有一批**开头被 PDF 硬换行切掉**的
（「机物中的能量释放出来…」——原文是「有机物中的能量释放出来…」，
PDF 按版面宽度断行，切在了词中间）。
`src/quote_repair.py` 拿引文的**尾部**回原文的句表里找，
找到那句如果更长且**以引文结尾**，就是完整版 —— 补了 705 条（8.2%）。

⚠️ 补全的门槛是**「以引文结尾」**，不是「比引文长」。
用后者会拿到另一处**相似但不同**的句子
（「生态系统」那次就踩过：引文是「…形成的统一整体就是生态系统」，
原文另有一处「…所形成的统一的整体叫做生态系统」，两者不是同一句）。

⚠️ **只有人教版能补**。沪教版是页图 OCR，
断行位置跟版面无关，接回去是瞎接 —— 那一层保持原样。

⚠️ **补全依赖 `data/pdf-cache/`（教材 PDF，不入库）**，
所以最终判定结果落盘在 `data/quote-repairs.json`（15,282 条，1.2 MB）。
**没有这个缓存，换台机器 clone 下来跑出来的学习卡跟入库的不一样**
（实测差 313 张卡 —— 而且不只差在引文文本，
「补全后算定义句」和「原样算提及句」会让**下游分类也变**）。

缓存里存的是**从教材里抽出来的句子**（6.2 万字，最长 195 字），
不是教材原件 —— 可以入库，跟 `concept-text.jsonl` 同一性质。

---

## 数据规模与成色

### OCR 层

| | |
|---|---|
| 页 | **12,939**（人教 30 册 4,410 + 其他版本 45 册 8,529） |
| 质量 ≥0.9 的页 | 8,671（86%） |
| 质量 <0.5 的页 | 201（2%） |
| 认出章名的页 | 1,825（人教版部分；其他版本的页眉排版不同，认出的少） |
| 目录页（已排除） | 337 |
| 拿到教材原话的概念 | **1361** / 8,590（15.8%），其中 1300 个有正文引文 |
| ├ 有定义句的 | **291** |
| ├ 精确匹配 | 1,176 |
| └ 模糊匹配（相似度 ≥0.72） | 171 |
| 总引文 | 5,530（平均每概念 4.1 条） |

按学科：数学 470 · 生物 377 · 化学 360 · 物理 140。

### 视觉层

| | |
|---|---|
| 已跑页 | **12,174**（人教 31 册 4,390 页 + 其他版本 45 册 7,784 页） |
| 解析成功 | 12,174（100%） |
| ├ 有公式的页 | 2,521（57%） |
| └ 有图的页 | 3,451（79%） |
| 公式 | 20,801 条 |
| 图 | 7,165 个 |
| 表格 | 1,047 张 |
| 例题/思考/探究 | 11,712 道 |
| 挂上概念 | **1990** 个（精确 1862 · 模糊 0 · 宽泛 128） |
| ├ 带公式的概念 | 1163 |
| └ 带图描述的概念 | 1891 |

其他版本（沪科/冀教/湘教/浙教/华东师大/北京/苏科/青岛，共 45 册）
也跑完了：**7,784 页 / 100%**（视觉层 + OCR 原文都有）。

### 其他版本怎么讲同一个概念

`concept-text.jsonl` 里每条概念的 `otherEditions` 字段，装着**别的出版社**怎么讲它：

```json
{"id":"math_9a_rjb_cpt48","name":"二次函数",
 "quotes":["…叫做二次函数(ｑｕａｄｒａｔｉｃｆｕｎｃｔｉｏｎ)…"],
 "source":"rjb-math-9a.txt",
 "otherEditions":{"初中数学华东师大版":{"book":"九上","quotes":[
     "的学习中还有许多应用,例如下学期将要学习的二次函数(第26章),"]},
   "初中数学沪科技版":{"book":"九上","quotes":[…]}}}}
```

**跟 `quotes` 分开是必须的** —— `quotes` 是人教版这一本，
`source` 字段只有一个；混在一起 `source` 就说谎了。
现在有 **219 个概念**有其他版本的说法，覆盖 8 个出版社：

- 初中数学青岛版：137 个概念
- 初中数学冀教版：114 个概念
- 初中数学湘教版：111 个概念
- 初中数学华东师大版：109 个概念
- 初中数学沪科技版：96 个概念
- 初中数学北京版：84 个概念
- 初中数学人教版：78 个概念
- 初中数学浙教版：35 个概念

## 三件决定质量的事

**① 跑页眉。** 教材每页页眉都写着「第几章」，这是**最可靠的定位信号** ——
比目录可靠（目录在扫描件里常常是图形化的，OCR 抽不出来）。

**② 概念匹配分级。** 精确命中记 `exact`；名字对不上但有 ≥0.72 相似度记 `fuzzy`。
**匹配不上的宁可没有** —— 宁可缺，不能错（跟多版本教材对照一个原则）。

**③ 逐页质量分。** 只数明确的 OCR 垃圾模式（替换符、私用区、汉字夹 ASCII）。
汉字占比另算 `cjkRatio` —— 数学书里公式、字母、图注本来就该是拉丁字符，
拿汉字占比当质量主项会冤枉好页面。

## 几个坑（都踩过）

- **括号注释要去掉再匹配**：上游的概念名大量带括号
  （「营养（生物的生活需要营养）」），教材里只写「营养」——
  不去掉括号，生物化学的概念**一条都精确匹配不上**。
- **学科前缀要映射**：文件叫 `rjb-bio-7a`，图谱里学科是 `biology`；
  `rjb-chem` → `chemistry`、`rjb-phys` → `physics`。
- **册次码跨学科复用**：`7a` 既是数学七上、也是生物七上、还是物理八上。
  键和 id 一律用 (学科, 册次)，其他版本再加出版社名。
- **目录页不算正文**：目录里概念名全都会「出现」一次，但那是目录。
  判据不能靠点线引导 —— **OCR 把「……」整个丢了**；
  改用「**每行都以页码结尾**」。
- **整句就是概念名 → 是标题不是内容**，丢掉。

## 没做到的

- ~~**公式和图形不可恢复**。这是 OCR 的物理上限，不是调参能解决的。~~
  **→ 这句话只对 OCR 通道成立。** 换视觉通道（多模态模型直接读扫描页）
  可以把公式和图形捞回来，见上面的「视觉层」和 `data/concept-vision.jsonl`。
  仍然拿不到的是**版面级**信息（哪块是正文、哪块是图注），那个得靠版面分析。
- **概念覆盖率 15.7%**。剩下 84% 是因为上游的概念名是**改写过的**
  （「三角形的内角和」vs 教材的「三角形三个内角的和等于180°」），
  字面匹配不到，模糊匹配也够不着。
  **这本身就是一个结论**：教材跟图谱的命名差距，比想象中大得多。
- ~~**其他版本的 18 本扫描件还没 OCR**~~ → **已补完**（`src/ocr_alt.py`，
  18 本 2,894 页，用时 38 分钟）。
  OCR 完生成同名 `.txt` 后重跑 `pdf_to_units.py` 即可接上。
- **章名只在人教版认得准**（1,825/4,410）。其他版本的页眉排版不同，
  认出的比例低。

## 复现

```bash
# OCR 层：全量，约 15 秒
python3 src/pdf_to_units.py              # 全量，约 15 秒
python3 src/pdf_to_units.py --books math-7b   # 只跑一册

# 视觉层：渲染 → 上传 → 视觉问答（慢，几十页/分钟）
python3 src/vision_pages.py --books math-9a --pages 34-64
python3 src/vision_pages.py --books math-7a,math-7b,math-8a,math-8b,math-9a,math-9b \
        --pages all --jobs 3 --batch 5 --resume
python3 src/vision_to_concepts.py        # 把页面数据挂到概念上
```

教材 PDF 不入库（`data/pdf-cache/` 已 gitignore），渲染出的 PNG 也不入库。
数据集本身（`data/lessons.jsonl`、`data/concept-text.jsonl`、
`data/vision-pages.jsonl`、`data/concept-vision.jsonl`）**入库**，
agent 直接下 repo 就能用。

---

## ⑥ Milvus 数据库层 —— 想「查」而不只是「读文件」

> 前五层都是**文件**：agent 读 jsonl，人得自己写脚本过滤。
> 这一层是**数据库**：能用 SQL 查、能向量检索、能按字段筛。
>
> 起因：朋友是 **Milvus 生态负责人**，要拿这个项目来自学术理化。
> 需求清单见 `docs/需求清单.md` 的 R-3。

### 三张表

| 表 | 是什么 | 粒度 | 条数 |
|---|---|---|---|
| `kg_textbook` | 教材原文**段落** | 一段 | 57,904 |
| `kg_concept` | 知识点 | 一个概念 | 8,590 |
| `kg_prereq` | 先修边 | 一条边 | 17,164 |

### 起库

```bash
# 方式 A：milvus-lite（单文件，不需要 Docker —— 推荐先用这个）
python3 -m pip install milvus-lite "pymilvus==2.5.1"
python3 optional/milvus/build_milvus.py

# 方式 B：Milvus Standalone（Docker，多用户时用这个）
cd data/milvus && docker compose -f milvus-standalone.yaml up -d
MILVUS_BACKEND=server python3 optional/milvus/build_milvus.py
```

⚠️ **`milvus-lite` 的版本必须配 `pymilvus==2.5.1`** ——
配 3.0.2 会起不来（socket 连不上）。

### 查询

```bash
python3 optional/milvus/query_milvus.py "浮力"                       # 语义检索教材原文
python3 optional/milvus/query_milvus.py "浮力" --edition 人教版 --book 8b   # 加过滤
python3 optional/milvus/query_milvus.py --name 浮力                    # 按概念名精确查
python3 optional/milvus/query_milvus.py --prereq 浮力                  # 查前置关系
```

### 为什么是「混合检索」而不是纯向量

按 `milvus-workshop/agent/specs/15-retrieval-tier-selection.md` 的
检索复杂度阶梯（那份 spec 自己说：从阶梯顶端起步是**教学选择，不是工程默认**），
我们自己的实测：

| 方案 | 「BM25 找不到定义句」那批概念的召回 |
|---|---|
| 纯 BM25 | 5/5 命中（top-10 里有该概念自己的引文） |
| 纯语义（`nomic-embed-text`） | **0/15** —— 英文模型，「邻补角」召回「近似数」 |
| 纯语义（`qwen3-embedding:8b`） | 4/4 正确项排第一，但 10 秒/条 |
| 纯语义（`bge-m3`） | 5/5 正确项在 top-2，**0.05 秒/条** |

**BM25 和向量各管一段**：
BM25 抓字面重合（快、免费），
向量抓「换了说法」（慢、要嵌入）。
Milvus 的混合检索就是把这两条路并起来。

### 嵌入模型：本机 `bge-m3`，教材不出境

```bash
ollama pull bge-m3        # 1.2 GB
```

**教材有版权，不出境** —— 嵌入全在本机 Ollama 算完，只把向量存本地。

对比另两个本机模型：

| 模型 | 中文效果 | 速度 | 结论 |
|---|---|---|---|
| `nomic-embed-text`（274 MB） | **不行**，「邻补角」召回「近似数」 | 0.1 秒/条 | 英文模型，别用 |
| `qwen3-embedding:8b`（4.7 GB） | 好，4/4 | 10 秒/条 | 全量要 37 小时 |
| **`bge-m3`（1.2 GB）** | **好，5/5** | **0.05 秒/条** | **选它** |

`qwen3-embedding` 还有个 **MRL 特性**（能截到 512/256 维，质量不掉），
但 8B 模型再快也不如 1.2 GB 的 bge-m3。

### 三条硬边界

1. **版权页不能进库。** 教材前十几页是版权页 / 编者信息
   （「版权所有…未经许可不得另做他用」「美术编辑：…」）。
   这些页进向量库 = 检索时召回版权声明，
   而且**把教材版权信息复制进了数据库** ——
   项目一直守着「教材 PDF 不入库、只存抽出来的结构化事实」这条线，不能在这儿破。
   所以入库前按关键词 + 汉字密度筛掉（实测 21,948 页 → 57,904 段，版权页 0 条）。

2. **段落边界不能切在词中间。** 按**句末标点**切，
   切在词中间会产生假召回（"…叫做浮" 跟 "…叫做浮力" 会被判成同一段）。

3. **来源标记必须进表。** `edition` / `book` / `subject` / `page` / `chapter`
   都要有 —— 不然查到一段话也不知道出自哪本书。

### milvus-lite 踩过的坑（都在 `optional/milvus/build_milvus.py` 的注释里）

| 现象 | 原因 | 怎么办 |
|---|---|---|
| `No index found in field [vector]` | 建集合时没带 `index_params` | 建集合时就把索引一起建 |
| `cannot create index on non-existed field: vector` | schema 里漏了 `vector` 字段 | 检查字段列表 |
| `Failed to parse schema info` / `internal error` | **milvus-lite 不支持 `default_value`** | 缺值在数据层补（`_fill_missing`） |
| `Insert missed an field 'x'` | 记录缺字段 | 数据层补齐 |
| `Attempt to insert an unexpected field 'x'` | 记录多字段 | 同上 |
| `should create connection first` | 用了老的 `Collection()` ORM | 只用 `MilvusClient` |
| `Post "http://127.0.0.1:xxxx/tokenize": EOF` | Ollama 在切模型 / 负载高 | 嵌入加重试 + 拆批重试 |

### 数据来源与许可

教材 PDF 来自 [ChinaTextbook](https://github.com/TapXWorld/ChinaTextbook)（开源镜像），
**不随本仓库分发**。知识点数据来自
[K12-KGraph](https://github.com/haolpku/K12-KGraph)（北京大学 PKU-DCAI，
arXiv:2605.09635，CC BY-NC-SA 4.0）。
