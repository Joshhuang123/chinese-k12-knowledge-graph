#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""重新生成 data/pdf-cache/manifest.txt 并下载人教版教材 PDF。

背景（2026-10-30）：
  `data/pdf-cache/` 整个空了 —— 31 册人教版 PDF 和 manifest 都没了。
  教材 PDF **不入库**（版权），所以 manifest 也得自己重建。

  影响：
  · `src/check_learn_site.py` 的「显示页大多提到这个概念」那条判据
    读不到页正文 → 只能跳过（已修成「输入缺失 ≠ 判据失败」）
  · `src/render_page_images.py`（重渲页图）、
    `src/quote_repair.py`（从 PDF 文本层补教材原话）没法跑

源：https://github.com/TapXWorld/ChinaTextbook （公开的教材 PDF 镜像）

⚠️ **用 git tree API 一次拿全量路径**，不要逐个目录列 ——
   逐目录列要几十次请求，未认证的 GitHub API 一小时只有 60 次，
   试到一半就 403 rate limit 了（实测踩过）。

⚠️ **本地文件名的册次码是转换过的**（跟 check_learn_site.py 的 HIGH_VOL 一致）：
   教材册次 bx1（必修一）→ 本地 m1；xzxbx1（选择性必修一）→ 本地 x1。
   写错一个字母，页图就对不上册次。

用法：
    python3 src/restore_pdf_cache.py            # 生成 manifest + 下载
    python3 src/restore_pdf_cache.py --manifest  # 只生成 manifest
"""
import argparse
import io
import json
import pathlib
import sys
import urllib.parse
import urllib.request

BASE = pathlib.Path(__file__).resolve().parent.parent
CACHE = BASE / "data" / "pdf-cache"
TREE_API = "https://api.github.com/repos/TapXWorld/ChinaTextbook/git/trees/master?recursive=1"
RAW = "https://raw.githubusercontent.com/TapXWorld/ChinaTextbook/master/"
UA = {"User-Agent": "Mozilla/5.0"}

# 本地文件名 → 仓库路径里的关键片段
# （学科关键词, 册次关键词）—— 路径是「…/学科/人教版…/年级/文件名.pdf」，
#  册次关键词在文件名里，所以按文件名匹配就够了。
WANT = {
    # 小学数学
    "rjb-math-1a.pdf": ("数学", "一年级上册"), "rjb-math-1b.pdf": ("数学", "一年级下册"),
    "rjb-math-2a.pdf": ("数学", "二年级上册"), "rjb-math-2b.pdf": ("数学", "二年级下册"),
    "rjb-math-3a.pdf": ("数学", "三年级上册"), "rjb-math-3b.pdf": ("数学", "三年级下册"),
    "rjb-math-4a.pdf": ("数学", "四年级上册"), "rjb-math-4b.pdf": ("数学", "四年级下册"),
    "rjb-math-5a.pdf": ("数学", "五年级上册"), "rjb-math-5b.pdf": ("数学", "五年级下册"),
    "rjb-math-6a.pdf": ("数学", "六年级上册"), "rjb-math-6b.pdf": ("数学", "六年级下册"),
    # 初中数学
    "rjb-math-7a.pdf": ("数学", "七年级上册"), "rjb-math-7b.pdf": ("数学", "七年级下册"),
    "rjb-math-8a.pdf": ("数学", "八年级上册"), "rjb-math-8b.pdf": ("数学", "八年级下册"),
    "rjb-math-9a.pdf": ("数学", "九年级上册"), "rjb-math-9b.pdf": ("数学", "九年级下册"),
    # 初中生物
    "rjb-bio-7a.pdf": ("生物学", "七年级上册"), "rjb-bio-7b.pdf": ("生物学", "七年级下册"),
    "rjb-bio-8a.pdf": ("生物学", "八年级上册"), "rjb-bio-8b.pdf": ("生物学", "八年级下册"),
    # 初中化学 / 物理
    "rjb-chem-9a.pdf": ("化学", "九年级上册"), "rjb-chem-9b.pdf": ("化学", "九年级下册"),
    "rjb-phys-8a.pdf": ("物理", "八年级上册"), "rjb-phys-8b.pdf": ("物理", "八年级下册"),
    # 高中数学 —— **必须锁 A 版（章建跃&李增沪）**！
    # ⚠️ 仓库里人教高中数学有 A 版和 B 版（高存明）两套，**都叫「必修第一册」**。
    # 我们页图用的是 A 版；下成 B 版 → 页数对不上（实测 B 版 154 页 vs 我们要 251+），
    # 于是「页码都在该书总页数内」那条判据报出 22 个假越界。
    # 拿错版本比没有更糟 —— **宁可不下载**。
    "rjb-math-m2.pdf": ("数学", "必修 第二册"),
    "rjb-math-x1.pdf": ("数学", "选择性必修 第一册"),
    "rjb-math-x2.pdf": ("数学", "选择性必修 第二册"),
    "rjb-math-x3.pdf": ("数学", "选择性必修 第三册"),
}
# 高中数学必修第一册（A 版）**这个镜像仓库里没有** ——
#   仓库的「人教版（A版）」目录只有必修第二册 + 选择性必修一~三，
#   「必修第一册」只在 B 版（高存明）下面，而那是**另一套教材**。
#   我们的页图是从 A 版必修第一册渲染的（扫描页到 251），
#   B 版只有 154 页 → 对不上。
#   所以这一册**故意不下载**：没有它，那条判据对 math-bx1 直接跳过，
#   而不是拿 B 版去比出一堆假越界。
#   要补的话得从别的源找 A 版必修第一册。
# ⚠️ 小学数学的文件名里「·」前后**有时有空格有时没有** ——
#    「义务教育教科书 · 数学一年级上册.pdf」vs「义务教育教科书·数学三年级下册.pdf」。
#    所以匹配时把空格全去掉再比。
# ⚠️ 「数学」是「生物学」「化学」等词的一部分？—— 不是，
#    但「物理」在「物理」而「数学」在「数学」；注意别让「数学」匹配到「生物学」。


def norm(s):
    return s.replace(" ", "").replace("　", "")


def get_tree():
    """拿仓库的全量路径。

    ⚠️ **优先用本地缓存** —— 未认证的 GitHub API 一小时只有 60 次请求，
    逐目录列 + tree 请求很容易撞上限流（实测踩过：403 rate limit）。
    缓存放在 data/pdf-cache/tree.json（不入库），下次直接用。
    """
    cache = CACHE / "tree.json"
    if cache.exists() and cache.stat().st_size > 1000:
        print("  · 用本地缓存 tree.json")
        return json.loads(cache.read_text(encoding="utf-8"))
    req = urllib.request.Request(TREE_API, headers=UA)
    with urllib.request.urlopen(req, timeout=120) as r:
        d = json.loads(r.read().decode("utf-8"))
    cache.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    return d


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", action="store_true", help="只生成 manifest，不下载")
    args = ap.parse_args()

    CACHE.mkdir(parents=True, exist_ok=True)

    print("拉 git tree（一次请求）…")
    tree = get_tree()
    paths = [t["path"] for t in tree.get("tree") or []
             if t.get("type") == "blob" and t["path"].lower().endswith(".pdf")
             and "人教版" in t["path"]]

    picked = {}
    for local, (subj, vol) in WANT.items():
        for p in paths:
            np_ = norm(p)
            # 学科：文件名里必须含学科词，且**不能**含别的学科词
            if subj not in np_:
                continue
            if subj == "数学" and ("生物" in np_ or "化学" in np_ or "物理" in np_):
                continue
            if vol.replace(" ", "") not in np_:
                continue
            # 排除五四学制（文件名里带「（五•四学制）」）
            if "五四学制" in p or "五•四学制" in p:
                continue
            # ⚠️ 高中数学必须锁 A 版（见上面的说明）——
            #   仓库里 B 版（高存明）也有同名文件，下错就是另一套教材。
            if local.startswith("rjb-math-") and local[9:] in ("m2", "x1", "x2", "x3"):
                if "人教版（A版）" not in p:
                    continue
            picked[local] = p
            break

    print(f"挑出 {len(picked)}/{len(WANT)} 册")
    missing = sorted(set(WANT) - set(picked))
    if missing:
        print(f"  !! 没找到: {missing}")

    man = CACHE / "manifest.txt"
    with io.open(man, "w", encoding="utf-8") as f:
        for local in sorted(picked):
            f.write(f"{picked[local]}\t{local}\n")
    print(f"manifest → {man}")

    if args.manifest:
        return 0

    total = 0
    for local in sorted(picked):
        dst = CACHE / local
        if dst.exists() and dst.stat().st_size > 100_000:
            print(f"  · {local}: 已有")
            continue
        src = RAW + urllib.parse.quote(picked[local])
        try:
            req = urllib.request.Request(src, headers=UA)
            with urllib.request.urlopen(req, timeout=600) as r, io.open(dst, "wb") as o:
                while True:
                    chunk = r.read(1 << 20)
                    if not chunk:
                        break
                    o.write(chunk)
            mb = dst.stat().st_size / 1024 / 1024
            total += mb
            print(f"  ✓ {local}: {mb:.1f} MB")
        except Exception as e:
            print(f"  ✗ {local}: {e}")
    print(f"\n本次下载约 {total:.0f} MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
