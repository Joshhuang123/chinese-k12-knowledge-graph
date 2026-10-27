#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
映射可行性（正确版）：他们的 topic 能不能挂到我们的节点上。

**关键发现**：两边颗粒度不同、名字不同，但**都锚在教材的「单元/节」上**：
  对方 chapter：「一年级上册 第1单元 5以内数的认识和加、减法」
  我方   cns ：['5以内数的认识和加减法', '一上', 0, 10]

所以映射走两步，都用**教材自己的名字**当锚点（不是我方起的概念名）：
  ① 册次 + 单元名 → 定位到我方的单元
  ② 单元内，概念名模糊匹配

⚠️ 纯名称模糊匹配**会出错**（实测「5以内的加法」→「10以内的加法」sim 0.77），
   所以必须先锚到单元，单元内再比 —— 误配率会大幅下降。

跑:  python3 src/probe_mapping.py <cn-math-taxonomy 目录>
"""
import collections
import difflib
import json
import pathlib
import re
import sys

BASE = pathlib.Path(__file__).resolve().parent.parent
OTHER = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/cmt")

# 册次叫法 → 规范码。
# 对方的叫法比我们多（「七年级上册」「高一」「九全」「必修第一册」…），
# 我方 CNS 用的是「七上」「必修一」「选必一」这一套。
VOL = {}
for _i, _cn in enumerate("一二三四五六七八九", 1):
    for _s, _sfx in (("上", "a"), ("下", "b")):
        VOL[f"{_cn}{_s}"] = f"{_i}{_sfx}"
        VOL[f"{_cn}年级{_s}册"] = f"{_i}{_sfx}"
VOL.update({
    "九全": "9", "九年级": "9", "九": "9",
    "必修一": "bx1", "必修二": "bx2", "必修三": "bx3", "必修四": "bx4",
    "必修第一册": "bx1", "必修第二册": "bx2", "必修第三册": "bx3", "必修第四册": "bx4",
    "选择性必修一": "xzxbx1", "选择性必修二": "xzxbx2", "选择性必修三": "xzxbx3",
    "选择性必修第一册": "xzxbx1", "选择性必修第二册": "xzxbx2", "选择性必修第三册": "xzxbx3",
    "选必一": "xzxbx1", "选必二": "xzxbx2", "选必三": "xzxbx3",
    # 人教 A 版：必修一在高一、必修二在高二（对方 README 明确说明这个约定）
    "高一": "bx1", "高二": "bx2", "高三": "bx3",
})
# 对方册次码 → 我方 CNS 用的册次名
CNS_VOL = {f"{i}{s}": f"{cn}{'上' if s=='a' else '下'}"
           for i, cn in enumerate("一二三四五六七八九", 1) for s in ("a", "b")}
CNS_VOL.update({"9": "九年级", "bx1": "必修一", "bx2": "必修二", "bx3": "必修三",
                "bx4": "必修四", "xzxbx1": "选必一", "xzxbx2": "选必二", "xzxbx3": "选必三"})


def norm(s):
    s = re.sub(r"[（(].*?[）)]", "", s or "").strip()
    s = re.sub(r"[、，,。\s]", "", s)
    return s


def parse_chapter(ch):
    """→ (册次码, 单元/节名)"""
    if not ch:
        return None, None
    for k, v in VOL.items():
        if ch.startswith(k):
            rest = ch[len(k):].strip()
            rest = re.sub(r"^第[0-9一二三四五六七八九十]+[单元章]\s*", "", rest).strip()
            rest = re.sub(r"^第[0-9一二三四五六七八九十]+章\s*", "", rest).strip()
            rest = re.sub(r"\s+[0-9]+\.[0-9]+\s*$", "", rest).strip()   # 高中末尾的 1.1
            return v, rest
    return None, None


def sim(a, b):
    return difflib.SequenceMatcher(None, a, b).ratio()


def main():
    topics = json.loads((OTHER / "data" / "topics.json").read_text(encoding="utf-8"))
    questions = json.loads((OTHER / "data" / "questions.json").read_text(encoding="utf-8"))

    # ── 我方人教站：单元 + 单元内的概念名 ──
    import re as _re
    h = (BASE / "index.html").read_text(encoding="utf-8")
    D = json.loads(_re.search(r'<script id="data" type="application/json">(.*?)</script>', h, _re.S).group(1))
    cns = D.get("cns", [])
    nodes = D["nodes"]
    # cns[i] = [单元名, 册次, 学科槽位, 里面第一个可点的概念下标]
    unit_of = {}          # (册次, 单元名) -> [概念名...]
    unit_bounds = []
    for i, c in enumerate(cns):
        unit_bounds.append((i, c[0], c[1], c[3]))
    # ⚠️ 161 个单元的 first = -1（高中那些章没有直接指到概念）。
    # 直接用「下一个单元的 first」当边界会错位，
    # 所以边界只在**有效 first** 之间切。
    valid = sorted((f, nm, vol) for (_i, nm, vol, f) in unit_bounds if f >= 0)
    for k, (f, nm, vol) in enumerate(valid):
        nxt = valid[k + 1][0] if k + 1 < len(valid) else len(nodes)
        names = [nodes[j][1] for j in range(f, nxt) if j < len(nodes)]
        unit_of.setdefault((vol, norm(nm)), []).extend(names)
    # 另建一份「规范码 → 单元名」的索引（对方册次码 → 我方册次名要转换）
    vol2units = collections.defaultdict(list)
    for (vol, un), names in unit_of.items():
        vol2units[vol].append((un, names))
    # 反查：我方册次名 → 规范码
    name2code = {}
    for code, nm in CNS_VOL.items():
        name2code[nm] = code
    unit_by_code = collections.defaultdict(list)
    for (volname, un), names in unit_of.items():
        unit_by_code[name2code.get(volname, volname)].append((un, names))
    print(f"我方人教站：{len(nodes)} 节点 / {len(cns)} 单元 / {len(unit_of)} 个(册次,单元)键")

    # ── 对方 topic → 单元 → 概念 ──
    stat = collections.Counter()
    mapped = {}
    unmapped_examples = []
    for t in topics:
        vol, unit = parse_chapter(t.get("chapter", ""))
        if not vol:
            stat["册次解析失败"] += 1
            continue
        stat["册次解析成功"] += 1
        cands = unit_of.get((CNS_VOL.get(vol, vol), norm(unit)))
        if not cands:
            # 单元名模糊（限定同册次）
            best, bestr = None, 0.0
            for u2, names in unit_by_code.get(vol, []):
                r = sim(norm(unit), u2)
                if r > bestr:
                    bestr, best = r, names
            if bestr >= 0.78:
                cands = best
                stat["单元模糊匹配"] += 1
            else:
                stat["单元对不上"] += 1
                if len(unmapped_examples) < 10:
                    unmapped_examples.append((t["name"], t.get("chapter", "")))
                continue
        else:
            stat["单元精确匹配"] += 1
        tn = norm(t["name"])
        exact = [c for c in cands if norm(c) == tn]
        if exact:
            mapped[t["id"]] = exact[0]
            stat["概念精确"] += 1
            continue
        best, bestr = None, 0.0
        for c in cands:
            r = sim(tn, norm(c))
            if r > bestr:
                bestr, best = r, c
        if bestr >= 0.88:
            mapped[t["id"]] = best
            stat["概念模糊≥0.80"] += 1
        else:
            stat["概念对不上"] += 1

    tot = len(topics)
    print(f"\n=== 映射结果（对方 {tot} 个 topic）===")
    for k, v in stat.most_common():
        print(f"  {k:14s} {v:5d}  ({v/tot*100:.1f}%)")
    got = len(mapped)
    print(f"  ── 挂上：**{got} / {tot} = {got/tot*100:.1f}%**")

    # 抽样看映射对不对
    print("\n=== 映射样例 ===")
    byid = {t["id"]: t for t in topics}
    ks = list(mapped)[:14]
    for tid in ks:
        print(f"  对方「{byid[tid]['name'][:20]:22s}」→ 我方「{mapped[tid][:20]:22s}」")

    # 题库能带过来多少
    qb = collections.Counter(q["topicId"] for q in questions)
    q_mapped = sum(qb.get(t, 0) for t in mapped)
    print(f"\n=== 题库 ===")
    print(f"  可挂上的 topic：{got}")
    print(f"  对应题目：**{q_mapped} / {len(questions)} = {q_mapped/len(questions)*100:.1f}%**")

    # ── 我方有多少概念根本没有对方对应（= 需要自己出题的部分）──
    mine = {n[1] for n in nodes}
    covered = {mapped[t] for t in mapped}
    print(f"\n=== 缺口 ===")
    print(f"  我方人教站 {len(mine)} 个概念名，对方题库覆盖 {len(covered & mine)}")
    print(f"  **没有题的概念：{len(mine) - len(covered & mine)}**")
    print(f"  教材原句可用的概念（data/concept-text.jsonl）：", end=" ")
    n_txt = sum(1 for x in (BASE / "data" / "concept-text.jsonl").read_text(encoding="utf-8").splitlines() if x.strip())
    print(n_txt)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
