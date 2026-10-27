#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
找平台扫描本里的**章首页** —— 用像素特征，不用视觉模型。

思路
----
人教社教材的**章首页**版式很固定：
  · 顶部是「第N章 XXX」的大标题（占页面上部 1/4）
  · 下面大面积留白（可能一张图或纯白）
  · 页脚是页码

普通正文页则是**满页文字**，墨水均匀分布。

所以：**墨水集中在上部** = 章首页。
用 PIL 算每一页的「上部墨水占比」，最高的几页就是章首页候选。

这一步的价值
------------
有了章首页的**扫描页**，再读出它页脚的**印刷页**，
就得到 **偏移 = 扫描页 − 印刷页**，
于是「我们 PDF 的第 N 页」能换算成「平台的第 N+偏移 页」。

跑:  python3 src/find_chapter_pages.py <contentId> [--base <url>]
"""
import io
import json
import re
import sys
import urllib.request

opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
DETAIL = "https://bdcs-file-1.ykt.cbern.com.cn/zxx/ndrv2/resources/tch_material/details/{cid}.json"


def get(url, timeout=45):
    return opener.open(url, timeout=timeout).read()


def top_ink_ratio(data):
    """上部 30% 区域的墨水占全页墨水的比例。章首页会明显偏高。"""
    from PIL import Image
    im = Image.open(io.BytesIO(data)).convert("L")
    w, h = im.size
    px = im.load()
    band = max(1, int(h * 0.30))
    total = 0
    top = 0
    step = max(1, w // 200)          # 降采样，够快
    for y in range(0, h, max(1, h // 300)):
        for x in range(0, w, step):
            if px[x, y] < 200:       # 算墨水
                total += 1
                if y < band:
                    top += 1
    return (top / total) if total else 0.0


def main() -> int:
    cid = sys.argv[1]
    d = json.loads(get(DETAIL.format(cid=cid)).decode("utf-8"))
    pv = (d.get("custom_properties") or {}).get("preview") or {}
    if not pv:
        print("没有 preview")
        return 1
    base = re.sub(r"/\d+\.jpg.*$", "", pv[sorted(pv, key=lambda s: int("".join(c for c in s if c.isdigit()) or 0))[0]])
    print(f"base: {base}\n")

    n = int(sys.argv[2]) if len(sys.argv) > 2 else 49
    rows = []
    for p in range(1, n + 1):
        try:
            data = get(base + f"/{p}.jpg")
        except Exception:
            continue
        rows.append((top_ink_ratio(data), p))
        print(f"  第{p:3d}页  上部墨水占比 {rows[-1][0]:.2f}")
    rows.sort(reverse=True)
    print("\n最像章首页的页（上部墨水占比最高）：")
    for r, p in rows[:8]:
        print(f"  第{p:3d}页  {r:.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
