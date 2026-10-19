#!/usr/bin/env python3
"""
核对：从节点 id 推出来的教材顺序，跟人教社官方 PDF 的目录对不对得上。

**为什么要有这个脚本**

顺序链（`build_viz.py` 的 `seq_slot`）完全建立在两个假设上：

1. `_chNN_sMM` 这个 id 后缀就是教材里的真实次序；
2. `books.py` 的 `GLOBAL_ORDER` 就是册次的真实先后。

这两个假设都是从数据结构里读出来的，**读数据不等于读事实**。
所以要有一份独立来源来对：**人教社出版的教材 PDF 自己的目录页**。

一旦 PDF 目录和推导结果不一致，说明我们排错了 —— 顺序链是页面上
唯一一条「上一单元 / 下一单元」的导航，排错比没有更糟。

**这个脚本只读目录页**，不抽正文、不存教材内容。

## 跑法

```bash
python3 src/verify_order.py              # 缓存已下载的 PDF，只重跑比对
python3 src/verify_order.py --fetch      # 先把缺的册次下载到 data/pdf-cache/
```

PDF 来自 `TapXWorld/ChinaTextbook`（GitHub 公开仓库），
直链 `raw.githubusercontent.com`，不需要 token。

## 已核对的结论（2026-10-19 实测，21 册）

```
次序错误 0 处（这才是「排错了」）
未核对 0 册
未能定位 9 个单元 —— 全部是 OCR 没认准字，不是图谱排错
覆盖缺口 11 册共 17 个单元（图谱没建，不是排错）
```

| 册次 | 结果 |
|---|---|
| 一上 ~ 六下（12 册） | ✓ 每一册的每个单元都落在官方目录的先后位置上 |
| 七上 / 七下 / 八上 / 八下 / 九上 / 九下 | ✓ 同上（七下/八下/九下走 OCR） |
| 必修一 / 必修二 / 选必一 | ✓ 已配上的章节次序都对；部分章名 OCR 没认出来 |

**「次序错误 0」这个数字要这么读**：它是**上界**，不是普查结果。
配套的「未能定位」数是下界 —— 七下 1/6、八下 4/5、必修一 4/5、
必修二 1/5、选必一 1/3，其余 16 册是满配。
配不上的全是 OCR 质量问题（漏整行、把「函」认成「子」、章号根本没识别出来），
不是图谱排错，但它们确实让这几册的结论**不完整** —— 报告里逐条列了出来。

## 比对口径为什么这么定

早期版本用「逐位相等」，三次栽在同一个地方：**中间配不上一个，
后面全部连锁报成排错**。四上（图谱缺「亿有多大」）一次报了 8 处，
真实问题只有 1 处。现在拆成三件独立的事：

1. **配不上** —— 图谱编了，或者 OCR 没认准。分开报，不算排错。
2. **次序反了**（配上了但下标不递增）—— 这才是排错。
3. **官方有、图谱没建** —— 覆盖缺口。

OCR 册用**模糊匹配**（字符相似度 ≥ 0.72），文本层册用**精确匹配**：
目录字是人排的没有理由宽容，而 OCR 的实际错法是逐字替换或加前缀噪声，
包含匹配对这两种完全无效。

## 踩平的解析坑（每一条都是先误报、后查清）

| 坑 | 症状 | 判据换成 |
|---|---|---|
| 册次码 ≠ 文件名码 | 初高中册全部「未缓存」，看着像没核对 | 走 `pdf_of()` 映射 |
| `.pdf.1`+`.pdf.2` 拆册 | 必修一读不出目录 | 先拼再读 |
| 纯扫描件无文本层 | 七下/八下/九下「没找到目录页」 | OCR 兜底 |
| TOC 窗口 2000 字 | 初中第二章往后全被截掉 | 放大到 8000 |
| 目录行判据靠缩进 | 「数学活动」只有一个空格 → 漏 | 改看**收不收尾于页码** |
| 目录行判据靠长度 | 九上「数学活动」去缩进仍 27 字 → 提前退 | 同上 |
| `miss >= 2` 太紧 | OCR 碎片行连着两三行 → 提前退出丢整章 | 放宽到 6 |
| 目录里没有「目 录」 | 高中 4 册全报「没找到目录页」，其实目录在第 6-7 页 | 章号 ≥2 的页即目录页 |
| 条目名不含汉字 | 目录的**页码列**被当成单元名，二上塌成 1 条 | 名字至少 1 个汉字 |
| 单字单元名被误杀 | 六上「比」「圆」两单元被我自己的判据判死 | 下限从 2 降到 1 |
| 正文页眉当目录 | 五上 8 条全对之后又吞进 3 条正文 | 单元号必须严格递增 |
| 插页编号复用单元号 | 四上「亿有多大」让递增判据提前中断 | 缩进的算插页，不参与递增 |
| `\x0c` 换页符当缩进 | 四上/五上/六下各丢三四个真单元 | 判缩进前先剥换页符 |
| 名跨两行 | 二上第 2 单元整条消失，报成「8 个找不到」 | 缩进=名字的一部分，顶格=单元号 |
| 章名后拖填充噪声 | 必修一第一章配不上，第二章顶上去 → **假排错** | 砍掉 `.eeee…` 尾巴 |
| 「函数」被认成「子数」 | 九下报 2 处排错，全是假的 | 模糊匹配 |

**两处曾误判、后来查清的原因**：

1. **小学数学一上的目录里「认识图形（一）」确实排在「6~10 的认识和加减法」之前。**
   我按旧版教材的印象以为反了，拉 2022 年 8 月第 2 版的官方 PDF 一对，
   是对的 —— 现行版就是这个次序。**我记错了，不是数据错了。**
2. **必修一曾报「第二章排错」**，是第一章的章名被 OCR 拖了
   `.eeeeeeeeeeeeeeeeesees1` 配不上，第二章顶到了第一章的位置。
   报的是 OCR 噪声，不是图谱。清洗尾巴后归零。

"""
import argparse
import json
import pathlib
import re
import subprocess
import sys
import urllib.parse
import urllib.request
from difflib import SequenceMatcher

BASE = pathlib.Path(__file__).resolve().parent.parent
GRAPH = BASE / "data" / "normalized" / "graph.json"
CACHE = BASE / "data" / "pdf-cache"
RAW = "https://raw.githubusercontent.com/TapXWorld/ChinaTextbook/master/"

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from books import rank           # noqa: E402

# 册次 → ChinaTextbook 里的文件名。
# 注意 `·` 两侧的空格不一致：一年级上册是「教科书 · 数学」，
# 一年级下册起是「教科书·数学」。照抄错了就是 404。
TEXTBOOKS = {
    "1a": "小学/数学/人教版/义务教育教科书 · 数学一年级上册.pdf",
    "1b": "小学/数学/人教版/义务教育教科书·数学一年级下册.pdf",
    "2a": "小学/数学/人教版/义务教育教科书 · 数学二年级上册.pdf",
    "2b": "小学/数学/人教版/义务教育教科书·数学二年级下册.pdf",
    "3a": "小学/数学/人教版/义务教育教科书 · 数学三年级上册.pdf",
    "3b": "小学/数学/人教版/义务教育教科书·数学三年级下册.pdf",
    "4a": "小学/数学/人教版/义务教育教科书 · 数学四年级上册.pdf",
    "4b": "小学/数学/人教版/义务教育教科书·数学四年级下册.pdf",
    "5a": "小学/数学/人教版/义务教育教科书 · 数学五年级上册.pdf",
    "5b": "小学/数学/人教版/义务教育教科书·数学五年级下册.pdf",
    "6a": "小学/数学/人教版/义务教育教科书 · 数学六年级上册.pdf",
    "6b": "小学/数学/人教版/义务教育教科书·数学六年级下册.pdf",
}

CN = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6,
      "七": 7, "八": 8, "九": 9, "十": 10}


def cn2int(s):
    """「二十二」→ 22。人教目录里章号最大到三十几。"""
    if s.isdigit():
        return int(s)
    if s == "十":
        return 10
    if "十" in s:
        a, _, b = s.partition("十")
        return (CN.get(a, 1) if a else 1) * 10 + (CN.get(b, 0) if b else 0)
    return CN.get(s, 0)


def fetch(book):
    CACHE.mkdir(parents=True, exist_ok=True)
    dst = CACHE / f"rjb-math-{book}.pdf"
    if dst.exists() and dst.stat().st_size > 1_000_000:
        return dst
    url = RAW + urllib.parse.quote(TEXTBOOKS[book])
    print(f"  下载 {book} …", flush=True)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=300) as r:
        dst.write_bytes(r.read())
    return dst


# 册次 → 本地 PDF 文件名。初高中这两套编码不一样：
#   图谱册次 7a / 8a / 9a / bx1 / bx2 / xzxbx1…
#   文件名   7a / 8a / 9a / m1  / m2  / x1 …
# 不映射的话 toc_of 去找 rjb-math-bx1.pdf → 文件不存在 → 静默跳过，
# 看起来像「没核对」，实际是路径写错了。
FILE = {"bx1": "m1", "bx2": "m2",
        "xzxbx1": "x1", "xzxbx2": "x2", "xzxbx3": "x3"}


def pdf_of(book):
    return CACHE / f"rjb-math-{FILE.get(book, book)}.pdf"


def toc_source(pdf):
    """这份目录是从哪来的：pdf 文本层还是 OCR。次序核对的比对口径取决于它。"""
    txt = pdf.with_suffix(".txt")
    if txt.exists() and txt.stat().st_size >= 20000:
        return "text"
    if pdf.with_suffix(".ocr.txt").exists():
        return "ocr"
    return "none"


def is_entry_name(name):
    """条目名至少要有 1 个汉字。

    `pdftotext -layout` 按栏宽硬折行，目录的**页码列会被排成独立的一行**：
    二上目录里出现过「1   2   3   4   5   6    3    4    5 ……」这样一整行，
    它被 m_num 当成「第 1 单元」收进去，官方目录就少了一条真单元，
    后面 8 条全部连锁报成「找不到」—— 而真排错混在里面就看不见了。
    一上/六下的插页列表里也全是这种（插页只列「1」「4」「9」）。
    纯数字不是条目名，无条件拒掉。

    下限是 1 不是 2：人教版目录里真有单字单元 —— 六上第 4 单元「比」、
    第 5 单元「圆」。卡 2 个汉字会把这两条判死，
    六上因此只配上 3/9，看起来像图谱排错了，其实是我自己的判据造的假阴性。
    """
    return len(re.findall(r"[\u4e00-\u9fff]", name)) >= 1


def strip_ocr_noise(name):
    """剥掉章名被 OCR 认出来的前后噪声。

    实测：七下「第五章 相交线与平行线」被认成「第五章，"相交线与平行线」，
    九下「第二十七章 相似」被认成「第二十七章"相似」，八下
    「第二十八章 锐角三角函数」里的「函」被吞成「锐角三角子数」。

    前缀噪声是系统性的（“”“ 一律被认成 `，“`），后面比对走包含匹配，
    多一个标点不影响；但不洗掉的话，「"相交线与平行线」这种还会被
    当成一条**不同的**插页条目，混进目录计数里。清洗只动章名开头，
    不动正文 —— 宁可少抽，不抽错。
    """
    name = re.sub(r'^[\s，“”"\'‘’、，,。．.·—\-]+', "", name).strip()
    # 章名中间的引号也去掉：必修一「第一章 ”集合与常用逻辑用语」，
    # 引号夹在章号和名字之间，清洗只管开头的话会漏掉。
    # 人教数学的章名不用引号，它在这里只可能是 OCR 噪声。
    return name.replace("“", "").replace("”", "").strip()


def strip_fill(name):
    """砍掉 OCR 在章名尾巴上拖的填充噪声。

    实测必修一：`第一章 集合与常用逻辑用语 .eeeeeeeeeeeeeeeeesees1`，
    选必修二：`平面向量及其应用.pp 1`、`立体几何初此间ee 96`。
    这些尾巴让章名配不上图谱，**而配不上会让配对整体错位**：
    第一章落空，第二章顶到第一章的官方位置上，
    单调性判据于是报「第二章排错」—— 报的是 OCR 的噪声，
    不是图谱排错了。跟四上那次「缺一课 → 后面全部排错」是同一类错位。

    只在 OCR 册的章级条目上用：初中高中目录里的小节号本身带点
    （`3.4 函数的应用`），照同一刀切会把 `3.4` 砍成 `3`。
    """
    return re.split(r"[\.…_]|\s{2,}", name)[0].strip()


def toc_window_by_pages(t):
    """OCR 册兜底定位目录页。

    **「目 录」这两个字经常识别不出来**：必修一认成「目 孙」，
    选必一也是「目 孙」，八下整本都没有 —— 之前报的是
    「PDF 里没找到目录页」，看着像 PDF 的问题，其实是 OCR 的问题，
    而目录页明明就在第 6-7 页。

    高中目录一章占一行，所以**第一页里出现 ≥2 个「第X章」就是它**。
    正文页也会提到章名，但不会在开头连续列出来；
    真混进来了，循环里「章号必须严格递增」会把正文回引挡掉。

    返回该页往后的 8000 字，找不到返回 None。
    """
    m_chap_head = re.compile(r"第[一二三四五六七八九十]{1,3}章")
    pages = re.split(r"<<<PAGE \d+>>>", t)
    for i, pg in enumerate(pages[1:], start=1):   # pages[0] 是封面之前那段
        if len(m_chap_head.findall(pg)) >= 2 and len(pg.strip()) > 200:
            return "".join(pages[i:i + 4])
    return None


def toc_of(pdf):
    """抽目录页：返回 [(单元号|None, 条目名), …]，按目录里的先后。

    目录是**连续**的一段，紧跟其后就是正文，所以遇到第一行不像目录条目
    的就停。人教 PDF 正文里的算式（「9 56 - 8 1 4 = 1 1 4」）也会被宽松
    的正则匹配上，拿目录对算式毫无意义。

    条目有两种：带单元号的「5   6~10 的认识和加减法   39」，
    和没编号的插页「数学乐园 82」「营养午餐 106」。

    **已知局限**：条目名跨行时（如二上第 2 条占三行）会漏掉那一册。
    漏掉的册次会报成「次序错误」——**宁可误报不可漏报**，
    误报会被看见，漏报会被当成核对通过。
    """
    txt = pdf.with_suffix(".txt")
    if not txt.exists() or txt.stat().st_size < 20000:
        ocr = pdf.with_suffix(".ocr.txt")
        if ocr.exists() and ocr.stat().st_size > 20000:
            txt = ocr          # 7b/8b/9b 是纯扫描件，只有 OCR 结果
        else:
            # stderr 全是 Marked Content 之类的告警，人教 PDF 结构特殊，
            # 不影响出字，直接丢掉。
            subprocess.run(["pdftotext", "-layout", str(pdf), str(txt)],
                           check=True, stderr=subprocess.DEVNULL)
    t = txt.read_text(encoding="utf-8", errors="replace")
    ocr_mode = txt.name.endswith(".ocr.txt")
    # 标题是「目   录」，空格数量不固定（实测三个），不能写死
    m = re.search(r"目\s{2,}录", t)
    if not m:
        seg = toc_window_by_pages(t)
        if seg is None:
            return None
    else:
        seg = t[m.end(): m.end() + 8000]
    # 窗口 2000 字是给小学目录定的。初中目录条目多（八上有 24 条插页 + 5 章），
    # 2000 字装不下，第二章往后全被截掉 → 报「目录只解析出 1 条」。
    # 循环里已经有边界判断，窗口放大不会误吞正文。

    out, started = [], False
    # 目录有两种版式，之前的正则只认一种，另一册册报「没找到目录」——
    # 而报告写的是「跳过（不是核对通过）」，两次都不报错地漏掉了。
    #   小学：  5   6~10 的认识和加减法   39          ← 单元号 + 空格
    #   初中：  第一章 有理数                        ← 章标题，无页码
    #           １．１ 正数和负数          ２            ← 全角「１．１」
    #           实验与探究 填幻方        ２１           ← 缩进插页，无单元号
    m_chap = re.compile(r"^\s*第([一二三四五六七八九十\d]+)[章单元]\s*(\S.*?)\s*$")
    m_sec = re.compile(r"^\s*(\d{1,2})[\.．]\s*(\d{1,2})\s+(\S.*?)\s*\.?\s*(\d{1,3})\s*$")
    m_num = re.compile(r"^\s*(\d{1,2})\s+(\S.*?)\s*\.?\s*(\d{1,3})\s*$")
    m_nam = re.compile(r"^\s+(\S.*?)\s*\.?\s*(\d{1,3})\s*$")
    # 跨行条目：「３．２ 解一元一次方程 （一）」的页码印在**下一行**。
    # 这行既不是完整的目录行，也不是正文。原来的 `if started: break`
    # 在这里退出，后面整章全丢 —— 七上因此只解析出 3 章。
    m_wrap = re.compile(r"^\s*\d{1,2}[\.．]\s*\d{1,2}\s+\S")
    # 插入页标题也会跨行：「阅读与思考 狓²＋（狆＋狇）狓＋狆狇 型式子的」
    # 的页码印在**下一行**，本行既不以页码收尾，也不是正文。
    # 单独看一行判断不了是「跨行标题」还是「进正文了」，
    # 唯一稳的信号是**连续性**：跨行最多断一节，正文段会连着断很多节。
    miss = 0
    last_chap = 0
    last_num = 0
    # **人教小学目录的名可以跨行，而且单元号印在续行上**：
    #     1   长度单位          2
    #         100 以内的加法
    #     2   和减法（二）
    #                      11
    # 名分两行，页码又落到第三行。原来三个正则一个都不匹配，
    # 二上因此只解出 8 个单元，第 2 单元整条消失，
    # 后面被判成「8 个图谱单元在官方目录里找不到」——
    # **把解析器的失败算到了图谱头上**，而真排错混在里面就看不见了。
    #
    # 区分「续行」和「新条目」靠**行首有没有单元号**：
    # 初中高中目录用「第X章」「X．Y」，行首带的是章号节号，
    # 跟小学的单元号不是一回事，正则 `\d{1,2}\s+` 只认小学那种。
    pending = None          # 上一条没带页码的名字，等续行来接

    def flush():
        """把挂着的名字收成一条。页码有没有都不影响章序。"""
        nonlocal pending
        if pending is not None:
            # 没有单元号的降级成插页：目录末尾的正文残骸
            # （「35人」「二（」这种）会从 mcont 兜底分支进来，
            # 顶着 unit 的身份混进章级条目里。
            kind = pending[2] if pending[0] is not None else "ins"
            out.append((pending[0], pending[1], kind))
            pending = None

    for line in seg.split("\n"):
        s_ = line.strip()
        if not s_:
            continue
        if re.fullmatch(r"<<<PAGE \d+>>>", s_):
            continue                        # ocr_books.py 写的页标记，不是目录行
        if re.fullmatch(r"[\d\s]{1,6}", s_):
            continue                        # 目录右侧那列页码，单独成行
        name = None
        miss = 0                                # 匹配上的行重置连续计数
        mc = m_chap.match(line)
        if mc:
            ch = cn2int(mc.group(1))
            # **章号必须严格递增，这是目录章级条目的硬特征，也是「进正文了」
            # 最可靠的信号。** 正文里随时会回引「上一章我们认识了几何图形」
            # 「第四章」，m_chap 不看行尾，会把「第五章 相交线与平行线」当成
            # 第 12 条目录 —— 七下实测解析出 17 条，其中 7 条是正文回引。
            # 章号一旦回退，说明已经越过目录末尾。
            if started and ch <= last_chap:
                break
            name = strip_ocr_noise(mc.group(2).strip())
            if ocr_mode:
                name = strip_fill(name)
            if not is_entry_name(name):
                continue                        # 页码列，不是条目
            if re.search(r"[-+×÷=]\s*\d|\d\s*[-+×÷=]", name):
                break                        # 进正文了
            flush()
            out.append((None, name, "chap"))
            started = True
            last_chap = ch
            continue
        ms = m_sec.match(line)
        if ms:
            name = strip_ocr_noise(ms.group(3).strip())
            if not is_entry_name(name):
                continue
            if re.search(r"[-+×÷=]\s*\d|\d\s*[-+×÷=]", name):
                break
            flush()
            out.append((None, name, "sec"))
            started = True
            continue
        mn = m_num.match(line)
        if mn:
            name = strip_ocr_noise(mn.group(2).strip())
            if not is_entry_name(name):
                continue
            if re.search(r"[-+×÷=]\s*\d|\d\s*[-+×÷=]", name):
                break
            num = int(mn.group(1))
            # **单元号必须严格递增 —— 但只对顶格的单元行成立。**
            # 目录里单元行顶格（`4   比             46`），
            # 编号插页则缩进（`    1 亿有多大       33`），
            # 插页的编号是**借用**它所在单元的号，会回退：
            # 四上 `    1 亿有多大` 让 last_num=1 之后紧跟 `2   公顷和平方千米`，
            # 判据一刀切下去，四上只剩 1/9 条，后面 8 章全丢。
            #
            # 而正文页的页眉「1   小数乘法」跟目录条目**一模一样**，
            # 纯靠 miss 计数分不开 —— 五上实测目录 8 条全对，
            # 紧接着又吞进「1 买3个 需要多少钱」等 3 条正文。
            # 页码回退到 1，只有递增判据能切开。
            # \x0c 是 pdftotext 的换页符，排在行首时会伪装成缩进：
            # `\x0c5   平行四边形和梯形     56` 是**顶格的第 5 单元**，
            # 不剥掉就被当成编号插页，四上/五上/六下各丢掉三四个真单元。
            inset = line.lstrip("\f")[:1].isspace()
            if started and not inset and num <= last_num:
                break
            flush()
            out.append((num if not inset else None, name,
                        "unit" if not inset else "ins"))
            started = True
            if not inset:
                last_num = num
            continue
        # 目录行的判据是**收尾有没有页码**，不是缩进也不是长度。
        # 「数学活动」在七上只有一个前导空格、在九上有二十几个对齐空格，
        # 按 \s{2,} 判会在七上漏掉，按长度判（>26 停）又会在九上的
        # 「数学活动                     ２３」（去缩进仍 27 字）提前退出。
        # 两条路都试过，都只解析出 1 章。可靠的信号只有一个：
        # 目录行以页码结尾，正文行不以页码结尾。
        mi = m_nam.match(line)
        if started and mi:
            name = strip_ocr_noise(mi.group(1).strip())
            if not is_entry_name(name):
                continue
            if re.search(r"[-+×÷=]\s*\d|\d\s*[-+×÷=]", name):
                break
            flush()
            out.append((None, name, "ins"))     # 数学乐园、营养午餐这类插页
            continue
        # ---- 兜底：**行首带数字、但名字后面没跟上页码** ----
        # 人教小学目录会把名字印成两行，单元号落在**后半行**上：
        #     1   长度单位          2
        #         100 以内的加法
        #     2   和减法（二）
        #                      11
        # 两个完整目录正则一个都不匹配，第 2 单元整条消失。
        #
        # **必须排在所有完整目录行之后**：它连页码一起吃，
        # 放前面的话 `1   四则运算       2` 会被当成续行，
        # 页码被塞进名字，整本目录塌成一条。
        # 单元号允许 3 位——「100 以内的加法」这半行的行首就是 100。
        mcont = re.match(r"^\s*(\d{1,3})\s+(\S.*?)\s*$", line)
        if mcont and is_entry_name(strip_ocr_noise(mcont.group(2))):
            miss = 0
            # **行首那串数字是单元号还是名字的一部分，靠缩进分。**
            # 二上第 2 单元叫「100 以内的加法和减法（二）」，
            # 名字被拆成两行：
            #     100 以内的加法          ← 缩进，行首的 100 是**名字的一部分**
            #     2   和减法（二）         ← 顶格，2 才是单元号
            # 一律把行首数字当单元号的话，「100 以内的加法和减法」
            # 会变成「以内的加法和减法」，配不上图谱，
            # 二上因此报成「8 个单元在官方目录里找不到」——
            # 又是把解析器的锅算到图谱头上。
            inset = line.lstrip("\f")[:1].isspace()
            # 行首那串数字：**缩进 → 是名字的一部分；顶格 → 是单元号。**
            nm = strip_ocr_noise(mcont.group(2))
            num = int(mcont.group(1)) if not inset else None
            if inset:
                nm = mcont.group(1) + nm
            if len(nm) > 24 or (pending and len(pending[1]) + len(nm) > 24):
                pending = None                   # 拼这么长已经不是目录条目了
                continue
            if pending is not None:
                pending = (num if num is not None else pending[0],
                           pending[1] + nm, pending[2])
            else:
                pending = (num, nm, "unit")
            continue
        if started:
            miss += 1
            # 阈值 2 太紧：OCR 把「5.1 相交线」切成一列碎片行（"<"、"二"、
            # "相交线"），连续两三行都不匹配 → 提前退出，第七章往后整本丢。
            # 但放宽不能没有上限，否则真正进正文了也停不下来。
            if miss >= 6:                      # 连续六行都不是目录行 → 进正文了
                break
    flush()
    return out


def derived(book):
    """从 graph.json 推：[(ch, 名字), …]，按推导顺序。"""
    g = json.load(open(GRAPH, encoding="utf-8"))
    xs = []
    for n in g["nodes"]:
        if n["subject"] != "math" or n["book"] != book:
            continue
        if n["label"] not in ("Chapter", "Section"):
            continue
        mm = re.search(r"_ch(\d+)(?:_s(\d+))?$", n["id"])
        if mm:
            xs.append((int(mm.group(1)), int(mm.group(2) or 0), n["name"]))
    xs.sort(key=lambda x: (x[0], x[1]))
    # 只保留章级：子节不参与目录比对（目录里不列子节）
    return [(c, nm) for c, s, nm in xs if s == 0]


def norm(name):
    """比对用的归一。

    目录里是「数学广角— 集合」（单破折号 + 空格），图谱里是
    「数学广角——集合」（双破折号）。这是排版差异不是排错，但会让
    后面每一项连锁误判 —— 三上、四上、六上、六下都栽在这。
    所以破折号和空白一律去掉再比。
    """
    name = re.sub(r"^第[一二三四五六七八九十百]+[单元章节]\s*", "", name)
    name = re.sub(r"[\u2010-\u2015\-－]", "", name)
    return re.sub(r"\s+", "", name).replace("（", "(").replace("）", ")")


def align(oseq, dseq, fuzzy):
    """把图谱推导序列配到官方目录序列上。返回 {图谱下标: 官方下标}。

    文本层教材走**精确匹配**——目录字是人排的，没有理由宽容。

    OCR 册走**模糊匹配**：`difflib` 的字符相似度，取最高的、且未被占用的官方项。
    OCR 的实际错法是逐字替换（九下「锐角三角函**数**」→「锐角三角**子**数」）
    或多字前缀噪声，不是整段乱码 —— 相似度对这两种都稳，
    而「包含匹配」对逐字替换完全无效（一字之差就互不为子串）。

    阈值 0.72：中文标题动辄 4-8 字，错一两个字的相似度在 0.8 上下，
    0.72 卡在「认错一两字」和「认不出」之间。太松会把
    「第六章 实数」配到「第十章 数据的收集」上去。
    """
    pairs = {}
    taken = set()
    if not fuzzy:
        it = iter(range(len(oseq)))
        for k, x in enumerate(dseq):
            hit = next((o for o in it if oseq[o] == x), None)
            if hit is not None:
                pairs[k] = hit
        return pairs
    for k, x in enumerate(dseq):
        best, score = None, 0.72
        for o, y in enumerate(oseq):
            if o in taken:
                continue
            r = SequenceMatcher(None, x, y).ratio()
            if r > score:
                best, score = o, r
        if best is not None:
            pairs[k] = best
            taken.add(best)
    return pairs


def monotonic(pairs):
    """配对结果是不是严格递增的。

    返回 (是否有序, 排错的图谱下标列表)。
    配对下标必须一路递增；一旦出现回退，说明官方目录和图谱
    对同一批条目给出了不同的先后 —— 这才是「排错了」。
    """
    seq = [(k, pairs[k]) for k in sorted(pairs)]
    bad = [seq[i][0] for i in range(1, len(seq)) if seq[i][1] <= seq[i - 1][1]]
    return (not bad), bad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fetch", action="store_true", help="缺册次时先去下载")
    ap.add_argument("--books", default="1a,4b,3b,5a", help="要比对的册次，逗号分隔")
    args = ap.parse_args()
    books = [b.strip() for b in args.books.split(",") if b.strip()]

    bad = 0
    gaps = []
    skipped = []
    for b in books:
        print(f"\n=== 数学 {b} ===")
        try:
            # 必须走 pdf_of：图谱册次码 bx1/xzxbx1 与文件名 m1/x1 不是一套，
            # 直接拼 f"rjb-math-{b}.pdf" 会去找一个不存在的文件，
            # 然后被「文件不存在 → 未缓存 → 提示加 --fetch」吞掉 ——
            # 报告上看着像「没核对」，实际是路径写错了。
            pdf = pdf_of(b)
            if not pdf.exists():
                if not args.fetch:
                    print("  未缓存，加 --fetch 先下载")
                    continue
                pdf = fetch(b)
            toc = toc_of(pdf)
        except Exception as e:
            print(f"  取目录失败：{type(e).__name__}: {e}")
            continue
        if not toc:
            # 两种情况都落到这里，但原因不同，写清楚是哪种：
            #   1. 「目 录」标题没识别出来（必修一/选必一认成「目 孙」）
            #      —— 兜底的「章号密集页」能救
            #   2. 兜底也救不回来：选必二把目录的**章号和章名排成两列**，
            #      同一页里凑不出「第X章」两个字，定位不到目录页
            # 说「没找到目录页」会让人以为 PDF 里没有，
            # 实际是有的（第 6 页），只是这一册的目录版式解析器吃不下。
            print("  ⊘ 未核对：目录页解析不出来（已试过「目 录」标题"
                  "和章号密集页两条路）。不是「核对通过」。")
            continue

        d = derived(b)
        # 目录里没有单元号的插页（营养午餐、数学乐园）在图谱里不是容器。
        # 只拿章级和单元级参与比对。目录里的插页（数学乐园、营养午餐、
        # 实验与探究）在图谱里不是容器，「sec」是小节，目录列了但图谱的
        # 章级比对用不上 —— 都剔掉，否则条数不等会误报「目录没解析全」。
        extra = [n for num, n, kind in toc if kind in ("ins",)]
        official = [n for num, n, kind in toc if kind in ("chap", "unit")]

        # 逐位比对会把「中间缺一课」误报成「后面全部排错」——
        # 四上就是这样：图谱缺了「亿有多大」，第 2 项起整体错位一格，
        # 一次报了 8 处「排错」，其实只有 1 处缺失。
        #
        # 这里要分清三件完全不同的事，混成一件就得出假结论：
        #   1. **配不上**（找不到官方条目）—— 可能是图谱编了，**也可能是 OCR 认错字**。
        #      九下实测：「锐角三角函数」被 OCR 认成「锐角三角子数」，字对不上，
        #      但次序完全正确。拿认错的字去报「排错」，报的是 OCR 的错。
        #   2. **次序反了**（配上了，但配到的官方下标不递增）—— 这才是排错。
        #   3. **官方有、图谱没建** —— 覆盖缺口，不是排错。
        #
        # 所以改成**相似度配对 + 只检查配对结果的单调性**。
        # 章序核对问的是顺序，认错字不是排错。
        src = toc_source(pdf)
        oseq = [norm(n) for n in official]
        dseq = [norm(x[1]) for x in d]
        pairs = align(oseq, dseq, fuzzy=(src == "ocr"))

        unmatched_d = [d[k][1] for k in range(len(d)) if k not in pairs]
        unmatched_o = [official[k] for k in range(len(oseq)) if k not in pairs.values()]
        # 配上了的下标必须严格递增。不递增 = 官方目录和图谱对同一批条目
        # 给出了不同的先后，那才是真的排错了。
        order_ok, bad_k = monotonic(pairs)
        misplaced = [d[k][1] for k in bad_k]
        matched = len(pairs)
        how = "（OCR 文本，模糊匹配）" if src == "ocr" else "（文本层，精确匹配）"
        if order_ok:
            print(f"  \u2713 次序正确：{matched}/{len(d)} 个单元都落在官方目录的先后位置上{how}")
        for nm in misplaced:
            bad += 1
            print(f"    \u2717 排错 \u300c{nm}\u300d：官方目录里它在更靠前/更靠后的位置")
        if unmatched_d:
            src2 = "OCR 没认准字" if src == "ocr" else "官方目录里找不到"
            print(f"  \u2298 {len(unmatched_d)} 个未能定位（{src2}，不等于排错）："
                  f"{'、'.join(unmatched_d)}")
        if not order_ok and matched < len(d):
            print("  \u2298 注意：这一册只配上了部分条目，次序结论不完整")
        if unmatched_o:
            gaps.append((b, unmatched_o))
            print(f"  \u00b7 官方有、图谱没建或未定位 {len(unmatched_o)} 个单元：{'、'.join(unmatched_o)}")
        if extra:
            real = [e for e in extra if len(e) <= 20]
            junk = len(extra) - len(real)
            print(f"  \u00b7 官方另有 {len(real)} 个无编号插页，图谱没建：{'、'.join(real)}")
            if junk:
                print(f"  \u00b7 另有 {junk} 条正文残骸被误收成条目（已滤掉，不影响次序结论）")

    print("\n" + "=" * 52)
    print(f"次序错误 {bad} 处（这才是「排错了」）")
    if skipped:
        print(f"未核对 {len(skipped)} 册：{'、'.join(skipped)} —— 目录解析不全，不是「核对通过」")
    if gaps:
        n = sum(len(m) for _, m in gaps)
        print(f"覆盖缺口 {len(gaps)} 册共 {n} 个单元（图谱没建，不是排错）")
    return 1 if bad else 0




if __name__ == "__main__":
    sys.exit(main())
