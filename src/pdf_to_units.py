#!/usr/bin/env python3
"""
把教材 PDF 转成**给 agent 用的结构化数据**。

## 为什么不是「把 PDF 抽成文本」

抽文本这条路对人眼够用、对 agent 不够：
OCR 的汉字占比只有 65% 左右，**公式和图形是不可恢复的**
（「S=ah」会被抽成「S一ah」，图直接没了）。

但有一件事是**可以做到高质量**的：
**图谱里已经有 8,590 个概念名和它们的教材位置** ——
拿这些名字当锚点，就能回答「教材在这个概念周围到底说了什么」。

所以产物不是「全文」，而是两层：

### ① `lessons.jsonl` —— 一页一条（教材的「课」）
```json
{"id":"math-9a-p102","book":"9a","page":102,"chapter":"第二十二章 二次函数",
 "section":"22.2 二次函数","text":"…这一页的正文…",
 "concepts":["二次函数","抛物线","顶点"],"quality":0.87,
 "hasFormula":true,"source":"rjb-math-9a.txt"}
```
agent 想读「第 22 章第 2 节这一课到底讲了什么」，读一条就行。

### ② `concept-text.jsonl` —— 一个概念一条（按概念索引）
```json
{"id":"math_9a_rjb_cpt7","name":"二次函数","subject":"math",
 "book":"9a","bookZh":"九上","chapter":"第二十二章 二次函数",
 "section":"22.2 二次函数","pages":[102,103,105],"mentions":7,
 "quotes":["二次函数的图象和性质","…"],
 "quality":0.87,"source":"rjb-math-9a.txt"}
```
agent 想写「二次函数的视频稿」，直接拿这条就有**教材原话 + 页码 + 第几节**。

## 三件事决定质量

1. **跑页眉**。教材每页页眉页脚都写着「第几章 / 第几页」——
   这是最可靠的定位信号，比目录可靠（目录在扫描件里经常是图形化的）。
2. **概念匹配分级**。精确命中 1.0；「二次函数的图象」这种带修饰的 0.85；
   模糊匹配 ≥0.85 相似度才算 0.6。**匹配不上的宁可没有**。
3. **逐页质量分**。汉字占比 + 噪声模式命中数。
   质量太低的页标出来，agent 可以自己决定要不要信。

## 跑法

```bash
python3 src/pdf_to_units.py                      # 全部已缓存教材
python3 src/pdf_to_units.py --books 7b,9a       # 只跑某几册
python3 src/pdf_to_units.py --out data          # 写到别处
```
"""
import argparse
import collections
import difflib
import glob
import json
import pathlib
import re
import sys

BASE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

CACHE = BASE / "data" / "pdf-cache"
GRAPH = BASE / "data" / "normalized" / "graph.json"

# ── 排版规范化（跟 extract_editions.py 同一套，抄一份是因为这里不 import 它）──
PRIVATE = re.compile("[-]")
FULLWIDTH = str.maketrans("０１２３４５６７８９．，：；（）",
                           "0123456789.,:;()")
# 教材页眉：「30 第五章 相交线与平行线」/「第五章 相交线与平行线 31」
RE_HEAD = re.compile(r"(?:^|\n)\s*([0-9]{1,3})?\s*[“”\"'‘’]?\s*"
                     r"第([一二三四五六七八九十]{1,3})章[””\"'‘’\s]*"
                     r"([^\n]{2,24}?)\s*(?:[0-9]{1,3})?\s*(?:\n|$)")
RE_SENT = re.compile(r"[^。！？；!?;\n]+[。！？；!?;]?")
# 明确的 OCR 垃圾模式：替换符、汉字夹 ASCII、连续标点
RE_NOISE = re.compile(
    r"[�□▪￼]"                       # 替换符
    r"|[一-鿿][\"''\u2018\u2019]{1,3}"     # 汉字夹单双引号（多半是图形标注）
    r"|[一-鿿]{1,2}[A-Za-z]{3,}"            # 汉字后跟长串拉丁
    r"|[A-Za-z]{2,}[一-鿿]{1,2}"            # 拉丁后跟汉字
)

# **文件名里的学科前缀 → 图谱里的学科名**。
# 文件叫 rjb-bio-7a，图谱里学科是 "biology"；rjb-chem → "chemistry"；
# rjb-phys → "physics"。不映射的话这三个学科的概念**一条都进不来**
# —— 症状是「只有数学有数据」，而且不报错。
SUBJMAP = {"math": "math", "bio": "biology", "chem": "chemistry",
           "phys": "physics"}

# 册次码 → (学科, 显示名)
BOOKMETA = {
    "1a": ("数学", "一上"), "1b": ("数学", "一下"), "2a": ("数学", "二上"),
    "2b": ("数学", "二下"), "3a": ("数学", "三上"), "3b": ("数学", "三下"),
    "4a": ("数学", "四上"), "4b": ("数学", "四下"), "5a": ("数学", "五上"),
    "5b": ("数学", "五下"), "6a": ("数学", "六上"), "6b": ("数学", "六下"),
    "7a": ("数学", "七上"), "7b": ("数学", "七下"), "8a": ("数学", "八上"),
    "8b": ("数学", "八下"), "9a": ("数学", "九上"), "9b": ("数学", "九下"),
    "m1": ("数学", "必修一"), "m2": ("数学", "必修二"),
    "x1": ("数学", "选必一"), "x2": ("数学", "选必二"), "x3": ("数学", "选必三"),
    "phys-8a": ("物理", "八上"), "phys-8b": ("物理", "八下"),
    "chem-9a": ("化学", "九上"), "chem-9b": ("化学", "九下"),
    "bio-7a": ("生物", "七上"), "bio-7b": ("生物", "七下"),
    "bio-8a": ("生物", "八上"), "bio-8b": ("生物", "八下"),
}


def norm(t):
    """排版规范化：全角数字、私用区字符、空白。"""
    t = PRIVATE.sub("", t)
    t = t.translate(FULLWIDTH)
    t = t.replace("　", " ")
    return t


def pages_of(path):
    """→ [(页码, 原文)]。两种分页标记都认。"""
    t = path.read_text(encoding="utf-8", errors="replace")
    out = []
    if "<<<PAGE" in t:
        parts = re.split(r"<<<PAGE (\d+)>>>", t)
        for i in range(1, len(parts) - 1, 2):
            out.append((int(parts[i]), parts[i + 1]))
    elif "\x0c" in t:
        for i, pg in enumerate(t.split("\x0c"), 1):
            out.append((i, pg))
    else:
        out.append((1, t))
    return out


def quality(text):
    """一页的质量分（0~1）。

    **原来用「汉字占比」当主项 —— 对数学教材不公平。**
    数学书里公式、字母、图注本来就该是拉丁字符，
    汉字占比只有 65% 不代表这页烂；反过来，
    一页全是「民1 HG」「谊曲的小路」也不该拿「汉字多」蒙混过关。

    改成**噪声率**：只数明确的垃圾模式（替换符、私用区、
    汉字夹 ASCII 乱码），噪声越少分越高。
    汉字占比另算一个字段 `cjkRatio`，给需要的人参考。
    """
    c = re.sub(r"\s", "", text)
    if not c:
        return 0.0
    noise = len(RE_NOISE.findall(c))
    return max(0.0, min(1.0, 1.0 - noise * 0.02))


def cjk_ratio(text):
    c = re.sub(r"\s", "", text)
    if not c:
        return 0.0
    return sum(1 for ch in c if "一" <= ch <= "鿿") / len(c)


def running_head(text):
    """从页眉页脚里认出「第几章」。返回 (章号, 章名) 或 None。

    教材每页页眉都写着章名，这是**最可靠的定位信号** ——
    比目录可靠（目录在扫描件里常常是图形化的，OCR 抽不出来）。
    """
    best = None
    for m in RE_HEAD.finditer(text):
        num, name = m.group(2), re.sub(r"\s+", "", m.group(3))
        # 章名里的标点是 OCR 噪声（「第五章 ,”相交线与平行线」）
        name = re.sub(r"[^一-鿿0-9A-Za-z、（）()·]", "", name)
        name = re.sub(r"[“”\"'‘’·\.]+$", "", name)
        if 2 <= len(name) <= 24:
            best = (num, name)
    return best


def sentences(text):
    out = []
    for s in RE_SENT.findall(text):
        s = re.sub(r"\s+", "", s)
        s = re.sub(r"^[0-9．.、]+\s*", "", s)
        if len(s) >= 6:
            out.append(s)
    return out


def build_concept_index():
    """概念名 → (id, 名, 学科, 册次码, 显示册次)。

    **只收能当锚点的名字**：太短的名字（1 个字）会在正文里到处出现，
    拿它做锚点会把整本书都标成它的正文。
    """
    g = json.load(open(GRAPH, encoding="utf-8"))
    idx = {}
    for n in g["nodes"]:
        if n.get("label") not in ("Concept", "Skill", "Experiment"):
            continue
        nm = (n.get("name") or "").strip()
        if len(nm) < 3 or len(nm) > 24:
            continue
        idx.setdefault(nm, []).append(
            (n["id"], nm, n.get("subject"), n.get("book"), n.get("bookZh")))
        # **括号注释要去掉再索引一份**：
        # 上游的概念名大量带括号（「营养（生物的生活需要营养）」
        # 「呼吸（生物能进行呼吸）」），教材里只写「营养」「呼吸」——
        # 不去掉括号，生物化学的概念**一条都精确匹配不上**。
        core = re.sub(r"[（(][^）)]*[）)]", "", nm).strip()
        if len(core) >= 2 and core != nm:
            idx.setdefault(core, []).append(
                (n["id"], nm, n.get("subject"), n.get("book"), n.get("bookZh")))
    return idx


# 引文分类：写视频稿最有用的是**定义句**
RE_DEF = re.compile(r"(叫做|称为|是指|指的是|定义为|就是|即为|全称是|通常指)")
RE_THM = re.compile(r"(定理|性质|公式|定律|公理|推论|法则|原理|结论)")
RE_EX = re.compile(r"^(例[0-9０-９一二三四五六七八九十]*[：:.、]|例题|如图|下图|上图中)")
RE_ASK = re.compile(r"[?？]$")


def quote_kind(s, concept):
    """一句引文的类型。**定义句最值钱** —— 视频稿要的就是这个。

    「叫做…」「是指…」这种是教材在**下定义**，
    写成稿子基本可以直接引用；定理句次之；
    例题和习题里的句子对「卡在哪」这个诊断没用。
    """
    s = s.strip()
    # 整句就是概念名 → 那是标题/目录项，不是正文
    if re.sub(r"[\s。．.、，,：:；;\u3000]", "", s) == \
            re.sub(r"[\s。．.、，,：:；;\u3000]", "", concept or ""):
        return "title"
    if RE_DEF.search(s):
        return "definition"
    if RE_THM.search(s):
        return "theorem"
    if RE_EX.match(s):
        return "example"
    if RE_ASK.search(s):
        return "question"
    return "text"


KIND_RANK = {"definition": 0, "theorem": 1, "text": 2, "example": 3,
             "question": 4, "title": 5}


def bigrams(s):
    s = re.sub(r"[^一-鿿A-Za-z0-9]", "", s)
    return {s[i:i + 2] for i in range(len(s) - 1)} or {s}


def fuzzy_concepts(cidx, lessons_by_book, min_ratio=0.72):
    """模糊匹配：概念名在教材里**字面找不到**时，找最像的句子。

    为什么需要这一层：上游的概念名多是**改写过的**
    （「三角形的内角和」vs 教材的「三角形三个内角的和等于180°」），
    精确匹配只能覆盖 4.6% 的概念。

    怎么做才不慢：给每本书的每个句子建**二元字组倒排索引**，
    查概念时只用**最罕见的几个字组**定位候选句，
    再对候选句算相似度。整库 23 册跑完是秒级。

    **匹配不上的宁可没有** —— 相似度不到阈值就标 unmatched，
    不硬凑（跟多版本教材对照一个原则）。
    """
    # 倒排：字组 → 句子列表
    inv = collections.defaultdict(list)
    for (bk, pgno), sents in lessons_by_book.items():
        for si, s in enumerate(sents):
            for g in bigrams(s):
                inv[g].append((bk, pgno, si, s))
    df = {g: len(v) for g, v in inv.items()}

    out = {}
    for nm, entries in cidx.items():
        gs = sorted(bigrams(nm), key=lambda g: df.get(g, 0))
        cand = collections.Counter()
        for g in gs[:3]:
            for key in inv.get(g, ()):
                cand[key] += 1
        best = None
        for (bk, pgno, si, s), _n in cand.most_common(120):
            r = difflib.SequenceMatcher(None, nm, s).ratio()
            if best is None or r > best[0]:
                best = (r, bk, pgno, si, s)
        if best and best[0] >= min_ratio:
            out[nm] = {"ratio": round(best[0], 3), "book": best[1],
                       "page": best[2], "sentence": best[4]}
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--books", help="只跑某几册（学科-册次 或 册次，逗号分隔，如 math-7b,9a）")
    ap.add_argument("--out", default="data")
    args = ap.parse_args()

    outdir = BASE / args.out
    outdir.mkdir(parents=True, exist_ok=True)
    cidx = build_concept_index()
    # 长名优先匹配：「二次函数的图象」比「二次函数」更具体
    names = sorted(cidx.keys(), key=len, reverse=True)

    lessons = []
    sent_by_page = {}          # (key, pgno) → [句子]，供模糊匹配用
    ctext = collections.defaultdict(lambda: {
        "pages": [], "quotes": [], "kinds": [], "mentions": 0, "quality": [],
        "chapters": set(), "meta": None})

    # **同一册可能有两份文本**（.txt 文本层 + .ocr.txt OCR）——
    # 全都跑一遍会把每页出两遍，id 还一样（页码不同但内容重复）。
    # 按 (学科, 册) 只留**内容最多的**那一份。
    cand = collections.defaultdict(list)
    for f in sorted(glob.glob(str(CACHE / "rjb-*.txt")) +
                    glob.glob(str(CACHE / "rjb-*.ocr.txt"))):
        stem = pathlib.Path(f).stem[4:]
        if stem.endswith(".ocr"):
            stem = stem[:-4]
        fsubj, _, bk = stem.partition("-")
        if bk:
            cand[(SUBJMAP.get(fsubj, fsubj), bk)].append(pathlib.Path(f))
    files = []
    altmeta = {}
    for k in sorted(cand):
        best = max(cand[k], key=lambda p: len(re.sub(r"\s", "", p.read_text(
            encoding="utf-8", errors="replace"))))
        files.append(str(best))
    # **其他出版社的教材**（data/pdf-cache/alt/<出版社>/<册次>.pdf）。
    # 有文本层的直接读，扫描件要 OCR —— 这里先只收有文本层的，
    # 扫描件等 OCR 完再补（OCR 完会生成同名 .txt，同样走这条路）。
    for pdf in sorted(glob.glob(str(CACHE / "alt" / "*" / "*.pdf"))):
        stem = pathlib.Path(pdf).stem
        fsubj, _, bk = stem.partition("-")
        if not bk:
            fsubj, _, bk = "math", "", stem
        pub = pathlib.Path(pdf).parent.name
        if not bk:
            bk = stem
        subj = SUBJMAP.get(fsubj, fsubj)
        key = f"{pub}-{subj}-{bk}"
        cand2 = CACHE / "alt" / pub / f"{bk}.txt"
        if not cand2.exists():
            continue                      # 扫描件：等 OCR
        files.append(str(cand2))
        altmeta[key] = {"publisher": pub, "subject": subj, "book": bk}
    for f in files:
        # 文件名 rjb-math-7b.ocr.txt → 学科 math、册次码 7b
        # **册次码不能带学科前缀** —— BOOKMETA 的键是 "7b" 这种，
        # 写成 "math-7b" 就一个都对不上（跑出来 0 页还不报错）。
        stem = pathlib.Path(f).stem
        is_alt = "/alt/" in str(f)
        if stem.startswith("rjb-"):
            stem = stem[4:]
        if stem.endswith(".ocr"):
            stem = stem[:-4]
        if is_alt:
            # alt 的文件名是「七上」「必修一」这种，没有学科前缀
            pub = pathlib.Path(f).parent.name
            bk = stem
            subj = "math"
            key = f"{pub}-{subj}-{bk}"
        else:
            fsubj, _, bk = stem.partition("-")
            subj = SUBJMAP.get(fsubj, fsubj)
            if not bk:
                continue
            key = f"{subj}-{bk}"
        # **册次码跨学科复用**（7a 既是数学七上、也是生物七上、还是物理八上）——
        # 只按册次筛会同时命中数学七下和生物七下，
        # 而且两者的页 id 都是「7b-p1」，**直接撞 id**。
        # 键和 id 一律用 (学科, 册次)；其他出版社再加上出版社名。
        if args.books and key not in args.books.split(",") \
                and bk not in args.books.split(","):
            continue
        for pgno, raw in pages_of(pathlib.Path(f)):
            t = norm(raw)
            q = quality(raw)
            head = running_head(t)
            chapter = f"第{head[0]}章 {head[1]}" if head else ""
            # **目录页不算正文**：目录里概念名全都会「出现」一次，
            # 但那是目录，不是教材在讲它。
            #
            # 判据不能靠点线引导 —— **OCR 把「……」整个丢了**
            # （人教七下的目录页 p5 里一个点都没有）。
            # 改用「**每行都以页码结尾**」：目录的每一行是「条目 + 页码」，
            # 正文没有这个特征。
            _lines = [l.strip() for l in t.split("\n") if l.strip()]
            _pg = [l for l in _lines if re.search(r"[0-9]{1,3}\s*$", l) and len(l) <= 32]
            is_toc = (len(_lines) >= 8 and len(_pg) >= 0.45 * len(_lines))
            sents = [] if is_toc else sentences(t)
            # 这一页出现了哪些概念
            hits = []
            joined = "\n".join(sents)
            for nm in names:
                if nm in joined:
                    hits.append(nm)
            # 只留这一页**最具体**的命中（避免「二次函数」和「二次函数的图象」同时算）
            keep = []
            for nm in hits:
                if not any(nm != o and nm in o for o in hits):
                    keep.append(nm)
            sent_by_page[(key, pgno)] = sents
            lessons.append({
                "id": f"{key}-p{pgno}",
                "book": bk, "subject": subj, "page": pgno,
                "chapter": chapter,
                "text": joined[:4000],
                "sentences": len(sents),
                "concepts": keep[:40],
                "quality": round(q, 3),
                "cjkRatio": round(cjk_ratio(raw), 3),
                "isToc": is_toc,
                "source": pathlib.Path(f).name,
            })
            # 概念 → 教材原话
            for nm in keep:
                for cid, name, csubj, book, bookZh in cidx[nm]:
                    if book != bk or csubj != subj:
                        continue
                    c = ctext[cid]
                    if c["meta"] is None:
                        c["meta"] = (cid, nm, csubj, book, bookZh,
                                     pathlib.Path(f).name)
                    c["mentions"] += 1
                    if pgno not in c["pages"]:
                        c["pages"].append(pgno)
                    if chapter:
                        c["chapters"].add(chapter)
                    c["quality"].append(q)
                    # 摘含它的句子 —— **带类型**，定义句优先
                    for s in sents:
                        if nm not in s:
                            continue
                        if s in c["quotes"]:
                            continue
                        k = quote_kind(s, nm)
                        if k == "title":
                            continue          # 只是标题，信息量为零
                        # **超长的句子要截断保留** ——
                        # 原来用 `len(s) <= 120` 直接丢掉，
                        # 结果 40 个概念「页面上找到了、但一条原话都没有」。
                        c["quotes"].append(s[:120])
                        c["kinds"].append(k)
                        if len(c["quotes"]) >= 24:
                            break
            if len(lessons) % 500 == 0:
                print(f"  {len(lessons)} 页…", flush=True)

    # ── 模糊匹配：精确匹配不到的概念，用字组倒排找最像的句子 ──
    exact_ids = set(ctext.keys())
    todo = {}
    for nm, entries in cidx.items():
        if any(cid in exact_ids for cid, *_ in entries):
            continue
        todo[nm] = entries
    print(f"  精确匹配 {len(exact_ids)} 个，剩 {len(todo)} 个走模糊匹配…", flush=True)
    # 只在同一学科同一册里找
    by_book = collections.defaultdict(list)
    for nm, entries in todo.items():
        for cid, name, subj, book, bookZh in entries:
            by_book[(subj, book)].append((nm, cid, name, subj, book, bookZh))
    fuzz = {}
    for (subj, book), items in by_book.items():
        sub = {k: v for k, v in sent_by_page.items() if k[0] == f"{subj}-{book}"}
        if not sub:
            continue
        got = fuzzy_concepts({nm: [(cid, nm, subj, book, bookZh)]
                              for nm, cid, name, s, b, bz in items}, sub)
        for nm, m in got.items():
            fuzz[nm] = m
    print(f"  模糊匹配命中 {len(fuzz)} 个", flush=True)
    # 把模糊命中也写进概念索引
    for nm, m in fuzz.items():
        for cid, name, subj, book, bookZh in cidx[nm]:
            # fuzzy_concepts 是**按 (学科, 册) 分组**调用的，
            # 命中结果天然同册 —— 这里不能再拿 m["book"]（"math-7b" 这种
            # 组合码）去比图谱的册次码（"7b"），比不上就全被丢掉。
            if f"{subj}-{book}" != m["book"]:
                continue
            c = ctext[cid]
            if c["meta"] is None:
                c["meta"] = (cid, nm, subj, book, bookZh, "")
            c["mentions"] += 1
            if m["page"] not in c["pages"]:
                c["pages"].append(m["page"])
            c["quality"].append(0.8)      # 模糊命中，质量打个折
            if m["sentence"] not in c["quotes"] and len(c["quotes"]) < 24:
                c["quotes"].append(m["sentence"])
                c["kinds"].append(quote_kind(m["sentence"], nm))
            c["fuzzy"] = m["ratio"]

    # 写产物
    lp = outdir / "lessons.jsonl"
    with open(lp, "w", encoding="utf-8") as fh:
        for r in lessons:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    cp = outdir / "concept-text.jsonl"
    n_c = 0
    with open(cp, "w", encoding="utf-8") as fh:
        for cid, c in ctext.items():
            meta = c["meta"]
            fh.write(json.dumps({
                "id": cid,
                "name": meta[1],
                "subject": meta[2],
                "book": meta[3],
                "bookZh": meta[4],
                "chapter": sorted(c["chapters"])[0] if c["chapters"] else "",
                "pages": sorted(c["pages"]),
                "mentions": c["mentions"],
                "quotes": [q for _, q in sorted(
                    zip(c["kinds"], c["quotes"]),
                    key=lambda kq: (KIND_RANK.get(kq[0], 9), -len(kq[1])))][:10],
                "quoteKinds": [k for k, _ in sorted(
                    zip(c["kinds"], c["quotes"]),
                    key=lambda kq: (KIND_RANK.get(kq[0], 9), -len(kq[1])))][:10],
                "hasDefinition": any(k == "definition" for k in c["kinds"]),
                "quality": (round(sum(c["quality"]) / len(c["quality"]), 3)
                           if c["quality"] else 0),
                "match": "fuzzy" if c.get("fuzzy") else "exact",
                "source": meta[5],
            }, ensure_ascii=False) + "\n")
            n_c += 1
    print(f"\nlessons.jsonl       {len(lessons)} 页")
    print(f"concept-text.jsonl  {n_c} 个概念（拿到了教材原话）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
