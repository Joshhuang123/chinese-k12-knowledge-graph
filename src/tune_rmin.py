#!/usr/bin/env python3
"""R_MIN 取值实验：每层最小圈半径该定多少。

背景：新布局用 `R = max(R_MIN, 4.54×√n)`。
R_MIN=88 是「密度一致」的解，但也是「小层被撑大」的解：
小学段（68~173 点）本该按 √n 给 37~60px，却被强制拉到 88px → 点距 9.2px，
而高中段（1985 点）点距只有 1.9px —— **层与层密度差 5 倍**。

小学站更极端：一层 4 个点也被撑到 82px（点距 43px），
一层 1 个点被撑到 62px（孤零零飘在一边）。

本脚本生成若干 R_MIN 变体，截图 + 实测密度，供人眼和指标一起判断。

跑:  python3 src/tune_rmin.py
输出: /tmp/rmin/*.html
"""
import pathlib
import re
import subprocess
import sys

BASE = pathlib.Path(__file__).resolve().parent.parent
TPL = BASE / "viz" / "template.html"
OUTDIR = pathlib.Path("/tmp/rmin")
SITES = ["index.html", "shanghai.html", "kx.html"]
RE_DATA = re.compile(r'<script id="data" type="application/json">(.*?)</script>', re.S)

CANDIDATES = [56, 40, 32, 24, 16, 0]


def main() -> int:
    OUTDIR.mkdir(parents=True, exist_ok=True)
    tpl = TPL.read_text(encoding="utf-8")
    files = []
    for rmin in CANDIDATES:
        v = tpl.replace("const R_MIN = 56;", f"const R_MIN = {rmin};", 1)
        if v == tpl and rmin != 56:
            raise SystemExit("模板里找不到 R_MIN 行")
        for site in SITES:
            src = BASE / site
            if not src.exists():
                continue
            m = RE_DATA.search(src.read_text(encoding="utf-8"))
            payload = m.group(1)
            out = OUTDIR / f"{site.replace('.html','')}_rmin{rmin}.html"
            out.write_text(v.replace("__DATA__", payload), encoding="utf-8")
            files.append(str(out))
    print(f"生成 {len(files)} 个变体\n")

    print("=== 指标 ===\n")
    r = subprocess.run(
        ["node", str(BASE / "src" / "measure_density.mjs"), *files],
        capture_output=True, text=True,
    )
    print(r.stdout)
    if r.returncode != 0:
        print(r.stderr, file=sys.stderr)

    print("=== 每层明细（上海站）===\n")
    sh = [f for f in files if "shanghai_rmin" in f]
    r2 = subprocess.run(
        ["node", str(BASE / "src" / "probe_layers.mjs"), *sh],
        capture_output=True, text=True,
    )
    print(r2.stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
