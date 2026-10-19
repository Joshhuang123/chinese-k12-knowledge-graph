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

## 已核对的结论（2026-10-19 实测，12 册小学数学全跑）

```
次序错误 0 处（这才是「排错了」）
未核对 1 册：2a —— 目录解析不全，不是「核对通过」
覆盖缺口 3 册共 4 个单元（图谱没建，不是排错）
```

| 册次 | 结果 |
|---|---|
| 一上 / 一下 / 二下 / 三上 / 三下 | ✓ 次序完全一致 |
| 四上 / 四下 / 五上 / 五下 / 六上 / 六下 | ✓ 次序完全一致 |
| 二上 | ⊘ **未核对**：第 2 条单元名跨三行，正则吃不下，解析不全 |
| 四上 | · 官方有「亿有多大」，图谱没建 |
| 四下 | · 官方有「数学广角—鸡兔同笼」「总复习」，图谱没建 |
| 五下 | · 官方有「总复习」，图谱没建 |

另有多册存在无编号插页（数学乐园、营养午餐、数字编码、掷一掷…），
图谱一律没建 —— 那些是教材里的选做页，不是教学单元，不该混进顺序链。

**两处曾经误判、后来查清的原因**：

1. **小学数学一上的目录里「认识图形（一）」确实排在「6~10 的认识和加减法」之前。**
   我按旧版教材的印象以为反了，拉 2022 年 8 月第 2 版的官方 PDF 一对，
   是对的 —— 现行版就是这个次序。**我记错了，不是数据错了。**
2. **四上一度报「8 处排错」**，其实是图谱缺了「亿有多大」导致整体错位一格。
   判据从「逐位比对」改成「是不是官方目录的子序列」之后，
   缺一课和排错序才分得开。

"""
import argparse
import json
import pathlib
import re
import subprocess
import sys
import urllib.parse
import urllib.request

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
    if not txt.exists():
        # stderr 全是 Marked Content 之类的告警，人教 PDF 结构特殊，
        # 不影响出字，直接丢掉。
        subprocess.run(["pdftotext", "-layout", str(pdf), str(txt)],
                       check=True, stderr=subprocess.DEVNULL)
    t = txt.read_text(encoding="utf-8", errors="replace")
    # 标题是「目   录」，空格数量不固定（实测三个），不能写死
    m = re.search(r"目\s{2,}录", t)
    if not m:
        return None
    seg = t[m.end(): m.end() + 2000]

    out, started = [], False
    for line in seg.split("\n"):
        if not line.strip():
            continue
        mnum = re.match(r"\s*(\d{1,2})\s+(\S.*?)\s*\.{0,}\s*(\d{1,3})\s*$", line)
        mnam = re.match(r"\s{2,}(\S.*?)\s*\.{0,}\s*(\d{1,3})\s*$", line)
        if mnum:
            name = mnum.group(2).strip()
            if re.search(r"[-+×÷=]\s*\d|\d\s*[-+×÷=]", name):
                break                        # 进正文了
            out.append((int(mnum.group(1)), name))
            started = True
        elif started and mnam:
            name = mnam.group(1).strip()
            if re.search(r"[-+×÷=]\s*\d|\d\s*[-+×÷=]", name):
                break
            out.append((None, name))          # 数学乐园、营养午餐这类插页
        elif started:
            break                              # 目录断了，后面是正文
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
            pdf = CACHE / f"rjb-math-{b}.pdf"
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
            print("  PDF 里没找到目录页，跳过（不是「核对通过」）")
            continue

        d = derived(b)
        # 目录里没有单元号的插页（营养午餐、数学乐园）在图谱里不是容器。
        extra = [n for num, n in toc if num is None]
        official = [n for num, n in toc if num is not None]

        # **官方条目数比推导数还少 → 目录根本没解析全，这一册是「未核对」
        # 而不是「排错」。** 二上第 2 条的名字跨了三行，正则吃不下，
        # 后面 8 条就连锁报成「在官方目录里找不到」。
        # 拿一份没读全的目录去判别人的次序，结论是假的。
        # 宁可报「未核对」也不报「排错」——误报会被看见，
        # 把没核对说成核对通过才是真的害人。
        if len(official) < len(d):
            skipped.append(b)
            print(f"  \u2298 未核对：目录只解析出 {len(official)} 条，少于图谱的 {len(d)} 个，解析不全")
            continue

        # 逐位比对会把「中间缺一课」误报成「后面全部排错」——
        # 四上就是这样：图谱缺了「亿有多大」，第 2 项起整体错位一格，
        # 一次报了 8 处「排错」，其实只有 1 处缺失。
        # 判据改成：推导结果是不是官方目录的**子序列**。
        # 是 → 次序对，缺的那些是覆盖缺口；不是 → 才叫排错。
        oseq = [norm(n) for n in official]
        dseq = [norm(x[1]) for x in d]
        missing = [official[k] for k in range(len(oseq)) if oseq[k] not in set(dseq)]
        it = iter(range(len(oseq)))
        misplaced = []
        for k, x in enumerate(dseq):
            hit = next((o for o in it if oseq[o] == x), None)
            if hit is None:
                misplaced.append(d[k][1])
        if not misplaced:
            print(f"  \u2713 次序正确：{len(d)} 个单元都在官方目录的先后位置上")
        for nm in misplaced:
            bad += 1
            print(f"    \u2717 排错 \u300c{nm}\u300d：在官方目录里找不到，或位置不对")
        if missing:
            gaps.append((b, missing))
            print(f"  \u00b7 官方有、图谱没建 {len(missing)} 个单元：{'、'.join(missing)}")
        if extra:
            print(f"  \u00b7 官方另有 {len(extra)} 个无编号插页，图谱没建：{'、'.join(extra)}")

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
