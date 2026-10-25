#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
知识点「学习卡」—— `data/learn-cards.jsonl`

R-1（docs/需求清单.md）：让人能靠这个图谱**自学**。

现在这个项目是个**图**：能查「谁是谁的前置」「教材第几页有这个概念」。
但它不能回答「我要学这个概念，读什么、做什么题、先补哪个」——
**图能告诉你顺序，不能给你教材**。

这一层做的事：把散在几个平行文件里的内容，按**知识点**组织成一张卡：

    浮力（沪科版·八下 · 第九章）
    ├─ 这是什么   教材原话（原文照抄）+ 图谱定义（转述，标来源）
    ├─ 怎么算     教材原书上的公式（LaTeX）+ 图形语义（标「据图」）
    ├─ 练一练     例题（去重、限量）
    ├─ 先补这些   前置链（与站点「学习路径」面板**逐条同源**）
    └─ 在书里     哪本书 · 哪一节 · 第几页

**为什么不塞进页面 payload**：主站 payload 已经在 2.6 MB 预算边缘，
再加一层内容会爆。而且学习卡是给「一次问一个概念」用的，
不需要整包塞进浏览器。详见需求清单 R-1 的「A/B 两条路」。

## 这一版修掉的四个问题（2026-10-25 实测定位，不是猜的）

1. **前置链跟站点对不上** —— 原来只读 `graph.json` 的上游边（3,703 条），
   而站点用的是**上游边 + 自建边（13,461 条）合并过环检测**的结果。
   结果「浮力」的前置是空的，站点面板上明明有 3 个。
   → 现在直接读**站点已构建好的 payload**（`index.html` 的 `<script id="data">`），
   边表、来源码、教材位置全部同源，**不可能对不上**。

2. **例题一条都召不回来** —— 视觉层的例题字段叫 `stem`，不叫 `text`。
   原来按 `text`/`question` 取，取了 8,590 个空。
   → 改用 `stem`，并按题型排序（练习 > 例题 > 探究 > 讨论 > 思考）。

3. **教材原话答非所问**（「电阻」召回的是「内电阻」「电阻率」「电阻箱」）——
   引文列表里的句子确实带 `definition` 标记，但**定义的对象不是这个概念**。
   → 现在按「定义对象 == 概念名」筛，分三级：
     ① 教材定义句（定义对象就是它）② 教材提及句（它在里面但不是定义）③ 图谱定义。

4. **图/公式噪声** —— 视觉层的图描述带 `tier` 分级：
   `topical` = 这一页在讲这个概念；`broad` = 只有模型转述里提到概念名，
   页面本身跟它没关系。→ `broad` 的一律不要。

**五条纪律**
------------
1. **每一段都带来源标记。** 教材原话是「教材自己说的」，
   图谱定义是「数据集转述的」—— 混起来就是拿二手货冒充一手。
2. **噪声要筛。** 一个概念可能召回 10 条图描述 + 12 道例题，
   先给最相关的 2–3 条，其余不要。
3. **空就说空。** 6.3% 的概念一层内容都没有，
   明确写「这一版没有内容」，不拿相邻概念凑。
4. **不替用户下结论。**「先补这些」只给先修关系链，
   不给「你应该先学 X」—— 那是模型的主观判断。
5. **教材原话只修不补。** 缺字时从原文回溯找回完整句，
   找不到就保持原样并标记残缺，**绝不自己造字**。

跑法：python3 src/build_learn_cards.py
"""
from __future__ import annotations

import collections
import json
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import quote_repair  # noqa: E402  —— 同目录模块

BASE = pathlib.Path("/Users/huangjunhai/Documents/个人/项目/中文知识图谱")
CT_RJB = BASE / "data" / "concept-text.jsonl"        # 人教教材原话
CT_SH = BASE / "data" / "concept-text-sh.jsonl"      # 沪教教材原话
CV_RJB = BASE / "data" / "concept-vision.jsonl"      # 人教公式/图/例题
CV_SH = BASE / "data" / "concept-vision-sh.jsonl"    # 沪教公式/图/例题
SITE_HTML = BASE / "index.html"                      # 站点 payload（前置链同源）
OUT = BASE / "data" / "learn-cards.jsonl"
# 一张卡一行，六个面都在里面。
#
# ⚠️ 试过**分面存储**（每个面一个文件），想省键名的开销 ——
#    实测反而更大（17 MB → 19 MB），而且取用时要 join 六张表。
#    原因：键名开销其实很小（3.9 万次 ≈ 0.3 MB），
#    **体积是内容本身**（教材原话 + 公式 + 例题 + 原文段落）。
#    分面拆开之后，id 和行结构反而多了一份。
#    已入库的 concept-vision-sh.jsonl 20 MB、vision-pages-alt.jsonl 16 MB，
#    量级一样 —— 这层不是新数据，是已有数据的组织形式。

# ── 限量（需求清单「关键约束」第 3 条）────────────────────
MAX_FORMULAS = 6
MAX_FIGURES = 2
MAX_EXERCISES = 5
# ⚠️ **前置链不设限量** —— 需求清单要求它跟站点「学习路径」面板逐条一致，
# 站点那边不截断，这边截了就不一致了
# （实测只有 3 个概念的直接前置超过 8，代价极小）。

# ── 定义句判定 ────────────────────────────────────────────
# 教材下定义的句式。
DEF_CUE = re.compile(r"(叫做|称为|是指|指的是|定义为|全称是|即为|就是)")
# 定理/原理句 —— 也是「教材自己的话」，但不是定义
THM_CUE = re.compile(r"(定理|性质|公式|定律|公理|推论|法则|原理|结论)")
# 题干型 —— 自学时看到的是噪声
#
# ⚠️ 「下列/以下」**不能**单独当题干信号：
# 「含量在0.01%以下的元素，称为微量元素。」里也有「以下」，
# 但它是**定义句**。
# 所以题干信号要带**题目结构**（括号填空 / 选项 / 编号），
# 而不是只看有没有「下列」。
QUESTION_CUE = re.compile(
    r"(说一说|想一想|算一算|连一连|填一填|画一画|看一看|试一试|找一找"
    r"|请回答|请你|你能|为什么|怎样做|如何)")
# 题干的结构特征 —— 比「下列」可靠
QUESTION_STRUCT = re.compile(
    r"(下列.{0,20}[（(][）)]|[（(][）)].{0,10}[A-D][．.、]"
    r"|练习\s*\d|练习[一二三四五六七八九十]|^\s*\d+[．.、]"
    r"|[（(]\s*[）)]|判断下列|下列.{0,8}正确的是)")


def han(s: str) -> str:
    return re.sub(r"[^一-鿿]", "", s)


def core_name(name: str) -> str:
    """概念名去掉括号注释 —— 上游的概念名大量带括号
    （「营养（生物的生活需要营养）」），教材里只写「营养」。"""
    return re.sub(r"[（(][^）)]*[）)]", "", name or "").strip()


def clean_target(t: str) -> str:
    """定义对象：去掉英文注释、修饰词、标点。"""
    t = re.sub(r"[（(〈《].*?[）)〉》]", "", t)
    t = re.split(r"[，,。；;：:、\s]", t)[0]
    return t.strip("的了吧呢")


def defines_this(q: str, core: str) -> bool:
    """这句教材原话**是不是在定义这个概念**（强证据）。

    判据：定义对象（"…叫做X"里的 X）**包含概念名，且概念名在对象里独立成词**。

    ⚠️ 不能用「完全相同」判据 —— 那会把「内电阻」「电阻率」「电阻箱」
    全算成「电阻」的定义（实测沪教有 383 条这种误配）。
    也不能用「只要句式里有叫做就算」——
    「生物的呼吸作用称为…细胞呼吸」会被算成「ATP」的定义。

    「包含」能过真实教材的说法：
    - 「电阻」→ 「导体对电流的阻碍作用叫做电阻」✓
    - 「DNA」→ 「遗传信息以碱基序列的形式储存在DNA分子中」✓（对象更长，概念名在里面）
    - 「内电阻」→ 对象「内电阻」含概念名「电阻」✗（概念名是对象的一部分，不是独立词）

    ⚠️ **对象要在句末标点处截断**：
    "…就是方程的根.揭示这些联系可以加深对一元二次方程的"
    如果不截断，整句后半段都算进"定义对象"，
    「方程的根」在里头但那明显不是定义（实测踩过）。
    """
    if not core:
        return False
    m = re.search(r"(?:叫做|称为|是指|指的是|定义为|全称是|即为|就是)"
                  r"([^，,。；;！？.!?]{2,16})", q)
    if not m:
        return False
    obj = m.group(1)
    # ⚠️ 编号要先剔 ——「就是命题(2)的闭命题」里的「命题(2)」是编号，
    # 不是定义对象（实测踩过）
    obj = re.sub(r"[（(]\s*\d+\s*[）)]", "", obj)
    if core not in obj:
        return False
    # 概念名必须在对象里**独立成词**：
    # 「内电阻」里的「电阻」前面接了「内」→ 不算
    if not mentions_this(obj, core):
        return False
    # **概念名要在对象的头或尾** —— 教材下定义的正常形态：
    # 「X叫做Y」「X是指Y」「X就是Y」里，Y（概念名）在尾部；
    # 「…称为Y」里 Y 也在尾部。
    # 中间出现的（"…就是方程的根.揭示…"）不算。
    return obj.rstrip("的") == core or obj.startswith(core)


def mentions_this(q: str, core: str) -> bool:
    """概念名在句子里**独立成词**地出现过。

    「内电阻」里的「电阻」不算 —— 前后紧接汉字说明是更长词的一部分。
    """
    if not core:
        return False
    for m in re.finditer(re.escape(core), q):
        i, j = m.start(), m.end()
        before = q[i - 1] if i > 0 else ""
        after = q[j] if j < len(q) else ""
        pre_ok = not ("一" <= before <= "鿿") or before in "的之"
        post_ok = not ("一" <= after <= "鿿")
        if pre_ok and post_ok:
            return True
    return False


def is_question(q: str) -> bool:
    """这是不是一道**题干**（而不是教材在讲知识）。

    两个信号：
    1. 题干动词（说一说/想一想/请回答…）
    2. 题目结构（括号填空、ABCD 选项、「练习1.」、编号开头）

    ⚠️ 「下列」「以下」单独出现**不算** ——
    「含量在0.01%以下的元素，称为微量元素。」是定义句，不是题干
    （第一版把「下列」当信号，把这句误杀了）。
    """
    if QUESTION_CUE.search(q):
        return True
    return bool(QUESTION_STRUCT.search(q))


# 图注/标题型引文 —— 「图4-2-6探究平面镜成像特点」「图3.5浓硫酸与铜的反应」
# 这些是图片标题，不是教材对这个概念说的话
RE_FIGCAP = re.compile(r"^\s*(图|表)\s*\d")


def is_figure_caption(q: str) -> bool:
    return bool(RE_FIGCAP.match(q))


def looks_truncated(q: str) -> bool:
    """引文开头是不是被切掉了（残缺）。

    ## 为什么不用「首字 + 标点」这种表面模式

    第一版就是这么写的，实测**准确率只有 50%**：
    - 「机物中的能量释放出来」首字后面接的是汉字 → 漏判
    - 「物理学中，把…」首字后面接逗号 → 误判

    ## 这版：交给原文核对

    残缺 = **这句话在原文里找不到以同样方式开头的完整版**。
    具体做法（`src/quote_repair.py`）：
    用引文的**尾部**（最可靠的部分）去原文的句表里找，
    找到的那句如果更长且**以引文结尾**，说明引文被切过。

    ⚠️ 判据必须是「以引文结尾」，不是「比引文长」——
    否则会拿到另一处**相似但不同**的句子
    （「生态系统」那次就踩过：引文是「…形成的统一整体就是生态系统」，
    原文另有一处「…所形成的统一的整体叫做生态系统」，两者不是同一句）。
    """
    return False


# PDF 文本层的页标记
RE_PAGEMARK = re.compile(r"<<<\s*PAGE\s*\d+\s*>>>|<\s*PAGE\s*\d+\s*>")


def strip_page_marker(q: str) -> str:
    """剔掉 PDF 页标记（<<<PAGE45>>>）。"""
    return RE_PAGEMARK.sub("", q).strip()


# 黏着字 —— 单独出现在句首时，几乎都是词被切开的残留
BROKEN_HEAD_CHARS = "的了着过"


def looks_broken_head(q: str) -> bool:
    """引文开头**仍然是残的**（补全失败后降级用）。

    只认黏着字开头（「的叫做…」「了…」）——
    「物/机/些/面/能」那些补全失败时往往已经在句中，
    不再是句首问题，硬判会误伤好句子。
    """
    s = q.strip()
    if len(s) < 4:
        return False
    if s[0] in BROKEN_HEAD_CHARS and len(s) > 1 and s[1] not in "的了着过":
        # 「的叫做…」「了,」这类
        return True
    return False


def _is_extension_of(old: str, new: str) -> bool:
    """新句是不是旧句的**补全版**（旧句是新句的尾巴）。

    这是替换引文的**唯一门槛**：
    - 旧句必须是新句的结尾（去标点后比）
    - 新句必须比旧句长（真的补上了东西）
    """
    a = han(old)
    b = han(new)
    if not a or not b or len(b) <= len(a):
        return False
    return b.endswith(a[-min(8, len(a)):])


# ── 载入 ──────────────────────────────────────────────────
def load_jsonl(p: pathlib.Path) -> dict:
    if not p.exists():
        return {}
    out = {}
    for line in p.open(encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
        except Exception:
            continue
        if "id" in r:
            out[r["id"]] = r
    return out


def load_site_payload() -> dict:
    """读**站点已构建好的 payload**。

    为什么不用 `graph.json`：站点的前置边表是
    「上游边 + 自建边合并 → 双向边对按来源优先级裁决 → 环检测截断」
    的结果（`src/build_viz.py`），跟 `graph.json` 里的原始边**不是一回事**。
    自己重算一遍 = 迟早跟站点对不上。
    直接读站点产物 = **不可能对不上**。
    """
    if not SITE_HTML.exists():
        raise SystemExit(f"缺 {SITE_HTML} —— 先跑 python3 src/build_viz.py")
    html = SITE_HTML.read_text(encoding="utf-8")
    m = re.search(r'<script id="data"[^>]*>(.*?)</script>', html, re.S)
    if not m:
        raise SystemExit("index.html 里找不到 payload（<script id=\"data\">）")
    return json.loads(m.group(1))


# ── 视觉层：公式 / 图 / 例题 ───────────────────────────────
# 题型优先级：练习和例题最有用，探究/讨论/思考是开放题，
# 自学时先做有标准答案的
EX_TYPE_RANK = {"练习": 0, "例题": 0, "例": 0, "思考": 3, "讨论": 3,
                "探究": 2, "实验": 2, "": 1}


def pick_exercises(r: dict) -> list[str]:
    """从视觉层挑例题。

    ⚠️ 字段叫 `stem`（题干），不叫 `text` —— 原来按 text 取，
    8,590 个概念一条例题都没召回来。
    """
    out = []
    for e in (r.get("exercises") or []):
        if isinstance(e, str):
            t = e.strip()
        elif isinstance(e, dict):
            t = (e.get("stem") or e.get("text") or e.get("question") or "").strip()
        else:
            continue
        if not t or len(t) < 8:
            continue
        out.append(t)
    return out


def ex_rank(text: str) -> tuple:
    """例题排序：先按题型，再按长度（短的先给）。"""
    t = text[:6]
    kind = 1
    for k, v in EX_TYPE_RANK.items():
        if k and t.startswith(k):
            kind = v
            break
    return (kind, len(text))


def pick_figures(r: dict, key: str, ver: str) -> list[dict]:
    """挑图形描述。

    ⚠️ **只取 `tier == "topical"`** ——
    `broad` 的意思是「只有模型转述里提到了概念名，页面本身跟它没关系」
    （模型写图形描述时会提到页面上任何名词，包括偶然出现的「正五边形的顶点」）。

    ⚠️ **每一段都必须带 source** —— 混进一行没出处的文字，
    读者会当成教材原话（需求清单「关键约束」第 1 条）。
    """
    out = []
    for g in (r.get(key) or []):
        if not isinstance(g, dict):
            if isinstance(g, str) and g.strip():
                out.append({"caption": "", "text": g.strip()[:200],
                            "source": f"教材原书上的图（据图，{ver}）"})
            continue
        if g.get("tier") and g["tier"] != "topical":
            continue
        desc = (g.get("description") or "").strip()
        cap = (g.get("caption") or "").strip()
        if not desc:
            continue
        # 「封面」不是教学内容
        if cap in ("封面", "无") and len(desc) > 80:
            continue
        out.append({"caption": cap, "text": desc[:220],
                    "source": f"教材原书上的图（据图，{ver}）",
                    "tier": g.get("tier") or "topical"})
    return out


def pick_formulas(r: dict, key: str) -> list[str]:
    out = []
    for f in (r.get(key) or []):
        if isinstance(f, str) and f.strip():
            out.append(f.strip())
        elif isinstance(f, dict):
            t = (f.get("latex") or f.get("text") or "").strip()
            if t:
                out.append(t)
    return out


# ── 主流程 ────────────────────────────────────────────────
def main() -> int:
    for p in (CT_RJB, CV_RJB, SITE_HTML):
        if not p.exists():
            print(f"缺 {p}")
            return 1

    payload = load_site_payload()
    pnodes = payload["nodes"]           # [i, zh, en, subj, dz, id, a1, a2, cen, core, desc, evn, chp, chn, unit]
    pedges = payload["edges"]           # [后继下标, 先修下标, 来源码, 可疑码]
    ptext = payload.get("text") or {}
    pvision = payload.get("vision") or {}
    paltvision = payload.get("visionAlt") or {}
    pcns = payload.get("cns") or []
    srczh = payload.get("srczh") or ["上游", "模型重建", "能力底座", "自建概念",
                                     "教材引入路径", "已修正", "教材结构图"]

    # 下标 → 节点
    by_idx = {n[0]: n for n in pnodes}
    idx_of_id = {n[5]: n[0] for n in pnodes}

    # 前置邻接：**后继 → [(先修下标, 来源码)]**
    # 方向跟站点模板一致（KG.pre 的键是后继）
    pre = collections.defaultdict(list)
    for to, fr, src, sus in pedges:
        pre[to].append((fr, src))

    ct = load_jsonl(CT_RJB)
    ctsh = load_jsonl(CT_SH)
    cv = load_jsonl(CV_RJB)
    cvsh = load_jsonl(CV_SH)

    # 引文修复用的原文（人教有文本层，沪教是页图 OCR 修不了）
    repair_all = quote_repair.build_book_sentences()
    book_sents = {k: v for k, v in repair_all.items() if len(k) == 2}
    # 原文也按 (subject, book) 存 —— 查询时要用同一个 key
    book_raw = {k[:2]: v for k, v in repair_all.items() if len(k) == 3}

    # 页原文段落（概念 → 教材原页上的那一段）
    page_by_concept = {}
    PIDX = BASE / "data" / "page-index.json"
    if PIDX.exists():
        pj = json.load(open(PIDX, encoding="utf-8"))
        page_by_concept = pj.get("_byConcept") or {}
    else:
        print("！缺 data/page-index.json —— 「教材原文段落」这一面会是空的"
              "（先跑 python3 src/build_page_index.py）")

    cards = []
    stat = collections.Counter()
    for node in pnodes:
        i, zh, en, subj, dz, cid = node[0], node[1], node[2], node[3], node[4], node[5]
        # **只给上游知识点做卡** —— 自建的「能力底座」不是教材知识点
        if not cid.startswith(("math_", "physics_", "chemistry_", "biology_")):
            continue
        core = core_name(zh)

        card = {
            "id": cid, "name": zh,
            "subjectZh": node[4].split("·")[0] if dz else "",
            "bookZh": (node[4].split("·")[0] if dz else ""),
            "label": dz,
        }
        # 教材位置（从 payload 的 cns 取单元）
        unit_idx = node[14] if len(node) > 14 else -1
        unit = pcns[unit_idx] if 0 <= unit_idx < len(pcns) else None

        # ── ① 这是什么 ─────────────────────────────────────
        # **三级证据强度**（不是「教材原话 / 图谱定义」二分）：
        #
        #   ① 教材定义句  —— 教材自己在给这个概念下定义（证据最强）
        #   ② 教材提及句  —— 教材里提到了它，且句子本身是陈述句（不是题干）
        #   ③ 图谱定义    —— 数据集里的转述（证据最弱，但覆盖最全）
        #
        # 为什么不能只认①：上游概念名大量是**改写过的**
        # （「ATP（能量储存形式）」「DNA（遗传信息载体）」），
        # 教材里根本不这么写 —— ①只覆盖 10~13%。
        # 但也不能把②当定义用：「电阻」的提及句可能是「内电阻」那句。
        what = []
        for rows, ver in ((ct, "人教版"), (ctsh, "沪教版")):
            r = rows.get(cid)
            if not r:
                continue
            quotes = r.get("quotes") or []
            kinds = r.get("quoteKinds") or []
            defs, mentions = [], []
            for q, k in zip(quotes, kinds):
                if not q or not q.strip():
                    continue
                q = q.strip()
                if is_question(q) or is_figure_caption(q):
                    continue
                # **残缺句回原文补全**（人教有文本层能补；沪教是 OCR 补不了）
                #
                # 判据不是猜的，是**回原文核对**：
                # 用引文的尾部（最可靠的部分）去原文句表里找，
                # 找到的句如果更长且**以引文结尾** → 引文被切过，
                # 那句就是完整版。
                # ⚠️ 必须验「以引文结尾」——
                # 否则会拿到另一处**相似但不同**的句子（「生态系统」那次就踩过：
                # 引文是「…形成的统一整体就是生态系统」，
                # 原文另有一处「…所形成的统一的整体叫做生态系统」，
                # 两者不是同一句，不能替换）。
                key = (r.get("subject"), r.get("book"))
                ss = book_sents.get(key)
                raw = book_raw.get(key)
                if ss:
                    fixed = quote_repair.repair_quote(q, ss, raw)
                    if fixed and _is_extension_of(q, fixed):
                        q = fixed
                        stat["引文已补全"] += 1
                # PDF 文本层里的页标记（<<<PAGE45>>>）要剔掉
                q = strip_page_marker(q)
                # **补全后再判一次题干** ——
                # 原文里的一句「…不正确的是：（）A.…」补全后可能带上了
                # 「练习1.」这样的编号前缀（实测踩过：
                # 「生物种类的多样性」补全后变成 "练习1.下列有关生物多样性的叙述中…"，
                # 那是一道题，不是教材的定义）。
                if is_question(q) or is_figure_caption(q):
                    stat["补全后变题干（丢弃）"] += 1
                    continue
                # 补不上、开头还是残的 → 不当定义句用，降级成提及句
                if looks_broken_head(q):
                    stat["引文仍残缺（降级）"] += 1
                    if mentions_this(q, core) and len(han(q)) >= 8:
                        mentions.append({"text": q, "kind": "教材提及句",
                                         "evidence": "教材提到了这个概念（这句开头残缺）"})
                    continue
                if defines_this(q, core):
                    defs.append({"text": q, "kind": "教材定义句",
                                 "evidence": "教材给这个概念下了定义"})
                elif mentions_this(q, core) and len(han(q)) >= 8:
                    mentions.append({"text": q, "kind": "教材提及句",
                                     "evidence": "教材提到了这个概念（不是定义句）"})
            for d in defs[:2]:
                d = dict(d)
                d["source"] = f"教材原话·{ver}"
                d["edition"] = ver
                what.append(d)
            if not defs:
                for d in mentions[:1]:
                    d = dict(d)
                    d["source"] = f"教材原话·{ver}"
                    d["edition"] = ver
                    what.append(d)
        # 图谱定义（转述，来源必须标出来）
        desc = (node[10] or "") if len(node) > 10 else ""
        if desc.startswith("图谱定义："):
            desc = desc[len("图谱定义："):]
        if desc.strip():
            what.append({"text": desc.strip()[:300], "kind": "图谱定义",
                         "source": "图谱定义",
                         "edition": "上游 K12-KGraph"})
        card["what"] = what
        if any(w["kind"] == "教材定义句" for w in what):
            stat["有教材定义句"] += 1
        elif any(w["kind"] == "教材提及句" for w in what):
            stat["只有教材提及句"] += 1
        if any(w["source"] == "图谱定义" for w in what):
            stat["有图谱定义"] += 1
        if not what:
            stat["一层都没有"] += 1

        # ── ② 怎么算 ───────────────────────────────────────
        formulas, figures = [], []
        for rows, ver, fk, gk in ((cv, "人教版", "formulas", "figureDescriptions"),
                                  (cvsh, "沪教版", "altFormulas", "altFigures")):
            r = rows.get(cid)
            if not r:
                continue
            fs = pick_formulas(r, fk)
            gs = pick_figures(r, gk, ver)
            if ver == "人教版":
                formulas += fs
                figures += gs
            else:
                formulas += [{"text": f, "source": f"教材原书上的公式（{ver}）"} for f in fs]
                figures += gs
        # 站点 payload 里的视觉层（已转成纯文本）——优先，因为它更干净
        pv = pvision.get(str(i))
        if isinstance(pv, list) and pv:
            for f in (pv[0] or []):
                if isinstance(f, str) and f.strip():
                    formulas.append({"text": f.strip(), "source": "教材原书上的公式"})
            for g in (pv[1] or []):
                if isinstance(g, list) and len(g) >= 2 and g[1]:
                    cap = (g[0] or "") if len(g) > 1 else ""
                    desc2 = (g[1] or "")
                    if cap in ("封面",):
                        continue
                    figures.append({"caption": cap, "text": desc2[:220],
                                    "source": "教材原书上的图（据图）",
                                    "tier": "topical"})
        pva = paltvision.get(str(i))
        if isinstance(pva, list) and pva:
            for f in (pva[0] or []):
                if isinstance(f, str) and f.strip():
                    formulas.append({"text": f.strip(),
                                     "source": "教材原书上的公式（沪教版）"})
        # 去重
        seen = set()
        fs2 = []
        for f in formulas:
            txt = f["text"] if isinstance(f, dict) else f
            k = re.sub(r"\s+", "", txt)
            if k in seen:
                continue
            seen.add(k)
            fs2.append(f if isinstance(f, dict)
                       else {"text": txt, "source": "教材原书上的公式"})
        seen = set()
        gs2 = []
        for g in figures:
            k = re.sub(r"\s+", "", g["text"])[:60]
            if k in seen:
                continue
            seen.add(k)
            gs2.append(g)
        card["how"] = {
            "formulas": fs2[:MAX_FORMULAS],
            "figures": gs2[:MAX_FIGURES],
        }
        if card["how"]["formulas"] or card["how"]["figures"]:
            stat["有怎么算"] += 1

        # ── ③ 练一练 ───────────────────────────────────────
        ex = []
        for rows, ver in ((cv, "人教版"), (cvsh, "沪教版")):
            r = rows.get(cid)
            if not r:
                continue
            for t in pick_exercises(r):
                ex.append({"text": t[:300], "source": f"教材例题·{ver}"})
        ex.sort(key=lambda x: ex_rank(x["text"]))
        seen = set()
        ex2 = []
        for e in ex:
            k = re.sub(r"\s+", "", e["text"])[:60]
            if k in seen:
                continue
            seen.add(k)
            ex2.append(e)
        card["practice"] = ex2[:MAX_EXERCISES]
        if card["practice"]:
            stat["有练一练"] += 1

        # ── ④ 先补这些 ─────────────────────────────────────
        # **跟站点「学习路径」面板同源**：同一份边表（payload.edges），
        # 同样的方向（后继 → 先修）。
        # 不给「你应该先学 X」—— 那是主观判断（需求清单「关键约束」第 4 条）。
        ps = []
        for (fr, src) in pre.get(i, []):
            fn = by_idx.get(fr)
            if not fn:
                continue
            ps.append({
                "id": fn[5], "name": fn[1],
                "bookZh": fn[4].split("·")[0] if fn[4] else "",
                "grade": fn[6],
                "src": srczh[src] if src < len(srczh) else "上游",
            })
        ps.sort(key=lambda x: (x["grade"] if isinstance(x["grade"], int) else 99,
                               x["name"]))
        # ⚠️ **不截断** —— 需求清单要求「先补这些」跟站点「学习路径」面板
        # **逐条一致**，站点那边是不截的。
        # 截了就不一致了（实测 3 个概念的直接前置 > 8，被切掉 6 个）。
        card["prereq"] = ps
        if card["prereq"]:
            stat["有先补"] += 1

        # ── ⑤ 在书里 ───────────────────────────────────────
        # 三部分：
        #   ① 教材位置（哪本书 · 哪一章 · 第几页）
        #   ② 教材单元（按人教版册次，来自 payload 的 cns）
        #   ③ **教材原文段落** —— 这一页上真的印着的话
        where = []
        for rows, ver in ((ct, "人教版"), (ctsh, "沪教版")):
            r = rows.get(cid)
            if not r:
                continue
            pages = [p for p in (r.get("pages") or []) if isinstance(p, int)]
            if pages:
                where.append({"edition": ver,
                              "bookZh": r.get("bookZh") or "",
                              "chapter": r.get("chapter") or "",
                              "pages": pages[:12]})
        if unit:
            where.insert(0, {"edition": "人教版",
                             "bookZh": unit[1] if len(unit) > 1 else "",
                             "chapter": unit[0] if unit else "",
                             "unit": unit[0], "pages": [],
                             "note": "教材单元（按人教版册次）"})
        card["where"] = where
        if where:
            stat["有在书里"] += 1

        # ── ⑥ 教材原文段落（页原文召回）────────────────────
        # `data/page-index.json` 用**引文反查**定位到页
        # （不靠页码换算 —— 扫描页码和印刷页码不是一套，差多少每册都不同）。
        # ⚠️ 段落是**教材原页上的字**，但 OCR 层有残骸，
        #    建索引时已经按汉字密度筛过（`quality_ok`）。
        texts = []
        for x in (page_by_concept.get(cid) or []):
            texts.append({"book": x.get("book") or "",
                          "page": x.get("page"),
                          "pageId": x.get("pageId") or "",
                          "text": (x.get("text") or "")[:600],
                          "source": "教材原页文字"})
        card["read"] = texts[:3]
        if texts:
            stat["有教材原文段落"] += 1

        # 覆盖标记
        layers = []
        if any(w["kind"] == "教材定义句" for w in what):
            layers.append("教材定义句")
        if any(w["kind"] == "教材提及句" for w in what):
            layers.append("教材提及句")
        if any(w["source"] == "图谱定义" for w in what):
            layers.append("图谱定义")
        if card["how"]["formulas"] or card["how"]["figures"]:
            layers.append("教材原书公式图")
        if card["practice"]:
            layers.append("教材例题")
        if card.get("read"):
            layers.append("教材原页文字")
        card["layers"] = layers
        if not layers:
            # **空要说空**（需求清单「关键约束」第 5 条）：
            # 明确写「这一版没有内容」，不能拿相邻概念的内容凑，
            # 也不能让调用方以为这是"查到了但没显示"。
            card["emptyNote"] = "这一版没有这个概念的内容。" \
                               "教材原话、公式、例题三层都没召回 —— " \
                               "不拿相邻概念的内容凑。"
            card["what"] = []
            card["how"] = {"formulas": [], "figures": []}
            card["practice"] = []
            card["read"] = []
        cards.append(card)

    cards.sort(key=lambda c: (c["bookZh"], c["name"]))
    OUT.write_text("".join(json.dumps(c, ensure_ascii=False) + "\n" for c in cards),
                   encoding="utf-8")

    n = len(cards)
    print(f"学习卡 {n:,} 条 → {OUT}  ({OUT.stat().st_size/1024/1024:.1f} MB)")
    print("\n各面覆盖：")
    for k, v in stat.most_common():
        print(f"  {k}: {v:,}  ({v/n*100:.1f}%)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
