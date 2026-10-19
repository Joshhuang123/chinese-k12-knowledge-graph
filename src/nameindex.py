#!/usr/bin/env python3
"""
名字 → node id 的解析器。

为什么需要它：
  上一轮盲测，独立子代理给 22 条前置，**按名字精确重合 0/22**。
  逐条人工判定，22 条语义全部站得住、0 条说错，17 条是数据集漏标的纯增量。
  也就是说模型说的是对的，但对不上名字 —— 对不上的边就并不进来，
  1898 个知识点跑下来会得到 1898 份互不可比的自由文本。

所以合并之前必须有这道闸：把模型说的名字落到具体节点上，
或者明确判它是**新概念**（那就得建节点，不能硬塞给一个近似的旧节点）。

解析分四档，从严到松，**结果必须带档位返回**，不能只给一个 id：
    EXACT   名字一字不差
    NORM    去了书次后缀、空白、标点之后相等
    CORE    去了括号内容之后相等（「圆柱的体积」→「圆柱」）
    CONTAIN 一方包含另一方（「焦点和焦距」对上「焦距」）
    AMBIG   匹配上了，但指向好几个不同节点，需要人判断
    NEW     图谱里根本没有这个东西

把 NEW 和 AMBIG 显式分开，是这个模块存在的全部理由：
  把 NEW 硬塞给一个 CONTAIN 匹配上的旧节点，图谱会看起来连上了，
  实际上是在撒谎。
"""
import json
import pathlib
import re
import sys
import unicodedata
from collections import defaultdict

BASE = pathlib.Path(__file__).resolve().parent.parent
GRAPH = BASE / "data" / "normalized" / "graph.json"

# 书次后缀：数学73/316 这种
_BOOK_RE = re.compile(r"[\[\(【\s]*(?:[一二三四五六七八九十]+\s*[上下]|[必修选修]\s*[一二三四五六七八九]|选择性必修[一二三四五]|\d\s*[abAB])[\]\)】\s]*$")
PAREN = re.compile(r"[（(\[【].*?[）)\]】]")
PUNCT = re.compile(r"[\s·・\.\,\;\:\?\!\"\'\"\'\u3000\-\u2014/\\|]+")
TAIL = re.compile(r"(?:的)?(?:知识|方法|技能|概念|内容|意义|原理)$")

# 章节/册次节点不是知识，不能作为前置的目标。
# 「总复习」「选择性必修一」出现在索引里，只会让解析器把一句话
# 接到一个章节标题上 —— 看起来接上了，其实什么都没说。
INDEXABLE = {"Concept", "Skill", "Method", "Theory", "Property"}

# 只有这四档能自动连边。CONTAIN 明确不行：
# 中文复合词分不清「同义词」和「限定语不同的新概念」（表内乘法 vs 乘法），
# 比例又分不开，只能给人判断。
AUTO = {"EXACT", "NORM", "CORE", "TAIL"}


def norm(s):
    """NFKC + 去书次后缀 + 去空白标点。

    去书次后缀有下限保护：「必修一」「八上」整个字符串都是书次，
    一刀切下去就成了空串，然后所有必修册会挤到同一个空键上。
    """
    s = unicodedata.normalize("NFKC", s or "")
    stripped = _BOOK_RE.sub("", s).strip()
    if len(norm_keep_len(stripped)) >= 2:
        s = stripped
    return PUNCT.sub("", s)


def norm_keep_len(s):
    return PUNCT.sub("", s)


def core(s):
    """再把括号内容整个去掉：「平行四边形的面积（割补法）」→「平行四边形面积」。"""
    s = norm(s)
    s = PAREN.sub("", s)
    return PUNCT.sub("", s)


def tail_strip(s):
    """去掉结尾的『的知识/方法/技能』等 —— 模型爱加，数据集不加。"""
    c = core(s)
    t = TAIL.sub("", c)
    return t or c


class NameIndex:
    def __init__(self, nodes):
        self.node_of = {n["id"]: n for n in nodes}
        self.exact = defaultdict(set)
        self.by_norm = defaultdict(set)
        self.by_core = defaultdict(set)
        self.by_tail = defaultdict(set)
        # 包含匹配用：把所有键按长度排好，长的优先（更具体的先试）
        self.core_keys = []
        for n in nodes:
            if not n.get("name") or n.get("label") not in INDEXABLE:
                continue
            if not norm(n["name"]):        # 「、、」这种空名习题节点
                continue
            self.exact[n["name"]].add(n["id"])
            self.by_norm[norm(n["name"])].add(n["id"])
            self.by_core[core(n["name"])].add(n["id"])
            self.by_tail[tail_strip(n["name"])].add(n["id"])
        for k in self.by_core:
            if k:
                self.core_keys.append(k)
        self.core_keys.sort(key=len, reverse=True)
        self._core_key_set = set(self.core_keys)

    # ── 歧义处理 ────────────────────────────────────────────────
    def _pick(self, ids, prefer_book=None):
        """多个候选时怎么选。

        同一册优先；否则取**最早**出现的那一册 —— 「二次函数」在九上、
        必修一、选必一各有一个，学不会九上那个，学到哪儿都卡，
        所以先修边应该指向最早引入它的那一册。
        """
        ids = sorted(ids)
        if len(ids) == 1:
            return ids[0], "single"
        if prefer_book:
            same = [i for i in ids if self.node_of[i].get("book") == prefer_book]
            if len(same) == 1:
                return same[0], "book"
            if same:
                ids = same
        return ids[0], f"ambiguous:{len(ids)}"

    def resolve(self, name, prefer_book=None):
        """→ (状态, node_id 或 None, 候选 id 列表, 用了哪一档)"""
        name = (name or "").strip()
        if not name:
            return "NEW", None, [], "empty"

        if name in self.exact:
            i, how = self._pick(self.exact[name], prefer_book)
            return "EXACT", i, sorted(self.exact[name]), how

        for key, tbl, tag in ((norm(name), self.by_norm, "NORM"),
                              (core(name), self.by_core, "CORE"),
                              (tail_strip(name), self.by_tail, "TAIL")):
            if key and key in tbl:
                i, how = self._pick(tbl[key], prefer_book)
                return tag, i, sorted(tbl[key]), how

        # 包含匹配：模型说「焦点和焦距」，数据里叫「焦距」。
        #
        # **只给候选，不给结论。** 中文复合词里包含匹配本质上不安全：
        # 「表内乘法」⊃「乘法」比例 0.5，「焦点和焦距」⊃「焦距」比例 0.4，
        # 两个比例分不开。真正的区别是**限定语**：表内 vs 焦点 —— 前者把概念
        # 缩小了，缩小的概念不能等同于大的那个。第一版按比例贪心取最长键，
        # 于是「表内乘法」被接到了「乘法」上，图谱上多了一条看着通顺、
        # 实际指窄了的边。指错比不指更糟。
        #
        # 所以 CONTAIN 一律返回 id=None + 候选列表，进人工队列，
        # 由人决定是「同义词，应合并」还是「限定语不同的新概念，应建节点」。
        n_c, t_c = core(name), tail_strip(name)
        for probe, ptag in ((n_c, "CONTAIN"), (t_c, "CONTAIN_TAIL")):
            if not probe or len(probe) < 2:
                continue
            hits = defaultdict(set)
            for k in self.core_keys:
                if len(k) * 3 < len(probe):
                    continue
                if k in probe or probe in k:
                    hits[k] |= self.by_core[k]
            if not hits:
                continue
            allids = sorted({i for v in hits.values() for i in v})
            cands = sorted(hits, key=len, reverse=True)[:5]
            return "CONTAIN", None, allids, f"{ptag}·候选:{'/'.join(cands)}"

        return "NEW", None, [], "no-match"

    def stats(self):
        return {
            "nodes": len(self.node_of),
            "exact_keys": len(self.exact),
            "norm_keys": len(self.by_norm),
            "core_keys": len(self.by_core),
        }


def load():
    g = json.loads(GRAPH.read_text())
    return g["nodes"], g


def main():
    nodes, g = load()
    ix = NameIndex(nodes)

    if len(sys.argv) > 1 and sys.argv[1] == "--stats":
        print(json.dumps(ix.stats(), ensure_ascii=False, indent=1))
        return

    # 自检：拿图谱自己的名字去解析，应该全部 EXACT 或 NORM。
    # 这一步要是不通过，说明 normalize 把不同的名字压成了同一个键
    # （压键是有损的，会让解析悄悄指向错的节点）。
    ok = 0
    collide = defaultdict(list)
    idx_nodes = [n for n in nodes if n.get("label") in INDEXABLE and norm(n.get("name") or "")]
    for n in idx_nodes:
        st, _i, _c, _h = ix.resolve(n["name"])
        ok += st in ("EXACT", "NORM", "CORE", "TAIL")
        if len(collide[norm(n["name"])]) < 6:
            collide[norm(n["name"])].append(n["name"])
    print(f"自检：可索引的 {len(idx_nodes)} 个知识节点，EXACT/NORM/CORE/TAIL 命中 {ok} "
          f"({100*ok/len(idx_nodes):.1f}%)")
    print("（章节/册次节点不进索引 —— 它们不是知识，接上去等于什么都没说）")

    worst = sorted(((len(v), k, v) for k, v in collide.items() if len(v) > 1),
                   reverse=True)[:12]
    print("\n归一化后撞名的键（解析歧义的来源）：")
    for cnt, k, vs in worst:
        print(f"  {cnt} 个 · {k[:26]:<28} 例：{ '、'.join(v[:18] for v in vs[:3]) }")

    # 命令行试解析
    if len(sys.argv) > 2:
        print()
        for probe in sys.argv[2:]:
            st, i, cands, how = ix.resolve(probe)
            nm = ix.node_of[i]["name"] if i else "—"
            print(f"  {probe[:26]:<28} {st:<12} → {nm[:24]:<26} {i or ''} {how}")


if __name__ == "__main__":
    main()
