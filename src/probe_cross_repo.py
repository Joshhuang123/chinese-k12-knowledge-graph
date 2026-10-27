#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
两边的重叠度分析：cn-math-taxonomy ↔ 中文知识图谱。

要回答的问题：
  ① 他们的 2,313 个 topics 覆盖哪些学科/学段，跟我们的图谱重合多少？
  ② 他们的**题库**能挂到我们的哪些节点上？
  ③ 有多少知识点是**他们没有、我们有**的（尤其是沪教版）？
  ④ 他们的知识点比我们细还是粗？粒度差多少？

跑:  python3 src/probe_cross_repo.py <cn-math-taxonomy 目录>
"""
import collections
import json
import pathlib
import re
import sys

BASE = pathlib.Path(__file__).resolve().parent.parent
OTHER = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/cmt")


def strip_paren(s):
    return re.sub(r"[（(].*?[）)]", "", s or "").strip()


def norm(s):
    """归一化：去括号、去空白、去标点。"""
    s = strip_paren(s)
    s = re.sub(r"\s+", "", s)
    return s


def main():
    print(f"对方仓库：{OTHER}\n")

    topics = json.loads((OTHER / "data" / "topics.json").read_text(encoding="utf-8"))
    deps = json.loads((OTHER / "data" / "dependencies.json").read_text(encoding="utf-8"))
    questions = json.loads((OTHER / "data" / "questions.json").read_text(encoding="utf-8"))
    stds_raw = json.loads((OTHER / "data" / "cn-curriculum-standards.json").read_text(encoding="utf-8"))
    stds = stds_raw.get("standards", stds_raw) if isinstance(stds_raw, dict) else stds_raw

    # ── 对方规模 ──
    subj_of = {}
    for t in topics:
        # id 形如 cnm_p001（数学·小学）/ cnp_h001（物理·高中）/ cne_j001（英语·初中）
        pre = t["id"].split("_")[0] if "_" in t["id"] else "?"
        s = {"cnm": "数学", "cne": "英语", "cnp": "物理"}.get(pre, pre)
        stage = "小学"
        if pre == "cnm":
            stage = "小学" if t["id"].startswith("cnm_p") else ("初中" if t["id"].startswith("cnm_j") else "高中")
        elif pre == "cne":
            stage = "初中" if t["id"].startswith("cne_j") else "高中"
        else:
            stage = "初中" if t["id"].startswith("cnp_j") else "高中"
        subj_of[t["id"]] = s + "·" + stage
    print("=== 对方规模 ===")
    print(f"  topics {len(topics)} · dependencies {len(deps)} · questions {len(questions)}")
    print(f"  课标条目 {len(stds)}")
    by_ss = collections.Counter(subj_of.values())
    print("  按学科×学段：")
    for k, v in sorted(by_ss.items()):
        print(f"    {k:10s} {v:5d}")
    print(f"  按类型：{dict(collections.Counter(t.get('type') for t in topics))}")
    grades = collections.Counter(t.get("grade") for t in topics)
    print("  按学段：" + str(dict(sorted(grades.items(), key=lambda kv: (kv[0] is None, kv[0])))))
    qb = collections.Counter(q["topicId"] for q in questions)
    print(f"  有题的知识点 {len(qb)} / {len(topics)}；平均每点 {len(questions)/max(len(qb),1):.1f} 题")
    mc = sum(1 for t in topics if t.get("mastery_criteria"))
    dq = sum(1 for t in topics if t.get("diagnostic_question"))
    sd = sum(1 for t in topics if t.get("standards"))
    print(f"  带掌握标准 {mc} · 带诊断题 {dq} · 带课标映射 {sd}")
    hard = sum(1 for d in deps if d.get("strength") == "hard")
    print(f"  先修边 hard {hard} / soft {len(deps)-hard}")

    # ── 我方节点 ──
    import re as _re
    def payload(path):
        h = pathlib.Path(path).read_text(encoding="utf-8")
        return json.loads(_re.search(r'<script id="data" type="application/json">(.*?)</script>', h, _re.S).group(1))

    ours = {}
    for tag, path in (("人教版", BASE / "index.html"), ("沪教版", BASE / "shanghai.html"),
                      ("小学科学", BASE / "kx.html")):
        d = payload(path)
        for n in d["nodes"]:
            ours.setdefault(norm(n[1]), []).append((tag, n))

    print(f"\n=== 我方 ===")
    print(f"  三站合计去重概念名 {len(ours)} 个")

    # ── 重叠：对方 topic 能不能落到我方节点 ──
    hit = collections.Counter()
    hit_subj = collections.Counter()
    examples = []
    for t in topics:
        key = norm(t["name"])
        if key in ours:
            hit[subj_of[t["id"]]] += 1
            for tag, n in ours[key]:
                hit_subj[tag] += 1
            if len(examples) < 12:
                examples.append((t["name"], subj_of[t["id"]], [x[0] for x in ours[key]]))
    tot = len(topics)
    print(f"\n=== 重叠（对方 topic 名字能落到我方节点）===")
    print(f"  命中 {sum(hit.values())} / {tot} = {sum(hit.values())/tot*100:.1f}%")
    print(f"  按对方学科：{dict(hit)}")
    print(f"  落到我方哪一站：{dict(hit_subj)}")
    print("  样例：")
    for nm, s, tags in examples:
        print(f"    {nm[:24]:26s} {s:4s} → {'/'.join(tags)}")

    # ── 对方有题、且落在我方节点的知识点数 ──
    q_hit = sum(1 for t in topics if qb.get(t["id"], 0) > 0 and norm(t["name"]) in ours)
    print(f"\n  其中**有题**且能落地的：{q_hit}")

    # ── 沪教版独占：他们没有、我们有 ──
    sh = payload(BASE / "shanghai.html")
    sh_names = {norm(n[1]) for n in sh["nodes"]}
    their_names = {norm(t["name"]) for t in topics}
    only_sh = sh_names - their_names
    print(f"\n=== 沪版站有、他们没有的概念名：{len(only_sh)} / {len(sh_names)} ===")
    print("  样例：", list(only_sh)[:10])

    # ── 粒度对比 ──
    print("\n=== 粒度对比 ===")
    print(f"  对方数学知识点 {sum(1 for t in topics if subj_of[t['id']].startswith('数学'))} 个")
    print(f"  对方英语知识点 {sum(1 for t in topics if subj_of[t['id']].startswith('英语'))} 个")
    print(f"  对方物理知识点 {sum(1 for t in topics if subj_of[t['id']].startswith('物理'))} 个")
    print(f"  我方人教站节点 {len(payload(BASE/'index.html')['nodes'])} 个")
    print("  —— 对方是「教学知识点」（带掌握标准+题），我方是「教材概念」（带页码+原文）")

    # ── 双方都有的概念，先修边能不能对齐 ──
    print("\n=== 先修边能不能对齐 ===")
    # 对方：topicId 的先修是 prerequisiteId
    o_pairs = set()
    for d in deps:
        a = norm_by_id.get(d["topicId"]) if False else None
    byid = {t["id"]: norm(t["name"]) for t in topics}
    for d in deps:
        if d["topicId"] in byid and d["prerequisiteId"] in byid:
            o_pairs.add((byid[d["topicId"]], byid[d["prerequisiteId"]]))
    print(f"  对方边（按名字归一后）：{len(o_pairs)} 条")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
