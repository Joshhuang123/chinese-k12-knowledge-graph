#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
视觉层跑**已下载的页图**（国家中小学智慧教育平台那套教材的页图）。

跟 `vision_pages.py` 的区别
--------------------------
`vision_pages.py` 处理的是本地 PDF：渲染 → 传 → 视觉问答。
这里处理的是**已经是图片的页图**（平台直接给的教材扫描页 JPEG），
所以只需要「传 → 视觉问答」。

复用 `vision_pages.py` 里的上传、批量调用、重试、解析逻辑，
保证两条路产出的数据格式一致。

跑法
----
    python3 src/vision_images.py --dir data/pdf-cache/hujiao --out data/vision-pages-sh.jsonl
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

BASE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE / "src"))

import vision_pages as V          # noqa: E402  复用上传/调用/解析


# 上海教材的册次 → 图谱册次码
# 沪教版是**五四学制**：一年级~七年级，章号跟人教版完全不是一套
# （沪教版七上从「第10章 整式的加减」起，人教版七上从「第1章 有理数」起）
BOOK_GUESS = [
    (re.compile(r"一年级上册"), "1a"), (re.compile(r"一年级下册"), "1b"),
    (re.compile(r"二年级上册"), "2a"), (re.compile(r"二年级下册"), "2b"),
    (re.compile(r"三年级上册"), "3a"), (re.compile(r"三年级下册"), "3b"),
    (re.compile(r"四年级上册"), "4a"), (re.compile(r"四年级下册"), "4b"),
    (re.compile(r"五年级上册"), "5a"), (re.compile(r"五年级下册"), "5b"),
    (re.compile(r"六年级上册"), "6a"), (re.compile(r"六年级下册"), "6b"),
    (re.compile(r"七年级上册"), "7a"), (re.compile(r"七年级下册"), "7b"),
    (re.compile(r"八年级上册"), "8a"), (re.compile(r"八年级下册"), "8b"),
    (re.compile(r"九年级上册"), "9a"), (re.compile(r"九年级下册"), "9b"),
    (re.compile(r"九年级全一册"), "9"),
    (re.compile(r"必修\s*第一册"), "bx1"), (re.compile(r"必修\s*第二册"), "bx2"),
    (re.compile(r"必修\s*第三册"), "bx3"), (re.compile(r"必修\s*第四册"), "bx4"),
    (re.compile(r"选择性必修\s*第一册"), "xzxbx1"),
    (re.compile(r"选择性必修\s*第二册"), "xzxbx2"),
    (re.compile(r"选择性必修\s*第三册"), "xzxbx3"),
]


def guess_graph_book(title: str) -> str:
    for pat, code in BOOK_GUESS:
        if pat.search(title):
            return code
    return ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="data/pdf-cache/hujiao")
    ap.add_argument("--out", default="data/vision-pages-sh.jsonl")
    ap.add_argument("--jobs", type=int, default=3)
    ap.add_argument("--batch", type=int, default=5)
    ap.add_argument("--subject", default="math")
    ap.add_argument("--resume", action="store_true")
    args = ap.parse_args()

    root = BASE / args.dir
    out_path = BASE / args.out
    books = [d for d in sorted(root.iterdir()) if d.is_dir()]
    print(f"{len(books)} 本书", flush=True)

    done_keys = set()
    if args.resume and out_path.exists():
        for line in out_path.open(encoding="utf-8"):
            try:
                r = json.loads(line)
                done_keys.add((r["book"], r["page"]))
            except Exception:
                pass
        print(f"resume: 已有 {len(done_keys)} 页")

    # 册次 → 图谱册次码：书目录名里带册次，从 data/shanghai-textbooks.json 取
    # **bookId 直接用清单里的** —— 册次码在两套教材里会撞车
    # （沪科版数学八上 / 物理八上 / 五四学制物理八上，册次码都一样），
    # 清单里的 bookId 带版别+学科+学制，天然不撞。
    meta = {}
    stj = BASE / "data" / "shanghai-textbooks.json"
    if stj.exists():
        for b in json.load(open(stj, encoding="utf-8"))["books"]:
            slug = re.sub(r"[^\w一-鿿]+", "_", b["title"])[:30] + "_" + b["contentId"][:8]
            meta[slug] = b

    tasks = []
    for d in books:
        m = meta.get(d.name, {})
        title = m.get("title", d.name)
        edition = m.get("edition", "")
        gbook = m.get("graphBook") or guess_graph_book(title)
        for p in sorted(d.glob("p*.jpg")):
            try:
                n = int(p.stem[1:])
            except ValueError:
                continue
            # 册次码用 ASCII（hj=沪教版 / hk=沪科版），
            # 册次用**图谱的**册次码 —— 同一册的人教/沪教/沪科是三本不同的书，
            # 但概念匹配的册次维度要跟图谱对齐。
            code = m.get("bookId") or f"sh-x-{gbook or 'x'}"
            if (code, n) in done_keys:
                continue
            tasks.append((code, title, edition, gbook, n, p))
    print(f"待处理 {len(tasks)} 页", flush=True)
    if not tasks:
        return 0

    # 按书分批
    batches = []
    cur = []
    for t in tasks:
        if cur and (cur[0][0] != t[0] or len(cur) >= args.batch):
            batches.append(cur)
            cur = []
        cur.append(t)
    if cur:
        batches.append(cur)

    fh = out_path.open("a" if args.resume else "w", encoding="utf-8")
    n_ok = n_fail = 0
    t0 = time.time()

    def work(batch):
        code, title, edition, gbook = batch[0][0], batch[0][1], batch[0][2], batch[0][3]
        pages = [t[4] for t in batch]
        paths = [t[5] for t in batch]
        prompt = V.PROMPT.replace("{subject}", "数学")
        try:
            urls = [V.upload(p) for p in paths]
            bodies = V.describe(urls, prompt,
                               accept=lambda b: V.parse_json_loose(b) is not None)
        except Exception as e:
            return [(code, title, edition, gbook, p, None, str(e)[:200]) for p in pages]
        out = []
        for (c, ti, ed, gb, pno, _path), body in zip(batch, bodies):
            parsed = V.parse_json_loose(body)
            out.append((c, ti, ed, gb, pno, parsed, None if parsed else "解析失败"))
        return out

    with ThreadPoolExecutor(max_workers=args.jobs) as ex:
        futs = [ex.submit(work, b) for b in batches]
        done = 0
        for fu in as_completed(futs):
            for code, title, edition, gbook, pno, parsed, err in fu.result():
                rec = {
                    "id": f"{code}-p{pno}",
                    "book": code,
                    "subject": args.subject,
                    "bookZh": title,
                    "edition": edition,
                    "graphBook": gbook,
                    "page": pno,
                    "source": "国家中小学智慧教育平台（页图）",
                    "ok": parsed is not None,
                }
                if parsed is not None:
                    rec["data"] = parsed
                else:
                    rec["error"] = err
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
                done += 1
                if parsed is not None:
                    n_ok += 1
                else:
                    n_fail += 1
            fh.flush()
            if done % 100 < args.batch:
                el = time.time() - t0
                print(f"  {done}/{len(tasks)}  成功 {n_ok} 失败 {n_fail}  "
                      f"{el/60:.1f} 分", flush=True)
    fh.close()
    print(f"\n完成 {done} 页：成功 {n_ok}，失败 {n_fail} → {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
