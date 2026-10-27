#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
抓取**教材原页图的基址**，让学习页能直接显示「这个知识点在教材的哪一页」。

页图直链格式（国家中小学智慧教育平台）：
    https://r{1-3}-ndr.ykt.cbern.com.cn/edu_product/esp/assets/{contentId}.t/zh-CN/{时间戳}/transcode/image/{页码}.jpg

⚠️ **时间戳每本书不同**，不能自己编 —— 必须从平台的 detail 接口拿：
    https://bdcs-file-1.ykt.cbern.com.cn/zxx/ndrv2/resources/tch_material/details/{contentId}.json
    → custom_properties.preview.Slide1 → 去掉末尾 /N.jpg 就是基址

⚠️ 平台的 preview 只给**前 N 页**（实测 49 页），
   但基址本身可以拼出后面的页码（只要该页在转码范围内）。
   所以先记下基址 + 已知最大页码，页码超界时页面要优雅降级。

跑:  python3 src/fetch_page_images.py
输出: data/page-images.json  {bookId: {base, max, contentId, title, edition, subject}}
"""
import json
import pathlib
import re
import sys
import time
import urllib.error
import urllib.request

BASE = pathlib.Path(__file__).resolve().parent.parent
TB = BASE / "data" / "shanghai-textbooks.json"
OUT = BASE / "data" / "page-images.json"
DETAIL = "https://bdcs-file-1.ykt.cbern.com.cn/zxx/ndrv2/resources/tch_material/details/{cid}.json"


def opener():
    # 不走本机代理（实测代理会挂），直连
    return urllib.request.build_opener(urllib.request.ProxyHandler({}))


def main() -> int:
    if not TB.exists():
        print(f"没有 {TB}")
        return 1
    tb = json.loads(TB.read_text(encoding="utf-8"))
    books = tb["books"]
    op = opener()
    out = {}
    fail = []
    for i, b in enumerate(books, 1):
        cid = b["contentId"]
        bid = b["bookId"]
        try:
            raw = op.open(DETAIL.format(cid=cid), timeout=30).read()
            d = json.loads(raw.decode("utf-8"))
            pv = (d.get("custom_properties") or {}).get("preview") or {}
            if not pv:
                fail.append((bid, "preview 空"))
                continue
            nums = sorted(int("".join(c for c in k if c.isdigit()) or 0) for k in pv)
            sample = pv[sorted(pv, key=lambda x: int("".join(c for c in x if c.isdigit()) or 0))[0]]
            base = re.sub(r"/\d+\.jpg.*$", "", sample)
            out[bid] = {
                "base": base,
                "maxPreview": max(nums),
                "contentId": cid,
                "title": b["title"],
                "edition": b["edition"],
                "subject": b["subject"],
                "pages": b.get("pages"),
                "bookZh": b.get("title"),
            }
            print(f"  [{i:2d}/{len(books)}] {bid:26s} {len(pv):3d} 页预览 → base ok")
        except Exception as e:                       # noqa: BLE001
            fail.append((bid, str(e)[:60]))
            print(f"  [{i:2d}/{len(books)}] {bid:26s} ✗ {str(e)[:60]}")
        time.sleep(0.15)

    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n成功 {len(out)} / {len(books)} 本 → {OUT.relative_to(BASE)}")
    if fail:
        print(f"失败 {len(fail)} 本：")
        for bid, e in fail:
            print(f"  {bid}: {e}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
