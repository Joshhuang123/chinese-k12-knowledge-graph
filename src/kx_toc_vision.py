#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
用**视觉模型**读人教版《小学科学》12 本的目录页，抽单元/节/起始页。

为什么不用 OCR
--------------
tesseract 在这种彩色底、装饰性排版的目录上很脏。实测上海教材就是这样：
节号带噪声前缀、页码被读成汉字。
视觉模型是**看版面**的，能读对「① 磁铁的磁极 /2」这种「序号 + 名称 + 页码」三段式。

人教版小学科学的目录长这样（三年级上册 p5）：
    第一单元  有趣的磁铁 /1
      ①  磁铁的磁极 /2
      ②  磁极间的作用 /7
      ③  指南针 /10
    第二单元  气体 液体 固体 /18
      ...

**注意**：目录页位置不固定 —— 1a/1b/2a/2b/3b/4a/4b/5b 在 p4，
3a 在 p5，5a/6a/6b 是彩色目录（也在 p4）。
所以**每本都扫 p3~p7**，用「抽到的节最多」选目录页。

产出的东西是「教材自己教什么」的骨架：
    第一单元 有趣的磁铁(p1) → 磁铁的磁极(p2)  磁极间的作用(p7) …
有了起始页，就能把「页 → 节」映射出来，
再拿节名去跟上游图谱的概念名匹配 —— 这是最强的匹配信号。

跑法：python3 src/kx_toc_vision.py
"""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import pathlib
import re
import sys
import time

BASE = pathlib.Path("/Users/huangjunhai/Documents/个人/项目/中文知识图谱")
sys.path.insert(0, str(BASE / "src"))
import vision_pages as V          # noqa: E402

IMG = BASE / "data" / "pdf-cache" / "kx"
OUT = BASE / "data" / "kx-toc.json"
SCAN_FROM, SCAN_TO = 3, 7

PROMPT = """这是一页中国小学教材《科学》的**目录页**。请把目录结构读出来，只输出 JSON：

{"units":[
  {"no":"第一单元","name":"有趣的磁铁","startPage":1,
   "sections":[{"no":"1","name":"磁铁的磁极","startPage":2},
               {"no":"2","name":"磁极间的作用","startPage":7},
               {"no":"3","name":"指南针","startPage":10}]},
  {"no":"第二单元","name":"气体 液体 固体","startPage":18,
   "sections":[{"no":"4","name":"无处不在的空气","startPage":19}]}]}

规则：
- "no" 是单元序号，原样写（第一单元 / 单元一 都行）；节用连续编号 1,2,3…
- "name" 只写名称本身，**不要带页码、不要带序号**
- "startPage" 是这一单元/这一节**开始的页码**（目录右边那一列的数字）
- 「单元回顾」「活动与练习」「阅读材料」这类条目也放进 sections，
  no 写空字符串
- 页码看不清就写 null，**不要猜**
- 单元名中间的空格照抄（"气体 液体 固体" 是一个单元名，不是三个）
- 这一页不是目录页就输出 {"units":[]}"""


def read_toc_page(img: pathlib.Path) -> dict:
    """用视觉模型读一页目录。"""
    url = V.upload(img)
    if not url:
        return {}
    try:
        bodies = V.describe([url], PROMPT, tries=3)
        raw = bodies[0] if bodies else None
    except Exception as e:
        print(f"  ! {img.name} 模型调用失败 {str(e)[:80]}")
        return {}
    if not raw:
        return {}
    d = V.parse_json_loose(raw)
    return d if isinstance(d, dict) else {}


def sections_of(toc: dict) -> int:
    """数这本目录里有多少节 —— 用来判断哪一页才是目录页。"""
    n = 0
    for u in toc.get("units") or []:
        n += len(u.get("sections") or [])
    return n


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--jobs", type=int, default=3)
    args = ap.parse_args()

    books = sorted(p for p in IMG.iterdir() if p.is_dir())
    print(f"{len(books)} 本书")

    out = {}
    if OUT.exists():
        out = json.load(open(OUT, encoding="utf-8"))
        print(f"已有 {len(out)} 本，重跑会覆盖")

    todo = [b for b in books if b.name not in out]
    print(f"待处理 {len(todo)} 本", flush=True)

    def work(bdir: pathlib.Path):
        best = {}
        best_n = 0
        for p in range(SCAN_FROM, SCAN_TO + 1):
            f = bdir / f"p{p:03d}.jpg"
            if not f.exists():
                continue
            toc = read_toc_page(f)
            n = sections_of(toc)
            if n > best_n:
                best, best_n = toc, n
            if n >= 5:      # 目录页一般有 5 节以上，够了
                break
        # **键要用书名（str），不能是 Path** —— Path 不能当 JSON 键，写盘会炸
        # （第一版就是这里 TypeError: keys must be str... not PosixPath，
        #  9 本都跑完了结果一个字节没写进去。）
        return bdir.name, best, best_n

    t0 = time.time()
    with concurrent.futures.ThreadPoolExecutor(args.jobs) as ex:
        futs = {ex.submit(work, b): b for b in todo}
        done = 0
        for fu in concurrent.futures.as_completed(futs):
            name, toc, n = fu.result()
            done += 1
            if n:
                toc["_sections"] = n
                out[name] = toc          # ← 用 str 键，不是 Path
                print(f"  ✓ {name}  {n} 节  ({done}/{len(todo)})  {time.time()-t0:.0f}s", flush=True)
            else:
                print(f"  ! {name}  没读到目录 ({done}/{len(todo)})", flush=True)

    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    total = sum(len(v.get("units") or []) for v in out.values())
    print(f"\n目录 → {OUT}  ({len(out)} 本 / {total} 个单元)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
