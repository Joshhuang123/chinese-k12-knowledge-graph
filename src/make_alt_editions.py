#!/usr/bin/env python3
"""
多版本教材对照的**一条命令**流水线。

```bash
python3 src/make_alt_editions.py
```

依次做：
1. `extract_editions.py` —— 从各版本教材抽目录结构（质量闸把关）
2. `align_editions.py`    —— 人教节 ↔ 其他版本节 对齐
3. `build_viz.py`         —— 把对照写进 payload
4. `build_quality.py`     —— 数据质量页同步
5. `health_check.py`      —— 体检

为什么要有这个脚本：这几步之间有**顺序依赖**（对齐要用提取结果、
payload 要用对齐结果），少跑一步就会出现「页面上还挂着旧对照」这种
查不出来的错位。合成一步就不可能漏。

**教材 PDF 不入库**（`data/pdf-cache/` 已 gitignore，约 900 MB），
所以第一次跑要先 `python3 src/fetch_editions.py --all --subject 初中/数学`。
"""
import pathlib
import subprocess
import sys

BASE = pathlib.Path(__file__).resolve().parent.parent
SRC = BASE / "src"


def run(args, title):
    print(f"\n{'='*66}\n{title}\n{'='*66}")
    r = subprocess.run([sys.executable] + args, cwd=BASE)
    if r.returncode != 0:
        print(f"✗ {title} 失败（退出码 {r.returncode}）")
        sys.exit(r.returncode)


def main():
    run([str(SRC / "extract_editions.py"), "--skip", "人教版"],
        "① 抽取各版本目录结构（带质量闸）")
    run([str(SRC / "align_editions.py")],
        "② 对齐：人教节 ↔ 其他版本节")
    run([str(SRC / "build_viz.py")],
        "③ 重建页面（把对照写进 payload）")
    run([str(SRC / "build_quality.py")],
        "④ 重建数据质量页")
    run([str(SRC / "full_stats.py"), "--out", "data/normalized/full-stats.json"],
        "⑤ 更新全库总账")
    run([str(SRC / "health_check.py")],
        "⑥ 体检")
    print("\n完成。数据在：")
    for f in ("data/alt-editions.json", "data/alt-align.json",
              "data/alt-editions-manifest.json"):
        p = BASE / f
        print(f"  {f}  {p.stat().st_size//1024 if p.exists() else 0} KB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
