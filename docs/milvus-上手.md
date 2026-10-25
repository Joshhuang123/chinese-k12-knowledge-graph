# 给「想查这个项目」的人：Milvus 数据库层

> **这一层是可选的 —— 不装不影响主项目的任何功能。**
>
> 主项目是静态站点 + jsonl 数据层：双击 `index.html` 就能玩，
> agent 直接读 `data/learn-cards.jsonl` 就能用，**零第三方依赖**。
>
> 这一层只解决一件事：**让你能用自己���话说出那个概念**。
> 上游概念名大量是改写过的（「ATP（能量储存形式）」「DNA（遗传信息载体）」），
> 教材里根本不这么写 —— 精确字面匹配只覆盖 4.6%。
>
> **代价**（实测）：装依赖 + 下 1.2 GB 模型 + 灌库 45 分钟 + 375 MB 库文件。
> 想清楚再装。

---

## 一句话

这个项目是个**中文 K12 知识图谱**：8,590 个知识点，2.3 万页教材原文，
每个知识点知道自己**在教材哪一页**、**前面该学什么**。

现在它还是一个网页 + 几个 jsonl 文件。这一层把它变成了**数据库**：

```sql
-- 你想要「浮力」在教材里怎么讲的
SELECT text, edition, book, page FROM kg_textbook
WHERE vector MATCH '[...]' LIMIT 5;
```

或者更简单：

```bash
python3 src/query_milvus.py "浮力"
```

---

## 起库

### 方式 A：milvus-lite（推荐先试这个）

**不需要 Docker**，一个文件就是整个库。

```bash
cd ~/Documents/个人/项目/中文知识图谱/

# 1. 装依赖
# ⚠️ **需要 Python ≥ 3.10**（milvus-lite 3.x 的要求）。
#    本机默认的 python3 是 3.9 —— 用 python3.12 建个虚拟环境。
python3.12 -m venv ~/kg-venv
source ~/kg-venv/bin/activate
pip install "milvus-lite>=3.2" "pymilvus>=3.0"

# 2. 下嵌入模型（1.2 GB，本机跑，教材不出境）
ollama pull bge-m3

# 3. 灌数据（约 45 分钟，5.5 万段教材 + 8,590 概念 + 1.7 万条先修边）
python3 src/build_milvus.py
```

灌完会有 `data/milvus/kg_lite.db`。

⚠️ **milvus-lite 有两代，格式不兼容**：

| 版本 | 要求 | 库的样子 |
|---|---|---|
| **3.x**（推荐，当前版） | Python ≥ 3.10 + `pymilvus>=3.0` | `.db` 是个**目录** |
| 2.5.x（老版） | Python 3.9 + `pymilvus==2.5.1` | `.db` 是**单个文件** |

**两代的库不能互相读** —— 换版本 = 重建（45 分钟）。
用 3.x 除非你的 Python 只有 3.9。

### 方式 B：Milvus Standalone（要多人同时查 / 远程访问时）

```bash
cd data/milvus
docker compose -f milvus-standalone.yaml up -d
cd ../..
MILVUS_BACKEND=server python3 src/build_milvus.py
```

⚠️ 镜像从 Docker Hub 拉，**国内网络可能要很久**（实测拉了 50 分钟没到）。
镜像拉不动时用方式 A —— 功能一样（向量检索 + 标量过滤），
只是不能多人同时写同一个库。

---

## 怎么查

### 语义检索教材原文

```bash
python3 src/query_milvus.py "浮力"
```

输出按相关度排，每条给**出处**（哪本书哪一页）：

```
「浮力」在教材原文里最相关的 5 段：

── 人教版·8b p53  相似度 0.812
   海洋中巨大的冰山能在水上漂浮，游船、鸭子能在水面游飞。把它们托起来的…
   命中概念：浮力, 压力, 重力
```

### 按教材筛着查

```bash
python3 src/query_milvus.py "浮力" --edition 人教版 --book 8b
python3 src/query_milvus.py "密度" --subject physics
```

### 查一个概念本身

```bash
python3 src/query_milvus.py --name 浮力
```

### 查前置关系

```bash
python3 src/query_milvus.py --prereq 浮力
```

```
「浮力」的先修关系（3 条）：
  力  →  浮力
      理由：浮力是一种力，没有力就读不出浮力属于哪一类
  液体压强  →  浮力
      理由：浮力源于液体内部压强差异，不知液体压强就读不出浮力为何向上
  重力  →  浮力
      理由：浮力定义中的『排开液体的重量』是对比重力的说法…
```

### 直接写 SQL

```python
from pymilvus import MilvusClient
c = MilvusClient(uri="data/milvus/kg_lite.db")

# 标量查询
rows = c.query("kg_textbook",
               filter='edition == "人教版" and book == "8b"',
               output_fields=["text", "page"], limit=10)

# 聚合：哪本书的段落最多
c.query("kg_textbook", filter="", output_fields=["book"], limit=100)
```

---

## 三张表

| 表 | 是什么 | 粒度 | 条数 | 关键字段 |
|---|---|---|---|---|
| `kg_textbook` | 教材原文**段落** | 一段 | 57,904 | `text` `vector` `edition` `book` `subject` `page` `chapter` `concepts` |
| `kg_concept` | 知识点 | 一个概念 | 8,590 | `name` `vector` `definition` `book_zh` `subject_zh` `grade` `importance` |
| `kg_prereq` | 先修边 | 一条边 | 17,164 | `from_name` `to_name` `evidence` `src` |

`kg_prereq` 的 `src` 是来源码：
`上游`（数据集里的）/ `model`（模型重建）/ `derived`（自建概念）/ `intro`（教材引入路径）。
**不是一回事** —— 上游那档恰恰是可信度最低的（上游 issue #10 逐条看过 38 条，
模型那边全对）。

---

## 两条要注意的

### 1. 向量检索给的是「相关段落」，不是「这就是定义」

`kg_textbook` 里是**教材原页上的话**（段落）。
你查「浮力」，它给你教材里讲浮力的那几段 ——
**哪一段是「定义」，哪一段是「例题」，得你自己看**。

想要**已经被判过是定义句**的那些，用学习卡：

```bash
python3 - <<'PY'
import json
for line in open("data/learn-cards.jsonl", encoding="utf-8"):
    r = json.loads(line)
    if r["name"] == "浮力":
        for w in r["what"]:
            print(f"[{w['kind']}] {w['text']}")
PY
```

每段都带 `kind`：
- `教材定义句` —— 教材在给这个概念下定义（证据最强）
- `教材提及句` —— 教材提到了它，但不是定义句
- `图谱定义` —— **数据集的转述，不是教材原话**

⚠️ **`图谱定义` 不能当教材原话引用。**

### 2. 教材版权页没有入库

教材前十几页是版权页 / 编者信息（「版权所有…未经许可不得另做他用」）。
这些**没有进库** —— 检索时不该召回版权声明，
数据库里也不该复制教材的版权信息。

入库的是**从教材里抽出来的段落**，性质跟 `data/lessons.jsonl` 一样。
教材 PDF 本身不随本仓库分发。

---

## 嵌入模型

```bash
ollama list        # 看本机有哪些
```

| 模型 | 大小 | 中文 | 速度 | 结论 |
|---|---|---|---|---|
| `bge-m3` | 1.2 GB | 好 | 0.05 秒/条 | **用这个** |
| `qwen3-embedding:8b` | 4.7 GB | 好 | 10 秒/条 | 太慢（全量 37 小时） |
| `nomic-embed-text` | 274 MB | **不行** | 0.1 秒/条 | 英文模型，「邻补角」会召回「近似数」 |

⚠️ **换模型必须重建库** —— 向量空间不一样，混用会召回乱的东西。
`build_milvus.py` 每次都是**重新建表**（检测到没有索引就删掉重建）。

---

## 校验

```bash
python3 src/check_milvus.py
```

8 组判据：表在不在、条数对不对、**正例召回**、**负例不误召回**、
过滤可用、**版权不外泄**、与学习卡不打架、先修边两端真实存在。

⚠️ **正负例都有** —— 只放成功样例的检查测不出辨别力
（这是 Milvus 那份 eval spec 的原话）。
「查连通器不该召回浮力」这种负例也要在。

---

## 相关的文档

- `docs/需求清单.md` —— R-3（这一层的需求、实测、验收判据）
- `docs/agent-data.md` —— 第 ⑥ 节（所有数据层怎么取、字段什么意思）
- `README.md` —— 九之四（这一层在项目里的位置）
