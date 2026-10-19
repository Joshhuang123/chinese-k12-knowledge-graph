#!/usr/bin/env python3
"""
拉初高中人教数学教材 PDF 到 data/pdf-cache/（只用于核对，不入库）。

为什么现在拉：
  1,367 个 Concept/Skill 缺 definition，其中 **1,133 个在初高中**
  ——占 83%。小学 12 册早就在本地了，缺口全在没书的那 17 个学段里。
  不先把书拉下来，核对就是无米之炊。

两处踩过的坑，都写在这儿免得下次再踩：
  1. GitHub 匿名 API 会 403 限流。走 raw.githubusercontent.com 直链，不碰 API。
  2. 必修第一册在仓库里被拆成 `.pdf.1` + `.pdf.2` —— 不是两个文件，
     是同一个 PDF 被按字节切开了。下载后要拼回一起再用，
     直接当两个 PDF 打开只会得到「文件已损坏」。

跑法：
    python3 src/fetch_books.py            # 只拉缺的
    python3 src/fetch_books.py --force    # 全部重拉
"""
import argparse
import hashlib
import pathlib
import subprocess
import sys
import urllib.parse
import urllib.request

BASE = pathlib.Path(__file__).resolve().parent.parent
CACHE = BASE / "data" / "pdf-cache"
RAW = "https://raw.githubusercontent.com/TapXWorld/ChinaTextbook/master/"
UA = {"User-Agent": "Mozilla/5.0"}

JR = "初中/数学/人教版-人民教育出版社"
SR = "高中/数学/人教版（A版）（主编：章建跃&李增沪）-人民教育出版社"

# 册次 → (仓库路径, 本地文件名)
#
# 注意两边编码不一样，这是个坑：
#   图谱里的册次编码   bx1 / bx2 / xzxbx1 / xzxbx2 / xzxbx3（books.py）
#   ChinaTextbook 里的 必修 第一册 / 选择性必修 第一册
# 第一版直接拿 m1/m2/x1/x2/x3 当册次用，结果 m2（必修二）在匹配知识点时
# 静默地一册都没匹配上 —— 提取脚本「跑完了、一个没找到」，看起来像教材没内容。
# 中文 PDF 里还有全角数字（１２３），册名匹配必须先做 NFKC 归一化。
BOOKS = {
    "7a": (f"{JR}/七年级/义务教育教科书·数学七年级上册.pdf", "rjb-math-7a.pdf"),
    "7b": (f"{JR}/七年级/义务教育教科书·数学七年级下册.pdf", "rjb-math-7b.pdf"),
    "8a": (f"{JR}/八年级/义务教育教科书·数学八年级上册.pdf", "rjb-math-8a.pdf"),
    "8b": (f"{JR}/八年级/义务教育教科书·数学八年级下册.pdf", "rjb-math-8b.pdf"),
    "9a": (f"{JR}/九年级/义务教育教科书·数学九年级上册.pdf", "rjb-math-9a.pdf"),
    "9b": (f"{JR}/九年级/义务教育教科书·数学九年级下册.pdf", "rjb-math-9b.pdf"),
    # ↓ 图谱册次码 = 文件名码，必须在这里对上
    "bx1": (f"{SR}/普通高中教科书·数学（A版）必修 第一册.pdf.1", "rjb-math-m1.pdf"),
    "bx2": (f"{SR}/普通高中教科书·数学（A版）必修 第二册.pdf", "rjb-math-m2.pdf"),
    "xzxbx1": (f"{SR}/普通高中教科书·数学（A版）选择性必修 第一册.pdf", "rjb-math-x1.pdf"),
    "xzxbx2": (f"{SR}/普通高中教科书·数学（A版）选择性必修 第二册.pdf", "rjb-math-x2.pdf"),
    "xzxbx3": (f"{SR}/普通高中教科书·数学（A版）选择性必修 第三册.pdf", "rjb-math-x3.pdf"),
}
# 必修一被切成两片，下载后要拼起来
SPLIT = {"bx1": [f"{SR}/普通高中教科书·数学（A版）必修 第一册.pdf.1",
                 f"{SR}/普通高中教科书·数学（A版）必修 第一册.pdf.2"]}


def download(path, dest, tries=3):
    url = RAW + urllib.parse.quote(path, safe="/")
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=300) as r, open(dest, "wb") as f:
                while True:
                    chunk = r.read(1 << 20)
                    if not chunk:
                        break
                    f.write(chunk)
            return dest.stat().st_size
        except Exception as e:
            if i == tries - 1:
                raise
            print(f"    重试 {i+1}/{tries}：{e}")


def check_pdf(p):
    """能打开、能读页数才算下好了。字节数对不代表文件完整。"""
    try:
        out = subprocess.run(["pdfinfo", str(p)], capture_output=True, text=True, timeout=60)
        for line in out.stdout.splitlines():
            if line.startswith("Pages:"):
                return int(line.split()[1])
    except Exception:
        pass
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="已有的也重下")
    args = ap.parse_args()
    CACHE.mkdir(parents=True, exist_ok=True)

    ok, bad = 0, []
    for bk, (path, fn) in BOOKS.items():
        dest = CACHE / fn
        if dest.exists() and not args.force:
            pages = check_pdf(dest)
            if pages:
                print(f"  {bk} {fn:<22} 已有 {pages} 页")
                ok += 1
                continue
            print(f"  {bk} {fn:<22} 已存在但打不开，重下")
        parts = SPLIT.get(bk, [path])
        tmp = CACHE / (fn + ".part")
        with open(tmp, "wb") as out:
            for p in parts:
                n = download(p, CACHE / ".dl.tmp")
                out.write((CACHE / ".dl.tmp").read_bytes())
                print(f"    {p.split('/')[-1]}  {n/1e6:.1f} MB")
        tmp.replace(dest)
        (CACHE / ".dl.tmp").unlink(missing_ok=True)
        pages = check_pdf(dest)
        if pages:
            print(f"  {bk} {fn:<22} ✓ {pages} 页  "
                  f"{dest.stat().st_size/1e6:.1f} MB  "
                  f"sha256 {hashlib.sha256(dest.read_bytes()).hexdigest()[:12]}")
            ok += 1
        else:
            print(f"  {bk} {fn:<22} ✗ 下载了但 pdfinfo 读不出页数")
            bad.append(bk)
    print(f"\n{ok}/{len(BOOKS)} 册就绪" + (f"，失败：{bad}" if bad else ""))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
