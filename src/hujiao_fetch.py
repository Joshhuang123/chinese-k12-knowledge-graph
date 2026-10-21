#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
从国家中小学智慧教育平台取**上海教材**（沪教版 / 沪科版）的整本页图。

数据链路（都是从平台的 app bundle 里挖出来的，不是猜的路径）
--------------------------------------------------------
标签树   /zxx/ndrs/tags/tch_material_tag.json          → 教材分类树
教材索引 /zxx/ndrs/resources/tch_material/part_*.json  → 全部 3,565 本教材的元数据
         （清单在 /zxx/ndrs/resources/tch_material/version/data_version.json 里给出分片地址）
教材详情 /zxx/ndrv2/resources/tch_material/details/{id}.json
         → custom_properties.requirements[].pagesize = 全书总页数
         → ti_items[].ti_storages[] = 页图存储基址
页图     {基址}/{页号}.jpg                               → 1303×1842 的 JPEG

为什么用页图而不是 PDF
--------------------
平台的 PDF 是 `assets_document` 资源，在 OSS 上、跟页图不是一个桶，
从本机拉不到（403）。**页图是能拉到的**（HTTP 200），
而且页图就是教材扫描的每一页 —— 正好是我们视觉层需要的东西。

跑法
----
    python3 src/hujiao_fetch.py --list          # 只列清单
    python3 src/hujiao_fetch.py --download      # 下页图
    python3 src/hujiao_fetch.py --download --only math
"""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import pathlib
import re
import sys
import urllib.request

BASE = pathlib.Path("/Users/huangjunhai/Documents/个人/项目/中文知识图谱")
WORK = BASE / "data" / "pdf-cache" / "work"
PARTS = WORK / "parts"
IMG_DIR = BASE / "data" / "pdf-cache" / "hujiao"

TAGS_URL = "https://bdcs-file-1.ykt.cbern.com.cn/zxx/ndrs/tags/tch_material_tag.json"
VER_URL = ("https://bdcs-file-1.ykt.cbern.com.cn/zxx/ndrs/resources/tch_material/"
           "version/data_version.json")
DET_TPL = ("https://bdcs-file-1.ykt.cbern.com.cn/zxx/ndrv2/resources/"
           "tch_material/details/{id}.json")
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
HDRS = {"User-Agent": UA, "Referer": "https://basic.smartedu.cn/"}

# 上海的两套教材
SH_PUBS = {
    "上海教育出版社": "沪教版",
    "上海科学技术出版社": "沪科版",
}
SUBJ_WANT = {"数学", "物理", "化学", "科学"}


def get_json(url, tries=3):
    last = None
    for _ in range(tries):
        try:
            req = urllib.request.Request(url, headers=HDRS)
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.load(r)
        except Exception as e:
            last = e
    raise last


def download(url, path, tries=3):
    last = None
    for _ in range(tries):
        try:
            req = urllib.request.Request(url, headers=HDRS)
            with urllib.request.urlopen(req, timeout=60) as r:
                data = r.read()
            if len(data) < 3000:        # 太小多半是错误页
                raise RuntimeError(f"内容过小 {len(data)}B")
            path.write_bytes(data)
            return len(data)
        except Exception as e:
            last = e
    raise last


def load_index():
    """教材索引：4 个分片。"""
    if not PARTS.exists() or not list(PARTS.glob("part_*.json")):
        PARTS.mkdir(parents=True, exist_ok=True)
        man = get_json(VER_URL)
        for u in man.get("urls", "").split(","):
            u = u.strip()
            if not u:
                continue
            name = "part_" + u.rsplit("/", 1)[-1].replace(".json", "") + ".json"
            (PARTS / name).write_bytes(download_bytes(u))
    items = []
    for f in sorted(PARTS.glob("part_*.json")):
        items += json.load(open(f, encoding="utf-8"))
    return items


def download_bytes(url):
    req = urllib.request.Request(url, headers=HDRS)
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read()


def pub_of(it):
    s = json.dumps(it, ensure_ascii=False)
    for p in SH_PUBS:
        if p in s:
            return p
    return ""


def subject_of(it):
    """学科从**标题**认。

    `global_label` 里没有学科标签，只有「zxx」「三年级下册」和一个
    不透明的 tag id（学科/版本/册次都编码在里面），认不出来。
    标题里带「数学」「物理」「化学」「科学」就够用了。
    """
    t = (it.get("global_title") or {}).get("zh-CN", "")
    for s in SUBJ_WANT:
        if s in t:
            return s
    return ""


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
    (re.compile(r"选择性必修\s*第一册"), "xzxbx1"),
    (re.compile(r"选择性必修\s*第二册"), "xzxbx2"),
    (re.compile(r"选择性必修\s*第三册"), "xzxbx3"),
    # **「选择性必修」要排在「必修」前面** —— 「选择性必修第一册」里
    # 也含「必修第一册」，先匹配到「必修」的话全都掉进 bx1，
    # 跟「必修第一册」撞成同一个 id。
    (re.compile(r"必修\s*第一册"), "bx1"), (re.compile(r"必修\s*第二册"), "bx2"),
    (re.compile(r"必修\s*第三册"), "bx3"), (re.compile(r"必修\s*第四册"), "bx4"),
    # **数字版**：高中化学/物理的选必修是「选择性必修1 化学反应原理」这种
    (re.compile(r"选择性必修\s*1(?![\d])"), "xzxbx1"),
    (re.compile(r"选择性必修\s*2(?![\d])"), "xzxbx2"),
    (re.compile(r"选择性必修\s*3(?![\d])"), "xzxbx3"),
    # 全一册：初中物理/化学的「九年级全一册」对上图谱的 '9'（物理就是这么记的）
    (re.compile(r"八年级全一册"), "8"),
    (re.compile(r"九年级全一册"), "9"),
    (re.compile(r"七年级全一册"), "7"),
]


def guess_graph_book(title: str) -> str:
    """教材自己的册次名 → 图谱的册次码。"""
    for pat, code in BOOK_GUESS:
        if pat.search(title):
            return code
    return ""


def base_of(it):
    """从 preview 的第一个 URL 里抽出页图基址（含版本号）。"""
    pv = (it.get("custom_properties") or {}).get("preview") or {}
    for u in pv.values():
        m = re.match(r"(https://r\d-ndr\.ykt\.cbern\.com\.cn/.*?/transcode/image)/", u)
        if m:
            return m.group(1)
    return ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--download", action="store_true")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--only", default="", help="按学科过滤，如 math")
    ap.add_argument("--jobs", type=int, default=6)
    args = ap.parse_args()

    print("拉教材索引…", flush=True)
    items = load_index()
    print(f"索引 {len(items)} 本")

    want = {"数学": "math", "物理": "physics", "化学": "chemistry", "科学": "science"}
    if args.only:
        args.only = args.only.lower()

    # **清单永远写全量** —— `--only` 只影响打印和下载。
    # 原来每跑一次 --only 就覆盖一次清单，跑完 --only science 之后
    # 清单里就没有数学书了，下载好的书在下游认不出自己是哪本。
    sel = []
    for it in items:
        p = pub_of(it)
        if not p:
            continue
        s = subject_of(it)
        if not s:
            continue
        t = (it.get("global_title") or {}).get("zh-CN", "")
        b = base_of(it)
        if not b:
            continue
        sel.append({
            "contentId": it["id"], "title": t, "publisher": p,
            "edition": SH_PUBS[p], "subject": s, "imageBase": b,
        })
    print(f"上海教材清单：{len(sel)} 本（全部学科）")

    # 总页数要从详情接口拿
    for i, b in enumerate(sel):
        try:
            d = get_json(DET_TPL.format(id=b["contentId"]))
        except Exception as e:
            print(f"  ! 详情失败 {b['title'][:30]} {str(e)[:50]}")
            continue
        ps = None
        # **pagesize 在两处**，顶层 custom_properties 和 ti_items[0].custom_properties
        # （实测 35542837 只在后者里有）
        reqs = list((d.get("custom_properties") or {}).get("requirements") or [])
        for ti in d.get("ti_items") or []:
            reqs += list((ti.get("custom_properties") or {}).get("requirements") or [])
        for req in reqs:
            if req.get("name") == "pagesize":
                ps = req.get("value")
        b["pages"] = int(ps) if ps and str(ps).isdigit() else None
        if (i + 1) % 10 == 0:
            print(f"  {i+1}/{len(sel)}", flush=True)

    tot = sum(b.get("pages") or 0 for b in sel)
    print(f"总页数 {tot}")
    for b in sel[:20]:
        print(f"  {b['edition']:5s} {b['subject']:4s} {b['title'][:46]:48s} {b.get('pages')} 页")

    # ── 图谱册次码 + book id ────────────────────────────────────
    # **版别必须进 id** —— 沪教版和沪科版的册次码是一样的（都是 7a/7b/…），
    # 只按册次码建 id 的话两套书的同名页会互相覆盖。
    # 这跟本项目一贯的「册次码跨学科复用」是同一类坑。
    # ── 平台本身有重复条目：同一本书传过两次（contentId 不同、页数不同）──
    # 英语七上就有两个。**取页数多的** —— 那是完整版。
    # 去重键：版别 + 学科 + 册次 + 书名（去掉「（根据2022年版课程标准修订）」这类前缀）
    def dedup_key(b):
        t = re.sub(r"（根据[^）]*）", "", b["title"])
        t = re.sub(r"[\s·•，,、]", "", t)
        return (b["edition"], b["subject"], b.get("graphBook"), t)

    best = {}
    for b in sel:
        k = dedup_key(b)
        if k not in best or (b.get("pages") or 0) > (best[k].get("pages") or 0):
            best[k] = b
    dropped = len(sel) - len(best)
    sel = list(best.values())
    if dropped:
        print(f"平台重复条目去掉 {dropped} 本（取页数多的那个）")

    for b in sel:
        b["graphBook"] = guess_graph_book(b["title"])
        ed_code = {"沪教版": "hj", "沪科版": "hk"}.get(b["edition"], "x")
        # **id 必须带学科和学制**：
        #   学科 —— 沪科版「数学八上」「物理八上」册次码一样
        #   学制 —— 沪科版物理有六三制和五四学制两套，册次码也一样
        # 少任何一个维度都会互相覆盖。
        b["system"] = "w" if ("五•四学制" in b["title"] or "五四学制" in b["title"]) else "s"
        b["bookId"] = (f"sh-{ed_code}-{b['subject']}-{b['system']}"
                       f"-{b['graphBook'] or 'x'}")

    OUT = BASE / "data" / "shanghai-textbooks.json"
    OUT.write_text(json.dumps({
        "_source": "国家中小学智慧教育平台 · 教材索引 part_*.json + 教材详情接口",
        "_indexUrls": VER_URL,
        "_detailTpl": DET_TPL,
        "books": sel,
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"清单 → {OUT}")

    if not args.download:
        return 0

    IMG_DIR.mkdir(parents=True, exist_ok=True)
    jobs = []
    for b in sel:
        if args.only and want.get(b["subject"]) != args.only:
            continue
        # slug 带上 contentId 前 8 位 —— 书名都长一个样，截到 40 字会撞车
        slug = re.sub(r"[^\w一-鿿]+", "_", b["title"])[:30] + "_" + b["contentId"][:8]
        d = IMG_DIR / slug
        d.mkdir(exist_ok=True)
        for n in range(1, (b.get("pages") or 0) + 1):
            jobs.append((b, d, n, d / f"p{n:03d}.jpg"))
    print(f"要下 {len(jobs)} 张", flush=True)

    ok = fail = 0
    done = 0

    def one(j):
        b, d, n, p = j
        if p.exists() and p.stat().st_size > 3000:
            return "skip"
        url = f"{b['imageBase']}/{n}.jpg"
        try:
            download(url, p)
            return "ok"
        except Exception:
            return "fail"

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as ex:
        for r in ex.map(one, jobs):
            done += 1
            if r == "ok":
                ok += 1
            elif r == "fail":
                fail += 1
            if done % 200 == 0:
                print(f"  {done}/{len(jobs)}  成功{ok} 失败{fail}", flush=True)
    print(f"下完 {done} 张：成功 {ok}，失败 {fail}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
