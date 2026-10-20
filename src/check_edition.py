#!/usr/bin/env python3
"""
查：图谱里的章号，跟我们手上的教材 PDF 对不对得上版本。

## 为什么要有这个

人教版 2024 年做了修订，**七年级下册大改**：旧版
```
第五章 相交线与平行线  第六章 实数  第七章 平面直角坐标系 …
```
现行版把「相交线与平行线」挪到了第七章，中间插入了新章节。

K12-KGraph 用的是**旧版章号**（它的 Chapter 节点写的是「第五章 相交线与平行线」）。
我们从 ChinaTextbook 下的七下 PDF **恰好也是旧版**，
所以 `verify_order.py` 报「0 处排错」—— **自洽，但不代表跟现行教材一致**。

**这不是数据错误**：知识点本身没变，只是挪了位置。
但页面上写着「七上·概念」，用户拿现行教材对的时候会对不上。

## 查法

对每册：把图谱的 Chapter 节点（按 id 里的 ch 号排序）跟 PDF 目录里
读到的章号+章名逐条比。章**名**对得上就说明版本一致。

## 跑法

```bash
python3 src/check_edition.py
```
"""
import json
import pathlib
import re
import sys
from collections import defaultdict

BASE = pathlib.Path(__file__).resolve().parent.parent
CACHE = BASE / "data" / "pdf-cache"
GRAPH = BASE / "data" / "normalized" / "graph.json"

FILE = {"bx1": "m1", "bx2": "m2",
        "xzxbx1": "x1", "xzxbx2": "x2", "xzxbx3": "x3"}
CN = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6,
      "七": 7, "八": 8, "九": 9, "十": 10, "十一": 11, "十二": 12}


def chap_name_of_pdf(pdf):
    """从 PDF 文本层 / OCR 里抽出「第X章 名」的列表。"""
    txt = pdf.with_suffix(".txt")
    if not (txt.exists() and txt.stat().st_size > 20000):
        txt = pdf.with_suffix(".ocr.txt")
    if not (txt.exists() and txt.stat().st_size > 20000):
        return None
    t = txt.read_text(encoding="utf-8", errors="replace")
    out, seen = [], set()
    # 小学教材用「第一单元」，初中高中用「第一章」—— 两种都要认。
    for m in re.finditer(
            r"第([一二三四五六七八九十]+)([章单元])\s*[\"“”'\s]*([^\s\n，,。]{2,16})", t):
        num = CN.get(m.group(1))
        if not num or num in seen:
            continue
        seen.add(num)
        name = re.sub(r'^[\s"“”\'、,，。]+', "", m.group(3)).strip()
        out.append((num, name))
    return out


def main():
    g = json.load(open(GRAPH, encoding="utf-8"))
    # **必须限定 subject="math"。**
    # `book` 字段在学科间是**复用**的：「7a」既是数学七年级上册、
    # 也是生物七年级上册、也是物理八年级上册（8a）。
    # 不限定学科的话，生物的「第一单元 生物和生物圈」会被当成
    # 数学的第一章去比教材 —— 比出来的「版本不同」全是假的。
    chaps = defaultdict(list)
    for n in g["nodes"]:
        if n["label"] != "Chapter" or n.get("subject") != "math":
            continue
        m = re.search(r"_ch(\d+)$", n["id"])
        if m:
            chaps[n.get("book", "")].append((int(m.group(1)), n["name"]))

    print(f"{'册':<6}{'图谱章':>7}{'教材章':>7}  判定")
    print("-" * 66)
    same = diff = unknown = 0
    for bk in sorted(chaps):
        pdf = CACHE / f"rjb-math-{FILE.get(bk, bk)}.pdf"
        if not pdf.exists():
            print(f"{bk:<6}{len(chaps[bk]):>7}{'-':>7}  没有 PDF")
            unknown += 1
            continue
        pdfc = chap_name_of_pdf(pdf)
        if not pdfc:
            print(f"{bk:<6}{len(chaps[bk]):>7}{'-':>7}  PDF 读不出章名")
            unknown += 1
            continue
        gmap = {num: re.sub(r"^第[一二三四五六七八九十]+章\s*", "", nm).strip()
                for num, nm in chaps[bk]}
        pmap = {num: re.sub(r'^[\s"“”]+', "", nm).strip() for num, nm in pdfc}
        # **比章号序列 + 章名抽查。**
        # 只比名字不稳：PDF 里正文也会出现「第X章」，
        # 抓到的可能是一句话（实测「通过上一章的学习可知」）。
        # 章号序列是硬的：教材有几章、每章是第几。
        mism = []
        gseq = sorted(gmap)
        pseq = sorted(pmap)
        if gseq != pseq:
            mism.append(f"章号序列 图谱{gseq} / 教材{pseq}")
        else:
            for num in gseq:
                gname, pname = gmap[num], pmap.get(num, "")
                if pname and gname[:3] != pname[:3]:
                    mism.append(f"第{num}章 图谱「{gname}」/教材「{pname}」")
        if mism:
            print(f"{bk:<6}{len(gmap):>7}{len(pmap):>7}  ✗ 版本不同：{'；'.join(mism[:3])}")
            diff += 1
        else:
            print(f"{bk:<6}{len(gmap):>7}{len(pmap):>7}  ✓ 章名章号全对")
            same += 1
    print("-" * 66)
    print(f"版本一致 {same} 册，版本不同 {diff} 册，读不出 {unknown} 册")
    return 0


if __name__ == "__main__":
    sys.exit(main())
