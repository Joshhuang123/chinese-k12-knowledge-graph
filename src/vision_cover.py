#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从 vision-pages*.jsonl 生成覆盖清单（vision_pages.py 跑完时也会写一份，
但那个要等整轮结束；这个可以随时跑，给「跑到哪了」一个即时快照）。"""
import collections
import json
import pathlib

BASE = pathlib.Path("/Users/huangjunhai/Documents/个人/项目/中文知识图谱")
PAIRS = [
    ("data/vision-pages.jsonl", "data/vision-cover.json"),
    ("data/vision-pages-alt.jsonl", "data/vision-cover-alt.json"),
]

for src, dst in PAIRS:
    p = BASE / src
    if not p.exists():
        print(f"跳过 {src}（还没有）")
        continue
    cov = {}
    n_ok = n_all = 0
    for line in p.open(encoding="utf-8"):
        try:
            r = json.loads(line)
        except Exception:
            continue
        n_all += 1
        if r.get("ok"):
            n_ok += 1
        c = cov.setdefault(r["book"], {"subject": r["subject"], "bookZh": r["bookZh"],
                                       "publisher": r.get("publisher", ""), "pages": []})
        c["pages"].append(r["page"])
    for c in cov.values():
        c["pages"] = sorted(set(c["pages"]))
        c["pageCount"] = len(c["pages"])
    out = {"_total": n_all, "_ok": n_ok, "_failed": n_all - n_ok, "books": cov}
    (BASE / dst).write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{dst}: {len(cov)} 册 / {n_ok} 页成功 / {n_all - n_ok} 页失败")
