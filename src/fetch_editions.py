#!/usr/bin/env python3
"""
下载**其他出版社**的教材，为多版本对照做准备。

## 为什么

人教版是全国通用，但**不是唯一**：
上海用沪教版（上海教育出版社）、
湖南用湘教版、
北京等地用北师大版、
江苏用苏科版、浙江用浙教版……

我们图谱的教材顺序是按**人教版**排的（`books.py` 的 `RANK` 只排人教）。
一个用湘教版的学生来查「二次函数」，页面上写的
「九上 22.2 二次函数」对他**没有意义** —— 他那本教材里不是这一章。

所以要下**多套教材**，把每套的目录结构抽出来，做成对照表：
「二次函数（人教九上 22.2）= 沪教九上 ？ = 湘教九上 ？」

## 为什么要单独一个脚本

`get_pdf.py` 是「按 manifest 下」，manifest 手写。
这里要下的是**目录里有什么就下什么**，得先遍历仓库树。
而且**教材 PDF 不入库**（`data/pdf-cache/` 已 gitignore），
所以要单独存一份「哪套教材在哪」的清单在 `data/` 下。

## 跑法

```bash
python3 src/fetch_editions.py --list                       # 看有哪些出版社
python3 src/fetch_editions.py --publisher 湘教版-湖南教育出版社 --subject 初中/数学
python3 src/fetch_editions.py --all --subject 初中/数学     # 全下
python3 src/fetch_editions.py --list-pdfs --publisher 沪科技版-上海科学技术出版社
"""
import argparse
import json
import pathlib
import re
import sys
import time
import urllib.parse
import urllib.request

BASE = pathlib.Path(__file__).resolve().parent.parent
CACHE = BASE / "data" / "pdf-cache" / "alt"
MANIFEST = BASE / "data" / "alt-editions-manifest.json"
UA = {"User-Agent": "Mozilla/5.0"}
TREE = "https://github.com/TapXWorld/ChinaTextbook/tree/master/"
RAW = "https://raw.githubusercontent.com/TapXWorld/ChinaTextbook/master/"


def tree(path, tries=4):
    """GitHub 的 tree 页面把整棵目录树嵌在 react-app.embeddedData 里。"""
    url = TREE + urllib.parse.quote(path, safe="/")
    last = None
    for _ in range(tries):
        try:
            req = urllib.request.Request(url, headers=UA)
            h = urllib.request.urlopen(req, timeout=90).read().decode("utf-8", "replace")
            tag = 'react-app.embeddedData">'
            i = h.find(tag)
            if i < 0:
                raise RuntimeError("页面结构变了")
            j = h.find("</script>", i)
            return json.loads(h[i + len(tag):j])["payload"]["codeViewTreeRoute"]["tree"]["items"]
        except Exception as e:
            last = e
            time.sleep(3)
    print(f"  ! {path}: {last}")
    return []


def walk(path, out):
    for it in tree(path):
        if it["contentType"] == "directory":
            walk(it["path"], out)
        elif it["name"].lower().endswith(".pdf"):
            out.append((it["name"], it["path"]))
    return out


def short(pub):
    """目录名 → 短名（用于本地文件名）。"""
    s = re.sub(r"（.*?）", "", pub)
    s = s.split("-")[0]
    return re.sub(r"[^\w一-鿿]+", "", s)


def book_key(name):
    """从文件名里认出是几年级上/下册。"""
    flat = re.sub(r"\s", "", name)
    for m in re.finditer(r"([一二三四五六七八九])年级(上|下)册", flat):
        return m.group(1) + m.group(2)
    if "全一册" in flat:
        return "全一册"
    m = re.search(r"(必修|选择性必修)[一二三]?", flat)
    if m:
        return m.group(0)
    return flat[:12]


def download(path, dest, tries=3):
    if dest.exists() and dest.stat().st_size > 500_000:
        return dest.stat().st_size
    url = RAW + urllib.parse.quote(path)
    last = None
    for _ in range(tries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=300) as r:
                data = r.read()
            if len(data) < 100_000:
                raise RuntimeError(f"只有 {len(data)} 字节，可能是 404")
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
            return len(data)
        except Exception as e:
            last = e
            time.sleep(4)
    print(f"    ✗ {path}: {last}")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--subject", default="初中/数学", help="学段/学科目录")
    ap.add_argument("--publisher", help="只下这个出版社（目录名）")
    ap.add_argument("--all", action="store_true", help="下所有出版社")
    ap.add_argument("--list", action="store_true", help="只列出有哪些出版社")
    ap.add_argument("--list-pdfs", help="列出某个出版社下的所有 PDF")
    ap.add_argument("--skip-existing", action="store_true", default=True)
    args = ap.parse_args()

    if args.list:
        pubs = [it["path"] for it in tree(args.subject)
                if it["contentType"] == "directory"]
        for p in pubs:
            print("  " + p.split("/")[-1])
        return 0

    if args.list_pdfs:
        for name, path in sorted(walk(args.list_pdfs, [])):
            print(f"  {name}\n      {path}")
        return 0

    pubs = [it["path"] for it in tree(args.subject)
            if it["contentType"] == "directory"]
    if args.publisher:
        pubs = [p for p in pubs if args.publisher in p]
    if not args.all and not args.publisher:
        print("要下全部请加 --all，或用 --publisher 指定一个")
        return 1

    man = {}
    if MANIFEST.exists():
        man = json.load(open(MANIFEST, encoding="utf-8"))
    man.setdefault("editions", {})

    for pub in pubs:
        s = short(pub)
        print(f"\n=== {pub.split('/')[-1]} ===")
        for name, path in sorted(walk(pub, [])):
            key = book_key(name)
            local = CACHE / s / f"{key}.pdf"
            n = download(path, local)
            if n:
                print(f"  ✓ {key:<10} {n/1e6:6.1f} MB  {name}")
            man["editions"].setdefault(s, {})[key] = {
                "repoPath": path, "fileName": name,
                "local": str(local.relative_to(BASE)), "bytes": n,
                "publisher": pub.split("/")[-1], "subject": args.subject,
            }
        # **每下完一个出版社就写一次清单。**
        # 一次全下 60 本要几十分钟，中间断了就白下 ——
        # 清单在磁盘上，下一次跑就能接着来。
        MANIFEST.write_text(json.dumps(man, ensure_ascii=False, indent=1),
                            encoding="utf-8")
    print(f"\n→ {MANIFEST.relative_to(BASE)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
