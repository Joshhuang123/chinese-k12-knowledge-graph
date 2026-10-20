#!/usr/bin/env python3
"""
从各版本教材里抽出**目录结构**（章 → 节），为多版本对照做准备。

## 为什么要多版本

人教版是全国通用，但**不是唯一**：上海用沪教版、湖南用湘教版、
北京等地用北师大版、江苏用苏科版……

我们图谱的教材顺序是按**人教版**排的（`books.py` 的 `RANK` 只排人教）。
一个用湘教的学生查「二次函数」，页面上写的「九上 22.2」对他没有意义 ——
他那本教材里不是这一章。

## 三个技术点

1. **人教基准不 OCR**：图谱里现成就是人教的 Chapter/Section 节点
   （609 个 Section），直接拿来当基准。人教那 6 本 PDF 有 3 本是扫描件，
   重跑 OCR 既慢又不如图谱里的准。
2. **两栏目录要拆行**：tesseract 的 psm 3/6 把左右栏串成一行
   （「第一章 有理数 1 第三章 代数式 95」）。用正则按「第N章」「N.M」切开。
   psm 4 会先读左栏再读右栏，天然分行 —— 两种都跑，哪个解析得好用哪个。
3. **匹配不硬凑**：各出版社的节名不完全一样，靠 difflib 相似度，
   低于阈值的标 unmatched。

## 跑法

```bash
python3 src/extract_editions.py
python3 src/extract_editions.py --only 湘教
python3 src/extract_editions.py --out data/alt-editions.json
"""
import argparse
import json
import pathlib
import re
import subprocess
import sys

BASE = pathlib.Path(__file__).resolve().parent.parent
CACHE = BASE / "data" / "pdf-cache" / "alt"
WORK = BASE / "data" / "pdf-cache" / "work"
MANIFEST = BASE / "data" / "alt-editions-manifest.json"
OUT = BASE / "data" / "alt-editions.json"

CN = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8,
      "九": 9, "十": 10, "十一": 11, "十二": 12}
# 章号**可以没有** —— 沪科版把「１」单独放一行，拼回来是「第章 有理数」。
# 没有编号的章靠**章名**合并（同一本书里章名不会重）。
RE_CH = re.compile(r"^第\s*([一二三四五六七八九十]{1,3})?\s*章\s*(.*)$")
# **纯数字编号的章**：湘教/浙教/沪科/青岛等不少版本不用「第N章」，
# 而是「1 有理数」这样。章号没有小数点，节号有（1.5）—— 靠这个区分。
RE_CH_NUM = re.compile(r"^(\d{1,2})\s+([^\d\s].{1,18}?)\s*$")
RE_SEC = re.compile(r"^(\d{1,2}(?:\.\d{1,2}){0,2})\s*(.*)$")
# 一行里挤了两栏时，按「第N章」或「N.M」切开
# 切分点：第N章 / N.M（节）/ N 名称（数字编号的章）。
# 「数字编号的章」要求数字后面跟空格再跟非数字，且前面不是 . 或数字 ——
# 这样「26.2 锐角三角函数」不会被误切（26 后面是 . 不是空格）。
SPLIT = re.compile(r"(?=第[一二三四五六七八九十]{1,3}章)"
                   r"|(?=(?<![0-9])\d{1,2}\.\d{1,2}(?!\d))"
                   r"|(?=(?<![.\d])\d{1,2}\s+[^\d\s])")


def cn2int(s):
    """中文数字 → 整数。

    **必须支持「二十三」这种写法。**
    原来只映射了一到十二，「二十三」算成 2→2、十→10、三→3 = 303，
    被 `1 <= num <= 40` 全部过滤掉 ——
    冀教九上的目录有 6 个章（第二十三章起）全军覆没，
    而冀教七上（章号一二三四）看着没问题。
    **症状是「有的书行、有的书不行」，不看具体数字根本发现不了。**
    """
    DIGIT = {"零": 0, "一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
             "六": 6, "七": 7, "八": 8, "九": 9}
    UNIT = {"十": 10, "百": 100}
    s = s.strip()
    if not s:
        return 0
    if s in CN:                      # 一…十二（含十一、十二）
        return CN[s]
    total, section, number = 0, 0, 0
    for ch in s:
        if ch in DIGIT:
            number = DIGIT[ch]
        elif ch in UNIT:
            unit = UNIT[ch]
            if unit == 10:
                # 「十」= 10；「二十」= 20（十前面有数就加）
                section += (number if number else 1) * unit
                number = 0
            else:
                section = (section + number) * unit
                number = 0
        else:
            return 0
    return total + section + number


def ocr(png, psm):
    r = subprocess.run(["tesseract", str(png), "stdout", "-l", "chi_sim", "--psm", psm],
                       capture_output=True, timeout=240)
    return r.stdout.decode("utf-8", "replace")


def page_text(doc, i, dpi=200, psm="4"):
    """先试文本层，没有再 OCR。

    **一半以上的版本有文本层** —— 青岛版 6/6、北京版 3/6、苏科版七上
    直接就能读出来又快又准；只有真正���扫描件才需要 OCR。
    之前一律走 OCR，把好材料也做坏了 —— 湘教那本扫描质量差，
    OCR 出来的目录全是乱码（章名读成「个单位」「(2) y=xr」）。
    """
    t = doc[i].get_text()
    if len(re.sub(r"\s", "", t)) >= 120:
        return t
    WORK.mkdir(parents=True, exist_ok=True)
    png = WORK / "_p.png"
    doc[i].get_pixmap(dpi=dpi).save(str(png))
    return ocr(png, psm)


def clean(s):
    s = re.sub(r"[“”\"'‘’]", "", s)
    s = re.sub(r"[·\.…]{2,}", "", s)
    s = s.strip(" .·、，,")
    return s


def parse(lines):
    """→ (chapters, nSections)。lines 已经拆过栏。"""
    chapters, cur = [], None
    nsec = 0
    for raw in lines:
        line = re.sub(r"\s+", " ", raw).strip()
        if not line or len(line) > 46:
            continue
        m = RE_CH.match(line)
        if m:
            num = cn2int(m.group(1)) if m.group(1) else None
            body = clean(m.group(2))
            pm = re.search(r"(\d{1,3})\s*$", body)
            page = int(pm.group(1)) if pm else None
            name = clean(re.sub(r"\d{1,3}\s*$", "", body))
            if num is not None and not (1 <= num <= 40):
                continue
            if not (2 <= len(name) <= 18):
                continue
            cur = {"ch": f"第{m.group(1)}章 {name}" if m.group(1) else name,
                   "chNum": num, "name": name, "page": page, "secs": []}
            chapters.append(cur)
            continue
        m = RE_CH_NUM.match(line)
        if m:
            # 「1 有理数」—— 数字编号的章。
            # **不能加「只在还没有当前章时才算章」的守卫**：
            # 那样每本书只认得出第一章，后面的数字章全被忽略
            # （症状是每本都「1 章 N 节」）。
            # 「1.5 xxx」不会被误判成章 —— 它的编号后面是「.」不是空格，
            # 而 RE_SEC 已经先一步把带小数点的行当成节了。
            num = int(m.group(1))
            name = clean(m.group(2))
            if not (1 <= num <= 40) or not (2 <= len(name) <= 18):
                continue
            cur = {"ch": f"第{num}章 {name}", "chNum": num,
                   "name": name, "page": None, "secs": []}
            chapters.append(cur)
            continue
        m = RE_SEC.match(line)
        if m and cur is not None:
            body = clean(m.group(2))
            pm = re.search(r"(\d{1,3})\s*$", body)
            page = int(pm.group(1)) if pm else None
            name = clean(re.sub(r"\d{1,3}\s*$", "", body))
            if name and len(name) <= 18 and not re.fullmatch(r"[\d\.\s]+", name):
                cur["secs"].append({"no": m.group(1), "name": name, "page": page})
                nsec += 1
    return chapters, nsec


def try_psm(doc, toc_pages, psm):
    lines = []
    for i in toc_pages:
        t = page_text(doc, i, psm=psm)
        for raw in t.split("\n"):
            line = re.sub(r"\s+", " ", raw).strip()
            if not line:
                continue
            for piece in SPLIT.split(line):
                if piece.strip():
                    lines.append(piece.strip())
    return parse(lines)


CJK_ONLY = re.compile(r"^[一-鿿、·]{2,14}$")

# ── 排版规范化 ──────────────────────────────────────────────
# 沪科版的目录用的是**全角数字 + 私用区字符当小数点**：
#     １\ue010１  正数和负数
# 那个 U+E010 是 PDF 里的小数点（私用区没有标准码位，出版方自己占的）。
# 不规范化的话，`^(\d{1,2}\.\d{1,2})` 一个都匹配不上 ——
# 表现是「章名认得出、节全丢了」。
PRIVATE = re.compile(r"[-]")
FULLWIDTH = str.maketrans("０１２３４５６７８９．，", "0123456789.,")


def normalize(text):
    """把各种排版怪癖拉回常规形态。"""
    text = PRIVATE.sub(".", text)
    text = text.translate(FULLWIDTH)
    text = text.replace("　", " ")
    return text


def join_split_headings(lines):
    """「第」单独占一行、下一行才是「章 有理数」—— 拼回去。

    沪科版、不少版本的目录是这么排的。
    """
    out, i = [], 0
    while i < len(lines):
        ln = lines[i]
        if ln.strip() == "第" and i + 1 < len(lines):
            out.append("第" + lines[i + 1].strip())
            i += 2
            continue
        out.append(ln)
        i += 1
    return out


def name_quality(names):
    """章名可信度：几个名字是「像样的中文」。

    **这道闸是必须的。** 扫描质量差的教材，OCR 出来的章名是这样的：
        「个单位」「设这两个自然数分别是*，r」「(2) y=xr」
        「CTCU$:VWA%8XBC!」「Se 4」「二次函数的应用 .pp」
    拿这种东西去做多版本对照，比不做还糟 ——
    用户看到「这个概念在湘教版是『个单位』」，只会觉得这个项目在瞎搞。

    所以：章名里必须有足够比例的正经汉字，全是符号/拉丁字母的一律不算。
    """
    if not names:
        return 0.0
    good = sum(1 for n in names if CJK_ONLY.match(n))
    return good / len(names)


def process(pdf, toc_scan=16):
    import fitz
    doc = fitz.open(pdf)
    # ① 逐页解析，**按得分挑目录页**。
    # 原来靠「这一页有『目录』两个字」来认目录页 —— 湘教那本的目录里
    # 既没有「目录」也没有「第」（它用「1 有理数」这种编号）。
    # 改成：哪一页解析出的章节/节最多，它就是目录页。
    def parse_page(doc, i, psm, dpi):
        t = normalize(page_text(doc, i, dpi=dpi, psm=psm))
        raw_lines = [re.sub(r"\s+", " ", l).strip() for l in t.split("\n")]
        raw_lines = [l for l in raw_lines if l]
        raw_lines = join_split_headings(raw_lines)
        lines = []
        for line in raw_lines:
            for piece in SPLIT.split(line):
                if piece.strip():
                    lines.append(piece.strip())
        return parse(lines)

    # ── 两遍扫描 ────────────────────────────────────────────
    # ① **便宜地找目录页**：dpi 140、只跑 psm 6，每页约 1.5 秒。
    #    原来每页都跑两个 psm、dpi 200 —— 一本 30 本要 2 小时。
    # ② 只在候选页上**认真解析**：dpi 200、psm 4 和 6 都跑，取好的那个。
    # 选页评分里**必须带上章名质量**。
    # 只按「章数×4+节数」排，会选中「节多但章名全是 OCR 垃圾」的正文页 ——
    # 冀教七上有个正文页能解析出 15 章 5 节（章名是「- 2，天气预报是怎样表示气温的?」），
    # 而真正的目录页是 4 章 41 节、章名干净。**加上质量项才选得对。**
    # **穷举每一页。**
    # 试过「先用便宜的一遍筛出候选页、再只解析前 5 页」——
    # 快了 4 倍，但**把冀教版弄坏了**：
    # 冀教七上真正的目录页是 4 章 41 节、章名干净，
    # 而正文页能解析出 15 章 5 节、章名是「- 2，天气预报是怎样表示气温的?」。
    # 便宜那一遍（dpi 140）没把真目录页排进前 5，
    # 结果整本选错、章名可信度只有 20%。
    #
    # 教训：**便宜的一遍可以用来排除，不能用来排序。**
    # 一本书的目录在哪一页，是不能靠「哪页解析出来的东西多」猜的 ——
    # 正文里的例题编号比目录还多。
    def seq_run(secs):
        """**最长连续节号串**的长度。

        这是判断「哪一页是目录」的可靠信号：
        目录里的节号是**连续的**（1.1 1.2 1.3 … 2.1 2.2 …），
        正文里的编号是散的（例题号、公式号、页码）。
        「哪页解析出来的东西多」不可靠 ——
        正文页的编号比目录还多（实测过）。
        """
        nos = [s.get("no", "") for s in secs]
        nos = [n for n in nos if n and "." in n]
        best = run = 1
        prev = None
        for n in nos:
            if prev is not None:
                try:
                    a = [int(x) for x in prev.split(".")]
                    b = [int(x) for x in n.split(".")]
                    if len(a) == len(b) and b[:-1] == a[:-1] and b[-1] == a[-1] + 1:
                        run += 1
                    elif len(a) == len(b) and b[:-1] != a[:-1] and b[-1] == 1:
                        run = 2          # 换章了
                    else:
                        run = 1
                except ValueError:
                    run = 1
            best = max(best, run)
            prev = n
        return best

    def merge(a, b):
        """两页的解析结果合并（目录常常跨页）。"""
        chs = list(a)
        for c in b:
            hit = next((x for x in chs
                        if (c["chNum"] is not None and x["chNum"] == c["chNum"])
                        or (c["chNum"] is None and x["name"] == c["name"])), None)
            if hit:
                hit["secs"] += [s for s in c["secs"] if s["no"] not in
                                 {x["no"] for x in hit["secs"]}]
            else:
                chs.append(c)
        chs.sort(key=lambda c: (c["chNum"] is None, c["chNum"] or 0))
        return chs

    # ① 逐页打分，找目录的**首页**
    scored = []
    for i in range(min(toc_scan, doc.page_count)):
        for psm in ("4", "6"):
            chs, nsec = parse_page(doc, i, psm, 200)
            q = name_quality([c["name"] for c in chs])
            run = seq_run([s for c in chs for s in c["secs"]])
            scored.append((run * 10 + nsec + len(chs) * 2 + q * 8, i, psm, chs))
    scored.sort(key=lambda x: -x[0])
    best = None
    if scored:
        _, bi, bp, bchs = scored[0]
        # ② **合并相邻页** —— 目录常常跨 2~3 页，
        #    只取一页的话节数永远不全（人教七上 25 节 vs 只取到 19 节）。
        merged = bchs
        for off in (1, 2, -1):
            j = bi + off
            if not (0 <= j < doc.page_count):
                continue
            for psm in ("4", "6"):
                jchs, _ = parse_page(doc, j, psm, 200)
                if not jchs:
                    continue
                cand = merge(bchs, jchs)
                if sum(len(c["secs"]) for c in cand) > sum(len(c["secs"]) for c in merged):
                    merged = cand
        nsec = sum(len(c["secs"]) for c in merged)
        q = name_quality([c["name"] for c in merged])
        best = (0, bi, merged, nsec)
    if not best:
        doc.close()
        return {"tocPages": [], "chapters": [], "nChapters": 0, "nSections": 0}
    score, bi, chs, nsec = best
    doc.close()
    q = name_quality([c["name"] for c in (chs or [])])
    # 质量闸：章名不可信 → 整本标为「提取不可靠」，**不进对照表**
    reliable = (len(chs or []) >= 2 and nsec >= 5 and q >= 0.6)
    return {"tocPages": [bi + 1], "chapters": chs or [],
            "nChapters": len(chs or []), "nSections": nsec,
            "tocScore": score, "nameQuality": round(q, 2),
            "reliable": reliable,
            "why": ("" if reliable else
                    f"章名可信度 {q:.0%}（要 ≥60%）、{len(chs or [])} 章、{nsec} 节"
                    + ("" if len(chs or []) >= 2 else "、章数不足 2")
                    + ("" if nsec >= 5 else "、节数不足 5"))}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only")
    ap.add_argument("--skip", help="跳过某个版本（人教用图谱里的现成结构，不��� OCR）")
    ap.add_argument("--out")
    args = ap.parse_args()
    if not MANIFEST.exists():
        print("! 先跑 src/fetch_editions.py")
        return 1
    man = json.load(open(MANIFEST, encoding="utf-8"))
    editions = man.get("editions", {})
    if args.only:
        editions = {k: v for k, v in editions.items() if args.only in k}
    if args.skip:
        editions = {k: v for k, v in editions.items() if args.skip not in k}
    out = {}
    for ed, books in sorted(editions.items()):
        out[ed] = {}
        for key, meta in sorted(books.items()):
            pdf = BASE / meta["local"]
            if not pdf.exists():
                continue
            try:
                r = process(str(pdf))
            except Exception as e:
                print(f"  {ed}/{key}: 失败 {e}")
                continue
            out[ed][key] = r
            flag = "✓" if r["reliable"] else "✗"
            print(f"  {flag} {ed}/{key:<8} {r['nChapters']:>2} 章 {r['nSections']:>3} 节"
                  f"  可信度 {r['nameQuality']:.0%}  " +
                  ("" if r["reliable"] else r["why"]) +
                  "  " + "、".join(c["name"] for c in r["chapters"][:3]))
    op = pathlib.Path(args.out) if args.out else OUT
    if not op.is_absolute():
        op = BASE / op
    # **合并而不是覆盖** —— --only 只跑一个版本时，
    # 覆盖会把之前跑好的版本全弄没了（踩过：只跑湘教就把冀教等冲掉了）。
    merged = {}
    if op.exists():
        merged = json.load(open(op, encoding="utf-8"))
    merged.update(out)
    json.dump(merged, open(op, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\n→ {op.relative_to(BASE)}（共 {len(merged)} 个版本）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
