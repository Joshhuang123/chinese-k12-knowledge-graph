#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
判据：**这个概念上海教材教不教？**

背景
----
上海站叫「上海的孩子学什么」，但先修闭包会把上游人教版图谱的概念拉进来
（实测 975 个，占 3,393 个节点的 28.8%），其中 549 个是高中概念
（ATP、DNA 双螺旋、σ键、sp²杂化轨道…）——
**这些在沪教版教材里根本不存在**。

后果不是「多了几个点」：
  · 搜「ATP」同时出现「ATP（腺苷三磷酸）沪科版·必修一」和
    「ATP水解供能 人教版·必修一」—— 同一个知识点被拆成两个节点
  · 学习路径面板里「单项式的次数 · 人教版·七上」跟「沪教版·六上」并排，
    用户分不出哪个是上海教材
  · 73 条边年级倒挂：八年级学「中枢神经系统」要求先会高一的「脑」

判据怎么定的
------------
三个候选都比过（`src/align_edition_probe.py` 可复现）：

  A. 概念名在沪教教材原文（9,009 页 OCR）里出现过
  B. 概念名等于某个沪教教材的节名或章名
  C. A + 册次约束

  B 只命中 6/975 —— 教材的节名往往是知识点集合
  （「B、T淋巴细胞参与特异性免疫应答」），不是单个概念名。太严，会误杀真前置。

  所以用 **A，但加两道约束**：
  ① **同学科**：只在**同学科**的沪教教材里找。
     「传热」「质量守恒」这类跨学科词不该让物理概念靠生物书命中。
     实测：加学科约束后 362 → 347，跨学科误命中只剩 15 个。
  ② **名称变体**：去掉括号补充说明（「B淋巴细胞（B细胞）」→「B淋巴细胞」）、
     去掉末尾数字且主体 ≥4 字（「不等式的性质1」→「不等式的性质」）。
     长度门槛是必须的 —— 「单位1」→「单位」是误救。

  变体为什么必要：沪教版可能用**另一个名字**教同一个概念。
  「B细胞」沪教版不这么叫，它叫「B淋巴细胞」——
  靠变体才认得出这是同一个概念。

实测结果
--------
975 个人教版前置节点 → 保留 314（沪教真的教）· 剔除 661（沪教不教）。
抽样核对：剔除的确实是人教版独有概念
（σ键、sp²杂化轨道、α粒子散射实验、下丘脑—垂体—甲状腺轴…）。

⚠️ 这个判据**只判「教不教」，不判「是不是同一个概念」**。
  同一个概念在两套教材里叫不同名字时，判据靠名称变体兜；
  兜不住的情况（沪教用了完全不同的说法）会漏 —— 那时宁可少留，
  也不要把人教版内容冒充成上海教材。
"""
import collections
import json
import pathlib
import re

BASE = pathlib.Path(__file__).resolve().parent.parent
LESSONS_SH = BASE / "data" / "lessons-sh.jsonl"

# 图谱的英文学科 → 教材的中文学科
SUBJ_ZH = {
    "math": "数学", "physics": "物理", "chemistry": "化学",
    "biology": "生物", "science": "科学",
}


def strip_paren(s: str) -> str:
    """去掉括号里的补充说明：「ATP（腺苷三磷酸）」→「ATP」"""
    return re.sub(r"[（(].*?[）)]", "", s).strip()


def name_variants(nm: str) -> set:
    """概念名的各种写法。

    ⚠️ 去末尾数字有**长度门槛**（主体 ≥4 字）——
    不加门槛的话「单位1」会退化成「单位」，
    「单位」在沪教教材里到处都是 → 误救。
    """
    out = {nm}
    core = strip_paren(nm)
    if core:
        out.add(core)
    for base in (nm, core):
        v = re.sub(r"[0-9０-９]+$", "", base).strip()
        if len(v) >= 4:
            out.add(v)
    return {v for v in out if len(v) >= 2}


def book_subject(book_id: str) -> str:
    """book id 形如 `sh-hk-数学-s-7a` → 「数学」"""
    parts = (book_id or "").split("-")
    return parts[2] if len(parts) > 2 else ""


class ShanghaiCorpus:
    """沪教教材全文，按学科分桶。"""

    def __init__(self):
        self.by_subject = collections.defaultdict(str)
        self.books = 0
        self.pages = 0
        if not LESSONS_SH.exists():
            return
        for line in LESSONS_SH.open(encoding="utf-8"):
            if not line.strip():
                continue
            d = json.loads(line)
            bid = d.get("book", "")
            txt = d.get("text", "")
            self.by_subject[book_subject(bid)] += txt
            self.books += 1
            self.pages += 1

    def teaches(self, subject_en: str, name: str) -> bool:
        """这个概念在本学科的沪教教材里出现过没有？"""
        subj = SUBJ_ZH.get(subject_en or "", "")
        corpus = self.by_subject.get(subj)
        if not corpus:
            return False
        for v in name_variants(name):
            if v in corpus:
                return True
        return False


_CACHE = {}


def get_corpus() -> ShanghaiCorpus:
    if "c" not in _CACHE:
        _CACHE["c"] = ShanghaiCorpus()
    return _CACHE["c"]


def taught_in_shanghai(subject_en: str, name: str) -> bool:
    return get_corpus().teaches(subject_en, name)


if __name__ == "__main__":
    c = get_corpus()
    print(f"沪教教材 {c.books} 页载入，按学科分 {len(c.by_subject)} 桶")
    for s, t in sorted(c.by_subject.items(), key=lambda kv: -len(kv[1])):
        print(f"  {s or '(空)':6s} {len(t):>9d} 字")
    for nm, subj in [("B细胞", "biology"), ("DNA双螺旋结构", "biology"),
                     ("不等式的性质1", "math"), ("单位1", "math"),
                     ("σ键", "chemistry"), ("三角形的顶点", "math")]:
        print(f"  {nm:16s} ({subj:9s}) 沪教教? {taught_in_shanghai(subj, nm)}")
