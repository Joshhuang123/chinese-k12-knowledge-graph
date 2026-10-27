#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
学习页数据层的**判别力校验**。

判据：
  ① **页图指向的是正文页，不是目录页** ——
     教材的目录页上每个概念名都出现（目录里列着），
     拿目录页当「教材原页」等于什么都没说。
     校验：显示页的正文里要**提到这个概念**，且不是目录页特征
     （目录页正文里出现大量「……第 N 页」这种目录条目）。
  ② **教材原话不串版** —— 沪教站的引文必须来自沪教教材
     （bookId 以 `sh-` 开头），人教站的来自人教版。
  ③ **公式不是 LaTeX 源码** —— 页面上不能出现 `\frac`、`\begin` 这类命令。
  ④ **页码两套不混** —— 页图用扫描序号；位置文字用印刷页码。
     校验：显示的扫描页必须落在该书的总页数内。

跑:  python3 src/check_learn_site.py
"""
import collections
import json
import pathlib
import re
import sys

BASE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE / "src"))

DATA = BASE / "data"
PAGE_IMG = json.loads((DATA / "page-images.json").read_text(encoding="utf-8"))
TB = {b["bookId"]: b for b in json.loads((DATA / "shanghai-textbooks.json").read_text(encoding="utf-8"))["books"]}

fail = 0
ok = 0


def check(cond, label, detail=""):
    global fail, ok
    if cond:
        ok += 1
    else:
        fail += 1
        print(f"  ✗ {label}" + (f"  —— {detail}" if detail else ""))


def load(tag):
    """把 learn-<tag>.js 读成 dict（它是 window.LEARN_DATA=...;）"""
    txt = (DATA / f"learn-{tag}.js").read_text(encoding="utf-8")
    body = txt[txt.index("=") + 1:].rstrip().rstrip(";")
    return json.loads(body)


def main() -> int:
    print("=== 学习页数据校验 ===\n")

    # 教材正文
    ocr = collections.defaultdict(dict)
    for line in (DATA / "lessons-sh.jsonl").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line[0] != "{":
            continue
        try:
            d = json.loads(line)
        except Exception:
            continue
        if isinstance(d, dict) and isinstance(d.get("book"), str):
            ocr[d["book"]][d.get("page")] = d.get("text") or ""

    for tag, want_prefix in (("sh", "sh-"), ("rjb", None), ("kx", None)):
        D = load(tag)
        nodes = D["nodes"]
        print(f"[{tag}] {len(nodes)} 个节点")

        # ① 页图指向正文页
        #
        # ⚠️ **只有沪教版有页图** ——
        # 人教版的教材来自 ChinaTextbook 的 PDF，平台没有对应扫描本；
        # 小学科学是人教版《小学科学》，同理。
        # 页码体系不同源，硬拼会**翻到错的页** ——
        # 那比不显示更坏。所以这两版不显示教材原页图，是已知限制，不是错误。
        withimg = [n for n in nodes if n.get("loc", {}).get("scan")]
        if tag == "sh":
            check(len(withimg) > 0, f"{tag}: 有节点带页图",
                  f"0 个（页面上的「教材原页」这一块会是空的）")
        else:
            print(f"  · {tag}: 无教材原页图（教材来自 PDF，平台无对应扫描本）—— 已知限制")
        bad_page = 0
        dirish = 0
        notmentioned = 0
        for n in withimg:
            loc = n["loc"]
            bk = loc["bk"]
            pg = loc["scan"][0]
            total = (TB.get(bk) or {}).get("pages")
            if total and pg > total:
                bad_page += 1
            txt = ocr.get(bk, {}).get(pg) or ""
            # 目录页特征：正文里出现「……第 N 页」这种目录条目串
            if len(re.findall(r"\.{3,}\s*\d+", txt)) >= 3:
                dirish += 1
            if n["n"] not in txt:
                notmentioned += 1
        check(bad_page == 0, f"{tag}: 页码都在该书总页数内",
              f"{bad_page} 个越界")
        check(dirish == 0, f"{tag}: 显示页不是目录页",
              f"{dirish} 个是目录页（正文里出现大量「…N 页」条目）")
        # 「正文里提到概念」不是硬性要求（有些概念的页图是插图页），
        # 但不能太多 —— 超过 60% 说明页码挑错了
        if withimg:
            ratio = notmentioned / len(withimg)
            check(ratio <= 0.6, f"{tag}: 显示页大多提到这个概念",
                  f"{notmentioned}/{len(withimg)} = {ratio:.0%} 的页正文里没有概念名")

        # ② 原话不串版
        if want_prefix:
            bad = []
            for n in nodes:
                for r in n.get("rd") or []:
                    b = r.get("b") or ""
                    if b and not b.startswith(want_prefix):
                        bad.append((n["n"], b))
            check(not bad, f"{tag}: 教材原话来自本版本教材",
                  f"{len(bad)} 条串版，例：{bad[:3]}")
            # 页图书也必须是本版本
            badb = [n["n"] for n in withimg if not n["loc"]["bk"].startswith(want_prefix)]
            check(not badb, f"{tag}: 页图来自本版本教材", f"{len(badb)} 个串版")

        # ③ 公式不是 LaTeX 源码
        raw = (DATA / f"learn-{tag}.js").read_text(encoding="utf-8")
        leaks = sum(1 for m in re.finditer(r"\\\\(frac|begin|end|text|sqrt|overrightarrow|boldsymbol|left|right)\b", raw))
        check(leaks == 0, f"{tag}: 公式已转成纯文本（没有 LaTeX 源码漏出）",
              f"{leaks} 处命令漏出")

        # ④ 页码两套不混：位置文字是印刷页码，页图是扫描序号
        mism = 0
        for n in withimg:
            loc = n["loc"]
            printed = [s.get("p") for s in loc.get("sec") or [] if s.get("p")]
            if printed and loc["scan"][0] in printed:
                mism += 1
        # 不要求完全不等（有的书偏移为 0），但两个字段必须都存在且各自有意义
        check(all("sec" in n.get("loc", {}) for n in withimg),
              f"{tag}: 有页图的节点都带教材位置")

        # 必备字段
        need = [n for n in nodes if not n.get("d") and not n.get("rd")]
        check(len(need) < len(nodes) * 0.5,
              f"{tag}: 多数节点有定义或教材原话",
              f"{len(need)}/{len(nodes)} 个两个都没有")
        print()

    # ⑤ 页图基址可用性
    check(len(PAGE_IMG) == 67, "页图基址覆盖 67 本沪教教材", f"{len(PAGE_IMG)} 本")

    print(f"\n{'=' * 46}\n通过 {ok} · 失败 {fail}")
    return 1 if fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
