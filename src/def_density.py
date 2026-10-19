#!/usr/bin/env python3
"""
统计任意教材 PDF 里的**定义句密度** —— 用来把 ISSUE-10 推广到非数学。

## 为什么单独写一个

ISSUE-10 的核心数字是「教材里有多少定义句」：
数学 12 册小学加起来只有 15 处「叫做/称为/统称」，而上游给了 782 个知识点 ——
比值 0.02。这个数字说明**上游那些 definition 不是从人教版抄的**。

但那个结论只验过数学教材。**如果化学、生物的教材里定义句密度也低，
那就不是「数学特殊」，而是上游数据集的普遍性质** —— 结论的强度完全不同。

所以这里做的是**跨学科的密度统计**，不比对具体定义文本
（那是 check_definitions.py 的活，它要跟图谱里的 definition 对撞）。

## 怎么算

定义句 = 含「叫做 / 称为 / 统称 / 合称 / 定义为」的句子。

两个坑（check_definitions.py 已经踩平，这里复用）：

1. **目录页要剔掉。** 目录里也有「1.3 有理数的加减法」这种带术语的行，
   不剔会把密度算高。
2. **中文 PDF 的标点是全角的**，还有 NFKC 归一化要处理。

## 跑法

```bash
python3 src/def_density.py data/pdf-cache/rjb-chem-9a.pdf data/pdf-cache/rjb-bio-7a.pdf
```
"""
import pathlib
import re
import subprocess
import sys
import unicodedata

# 定义句的判断词
DEFS = ("叫做", "称为", "统称", "合称", "定义为", "叫做的")


def nfkc(t):
    return unicodedata.normalize("NFKC", t or "")


def text_of(pdf):
    """PDF → 正文文本。优先文本层，没有就 OCR。"""
    txt = pdf.with_suffix(".txt")
    if not (txt.exists() and txt.stat().st_size > 20000):
        ocr = pdf.with_suffix(".ocr.txt")
        if ocr.exists() and ocr.stat().st_size > 20000:
            txt = ocr
        else:
            subprocess.run(["pdftotext", "-layout", str(pdf), str(txt)],
                           check=True, stderr=subprocess.DEVNULL)
    return txt.read_text(encoding="utf-8", errors="replace")


def drop_toc(text):
    """剔掉目录页。复用 check_definitions.py 的判据。"""
    lines = text.split("\n")
    # 找「目录」标题；找不到就用「连续多行像目录行」来切
    start = None
    for i, l in enumerate(lines):
        if re.search(r"目\s{1,3}录", l):
            start = i
            break
    if start is not None:
        # 目录通常 1-3 页，往后找正文第一个「章」标题
        for j in range(start + 1, min(start + 400, len(lines))):
            if re.search(r"第[一二三四五六七八九十]{1,3}[章单元]\s*\S", lines[j]):
                start = j
                break
    body = lines[start:] if start is not None else lines
    return "".join(l.strip() for l in body)


def count_defs(text):
    """定义句数量。按句号/分号切句。"""
    t = nfkc(text)
    # 中文标点在这一步都已变半角（NFKC）
    sents = re.split(r"[。;!?\n]+", t)
    out = []
    for s in sents:
        s = s.strip()
        if 4 <= len(s) <= 120 and any(d in s for d in DEFS):
            out.append(s)
    return out


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return 1
    print(f"{'文件':<34}{'页':>5}{'字符数':>9}{'定义句':>8}  样例")
    print("-" * 96)
    total = 0
    for a in args:
        p = pathlib.Path(a)
        if not p.exists():
            print(f"{p.name:<34}  文件不存在")
            continue
        try:
            pages = subprocess.run(["pdfinfo", str(p)], capture_output=True,
                                   text=True).stdout
            npages = re.search(r"Pages:\s+(\d+)", pages)
            npages = int(npages.group(1)) if npages else 0
        except Exception:
            npages = 0
        try:
            t = text_of(p)
        except Exception as e:
            print(f"{p.name:<34}  读不出文本：{e}")
            continue
        body = drop_toc(t)
        defs = count_defs(body)
        total += len(defs)
        sample = defs[0][:40] if defs else "—"
        print(f"{p.name:<34}{npages:>5}{len(body):>9}{len(defs):>8}  {sample}")
    print("-" * 96)
    print(f"合计定义句 {total}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
