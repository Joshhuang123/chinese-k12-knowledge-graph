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
import subprocess
import sys

BASE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE / "src"))
from build_learn_site import site_payload   # noqa: E402

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

    # ── 人教版的教材正文：从本地 PDF 取 ──
    # 沪教用 OCR 文本层（lessons-sh.jsonl），人教没有那套，
    # 但我们有 PDF —— 而且**页码就是 PDF 的扫描页**，天然对齐。
    rjb_index = {}
    # ⚠️ **读页面真正加载的那个文件** ——
    #   页面 loadScript('data/page-images-rjb.js')，这里原来读的是 .json。
    #   两份索引曾经对不上（1,018 条重合，各有 100 多条独有；.js 里还有 37 条
    #   指向不存在的文件），于是门禁校验的东西和线上跑的东西不是一份 ——
    #   真坏了看不见，假坏了报警。
    #   现在两个文件由 src/render_page_images.py 从同一份索引生成，
    #   这里读 .js，并**额外断言 .js 与 .json 一致**。
    idx_f = DATA / "page-images-rjb.js"
    if idx_f.exists():
        rjb_index = json.loads(
            idx_f.read_text(encoding="utf-8").split("=", 1)[1].rstrip().rstrip(";"))
    idx_j = DATA / "page-images-rjb.json"
    if idx_f.exists() and idx_j.exists():
        a = set(rjb_index), {k for k in rjb_index}
        b = {k for k in json.loads(idx_j.read_text(encoding="utf-8"))}
        check(rjb_index == json.loads(idx_j.read_text(encoding="utf-8")),
              "page-images 的 .js（页面加载的）和 .json 是同一份",
              f"差异 {len(a[1] ^ b)} 册")
    PDFC = DATA / "pdf-cache"
    SUBJ_ABBR = {"biology": "bio", "chemistry": "chem", "physics": "phys", "math": "math"}
    HIGH_VOL = {"bx1": "m1", "bx2": "m2", "bx3": "m3",
                "xzxbx1": "x1", "xzxbx2": "x2", "xzxbx3": "x3"}
    _docs = {}

    def _rjb_pdf(pbk):
        if pbk in _docs:
            return _docs[pbk]
        try:
            head, rest = pbk.split("-", 1)
            rest = HIGH_VOL.get(rest, rest)
            p = PDFC / f"rjb-{SUBJ_ABBR.get(head, head)}-{rest}.pdf"
            import fitz
            try:
                fitz.TOOLS.mupdf_display_errors(False)
            except Exception:
                pass
            d = fitz.open(p) if p.exists() else None
        except Exception:
            d = None
        _docs[pbk] = d
        return d

    def rjb_pages(pbk):
        d = _rjb_pdf(pbk)
        return d.page_count if d else None

    def rjb_text(pbk, pg):
        d = _rjb_pdf(pbk)
        if not d or pg < 1 or pg > d.page_count:
            return ""
        try:
            return d[pg - 1].get_text()
        except Exception:
            return ""

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
        # ⚠️ **三个版本的页图来源不同**，门禁不能只认 `loc.bk`：
        #   沪教版  loc.bk     = 沪教书号（sh-hk-数学-s-7b…）→ 平台扫描页图
        #   人教版  loc.pdfBook = 教材册次码（math-7a…）       → **本地 PDF 渲染的页图**
        #   小学科学 loc.pdfBook = kx/s6-1a…                   → 还没接（见下）
        #
        # 原来只判 `loc.bk`，于是人教版那条分支**一条都没跑**，
        # 判据形同虚设（而它自己还在报「人教无教材原页图」——口径也过时了）。
        withimg = [n for n in nodes if n.get("loc", {}).get("scan")]
        if tag in ("sh", "rjb"):
            check(len(withimg) > 0, f"{tag}: 有节点带页图",
                  f"0 个（页面上的「教材原页」这一块会是空的）")
        else:
            print(f"  · {tag}: 无教材原页图（小学科学还没接页图）—— 已知限制")
        bad_page = 0
        dirish = 0
        notmentioned = 0
        judged = 0              # 真正读到过页正文的节点数（没有 PDF 时是 0）
        missing_file = 0
        for n in withimg:
            loc = n["loc"]
            bk = loc.get("bk") or ""
            pbk = loc.get("pdfBook") or ""
            pg = loc["scan"][0]
            if pbk:
                # 人教版：页码是本地 PDF 的扫描页，总页数按 PDF 算
                total = rjb_pages(pbk)
                txt = rjb_text(pbk, pg)
                # 页图文件必须真的在磁盘上
                f = rjb_index.get(pbk, {}).get(str(pg))
                if not f or not (BASE / f).exists():
                    missing_file += 1
            else:
                total = (TB.get(bk) or {}).get("pages")
                txt = ocr.get(bk, {}).get(pg) or ""
            if total and pg > total:
                bad_page += 1
            # 目录页特征：正文里出现「……第 N 页」这种目录条目串
            if len(re.findall(r"\.{3,}\s*\d+", txt)) >= 3:
                dirish += 1
            # 只有**真读到正文**才能判断「这一页有没有提到这个概念」。
            # 空串 = 没读到（PDF 不在 / 那一页没文本层），不是「没提到」。
            if txt:
                judged += 1
                if n["n"] not in txt:
                    notmentioned += 1
        check(bad_page == 0, f"{tag}: 页码都在该书总页数内",
              f"{bad_page} 个越界")
        check(dirish == 0, f"{tag}: 显示页不是目录页",
              f"{dirish} 个是目录页（正文里出现大量「…N 页」条目）")
        if tag == "rjb":
            check(missing_file == 0, f"{tag}: 页图文件都在磁盘上",
                  f"{missing_file} 个索引指向的文件不存在")
        # 「正文里提到概念」不是硬性要求（有些概念的页图是插图页），
        # 但不能太多 —— 超过 60% 说明页码挑错了
        #
        # ⚠️ **先分清「页正文里没有概念名」和「压根没读到正文」** ——
        # 本地教材 PDF（data/pdf-cache/）是**不入库**的（版权），随时可能不在。
        # 没有 PDF 时 rjb_text() 返回空串，于是每个节点都算「没提到」→
        # 报出「100% 的页正文里没有概念名」这种**整齐得可疑**的数字。
        # 那是**输入缺失**，不是「页码全挑错了」—— 两回事，必须分开，
        # 否则一个可选输入没了，整个判据就变成一句假警报。
        # （判据守的是意图：页码挑对没有，不是「必须能读到 PDF」。）
        if withimg:
            if judged > 0:
                ratio = notmentioned / judged
                check(ratio <= 0.6, f"{tag}: 显示页大多提到这个概念",
                      f"{notmentioned}/{judged} = {ratio:.0%} 的页正文里没有概念名")
            else:
                print(f"  · {tag}: 本地没有教材 PDF（data/pdf-cache/ 不入库），"
                      f"跳过「页正文是否提到概念」这条（{len(withimg)} 个节点无从判断）")

        # ⑤ **先修/后继必须跟站点 payload 对得上** ——
        # 这条是**踩坑踩出来的**（ISSUE-53）：
        #   build_learn_site.py 里教材原话那个内层循环
        #   `for i in order[:6]` **覆盖了外层的节点下标 i**，
        #   于是 `pre_of.get(i, [])` 查的是**引文序号**（0–5），不是节点下标。
        #   结果：**每个有教材原话的概念**，先修和后继全是**别的概念**的 ——
        #   而且「49% 的沪教概念前置完全相同」这种整齐数字，
        #   一看就该怀疑是 bug 而不是数据特征（差点当成上游数据问题去过滤）。
        #
        # 判据：**独立地**读站点 payload，拿它算这个节点的前置，
        # 再跟学习页数据里的对。两者必须一致。
        # 判别力：把 build_learn_site.py 里的 `qi` 改回 `i` → 这条立刻红。
        if tag == "rjb":
            payload = site_payload(BASE / "index.html")
        elif tag == "sh":
            payload = site_payload(BASE / "shanghai.html")
        else:
            payload = site_payload(BASE / "kx.html")
        if payload:
            pnodes = payload["nodes"]
            pre_of = collections.defaultdict(list)
            for e in payload["edges"]:
                pre_of[e[0]].append(e[1])
            checked = mismatch = 0
            bad = []
            for n in nodes:
                if not n.get("pre"):
                    continue
                checked += 1
                if checked > 3000:
                    break
                i = n["i"]
                if not (0 <= i < len(pnodes)) or pnodes[i][1] != n["n"]:
                    continue
                expect = [pnodes[p][1] for p in pre_of.get(i, [])][:12]
                got = [nm for _, nm in n["pre"]]
                if expect != got:
                    mismatch += 1
                    if len(bad) < 3:
                        bad.append((n["n"], expect[:3], got[:3]))
            check(mismatch == 0, f"{tag}: 先修跟站点 payload 对得上",
                  f"{mismatch} 个概念对不上，例：{bad[:2]}")

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

    # ⑥ 成片必须**真的能解码** ——
    #   2026-10-28 撞上：21 条成片里有 1 条 mp4 的 mdat 是坏的
    #   （「Invalid NAL unit size」× 4000+），文件在、封面帧也在、索引也正常，
    #   **所有已有的检查都显示正常** —— 但视频播不出来。
    #
    #   ⚠️ `ffprobe` 只报时长是**抓不住**的：moov atom 完整，
    #   时长读得出来，但 mdat 里的数据是垃圾 → 探时长通过、解码失败。
    #   所以判据必须**整解码一遍**（`ffmpeg -f null -`），一条 0.66 秒。
    vids = sorted((BASE / "video").glob("*.mp4"))
    if vids:
        broken = []
        for v in vids:
            try:
                r = subprocess.run(
                    ["ffmpeg", "-v", "error", "-i", str(v), "-f", "null", "-"],
                    capture_output=True, text=True, timeout=60)
                errs = sum(1 for ln in r.stderr.splitlines()
                           if "Invalid NAL" in ln or "missing picture" in ln
                           or "Error splitting" in ln)
                # ⚠️ **必须看退出码** ——
                #   只数那三句错误串，**「mdat 被清零」「上传截断」「零字节」全都判绿**
                #   （verifier 实测：截断一半的坏文件 ffmpeg rc=183，但三句错误串一条都没有，
                #    stderr 里写的是「moov atom not found」/「Invalid data found…」）。
                #   退出码才是「这个文件到底能不能解码」的权威。
                if errs or r.returncode != 0:
                    broken.append(f"{v.name}({errs or 'rc=' + str(r.returncode)})")
            except Exception as e:
                broken.append(f"{v.name}({e})")
        check(not broken, f"{len(vids)} 条成片都能整解码（不是只有文件在）",
              " | ".join(broken[:3]) if broken else "")
        # 每条成片都得有封面帧（播放器是 preload="none"，没封面就是个黑框）
        noposter = [v.stem for v in vids if not (BASE / "video" / f"{v.stem}.jpg").exists()]
        check(not noposter, "每条成片都有封面帧", " | ".join(noposter[:3]))

        # ⑦ 成片文件与索引必须**一一对应** ——
        #   2026-10-28 撞上：索引是**累积式**的，只处理这轮跑过的稿子，
        #   其余靠「读磁盘再并进来」保住 —— 而那个合并只加不减，
        #   加上循环里清「早期裸 id 键」的 pop，
        #   就出现了条目被删掉**再也补不回来**的情况：
        #   两条视频的 mp4 文件一直在，索引里却没了 → 学习页上挂不出来。
        #   现在索引改成**全量重建**，这条判据守住它。
        try:
            vidx = json.loads((DATA / "learn-videos.json").read_text(encoding="utf-8"))
        except Exception:
            vidx = {}
        indexed = {v.get("mp4") for v in vidx.values()
                   if isinstance(v, dict) and v.get("mp4")}
        on_disk = {f"video/{v.name}" for v in vids}
        orphan = sorted(on_disk - indexed)
        check(not orphan, "每条成片都在索引里（挂得出来）",
              " | ".join(orphan[:3]) if orphan else f"{len(vids)} 条")
        ghost = sorted(p for p in indexed - on_disk if p.startswith("video/"))
        check(not ghost, "索引里没有指向不存在文件的条目", " | ".join(ghost[:3]))
    else:
        print("  · 没有成片，跳过解码检查")

    # ⑧ 三个成品的「去学习页」链接：版本要对、相对路径要对
    #    同一份模板产出两个深度（index.html 在根、viz/知识图谱3D.html 在子目录），
    #    相对路径写死的话 viz 那份会指到 viz/learn.html → **404**（线上实测过）。
    for f, ver, base in (("index.html", "rjb", "./learn.html"),
                         ("viz/知识图谱3D.html", "rjb", "../learn.html"),
                         ("shanghai.html", "sh", "./learn.html"),
                         ("kx.html", "kx", "./learn.html")):
        p = BASE / f
        if not p.exists():
            check(False, f"{f} 存在")
            continue
        src = p.read_text(encoding="utf-8")
        want = f'{base}?v={ver}'
        check(want in src, f"{f}: 去学习页链接指向 {want}", "" if want in src else
              "（版本或深度不对）")
        check("__LEARN_BASE__" not in src and "__LEARN_VER__" not in src,
              f"{f}: 没有漏掉的占位符")

    print(f"\n{'=' * 46}\n通过 {ok} · 失败 {fail}")
    return 1 if fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
