## `is_a` 和 `prerequisites_for` 各存在环，与 §10.2 的 DAG 检查描述不符

先说结论：在贵方发布的 `global_KG/edges.json` 上，`prerequisites_for` 有 **2 个二元环**，`is_a` 有 **1 个三元环**。

论文原文（§10.2 KG Validation: Structural Checks and Human Verification）：

> We first perform automatic consistency checks on the **is_a** and **prerequisites_for** subgraphs, both expected to be directed acyclic graphs (DAGs). Cycles and structural inconsistencies are detected after graph construction and merging. Detected conflicts are then reviewed by subject annotators, who determine whether to remove, modify, or retain edges based on curriculum correctness.

构建流程第 (v) 步：

> We run depth-first cycle detection on the is_a and prerequisites_for subgraphs and manually resolve any violations, **yielding valid DAGs** for the taxonomic and prerequisite relations.

这三条边都在官方发布的原件里，不是在下游加工中产生的。

---

### 1. `prerequisites_for`：两个二元环

**环 A —— 相似相溶规律 ⇄ 极性分子**（均属 选必二）

```
chemistry_xzxbx2_rjb_cpt100 --prerequisites_for--> chemistry_xzxbx2_rjb_cpt108
chemistry_xzxbx2_rjb_cpt108 --prerequisites_for--> chemistry_xzxbx2_rjb_cpt100
```

两条边的 `evidence` 字段是**完全同一句**教材原文（"相似相溶"），所以看起来是同一处抽取重复写了两遍，而不是建模上有意的双向关系。

**环 B —— 化学键能量变化与反应热 ⇄ 根据键能估算反应热**（均属 选必一）

```
chemistry_xzxbx1_rjb_cpt10 --prerequisites_for--> chemistry_xzxbx1_rjb_skl2
chemistry_xzxbx1_rjb_skl2 --prerequisites_for--> chemistry_xzxbx1_rjb_cpt10
```

这一对的语义是「用键能估算反应热，需要先理解化学键能量变化」——单向说得通，反向不成立。

---

### 2. `is_a`：一个三元环

这一条可能更值得看，因为论文把 `is_a` 和 `prerequisites_for` **并列**作为做过 DAG 检查的两个子图。

```
chemistry_9a_rjb_cpt188  --is_a--> chemistry_bx1_rjb_cpt213
chemistry_bx1_rjb_cpt213  --is_a--> chemistry_xzxbx2_rjb_cpt28
chemistry_xzxbx2_rjb_cpt28  --is_a--> chemistry_9a_rjb_cpt188
```

| id | 名称 | 册次 |
|---|---|---|
| `chemistry_9a_rjb_cpt188` | 元素周期表 | 九上 |
| `chemistry_bx1_rjb_cpt213` | 元素周期律 | 必修一 |
| `chemistry_xzxbx2_rjb_cpt28` | 元素周期系 | 选必二 |

读起来是：**元素周期表 是 元素周期律 的下位概念；元素周期律 是 元素周期系 的下位概念；元素周期系 又 是 元素周期表 的下位概念。**

无论按哪个方向读都不成立——元素周期表是元素周期律的**载体与体现**，元素周期律描述的是元素周期系的规律，这些属于「描述—被描述」，不是属种。

补充一条观察：`chemistry_9a_rjb_cpt188`（元素周期表）与 `chemistry_bx1_rjb_cpt213`（元素周期律）之间同时存在 `is_a` 和 `relates_to` 两个方向的边。同一对节点上并存两种关系，可能就是环被引入的位置。

---

### 复现

只用标准库，直接跑在官方发布的文件上：

```python
#!/usr/bin/env python3
import json, sys, pathlib
from collections import defaultdict

root = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else ".")
edges = json.load(open(root/"global_KG"/"edges.json"))
nodes = {n["id"]: n.get("name","") for n in json.load(open(root/"global_KG"/"nodes.json"))}

def find_cycles(et):
    adj = defaultdict(list)
    for e in edges:
        if e["type"] == et: adj[e["source"]].append(e["target"])
    color, out = {}, []
    def dfs(u, stack):
        color[u] = 1; stack.append(u)
        for v in adj.get(u, ()):
            if color.get(v) == 1:
                i = stack.index(v); out.append(stack[i:] + [v])
            elif color.get(v) is None:
                dfs(v, stack)
        stack.pop(); color[u] = 2
    sys.setrecursionlimit(100000)
    for n in list(adj):
        if color.get(n) is None: dfs(n, [])
    return out

for et in ("prerequisites_for", "is_a"):
    for c in find_cycles(et):
        print(f"{et}: " + " -> ".join(f"{x} ({nodes[x]})" for x in c))
```

```bash
python repro_cycles.py /path/to/K12-KGraph
```

如果贵方有内部的修复版本，我很想看到「手工解决后的最终状态」长什么样——是删边、改向，还是保留并标注？因为这直接决定下游该不该信任 `is_a` 和 `prerequisites_for` 这两个子图可以当作 DAG 用。

---

**一点说明**：我这边建了一个中文教材知识图谱的可视化项目（[chinese-k12-knowledge-graph](https://github.com/Joshhuang123/chinese-k12-knowledge-graph)），定位是**给贵方数据补一层校验**，不修改贵方原件。这三个环是第一遍跑校验就抓到的。如果对定位有问题或不希望被引用，我可以撤掉链接。
