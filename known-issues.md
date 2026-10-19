# 已知问题清单

数据源：**K12-KGraph**（北京大学 PKU-DCAI）
- arXiv: **2605.09635**（注意末尾那个 5，部分二手文章写成 2605.0963，那是一个完全不同的论文）
- HuggingFace: `lhpku20010120/K12-KGraph`
- 许可：**CC BY-NC-SA 4.0**（署名 + 非商用 + 相同方式共享）
- 原件落盘在 `data/raw/`，**一字未改**，校验全部在 `data/normalized/` 上跑

## 处置原则

**发现问题 ≠ 修改数据。**

本项目的立场是「提供校验层」，不是「重新标注数据库」。所以：

1. 原件 `data/raw/` 永远只读，不回写；
2. 发现的问题逐条记在这里：出处、错在哪、建议怎么改；
3. 校验层继续报警，不因为「已经知道了」就降级成 info；
4. `build_viz.py` 渲染前剪掉环边（只影响画面，不影响数据）。

改动原件的正确路径是给上游提 issue，不是自己悄悄修。

**已上报（2026-10-19）**，上游仓库 [`haolpku/K12-KGraph`](https://github.com/haolpku/K12-KGraph)：

| 上游 issue | 内容 | 对应本文件 |
|---|---|---|
| [#8](https://github.com/haolpku/K12-KGraph/issues/8) | `is_a` / `prerequisites_for` 各存在环，与论文 §10.2 的 DAG 检查描述不符 | ISSUE-01 / 02 / 04 |
| [#9](https://github.com/haolpku/K12-KGraph/issues/9) | 一上数学 6 个习题节点 `name` 为空，但被引用 16 次 | ISSUE-03 |

> 草稿原文存在 `docs/issue-1-dag-cycles.md` 和 `docs/issue-2-empty-nodes.md`，
> 复现脚本在两处都有，纯标准库、只依赖官方发布文件。

---

## ISSUE-01　互为前置：「极性分子」⇄「相似相溶规律」

**位置**：`chemistry_xzxbx2_rjb_cpt100` ⇄ `chemistry_xzxbx2_rjb_cpt108`（人教版化学·选择性必修二）

**性质**：概念 A 说「学 B 之前要先会 A」，概念 B 说「学 A 之前要先会 B」。逻辑上不可能同时成立。

**原件证据**（`data/raw/global_KG/edges.json`，已按 id 逐条比对确认，这两条边在官方原件里就有，**不是我们归一化时造出来的**）：

```json
{"source": "chemistry_xzxbx2_rjb_cpt100", "target": "chemistry_xzxbx2_rjb_cpt108", "type": "prerequisites_for"}
{"source": "chemistry_xzxbx2_rjb_cpt108", "target": "chemistry_xzxbx2_rjb_cpt100", "type": "prerequisites_for"}
```

**错在哪**：证据是同一句教材原文，两条边一字不差：

> 蔗糖、氨、水是极性分子，而萘、碘、四氯化碳是非极性分子。通过对许多实验的观察和研究，人们得出了一个经验性的"相似相溶"的规律……

这句话本身的逻辑顺序是：先有极性/非极性分子的分类，再**总结出**相似相溶规律。两个节点的 definition 也各自印证了这一点——

- `相似相溶规律`：「从分子结构角度**总结出的经验规律**」
- `极性分子`：「分子内正电中心和负电中心不重合……」

**结论**：`极性分子 → 相似相溶规律` 是对的；`相似相溶规律 → 极性分子` 是抽取时把同一句里后出现的词当成了前置。

**建议改法**：删掉 `cpt108 → cpt100` 这一条。

**附带发现**：同一句证据还锚定了第三条边 `非极性分子 → 相似相溶规律`，那一条是对的。也就是说模型读这一句话，产出了 3 条边、错 1 条。

---

## ISSUE-02　互为前置：「化学键能量变化与反应热」⇄「根据键能估算反应热」

**位置**：`chemistry_xzxbx1_rjb_cpt10` ⇄ `chemistry_xzxbx1_rjb_skl2`（人教版化学·选择性必修一）

同样在官方原件里：

```json
{"source": "chemistry_xzxbx1_rjb_skl2", "target": "chemistry_xzxbx1_rjb_cpt10", "type": "prerequisites_for"}
{"source": "chemistry_xzxbx1_rjb_cpt10", "target": "chemistry_xzxbx1_rjb_skl2", "type": "prerequisites_for"}
```

**错在哪**：一个是 Concept，一个是 Skill，两个节点的原文把方向说死了——

- `cpt10`（Concept）「掌握」：「化学反应中，化学键断裂需要吸收能量，化学键形成释放能量；……之差，体现了反应热。」
- `skl2`（Skill）「根据键能估算反应热」：「**列出**化学反应中所有将要断裂和形成的化学键，**利用**已知的平均键能数据，**计算**反应物中断键吸收的总能量和生成物中成键释放的总能量，**将两者相减**得到反应热的估算值。」

Skill 的每一个动词都建立在 Concept 之上。概念在先，技能在后。

**结论**：`cpt10 → skl2` 是对的；`skl2 → cpt10` 是多余的。

**建议改法**：删掉 `skl2 → cpt10` 这一条。

**与 ISSUE-01 的区别**：这一对的证据**不完全相同**（相似度 0.55）。两条边共享同一句结论——「上述分析表明，化学键断裂和形成时的能量变化是化学反应中能量变化的主要原因。」——但开头分别是两个不同例子的引导句。所以模型是从两处不同上下文各抽了一次，先修方向抽反了一次。

---

## ISSUE-03　6 个空名习题节点

**位置**：`math_1a_rjb_exe40` ~ `math_1a_rjb_exe45`（人教版数学一年级上册）

**现象**：`name` 字段是空字符串。官方原件 `data/raw/global_KG/nodes.json` 里同样为空，不是我们丢的。

**不是孤立的悬空点**——它们被引用了 **16** 次：

| 节点 | 引用 |
|---|---|
| `exe40` | `appears_in → 6和7`；`tests_concept → 6的加减法`；`tests_skill → 利用操作理解加减法` |
| `exe41` | `appears_in → 6和7`；`tests_concept → 分与合（拆分与组合）` |
| `exe42` | `appears_in → 6和7`；`tests_concept → 加法意义`；`tests_skill → 利用操作理解加减法` |
| `exe43` | `appears_in → 6和7`；`tests_concept → 6的加减法`；`tests_skill → 利用操作理解加减法` |
| `exe44` | `appears_in → 6和7`；`tests_concept → 分与合（拆分与组合）` |
| `exe45` | `appears_in → 6和7`；`tests_concept → 加法意义`；`tests_skill → 利用操作理解加减法` |

**推测**：这些是教材里没有标题的练习栏（「做一做」「练习」这类），抽取时正文抓到了、栏目标题没抓到，所以节点建出来了但名字空着。

**建议改法**：用被测概念 + 册次回填名字，例如「6和7的加减法（一上·练习）」。**不要直接删**——删了这 **16** 条 `tests_concept` / `tests_skill` / `appears_in` 边就全成了悬空边。

**当前处置**：不进画面。`build_viz.py` 只画 Concept 和 Skill，Exercise 本来就不画，所以这条不影响可视化。

---

## ISSUE-04　属种关系成环：「元素周期表」⇄「元素周期律」⇄「元素周期系」

**位置**：`chemistry_9a_rjb_cpt188` → `chemistry_bx1_rjb_cpt213` → `chemistry_xzxbx2_rjb_cpt28` → 回到起点

**现象**：三条 `is_a` 边构成一个环。
「元素周期表」is_a「元素周期律」，「元素周期律」is_a「元素周期系」，「元素周期系」is_a「元素周期表」。

**为什么是硬错误**：`is_a` 是严格层级关系——A is_a B 意味着 B 是 A 的一种，
反向就意味着 A 是 B 的一种。成环在语义上不可能成立，**不像 `relates_to`
那种对称关系成环无意义**。

**在原件里**：三条边在 `data/raw/global_KG/edges.json` 逐条确认存在，不是我们归一化造出来的。

**为什么之前没发现**：`validate.py` 原来只对 `prerequisites_for` 查环。
实测各边型的环数：

| 边型 | 边数 | 环 | 是否该报警 |
|---|---|---|---|
| `prerequisites_for` | 3,703 | 2 | 是（已在查） |
| `is_a` | 1,895 | **1** | 是（**漏了**） |
| `relates_to` | 2,174 | 17 | 否——语义对称，成环无意义 |
| `leads_to` / `verifies` / `tests_concept` / `tests_skill` / `is_part_of` / `appears_in` | — | 0 | — |

**当前处置**：`validate.py` 已补 `IS_A_CYCLE` 检查，归入硬错误。
已并入上游 [#8](https://github.com/haolpku/K12-KGraph/issues/8) 上报。

---

## ISSUE-05　`global_KG/` 从未被读入，静默丢掉 187 条跨学科边

**现象**：`data/raw/global_KG/edges.json` 有 **23,278** 条边，
`data/normalized/graph.json` 只有 **23,091** 条，差 **187** 条。

**丢的是什么**：全部是 `leads_to`，全部是**数学某章 → 物理某章**的跨学科进阶线，
例如 `math_7a_rjb_ch3 → physics_bx1_rjb_ch2`。
四个 `subject_specific_KG` 文件里跨学科边数为 0，所以不是被过滤掉的，
而是**整条输入源根本没进管线**：`src/normalize.py` 的 `RAW` 指向
`subject_specific_KG`，`data/raw/global_KG/` 没有任何代码打开过。

**为什么危险**：`report.json` 的 `rawEdgeSchemas` 只统计 subject_specific，
这 187 条的差集在报告里**完全不可见**。三处文档（`README.md` 写 global_KG
23,278 / 合计 23,091，`known-issues.md` 写 23,278）把两个数字并列印出来，
却没有任何一处解释这个差。

**已修（怎么修的）**：先抽了一层 `src/books.py` 做册次映射，再补读。

原来的映射写在 `normalize.py` 里、用 `list(BOOKS)` 的插入顺序当排名，
于是物理的「九年级」（整年本）rank 17，排在数学「九上」rank 18 **之前**——
单学科内看不出来，一引入跨学科边就会大面积误报。

`books.py` 把三个概念分开，不再混用：

| 字段 | 用途 | 口径 |
|---|---|---|
| `grade` | 画面分层（锥形高度） | 沿用既有口径，**不改** |
| `rank` | 同学科内排先后 | 全局教材序列 |
| `year` | 跨学科比学年 | 学年序 |

关键一条：**跨学科只比学年，不比册次**。不同学科在同一学年里的推进节奏本来
就不同，「数学九上早于物理九年级」这种比较在跨学科语境下没有意义 ——
把整年本和上下册硬排出先后只会造假警报。

**结果**：
- `graph.json` 边数 23,091 → **23,278**，与 `global_KG/edges.json` 精确一致
- `leads_to` 407 → 594（其中 187 条跨学科）
- 187 条里只有 **4 条**被标册次倒挂，且是上游数据里真实存在的倒流：
  数学九下第 27/28 章 → 物理八上第 4/5 章、八下第 7/12 章。
  **补进来之前这 4 条根本看不见** —— 这就是补它的价值。
- 画面零变化：`build_viz` 只画 `prerequisites_for`，`leads_to` 不参与，
  仍然是 7,938 节点 / 3,408 边；先修边的册次倒挂数仍是 119/3,703

**留下的坑**：`grade` 和 `year` 在高中段本来就不一致 —— 必修二的 `grade`
是 11（真实学年是高一）。那是画面分层的既有选择，改了会移动画面上的点，
所以**没动**。跨学科比较只走 `year`，两条线互不干扰。

---

## ISSUE-06　概念层的前置大面积缺失：69.6% 的知识点「看起来没有前置」

**现象**：用户查「二次函数[九上·概念]」发现它前置 0、解锁 2，与常识不符。
顺带查「小数」，同类问题。

**实测（`data/normalized/graph.json`，7,938 个进可视化的概念/技能）**：

| 指标 | 数值 |
|---|---|
| 没有 `prerequisites_for` 入边的 | 5,524（**69.6%**） |
| 其中连 `is_a` 上位关联也没有的 | 4,952（62.4%） |
| 名字含「二次函数」的 19 个节点里没有前置的 | 10 |
| 九上 617 个概念+技能里没有前置的 | 396（64.2%） |

**但常识上的先修并没有丢，它记在章节节点上。**
`math_9a_rjb_cpt16`（二次函数）的概念层前置确实是 0，而：

```
第十三章 轴对称[8a]      ──leads_to──▶ 第二十二章 二次函数[9a]
第十九章 一次函数[8b]    ──leads_to──▶ 第二十二章 二次函数[9a]
第二十一章 一元二次方程[9a] ──leads_to──▶ 第二十二章 二次函数[9a]
图形的运动（二）[4b]      ──leads_to──▶ 第二十二章 二次函数[9a]
数学广角 数与形[6a]      ──leads_to──▶ 第二十二章 二次函数[9a]
```

「一次函数先于二次函数」在数据里是对的，只是挂章上而不是挂概念上。
全库共 594 条 `leads_to`，实测**两端全部是 `Chapter`，无一条例外**
（`Chapter → Chapter : 594`）。所以章级教材顺序不存在噪声边，
不需要再按类型过滤。

**为什么之前没发现**：本项目 `build_viz.py:40` 的 `KEEP = {"Concept", "Skill"}`
只保留这两类节点之间的 `prerequisites_for`，章节层和 `is_a` 整条没进 payload。
于是页面上「前置 0」既可能是「真的没有」，也可能是「这一层没标」，
而界面把两者渲染成同一句话。

**这条 issue 里有一半是我们自己的 bug**：卡片无前置时写的是
「没有直接前置 —— **它是这一串的起点**」。后半句是拿数据缺口冒充知识点属性 ——
九上册的二次函数在常识上不可能是起点。按本项目立场（「发现问题 ≠ 修改数据」，
不让缺口冒充事实），这句必须改。

**已修（我们这一侧，不动上游数据）**：

| 改动 | 位置 | 效果 |
|---|---|---|
| 导出章级 `leads_to` 到 payload | `build_viz.py` `book_order()` | 7,510/7,938（95%）个知识点能定出教材顺序 |
| 导出 `is_a` 上下位 | `build_viz.py` `isa_pairs` | 1,895 对，涉及 2,342 个节点 |
| 小学章的归因路径 | 同上 `chapter_of_node` | 小学 86 → **611**/782（`appears_in` 在小学直指 Chapter） |
| 卡片从 2 栏扩到 6 栏 | `template.html` `showCard()` | 先修/后继/前后章/上下位 |
| 空态文案改成如实说明 | 同上 | 「数据里没记前置 —— 不等于它没有前置」 |
| 搜索脚注标明匹配方式 | 同上 | 「共 19 条**按名字匹配** · 名字匹配不等于前置关系」 |

payload 1,958 KB → 2,229 KB（+14%）。画面上的点和先修边**一条没动**，
仍是 7,938 节点 / 3,408 边 —— 新增的四栏只在卡片里显示，不参与布局和绘制。

**仍未修 / 需要上游**：概念层的 `prerequisites_for` 本身该补。
这是标注口径问题（前置标在章上还是知识点上），不该由我们替原作者决定。
**暂不提 issue，等证据再核一遍。**

**顺带一个界面教训**：搜「二次函数」返回 19 条，脚注原来写「共 19 条匹配」。
这 19 条是名字含「二次函数」的条目横跨九上 15 条 / 必修一 3 条 / 选必一 1 条，
是**同一主题在不同册次的平行表述**，不是 19 个前置 ——
但那句话读起来就是「二次函数有 19 个前置」。
凡是「N 条结果」可能被读成「N 个关系」的场合，都必须写明匹配方式。

**复现**：

```bash
python3 - <<'PY'
import json, collections
g = json.load(open('data/normalized/graph.json'))
N, E = g['nodes'], g['edges']
byid = {n['id']: n for n in N}
inb = collections.defaultdict(list)
for e in E: inb[e['to']].append(e)
print('二次函数 的概念层前置：',
      len([e for e in inb['math_9a_rjb_cpt16'] if e['type'] == 'prerequisites_for']))
print('但章级前置：',
      [e['fromName'] + '[' + e['fromBook'] + ']'
       for e in inb['math_9a_rjb_ch22'] if e['type'] == 'leads_to'])
PY
```

---

## 一条我想错了的规律

发现 ISSUE-01 时我以为找到了通用检测规则：

> **两条先修边共用同一句教材原文 → 其中一条大概率是倒抽的。**

拿全图 3,663 条带原文的先修边实测：

| 指标 | 数值 |
|---|---|
| 共用同一句原文的「证据组」 | 189 组 |
| 这些组展开出的边对 | 257 对 |
| 其中真的是环的 | **1 对** |
| 组级精确率 | 1 / 189 = **0.5%** |
| 边对级精确率 | 1 / 257 = **0.4%** |
| 召回率 | 1 / 2 = **50%**（ISSUE-02 漏掉） |

**这条规则不能用。** 同一句话里出现三个概念，本来就会产生三条两两不重复的边，这是正常现象。

真正有效的还是老老实实跑强连通分量：Kosaraju 两趟，10,685 个节点 10,683 个连通分量，**大小 >1 的恰好 2 个**，都是二元环，且都是化学。

证据字段的价值在别处：**它不能用来找错，但能解释错在哪**。找到环之后回头看证据，才知道该删哪一条。

---

## 提示级问题（不阻断交付）

| 代码 | 数量 | 占比 | 结论 |
|---|---|---|---|
| `BOOK_REVERSED` | 119 / 3,703 | 3.2% | **全部核验为正确**，不是错误 |
| `PREREQ_NO_EVIDENCE` | 40 / 3,703 | 1.1% | 先修边没有配教材原文，方向仍可查证 |
| `PREREQ_CROSSBOOK` | 368 / 3,703 | 9.9% | 跨册先修，正常（复习性引用） |

### 关于 `BOOK_REVERSED`

它报的是「先修方所在册次比后继方更晚」，例如：

- `毫米`(三上) → `厘米`(二上)
- `三角形的高`(八上) → `三角形`(一下)
- `惯性`(八下) → `质量`(八上)

逐条看下来全部成立。**教材册次不是难度排序。** 人教版把长度单位按认识顺序排在三年级，却不把「厘米」排在「毫米」之前；八年级讲三角形的高，依赖的是一年级就认识的三角形这个图形本身，而不是八年级之前某个叫「三角形」的东西。

所以这条检查作为**信息**保留，作为**错误**报警是错的。

顺带一提：Marble 仓库的 issue #5 测的正是这个（年龄段不重叠的反向依赖），实测只有 5 条严格意义上的。那边测的对象就不对——真该测的是成环，不是册次先后。

---

## 一个结构性事实

`data/raw/global_KG/edges.json` 里的边**只有三个字段**：

```json
{"source": "...", "target": "...", "type": "prerequisites_for"}
```

**没有证据字段。** 教材原文引用只存在于 `data/raw/subject_specific_KG/{math,physics,chemistry,biology}.json` 里，嵌在 `properties.evidence`。

两边对照：

| | `global_KG` | `subject_specific_KG` |
|---|---|---|
| 边数 | 23,278 | 数学/物理/化学/生物各自独立 |
| 证据原文 | 无 | 有 |
| 用途 | 跨册合并后的骨架 | 单科细节 |

这解释了为什么 ISSUE-01 和 ISSUE-02 的两条方向相反的边**证据一字不差**——它们不是从两处独立证据抽出来的，而是从同一句原文抽了两次。

---

## 校验层当前规则

`src/validate.py`，有硬错误时 `exit 1`。

| 代码 | 级别 | 实测结果 |
|---|---|---|
| `PREREQ_CYCLE` | **错误** | 2 个环 |
| `EMPTY_NAME` | **错误** | 6 个 |
| `DANGLING` | 错误 | 0 |
| `DUP_ID` | 错误 | 0 |
| `SELF_LOOP` | 错误 | 0 |
| `BOOK_REVERSED` | 提示 | 119 |
| `PREREQ_NO_EVIDENCE` | 提示 | 40 |
| `PREREQ_CROSSBOOK` | 提示 | 368 |
| `COVER_*` | 信息 | 小学 1 科 / 782 个；初中 4 科 / 2,655 个；高中 4 科 / 4,501 个 |

**「校验本身也需要被校验」**：这套规则上线时抓到 2 个硬错误，说明上游确实没跑等价检查。而规则本身也出过 bug——强连通分量第一版用字符串 id 建邻接表却用整数下标遍历，第二趟一条边都没走，报出「0 个环」的假阴性。**没有第二份实现来对照，就没法知道校验层自己有没有错。** 这是本项目存在的理由，也是它现在还没做完的部分。

---

## 复现

```bash
cd ~/Documents/01_工作_确石智能/项目/中文知识图谱/
python3 src/normalize.py     # 原件 → data/normalized/graph.json
python3 src/validate.py      # → data/normalized/validation.json（当前会 exit 1）
python3 src/build_viz.py     # → viz/知识图谱3D.html（渲染前自动剪掉 2 条环边）
```

确认环在官方原件里：

```bash
python3 -c "
import json
ed=json.load(open('data/raw/global_KG/edges.json'))
for e in ed:
    if e['type']=='prerequisites_for' and {'chemistry_xzxbx2_rjb_cpt100','chemistry_xzxbx2_rjb_cpt108'}=={e['source'],e['target']}:
        print(e)"
```
