#!/usr/bin/env python3
"""
拿教材正文核对上游写给每个知识点的 definition，找出三种情况。

为什么要写这个：
  1,367 个 Concept/Skill 没有 definition，6,571 个有 —— 但「有」不等于「对」。
  ISSUE-07/09 已经两次栽在同一个毛病上：上游的 evidence 字段
  只是正文里恰好出现的一句话，不是「这条边/这个定义为什么成立」的说明。
  现在教材正文在手，能做第一次真正的对撞。

三种发现：
  MISMATCH   上游的定义和教材说的不是一回事        → 定义要重写
  THIN       上游的定义太短或太空，抓不住这个概念  → 定义要重写
  MISSING    上游没写，教材有                       → 补定义

两个坑，都踩过：
  1. 中文 PDF 里全是**全角数字**（１２３）和全角标点，不做 NFKC 归一化
     的话「１．２．３相反数」跟「1.2.3 相反数」永远匹配不上。
  2. **找到关键词 ≠ 找到定义。**「相反数」在一册书里出现几十次，
     大半是习题。取第一处会拿到「在数轴上，与原点的距离是 2 的点有几个？」
     这种纯题目文本。所以要挑「像定义」的段落：含「是指」「叫做」
     「定义为」「即」「表示」这类判断词，或以概念名开头。

跑法：
    python3 src/check_definitions.py              # 全部已就绪的册
    python3 src/check_definitions.py --books 7a,9a
"""
import argparse
import json
import pathlib
import re
import sys
import unicodedata
from collections import Counter, defaultdict

BASE = pathlib.Path(__file__).resolve().parent.parent
CACHE = BASE / "data" / "pdf-cache"
GRAPH = BASE / "data" / "normalized" / "graph.json"
OUT = BASE / "data" / "normalized" / "def-check.json"

# 判断词：出现这些词的句子才像在定义一个概念
DEFINER = re.compile(r"(是指|叫做|定义为|称为|即为|表示|意味着|指的是|统称|合称)")
# 像题目的句子 → 扣分。**只认「句子的形状」，不认「有没有这些字」。**
# 第一版写了「求|计算|证明」就算题目，结果
#   「把 3,4,5 叫做等腰三角形，求它的周长」
# 这种半定义半题目的句子被扣到 0 分扔掉，2140/2269 判成「教材里找不到」。
# 「求」「计算」「证明」在数学定义句里太常见了，不能当习题标志。
QUESTION = re.compile(r"(?:[？?]$|^例\s*[0-9１-９]|^[练习习题]|^\d+[.、]|下列|如图所示的?[时候]*求)")

FILES = {"7a": "7a", "7b": "7b", "8a": "8a", "8b": "8b", "9a": "9a", "9b": "9b",
         "bx1": "m1", "bx2": "m2", "xzxbx1": "x1", "xzxbx2": "x2", "xzxbx3": "x3"}


def norm(t):
    """全角→半角，空白压掉。中文 PDF 大量使用全角数字和标点。"""
    t = unicodedata.normalize("NFKC", t or "")
    return re.sub(r"\s+", "", t)


# 目录行：「1.3 有理数的加减法 16」——标题 + 尾巴一个页码。
# 目录排在正文**前面**，不剔掉的话它会把候选槽占满，
# 脚本翻到后面的正文就找不到了 —— 「有理数」在正文里写着
# 「整数和分数统称为有理数」，却被目录里的「1.3 有理数的加减法 16」挤掉。
TOC_LINE = re.compile(r"^[0-9．.\s]{0,12}[^。，]{2,24}[0-9]{1,3}$")


def drop_toc(text):
    """去掉目录页。

    这套人教 PDF 的文本层里**没有「目录」标题**（`re.finditer(r'目\s*录')` 零命中），
    目录是一段「标题 + 全角页码」的连续行，而且**不全是数字开头**：
        １．３ 有理数的加减法      １６
        实验与探究 无限循环小数化分数      ９２
        数学活动      １０９
        第四章 几何图形初步
    靠「以数字开头」筛会漏掉后三类、导致 run 计数断掉（实测在「实验与探究」处断）。

    改用**锚点法**：正文第一行长这样 ——
        第一章 有理数
        在生活、生产和科研中，经常遇到数的表示和运算等问题．例如：
    所以「一个 `第N章 <标题>` 的行，且它的下一非空行长度 > 30」就是正文起点，
    目录整段在它之前。跟目录长什么样无关。
    """
    lines = text.split("\n")
    start = None
    for i in range(len(lines) - 2):
        sn = norm(lines[i])
        if not re.match(r"^第[0-9一二三四五六七八九十]+章[^0-9]", sn):
            continue
        # 下一非空行是正文（目录后面不会跟正文，目录页会跟另一条目录行）。
        # 长度门槛必须放到 12 —— pdftotext -layout **按栏宽硬折行**，
        # 一句话被劈成两三行，单行只有 20~25 字。第一版按 30 卡，
        # 结果「在生活、生产和科研中，经常遇到数的表示和运」(23 字)
        # 就被判成「还是目录」，一个章节都没切掉。
        for j in range(i + 1, min(i + 6, len(lines))):
            nxt = norm(lines[j])
            if not nxt:
                continue
            if len(nxt) >= 12 and not re.search(r"[0-9]{1,3}$", nxt):
                start = i
            break
        if start is not None:
            break

    body = lines[start:] if start is not None else lines
    # **把折行接回去。** 中文行与行之间不补空格，直接拼。
    # 不拼的话按换行切句会把每一句都切成两半 —— 这是上一版 92% 判「找不到」的真正原因。
    return "".join(l.strip() for l in body)


def load_text(bk):
    """优先用 pdftotext 的文本层，没有就用 OCR 结果。"""
    for suffix in (".txt", ".ocr.txt"):
        p = CACHE / f"rjb-math-{FILES[bk]}{suffix}"
        if p.exists() and p.stat().st_size > 20000:
            return drop_toc(p.read_text(encoding="utf-8", errors="replace")), suffix
    return None, None


def key_variants(name):
    """概念名 → 拿去正文里找的几种写法。"""
    n = norm(name)
    out = {n}
    # 去掉括号：「数物体（数一数）」→「数物体」
    bare = re.sub(r"[（(\[【].*?[)）\]】]", "", n)
    out.add(bare)
    # 去掉「的」连接：「分与合的性质」→「分与合」
    for cut in ("的性质", "的意义", "的概念", "的定义", "的表示", "的计算", "的认识"):
        if bare.endswith(cut):
            out.add(bare[:-len(cut)])
    # 「数字1到5的认识」→「1到5」/「数字1到5」
    m = re.match(r"^(?:认识|理解)?(.+?)(?:的认识|的意义)?$", bare)
    if m:
        out.add(m.group(1))
    # 门槛是 2 不是 3。「符号」「正数」「倒数」这类两字概念占不小一块，
    # 按 3 起步会把它们全滤掉，然后报成「教材里找不到」——
    # 第一版就是这么把 100% 判成 NOT_FOUND 的。找不到 ≠ 教材没有，
    # 大概率是自己把门关太窄了。
    return {x for x in out if len(x) >= 2}


def sentences_around(text, kw, span=260):
    """取 kw 前后 span 字的一段，切成句子。

    两处必须注意，都是踩过的：
    1. **切句要在归一化之前做。** 这套教材 PDF 的文本层句号是**半角 `.`**，
       不是 `。`。第一版先把全文 norm 掉（压掉所有空白）再按 `[。？！]` 切，
       一个句子都切不出来，2269 个知识点全判成「教材里找不到」——
       而实际上「像 3,1.8%,3.5 这样大于 0 的数叫做正数」就写在正文里。
    2. **半角 `.` 还会出现在小数里**（1.8%、0.5），所以先按换行和全角标点切，
       再把剩下的半角 `.` 前后都带数字的情况跳过。
    """
    out = []
    kwn = norm(kw)
    for m in re.finditer(re.escape(kwn), norm(text)):
        pass    # 占位，下面用原文扫描，避免归一化后位置对不上
    # 在**原文**上定位：把归一化后的关键字映回原文不可靠，
    # 所以按中文两字以上的关键片段直接扫原文（原文里中文不会被拆开）
    raw_kw = re.escape(kw if kw in text else kwn)
    for m in re.finditer(raw_kw, text):  # 扫全书
        i = m.start()
        seg = text[max(0, i - span): i + span]
        for s in re.split(r"[。？！；;]", seg):
            sn = norm(s)
            if kwn in sn and 8 <= len(sn) <= 130:
                out.append(sn)
    # **必须扫全书，不能只看前若干处。**「相反数」在七上出现 34 次，
    # 定义句「像 a 和 -a 这样的数叫做互为相反数」在第 60 处之后。
    # 第一版收集够 60 条就 break，于是永远选到章首那段引言，
    # 拿到的全是「在生活、生产和科研中…」这种导语。
    return out


def pick_definition(cands, kw):
    """从候选句里挑最像定义的那句。挑不到就返回 None，不硬凑。"""
    # 最强信号：**判断词紧贴概念名**
    #   像 3,1.8%,3.5 这样大于 0 的数叫做正数        ← 叫做 + 正数
    #   像 a 和 -a 这样的数叫做互为相反数            ← 相反数 紧跟
    #   绝对值是一个数在数轴上...                    ← 绝对值 + 是
    # 「句子里出现过这个词」和「这个词是被定义的那个」差得很远：
    # 「正数」的第一条命中是「2 的相反数是 -2，正数、负数、零…」这种列举。
    # 只有两种句式算数：
    #   正向：…的数叫做正数          （判断词 + 概念名）
    #   反向：绝对值是一个数在数轴…   （概念名 + 是/指）
    # 「句子里出现过判断词」不算 —— 「可以是正数、负数」出现在一段讲**相反数**的话里，
    # 判断词和概念名挨着，但那句话定义的不是正数。
    adj_pat = re.compile(r"(?:叫做|称为|定义为|是指|统称|合称)\s*" + re.escape(kw))
    back_pat = re.compile(re.escape(kw) + r"\s*(?:是指|是|指的是|表示|指)")
    scored = []
    for s in cands:
        if not (adj_pat.search(s) or back_pat.search(s)):
            continue          # 不是在定义这个词的句子，直接不看
        score = 0
        # 「互为/互相」是定义数学概念最强的信号：
        # 「像 a 和 -a 这样的数叫做互为相反数」
        if re.search(r"(互为|互相|各自|相对地)", s):
            score += 3
        if s.startswith(kw):
            score += 2
        if len(s) < 14:
            score -= 3           # 太短，多半是残句
        if QUESTION.search(s):
            score -= 4
        if re.search(r"[0-9]{3,}", s):      # 一堆数字，多半是算式不是定义
            score -= 2
        if len(s) > 95:
            score -= 1
        if score > 0:
            scored.append((score, s))
    if not scored:
        # 全被判负不代表教材没写，只代表判据太窄。
        # 退一步：只要有判断词就采信，再不济给空 —— 不硬凑。
        loose = [s for s in cands if DEFINER.search(s)]
        return loose[0] if loose else None
    scored.sort(key=lambda x: (-x[0], abs(len(x[1]) - 42)))
    if not scored:
        # 整本书里没有一句是**在定义这个词**。宁可不抽。
        # 随便挑一句塞给用户比不给更坏 —— 错的定义会被当成教材原话，
        # 等 somebody 按它去复习、卡住了又查不出错在哪。
        return None
    return scored[0][1]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--books", help="逗号分隔册次码，如 7a,9a,bx2")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    g = json.loads(GRAPH.read_text())
    texts, used = {}, {}
    books = args.books.split(",") if args.books else list(FILES)
    for bk in books:
        t, src = load_text(bk)
        if t:
            texts[bk] = t      # **不要**在这里 norm
            used[bk] = src
    print("正文可用的册：" + "  ".join(f"{k}({v})" for k, v in sorted(used.items())))
    print(f"未就绪：{'  '.join(b for b in books if b not in texts) or '无'}\n")

    cs = [n for n in g["nodes"]
          if n["label"] in ("Concept", "Skill") and n["book"] in texts]
    if args.limit:
        cs = cs[:args.limit]

    stat = Counter()
    rows = []
    for n in cs:
        prop = (n.get("props") or {}).get("definition") or ""
        d = norm(prop)
        found = None
        for kw in sorted(key_variants(n["name"]), key=len, reverse=True):
            cands = sentences_around(texts[n["book"]], kw)
            found = pick_definition(cands, kw)
            if found:
                break
        if not found:
            stat["NOT_FOUND"] += 1
            rows.append({"id": n["id"], "name": n["name"], "book": n["bookZh"],
                         "upstream": prop, "status": "NOT_FOUND"})
            continue
        if not d:
            stat["MISSING"] += 1
            rows.append({"id": n["id"], "name": n["name"], "book": n["bookZh"],
                         "upstream": "", "textbook": found, "status": "MISSING"})
            continue
        # 词面重合度：上游定义和教材句子说的是不是一件事
        a = set(re.findall(r"[一-鿿]{2,}", d))
        b = set(re.findall(r"[一-鿿]{2,}", found))
        overlap = len(a & b) / max(1, len(a))
        if overlap >= 0.5:
            stat["AGREE"] += 1
        elif len(d) < 22:
            stat["THIN"] += 1
            rows.append({"id": n["id"], "name": n["name"], "book": n["bookZh"],
                         "upstream": prop, "textbook": found,
                         "overlap": round(overlap, 2), "status": "THIN"})
        else:
            stat["MISMATCH"] += 1
            rows.append({"id": n["id"], "name": n["name"], "book": n["bookZh"],
                         "upstream": prop, "textbook": found,
                         "overlap": round(overlap, 2), "status": "MISMATCH"})

    tot = sum(stat.values()) or 1
    print(f"═══ 定义核对 · {tot} 个知识点 ═══")
    for k in ("AGREE", "MISSING", "THIN", "MISMATCH", "NOT_FOUND"):
        print(f"  {k:<11}{stat[k]:>5}  {100*stat[k]/tot:5.1f}%")
    todo = stat["MISSING"] + stat["THIN"] + stat["MISMATCH"]
    print(f"\n要重写/补的：{todo} 个 = {100*todo/tot:.0f}%")

    OUT.write_text(json.dumps({"books": used, "stats": dict(stat), "rows": rows},
                              ensure_ascii=False, indent=1), encoding="utf-8")

    for st in ("MISMATCH", "THIN", "MISSING"):
        sample = [r for r in rows if r["status"] == st][:4]
        if not sample:
            continue
        print(f"\n── {st} 样例 ──")
        for r in sample:
            print(f"▸ {r['name']}[{r['book']}]")
            if r["upstream"]:
                print(f"  上游：{r['upstream'][:70]}")
            if r.get("textbook"):
                print(f"  教材：{r['textbook'][:80]}")
    print(f"\n→ {OUT.relative_to(BASE)}")


if __name__ == "__main__":
    main()
