#!/usr/bin/env python3
"""
列出 ChinaTextbook 某个目录下的 PDF 一手路径。

为什么不用 GitHub API：匿名调用会 403 限流，而 1,133 个缺失定义
分散在 17 本初高中教材里，限流一次就得等一整轮重试。
GitHub 的 tree 页面把完整目录树嵌在 react-app.embeddedData 里，
一次请求就能拿全，不用 token。

用法：
    python3 src/list_textbooks.py 初中/数学/人教版-人民教育出版社
"""
import json
import re
import sys
import urllib.parse
import urllib.request

RAW = "https://github.com/TapXWorld/ChinaTextbook/tree/master/"
UA = {"User-Agent": "Mozilla/5.0"}


def tree(path, tries=3):
    url = RAW + urllib.parse.quote(path, safe="/")
    last = None
    for _ in range(tries):
        try:
            req = urllib.request.Request(url, headers=UA)
            h = urllib.request.urlopen(req, timeout=60).read().decode("utf-8", "replace")
            tag = 'react-app.embeddedData">'
            i = h.find(tag)
            if i < 0:
                raise RuntimeError("页面结构变了，找不到 embeddedData")
            # 必须切到 </script> 为止。第一版直接 json.loads(h[i+len:])，
            # 报 "Extra data" —— 后面还跟着收尾的 </script> 和整页 HTML。
            j = h.find("</script>", i)
            data = json.loads(h[i + len(tag):j])
            return data["payload"]["codeViewTreeRoute"]["tree"]["items"]
        except Exception as e:                      # 网络抖动重试
            last = e
    raise RuntimeError(f"{path}: {last}")


def walk(path, out, depth=0):
    for it in tree(path):
        if it["contentType"] == "directory":
            walk(it["path"], out, depth + 1)
        elif it["name"].lower().endswith(".pdf"):
            out.append((it["name"], it["path"]))
    return out


def main():
    root = sys.argv[1] if len(sys.argv) > 1 else "初中/数学/人教版-人民教育出版社"
    found = walk(root, [])
    print(f"{root}：{len(found)} 个 PDF\n")
    for name, path in sorted(found):
        print(f"  {name}\n      {path}")


if __name__ == "__main__":
    main()
