## 一年级上册数学 6 个习题节点的 `name` 为空字符串，但被引用 16 次

### 现象

这 6 个节点在官方 `global_KG/nodes.json` 里的 `name` 是空字符串：

```
math_1a_rjb_exe40  math_1a_rjb_exe41  math_1a_rjb_exe42
math_1a_rjb_exe43  math_1a_rjb_exe44  math_1a_rjb_exe45
```

它们不是孤立节点——被 `appears_in` / `tests_concept` / `tests_skill` 共引用 16 次：

| 节点 | 引用它的边 |
|---|---|
| `exe40` | `appears_in → 6和7`；`tests_concept → 6的加减法`；`tests_skill → 利用操作理解加减法` |
| `exe41` | `appears_in → 6和7`；`tests_concept → 分与合（拆分与组合）` |
| `exe42` | `appears_in → 6和7`；`tests_concept → 加法意义`；`tests_skill → 利用操作理解加减法` |
| `exe43` | `appears_in → 6和7`；`tests_concept → 6的加减法`；`tests_skill → 利用操作理解加减法` |
| `exe44` | `appears_in → 6和7`；`tests_concept → 分与合（拆分与组合）` |
| `exe45` | `appears_in → 6和7`；`tests_concept → 加法意义`；`tests_skill → 利用操作理解加减法` |

共 6 条 `appears_in` + 6 条 `tests_concept` + 4 条 `tests_skill` = **16 条**。

### 推测

人教版教材里有大量没有标题的练习栏（「做一做」「练习」这类）。抽取时正文抓到了、栏目标题没抓到，于是节点建出来了但名字空着。

### 为什么值得修

严重程度不高，但这会让任何**按名称检索**的下游拿到空字符串：

- 搜索框里搜不到这些节点，用户会以为数据缺失
- 引用了它们的 16 条边的 `fromName` / `toName` 也随之为空，按边文本检索同样落空

### 复现

```python
import json
nodes = json.load(open("global_KG/nodes.json"))
empty = [n["id"] for n in nodes if not (n.get("name") or "").strip()]
print(len(empty), sorted(empty))
```

### 一点说明

我这边建了一个中文教材知识图谱的可视化项目（[chinese-k12-knowledge-graph](https://github.com/Joshhuang123/chinese-k12-knowledge-graph)），定位是给贵方数据补一层校验，不修改贵方原件——发现问题只记录和上报。如果不希望被引用，我可以撤掉链接。
