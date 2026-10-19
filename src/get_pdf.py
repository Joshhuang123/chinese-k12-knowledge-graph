#!/usr/bin/env python3
"""
按「仓库路径 → 本地文件名」的清单下载教材 PDF。

为什么不用 `fetch_books.py`：那个脚本的册次表是数学硬编码的
（`JR`/`SR` 两个常量 + 10 条映射），非数学的册次和路径都不一样，
硬塞进去会把一个清楚的文件弄成一堆 if。

用法：
    python3 src/get_pdf.py data/pdf-cache/manifest.txt
    python3 src/get_pdf.py data/pdf-cache/manifest.txt --force

manifest 每行两列（空格或制表符分隔）：
    <仓库相对路径>    <本地文件名>

只用于核对，PDF 不入库（data/pdf-cache/ 已 gitignore）。
"""
import argparse
import pathlib
import subprocess
import sys
import urllib.parse
import urllib.request

BASE = pathlib.Path(__file__).resolve().parent.parent
RAW = "https://raw.githubusercontent.com/TapXWorld/ChinaTextbook/master/"
UA = {"User-Agent": "Mozilla/5.0"}


def get(path, dst, force=False):
    if dst.exists() and dst.stat().st_size > 1_000_000 and not force:
        print(f"  已有 {dst.name}（{dst.stat().st_size/1e6:.1f} MB）")
        return True
    url = RAW + urllib.parse.quote(path)
    print(f"  下载 {dst.name} …", flush=True)
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=300) as r:
            data = r.read()
    except Exception as e:
        print(f"  ✗ {dst.name}: {e}")
        return False
    if len(data) < 100_000:
        print(f"  ✗ {dst.name}: 只有 {len(data)} 字节，可能是 404 页面")
        return False
    dst.write_bytes(data)
    print(f"  ✓ {dst.name}（{len(data)/1e6:.1f} MB）")
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("manifest")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--out", default=str(BASE / "data" / "pdf-cache"))
    args = ap.parse_args()

    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    lines = [l for l in pathlib.Path(args.manifest).read_text(encoding="utf-8").splitlines()
             if l.strip() and not l.strip().startswith("#")]
    print(f"清单 {len(lines)} 条")
    ok = 0
    for line in lines:
        parts = line.split()
        if len(parts) < 2:
            print(f"  ✗ 清单行格式不对: {line!r}")
            continue
        repo_path, local = parts[0], parts[1]
        if get(repo_path, out / local, args.force):
            ok += 1
    print(f"\n成功 {ok}/{len(lines)}")
    return 0 if ok == len(lines) else 1


if __name__ == "__main__":
    sys.exit(main())
