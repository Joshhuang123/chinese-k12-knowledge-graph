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
from collections import defaultdict

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from books import rank           # noqa: E402  册次排序，跟归一化层共用一套口径
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
KEEP = {"Concept", "Skill"}

# 先修边的来源。页面上每条边都要标出来是哪来的 ——
# 「上游数据集标的」和「我们用模型重建的」可信度完全不同，
# 混着显示等于让推测冒充数据。
SRC = {"dataset": 0, "model": 1, "l0": 2, "derived": 3}
SRC_ZH = {0: "上游", 1: "模型重建", 2: "能力底座", 3: "自建概念"}

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

    # 环检测并剪枝：回边直接丢弃（先把要删的边收集完，再统一改集合，
    # 不能一边迭代一边改 —— 会 RuntimeError: Set changed size during iteration）
    color, to_drop = {}, set()
    for start in range(len(nodes)):
        if color.get(start):
            continue
        stack = [(start, iter(list(prereq.get(start, ()))))]
        color[start] = 1
        while stack:
            u, it = stack[-1]
            adv = next((v for v in it if color.get(v) != 2), None)
            if adv is None:
                color[u] = 2
                stack.pop()
            elif color.get(adv) == 1:
                to_drop.add((u, adv))
            else:
                color[adv] = 1
                stack.append((adv, iter(list(prereq.get(adv, ())))))
    for u, v in to_drop:
        prereq[u].discard(v)
    dropped = len(to_drop)

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

    payload_edges = [[b, a, edge_src.get((nodes[a]["id"], nodes[b]["id"]), 0)]
                     for a, bs in prereq.items() for b in bs]   # [后继, 先修, 来源]

    by_subject = defaultdict(int)
    for n in nodes:
        if n.get("source") in ("l0", "derived"):
            continue          # 自建节点不计入学科知识点数
        by_subject[n["subject"]] += 1
    subjects = [{"en": s[0], "zh": s[1], "c": s[2], "n": by_subject.get(s[0], 0)} for s in SUBJECTS]

    payload = {"nodes": payload_nodes, "edges": payload_edges,
               "isa": isa_pairs, "chs": chs, "cns": cns,
               "subjects": subjects, "core": sum(1 for n in nodes if n["stage"] == "初中"),
               # 画布上画的点数（含自建），但首页写的「N 个知识点」
               # 必须只数上游那批 —— 把能力节点算进「知识点」是偷换概念。
               "total": sum(1 for n in nodes if n.get("source") not in ("l0", "derived")),
               "drawn": len(nodes), "acc": ACC,
               # 自建能力节点的说明文字单独传：payload 节点的槽位排满了，
               # 硬塞进去会让 16 个能力的定义挤掉别的东西。
               "abi": [[n["id"], n["name"], n.get("definition", ""), n.get("blocks", ""),
                        n.get("core", "")] for n in self_l0.values()],
               "srczh": [SRC_ZH[i] for i in range(4)],
               "selfbuilt": {"nodes": len(self_nodes), "edges": len(self_edges)}}

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
        ("美英课程标准 · ", "人教版教材 · "),
        ("<h1>全世界孩子<br>在<em>学什么</em>。</h1>",
         "<h1>中国的孩子<br>在<em>学什么</em>。</h1>"),
        ("下面这根锥形从 4 岁长到 15 岁——越往上，概念越大越抽象。",
         "下面这根锥形从小学一年级长到高中——越往上，概念越大越抽象。"),
        ("高度是年龄", "高度是年级"),
        ("其中 <b>__N_CORE__</b> 个属于 9–10 岁核心", "其中 <b>__N_CORE__</b> 个属于初中"),
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
    html = (html.replace("__N_TOPIC__", f"{len(payload_nodes):,}")
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
    print(f"输出 {OUT.relative_to(BASE)}  ({OUT.stat().st_size/1024:.0f} KB)")
    print(f"     {INDEX.relative_to(BASE)}  (GitHub Pages 入口，内容相同)")


if __name__ == "__main__":
    main()
