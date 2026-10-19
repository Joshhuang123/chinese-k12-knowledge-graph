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

# 年级 → 视觉层（小学 1-6，初中 7-9，高中 10-12）
GRADE = {"小学": range(1, 7), "初中": range(7, 10), "高中": range(10, 13)}


def grade_of(n):
    return n["grade"]


def main():
    g = json.load(open(GRAPH, encoding="utf-8"))
    raw_nodes, raw_edges = g["nodes"], g["edges"]

    nodes = [n for n in raw_nodes if n["label"] in KEEP and n["name"].strip()]
    idx = {n["id"]: i for i, n in enumerate(nodes)}

    # 依赖关系（DAG 校验发现的环在这里被截断，避免渲染时死循环）
    prereq = defaultdict(set)
    for e in raw_edges:
        if e["type"] != "prerequisites_for":
            continue
        a, b = idx.get(e["from"]), idx.get(e["to"])
        if a is None or b is None:
            continue
        prereq[a].add(b)                      # a 的先修是 b

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

    chapter_of = {}
    for e in raw_edges:
        if e["type"] == "is_part_of" and node_of.get(e["from"], {}).get("label") == "Section":
            chapter_of[e["from"]] = e["to"]

    # appears_in 有两种指向，差别只在一个 label 上：
    #   初中/高中 → Section（8,125 条），再 is_part_of 上溯到 Chapter；
    #   **小学 → 直接指 Chapter（819 条）**。
    # 第一版只认前者，于是 782 个小学知识点里有 742 个拿不到教材顺序，
    # 卡片上「教材里排在它前面的章」整栏是空的 —— 而小学章其实有 69 条
    # leads_to，数据一直都在，是我们没接上。
    chapter_of_node = defaultdict(list)
    appears_of = defaultdict(list)      # 容器 → 属于它的知识点（appears_in 的反向）
    for e in raw_edges:
        if e["type"] != "appears_in":
            continue
        tgt = node_of.get(e["to"], {})
        if tgt.get("label") == "Section":
            ch = chapter_of.get(e["to"])
            if ch:
                chapter_of_node[e["from"]].append(ch)
            appears_of[e["to"]].append(e["from"])
        elif tgt.get("label") == "Chapter":
            chapter_of_node[e["from"]].append(e["to"])
            appears_of[e["to"]].append(e["from"])

    # leads_to 只有章与章之间才是「教材顺序」，混进节/册会得到一堆噪音
    chap_pre, chap_next = defaultdict(list), defaultdict(list)
    for e in raw_edges:
        if e["type"] != "leads_to":
            continue
        if node_of.get(e["from"], {}).get("label") != "Chapter" or \
           node_of.get(e["to"], {}).get("label") != "Chapter":
            continue
        chap_pre[e["to"]].append(e)
        chap_next[e["from"]].append(e)

    # 同一个章会被几百个知识点引用，节点槽位里只存下标
    chs, ch_ix = [], {}

    def ch_slot(cid):
        if cid not in ch_ix:
            c = node_of[cid]
            ch_ix[cid] = len(chs)
            chs.append([c["name"], c["bookZh"]])
        return ch_ix[cid]

    # ── 教材顺序链：从节点 id 直接推，不依赖任何外部数据源 ────────────
    # 609 个 Section 全部带 _chNN_sMM，264 个 Chapter 带 _chNN，
    # 配上 books.py 的册序，完整教学顺序就写在 id 里。
    #
    # 已经用人教社官方 PDF 的目录逐册核对过（见 src/verify_order.py）：
    # 数学一上「准备课→位置→5以内→认识图形（一）→6~10→11~20→认识钟表→
    # 20以内的进位加法→总复习」、四下、九上、物理八下、化学必修一全部吻合。
    #
    # **顺序 ≠ 先修**：教材把 A 排在 B 前面，不等于学 B 必须先会 A。
    # 页面文案因此叫「教材顺序」，不叫「前置」——两者不能混。
    seq_key = {}
    for n in raw_nodes:
        m = re.search(r"_ch(\d+)(?:_s(\d+))?$", n["id"])
        if m:
            seq_key[n["id"]] = (int(m.group(1)), int(m.group(2) or 0))

    # 每个学科按 (册序, ch, s) 排成一个总序列
    order_by_subject = defaultdict(list)
    for n in raw_nodes:
        if n["label"] not in ("Section", "Chapter") or n["id"] not in seq_key:
            continue
        ch, s = seq_key[n["id"]]
        order_by_subject[n["subject"]].append((rank(n["book"]), ch, s, n["id"]))
    for v in order_by_subject.values():
        v.sort(key=lambda x: (x[0], x[1], x[2]))

    # 容器在序列中的位置 → 全局表；每个容器记住「里面第一个可点的概念」
    cns, cn_pos = [], {}
    for si, (sub, lst) in enumerate(sorted(order_by_subject.items())):
        for pos, (_, _, _, cid) in enumerate(lst):
            cn_pos[cid] = (len(cns), pos, len(lst), si)
            cns.append([None, None, None, None])       # 先占位，下面填
    node_ix = {n["id"]: i for i, n in enumerate(nodes)}
    # 每个容器记住「里面第一个可点的概念」。按 cn_pos 的自然顺序扫，
    # 命中的第一个就是教材顺序最靠前的那个容器 —— 与下面 container_of
    # 取「最靠前的容器」是同一套口径（这里不能反过来依赖 container_of）。
    first_concept = {}
    for cid in cn_pos:
        for nid in appears_of.get(cid, ()):
            if nid in node_ix and cid not in first_concept:
                first_concept[cid] = node_ix[nid]
    for cid, (gi, _, _, si) in cn_pos.items():
        c = node_of[cid]
        cns[gi] = [c["name"], c["bookZh"], si, first_concept.get(cid, -1)]

    # 概念 → 它所属的容器（Section 或 Chapter）。一个概念可能出现在多个容器里，
    # 取全局表里最靠前的那个，保证同一个概念在页面上位置唯一且稳定。
    container_of = defaultdict(list)
    for cid in cn_pos:
        for nid in appears_of.get(cid, ()):
            container_of[nid].append(cid)
    for v in container_of.values():
        v.sort(key=lambda c: cn_pos[c][0])

    def seq_slot(nid):
        """它属于教材序列里的哪个单元。

        优先挑**有可点概念**的那个容器，不是编号最小的那个。
        初中/高中概念挂在 Section 上（「第一节 二次函数的图象和性质」），
        Chapter 层自己一个概念都没有 —— 按编号最小挑的话，每个知识点
        都会落在那个点不动的章上，「下一单元」按钮点了没反应。
        """
        cs = container_of.get(nid) or []
        if not cs:
            return -1
        withconcept = [c for c in cs if first_concept.get(c, -1) >= 0]
        return cn_pos[(withconcept or cs)[0]][0]

    def book_order(nid):
        """→ (leads_to 标为前置的章, leads_to 指向的后续章)，都是 CHS 的下标。

        必须用 chapter_of_node 上溯到 Chapter，不能用 container_of ——
        后者对初中/高中给的是 Section，而 chap_pre 是按 Chapter 建的键，
        直接拿 Section 去查会一个都查不到（第一版就这么写的，
        7,510 掉到 569，全库 95% 的知识点凭空丢掉前置章）。
        """
        chs_ = chapter_of_node.get(nid) or []
        if not chs_:
            return [], []
        ch = chs_[0]
        return ([ch_slot(e["from"]) for e in chap_pre.get(ch, ())],
                [ch_slot(e["to"]) for e in chap_next.get(ch, ())])

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
        props = n["props"] or {}
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
            f"{n['bookZh']}·{LABEL_ZH.get(n['label'], n['label'])}",   # dz
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

    payload_edges = [[b, a] for a, bs in prereq.items() for b in bs]   # [后继, 先修]

    by_subject = defaultdict(int)
    for n in nodes:
        by_subject[n["subject"]] += 1
    subjects = [{"en": s[0], "zh": s[1], "c": s[2], "n": by_subject.get(s[0], 0)} for s in SUBJECTS]

    payload = {"nodes": payload_nodes, "edges": payload_edges,
               "isa": isa_pairs, "chs": chs, "cns": cns,
               "subjects": subjects, "core": sum(1 for n in nodes if n["stage"] == "初中"),
               "total": len(nodes), "acc": ACC}

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
