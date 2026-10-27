#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
从**教材原话**确定性地生成可自动判分的练习题。

为什么是确定性的
----------------
LLM 通道（`MINIMAX_API_KEY` → llm_call.py）现在 401 —— 那个 key 对
`agent.minimax.cn` 端点无效。所以这一轮不做模型出题。

而且确定性出题有个模型出题没有的好处：**每一道题都逐字来自教材**。
选项、答案、解析全都是教材原句的重新排列 ——
不存在「模型自己补的知识混进来」的风险。

⚠️ 第一版做过，两处都是**设计缺陷**（不是实现 bug）：
  ① 选项重复 —— 同一本书同一概念被重复选中
  ② **题干泄露答案** —— 教材的定义句本来含概念名
     （「几个单项式的和叫做整式」），学生不看选项就知道是哪个
     ②的修法：**把概念名挖空**（「几个单项式的和叫做____」）
     —— 这一步同时解决了两个方向的泄露

两种题型
--------
**A. 定义配对（正→反）**
    「下面哪一句是教材给「X」下的定义？」
    1 句真定义（X 已挖空）+ 3 句别的概念的真定义（也挖空了各自的名字）

**B. 概念配对（反→正）**
    「教材里说『……』——说的是哪个概念？」
    用**提及句**（教材提到了这个概念但没给它下定义），概念名挖空

质量闸（不合就丢弃，宁缺毋滥）
----------------------------
  · 句子要**完整**（长度 12–120 字，括号配对）
  · **不能有 OCR 残骸**（连续点+页码、孤立公式残片、半截句）
  · 定义句**必须含该概念名**（不含就不是它的定义）
  · 题干和**每一个选项**都不能泄露答案
  · 四个选项**互不相同**

跑:  python3 src/build_learn_questions.py
输出: data/learn-questions.jsonl
"""
import collections
import json
import pathlib
import random
import re
import sys

BASE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE / "src"))

VERSIONS = [("sh", "沪教版/沪科版"), ("rjb", "人教版"), ("kx", "小学科学")]
OUT = BASE / "data" / "learn-questions.jsonl"

MIN_LEN = 12
MAX_LEN = 120
MASK = "＿＿"


def load(tag):
    txt = (BASE / "data" / f"learn-{tag}.js").read_text(encoding="utf-8")
    return json.loads(txt[txt.index("=") + 1:].rstrip().rstrip(";"))


def clean_quote(t: str) -> str:
    t = re.sub(r"\s+", " ", t or "").strip()
    t = re.sub(r"上海教育出版社|上海科学技术出版社|人民教育出版社", "", t).strip()
    return t


# 句子开头/结尾出现这些字 → 一定是**上一栏/上一页续接的半截句**
# （实测「时所放出的＿＿叫做该物质的燃烧炊」开头就是个「时」）
FRAG_HEAD = set("的和与及或则就也都更最不没很把被让使将对于从向到在为是有个只")
FRAG_TAIL = set("的和与及或则就也都更最不没很把被让使将对于从向到在为是有个只时")
# 定义标志 —— 「哪一句是定义」这种题，四个选项都该是定义句
DEF_VERB = ("叫做", "称为", "叫作", "是指", "就是", "我们把", "规定")
# ⚠️ 「被称为」**不算**定义标志 —— 那是**别的概念**的定义句，
#    不是这句自己在定义东西（实测「…曾经被称为『碳水化合物』」）。


def is_broken(t: str) -> bool:
    """OCR 残骸检测 —— 宁可漏，不要出一道废题。"""
    if not (MIN_LEN <= len(t) <= MAX_LEN):
        return True
    # 半截句：开头或结尾是虚词/介词
    if t[0] in FRAG_HEAD or t[-1] in FRAG_TAIL:
        return True
    # **截断**：句子没以句号/括号收尾，说明后面还有半句被 OCR 丢了
    # （实测「…保护生物多样性就是保护」—— 整句被切断）
    if not re.search(r"[。．)）\"”]$", t):
        return True
    # 句中夹单个大写字母（OCR 把汉字读坏了：「昌Ra」「炊，习惯」）
    if re.search(r"[一-鿿][A-Z]", t):
        return True
    # 开头是标点 → 上一句的尾巴接过来了（实测「(boiling).液体沸腾时的温度叫做…」）
    if t[0] in ").,，。、：:；;\"“":
        return True
    # 开头是题号 → 例题不是定义句（实测「(1)试从葡欧糖的分子组成解释…」）
    if re.match(r"^[（(]?\d+[）).、]", t):
        return True
    if re.search(r"\.{3,}\s*\d+", t):          # 目录残骸
        return True
    if t.count("（") != t.count("）") or t.count("(") != t.count(")"):
        return True
    # 公式残骸：出现 =、^、\、下标数字堆
    if re.search(r"\\[a-zA-Z]+|\\\\", t):
        return True
    if re.search(r"[=^]", t):
        return True
    # 半截句：以逗号/顿号/连词结尾
    if t[-1] in "，、,：:和与而且或则":
        return True
    # 明显的残句：出现「。.」后紧跟半个词（OCR 断字）
    if re.search(r"[一-鿿][.．][一-鿿]", t):
        return True
    # 题干腔（不是定义，是练习指令）
    if re.match(r"^(例|练习|习题|复习|思考与练习|小组讨论|探究)\s*[0-9一二三四五六七八九十]", t):
        return True
    if "下列" in t or "不正确的是" in t or "正确的是" in t:
        return True
    return False


def def_anchor(t: str, name: str) -> bool:
    """这个概念**是不是这句定义的宾语**？

    必须满足：定义动词后面紧跟概念名。
    「动能、重力势能和弹性势能统称为机械能。」✓
    「由两种元素组成的化合物中,其中一种元素是氧元素的叫做氧化物。」✓
    「如果两个数互素,那么它们的最大公因数就是1。」（概念名是「因数」，
      句中却是「最大公因数」——**定义的不是它**）✗

    ⚠️ 少了这一道，教材原话里 `def` 标记不准的句子会混进来 ——
    实测「因数」题的答案竟是「最大公＿＿就是1」。
    """
    for v in DEF_VERB:
        i = t.find(v)
        while i >= 0:
            if v == "称为" and i > 0 and t[i - 1] == "被":
                i = t.find(v, i + 1)
                continue
            rest = t[i + len(v):].lstrip()
            if rest.startswith(name):
                return True
            i = t.find(v, i + 1)
    return False


def is_def_shape(t: str) -> bool:
    """这句是不是**定义句的形态**？

    定义动词（叫做/称为/是指…）必须出现在后半段 ——
    动词在前面的是「××叫做××」的例句，不是定义句。
    「哪一句是定义」这种题，四个选项都必须是定义句才成立。
    """
    # 「被称为」不算（见 DEF_VERB 注释）
    tt = t.replace("被称为", "被称为")
    pos = -1
    for v in DEF_VERB:
        i = tt.find(v)
        if i >= 0 and (pos < 0 or i < pos):
            # 「被称为X」里的「称为」不算
            if v == "称为" and i > 0 and tt[i - 1] == "被":
                continue
            pos = i
    return pos >= 0 and pos >= len(t) * 0.45


def core_name(nm: str) -> str:
    """概念的核心词 —— 去掉修饰后缀。

    「三角形的外角」→ 「三角形」
    「一元二次方程的一般形式」→ 「一元二次方程」

    ⚠️ 放宽了名字，**定义动词的位置检查不能放宽** ——
    实测放宽后出现「pH 越小溶液酸性越强」被挖空、
    「DNA 上有指导生物发育的全部信息」被挖空这类废题。
    """
    m = re.match(r"^(.*?)的[^的]{1,8}$", nm or "")
    if m and len(m.group(1)) >= 2:
        return m.group(1)
    return nm


def mask_name(t: str, name: str) -> str:
    """把概念名挖空 —— 这是防泄露的关键一步。"""
    if not name or len(name) < 2:
        return t
    out = t.replace(name, MASK)
    # 概念名常带括号补充，先挖长的再挖短的
    m = re.match(r"^(.+?)[（(]", name)
    if m and len(m.group(1)) >= 2:
        out = out.replace(m.group(1), MASK)
    return out


def leaks(quote: str, concept: str) -> bool:
    """题干/定义句里有没有泄露概念名。"""
    return bool(concept) and len(concept) >= 2 and concept in quote


def build(tag):
    D = load(tag)
    nodes = D["nodes"]
    by_name = {n["n"]: n for n in nodes}

    defs, mentions = {}, {}
    gdef_names = set()      # 定义来自「图谱定义」而不是「教材原话」的概念
    for n in nodes:
        for r in (n.get("rd") or []):
            t = clean_quote(r["t"])
            if is_broken(t):
                continue
            if r.get("def"):
                # 定义句必须**含该概念名**，否则不是它的定义
                if not leaks(t, n["n"]):
                    continue
                # 还要有**定义标志**（叫做/称为/是指…）——
                # 「哪一句是定义」这种题，四个选项都该是定义句才成立。
                if not any(v in t for v in DEF_VERB):
                    continue
                # 定义动词必须在**后半段** —— 动词在前面的句子多半是
                # 「××叫做××」的例句，不是定义句。
                # （「代公民,应当理解每种生物都有存在的价值,保护生物多样性就是保护」
                #  就没有定义动词，属于例句，挖空后不是定义句形态）
                if not is_def_shape(t):
                    continue
                # **这个概念必须就是这句定义的宾语**（定义动词后面紧跟它）
                if not def_anchor(t, n["n"]):
                    continue
                # 挖空后**只能有一个空** —— 挖掉多个说明句子里有别的概念，
                # 那种题填回去也不知道填哪个
                if mask_name(t, n["n"]).count(MASK) != 1:
                    continue
                if n["n"] not in defs:
                    defs[n["n"]] = t
            else:
                if leaks(t, n["n"]):
                    continue
                if n["n"] not in mentions:
                    mentions[n["n"]] = t

    # ── 图谱定义（第二个来源）────────────────────────────────
    # 教材原话层大量句子是**截断的**（OCR 从页面切出来的段落不完整，
    # 实测沪教 732 条定义句被「没以句号收尾」挡掉）。
    # 图谱定义是上游写的完整句，干净得多 —— 但它**不是教材原话**，
    # 所以题目来源必须标「图谱定义」，不能混进「教材定义句」。
    for n in nodes:
        d = n.get("d")
        if not d or n["n"] in defs:
            continue
        c = core_name(n["n"])
        if c not in d or not def_anchor(d, c):
            continue
        if mask_name(d, c).count(MASK) != 1:
            continue
        if is_broken(d):
            continue
        defs[n["n"]] = d
        gdef_names.add(n["n"])

    pool_def = sorted(defs.items())
    pool_men = sorted(mentions.items())
    if len(pool_def) < 8:
        return [], 0, 0, 0

    # 同册次优先的干扰项池
    by_book = collections.defaultdict(list)
    for nm, q in pool_def:
        n = by_name.get(nm)
        if n:
            by_book[(n.get("b"), n.get("s"))].append((nm, q))
    # 去重（同一句话只留一次）
    seen = set()
    for k in list(by_book):
        uniq = []
        for nm, q in by_book[k]:
            if q in seen:
                continue
            seen.add(q)
            uniq.append((nm, q))
        by_book[k] = uniq

    rng = random.Random(20261027)
    out = []
    stats = collections.Counter()

    def distractors(tgt_nm, tgt_q, k=3):
        n = by_name.get(tgt_nm)
        key = (n.get("b"), n.get("s")) if n else None
        cand = list(by_book.get(key, []))
        if len(cand) < k + 1:
            cand = [x for x in pool_def if x[0] != tgt_nm]
        rng.shuffle(cand)
        picked, used = [], set()
        for nm, q in cand:
            if nm == tgt_nm or q == tgt_q or q in used:
                continue
            # 干扰项的定义里不能出现目标概念名
            if leaks(q, tgt_nm):
                continue
            # 目标定义里不能出现干扰项概念名
            if leaks(tgt_q, nm):
                continue
            used.add(q)
            picked.append((nm, q))
            if len(picked) >= k:
                break
        return picked

    # ── 题型 A：定义配对（正→反）──
    for nm, q in pool_def:
        ds = distractors(nm, q, 3)
        if len(ds) < 3:
            stats["A 干扰项不够"] += 1
            continue
        masked_t = mask_name(q, nm)
        opts = [masked_t] + [mask_name(dq, dnm) for dnm, dq in ds]
        if len(set(opts)) != 4:
            stats["A 选项重复"] += 1
            continue
        # 挖空后题干不能泄露（挖空本身不泄露，但要确认没有第二处出现）
        if leaks(masked_t, nm) or any(leaks(o, nm) for o in opts[1:]):
            stats["A 泄露答案"] += 1
            continue
        order = list(range(4))
        rng.shuffle(order)
        letters = "ABCD"
        out.append({
            "id": f"{tag}_a_{len(out)}",
            "type": "choice",
            "edition": tag,
            "concept": nm,
            "grade": by_name.get(nm, {}).get("g"),
            "book": by_name.get(nm, {}).get("b", ""),
            "stem": f"下面哪一句是教材给「{nm}」下的定义？（{MASK} 是教材里被挖掉的部分）",
            "options": [opts[i] for i in order],
            "answer": letters[order.index(0)],
            "explanation": (f"教材原话：「{q}」" if nm not in gdef_names
                            else f"图谱定义：「{q}」"),
            "from": "图谱定义" if nm in gdef_names else "教材定义句",
        })
        stats["A 定义配对"] += 1

    # ── 题型 B：概念配对（反→正）──
    for nm, q in pool_men:
        n = by_name.get(nm)
        if not n:
            continue
        masked_q = mask_name(q, nm)
        key = (n.get("b"), n.get("s"))
        cands = [x["n"] for x in nodes
                 if (x.get("b"), x.get("s")) == key and x["n"] != nm]
        if len(cands) < 3:
            cands = [x["n"] for x in nodes if x.get("s") == n.get("s") and x["n"] != nm]
        rng.shuffle(cands)
        picked = []
        for c in cands:
            if c and len(c) >= 2 and c in masked_q:
                continue
            if c in picked:
                continue
            picked.append(c)
            if len(picked) >= 3:
                break
        if len(picked) < 3:
            stats["B 干扰项不够"] += 1
            continue
        opts = [nm] + picked
        if len(set(opts)) != 4:
            stats["B 选项重复"] += 1
            continue
        order = list(range(4))
        rng.shuffle(order)
        letters = "ABCD"
        out.append({
            "id": f"{tag}_b_{len(out)}",
            "type": "choice",
            "edition": tag,
            "concept": nm,
            "grade": n.get("g"),
            "book": n.get("b", ""),
            "stem": f"教材里有这样一句话：「{masked_q}」——说的是哪个概念？（{MASK} 是教材里被挖掉的部分）",
            "options": [opts[i] for i in order],
            "answer": letters[order.index(0)],
            "explanation": f"这句在教材里说的是「{nm}」。",
            "from": "教材提及句",
        })
        stats["B 概念配对"] += 1

    return out, len(pool_def), len(pool_men), len(pool_def) + len(pool_men)


def main() -> int:
    allq = []
    for tag, label in VERSIONS:
        qs, nd, nm_, _ = build(tag)
        print(f"[{tag}] {label}：可用定义句 {nd} · 提及句 {nm_} → {len(qs)} 道题")
        allq += qs

    OUT.write_text("".join(json.dumps(q, ensure_ascii=False) + "\n" for q in allq), encoding="utf-8")
    print(f"\n{len(allq)} 道题 → {OUT.relative_to(BASE)}")
    for k, v in sorted(collections.Counter((q["edition"], q["from"]) for q in allq).items()):
        print(f"  {k[0]:4s} {k[1]:8s} {v:5d}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
