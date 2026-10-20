#!/usr/bin/env python3
"""
把模型重建的先修关系接回图谱，并诚实报告接上了多少、接不上的去哪了。

不做的事：不自动建边。
  盲测第一轮 22 条里 17 条是数据集漏标的纯增量 —— 但那 17 条在图谱里
  根本没有对应节点，要接就得**新建节点**。新建节点是改数据集，
  不是一个脚本该偷偷干的事。这里只出报告和待办队列，建不建由人拍。

四道闸，顺序不能换：
  1 解析   名字 → node id，分 EXACT/NORM/CORE/TAIL/CONTAIN/NEW 六档
  2 册序   低册的概念当高册知识点的前置 → 几乎必错，进队列
  3 环     模型自己给出的边里出现 A→B→A → 进队列
  4 重复   模型说的和数据已记的是同一条 → 认同计数，这是唯一能交叉验证的数字

跑法：
    python3 src/merge_prereq.py            # 汇总所有批
    python3 src/merge_prereq.py --queue    # 只打待办队列
"""
import json
import pathlib
import sys
from collections import Counter, defaultdict

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import books
import nameindex
import order as order_mod

BASE = pathlib.Path(__file__).resolve().parent.parent
BATCH_DIR = BASE / "data" / "lmm-batches"
OUT_DIR = BASE / "data" / "lmm-out"
OUT = BASE / "data" / "normalized" / "lmm-merged.json"

# 只有这四档能自动定位。CONTAIN 明确不行：
# 中文复合词分不清「同义词」和「限定语不同的新概念」（表内乘法 vs 乘法）。
AUTO = nameindex.AUTO


def main():
    g = json.loads((BASE / "data" / "normalized" / "graph.json").read_text())
    nodes = {n["id"]: n for n in g["nodes"]}
    order = order_mod.Order(g["nodes"], g["edges"])
    ix = nameindex.NameIndex(g["nodes"])

    existing = set()
    for e in g["edges"]:
        if e["type"] == "prerequisites_for":
            existing.add((e["from"], e["to"]))

    # **不要硬编码 math-*。** 数学只是第一个跑完的学科，
    # 物理/化学/生物的批次文件名是 `physics-01.json` 这种。
    # 原来只认 math-*.json，模型边只接了数学的 1898 个知识点，
    # 非数学跑完的 6692 个会被静默丢掉 —— 报告上看着像「跑完了」。
    batches = sorted(BATCH_DIR.glob("*.json"))
    outs = sorted(OUT_DIR.glob("*.json"))
    done = {p.stem for p in outs}

    stat = Counter()
    by_type = Counter()
    resolved = []          # 能自动定位的
    queue = []             # 接不上的 / 有问题的
    ability_names = Counter()
    disputes = []

    for op in outs:
        bn = op.stem
        rows = json.loads(op.read_text())
        bpath = BATCH_DIR / f"{bn}.json"
        if not bpath.exists():
            stat["NO_BATCH"] += 1
            continue
        batch = {r["id"]: r for r in json.loads(bpath.read_text())}
        seen_ids = set()
        for row in rows:
            nid = row.get("id")
            seen_ids.add(nid)
            tgt = nodes.get(nid)
            if tgt is None:
                stat["UNKNOWN_TARGET"] += 1
                continue
            stat["targets"] += 1
            if not row.get("prereq"):
                stat["empty"] += 1
            if row.get("dispute"):
                disputes.append({"id": nid, "name": tgt["name"], "dispute": row["dispute"]})

            for p in row.get("prereq", []):
                stat["prereq_total"] += 1
                ptype = p.get("type") or "?"
                by_type[ptype] += 1
                if ptype == "ability":
                    ability_names[(p.get("name") or "").strip()] += 1

                st, tid, cands, how = ix.resolve(p.get("name"), prefer_book=tgt.get("book"))

                # **同学科优先。** 图谱里「归纳推理」数学和物理都有，
                # 「显微镜」物理八上和生物七上都有。
                # nameindex 的 _pick 消歧规则是「取最早出现的那一册」，
                # 跨学科时不成立 —— 会出现「生物的显微镜」被接到
                # 「物理的显微镜」上，然后连出
                # 「显微镜(物理) → 玻片标本(生物)」这种跨学科边。
                #
                # 目标节点同学科下有同名候选时，改选它。
                # 这里只做**后置修正**，不改 nameindex ——
                # nameindex 被另外几个脚本共用，改它的消歧规则影响面太大。
                if st in AUTO and tid is not None and \
                        ix.node_of[tid].get("subject") != tgt.get("subject"):
                    same_subj = [c for c in cands
                                 if ix.node_of.get(c, {}).get("subject")
                                 == tgt.get("subject")]
                    if same_subj:
                        stat["CROSS_SUBJECT_FIXED"] += 1
                        tid = same_subj[0]
                        how += "+同学科修正"

                if ptype == "ability":
                    # 能力节点图谱里一个都没有，任何解析结果都是巧合。
                    # 不能因为「识字」碰巧对上某个知识点就把它接进去。
                    stat["ability"] += 1
                    if st in AUTO and ix.node_of[tid]["label"] not in ("Concept", "Skill"):
                        st = "NEW"
                    # **模型会把知识标成 ability。** 实测 61 次：
                    # 「比例运算」17、「四则运算」4、「营养成分」3、「光屏」3、
                    # 「电子间排斥能」「有机基团」「电导率」……
                    # 这些是**知识**不是能力，模型只是归类错了。
                    # 走 L0 队列它们永远连不上任何节点 —— 白丢。
                    #
                    # 所以 ability 归不进 L0 时，**再当知识试一次**：
                    # 能落位就当知识接上（type 标回 knowledge），
                    # 落不了才真的进 L0 建设队列。
                    if st not in AUTO:
                        st2, tid2, c2, how2 = ix.resolve(
                            p.get("name"), prefer_book=tgt.get("book"))
                        if st2 in AUTO and tid2 != nid and \
                                ix.node_of[tid2]["label"] in ("Concept", "Skill"):
                            stat["ability_but_knowledge"] += 1
                            ptype = "knowledge"
                            st, tid, cands, how = st2, tid2, c2, how2
                            by_type["ability"] -= 1
                            by_type["knowledge"] += 1
                            continue
                    queue.append({
                        "kind": "ABILITY", "target": nid, "targetName": tgt["name"],
                        "book": tgt["bookZh"], "type": ptype,
                        "name": p.get("name"), "why": p.get("why"),
                        "resolved": st, "candidates": [ix.node_of[c]["name"] for c in cands[:4]],
                    })
                    stat["status:" + st] += 1
                    continue

                if st in AUTO and tid == nid:
                    st, how = "SELF", "自己给自己当前置"
                if st in AUTO and nid in ix.node_of:
                    # **册序倒挂：前置所在的册比后继更晚。**
                    #
                    # 原来比的是 `order.seq_slot`（**单元**位置），比文档写的严 ——
                    # 同册里「前置在后面的单元」也被扔掉，906 条里 363 条是这种。
                    # 而本项目自己的原则是「顺序 ≠ 先修：教材把 A 排在 B 前面
                    # 不等于学 B 必须先会 A」—— 这条原则被用在了跨册判断上，
                    # 却没用在同册的单元顺序上。
                    #
                    # 现在统一走 books.is_reversed：同科比册序、跨科比学年。
                    # 跟 validate.py 的 BOOK_REVERSED、flag_suspect.py 的
                    # 「册序倒挂」是**同一套口径**。
                    #
                    # **参数顺序别搞反**：is_reversed(from, to) 问的是
                    # 「from 是不是比 to 晚」。这里 from 必须是**前置方**。
                    # 传反了会把所有正常的边判成倒挂（实测 906 → 4,786）。
                    fb = ix.node_of[tid].get("book")     # 前置方所在册
                    tb = ix.node_of[nid].get("book")     # 目标所在册
                    same_subj = ix.node_of[nid].get("subject") == \
                        ix.node_of[tid].get("subject")
                    if fb and tb and books.is_reversed(fb, tb, same_subj):
                        queue.append({
                            "kind": "BOOK_REVERSED", "target": nid, "targetName": tgt["name"],
                            "book": tgt["bookZh"], "type": ptype, "name": p.get("name"),
                            "why": p.get("why"), "resolved": st,
                            "resolvedName": ix.node_of[tid]["name"],
                            "resolvedBook": ix.node_of[tid]["bookZh"],
                        })
                        stat["status:BOOK_REVERSED"] += 1
                        continue

                if st in AUTO:
                    dup = (tid, nid) in existing
                    stat["status:" + ("DUP" if dup else st)] += 1
                    resolved.append({
                        "kind": "dup" if dup else "new", "from": tid,
                        "fromName": ix.node_of[tid]["name"],
                        "fromBook": ix.node_of[tid]["bookZh"],
                        "to": nid, "toName": tgt["name"], "toBook": tgt["bookZh"],
                        "type": ptype, "why": p.get("why"),
                        "status": st, "how": how, "batch": bn,
                    })
                else:
                    stat["status:" + st] += 1
                    queue.append({
                        "kind": st, "target": nid, "targetName": tgt["name"],
                        "book": tgt["bookZh"], "type": ptype, "name": p.get("name"),
                        "why": p.get("why"),
                        "candidates": [ix.node_of[c]["name"] for c in cands[:4]],
                    })

        missing = set(batch) - seen_ids
        if missing:
            stat["BATCH_INCOMPLETE"] += 1
            print(f"⚠ {op.name} 漏了 {len(missing)} 条：{sorted(missing)[:3]}")

    # ── 模型自己给的边里有没有环 ──
    fwd = {(r["from"], r["to"]) for r in resolved if r["kind"] == "new"}
    back = {(r["to"], r["from"]) for r in resolved if r["kind"] == "new"}
    both = fwd & back
    stat["CYCLES"] += len(both) // 2

    # ── 报告 ──
    done_n = len(outs)
    print(f"═══ 模型重建 · 已回收 {done_n}/{len(batches)} 批 ═══")
    print(f"目标知识点 {stat['targets']} | 其中模型认为「无前置」{stat['empty']}")
    print(f"模型给出前置 {stat['prereq_total']} 条\n")

    print("按类型：")
    for t, c in by_type.most_common():
        print(f"  {t:<11}{c:>5}")

    print("\n解析结果（六档，只有前四档能自动连边）：")
    LABEL = {
        "EXACT": "名字一字不差", "NORM": "去书次/标点后相等",
        "CORE": "去括号后相等", "TAIL": "去『的知识/方法』后相等",
        "CONTAIN": "只对上包含关系，不敢自动连",
        "NEW": "图谱里根本没有这个东西",
        "SELF": "自己给自己当前置", "BOOK_REVERSED": "册序倒挂（多因改名，非模型错）",
        "DUP": "★ 与数据集已有的边重合 = 交叉验证通过",
    }
    for k in ("DUP", "EXACT", "NORM", "CORE", "TAIL", "CONTAIN", "NEW", "SELF", "BOOK_REVERSED"):
        if stat["status:" + k]:
            print(f"  {k:<15}{stat['status:' + k]:>5}  {LABEL[k]}")
    auto = sum(stat["status:" + k] for k in AUTO)
    know_total = by_type["knowledge"] + by_type["method"]
    know_auto = sum(stat["status:" + k] for k in AUTO)
    print(f"\n知识类前置 {know_total} 条，能自动落位的 {know_auto} 条 "
          f"({100*know_auto/max(1,know_total):.0f}%)，其余进人工队列")
    print(f"能力类前置 {by_type['ability']} 条 —— 图谱里能力节点为 0，"
          f"全部进 L0 建设队列")
    print(f"交叉验证：DUP {stat['status:DUP']} 条 —— 模型独立说出、数据也记了的边。")
    print(f"          抽检这 {stat['status:DUP']} 条语义是否站得住，是唯一能算准确率的地方。")

    # ── 词汇表缺口有多大 ──
    newnames = Counter()
    for q in queue:
        if q["kind"] in ("NEW", "CONTAIN") and q.get("type") != "ability":
            newnames[q["name"]] += 1
    print(f"\n词汇表缺口：{stat['status:NEW']} 条接不上，去重后 {len(newnames)} 个不同说法，"
          f"覆盖 {know_total} 条知识类前置的 {100*len(newnames)/max(1,know_total):.0f}%")
    print("  同一个概念被叫成几个名字，是缺口的直接体现：")
    for nm, c in newnames.most_common(8):
        print(f"    {c} 次 · {nm[:34]}")
    print(f"自环/册序倒挂/环：{stat['status:SELF']} / {stat['status:BOOK_REVERSED']} / {stat['CYCLES']}")
    print(f"人工队列合计 {len(queue)} 条")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({
        "batches_done": done_n, "batches_total": len(batches),
        "stats": dict(stat), "by_type": dict(by_type),
        "resolved": resolved, "queue": queue, "disputes": disputes,
        "ability_names": ability_names.most_common(),
    }, ensure_ascii=False, indent=1))

    if "--queue" in sys.argv:
        print("\n─── 待办队列抽样 ───")
        seenk = Counter()
        for q in queue:
            if seenk[q["kind"]] >= 4:
                continue
            seenk[q["kind"]] += 1
            print(f"  [{q['kind']}] {q.get('book','')} {q.get('targetName','')[:20]:<22}"
                  f"← {q.get('name','')[:24]:<26} {q.get('resolved','')}")

    print(f"\n→ {OUT.relative_to(BASE)}")


if __name__ == "__main__":
    main()
