#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ISSUE-34: 视觉层 —— 用多模态视觉模型读教材扫描页，补回 OCR 丢掉的东西。

背景
----
数学教材 PDF 的文本层是坏的（公式字体的 ToUnicode 表缺失，取出来是 `!"#$%&'"()*`
和私用区字符 `狔狓犪`），OCR 只能救回汉字和一部分字母变量：

    OCR 版:   狔＝狓２   犪狓２＋犫狓＋犮   →  变量、上下标、公式全废
    视觉版:   y = x^2    ax^2 + bx + c      →  LaTeX 完整

几何图形、坐标系、表格、颜色对应关系，OCR 一律丢失，视觉能读出来。
人教九上 p45（顶点式）实测：视觉给出 11 条 LaTeX 公式 + 图 22.1-10 的顶点 (6,3)、
对称轴虚线、配色，OCR 同一页只剩「狔＝狓２」这类残骸。

产物
----
data/vision-pages.jsonl   一页一条：公式(LaTeX) / 图形语义 / 表格 / 例题步骤
data/vision-cover.json     哪些册次哪些页跑了视觉

用法
----
    python3 src/vision_pages.py --books math-9a --pages all
    python3 src/vision_pages.py --books math-9a --pages 34-64
    python3 src/vision_pages.py --books "alt:初中数学沪科技版:七上" --pages all
    python3 src/vision_pages.py --books math-9a --pages all --jobs 4 --resume
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "data" / "pdf-cache"
WORK = CACHE / "work" / "vision"
OUT = ROOT / "data" / "vision-pages.jsonl"
COVER = ROOT / "data" / "vision-cover.json"

# 册次码 -> (pdf 文件, 学科, 中文册名)
BOOKS = {
    "math-1a": ("rjb-math-1a.pdf", "math", "一年级上册"),
    "math-1b": ("rjb-math-1b.pdf", "math", "一年级下册"),
    "math-2a": ("rjb-math-2a.pdf", "math", "二年级上册"),
    "math-2b": ("rjb-math-2b.pdf", "math", "二年级下册"),
    "math-3a": ("rjb-math-3a.pdf", "math", "三年级上册"),
    "math-3b": ("rjb-math-3b.pdf", "math", "三年级下册"),
    "math-4a": ("rjb-math-4a.pdf", "math", "四年级上册"),
    "math-4b": ("rjb-math-4b.pdf", "math", "四年级下册"),
    "math-5a": ("rjb-math-5a.pdf", "math", "五年级上册"),
    "math-5b": ("rjb-math-5b.pdf", "math", "五年级下册"),
    "math-6a": ("rjb-math-6a.pdf", "math", "六年级上册"),
    "math-6b": ("rjb-math-6b.pdf", "math", "六年级下册"),
    "math-7a": ("rjb-math-7a.pdf", "math", "七年级上册"),
    "math-7b": ("rjb-math-7b.pdf", "math", "七年级下册"),
    "math-8a": ("rjb-math-8a.pdf", "math", "八年级上册"),
    "math-8b": ("rjb-math-8b.pdf", "math", "八年级下册"),
    "math-9a": ("rjb-math-9a.pdf", "math", "九年级上册"),
    "math-9b": ("rjb-math-9b.pdf", "math", "九年级下册"),
    "math-m1": ("rjb-math-m1.pdf", "math", "高中必修一"),
    "math-m2": ("rjb-math-m2.pdf", "math", "高中必修二"),
    "math-x1": ("rjb-math-x1.pdf", "math", "高中选择性必修一"),
    "math-x2": ("rjb-math-x2.pdf", "math", "高中选择性必修二"),
    "math-x3": ("rjb-math-x3.pdf", "math", "高中选择性必修三"),
    "phys-8a": ("rjb-phys-8a.pdf", "physics", "八年级上册"),
    "phys-8b": ("rjb-phys-8b.pdf", "physics", "八年级下册"),
    "chem-9a": ("rjb-chem-9a.pdf", "chemistry", "九年级上册"),
    "chem-9b": ("rjb-chem-9b.pdf", "chemistry", "九年级下册"),
    "bio-7a": ("rjb-bio-7a.pdf", "biology", "七年级上册"),
    "bio-7b": ("rjb-bio-7b.pdf", "biology", "七年级下册"),
    "bio-8a": ("rjb-bio-8a.pdf", "biology", "八年级上册"),
    "bio-8b": ("rjb-bio-8b.pdf", "biology", "八年级下册"),
}

# 人教 alt 目录里的书跟 rjb-math-* 是同一批文件，别重复跑
ALT_SKIP = {"初中数学人教版"}

PROMPT = """这是一页中国初中{subject}教材扫描件。请严格按页面原文提取，不要补充页面上没有的内容。

按下面四类输出，用 JSON：
1. "formulas": 数组，每项 {"latex": "公式的 LaTeX", "context": "它在页面上出现的位置/用途"}。
   变量名要还原（如 y、x、a、b、c、h、k），上下标、分数、幂次、根号必须准确。
2. "figures": 数组，每项 {"caption": "图号", "kind": "坐标系/几何图形/表格/实验装置/示意图",
   "description": "图形里到底画了什么"}。坐标系要说明：画了哪几条曲线、每条曲线叫什么、
   开口方向、顶点坐标、对称轴方程、与坐标轴的交点、点的颜色对应哪条曲线。
   几何图形要说明：有哪些点、线段、角、标注了什么、图形关系。
3. "tables": 数组，每项 {"caption": "表号或位置", "rows": [["表头"],["数据"],...] }。
4. "exercises": 数组，每项 {"type": "例题/思考/探究/练习", "stem": "题干",
   "steps": ["解答步骤或提示"]}。

如果某类内容本页没有，对应数组留空。"""

_print_lock = threading.Lock()


def run(cmd: list[str], timeout: int = 300) -> str:
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(f"{cmd[0]} 失败: {_clean_err(r.stderr)}")
    return r.stdout


def _clean_err(s: str) -> str:
    """去掉 node 的实验性警告，只留真正的错误。"""
    keep = []
    for ln in (s or "").splitlines():
        t = ln.strip()
        if not t:
            continue
        if t.startswith("(node:") or "UNDICI-EHPA" in t or t.startswith("(Use `MiniMax Code"):
            continue
        keep.append(t)
    return " | ".join(keep)[:300]


def upload(path: Path, tries: int = 3) -> str:
    last = None
    for i in range(tries):
        try:
            out = run(["mcode-tools", "upload_temp_url", str(path)], timeout=180)
            return json.loads(out[out.index("{"):])["temp_url"]
        except Exception as e:
            last = e
            time.sleep(1.5 * (i + 1))
    raise RuntimeError(f"上传失败 {path.name}: {last}")


def describe(urls: list[str], prompt: str, tries: int = 3) -> list[str]:
    """批量视觉问答，返回每页一段正文。失败会重试。"""
    args = json.dumps(
        {"image_info": [{"url": u, "prompt": prompt} for u in urls]},
        ensure_ascii=False,
    )
    last = None
    for i in range(tries):
        try:
            out = run(
                ["mcode-tools", "connector", "call", "connector__matrix__describe_images",
                 "--args", args],
                timeout=600,
            )
            j = json.loads(out[out.index("{"):])
            bodies = []
            for r in j.get("results", []) or []:
                if r.get("success") and r.get("description"):
                    bodies.append(r["description"])
                else:
                    bodies.append(None)
            # 整批全空也算失败，重试
            if any(b for b in bodies):
                return bodies
            last = RuntimeError("返回全空")
        except Exception as e:
            last = e
        time.sleep(2.0 * (i + 1))
    raise RuntimeError(f"视觉问答失败: {last}")


def parse_json_loose(text):
    """模型返回里常裹着 markdown 代码块或前后说明，尽力抠出 JSON。"""
    if not text:
        return None
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*", "", t)
    t = re.sub(r"\s*```$", "", t)
    try:
        return json.loads(t)
    except Exception:
        pass
    start = t.find("{")
    while start != -1:
        depth, instr, esc = 0, False, False
        for i in range(start, len(t)):
            ch = t[i]
            if esc:
                esc = False
                continue
            if ch == "\\":
                esc = True
                continue
            if ch == '"':
                instr = not instr
                continue
            if instr:
                continue
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(t[start:i + 1])
                    except Exception:
                        break
        start = t.find("{", start + 1)
    return None


def render(pdf: Path, page_no: int, zoom: float = 2.2) -> Path:
    import fitz
    WORK.mkdir(parents=True, exist_ok=True)
    out = WORK / f"{pdf.stem}-p{page_no}.png"
    if out.exists() and out.stat().st_size > 1000:
        return out
    doc = fitz.open(pdf)
    try:
        pix = doc[page_no - 1].get_pixmap(matrix=fitz.Matrix(zoom, zoom))
        pix.save(out)
    finally:
        doc.close()
    return out


def parse_pages(spec: str, total: int) -> list[int]:
    if spec.strip() in ("all", "*", ""):
        return list(range(1, total + 1))
    pages: list[int] = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            pages.extend(range(int(a), int(b) + 1))
        else:
            pages.append(int(part))
    return sorted(p for p in set(pages) if 1 <= p <= total)


def resolve_book(code: str):
    """返回 (pdf路径, 学科, 册次中文名, 出版社)。"""
    if code.startswith("alt:"):
        _, pub, vol = code.split(":", 2)
        pdf = CACHE / "alt" / pub / f"{vol}.pdf"
        subject = "math" if "数学" in pub else "biology" if "生物" in pub else \
                  "chemistry" if "化学" in pub else "physics" if "物理" in pub else "unknown"
        return pdf, subject, vol, pub
    if code not in BOOKS:
        return None
    fname, subject, bookzh = BOOKS[code]
    return CACHE / fname, subject, bookzh, "人教版"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--books", required=True, help="册次码，逗号分隔。math-9a 或 alt:初中数学沪科技版:七上")
    ap.add_argument("--pages", default="all", help="all 或 34-64 或 38,45")
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--cover", default=str(COVER))
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--batch", type=int, default=5, help="每次调用放几页")
    ap.add_argument("--jobs", type=int, default=3, help="并发批次数")
    ap.add_argument("--zoom", type=float, default=2.2)
    ap.add_argument("--keep-raw", action="store_true")
    ap.add_argument("--limit", type=int, default=0, help="每册最多处理多少页")
    args = ap.parse_args()

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cover_path = Path(args.cover)
    done: set[tuple[str, int]] = set()
    if args.resume and out_path.exists():
        # **失败的记录不算 done** —— 它们要重跑。
        # 重跑时先把失败记录从文件里剔掉再追加，否则同一个 id 会出现两次。
        kept, dropped = [], 0
        for line in out_path.open(encoding="utf-8"):
            try:
                r = json.loads(line)
            except Exception:
                dropped += 1
                continue
            if r.get("ok"):
                kept.append(line)
                done.add((r["book"], r["page"]))
            else:
                dropped += 1
        if dropped:
            with out_path.open("w", encoding="utf-8") as f:
                f.writelines(kept)
        with _print_lock:
            print(f"resume: 已有 {len(done)} 页成功，{dropped} 页失败要重跑", flush=True)

    tasks = []          # (book_code, pdf, subject, bookzh, publisher, page)
    for code in args.books.split(","):
        code = code.strip()
        if not code:
            continue
        if code.startswith("alt:") and code.split(":")[1] in ALT_SKIP:
            with _print_lock:
                print(f"跳过 {code}（与人教正本重复）", flush=True)
            continue
        info = resolve_book(code)
        if not info:
            with _print_lock:
                print(f"跳过未知册次 {code}", flush=True)
            continue
        pdf, subject, bookzh, publisher = info
        if not pdf.exists():
            with _print_lock:
                print(f"跳过 {code}: 没有 {pdf}", flush=True)
            continue
        import fitz
        doc = fitz.open(pdf)
        total = doc.page_count
        doc.close()
        pages = parse_pages(args.pages, total)
        if args.limit:
            pages = pages[:args.limit]
        pages = [p for p in pages if (code, p) not in done]
        for p in pages:
            tasks.append((code, pdf, subject, bookzh, publisher, p))
        with _print_lock:
            print(f"{code} 共 {total} 页，本次处理 {len(pages)} 页", flush=True)

    if not tasks:
        print("没有待处理页面")
        return 0

    # 同一册的页连在一起做批。
    # **不要按册次码重排** —— 命令行里的顺序是有意义的
    # （比如「先把有二次函数的九上九下跑完」），重排会把它打乱。
    batches = []
    cur: list = []
    for t in tasks:
        if cur and (cur[0][0] != t[0] or len(cur) >= args.batch):
            batches.append(cur)
            cur = []
        cur.append(t)
    if cur:
        batches.append(cur)

    mode = "a" if args.resume else "w"
    fh = out_path.open(mode, encoding="utf-8")
    counter = {"n": 0, "ok": 0}
    t_start = time.time()

    def work(batch):
        code, pdf, subject, bookzh, publisher = batch[0][0], batch[0][1], batch[0][2], batch[0][3], batch[0][4]
        pages = [t[5] for t in batch]
        # 注意：PROMPT 里含 {"latex": ...} 这类 JSON 样例，不能用 str.format
        prompt = PROMPT.replace("{subject}", subject)
        recs = []
        try:
            urls = [upload(render(pdf, p, args.zoom)) for p in pages]
            bodies = describe(urls, prompt)
        except Exception as e:
            bodies = [None] * len(pages)
            err = str(e)[:200]
        else:
            err = ""
        for p, body in zip(pages, bodies):
            parsed = parse_json_loose(body)
            rec = {
                "id": f"{code}-p{p}",
                "book": code,
                "subject": subject,
                "bookZh": bookzh,
                "publisher": publisher,
                "page": p,
                "pdf": pdf.name,
                "ok": parsed is not None,
            }
            if parsed is not None:
                rec["data"] = parsed
            else:
                rec["body"] = (body or "")[:2000]
                if err:
                    rec["error"] = err
            recs.append(rec)
        return recs

    with ThreadPoolExecutor(max_workers=args.jobs) as ex:
        futs = [ex.submit(work, b) for b in batches]
        for fu in as_completed(futs):
            try:
                recs = fu.result()
            except Exception as e:
                with _print_lock:
                    print(f"批次异常: {str(e)[:200]}", flush=True)
                continue
            with _print_lock:
                for r in recs:
                    fh.write(json.dumps(r, ensure_ascii=False) + "\n")
                    counter["n"] += 1
                    if r["ok"]:
                        counter["ok"] += 1
                    d = r.get("data", {}) or {}
                    nf = len(d.get("formulas", []) or []) if isinstance(d.get("formulas"), list) else 0
                    nfig = len(d.get("figures", []) or []) if isinstance(d.get("figures"), list) else 0
                    el = time.time() - t_start
                    eta = el / max(counter["n"], 1) * (len(tasks) - counter["n"])
                    print(f"[{counter['n']}/{len(tasks)}] {r['book']} p{r['page']} "
                          f"ok={r['ok']} 公式={nf} 图={nfig} "
                          f"| 已用 {el/60:.1f} 分, 预计还剩 {eta/60:.1f} 分", flush=True)
                fh.flush()
    fh.close()

    # 覆盖清单
    cov = {}
    if cover_path.exists():
        try:
            cov = json.loads(cover_path.read_text(encoding="utf-8"))
        except Exception:
            cov = {}
    for bk, c in cov.items():
        c.setdefault("pages", [])
    for line in out_path.open(encoding="utf-8"):
        try:
            r = json.loads(line)
        except Exception:
            continue
        c = cov.setdefault(r["book"], {"subject": r["subject"], "bookZh": r["bookZh"],
                                       "publisher": r.get("publisher", ""), "pages": []})
        c["pages"].append(r["page"])
    for c in cov.values():
        c["pages"] = sorted(set(c["pages"]))
        c["pageCount"] = len(c["pages"])
    n_all = n_ok = 0
    for line in out_path.open(encoding="utf-8"):
        try:
            r = json.loads(line)
        except Exception:
            continue
        n_all += 1
        if r.get("ok"):
            n_ok += 1
    cover_path.write_text(json.dumps(
        {"_total": n_all, "_ok": n_ok, "_failed": n_all - n_ok, "books": cov},
        ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n完成 {counter['n']} 页（成功解析 {counter['ok']}）→ {out_path}")
    print(f"覆盖清单 → {cover_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
