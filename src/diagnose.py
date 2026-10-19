#!/usr/bin/env python3
"""
诊断：给定一个「卡住了的知识点」，定位最可能缺的是哪一块前置。

**为什么需要它**

可视化能回答「这个知识点有哪些前置」，但那回答不了真正的问题 ——
「我朋友卡在二次函数上，是因为什么前置的缺失？」

要回答这个，得反过来做：
1. 把卡住的概念**拆成必须先懂的子知识**；
2. 对每一块，查它在图里的先修链有多深、**断在哪一节**；
3. 按「必要程度 × 断裂程度」排序，给出最可能的缺口。

教材顺序只能告诉你「前面讲过什么」，那是解剖不是诊断。
诊断要的是「**哪一环是空的**」。

## 跑法

```bash
python3 src/diagnose.py 二次函数
python3 src/diagnose.py --id math_9a_rjb_cpt16
python3 src/diagnose.py 浮力 --explain     # 打印每块的判定依据
```

## 拆解从哪来

`SUBKNOWLEDGE` 是一张**手工维护**的表：概念名 → 它必需的前置子知识。
不用模型来拆，有两个原因：

- 本机没有可用的程序化模型通道（见 docs/probe-llm-prereq.md 的阻塞一节）
- 拆错了没法测。手工表可以被测试钉住，模型输出不能

所以这张表现在是**半自动的**：初稿手工写，将来靠盲测结果补。
每一项都带 `must`（是不是真的必需）和 `why`（为什么必需），
写不出 why 的项就不该进表 —— 那是在凑数。
"""
import argparse
import collections
import json
import pathlib
import re
import os
import sys

BASE = pathlib.Path(__file__).resolve().parent.parent
GRAPH = BASE / "data" / "normalized" / "graph.json"

# ── 子知识表：卡住的概念 → 必须先懂的那些东西 ──────────────────────────
# must=True  真的必需，缺了理解不了这个概念
# must=False 相关但不是理解它的必要条件（用在「实际问题」类概念上）
SUBKNOWLEDGE = {
    "二次函数": [
        ("一次函数", True, "y=ax²+bx+c 是 y=kx+b 的非线性推广，直线型函数是它的退化情形"),
        ("函数", True, "「形如…的函数」这句话本身要求先有函数概念"),
        ("变量", True, "x 是自变量、a/b/c 是常数，这个区分不懂就定义不了"),
        ("一元二次方程", True, "求零点就是在解 ax²+bx+c=0，两个章节紧挨着"),
        ("配方法", True, "顶点式 y=a(x-h)²+k 只能由配方法推出，不会配方读不出顶点"),
        ("抛物线", True, "是 y=ax² 图象的一般化，不知道抛物线形状就无法想象系数的作用"),
        ("轴对称", True, "抛物线的对称轴是二次函数最核心的性质"),
        ("顶点", True, "最值问题完全建立在顶点坐标上"),
        ("不等式", False, "定义里的 a≠0 用到不等式，但只是排除退化情形"),
    ],
    "浮力": [
        ("压力", True, "浮力本质是液体对物体的压力，不懂压力就理解不了「浮」"),
        ("密度", True, "F浮=ρ液gV排 里的 ρ 就是密度，不会算质量体积关系就得不出公式"),
        ("重力", True, "要跟 G=mg 对照着记，分不清浮和重就会算错方向"),
        ("压强", True, "浮力由液体压强差产生，不懂压强就推不出阿基米德原理"),
        ("液体的体积", True, "V排 是公式的独立因子，不懂它就算不出 F浮"),
    ],
    "小数的意义": [
        ("计数单位", True, "0.1 是十分之一，没有「单位是 10 的幂」这个前提就没有小数"),
        ("数位", True, "小数点右边怎么记位，取决于左边已经建立的位值概念"),
        ("十进制计数法", True, "整个小数体系是十进制的延伸"),
        ("分数", True, "0.1 和 1/10 是同一个数的两种写法，不会分数就看不懂等价"),
    ],
}

ALIAS = {  # 概念名在数据里可能长这样
    "液体的体积": ["体积", "液体的体积"],
    "变量": ["变量", "变量与函数关系"],
    "函数": ["函数"],
}


class KG:
    def __init__(self, path=GRAPH, viz_html=None):
        g = json.load(open(path, encoding="utf-8"))
        self.g = g
        self.nodes = {n["id"]: n for n in g["nodes"]}
        self.inb = collections.defaultdict(list)
        self.outb = collections.defaultdict(list)
        for e in g["edges"]:
            self.inb[e["to"]].append(e)
            self.outb[e["from"]].append(e)
        self.by_name = {}
        for n in g["nodes"]:
            if n["label"] in ("Concept", "Skill") and n["name"].strip():
                self.by_name.setdefault(n["name"], []).append(n)
        self.units = self._load_units(viz_html)

    def _load_units(self, viz_html):
        """教材顺序单元表（build_viz.py 产出）。先修边在数学这边几乎全空，
        真正能用来回溯的是这条链。"""
        viz_html = viz_html or (BASE / "index.html")
        s = open(viz_html, encoding="utf-8").read()
        m = re.search(r'<script id="data" type="application/json">(.*?)</script>', s, re.S)
        D = json.loads(m.group(1))
        cns = D["cns"]
        ns = D["nodes"]
        groups = collections.defaultdict(list)
        for i, c in enumerate(cns):
            groups[c[2]].append(i)
        pos = {}
        for grp in groups.values():
            for k, gi in enumerate(grp):
                pos[gi] = (grp, k)
        return {"cns": cns, "ns": ns, "groups": groups, "pos": pos}

    def find(self, name):
        for cand in ALIAS.get(name, [name]):
            if cand in self.by_name:
                return self.by_name[cand][0]
        return None

    def unit_of(self, nid):
        ns = self.units["ns"]
        for i, a in enumerate(ns):
            if a[5] == nid:
                return a[14]
        return -1

    def gap_to(self, from_nid, to_nid):
        """两个知识点在教材顺序上隔了几个单元。隔得越近，越可能是卡点。"""
        a = self.unit_of(from_nid)
        b = self.unit_of(to_nid)
        if a < 0 or b < 0:
            return None
        ga, _ = self.units["pos"][a]
        gb, _ = self.units["pos"][b]
        return abs(ga.index(b) - gb.index(a))

    def prereq_count(self, nid):
        return len([e for e in self.inb.get(nid, []) if e["type"] == "prerequisites_for"])

    def reachable_from(self, src, dst, cap=4000):
        """从 src 出发能不能走到 dst（任意边类型）。走不到就是走不到，
        不解释、不绕路 —— 「没有路径」本身就是诊断结论。"""
        prev = {src: None}
        q = collections.deque([src])
        seen = 0
        while q and seen < cap:
            u = q.popleft()
            seen += 1
            if u == dst:
                return True
            for e in self.outb.get(u, []):
                v = e["to"]
                if v not in prev:
                    prev[v] = u
                    q.append(v)
        return dst in prev

    def leads_to_chapters(self, nid):
        """leads_to 标出来的前置章 —— 少但权威，是上游手工标的。"""
        out = []
        for e in self.outb.get(nid, []):
            t = self.nodes.get(e["to"])
            if t and t["label"] == "Chapter":
                out.append(t)
        return out

    def overlay_model_edges(self, path=None):
        """把模型重建的先修边叠进来，用于对比「补了之后定位能力变了多少」。

        叠进来的边一律打 source="model"，**不许跟数据集的边混在一起统计**：
        混了就分不清「图谱本来就知道」和「我们自己补的」，
        而这两件事的可信度完全不一样。
        只收 resolved 里的 new / dup（已经解析到具体节点的那部分），
        队列里那些没落位的边不在这里 —— 它们连边是什么都还不知道。
        """
        path = path or (BASE / "data" / "normalized" / "lmm-merged.json")
        if not os.path.exists(path):
            return 0
        d = json.load(open(path, encoding="utf-8"))
        added = 0
        for r in d.get("resolved", []):
            if r["kind"] != "new":          # dup 本来就有，叠了没意义
                continue
            e = {"from": r["from"], "to": r["to"], "type": "prerequisites_for",
                 "fromName": r["fromName"], "toName": r["toName"],
                 "evidence": r.get("why") or "", "source": "model"}
            self.inb[r["to"]].append(e)
            self.outb[r["from"]].append(e)
            added += 1
        self.model_edges = added
        return added

    def overlay_selfbuilt_edges(self, path=None):
        """把**自建层**的边（L0 能力底座 + derived 概念）叠进来。

        **诊断层以前完全看不见这两层。**
        diagnose 只读 graph.json 的边（上游 3703 条）+ overlay 的模型边
        （2928 条）= 6631 条，而页面上有 6800 条 —— 差的 505 条
        （L0 能力边 415 + derived 概念边 90）**在诊断里等于不存在**。

        这两层恰恰是这个项目自己建的东西：
        16 个 L0 能力、48 个 derived 概念。诊断报告里
        「能力底座挡在多少条边上」「概念层前置有多少条」
        这类结论，用的是残缺的边集。

        叠进来的边按 source 原样保留（l0 / derived / intro），
        跟 model 分开统计 —— 三者的可信度完全不同：
        上游标的、模型重建的、能力底座建的。
        """
        path = path or (BASE / "data" / "normalized" / "selfbuilt-edges.json")
        if not os.path.exists(path):
            return 0
        d = json.load(open(path, encoding="utf-8"))
        added = 0
        for e in d.get("edges", []):
            src = e.get("source", "")
            if src not in ("l0", "derived", "intro"):
                continue                  # model 的走 overlay_model_edges
            if e.get("type") != "prerequisites_for":
                continue
            self.inb[e["to"]].append(e)
            self.outb[e["from"]].append(e)
            added += 1
        self.selfbuilt_edges = added
        return added

    def prereq_of(self, nid, only=None):
        """→ [(节点, 边)]，only='dataset' 时只看数据集自己的边。"""
        out = []
        for e in self.inb.get(nid, []):
            if e["type"] != "prerequisites_for":
                continue
            if only == "dataset" and e.get("source") == "model":
                continue
            n = self.nodes.get(e["from"])
            if n:
                out.append((n, e))
        return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("concept", nargs="?", help="概念名")
    ap.add_argument("--id", help="直接给节点 id")
    ap.add_argument("--explain", action="store_true", help="打印判定依据")
    ap.add_argument("--model", action="store_true",
                    help="叠加模型重建的先修边（来源会单独标注，不跟数据集混算）")
    args = ap.parse_args()

    kg = KG()
    if args.model:
        n = kg.overlay_model_edges()
        print(f"[已叠加模型重建的先修边 {n} 条，来源标记 model]")
        m = kg.overlay_selfbuilt_edges()
        print(f"[已叠加自建层边 {m} 条（能力底座 l0 + 自建概念 derived）]")
        print()
    node = kg.nodes[args.id] if args.id else (kg.find(args.concept) if args.concept else None)
    if node is None:
        ap.error("给个概念名或者 --id（已登记子知识表的概念：" + "、".join(SUBKNOWLEDGE) + "）")

    print("=" * 64)
    print(f"症状：{node['name']}  [{node['bookZh']}·{node['label']}]")
    print(f"定义：{(node.get('props') or {}).get('definition', '')[:88] or '（无）'}")
    np = kg.prereq_count(node["id"])
    ins = [e for e in kg.inb[node["id"]]]
    print(f"概念层前置：{np} 条　|　全部入边：{len(ins)} 条"
          + ("　← **前置标注是空的**" if np == 0 else ""))
    for e in ins:
        print(f"    ← {e['type']}：{e['fromName']}")
    print("=" * 64)

    # 能走到这儿吗？从最相关的几个候选反查
    probe = ["一次函数", "抛物线", "轴对称"]
    reach = []
    for p in probe:
        pn = kg.find(p)
        if pn and pn["id"] != node["id"]:
            reach.append((p, kg.reachable_from(pn["id"], node["id"])))
    print("\n可达性检查（从最相关的前置能不能走到它）：")
    for p, ok in reach:
        print(f"   {'能走到' if ok else '走不到'}　← {p}")

    subs = SUBKNOWLEDGE.get(node["name"])
    if not subs:
        print(f"\n「{node['name']}」还没登记子知识表。已登记：" + "、".join(SUBKNOWLEDGE))
        return 0

    print(f"\n拆成 {len(subs)} 块必须先懂的东西，按「离症状多近 × 有没有被标注」排序：\n")
    rows = []
    for name, must, why in subs:
        sub = kg.find(name)
        if not sub:
            rows.append(dict(name=name, must=must, why=why, gap=None,
                             note="图里根本没有这个节点", sev=90))
            continue
        gap = kg.gap_to(sub["id"], node["id"])
        npc = kg.prereq_count(sub["id"])
        reach_ok = kg.reachable_from(sub["id"], node["id"])
        # 排序权重：必需 > 近 > 有链。缺前置标注本身不扣分 ——
        # 「变量」没有前置是应该的，那是地基。扣分的是「够近却没有前置标注」。
        sev = 0
        if npc == 0:
            sev += 40
            note = "自身没有任何前置标注"
        else:
            note = f"有 {npc} 条前置标注"
        if not reach_ok:
            sev += 25
            note += "；走不到症状节点"
        if gap is not None and gap <= 2:
            sev += 35
            note += f"；教材顺序上只隔 {gap} 个单元"
        elif gap is not None and gap <= 8:
            sev += 15
            note += f"；教材顺序上隔 {gap} 个单元"
        rows.append(dict(name=name, must=must, why=why, gap=gap, note=note,
                         sev=sev, sub=sub, npc=npc, reach=reach_ok))
    rows.sort(key=lambda r: (-int(r["must"]), -r["sev"]))

    print("%-12s %-6s %-5s %s" % ("子知识", "必需", "隔几章", "图谱状况"))
    print("-" * 64)
    for r in rows:
        print("%-12s %-6s %-5s %s" % (r["name"], "必需" if r["must"] else "相关",
                                      r["gap"] if r["gap"] is not None else "-", r["note"]))

    print("\n" + "=" * 64)
    print("最可能的卡点（必需 + 离得近 + 链是断的）：\n")
    hot = [r for r in rows if r["must"] and r["sev"] >= 60][:3]
    if not hot:
        print("  子知识本身都有链。卡点更可能在「图谱之外的表征层」——")
        print("  识字、生活经验、数量感。那一层数据里 0 个节点。")
    for r in hot:
        s2 = r["sub"]
        print(f"  · {r['name']} [{s2['bookZh']}]　{r['note']}")
        print(f"      {r['why']}")
        if args.explain and r["gap"] is not None:
            gi = kg.unit_of(s2["id"]); gj = kg.unit_of(node["id"])
            cns = kg.units["cns"]; grp, k = kg.units["pos"][gj]
            for j in range(max(0, k - 3), min(len(grp), k + 2)):
                mark = ">>>" if grp[j] == gj else ("   " if grp[j] == gi else "   ")
                print("      %s %s" % (mark, "%-26s %s" % (cns[grp[j]][0][:24], cns[grp[j]][1])))
        print()

    print("这套排序只能指出「哪一环最可能是空的」，不能确诊。")
    print("真要确诊得知道那个人具体在哪一步卡住 —— 图谱不知道学的人是谁。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
