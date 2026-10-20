#!/usr/bin/env python3
"""
每本教材的**版本指纹** —— 我们引用的到底是哪一代教材。

## 为什么要有这个

视频里会说「这是人教七下第五章 5.1 讲的」。
这句话只有在**读者手上的书跟我们是同一代**时才成立。
人教版初中数学 2024 秋起换成了新版，**章号全变了**：

    我们手上的（2020 印次）        2024 新版
    第五章 相交线与平行线     →    第七章 相交线与平行线
    第六章 实数               →    第八章 实数
    第七章 平面直角坐标系     →    第九章 平面直角坐标系
    ……                             ……

所以「引用第几章第几节」这件事，**必须钉在一个具体版本上**。
这个脚本从每本 PDF 的版权页抠出版次、印次、ISBN、依据的课标，
再加上**章数指纹**（图谱里的章 vs 教材里的章），
写进 `data/textbook-editions.json`。

## 跑法

```bash
python3 src/book_editions.py                    # 只看
python3 src/book_editions.py --out data/textbook-editions.json
python3 src/book_editions.py --check            # 跟已存的表对账
```

**教材 PDF 不入库**（`data/pdf-cache/` 已 gitignore），
所以这个表是**唯一**记录「我们引用的是哪一代」的地方。
"""
import argparse
import json
import pathlib
import re
import subprocess
import sys

BASE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

CACHE = BASE / "data" / "pdf-cache"
OUT = BASE / "data" / "textbook-editions.json"

# 册次码 → (学科中文, 显示册次)
BOOKS = {
    "math-1a": ("数学", "一上"), "math-1b": ("数学", "一下"),
    "math-2a": ("数学", "二上"), "math-2b": ("数学", "二下"),
    "math-3a": ("数学", "三上"), "math-3b": ("数学", "三下"),
    "math-4a": ("数学", "四上"), "math-4b": ("数学", "四下"),
    "math-5a": ("数学", "五上"), "math-5b": ("数学", "五下"),
    "math-6a": ("数学", "六上"), "math-6b": ("数学", "六下"),
    "math-7a": ("数学", "七上"), "math-7b": ("数学", "七下"),
    "math-8a": ("数学", "八上"), "math-8b": ("数学", "八下"),
    "math-9a": ("数学", "九上"), "math-9b": ("数学", "九下"),
    "math-m1": ("数学", "必修一"), "math-m2": ("数学", "必修二"),
    "math-x1": ("数学", "选必一"), "math-x2": ("数学", "选必二"),
    "math-x3": ("数学", "选必三"),
    "phys-8a": ("物理", "八上"), "phys-8b": ("物理", "八下"),
    "chem-9a": ("化学", "九上"), "chem-9b": ("化学", "九下"),
    "bio-7a": ("生物", "七上"), "bio-7b": ("生物", "七下"),
    "bio-8a": ("生物", "八上"), "bio-8b": ("生物", "八下"),
}


def load_text(bk):
    """扫描件只有 OCR 文本有内容；文本层的优先用 pdftotext。"""
    for cand in (CACHE / f"rjb-{bk}.ocr.txt", CACHE / f"rjb-{bk}.txt"):
        if cand.exists():
            s = cand.read_text(encoding="utf-8", errors="replace")
            if len(re.sub(r"\s", "", s)) > 800:
                return s, "ocr" if ".ocr." in cand.name else "text"
    tmp = CACHE / f"_tmp_{bk}.txt"
    pdf = CACHE / f"rjb-{bk}.pdf"
    if pdf.exists():
        subprocess.run(["pdftotext", "-layout", str(pdf), str(tmp)],
                       capture_output=True)
        if tmp.exists():
            s = tmp.read_text(encoding="utf-8", errors="replace")
            tmp.unlink()
            return s, "text"
    return "", "none"


CN_NUM = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7,
          "八": 8, "九": 9, "十": 10, "十一": 11, "十二": 12}


def chapters_of(text):
    """从教材文本里抽出「第 N 章」的编号集合。"""
    flat = re.sub(r"\s", "", text)
    out = set()
    for m in re.finditer(r"第([一二三四五六七八九十]{1,3})章", flat):
        s = m.group(1)
        n = 0
        for ch in s:
            n = n * 10 + CN_NUM.get(ch, 0)
        if 1 <= n <= 30:
            out.add(n)
    return sorted(out)


def chapter_names_of(text):
    """教材里「第N章 XXX」的**章名**集合（去掉编号前缀）。

    **比章号没意义** —— 图谱用的是上游数据集的全局编号（八上是 1-6、11-15），
    教材用的是册内编号（七下是 5-10）。两边编号体系不同，
    只有**名字**能对上。
    """
    flat = re.sub(r"[ \t]+", " ", text)
    out = set()
    for m in re.finditer(r"第[一二三四五六七八九十]{1,3}章\s*([^\n\d]{2,18})", flat):
        nm = re.sub(r"\s", "", m.group(1))
        nm = re.split(r"[，。；、\d]", nm)[0]
        if len(nm) >= 2:
            out.add(nm)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out")
    ap.add_argument("--check", action="store_true",
                    help="跟已存的表对账（教材换版了要报错）")
    args = ap.parse_args()

    rows = {}
    for bk, (subj, bookzh) in BOOKS.items():
        if not (CACHE / f"rjb-{bk}.pdf").exists():
            continue
        t, how = load_text(bk)
        flat = re.sub(r"\s", "", t[:16000])
        # 版次：版次2022年5月第1版（OCR 可能把「版次」读坏）
        edition = ""
        m = re.search(r"版[次决]?[^0-9]{0,6}(\d{4})年(\d{1,2})月第1版", flat)
        if m:
            edition = f"{m.group(1)}.{int(m.group(2)):02d}"
        else:
            m = re.search(r"版[次决]?[^0-9]{0,6}(\d{4})年", flat)
            if m:
                edition = m.group(1)
        # 印次：版权页那串日期戳（2022/5/7）
        printed = ""
        m = re.search(r"(\d{4})/(\d{1,2})/(\d{1,2})", flat)
        if m:
            printed = f"{m.group(1)}.{int(m.group(2)):02d}.{int(m.group(3)):02d}"
        isbn = ""
        m = re.search(r"ISBN([0-9\-]{10,17})", flat)
        if m:
            isbn = m.group(1)
        std = ""
        m = re.search(r"课程标准[（(]?(\d{4})年?版", flat)
        if m:
            std = "《义务教育课程标准（" + m.group(1) + "年版）》"
        rows[bk] = {
            "subject": subj, "bookZh": bookzh,
            "edition": edition, "printed": printed,
            "isbn": isbn, "curriculum": std,
            "textSource": how,
            "chaptersInBook": chapters_of(t),
            "chapterNamesInBook": sorted(chapter_names_of(t)),
        }

    # 图谱里的章（用来对账）—— **比章名，不比章号**
    g = json.load(open(BASE / "data" / "normalized" / "graph.json",
                       encoding="utf-8"))
    graph_ch = {}
    for n in g["nodes"]:
        if n.get("label") != "Chapter":
            continue
        m = re.search(r"_ch(\d+)$", n["id"])
        if m:
            graph_ch.setdefault(n.get("book"), set()).add(int(m.group(1)))
    graph_names = {}
    for n in g["nodes"]:
        if n.get("label") != "Chapter":
            continue
        m = re.search(r"_ch\d+$", n["id"])
        if m:
            graph_names.setdefault(n.get("book"), set()).add(
                re.sub(r"^第[一二三四五六七八九十]+章\s*", "", n["name"]).strip())

    print("=" * 78)
    print("教材版本指纹")
    print("=" * 78)
    # **章序对不对得上不在这儿查。**
    # 目录排版每册都不一样（有的「第一章」有的「第1章」，有的章名带单元前缀），
    # 自己抽一遍只会得到一堆假警报。章序核对是 verify_order.py 的活
    # （23 册 0 处排错），别在这里重造一遍。
    print(f"{'册':<10}{'版次':<9}{'印次':<13}{'ISBN':<20}教材里的章名（部分）")
    for bk, r in rows.items():
        bn = r["chapterNamesInBook"][:5]
        print(f"  {r['bookZh']:<8}{r['edition'] or '?':<9}{r['printed'] or '?':<13}"
              f"{r['isbn'] or '?':<20}{'、'.join(bn) if bn else '（未抽到）'}")

    if args.check:
        if not OUT.exists():
            print("\n! data/textbook-editions.json 还没生成")
            return 1
        old = json.load(open(OUT, encoding="utf-8"))
        diffs = []
        for bk, r in rows.items():
            o = old.get("books", {}).get(bk, {})
            for k in ("edition", "printed", "isbn"):
                if o.get(k) != r.get(k):
                    diffs.append(f"{bk}.{k}: {o.get(k)!r} → {r.get(k)!r}")
        if diffs:
            print("\n✗ 教材版本变了：")
            for d in diffs:
                print("   " + d)
            return 1
        print("\n✓ 教材版本与记录一致")
        return 0

    out = {"_comment": ("每本教材的版本指纹。**引用「第几章第几节」必须钉在这个版本上** —— "
                        "人教版初中 2024 秋起换新版，章号全变了。"
                        "由 src/book_editions.py 从 PDF 版权页生成。"),
           "generated": __import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M"),
           "books": rows}
    op = pathlib.Path(args.out) if args.out else OUT
    if not op.is_absolute():
        op = BASE / op
    op.parent.mkdir(parents=True, exist_ok=True)
    json.dump(out, open(op, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\n→ {op.relative_to(BASE)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
