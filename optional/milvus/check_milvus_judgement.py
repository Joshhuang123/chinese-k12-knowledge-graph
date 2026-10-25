#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Milvus 校验器的判别力自检 —— `optional/milvus/check_milvus_judgement.py`

项目铁律：**判别力为零的断言，等于没写。**

所以每一条检查都要能证明「**它真的会红**」——
做法是**往库里注入一条该检查应该抓住的脏数据**，
看检查是不是真的报出来。

## ⚠️ 为什么要用子进程

`milvus-lite` 是**单进程**的：文件被一个进程打开着，
另一个就再也开不了（`Open local milvus failed`，实测踩过）。

所以**注入和检查都必须在独立子进程里做** ——
父进程一个连接都不能留。

跑法：
    python3 optional/milvus/check_milvus_judgement.py
"""
from __future__ import annotations

import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

BASE = pathlib.Path(__file__).resolve().parent.parent.parent
SRC_DB = BASE / "data" / "milvus" / "kg_lite.db"

PASS, FAIL = [], []


def ok(cond, label, extra=""):
    if cond:
        PASS.append(label)
        print(f"  ✓ {label}")
    else:
        FAIL.append((label, extra))
        print(f"  ✗ {label}" + (f"\n      {extra}" if extra else ""))


def run_check(db_path: str) -> tuple[int, str]:
    """跑一遍检查脚本（**独立子进程**），返回 (退出码, 输出)。"""
    env = dict(os.environ)
    env["MILVUS_LITE_PATH"] = db_path
    env["MILVUS_BACKEND"] = "lite"
    r = subprocess.run([sys.executable, str(BASE / "optional" / "milvus" / "check_milvus.py")],
                       capture_output=True, text=True, env=env, timeout=900)
    return r.returncode, (r.stdout or "") + (r.stderr or "")


# 注入脚本 —— 在子进程里跑，跑完进程退出，文件锁自动释放
INJECT = r'''
import os, sys
os.environ["MILVUS_BACKEND"] = "lite"
from pymilvus import MilvusClient
db, mode = sys.argv[1], sys.argv[2]
c = MilvusClient(uri=db)
if mode == "copyright":
    c.insert("kg_textbook", data=[{
        "seg_id": "LEAK-test", "vector": [0.0] * 1024,
        "text": "版权所有，未经许可不得另做他用。美术编辑：王致。",
        "edition": "人教版", "book": "7a", "subject": "biology",
        "page": 1, "chapter": "", "concepts": [], "source": "test"}])
elif mode == "extra":
    c.insert("kg_textbook", data=[{
        "seg_id": "FILTER-test", "vector": [0.0] * 1024,
        "text": "这是一段用来测试过滤越界的文字，讲的是浮力。",
        "edition": "沪教版", "book": "9b", "subject": "physics",
        "page": 1, "chapter": "", "concepts": [], "source": "test"}])
elif mode == "dropconcept":
    c.delete("kg_concept", filter='id != ""')
else:
    c.flush("kg_textbook")   # ⚠️ flush 要集合名（传 None 会报
                          #    "flush() missing 1 required positional argument"）
'''


def inject(db: str, mode: str) -> None:
    """在独立子进程里注入脏数据（跑完自动释放文件锁）。"""
    r = subprocess.run([sys.executable, "-c", INJECT, db, mode],
                       capture_output=True, text=True, timeout=600)
    if r.returncode != 0:
        raise RuntimeError(f"注入失败（{mode}）：{(r.stderr or '')[-300:]}")


def main() -> int:
    if not SRC_DB.exists():
        print(f"✗ 缺 {SRC_DB} —— 先跑 python3 optional/milvus/build_milvus.py")
        return 1

    # ⚠️ **必须在库静止的时候跑** ——
    # 复制一个正在写入的库会得到 "database disk image is malformed"（实测踩过）。
    r = subprocess.run(["pgrep", "-f", "build_milvus.py"], capture_output=True)
    if r.returncode == 0:
        print("✗ 正在灌数据 —— 等它跑完再跑判别力自检"
              "（复制正在写入的库会得到损坏的镜像，实测踩过）")
        return 1

    print("判别力自检：注入脏数据 → 检查必须报红\n")

    # ── 0. 正常库必须全绿 ────────────────────────────────
    print("【0】正常库")
    code, out = run_check(str(SRC_DB))
    ok(code == 0, "正常库跑检查是绿的（退出码 0）",
       f"退出码 {code}\n{out[-800:]}")

    # ── 1. 注入版权页 → 版权检查必须红 ───────────────────
    print("\n【1】注入版权页（「版权所有…未经许可不得另做他用」）")
    with tempfile.TemporaryDirectory() as td:
        db = str(pathlib.Path(td) / "leak.db")
        shutil.copy2(SRC_DB, db)
        inject(db, "copyright")
        code, out = run_check(db)
        ok(code != 0, "注入版权段后检查报红（退出码非 0）", f"退出码 {code}")
        ok("版权" in out, "报红原因指到了版权那一项", out[-500:])

    # ── 2. 注入额外段 → 不该误报 ────────────────────────
    print("\n【2】注入一段沪教版9b 的段（查人教版8b 时不该出现）")
    with tempfile.TemporaryDirectory() as td:
        db = str(pathlib.Path(td) / "filter.db")
        shutil.copy2(SRC_DB, db)
        inject(db, "extra")
        code, out = run_check(db)
        seg = out.split("5. 过滤")[1].split("6.")[0] if "5. 过滤" in out else ""
        ok("✗" not in seg,
           "过滤检查没误报（沪教版9b 的段没混进人教版8b 的结果里）",
           seg[:300])
        ok(code == 0, "注入额外数据后检查仍然全绿（不是误报）",
           f"退出码 {code}\n{out[-400:]}")

    # ── 3. 清空概念表 → 条数检查必须红 ───────────────────
    print("\n【3】清空概念表 → 条数检查必须红")
    with tempfile.TemporaryDirectory() as td:
        db = str(pathlib.Path(td) / "noconcept.db")
        shutil.copy2(SRC_DB, db)
        inject(db, "dropconcept")
        code, out = run_check(db)
        ok(code != 0, "概念表清空后检查报红", f"退出码 {code}")
        ok("概念数" in out, "报红原因指到了概念数那一项", out[-400:])

    print()
    print("=" * 56)
    if FAIL:
        print(f"✗ {len(FAIL)} 项判别力验证没过：")
        for lab, extra in FAIL:
            print(f"    - {lab}")
        return 1
    print(f"✓ {len(PASS)} 项判别力验证全过 —— 这些检查真的会红")
    return 0


if __name__ == "__main__":
    sys.exit(main())
