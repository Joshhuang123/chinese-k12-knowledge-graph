#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ISSUE-42: 沪教教材的**原文层** —— OCR 页图 → 抽定义句 → 挂到概念上。

为什么人教版有、上海版没有
--------------------------
`data/concept-text.jsonl` 里，1,361 个人教概念有 **291 个带着「教材自己的定义句」**
（「在一定的空间范围内，生物与环境形成的统一整体就是生态系统」）。
上海版一张卡片上只有「教材位置 + 公式 + 难点」，**没有「教材怎么说」** ——
两个站最大的内容落差就在这儿。

为什么人教版有、上海版没有
--------------------------
人教版拿的是**教材 PDF**，OCR 直接跑在 PDF 渲染页上；
上海版拿的是国家平台的**页图 JPEG**，没有 PDF 那一层。
但 tesseract 吃 JPEG 没问题（实测 0.85 秒/页），
所以这条路是通的。

怎么把句子挂到概念上
--------------------
**不用重新做概念↔页的匹配** —— 视觉层已经做过了
（`data/concept-vision-sh.jsonl` 里，每个概念在每本书的哪些页上都有记录）。
这一层只做一件事：**把那些页上的句子读出来，判断哪句是「定义句」**。

判据跟人教版完全一致（`src/pdf_to_units.py` 的 `quote_kind`）：
`叫做|称为|是指|指的是|定义为|就是|即为|全称是|通常指` → definition；
`定理|性质|公式|定律|公理|推论|法则|原理|结论` → theorem。

跑法
----
    python3 src/ocr_sh.py            # OCR + 挂概念（两段）
    python3 src/ocr_sh.py --ocr      # 只 OCR
    python3 src/ocr_sh.py --match    # 只挂概念（OCR 已跑过）
"""
from __future__ import annotations

import argparse
import collections
import concurrent.futures
import difflib
import json
import pathlib
import re
import subprocess
import sys
import time

BASE = pathlib.Path(__file__).resolve().parent.parent
IMG = BASE / "data" / "pdf-cache" / "hujiao"
TESSERACT = "/opt/homebrew/bin/tesseract"
STJ = BASE / "data" / "shanghai-textbooks.json"
CVIS = BASE / "data" / "concept-vision-sh.jsonl"
OUT_LESSONS = BASE / "data" / "lessons-sh.jsonl"
OUT_TEXT = BASE / "data" / "concept-text-sh.jsonl"

# 跟人教版一套判据 —— 两边的「定义句」得是同一种东西
RE_SENT = re.compile(r"[^。！？；!?;\n]+[。！？；!?;]?")
RE_DEF = re.compile(r"(叫做|称为|是指|指的是|定义为|就是|即为|全称是|通常指)")
RE_THM = re.compile(r"(定理|性质|公式|定律|公理|推论|法则|原理|结论)")
RE_EX = re.compile(r"^(例[0-9０-９一二三四五六七八九十]*[：:.、]|例题|如图|下图|上图中)")
RE_ASK = re.compile(r"[?？]$")
KIND_RANK = {"definition": 0, "theorem": 1, "text": 2, "example": 3,
             "question": 4, "title": 5}


def strip_paren(nm: str) -> str:
    return re.sub(r"[（(][^）)]*[）)]", "", nm or "").strip()


def sentences(text):
    out = []
    for s in RE_SENT.findall(text):
        s = re.sub(r"\s+", "", s)
        s = re.sub(r"^[0-9．.、]+\s*", "", s)
        if len(s) >= 6:
            out.append(s)
    return out


def cjk_ratio(text):
    if not text:
        return 0.0
    cjk = sum(1 for ch in text if "一" <= ch <= "鿿")
    return cjk / len(text)


def quote_kind(s: str, concept: str) -> str:
    s = s.strip()
    if re.sub(r"[\s。．.、，,：:；;　]", "", s) == \
            re.sub(r"[\s。．.、，,：:；;　]", "", concept or ""):
        return "title"
    # **问句先判** ——
    # 「有人将 ATP 称为细胞的『能量货币』，你觉得这个比喻合适吗？」
    # 里有「称为」，按定义句收下了 —— 但它明明是个讨论题。
    # 问句不是定义。
    if RE_ASK.search(s):
        return "question"
    if RE_DEF.search(s):
        return "definition"
    if RE_THM.search(s):
        return "theorem"
    if RE_EX.match(s):
        return "example"
    return "text"


def ocr_page(path: pathlib.Path) -> str:
    try:
        r = subprocess.run([TESSERACT, str(path), "stdout", "-l", "chi_sim", "--psm", "3"],
                           capture_output=True, text=True, timeout=120)
        return r.stdout or ""
    except Exception:
        return ""


def phase_ocr(jobs: int) -> int:
    books = json.load(open(STJ, encoding="utf-8"))["books"]
    meta = {}
    for b in books:
        slug = re.sub(r"[^\w一-鿿]+", "_", b["title"])[:30] + "_" + b["contentId"][:8]
        meta[slug] = b

    tasks = []
    for d in sorted(IMG.iterdir()):
        if not d.is_dir():
            continue
        b = meta.get(d.name)
        if not b:
            continue
        for p in sorted(d.glob("p*.jpg")):
            try:
                n = int(p.stem[1:])
            except ValueError:
                continue
            tasks.append((b, n, p))
    print(f"要 OCR {len(tasks)} 页（{len(set(b['bookId'] for _, _, _ in tasks))} 本）", flush=True)

    done = set()
    if OUT_LESSONS.exists():
        for line in OUT_LESSONS.open(encoding="utf-8"):
            try:
                r = json.loads(line)
                done.add((r["book"], r["page"]))
            except Exception:
                pass
        print(f"已有 {len(done)} 页，跳过", flush=True)
    tasks = [t for t in tasks if (t[0]["bookId"], t[1]) not in done]
    if not tasks:
        print("没有要跑的页")
        return 0

    fh = OUT_LESSONS.open("a", encoding="utf-8")
    t0 = time.time()
    n_ok = 0

    def one(t):
        b, n, p = t
        return (b, n, ocr_page(p))

    with concurrent.futures.ThreadPoolExecutor(max_workers=jobs) as ex:
        for i, (b, n, raw) in enumerate(ex.map(one, tasks), 1):
            sents = sentences(raw)
            rec = {
                "id": f"{b['bookId']}-p{n}",
                "book": b["bookId"],
                "subject": b["subject"],
                "page": n,
                "text": raw,
                "sentences": len(sents),
                "cjkRatio": round(cjk_ratio(raw), 3),
                "isToc": bool(re.search(r"目\s*录", raw[:400])),
                "source": "国家中小学智慧教育平台（页图 OCR）",
            }
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            n_ok += 1
            if i % 200 == 0:
                fh.flush()
                el = time.time() - t0
                print(f"  {i}/{len(tasks)}  {el/60:.1f} 分  {i/max(el,1)*60:.0f} 页/分", flush=True)
    fh.close()
    print(f"OCR 完成 {n_ok} 页，用时 {(time.time()-t0)/60:.1f} 分 → {OUT_LESSONS}")
    return 0


def phase_match() -> int:
    # 页 → 正文
    page_text = {}
    for line in OUT_LESSONS.open(encoding="utf-8"):
        try:
            r = json.loads(line)
        except Exception:
            continue
        page_text[(r["book"], r["page"])] = r

    # 概念 → (书, 页)
    out = {}
    n_c = 0
    for line in CVIS.open(encoding="utf-8"):
        if not line.strip():
            continue
        c = json.loads(line)
        cid = c["id"]
        nm = c["name"]
        core = strip_paren(nm) or nm
        quotes, kinds, pages = [], [], []
        for bid, b in (c.get("books") or {}).items():
            for pg in (b.get("pages") or []):
                pr = page_text.get((bid, pg))
                if not pr:
                    continue
                pages.append(pg)
                for s in sentences(pr.get("text", "")):
                    if len(s) > 160:
                        continue
                    # **概念名要在句子里**（含去括号的短名）
                    if nm not in s and not (core and core in s):
                        continue
                    k = quote_kind(s, nm)
                    if k == "title":
                        continue
                    # **断在半截的句子不要** ——
                    # OCR 把公式读成残骸，句子尾巴常缺一块
                    # （「用公式表示为」后面没了）。
                    # 判据是**结尾是个连词**（句子明显还没说完），
                    # 而不是「必须以句号结尾」—— 那样会砍掉太多真句子。
                    if s[-1] in "为是和与、，：:等或则而且":
                        continue
                    if s not in quotes:
                        quotes.append(s)
                        kinds.append(k)
        if not quotes:
            continue
        order = sorted(range(len(quotes)),
                       key=lambda i: (KIND_RANK.get(kinds[i], 9), -len(quotes[i])))
        rec = {
            "id": cid,
            "name": nm,
            "subject": c.get("subject"),
            "books": sorted({bid for bid, b in (c.get("books") or {}).items()
                             for pg in (b.get("pages") or []) if (bid, pg) in page_text}),
            "pages": sorted(set(pages)),
            "quotes": [quotes[i] for i in order][:8],
            "quoteKinds": [kinds[i] for i in order][:8],
            "hasDefinition": any(k == "definition" for k in kinds),
            "match": "exact",
            "source": "国家中小学智慧教育平台（页图 OCR）",
        }
        out[cid] = rec
        n_c += 1

    with OUT_TEXT.open("w", encoding="utf-8") as fh:
        for cid in sorted(out, key=lambda k: out[k]["name"]):
            fh.write(json.dumps(out[cid], ensure_ascii=False) + "\n")
    n_def = sum(1 for r in out.values() if r["hasDefinition"])
    print(f"概念原文层 {n_c} 个概念 · 有定义句 {n_def} 个 → {OUT_TEXT}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--jobs", type=int, default=8)
    ap.add_argument("--ocr", action="store_true")
    ap.add_argument("--match", action="store_true")
    args = ap.parse_args()
    do_ocr = args.ocr or not args.match
    do_match = args.match or not args.ocr
    if do_ocr:
        phase_ocr(args.jobs)
    if do_match:
        if not OUT_LESSONS.exists():
            print("还没有 OCR 结果，先跑 --ocr")
            return 1
        phase_match()
    return 0


if __name__ == "__main__":
    sys.exit(main())
