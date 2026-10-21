# 给 agent 用的教材数据

> 中文 K12 教材（人教版为主，含沪科/冀教/北京/华东师大/青岛等版本）
> 转成结构化数据。**10,045 页 · 1,347 个概念拿到教材原话 · 291 个概念拿到教材的定义句。**
> 另有**视觉层**：让多模态模型直接读扫描页，把 OCR 丢掉的**公式和图形**捞回来。

## 为什么不是「把 PDF 抽成文本」

抽文本对人眼够用、对 agent 不够。实测人教七下的 OCR：

- 汉字占比只有 **64.8%**
- **公式是不可恢复的**：`S=ah` 被抽成「S一ah」，`am` 成「已m」
- **图形整个丢了**：正文里全是「如图」「下图」，图在哪、什么形状，一个字都没留下

所以「全文」这条路做不出高质量。但有一件事**可以**做到高质量：
**图谱里已经有 8,590 个概念名和它们的教材位置** ——
拿这些名字当锚点，就能回答「教材在这个概念周围到底说了什么」。

公式丢了不要紧。视频稿要的是**「教材的原话 + 第几页 + 第几节」**，那部分是可以拿回来的。

## 四个产物

OCR 层两个（`lessons.jsonl` + `concept-text.jsonl`），
视觉层两个（`vision-pages.jsonl` + `concept-vision.jsonl`）。下面分开讲。

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

## 数据规模与成色

### OCR 层

| | |
|---|---|
| 页 | **10,045**（人教 30 册 4,410 + 其他版本 33 册 5,635） |
| 质量 ≥0.9 的页 | 8,671（86%） |
| 质量 <0.5 的页 | 201（2%） |
| 认出章名的页 | 1,825（人教版部分；其他版本的页眉排版不同，认出的少） |
| 目录页（已排除） | 337 |
| 拿到教材原话的概念 | **1,347** / 8,590（15.7%），其中 1,307 个有正文引文 |
| ├ 有定义句的 | **291** |
| ├ 精确匹配 | 1,176 |
| └ 模糊匹配（相似度 ≥0.72） | 171 |
| 总引文 | 5,537（平均每概念 4.1 条） |

按学科：数学 470 · 生物 377 · 化学 360 · 物理 140。

### 视觉层

| | |
|---|---|
| 已跑页 | **4,390**（人教 31 册全量：小学数学 12 册 · 初中 9 册 · 高中数学 5 册 · 物理 2 册 · 化学 2 册 · 生物 4 册） |
| 解析成功 | 4,390（100%） |
| ├ 有公式的页 | 2,521（57%） |
| └ 有图的页 | 3,451（79%） |
| 公式 | 20,801 条 |
| 图 | 7,165 个 |
| 表格 | 1,047 张 |
| 例题/思考/探究 | 11,712 道 |
| 挂上概念 | **403** 个（精确 375 · 模糊 0 · 宽泛 28） |
| ├ 带公式的概念 | 333 |
| └ 带图描述的概念 | 375 |

其他版本（沪科/冀教/湘教/浙教/华东师大/北京/苏科/青岛，共 45 册 7,597 页）
在后台跑，**跑到哪算哪**，实际覆盖看 `data/vision-cover-alt.json`。

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
- **其他版本的 18 本扫描件还没 OCR**（浙教/湘教/华东师大/苏科版多数）。
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

## 数据来源与许可

教材 PDF 来自 [ChinaTextbook](https://github.com/TapXWorld/ChinaTextbook)（开源镜像），
**不随本仓库分发**。知识点数据来自
[K12-KGraph](https://github.com/haolpku/K12-KGraph)（北京大学 PKU-DCAI，
arXiv:2605.09635，CC BY-NC-SA 4.0）。
