#!/usr/bin/env python3
"""
把归一化后的图谱编译成 3D 可视化页面。

渲染器复用 os-taxonomy 那个手写 canvas 3D（零依赖，约 500 行），
本脚本只做两件事：把 graph.json 压成它要的紧凑数组、把卡片文案换成中文口径。

布局：高度 = 年级（12 层），颜色 = 学科，锥形随年级张开。
边：先修关系，方向 先修方 → 后继方。

跑:  python3 src/build_viz.py
输出: viz/知识图谱3D.html（单文件，双击即可打开，不联网）
"""
import json
import pathlib
import re
import sys
from collections import Counter, defaultdict

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from books import is_reversed, rank           # noqa: E402  册次排序，跟归一化层共用一套口径
from order import Order           # noqa: E402  教材顺序推导，与 sweep_math.py 共用一份

BASE = pathlib.Path(__file__).resolve().parent.parent
GRAPH = BASE / "data" / "normalized" / "graph.json"
TPL = BASE / "viz" / "template.html"
OUT = BASE / "viz" / "知识图谱3D.html"
# 同一份内容再出一份到根目录：GitHub Pages 只能把 index.html 当站点首页，
# 而中文文件名在 URL 里要百分号编码，当入口不好用。
INDEX = BASE / "index.html"

SUBJECTS = [                       # 顺序即颜色数组下标，必须与 payload.subjects 一致
    ("math", "数学", "#4d8dff"),
    ("physics", "物理", "#2fd6a0"),
    ("chemistry", "化学", "#ffb347"),
    ("biology", "生物", "#ff7ab6"),
]
ACC = "#ff3d7f"

LABEL_ZH = {
    "Concept": "概念", "Skill": "技能", "Exercise": "习题",
    "Experiment": "实验", "Section": "节", "Chapter": "章", "Book": "册",
}
# 只画概念与技能。习题/实验/节/章/册是容器或素材，10,685 → 7,938，画面才读得动。
# **Experiment 要画出来。**
# 原来只有 Concept/Skill，652 个 Experiment 节点从来没上过画布 ——
# 页面上的「中国的孩子在学什么」漏了 8% 的知识点。
#
# 而这 652 个不是孤岛垃圾：**464 条边涉及它们**（上游 286 + 模型 178），
# 全是物理/化学/生物的**方法链**关键环节：
#     「使用刻度尺测量长度」→「测量物体运动的平均速度」
#     「正确使用温度计的方法」→「用温度计测量水的温度」
#     「二力平衡」→「测量滑动摩擦力」
#     「用排水法测量不规则固体体积」→「测量小石块密度」
#
# 剩下 406 个确实没有任何先修边 —— 但那正是「0 前置节点」这个问题
# 的一部分，**画出来才能看见**。藏起来只会让 69.6% 这个数字好看。
KEEP = {"Concept", "Skill", "Experiment"}

# 先修边的来源。页面上每条边都要标出来是哪来的 ——
# 「上游数据集标的」和「我们用模型重建的」可信度完全不同，
# 混着显示等于让推测冒充数据。
SRC = {"dataset": 0, "model": 1, "l0": 2, "derived": 3, "intro": 4,
       "fix": 5, "structmap": 6}
SRC_ZH = {0: "上游", 1: "模型重建", 2: "能力底座", 3: "自建概念",
          4: "教材引入路径", 5: "已修正", 6: "教材结构图"}

# **来源档位 ≠ 优先级。**
# 档位数字是给页面显示用的（7 个徽标），跟「谁更可信」没有必然关系 ——
# 比如「教材引入路径」=4、「上游」=0，看起来上游优先级最高，
# 实际上上游恰恰是可信度最低的一档（ISSUE-09 逐条看过 38 条，模型全对）。
# 所以优先级必须**单独一张表**写死，不能拿档位数字凑。
#
# 顺序的依据：
#   fix       M3 逐条裁决过的修正（341 条争议边里 96.5% 判上游错）
#   intro     教材原话直接声明的依赖（「像研究一次函数一样，现在研究二次函数」）
#   structmap 教材「本章知识结构图」画出来的层级
#   derived   自建概念：节点和边都是我们的
#   model     模型重建，每条边带 why 理由，全量盲测过
#   l0        能力底座
#   upstream  上游数据集标的 —— 排最后（ISSUE-09：38 条逐条看过，模型那边全对）
TIER_SRC = {0: "upstream", 1: "model", 2: "l0", 3: "derived",
            4: "intro", 5: "fix", 6: "structmap"}
PRIORITY = {"fix": 110, "intro": 100, "structmap": 95, "derived": 70,
            "model": 60, "l0": 45, "upstream": 40}

# 年级 → 视觉层（小学 1-6，初中 7-9，高中 10-12）
GRADE = {"小学": range(1, 7), "初中": range(7, 10), "高中": range(10, 13)}


def grade_of(n):
    return n["grade"]


def main():
    g = json.load(open(GRAPH, encoding="utf-8"))
    raw_nodes, raw_edges = g["nodes"], g["edges"]

    nodes = [n for n in raw_nodes if n["label"] in KEEP and n["name"].strip()]
    idx = {n["id"]: i for i, n in enumerate(nodes)}

    # ── 自建三层接进来：L0 能力底座 + derived 概念 + 模型重建的先修边 ──
    # 数据集本身 69.6% 的节点零前置，图谱对「为什么不会」无话可说。
    # 自建层就是补这一段。**来源逐条标记**，页面上分得清哪条是上游的、
    # 哪条是我们用模型重建的 —— 混在一起就等于把推测伪装成数据。
    SELF = BASE / "data" / "normalized" / "selfbuilt-edges.json"
    self_nodes, self_edges, self_l0 = [], [], []
    if SELF.exists():
        sb = json.load(open(SELF, encoding="utf-8"))
        self_nodes = sb["nodes"]
        self_edges = sb["edges"]
        self_l0 = {n["id"]: n for n in self_nodes if n["label"] == "Ability"}
        for n in self_nodes:
            n.setdefault("grade", 0)
            nodes.append(n)
            idx[n["id"]] = len(nodes) - 1

    # 依赖关系（DAG 校验发现的环在这里被截断，避免渲染时死循环）
    prereq = defaultdict(set)
    for e in raw_edges:
        if e["type"] != "prerequisites_for":
            continue
        a, b = idx.get(e["from"]), idx.get(e["to"])
        if a is None or b is None:
            continue
        prereq[a].add(b)                      # a 的先修是 b
    # 自建边并入同一张先修表。环检测在下面统一跑 —— 自建边必须过校验，
    # 不然「模型说有环」跟「我们加出来一个环」分不清。
    edge_src = {}
    for e in raw_edges:
        if e["type"] == "prerequisites_for":
            edge_src[(e["from"], e["to"])] = 0
    for e in self_edges:
        a, b = idx.get(e["from"]), idx.get(e["to"])
        if a is None or b is None:
            continue
        prereq[a].add(b)
        edge_src[(e["from"], e["to"])] = SRC[e["source"]]

    # ── 先处理「双向边对」，再跑环检测 ────────────────────────
    # 上游 3703 条边里有 84 条跟自建边**方向相反**（ISSUE-09 那 38 条
    # 已逐条确认是上游错；非数学新增的 46 条待审）。
    #
    # 以前这些边交给下面的环检测「回边直接丢弃」——
    # **丢哪条取决于遍历顺序，是随机的**。同一份数据两次构建可能留不同的边。
    # 现在改成**按来源优先级确定性地丢**：
    #   intro（有教材原文） > derived（自建概念） > model（有 why 理由） > upstream
    # 上游排最后是有依据的：ISSUE-09 逐条看过 38 条，**模型那边全对**，
    # 上游的「证据」往往只是正文里的一句话（ISSUE-09 的原话）。
    #
    # 丢掉的边要记进 conflicts，不能默默消失。
    #
    # ── 这里曾经有一个静默失效的 bug ────────────────────────────
    # `prereq` 的键是**下标**（u、v 是 nodes 数组的下标），
    # `edge_src` 的键是**节点 id**（"math_1a_rjb_cpt3" 这样的字符串）。
    # 原来写的是 `edge_src.get((u, v), 0)` —— 拿下标去查 id 键，
    # **永远查不到**，恒返回默认值 0。
    # 于是 su == sv == 0 → `if su == sv: continue` → **整段裁决从未执行过**。
    # 页面上「对的那条留哪条」一直由后面环检测的遍历顺序决定，
    # 跟注释里写的优先级毫无关系。
    #
    # 证据：这 246 组「上游 vs 模型」的对局里，模型赢 193 组、上游赢 53 组 ——
    # **不是任何一套规则的执行结果，是遍历顺序的产物**。
    # 修好之后模型 246:0 全赢，53 条上游边翻成模型边。
    pair_drop, pair_log = set(), []
    for u in list(prereq):
        for v in list(prereq[u]):
            # **prereq 的键是 int（下标），值是后继下标集合。**
            # 原来写的是 `(v, u) in prereq` —— 拿 tuple 去查一个 int 键的 dict，
            # **恒为 False**。这是第一道门，门本来就没开过。
            # 正确的问法是「v 的后继里有没有 u」，即反向边存不存在。
            if u not in prereq.get(v, ()):
                continue
            # 这一对已经在别处判过了（(u,v) 或 (v,u) 有一个已在 pair_drop 里）
            if (u, v) in pair_drop or (v, u) in pair_drop:
                continue
            # **必须用 id 去查 edge_src**（u、v 是下标）
            iu, iv = nodes[u]["id"], nodes[v]["id"]
            su = edge_src.get((iu, iv), 0)
            sv = edge_src.get((iv, iu), 0)
            if su == sv:
                continue          # 同来源，不在这里判
            pu = PRIORITY.get(TIER_SRC.get(su, "upstream"), 40)
            pv = PRIORITY.get(TIER_SRC.get(sv, "upstream"), 40)
            if pu == pv:
                continue          # 优先级相同，交给环检测
            # **pu 大的那条赢**（优先级表里 model=60 > upstream=40）
            if pu > pv:
                winner, loser = (u, v), (v, u)
                ws, ls = su, sv
            else:
                winner, loser = (v, u), (u, v)
                ws, ls = sv, su
            pair_drop.add(loser)
            pair_log.append({
                "kept": [nodes[winner[0]]["id"], nodes[winner[1]]["id"]],
                "dropped": [nodes[loser[0]]["id"], nodes[loser[1]]["id"]],
                "keptSrc": TIER_SRC.get(ws, "upstream"),
                "droppedSrc": TIER_SRC.get(ls, "upstream"),
                "keptNames": [nodes[winner[0]]["name"], nodes[winner[1]]["name"]],
                "droppedNames": [nodes[loser[0]]["name"], nodes[loser[1]]["name"]],
                "reason": "conflict",
            })
    for u, v in pair_drop:
        prereq[u].discard(v)
    if pair_log:
        print(f"  双向边对 {len(pair_log)} 组，按来源优先级各丢 1 条")
        for r in pair_log:
            print(f"    留 {r['keptSrc']:>9}：{r['keptNames'][0]} → {r['keptNames'][1]}"
                  f"   丢 {r['droppedSrc']:>9}：{r['droppedNames'][0]} → {r['droppedNames'][1]}")

    # ── 环检测并剪枝：丢**优先级最低**的那条，不是丢回边 ──────────
    # 原来这里是「回边直接丢弃」—— 丢哪条由 DFS 遍历顺序决定。
    # 遍历顺序虽然对同一份数据是稳定的，但**没有任何理由**：
    # 一条环里上游边和模型边都在，凭什么牺牲模型边？
    #
    # 现在改成：把环找出来，丢环里**来源优先级最低**的那条。
    # 这跟前面的冲突裁决用同一张 PRIORITY 表，规则统一。
    #
    # 同优先级怎么办？用「册次倒挂」当次级判据 ——
    # 先修方出现在更晚的册次里，这条边更可能是错的
    # （ISSUE-11 实测上游 3703 条里有 188 条倒挂）。
    # 再同就按 id 稳定排序，保证同样输入永远同样结果。
    def cycle_edge_sets():
        """列出当前图里所有环的边集合（只读，不改图）。"""
        color = {}
        out = []
        for start in range(len(nodes)):
            if color.get(start):
                continue
            stack = [(start, iter(list(prereq.get(start, ()))))]
            color[start] = 1
            path_edges, path_nodes = [], [start]
            while stack:
                u, it = stack[-1]
                adv = next((v for v in it if color.get(v) != 2), None)
                if adv is None:
                    color[u] = 2
                    stack.pop()
                    if path_edges:
                        path_edges.pop()
                    if path_nodes:
                        path_nodes.pop()
                elif color.get(adv) == 1:
                    i = path_nodes.index(adv)
                    out.append(set(path_edges[i:]) | {(u, adv)})
                else:
                    color[adv] = 1
                    stack.append((adv, iter(list(prereq.get(adv, ())))))
                    path_edges.append((u, adv))
                    path_nodes.append(adv)
        return out

    def cycle_key(e):
        u, v = e
        iu, iv = nodes[u]["id"], nodes[v]["id"]
        tier = edge_src.get((iu, iv), 0)
        prio = PRIORITY.get(TIER_SRC.get(tier, "upstream"), 40)
        rev = 0
        try:
            if is_reversed(nodes[u]["book"], nodes[v]["book"],
                           nodes[u]["subject"] == nodes[v]["subject"]):
                rev = 1
        except KeyError:
            rev = 0            # 自建节点没有册次，不参与册次判据
        # 优先级小的先丢；同级里册次倒挂的先丢（-rev 把它排到前面）；再同按 id
        return (prio, -rev, iu, iv)

    to_drop = set()
    rounds = 0
    while True:
        cycs = cycle_edge_sets()
        if not cycs:
            break
        uniq, seen = [], set()
        for c in cycs:
            f = frozenset(c)
            if f not in seen:
                seen.add(f)
                uniq.append(c)
        if not uniq:
            break
        rounds += 1
        if rounds > 100:
            raise SystemExit("构建中止：环剪了 100 轮还没收敛，算法有问题")
        for c in uniq:
            e = min(c, key=cycle_key)
            prereq[e[0]].discard(e[1])
            to_drop.add(e)
    dropped = len(to_drop)
    # **环剪掉的边也要记进账。**
    # 原来只有「双向冲突」的裁决有日志，环剪掉的边是默默消失的 ——
    # 「不能默默剪掉」这条铁律要求**每一条**没进最终图的边都有出处。
    for u, v in sorted(to_drop):
        pair_log.append({
            "kept": None,
            "dropped": [nodes[u]["id"], nodes[v]["id"]],
            "keptSrc": None,
            "droppedSrc": TIER_SRC.get(edge_src.get((nodes[u]["id"], nodes[v]["id"]), 0),
                                       "upstream"),
            "keptNames": None,
            "droppedNames": [nodes[u]["name"], nodes[v]["name"]],
            "reason": "cycle",
        })
    if dropped:
        byt = Counter(TIER_SRC.get(edge_src.get((nodes[u]["id"], nodes[v]["id"]), 0),
                                    "upstream") for u, v in to_drop)
        print(f"  环剪掉 {dropped} 条（{rounds} 轮收敛），按来源：{dict(byt)}")

    # 入度（被多少人依赖），归一化成 0-1 的"重要度"
    indeg = {i: 0 for i in range(len(nodes))}
    for a, bs in prereq.items():
        for b in bs:
            indeg[b] += 1
    mx = max(indeg.values()) or 1

    # ── 关系补齐：is_a 上下位 + 章节级教材顺序 ────────────────────────
    # 为什么必须加：可视化原本只保留 Concept/Skill 之间的 prerequisites_for，
    # 于是「二次函数[九上]」显示前置 0、解锁 2，看着像凭空冒出来的。
    # 真实先修并没有丢，是记在章节节点的 leads_to 上：
    #   轴对称[8a] / 一次函数[8b] / 一元二次方程[9a] --leads_to--> 第二十二章 二次函数[9a]
    # 概念层没记 ≠ 没有前置。页面不能拿「数据集没说」冒充「它没有」。
    node_of = {n["id"]: n for n in raw_nodes}

    # 教材顺序 / 章归属 / 章级 leads_to 的推导全部搬到 src/order.py。
    # 原来这段在这里，sweep_math.py 又自己写了一份，结果两边对不上 ——
    # sweep 只按节点 id 里的 _chNN 正则找位置，concept 的 id 是
    # math_1a_rjb_cpt1，正则匹配不上，于是算出「11.7% 能定位」，
    # 这里算出「100%」。两份实现各错各的，比一份实现错更难查。
    node_ix = {n['id']: i for i, n in enumerate(nodes)}
    order = Order(raw_nodes, raw_edges, clickable=set(node_ix))
    chapter_of_node = order.chapter_of_node
    appears_of = order.appears_of
    chap_pre, chap_next = order.chap_pre, order.chap_next
    container_of = order.container_of

    # 槽位懒分配：第一次用到某个章时才占位。两种分配方式渲染结果完全一样
    # （页面只按槽位取名字），懒分配把章号压在 0~230 而不是按教材序的 0~870，
    # payload 小 38 KB。确定性不依赖这个顺序 —— 节点遍历顺序本身是稳定的。
    chs, ch_ix = [], {}
    def ch_slot(cid):
        if cid not in ch_ix:
            ch_ix[cid] = len(chs)
            c = node_of[cid]
            chs.append([c["name"], c["bookZh"]])
        return ch_ix[cid]

    # 学科下标必须跟 SUBJECTS 同一套（math=0、physics=1…）。
    # 原来写的是 enumerate(sorted(...))，那是**字母序**
    # （biology=0、chemistry=1、math=2、physics=3）。两边各自自洽所以没出事，
    # 但任何按 SUBJECTS 索引去读 cns[gi][2] 的新代码都会静默取错学科 ——
    # 数学的单元会当成化学。是个雷，先埋掉。
    cns, cn_pos = [], {}
    sub_ix = {s[0]: i for i, s in enumerate(SUBJECTS)}
    for uid, usub, ubookZh, _uname, _upos, _utot in order.units:
        cn_pos[uid] = (len(cns), order.cn_pos[uid][1], order.cn_pos[uid][2], sub_ix[usub])
        cns.append([None, None, None, None])       # 先占位，下面填
    # 每个容器记住「里面第一个可点的概念」。order 里存的是 node id，
    # 这里要的是 payload 里的下标。
    first_concept = {}
    for cid, nid in order.first_concept.items():
        if nid in node_ix:
            first_concept[cid] = node_ix[nid]
    for cid, (gi, _, _, si) in cn_pos.items():
        c = node_of[cid]
        cns[gi] = [c["name"], c["bookZh"], si, first_concept.get(cid, -1)]

    def seq_slot(nid):
        return order.seq_slot(nid)

    def book_order(nid):
        pre_, next_ = order.book_order(nid)
        return ([ch_slot(x) for x in pre_], [ch_slot(x) for x in next_])


    # is_a 的方向：具体 → 一般（「二次函数 y=a(x-h)²+k」is_a「二次函数」）。
    # 数据里有 3 个 is_a 环（已记 ISSUE 并上报上游），展示前先去重，
    # 否则同一个关系会在卡片里出现两遍。
    isa_pairs = []
    for e in raw_edges:
        if e["type"] != "is_a":
            continue
        a, b = idx.get(e["from"]), idx.get(e["to"])
        if a is not None and b is not None and a != b:
            isa_pairs.append([a, b])
    isa_pairs = sorted({tuple(p) for p in isa_pairs})
    isa_pairs = [list(p) for p in isa_pairs]

    payload_nodes = []
    for i, n in enumerate(nodes):
        props = n.get("props") or {}
        desc = (props.get("definition") or props.get("description")
                or props.get("steps") or props.get("formula") or "")
        if isinstance(desc, list):
            desc = "；".join(str(x) for x in desc[:3])
        chp, chn = book_order(n["id"])
        payload_nodes.append([
            i,
            n["name"],                       # zh
            "",                              # en（中文教材无英文名，留空走 label() 回退）
            [s[0] for s in SUBJECTS].index(n["subject"]),
            # 自建节点不属于任何一册，「—·Ability」这种写法一眼就假。
            # 它们标自己的层，不标册次。
            # **教材缺口节点（textbook）要标册次** —— 它们是真实存在于
            # 人教版某册某章的概念（「垂线及其性质[七下]」），
            # 标成「自建概念」会把教材位置丢掉，那正是补它们的目的。
            n.get("source") in ("l0", "derived") and (
                {"l0": "能力底座", "derived": "自建概念"}[n["source"]]
            ) or f"{n['bookZh']}·{LABEL_ZH.get(n['label'], n['label'])}",   # dz
            n["id"],                          # de
            grade_of(n), grade_of(n),          # a1,a2 → 布局层
            round(indeg[i] / mx, 4),          # cen → 被依赖度
            1 if n["stage"] == "初中" else 0,  # core → 中考段高亮
            str(desc)[:260],
            # 槽位 11 = 课程标准的三级要求（掌握/重要/了解），不是计数：
            # 原模板这里放的是「N 条掌握证据」，但中文数据里 59.7% 的节点为 0，
            # 展示出来一片「0 条掌握证据」，白占一行。
            props.get("importance") or "—",
            chp,                               # 12 → 教材里排在它前面的章（CHS 下标）
            chn,                               # 13 → 教材里排在它后面的章
            seq_slot(n["id"]),                 # 14 → 它所属的单元在 CNS 里的下标
        ])

    # ── 已裁决的修正（A 档双证据）──────────────────────────
    # M3 逐条裁决 341 条争议边，96.5% 是上游错。
    # A 档 19 条有**两条独立证据**（模型 dispute + 教材顺序倒挂），
    # 可以直接改：反向的加一条反向边，删除的就剔掉。
    #
    # **上游数据本身不动**（data/raw/ 只读，铁律）——
    # 改的是**页面用的派生边集**，每一笔记在 fixes 字段里，来路清楚。
    FIX = BASE / "data" / "normalized" / "confirmed-wrong.json"
    fixes = []
    if FIX.exists():
        for v in json.loads(FIX.read_text(encoding="utf-8"))["verdicts"]:
            fixes.append(v)
    fixed_del, fixed_rev = set(), []
    for v in fixes:
        if v["action"] == "删除":
            fixed_del.add((v["from"], v["to"]))
        elif v["action"] == "反向":
            fixed_rev.append(v)
            # **反向的也必须剔掉原边。**
            # 原来只加了 to→from，没删 from→to ——
            # 结果同一对节点同时出现在「前置」和「后继」里：
            # 「三角形的高」的卡片上，「三角形」既是它的前置（已修正）
            # 又是它的后继（原来的坏边，还带着「可疑」标记）。
            # 一眼就看出矛盾：它既是因又是果。
            fixed_del.add((v["from"], v["to"]))
    if fixed_del or fixed_rev:
        # 从 prereq 里剔掉要改的边（按 node id → 下标）
        for u in list(prereq):
            for v in list(prereq[u]):
                if (nodes[u]["id"], nodes[v]["id"]) in fixed_del:
                    prereq[u].discard(v)
                    edge_src.pop((nodes[u]["id"], nodes[v]["id"]), None)
                    # 裁决删掉的边也要进账
                    pair_log.append({
                        "kept": None, "dropped": [nodes[u]["id"], nodes[v]["id"]],
                        "keptSrc": None, "droppedSrc": "upstream",
                        "keptNames": None,
                        "droppedNames": [nodes[u]["name"], nodes[v]["name"]],
                        "reason": "adjudicated",
                    })
        # 反向的：加入 to→from
        for v in fixed_rev:
            a, b = idx.get(v["to"]), idx.get(v["from"])
            if a is None or b is None:
                continue
            prereq[a].add(b)
            edge_src[(v["to"], v["from"])] = SRC["fix"]
        print(f"  已按裁决修正 {len(fixed_del) + len(fixed_rev)} 条上游边"
              f"（删除 {len(fixed_del)} · 反向 {len(fixed_rev)}）")

    # ── 最终环检测（必须在修正之后）──────────────────────────
    # 上面那次环检测跑在**修正之前**。修正会新增反向边，
    # 新增的边可能跟别的边构成新环 —— 而那次检测看不见。
    # 这是个真隐患，不是理论风险：加一条反向边就能造出环。
    # 所以这里再检一次，发现环就让构建**失败**：
    # 环意味着「学 A 前要先会 B，学 B 前要先会 A」，页面不能带着它上线。
    color2, cyc2 = {}, []

    def dfs2(u, path):
        color2[u] = 1
        for v in prereq.get(u, ()):
            if color2.get(v) == 1:
                cyc2.append(path[path.index(v):] + [u, v])
            elif color2.get(v) is None:
                dfs2(v, path + [u])
        color2[u] = 2

    for nid in range(len(nodes)):
        if color2.get(nid) is None:
            dfs2(nid, [])
    if cyc2:
        for c in cyc2[:5]:
            print("    环：" + " → ".join(nodes[i]["name"] for i in c))
        raise SystemExit(f"构建中止：修正后出现 {len(cyc2)} 个环，先修边必须是 DAG")

    # ── 可疑上游边标记 ──────────────────────────────────────
    # 267 条上游先修边（7.2%）跟教材顺序倒挂、或把下位概念当前置。
    # **不删**（上游数据只读，铁律是不静默改），
    # 但要在页面上标出来 —— 否则用户拿一条可能反了的边去推「我卡在哪」。
    # 0 无 / 1 疑似（命中 1 条规则）/ 2 确认可疑（命中 ≥2 条规则）
    SUSPECT = BASE / "data" / "normalized" / "suspect-edges.json"
    suspect = {}
    if SUSPECT.exists():
        for r in json.loads(SUSPECT.read_text(encoding="utf-8")):
            suspect[(r["from"], r["to"])] = r["level"]
    # prereq 的键是**前置**、值是**后继**（prereq[前置] = {后继}），
    # 所以可疑边的 key 应该是 (前置id, 后继id) = (nodes[a], nodes[b])。
    # 方向写反的话一条都匹配不上，n_sus 恒为 0 —— 而且不报错。
    n_sus = sum(1 for k, v in suspect.items()
                if any((nodes[a]["id"], nodes[b]["id"]) == k
                       for a, bs in prereq.items() for b in bs))
    if n_sus:
        print(f"  可疑上游边 {n_sus} 条已打标记（不删，只标）")

    payload_edges = [[b, a,
                      edge_src.get((nodes[a]["id"], nodes[b]["id"]), 0),
                      suspect.get((nodes[a]["id"], nodes[b]["id"]), 0)]
                     for a, bs in prereq.items() for b in bs]   # [后继, 先修, 来源, 可疑]

    by_subject = defaultdict(int)
    for n in nodes:
        if n.get("source") in ("l0", "derived", "textbook"):
            continue          # 自建节点不计入学科知识点数
        by_subject[n["subject"]] += 1
    subjects = [{"en": s[0], "zh": s[1], "c": s[2], "n": by_subject.get(s[0], 0)} for s in SUBJECTS]

    payload = {"nodes": payload_nodes, "edges": payload_edges,
               "isa": isa_pairs, "chs": chs, "cns": cns,
               "subjects": subjects, "core": sum(1 for n in nodes if n["stage"] == "初中"),
               # 画布上画的点数（含自建），但首页写的「N 个知识点」
               # 必须只数上游那批 —— 把能力节点算进「知识点」是偷换概念。
               # **教材缺口节点（textbook）也不算在内**：
               # 它们是从教材里读出来的，不是上游数据集里的。
               "total": sum(1 for n in nodes
                            if n.get("source") not in ("l0", "derived", "textbook")),
               "drawn": len(nodes), "acc": ACC,
               # 自建能力节点的说明文字单独传：payload 节点的槽位排满了，
               # 硬塞进去会让 16 个能力的定义挤掉别的东西。
               "abi": [[n["id"], n["name"], n.get("definition", ""), n.get("blocks", ""),
                        n.get("core", "")] for n in self_l0.values()],
               "srczh": [SRC_ZH[i] for i in range(7)],
               "selfbuilt": {"nodes": len(self_nodes), "edges": len(self_edges)},
               # **别名索引。** L0 能力节点的别名（「观察力」「生活经验」
               # 「规范操作」…）是模型在盲测里实际说的词，
               # 全量跑完它们出现了 1,700+ 次 —— 但主名是「观察与发现规律」，
               # 用户搜「观察力」搜不到，等于最常被提到的名字反而搜不着。
               # id（下标）→ 别名数组
               "aliases": {i: n.get("aliases", []) for i, n in enumerate(nodes)
                           if n.get("source") == "l0" and n.get("aliases")}}

    blob = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    html = TPL.read_text(encoding="utf-8")
    html = html.replace("__DATA__", blob)

    # ── 文案：整页换成中文口径 ──
    # 注意：__N_TOPIC__ 这类占位符必须最后再替换，
    # 因为下面几条文案本身含有占位符，先替换占位符就匹配不上了。
    # 模板原文是美英小学口径（4–15 岁 / 9–10 岁核心），直接用会跟国内数据对不上。
    GRADE_MAP = ("const GRADE_ZH={1:'一年级',2:'二年级',3:'三年级',4:'四年级',"
                 "5:'五年级',6:'六年级',7:'初一',8:'初二',9:'初三',"
                 "10:'高一',11:'高二',12:'高三'};\n")
    COPY = [
        # 模板原文是美英小学口径（4–15 岁 / 9–10 岁核心），直接用会跟国内数据对不上。
        # 这一行不只是「哪套标准」，说的是**按哪套教材排的序** ——
        # 「人教版教材 · 8,590 个知识点」读起来像这些知识点来自人教版教材，
        # 实际来自 K12-KGraph，教材只用来核对顺序。写清「按…排序」。
        ("美英课程标准 · ", "按人教版教材排序 · "),
        ("<h1>全世界孩子<br>在<em>学什么</em>。</h1>",
         "<h1>中国的孩子<br>在<em>学什么</em>。</h1>"),
        # **<title>（浏览器标签页）也要改。**
        # 原来只替换了 <h1>，标签页上一直写着「全世界孩子在学什么」，
        # 页面主体却是「中国的孩子在学什么」—— 自己跟自己打架。
        # 分享链接时标签页那句最先被看见。
        ("<title>全世界孩子在学什么 · ",
         "<title>中国的孩子在学什么 · "),
        ("下面这根锥形从 4 岁长到 15 岁——越往上，概念越大越抽象。",
         "下面这根锥形从小学一年级长到高中——越往上，概念越大越抽象。"),
        ("高度是年龄", "高度是年级"),
        # 「共 X 个（另有 Y 个）」的「共」字跟括号自相矛盾 ——
        # 读起来像「总共 8590 个，其中另外有 68 个」。改成两个并列的口径。
        # 整段替换，模板里保持旧形式，这样这道守卫仍然有效
        # （模板一改就报「文案未命中」，不会静默漂移）。
        ("共 <b>__N_TOPIC__</b> 个知识点（另有 <b>__N_SELF__</b> 个我们补的能力节点与自建概念），其中 <b>__N_CORE__</b> 个属于 9–10 岁核心",
         "教材知识点 <b>__N_TOPIC__</b> 个，我们另外补了 <b>__N_SELF__</b> 个能力节点、教材节点与自建概念；其中 <b>__N_CORE__</b> 个是初中概念"),
        ("只看 9–10 岁", "只看初中"),
        ("<span class=\"hi\">9–10 岁核心</span>", "<span class=\"hi\">初中</span>"),
        ("<span>低年级基础</span>", "<span>其他学段</span>"),
        # 注意：这里的引号是 U+0027，不是中文引号。少写一个收尾引号就会静默失配。
        ("'<span>' + n.evn + ' 条掌握证据</span><span>重要度 '",
         "'<span>课程要求：' + n.evn + '</span><span>被依赖度 '"),
        # 年龄轴：模板写死 "age N"，我们画的是年级
        ("ctx.fillText('age ' + age, sx, sy);",
         GRADE_MAP + "ctx.fillText(GRADE_ZH[age] || age, sx, sy);"),
    ]
    # 文案替换必须会失败、会报错。str.replace 未命中时静默返回原串，
    # 一条失效的文案能悄悄留在成品页面上几个月——这正是本项目要抓的那类错误，
    # 自己先犯就没意思了。
    missed = []
    for a, b in COPY:
        if a not in html:
            missed.append(a)
            continue
        html = html.replace(a, b)
    if missed:
        for a in missed:
            print(f"  ✗ 文案未命中: {a[:60]}")
        raise SystemExit(f"构建中止：{len(missed)} 条文案没匹配上，先修模板或规则")

    # 卡片眉标里原来拼的是「学科 · 册次 · 3–3 岁」
    html = re.sub(r"n\.dz \+ ' · ' \+ n\.a1 \+ '–' \+ n\.a2 \+ ' 岁'", "n.dz", html)
    # 不再把空的 en 替换成「(无英文名)」：人教版教材本来就没有英文名，
    # 7,938 个节点全是空的，于是每张卡片都印一行字。现在模板里空就是空、不渲染。

    # ── 占位符：最后替换 ──
    # **__N_TOPIC__ 用 payload.total（只数上游的知识点），不是画布点数。**
    # 画布上多出来的 68 个是我们补的 L0 能力节点和 derived 概念，
    # 标题写「中国的孩子在学什么 · 8,006 个知识点」会把它们算成教材知识点 ——
    # 「中国的孩子在学什么」这句话里的「孩子」指的是教材里的知识点。
    # 数字拆成两个：教材知识点数 + 我们补的节点数。
    n_self = len(payload_nodes) - payload["total"]
    html = (html.replace("__N_TOPIC__", f"{payload['total']:,}")
                .replace("__N_SELF__", f"{n_self:,}")
                .replace("__N_EDGE__", f"{len(payload_edges):,}")
                .replace("__N_CORE__", f"{payload['core']:,}"))

    OUT.write_text(html, encoding="utf-8")
    INDEX.write_text(html, encoding="utf-8")

    print(f"节点 {len(payload_nodes):,} | 边 {len(payload_edges):,} | 剪掉的环边 {dropped}")
    print(f"is_a 上下位 {len(isa_pairs):,} 对 | leads_to 章表 {len(chs)} 章 | "
          f"能定出前置章的知识点 {sum(1 for n in payload_nodes if n[12] or n[13]):,}")
    withunit = sum(1 for n in payload_nodes if n[14] >= 0)
    print(f"教材顺序单元 {len(cns)} 个 | 能定出单元位置的知识点 {withunit:,}"
          f"（{100*withunit/len(payload_nodes):.1f}%）")
    dist = "、".join("{} {}".format(s["zh"], s["n"]) for s in subjects)
    print(f"学科分布: {dist}")

    # ── 裁决日志落盘 ─────────────────────────────────────────
    # 「不能默默剪掉」这条铁律要求丢掉的边**有账可查**。
    # 原来 pair_log 只打印到 stdout，构建完就没了 ——
    # 谁也不知道 53 条上游边被换成了模型边、为什么换。
    #
    # **写盘前跟最终图对一次账**：裁决时判「留」的边，可能又被后面的
    # 环剪枝或裁决删除给干掉了。日志必须反映**最终状态**，
    # 否则「留」和实际不符，账就是假的。
    final_pairs = {(nodes[a]["id"], nodes[b]["id"])
                   for a, bs in prereq.items() for b in bs}
    for r in pair_log:
        if r.get("kept"):
            r["keptSurvived"] = tuple(r["kept"]) in final_pairs
    CONFL = BASE / "data" / "normalized" / "prereq-conflicts.json"
    CONFL.write_text(json.dumps({
        "_comment": ("先修边从素材到成品图的完整账本。每一条没进最终图的边都在 "
                     "resolved 里，标明 reason：conflict=方向冲突按优先级裁决、"
                     "cycle=成环剪掉、adjudicated=M3 裁决删除。"
                     "上游数据本身没动（data/raw/ 只读），这里记的是"
                     "**页面上用的派生边集**的取舍。"),
        "priority": PRIORITY,
        "finalEdges": len(final_pairs),
        "resolved": pair_log,
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    by_reason = Counter(r.get("reason", "conflict") for r in pair_log)
    print(f"裁决日志 {len(pair_log)} 条 "
          f"（{' · '.join(f'{k} {v}' for k, v in sorted(by_reason.items()))}）"
          f" → {CONFL.relative_to(BASE)}")

    # 同时写一份**人可读的账**到 docs/。
    # 为什么要有两份：data/normalized/ 是 gitignore 的派生产物，
    # 里面的 JSON 谁在 GitHub 上都看不到 —— 而「不能默默剪掉」这条铁律
    # 要求账是**公开可复核**的。docs/ 进库，评审的人能直接读、能 diff。
    DOC = BASE / "docs" / "prereq-conflicts.md"
    REASON_ZH = {"conflict": "方向冲突（按来源优先级裁决）",
                  "cycle": "成环剪掉",
                  "adjudicated": "M3 裁决删除"}
    TIER_DOC = {"upstream": "上游", "model": "模型重建", "l0": "能力底座",
                "derived": "自建概念", "intro": "教材引入路径",
                "fix": "已修正", "structmap": "教材结构图"}
    lines = [
        "# 先修边裁决账本",
        "",
        "**这份文件由 `python3 src/build_viz.py` 自动生成，不要手改。**",
        "",
        "素材（`data/normalized/graph.json` + `selfbuilt-edges.json`）里的每一条先修边，",
        "要么出现在页面上，要么出现在这张账里。**下落不明的边一条都不许有** ——",
        "`src/health_check.py` 会查这条。",
        "",
        f"- 成品图边数：**{len(final_pairs):,}**",
        f"- 记在账上的：**{len(pair_log):,}** 条",
        f"- 按原因：{' · '.join(f'{REASON_ZH.get(k, k)} {v}' for k, v in sorted(by_reason.items()))}",
        "",
        "## 优先级规则",
        "",
        "| 档位 | 优先级 | 依据 |",
        "|---|---|---|",
        "| 已修正 | 110 | M3 逐条裁决过（341 条争议边里 96.5% 判上游错） |",
        "| 教材引入路径 | 100 | 教材原话直接声明的依赖 |",
        "| 教材结构图 | 95 | 教材「本章知识结构图」画出来的层级 |",
        "| 自建概念 | 70 | 节点和边都是我们的 |",
        "| 模型重建 | 60 | 每条边带 why 理由，全量盲测过 |",
        "| 能力底座 | 45 | L0 能力挂到知识点 |",
        "| 上游 | 40 | 数据集标的 —— 排最后（ISSUE-09：38 条逐条看过，模型全对） |",
        "",
        "## 逐条",
        "",
        "| # | 原因 | 留 / 丢 | 前置 | 后继 |",
        "|---|---|---|---|---|",
    ]
    for i, r in enumerate(pair_log, 1):
        if r.get("kept"):
            act = f"留 **{TIER_DOC.get(r['keptSrc'], r['keptSrc'])}**" \
                  f" ／ 丢 {TIER_DOC.get(r['droppedSrc'], r['droppedSrc'])}"
        else:
            act = f"丢 **{TIER_DOC.get(r['droppedSrc'], r['droppedSrc'])}**"
        keep = r.get("keptNames")
        drop = r.get("droppedNames")
        cell = (f"{keep[0]} → {keep[1]}" if keep else "") + \
               (" ／ " if keep and drop else "") + \
               (f"{drop[0]} → {drop[1]}" if drop else "")
        lines.append(f"| {i} | {REASON_ZH.get(r.get('reason', 'conflict'), '?')} "
                     f"| {act} | {cell} |")
    lines += ["",
              "---",
              "",
              "「留」的那条也可能后来被环剪掉（它是更长环的一部分）——",
              "JSON 里的 `keptSurvived` 字段如实记录了这一点。",
              ""]
    DOC.parent.mkdir(parents=True, exist_ok=True)
    DOC.write_text("\n".join(lines), encoding="utf-8")
    print(f"人可读账本 → {DOC.relative_to(BASE)}")

    print(f"输出 {OUT.relative_to(BASE)}  ({OUT.stat().st_size/1024:.0f} KB)")
    print(f"     {INDEX.relative_to(BASE)}  (GitHub Pages 入口，内容相同)")


if __name__ == "__main__":
    main()
