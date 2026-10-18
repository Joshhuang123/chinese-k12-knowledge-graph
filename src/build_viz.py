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
from collections import defaultdict

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

    payload_nodes = []
    for i, n in enumerate(nodes):
        props = n["props"] or {}
        desc = (props.get("definition") or props.get("description")
                or props.get("steps") or props.get("formula") or "")
        if isinstance(desc, list):
            desc = "；".join(str(x) for x in desc[:3])
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
        ])

    payload_edges = [[b, a] for a, bs in prereq.items() for b in bs]   # [后继, 先修]

    by_subject = defaultdict(int)
    for n in nodes:
        by_subject[n["subject"]] += 1
    subjects = [{"en": s[0], "zh": s[1], "c": s[2], "n": by_subject.get(s[0], 0)} for s in SUBJECTS]

    payload = {"nodes": payload_nodes, "edges": payload_edges,
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
    html = html.replace("n.en;", '"(无英文名)";')

    # ── 占位符：最后替换 ──
    html = (html.replace("__N_TOPIC__", f"{len(payload_nodes):,}")
                .replace("__N_EDGE__", f"{len(payload_edges):,}")
                .replace("__N_CORE__", f"{payload['core']:,}"))

    OUT.write_text(html, encoding="utf-8")
    INDEX.write_text(html, encoding="utf-8")

    print(f"节点 {len(payload_nodes):,} | 边 {len(payload_edges):,} | 剪掉的环边 {dropped}")
    dist = "、".join("{} {}".format(s["zh"], s["n"]) for s in subjects)
    print(f"学科分布: {dist}")
    print(f"输出 {OUT.relative_to(BASE)}  ({OUT.stat().st_size/1024:.0f} KB)")
    print(f"     {INDEX.relative_to(BASE)}  (GitHub Pages 入口，内容相同)")


if __name__ == "__main__":
    main()
