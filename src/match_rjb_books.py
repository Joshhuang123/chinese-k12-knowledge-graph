#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
定位我们每本人教版教材在**国家中小学智慧教育平台**上的对应电子教材。

为什么这事必须做对
----------------
学习页的「教材原页」要显示平台上的官方扫描页图。
但平台上同名书一大把：
  · 人教社官方版
  · 盲校版 / 聋校版 / 培智学校版（同一批知识，换了排版）
  · 河北社 / 西南社 / 江苏凤凰社 / 北京社 / 青岛社（同一年级同名）
**认错一本 = 显示的是另一家出版社的书。**

怎么认
------
① **标题过滤**：书名必须含「学科 + 年级 + 册次」，且**不含**特殊版本标记
   （盲校 / 聋校 / 培智 / 实验 / 特殊教育 …）。
② **封面判出版者**：封面底部印着出版社名 —— 人教社的封面写「人民教育出版社」。
   这一步需要视觉模型读图。
③ **页数 + 目录比对**：两本书是不是同一版，看目录里的章名和印刷页码。

跑:  python3 src/match_rjb_books.py --list
"""
import argparse
import collections
import json
import pathlib
import re
import sys
import urllib.request

BASE = pathlib.Path(__file__).resolve().parent.parent
PDF_CACHE = BASE / "data" / "pdf-cache"
OUT = BASE / "data" / "rjb-book-candidates.json"
INDEX_PARTS = [
    "https://bdcs-file-2.ykt.cbern.com.cn/zxx/ndrs/resources/tch_material/part_100.json",
    "https://bdcs-file-1.ykt.cbern.com.cn/zxx/ndrs/resources/tch_material/part_101.json",
    "https://bdcs-file-1.ykt.cbern.com.cn/zxx/ndrs/resources/tch_material/part_102.json",
    "https://bdcs-file-2.ykt.cbern.com.cn/zxx/ndrs/resources/tch_material/part_103.json",
]
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

# **特殊版本标记** —— 标题里有这些的都不是我们要的普通版
SPECIAL = re.compile(r"(盲校|聋校|培智|实验教科书|特殊教育|培智学校|特殊)")
GRADE_CN = {"1": "一年级", "2": "二年级", "3": "三年级", "4": "四年级",
            "5": "五年级", "6": "六年级", "7": "七年级", "8": "八年级", "9": "九年级"}
VOL_CN = {"a": "上册", "b": "下册"}
SUBJ_ZH = {"math": "数学", "phys": "物理", "chem": "化学", "bio": "生物"}


def get(url, timeout=60):
    return opener.open(url, timeout=timeout).read()


def title_of(x):
    t = x.get("global_title")
    return t.get("zh-CN", "") if isinstance(t, dict) else str(t or "")


def label_of(x):
    l = x.get("global_label")
    return l.get("zh-CN", []) if isinstance(l, dict) else []


def load_index():
    idx = []
    for u in INDEX_PARTS:
        try:
            d = json.loads(get(u).decode("utf-8"))
        except Exception as e:
            print(f"  索引取不到：{str(e)[:50]}")
            continue
        if isinstance(d, list):
            idx += d
        elif isinstance(d, dict):
            for v in d.values():
                if isinstance(v, list):
                    idx += v
    return idx


def our_books():
    """我们数据里用到的人教版册次 → (学科, 册次码, 本地 PDF, 页数)"""
    te = json.loads((BASE / "data" / "textbook-editions.json").read_text(encoding="utf-8"))
    subj_of = {}
    for k in te["books"]:
        s, v = k.split("-", 1)
        subj_of.setdefault(v, s)

    pages = collections.defaultdict(set)
    for line in (BASE / "data" / "lessons.jsonl").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line[0] != "{":
            continue
        try:
            d = json.loads(line)
        except Exception:
            continue
        if isinstance(d, dict) and isinstance(d.get("book"), str) and isinstance(d.get("page"), int):
            pages[d["book"]].add(d["page"])

    out = []
    for bid in sorted(pages):
        subj = subj_of.get(bid)
        if not subj:
            continue
        pdf = PDF_CACHE / f"rjb-{subj}-{bid}.pdf"
        if not pdf.exists():
            hits = list(PDF_CACHE.glob(f"*rjb-{subj}-{bid}*.pdf")) or list(PDF_CACHE.glob(f"{subj}-{bid}.pdf"))
            pdf = hits[0] if hits else None
        out.append({"book": bid, "subject": subj, "vol": bid,
                    "pdf": str(pdf.relative_to(BASE)) if pdf else None,
                    "pages": max(pages[bid])})
    return out


def candidates_for(idx, subj, vol):
    """按标题找候选（先粗筛，再排除特殊版本）。"""
    zh = SUBJ_ZH.get(subj)
    if not zh:
        return []
    out = []
    for x in idx:
        t = title_of(x)
        if not t or zh not in t:
            continue
        if SPECIAL.search(t):
            continue
        if vol.startswith("m"):
            if "必修" not in t or "普通高中" not in t:
                continue
        elif vol.startswith("x"):
            if "选择性必修" not in t:
                continue
        else:
            g = GRADE_CN.get(vol[0])
            if not g or g not in t or VOL_CN[vol[1]] not in t:
                continue
        out.append(x)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true", help="列出候选")
    args = ap.parse_args()

    books = our_books()
    print(f"我们数据里的人教版册次：{len(books)} 本\n")
    idx = load_index()
    print(f"平台教材索引 {len(idx)} 本\n")

    result = {}
    for b in books:
        cands = candidates_for(idx, b["subject"], b["vol"])
        ids = []
        for x in cands:
            ids.append({"id": x["id"], "title": title_of(x), "label": label_of(x)[:4]})
        result[f"{b['subject']}-{b['vol']}"] = {"ours": b, "candidates": ids}
        flag = "  ← 候选多，需看封面" if len(ids) > 3 else ""
        print(f"  {b['subject']}-{b['vol']:5s} 候选 {len(ids):2d}{flag}")
        if args.list:
            for c in ids:
                print(f"        {c['id'][:8]}  {c['title'][:48]}")
                print(f"                label={c['label']}")

    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n→ {OUT.relative_to(BASE)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
