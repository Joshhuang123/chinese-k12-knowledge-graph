#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
从国家中小学智慧教育平台取**人教版小学科学**的整本页图。

为什么拉这个
------------
上游 K12-KGraph 的 `books.yaml` 里**小学只有数学**（12 册），
物理 / 化学 / 生物学在小学阶段一个都没有 —— 这就是上游 issue #10 提的事。
但平台上人教版《小学科学》1 上~6 下 **12 本俱全**（每册 7 个版本），
也就是说：**教材是有的，缺的是把它接进图谱**。

这是补小学阶段物理/化学/生物学概念的**唯一一手来源** ——
教材上印的「物质」「能量」「光」「电」「生命现象」这些单元，
就是小学科学的内容，跟初中物理化学生物直接接得上。

数据链路（跟 hujiao_fetch.py 同源，不是猜的路径）
----------------------------------------------
标签树   /zxx/ndrs/tags/tch_material_tag.json          → 教材分类树
教材索引 /zxx/ndrs/resources/tch_material/part_*.json  → 全部 3,565 本教材的元数据
         （分片地址在 /zxx/ndrs/resources/tch_material/version/data_version.json）
教材详情 /zxx/ndrv2/resources/tch_material/details/{id}.json
         → provider_list[].name  = 出版社
         → custom_properties.requirements[].pagesize = 全书总页数
         → ti_items[].ti_storages[] = 页图存储基址
页图     {基址}/{页号}.jpg                               → 1303×1842 的 JPEG

为什么用页图而不是 PDF
----------------------
平台的 PDF 是 `assets_document` 资源，在 OSS 上、跟页图不是一个桶，
从本机拉不到（403）。**页图是能拉到的**（HTTP 200）。

去重规则
--------
平台上同一本教材有多个版本（不同印次、不同封面、不同扫描批次），
标题完全一样。判据：
  1. 先按**出版社**筛（只留人民教育出版社）
  2. 同一册次下，**取总页数最多的那个**（页数多 = 版本全，不是节选）
  3. 页数相同则取 create_time 最新的
  4. **学制要分开**：五·四学制（上海）的和六年制的不是一套，要分开存

跑法
----
    python3 src/kx_fetch.py --list          # 只列清单
    python3 src/kx_fetch.py --download      # 下页图
    python3 src/kx_fetch.py --download --grade 3
"""
from __future__ import annotations

import argparse
import collections
import concurrent.futures
import json
import pathlib
import re
import sys
import urllib.request

BASE = pathlib.Path(__file__).resolve().parent.parent
WORK = BASE / "data" / "pdf-cache" / "work"
IMG_DIR = BASE / "data" / "pdf-cache" / "kx-rjb"

VER_URL = ("https://bdcs-file-1.ykt.cbern.com.cn/zxx/ndrs/resources/tch_material/"
           "version/data_version.json")
DET_TPL = ("https://bdcs-file-1.ykt.cbern.com.cn/zxx/ndrv2/resources/"
           "tch_material/details/{id}.json")
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
HDRS = {"User-Agent": UA, "Referer": "https://basic.smartedu.cn/"}

# 要的出版社：人民教育出版社
WANT_PUB = "人民教育出版社"

# 册次：1a..6b（小学科学一上~六下）
GRADES = {
    "1a": ("一", "上"), "1b": ("一", "下"),
    "2a": ("二", "上"), "2b": ("二", "下"),
    "3a": ("三", "上"), "3b": ("三", "下"),
    "4a": ("四", "上"), "4b": ("四", "下"),
    "5a": ("五", "上"), "5b": ("五", "下"),
    "6a": ("六", "上"), "6b": ("六", "下"),
}
CN_NUM = "一二三四五六"


def get_json(url, tries=3):
    last = None
    for _ in range(tries):
        try:
            req = urllib.request.Request(url, headers=HDRS)
            with urllib.request.urlopen(req, timeout=90) as r:
                return json.load(r)
        except Exception as e:  # 网络抖动，重试
            last = e
    raise last


def fetch_index():
    """拉全部教材索引（3,565 本）。"""
    ver = get_json(VER_URL)
    urls = [u for u in ver["urls"].split(",") if u]
    items = []
    with concurrent.futures.ThreadPoolExecutor(4) as ex:
        for d in ex.map(get_json, urls):
            if isinstance(d, dict):
                for k in ("data", "list", "items", "resources"):
                    if k in d:
                        items += d[k]
                        break
            elif isinstance(d, list):
                items += d
    return items


def grade_of(title: str):
    """从标题认册次（'科学三年级上册' → '3a'）。认不出返回 None。"""
    m = re.search(r"([一二三四五六])年级\s*[·•]?\s*(上|下)册", title)
    if not m:
        return None
    g = CN_NUM.index(m.group(1)) + 1
    return f"{g}{'a' if m.group(2) == '上' else 'b'}"


def is_54(title: str) -> bool:
    """五·四学制（上海那一套）。"""
    return "五•四学制" in title or "五四学制" in title


def details_of(item):
    """拉单本详情，抽出 publisher / pagesize / 页图基址。"""
    d = get_json(DET_TPL.format(id=item["id"]))
    title = d.get("global_title", {}).get("zh-CN", "")
    pub = ""
    for p in d.get("provider_list") or []:
        if p.get("name"):
            pub = p["name"]
            break
    # 页数：**在 ti_items[].custom_properties.requirements[] 里，值是字符串**
    # （custom_properties 顶层没有 requirements —— 第一版按顶层找，12 本全是 0 页）
    pages = 0
    for it in d.get("ti_items") or []:
        for r in (it.get("custom_properties") or {}).get("requirements") or []:
            if r.get("name") == "pagesize":
                try:
                    pages = max(pages, int(r.get("value") or 0))
                except (TypeError, ValueError):
                    pass
    # 页图基址：**从 custom_properties.preview 的第一个 URL 里抽**
    # —— ti_items[].ti_storages[] 给的是 `r1-ndr-**private**.ykt.cbern.com.cn`，
    #    那个主机要授权（401）；preview 给的是 `r1-ndr.ykt.cbern.com.cn`（不带 private），能直接下。
    # （这是跟 hujiao_fetch.py 的同一处坑。）
    base = ""
    pv = (d.get("custom_properties") or {}).get("preview") or {}
    for u in pv.values():
        m = re.match(r"(https://r\d-ndr\.ykt\.cbern\.com\.cn/.*?/transcode/image)/", u)
        if m:
            base = m.group(1)
            break
    if not base:
        for it in d.get("ti_items") or []:
            if it.get("lc_ti_format") != "image/jpg":
                continue
            st = it.get("ti_storages") or []
            if not st:
                continue
            # private 主机换掉（ti_storages 给的是 private 的，要授权）
            base = re.sub(r"^https://r\d-ndr-private\.", "https://r1-ndr.",
                          st[0].rsplit("/", 1)[0])
            break
    return {
        "id": item["id"], "title": title, "publisher": pub, "pages": pages,
        "base": base, "create_time": d.get("create_time", ""),
        "update_time": d.get("update_time", ""),
        "g54": is_54(title),
    }


def build_list(force=False):
    cache = WORK / "kx-rjb-details.json"
    if cache.exists() and not force:
        rows = json.load(open(cache, encoding="utf-8"))
        print(f"用缓存：{cache}（{len(rows)} 本）")
        return rows

    print("拉教材索引…")
    items = fetch_index()
    print(f"索引 {len(items)} 本")

    # 先按标题筛掉绝大多数，别对 3,565 本都拉详情
    cand = []
    for it in items:
        t = it.get("global_title", {}).get("zh-CN", "")
        if "科学" not in t:
            continue
        g = grade_of(t)
        if not g:
            continue
        cand.append(it)
    print(f"标题含「科学」且能认册次：{len(cand)} 本")

    print("拉详情…")
    rows = []
    with concurrent.futures.ThreadPoolExecutor(6) as ex:
        futs = {ex.submit(details_of, it): it for it in cand}
        for i, fu in enumerate(concurrent.futures.as_completed(futs), 1):
            try:
                rows.append(fu.result())
            except Exception as e:
                print(f"  ! 详情失败 {futs[fu].get('id')}: {str(e)[:60]}")
            if i % 20 == 0:
                print(f"  {i}/{len(cand)}")
    cache.parent.mkdir(parents=True, exist_ok=True)
    json.dump(rows, open(cache, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"详情 → {cache}")
    return rows


def pick(rows):
    """按出版社 + 册次去重，取页数最多的。"""
    by_pub = collections.defaultdict(list)
    for r in rows:
        by_pub[r["publisher"]].append(r)
    print("\n=== 小学科学 · 出版社分布 ===")
    for p, v in sorted(by_pub.items(), key=lambda kv: -len(kv[1])):
        print(f"  {len(v):4d} 本  {p}")
    print()

    rjb = by_pub.get(WANT_PUB, [])
    if not rjb:
        # 出版社名可能带前缀，退一步模糊匹配
        for p, v in by_pub.items():
            if "人民教育" in p or "人教" in p:
                rjb = v
                print(f"（出版社名匹配到「{p}」）")
                break
    print(f"目标出版社 {WANT_PUB}：{len(rjb)} 本")

    # 分学制
    out = {}
    for r in rjb:
        g = grade_of(r["title"])
        if not g:
            continue
        key = (r["g54"], g)
        cur = out.get(key)
        # 页数多优先；页数相同取 create_time 新
        if cur is None or (r["pages"], r["create_time"]) > (cur["pages"], cur["create_time"]):
            out[key] = r
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--download", action="store_true")
    ap.add_argument("--grade", help="只下某册，如 3a")
    ap.add_argument("--force", action="store_true", help="重建详情缓存")
    args = ap.parse_args()

    rows = build_list(force=args.force)
    picked = pick(rows)

    print("\n=== 选中清单 ===")
    total = 0
    for (g54, g), r in sorted(picked.items(), key=lambda kv: (kv[0][0], kv[0][1])):
        total += r["pages"]
        tag = "五四学制" if g54 else "六年制"
        print(f"  {tag}  {g}  {r['pages']:4d} 页  {r['publisher']}  {r['title'][:40]}")
        print(f"      id={r['id']}")
    print(f"\n合计 {len(picked)} 本 / {total} 页")
    if not args.download:
        print("\n（加 --download 下页图）")
        return

    # 下载
    IMG_DIR.mkdir(parents=True, exist_ok=True)
    for (g54, g), r in sorted(picked.items(), key=lambda kv: (kv[0][0], kv[0][1])):
        if args.grade and g != args.grade:
            continue
        tag = "g54" if g54 else "s6"
        outdir = IMG_DIR / f"{tag}-{g}"
        outdir.mkdir(parents=True, exist_ok=True)
        if not r["base"]:
            print(f"  ! {g} 没有页图基址，跳过")
            continue
        print(f"  {tag}-{g} {r['pages']} 页 → {outdir}")
        n = 0
        for p in range(1, r["pages"] + 1):
            dst = outdir / f"{p:03d}.jpg"
            if dst.exists() and dst.stat().st_size > 1024:
                n += 1
                continue
            url = f"{r['base']}/{p}.jpg"
            try:
                req = urllib.request.Request(url, headers=HDRS)
                with urllib.request.urlopen(req, timeout=60) as resp:
                    data = resp.read()
                if len(data) < 1024:
                    break
                dst.write_bytes(data)
                n += 1
            except Exception as e:
                print(f"    ! 页 {p} 失败 {str(e)[:50]}")
                break
        print(f"    下了 {n} 页")


if __name__ == "__main__":
    main()
