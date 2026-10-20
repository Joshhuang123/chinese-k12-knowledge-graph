#!/usr/bin/env python3
"""
教材顺序推导：知识点 → 它在教材序列里的位置。

为什么单独抽一个模块：
  build_viz.py 和 sweep_math.py 都需要「这个知识点在第几单元」。
  第一版两边各写一份，结果 sweep 算出「11.7% 能定位」，
  build_viz 算出「100% 能定位」—— 因为 sweep 只按节点 id 里的
  _chNN 正则找位置，而 concept 节点的 id 是 math_1a_rjb_cpt1，
  正则根本匹配不上，必须走 appears_in 上溯到 Chapter/Section。
  两份实现各错各的，比一份实现错更难查。
  册序表已经在 books.py 上吃过同样的亏（字母序 vs 册序），不再来第二次。

数据来源: K12-KGraph (arXiv:2605.09635) · PKU-DCAI · CC BY-NC-SA 4.0
"""
import pathlib
import re
import sys
from collections import Counter, defaultdict

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import books

RANK = books.RANK


def seq_key_of(nid):
    """math_5a_rjb_ch12_s03 → (12, 3)；只有 ch 的 → (12, 0)；没有 → None。

    609 个 Section 全带 _chNN_sMM，264 个 Chapter 带 _chNN，
    完整教学顺序就写在 id 里，不依赖任何外部数据源。
    """
    m = re.search(r"_ch(\d+)(?:_s(\d+))?$", nid)
    if not m:
        return None
    return int(m.group(1)), int(m.group(2) or 0)


class Order:
    """一次构建，反复查询。nodes/edges 就是 graph.json 的两个数组。

    clickable：算「这个单元里第一个可点的概念」时只看这些节点。
        可视化只导出 Concept/Skill，习题节点不在 payload 里 —— 第一版
        没过滤，「第四节 实验活动4」里第一个出现的恰好是道习题，
        于是这个单元的锚点被吃掉，卡片上「下一单元」按钮点了没反应。
    """

    def __init__(self, nodes, edges, clickable=None):
        self.node_of = {n["id"]: n for n in nodes}
        self.clickable = clickable

        # ── 章归属：Section --is_part_of--> Chapter ──
        chapter_of = {}
        for e in edges:
            if e["type"] == "is_part_of" and \
               self.node_of.get(e["from"], {}).get("label") == "Section":
                chapter_of[e["from"]] = e["to"]

        # ── 知识点出现在哪个容器 ──
        # appears_in 有两种指向，差别只在一个 label 上：
        #   初中/高中 → Section（8,125 条），再 is_part_of 上溯到 Chapter；
        #   **小学 → 直接指 Chapter（819 条）**。
        # 第一版只认前者，于是 782 个小学知识点里 742 个拿不到教材顺序。
        self.chapter_of_node = defaultdict(list)
        appears_of = defaultdict(list)
        for e in edges:
            if e["type"] != "appears_in":
                continue
            tgt = self.node_of.get(e["to"], {})
            if tgt.get("label") == "Section":
                ch = chapter_of.get(e["to"])
                if ch:
                    self.chapter_of_node[e["from"]].append(ch)
                appears_of[e["to"]].append(e["from"])
            elif tgt.get("label") == "Chapter":
                self.chapter_of_node[e["from"]].append(e["to"])
                appears_of[e["to"]].append(e["from"])
        self.appears_of = appears_of
        # 容器 → 它所属的 Chapter（小学直接指 Chapter，自己就是自己）
        self.chapter_of_container = {}
        for cid in list(appears_of) + list(chapter_of.keys()):
            if self.node_of.get(cid, {}).get("label") == "Chapter":
                self.chapter_of_container[cid] = cid
            elif cid in chapter_of:
                self.chapter_of_container[cid] = chapter_of[cid]
            else:
                self.chapter_of_container[cid] = cid

        # ── 章级 leads_to（只收 Chapter→Chapter，混进节/册全是噪音）──
        self.chap_pre, self.chap_next = defaultdict(list), defaultdict(list)
        for e in edges:
            if e["type"] != "leads_to":
                continue
            if self.node_of.get(e["from"], {}).get("label") != "Chapter" or \
               self.node_of.get(e["to"], {}).get("label") != "Chapter":
                continue
            self.chap_pre[e["to"]].append(e)
            self.chap_next[e["from"]].append(e)

        # ── 全局教材序列：每学科 (册序, ch, s) 排成一条 ──
        by_subject = defaultdict(list)
        for n in nodes:
            if n["label"] not in ("Section", "Chapter"):
                continue
            k = seq_key_of(n["id"])
            if k:
                by_subject[n["subject"]].append((RANK[n["book"]], k[0], k[1], n["id"]))
        for v in by_subject.values():
            v.sort(key=lambda x: (x[0], x[1], x[2]))

        self.units = []            # [(unit_id, subject, bookZh, name, pos, total)]
        cn_pos = {}
        for sub, rows in by_subject.items():
            for pos, (_r, _ch, _s, cid) in enumerate(rows):
                c = self.node_of[cid]
                cn_pos[cid] = (len(self.units), pos, len(rows), sub)
                self.units.append((cid, sub, c["bookZh"], c["name"], pos, len(rows)))

        # 每个容器记住「里面第一个可点的概念」——按 cn_pos 自然顺序扫，
        # 命中的第一个就是教材顺序最靠前的那个。
        self.first_concept = {}
        for cid in cn_pos:
            for nid in appears_of.get(cid, ()):
                if cid in self.first_concept:
                    break
                if clickable is not None and nid not in clickable:
                    continue
                self.first_concept[cid] = nid

        # 概念 → 所属容器。一个概念可能在多个容器里，取全局最靠前的，
        # 保证同一个概念在页面上位置唯一且稳定。
        self.container_of = defaultdict(list)
        for cid in cn_pos:
            for nid in appears_of.get(cid, ()):
                self.container_of[nid].append(cid)
        for v in self.container_of.values():
            v.sort(key=lambda c: cn_pos[c][0])
        self.cn_pos = cn_pos

    def seq_slot(self, nid):
        """它属于教材序列里的第几个单元（全局下标），-1 = 定不出。

        优先挑**有可点概念**的那个容器，不是编号最小的那个。
        初中/高中概念挂在 Section 上，Chapter 层自己一个概念都没有 ——
        按编号最小挑的话，每个知识点都会落在那个点不动的章上，
        「下一单元」按钮点了没反应。

        **同一个概念可能在好几个容器里出现**（跨章回顾、习题引用…）。
        原来在这些容器里直接取**最早**的那个，但「最早」常常只是
        「被提一句」而不是「被教」：

            光合作用[七上] 出现在 第一章 认识生物（提一句）、
                          第四章 绿色植物是生物圈中有机物的制造者（真正教）、
                          第五章 绿色植物与生物圈中的碳-氧平衡（回顾）
            取最早就落到了第一章 —— 教材顺序、上一/下一单元导航、
            册序倒挂检测，全都跟着错。

        改成两条规则：
        ① **先只看节点自己那本册里的容器**。
           「催化剂[九上]」在九上有个容器（课题3 制取氧气），
           另有两个在必修二（回顾）。不先按册筛，它会被挪到必修二去 ——
           而催化剂确实是九上教的。跨册的容器是**回顾/引用**，
           跨学科的更是不同教材的同名概念。
        ② 同一册内再按**所属 Chapter 归组**，取出现次数最多的那个 Chapter
           —— 那才是它「住在」的章，再在该 Chapter 内取最早的容器。
        全库 48 个知识点因此换了位置，同册倒挂里的 10 条假信号被消掉。
        """
        cs = self.container_of.get(nid) or []
        if not cs:
            return -1
        withconcept = [c for c in cs if c in self.first_concept]
        pool = withconcept or cs
        # ① 先按节点自己那本册筛
        own = self.node_of.get(nid, {}).get("book")
        if own:
            inown = [c for c in pool
                     if self.node_of.get(c, {}).get("book") == own]
            if inown:
                pool = inown
        # ② 同一册内按 Chapter 归组，取最多的那个
        grp = Counter(self.chapter_of_container.get(c, c) for c in pool)
        top = max(grp.values())
        cands = [c for c in pool if grp[self.chapter_of_container.get(c, c)] == top]
        return self.cn_pos[min(cands, key=lambda c: self.cn_pos[c][0])][0]

    def seq_pos(self, nid):
        """(学科内位次, 该学科单元总数)，定不出时 (None, total)。"""
        slot = self.seq_slot(nid)
        if slot < 0:
            sub = self.node_of[nid]["subject"]
            total = sum(1 for u in self.units if u[1] == sub)
            return None, total
        uid = self.units[slot][0]
        _gi, pos, total, _sub = self.cn_pos[uid]
        return pos, total

    def book_order(self, nid):
        """→ (leads_to 标为前置的章, leads_to 指向的后续章)，Chapter 节点 id 列表。

        必须用 chapter_of_node 上溯到 Chapter，不能用 container_of ——
        后者对初中/高中给的是 Section，而 chap_pre 是按 Chapter 建的键，
        直接拿 Section 去查会一个都查不到（第一版就这么写的，
        7,510 掉到 569，全库 95% 的知识点凭空丢掉前置章）。
        """
        chs = self.chapter_of_node.get(nid) or []
        if not chs:
            return [], []
        ch = chs[0]
        return ([e["from"] for e in self.chap_pre.get(ch, ())],
                [e["to"] for e in self.chap_next.get(ch, ())])
