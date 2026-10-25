#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
生成「数据一览」公开页 —— `data.html`

## 为什么要有这个页

`data/DATASETS.json` 是**给 agent 用的**（机器可读）。
但这个仓库的访问者**一半是人** —— 打开 GitHub 首页的人，
不会先 cat 一个 JSON。

这个页就是那份清单的**人读版**：
- 全部数据集在一页里，按需求查
- 每个数据集的字段表、样本行都能看
- **能搜**（搜「浮力」「先修边」「公式」立刻定位）

## 跟 `data/DATASETS.json` 的关系

**页面是清单的投影** —— 内容全部来自那份 JSON，不重新统计。
改了数据 → 重跑 `src/build_datasets_catalog.py` → 重跑本脚本。

## 跟 `quality.html` 的关系

`quality.html` 摆的是**已知问题**（我们承认什么做错了），
这个页摆的是**有什么数据**（你能拿到什么）。
两页是互补的，导航栏互链。

## 跑法

```bash
python3 src/build_datasets_catalog.py   # 先更新清单
python3 src/build_data_browser.py      # 再生成页面
```
"""
from __future__ import annotations

import html
import json
import pathlib
import re

BASE = pathlib.Path(__file__).resolve().parent.parent
CATALOG = BASE / "data" / "DATASETS.json"
OUT = BASE / "data.html"

# 跟 quality.html / 主站同一套配色（别让三个页面长得像三个项目）
BG = "#08090C"
FG = "#E8EAF0"
MUTED = "#8B93A7"
ACCENT = "#FF9F45"
LINE = "rgba(255,255,255,.09)"
CARD = "rgba(255,255,255,.032)"


def esc(s) -> str:
    return html.escape(str(s), quote=True)


def md(s) -> str:
    """转义后把 markdown 的 **粗体** 变成 HTML。

    ⚠️ 说明文字是从手写的 DESC 里来的，里面用了 `**粗体**`。
    直接 esc 出去会显示成 `知识点**自学卡**`（标记露出来，很丑）。
    """
    out = esc(s)
    return re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", out)


def kb(n: int) -> str:
    return f"{n/1024/1024:.0f} MB" if n >= 1024 * 1024 else f"{n/1024:.0f} KB"


def sample_html(obj) -> str:
    """样本行渲染成带缩进的 JSON。"""
    if obj is None:
        return '<div class="empty">（没有样本）</div>'
    try:
        s = json.dumps(obj, ensure_ascii=False, indent=1)
    except Exception:
        s = str(obj)
    s = esc(s)
    # 键名加一点颜色，让人一眼看出结构
    s = re.sub(r'(&quot;[^&]*?&quot;)(\s*:)', r'<span class="k">\1</span>\2', s)
    return f'<pre class="sample">{s}</pre>'


def build() -> str:
    cat = json.load(open(CATALOG, encoding="utf-8"))
    ds = cat["datasets"]
    total_bytes = sum(d["bytes"] for d in ds)
    total_records = sum(d["records"] for d in ds if isinstance(d["records"], int))

    cards = []
    for d in ds:
        critical = d.get("critical_note")
        rec = f"{d['records']:,}" if isinstance(d["records"], int) else "?"
        fields = d.get("fields") or []
        field_html = ""
        if fields:
            chips = "".join(f'<span class="chip">{esc(f)}</span>' for f in fields[:40])
            more = (f'<span class="chip more">还有 {len(fields)-40} 个</span>'
                    if len(fields) > 40 else "")
            field_html = f'<div class="fields">{chips}{more}</div>'
        crit_html = (f'<div class="crit">{md(critical)}</div>'
                     if critical else "")
        ngit = "" if d.get("in_git") else '<span class="chip nogit">不入库</span>'
        cards.append(f"""
<article class="ds" data-kind="{esc(d['kind'])}">
  <header>
    <h3><code>{esc(d['file'])}</code></h3>
    <div class="meta">
      <span class="m rec">{rec} {esc(d['unit'].split('（')[0])}</span>
      <span class="m">{kb(d['bytes'])}</span>
      <span class="m fmt">{esc(d['format'])}</span>
      {ngit}
    </div>
  </header>
  <p class="what">{md(d["what"])}</p>
  <p class="use"><b>能回答什么</b>：{md(d["use_for"])}</p>
  <p class="how"><b>怎么取</b>：{md(d["how_to_use"])}</p>
  {crit_html}
  <details><summary>字段与样本</summary>{field_html}{sample_html(d.get('sample'))}</details>
</article>""")

    pick = "".join(f"<li>{md(x)}</li>" for x in cat["how_to_pick"])

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>数据一览 · 中文 K12 知识图谱</title>
<style>
:root {{
  --bg:{BG}; --fg:{FG}; --muted:{MUTED}; --accent:{ACCENT};
  --line:{LINE}; --card:{CARD};
}}
* {{ box-sizing:border-box; }}
body {{
  margin:0; background:var(--bg); color:var(--fg);
  font:15px/1.75 -apple-system,BlinkMacSystemFont,"PingFang SC","Hiragino Sans GB",
       "Microsoft YaHei","Noto Sans CJK SC",sans-serif;
  -webkit-font-smoothing:antialiased;
}}
.wrap {{ max-width:1080px; margin:0 auto; padding:28px 20px 80px; }}
h1 {{ font-size:28px; margin:0 0 6px; letter-spacing:-.01em; }}
h2 {{ font-size:18px; margin:44px 0 14px; }}
.lede {{ color:var(--muted); margin:0 0 26px; max-width:760px; }}
.nav {{ display:flex; gap:16px; flex-wrap:wrap; padding:12px 0 22px;
       border-bottom:1px solid var(--line); margin-bottom:26px; }}
.nav a {{ color:var(--muted); text-decoration:none; font-size:13.5px; }}
.nav a:hover {{ color:var(--accent); }}
.stats {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr));
         gap:12px; margin:0 0 8px; }}
.stat {{ background:var(--card); border:1px solid var(--line); border-radius:12px;
        padding:14px 16px; }}
.stat b {{ display:block; font-size:22px; font-weight:650; }}
.stat span {{ color:var(--muted); font-size:12.5px; }}
.pick {{ background:var(--card); border:1px solid var(--line); border-radius:12px;
        padding:14px 18px 14px 34px; margin:0 0 6px; }}
.pick li {{ margin:5px 0; }}
.pick b {{ color:var(--accent); font-weight:600; }}
#q {{ width:100%; padding:11px 14px; border-radius:10px; border:1px solid var(--line);
     background:rgba(255,255,255,.04); color:var(--fg); font-size:14.5px;
     font-family:inherit; }}
#q:focus {{ outline:none; border-color:var(--accent); }}
#cnt {{ color:var(--muted); font-size:13px; margin:10px 0 16px; }}
.ds {{ background:var(--card); border:1px solid var(--line); border-radius:14px;
      padding:18px 20px; margin:0 0 12px; }}
.ds:hover {{ border-color:rgba(255,159,69,.32); }}
.ds h3 {{ margin:0 0 8px; font-size:15.5px; font-weight:600; }}
.ds code {{ font-family:ui-monospace,SFMono-Regular,Menlo,monospace;
           font-size:13.5px; color:var(--accent); }}
.meta {{ display:flex; gap:8px; flex-wrap:wrap; margin-bottom:11px; }}
.m {{ font-size:12px; color:var(--muted); background:rgba(255,255,255,.05);
     padding:2px 8px; border-radius:6px; }}
.rec {{ color:var(--fg); }}
.p {{ margin:6px 0; font-size:14px; }}
.p b {{ color:var(--muted); font-weight:600; margin-right:2px; }}
.use {{ color:#C9CEDA; }}
.crit {{ margin-top:10px; padding:9px 12px; border-radius:9px; font-size:13px;
        background:rgba(255,159,69,.09); border:1px solid rgba(255,159,69,.26);
        color:#FFD9AE; }}
details {{ margin-top:12px; }}
summary {{ cursor:pointer; font-size:13px; color:var(--muted); user-select:none; }}
summary:hover {{ color:var(--accent); }}
.fields {{ display:flex; gap:6px; flex-wrap:wrap; margin:12px 0 10px; }}
.chip {{ font-size:11.5px; padding:2px 8px; border-radius:6px;
         background:rgba(120,200,255,.10); color:#9FD8F5;
         font-family:ui-monospace,SFMono-Regular,Menlo,monospace; }}
.chip.more {{ background:rgba(255,255,255,.06); color:var(--muted); }}
.chip.nogit {{ background:rgba(255,209,102,.12); color:#FFD166; }}
.sample {{ margin:10px 0 0; padding:12px 14px; border-radius:9px;
           background:rgba(0,0,0,.34); border:1px solid var(--line);
           font-family:ui-monospace,SFMono-Regular,Menlo,monospace;
           font-size:12.5px; line-height:1.6; overflow-x:auto;
           white-space:pre-wrap; word-break:break-word; color:#C4CAD8; }}
.sample .k {{ color:#9FD8F5; }}
.empty {{ color:var(--muted); font-size:13px; padding:10px 0; }}
footer {{ margin-top:46px; padding-top:20px; border-top:1px solid var(--line);
         color:var(--muted); font-size:12.5px; }}
footer a {{ color:var(--muted); }}
@media (max-width:640px) {{
  h1 {{ font-size:23px; }}
  .wrap {{ padding:20px 14px 60px; }}
  .ds {{ padding:15px 16px; }}
}}
</style>
</head>
<body>
<div class="wrap">

<div class="nav">
  <a href="./">← 回到图谱</a>
  <a href="./shanghai.html">上海版</a>
  <a href="./kx.html">小学科学</a>
  <a href="./quality.html">数据质量</a>
  <a href="https://github.com/Joshhuang123/chinese-k12-knowledge-graph">源码</a>
</div>

<h1>这个项目有什么数据</h1>
<p class="lede">
{len(ds)} 个数据集，共 {kb(total_bytes)}。
每个都是<strong>结构化事实</strong>（不是教材原件 —— 教材 PDF 有版权，不随仓库分发）。
不知道用哪个？先看下面的「按需求查」，或者直接搜。
</p>

<div class="stats">
  <div class="stat"><b>{len(ds)}</b><span>数据集</span></div>
  <div class="stat"><b>{kb(total_bytes)}</b><span>总体积</span></div>
  <div class="stat"><b>{total_records:,}</b><span>总条数</span></div>
  <div class="stat"><b>0</b><span>第三方依赖（主项目）</span></div>
</div>

<h2>按需求查</h2>
<ul class="pick">
{pick}
</ul>

<h2>全部数据集</h2>
<input id="q" type="search" placeholder="搜「浮力」「先修边」「公式」「沪教」…" autocomplete="off">
<div id="cnt">{len(ds)} 个数据集</div>
<div id="list">
{"".join(cards)}
</div>

<footer>
本页由 <code>src/build_data_browser.py</code> 从 <code>data/DATASETS.json</code> 生成
—— 内容单一来源，改了数据重跑一次就同步。<br>
字段说明和取用示例见仓库里的 <code>docs/agent-data.md</code>；
已知问题见 <code>quality.html</code>。
</footer>

</div>
<script>
(function () {{
  var q = document.getElementById('q');
  var list = document.getElementById('list');
  var cnt = document.getElementById('cnt');
  var items = Array.prototype.slice.call(list.querySelectorAll('.ds'));
  var total = items.length;
  function apply() {{
    var s = q.value.trim().toLowerCase();
    var n = 0;
    items.forEach(function (el) {{
      var hit = !s || el.textContent.toLowerCase().indexOf(s) >= 0;
      el.style.display = hit ? '' : 'none';
      if (hit) n++;
    }});
    cnt.textContent = s ? (n + ' / ' + total + ' 个数据集（搜「' + s + '」）')
                        : (total + ' 个数据集');
  }}
  q.addEventListener('input', apply);
  apply();
}})();
</script>
</body>
</html>
"""


def main() -> int:
    if not CATALOG.exists():
        print(f"✗ 缺 {CATALOG} —— 先跑 python3 src/build_datasets_catalog.py")
        return 1
    doc = build()
    OUT.write_text(doc, encoding="utf-8")
    print(f"数据一览页 → {OUT.relative_to(BASE)}  ({OUT.stat().st_size//1024} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
