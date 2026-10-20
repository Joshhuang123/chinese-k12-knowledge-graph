#!/usr/bin/env python3
"""
生成「数据质量」公开页 quality.html。

## 为什么要有这个页

这个项目跟满街的「AI 生成知识图谱」的区别，是**每条边都能查来源**。
但这个优势现在只存在于仓库里 —— `known-issues.md` 有 29 条问题、
`docs/prereq-conflicts.md` 有 322 条裁决记录，**访问网站的人看不到**。

一个把已知问题公开摆出来的图谱，比一个声称自己全对的图谱可信得多。
所以把这些数据做成一个页面，挂到主站上。

## 页面里有什么

- 全库总账（节点、边、来源分档、0 前置率、链深）
- 四类已知问题，各一张表：
  ① 上游先修边跟教材顺序倒挂（跨册为准）
  ② 教材有、图谱没有的**覆盖缺口**
  ③ 方向冲突的裁决账本（谁赢谁输、为什么）
  ④ 可疑的上游先修边（标了但不删）
- 每条都能点开看到两个端点的名字和出处

## 跑法

```bash
python3 src/build_quality.py
```
"""
import html
import json
import pathlib
import re
from collections import Counter

BASE = pathlib.Path(__file__).resolve().parent.parent
NORM = BASE / "data" / "normalized"
OUT = BASE / "quality.html"

TIER_ZH = {0: "上游", 1: "模型重建", 2: "能力底座", 3: "自建概念",
           4: "教材引入路径", 5: "已修正", 6: "教材结构图"}

# 来源色跟主页面脉络视图用的是同一套（viz/template.html 的 MAP_SRC_COLOR）
# —— 两处颜色不一样的话，看图页和这个页会给出两种印象。
SRC_COLOR = {"上游": "#5b6472", "模型重建": "#7fd3ff", "能力底座": "#ffc477",
             "自建概念": "#c6a7ff", "教材引入路径": "#6ee7b7", "已修正": "#ffd166",
             "教材结构图": "#ff8fab"}


def load(name, default=None):
    p = NORM / name
    if not p.exists():
        return default
    return json.load(open(p, encoding="utf-8"))


def esc(s):
    return html.escape(str(s), quote=True)


def table(headers, rows, cls=""):
    h = "".join(f"<th>{esc(x)}</th>" for x in headers)
    body = ""
    for r in rows:
        body += "<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>"
    if not rows:
        body = f'<tr><td colspan="{len(headers)}" class="empty">（无）</td></tr>'
    return (f'<table class="{cls}"><thead><tr>{h}</tr></thead>'
            f"<tbody>{body}</tbody></table>")


def main():
    stats = load("full-stats.json", {})
    collide = load("order-collide.json", {"rows": []})
    struct = load("structmap-edges.json", {"missing_nodes": []})
    confl = load("prereq-conflicts.json", {"resolved": []})
    suspect = load("suspect-edges.json", [])
    wrong = load("confirmed-wrong.json", {"verdicts": []})

    # ── ① 教材顺序倒挂（只取跨册，跟 flag_suspect 同一套口径）──
    rev = [r for r in collide.get("rows", [])
           if r.get("kind") == "cross" and r.get("source") == "upstream"]
    rev.sort(key=lambda r: r.get("toPos", 0) - r.get("fromPos", 0), reverse=True)

    # ── ② 覆盖缺口 ──
    miss = struct.get("missing_nodes", [])

    # ── ③ 方向冲突裁决 ──
    conf = [r for r in confl.get("resolved", []) if r.get("reason") == "conflict"]
    cyc = [r for r in confl.get("resolved", []) if r.get("reason") == "cycle"]
    adj = [r for r in confl.get("resolved", []) if r.get("reason") == "adjudicated"]

    # ── ④ 可疑边 ──
    sus = suspect

    by_reason = Counter(r.get("reason", "conflict") for r in confl.get("resolved", []))

    cards = [
        ("教材知识点", f"{stats.get('upstream_nodes', 0):,}", "上游 Concept+Skill+Experiment"),
        ("前置关系", f"{stats.get('total_edges', 0):,}", "7 档来源，逐条可查"),
        ("0 前置知识点", f"{stats.get('zero_prereq', 0)}",
         f"占 {100*stats.get('zero_prereq', 0)/max(1,stats.get('upstream_nodes', 1)):.1f}%"),
        ("链深中位", str(stats.get("chain_depth_median", "—")),
         f"均值 {stats.get('chain_depth_mean', '—')}"),
        ("方向冲突已裁决", f"{len(conf)}", "同一对节点两个方向都有边时，按来源优先级留一条"),
        ("成环剪掉", f"{len(cyc)}", "先修边必须是 DAG，剪掉的每条都记在账上"),
        ("教材覆盖缺口", f"{len(miss)}", "教材里有、图谱里没有的概念"),
        ("可疑上游边", f"{len(sus)}", "标出来但不删 —— 上游数据只读"),
    ]
    card_html = "".join(
        f'<div class="c"><div class="lab">{esc(a)}</div>'
        f'<div class="num">{esc(b)}</div><div class="sub">{esc(c)}</div></div>'
        for a, b, c in cards)

    src_rows = []
    for k, v in sorted(stats.get("edge_sources", {}).items(),
                       key=lambda kv: -kv[1]):
        tot = max(1, stats.get("total_edges", 1))
        col = SRC_COLOR.get(k, "#8b93a7")
        src_rows.append([
            f'<span class="sw" style="background:{col}"></span>{esc(k)}',
            f"{v:,}",
            f'<span class="bar"><i style="background:{col};width:{100*v/tot:.1f}%"></i></span>',
        ])

    rev_rows = []
    for r in rev[:60]:
        rev_rows.append([
            esc(r.get("fromName", "")), esc(r.get("fromBook", "")),
            "→", esc(r.get("toName", "")), esc(r.get("toBook", "")),
            f"{r.get('fromPos', 0)} → {r.get('toPos', 0)}",
        ])

    miss_rows = []
    for m in miss:
        miss_rows.append([
            esc(m.get("name", "")), esc(m.get("book", "")),
            esc(m.get("kind", "")), esc(m.get("fromHow", m.get("how", ""))),
        ])

    conf_rows = []
    for r in conf[:60]:
        keep = r.get("keptNames") or ["—", "—"]
        drop = r.get("droppedNames") or ["—", "—"]
        conf_rows.append([
            f"{esc(keep[0])} → {esc(keep[1])}",
            f'<span class="tg t-keep">留 {esc(TIER_ZH.get(r.get("keptSrc"), "") or r.get("keptSrc", ""))}</span>',
            f"{esc(drop[0])} → {esc(drop[1])}",
            f'<span class="tg t-drop">丢 {esc(r.get("droppedSrc", ""))}</span>',
        ])

    sus_rows = []
    for r in sorted(sus, key=lambda x: -x.get("level", 0))[:60]:
        sus_rows.append([
            esc(r.get("fromName", "")), esc(r.get("fromBook", "")),
            "→", esc(r.get("toName", "")), esc(r.get("toBook", "")),
            " / ".join(r.get("hits", [])),
            f'<span class="tg t-l{r.get("level", 1)}">命中 {r.get("level", 1)} 条</span>',
        ])

    adj_rows = []
    for v in wrong.get("verdicts", []):
        adj_rows.append([
            esc(v.get("fromName", "")), "→", esc(v.get("toName", "")),
            f'<span class="tg t-drop">{esc(v.get("action", ""))}</span>',
            esc(str(v.get("reason") or v.get("evidence") or "")[:70]),
        ])

    doc = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>数据质量 · 中国的孩子在学什么</title>
<style>
:root{{--bg:#0b0c10;--panel:#14171e;--line:#242a35;--fg:#e8ebf2;--muted:#8b93a7}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--fg);
  font:15px/1.7 -apple-system,BlinkMacSystemFont,"PingFang SC","Hiragino Sans GB","Microsoft YaHei",sans-serif}}
.wrap{{max-width:1080px;margin:0 auto;padding:38px 22px 70px}}
h1{{font-size:30px;margin:0 0 6px;font-weight:700}}
.sub{{color:var(--muted);font-size:13.5px;margin:0 0 26px}}
a{{color:#7fd3ff}}
.nav{{margin-bottom:26px;font-size:13px}}
.nav a{{margin-right:16px;text-decoration:none;color:#7fd3ff}}
.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:11px;margin-bottom:34px}}
.c{{background:var(--panel);border:1px solid var(--line);border-radius:11px;padding:14px 16px}}
.c .lab{{font-size:11.5px;color:var(--muted)}}
.c .num{{font:700 27px/1.25 ui-monospace,SFMono-Regular,Menlo,monospace;color:#ff3d7f}}
.c .sub{{font-size:11px;margin:3px 0 0}}
h2{{font-size:19px;margin:34px 0 6px;padding-top:18px;border-top:1px solid var(--line)}}
h2 .n{{color:#ff3d7f;font-family:ui-monospace,Menlo,monospace;margin-right:9px}}
.note{{color:var(--muted);font-size:12.5px;margin:0 0 13px;line-height:1.75}}
table{{width:100%;border-collapse:collapse;font-size:12.5px;margin-bottom:8px}}
th{{text-align:left;font-weight:600;color:#9fb0c8;border-bottom:1px solid var(--line);
  padding:7px 9px;font-size:11.5px;white-space:nowrap}}
td{{padding:6px 9px;border-bottom:1px solid #191d25;vertical-align:top}}
td.empty{{color:#6b7488;text-align:center;padding:16px}}
tr:hover td{{background:rgba(255,255,255,.025)}}
.sw{{display:inline-block;width:11px;height:11px;border-radius:3px;margin-right:7px;vertical-align:-1px}}
.bar{{display:block;height:5px;background:#22262f;border-radius:3px;overflow:hidden;min-width:60px}}
.bar i{{display:block;height:100%;background:#7fd3ff}}
.tg{{font-size:10.5px;padding:2px 7px;border-radius:20px;border:1px solid var(--line);white-space:nowrap}}
.t-keep{{border-color:#2f5a3f;color:#8fd6a8}}
.t-drop{{border-color:#5a2f3f;color:#ff9db8}}
.t-l2{{border-color:#5a2f3f;color:#ff9db8}}
.foot{{margin-top:40px;padding-top:18px;border-top:1px solid var(--line);
  color:var(--muted);font-size:12px;line-height:1.9}}
code{{background:#191d25;padding:1px 5px;border-radius:4px;font-size:11.5px}}
</style>
</head>
<body>
<div class="wrap">
<div class="nav"><a href="./">← 回到图谱</a><a href="https://github.com/Joshhuang123/chinese-k12-knowledge-graph">源码</a></div>
<h1>数据质量</h1>
<p class="sub">这张图谱有多少条边是可信的、有多少条是有问题的、问题具体是什么 —— 全部摊开。
<b>发现问题 ≠ 隐藏问题</b>：上游数据一字未改，问题逐条记在这里。</p>

<div class="cards">{card_html}</div>

<h2><span class="n">01</span>先修边的来源分档</h2>
<p class="note">每一档的可信度不同，页面上每条边都带来源徽标。
「上游」是数据集自己标的，排在最后 —— ISSUE-09 逐条看过 38 条方向冲突，
模型那边全对；「教材引入路径」和「教材结构图」有教材原文，最硬。</p>
{table(["来源", "条数", "占比"], src_rows)}

<h2><span class="n">02</span>上游先修边跟教材顺序倒挂（跨册 {len(rev)} 条）</h2>
<p class="note">教材把 A 排在 B 后面，而图谱说「要先会 A 才学得会 B」。
跨册的这类可信度高 —— 通常是边错了。<b>只标不删</b>：上游数据只读。
（同一册里位置反的 <b>不作判据</b>：教材自己就大量这么排，拿它当依据一半以上是假阳性。）</p>
{table(["前置", "册", "", "后继", "册", "教材位置"], rev_rows)}

<h2><span class="n">03</span>教材覆盖缺口（{len(miss)} 处）</h2>
<p class="note">教材里有、图谱里没有的概念 —— 比如「垂线及其性质」「等分圆周」
「常用逻辑用语」「和差角公式」「空间几何体」。
<b>没有节点就没有边</b>，所以这一栏比「再加一千条边」更值钱。</p>
{table(["教材里的概念", "册", "类型", "怎么找到的"], miss_rows)}

<h2><span class="n">04</span>方向冲突的裁决（{len(conf)} 组）</h2>
<p class="note">同一对节点上下两个方向都有边时，按来源优先级留一条、丢一条。
优先级：已修正 110 &gt; 教材引入路径 100 &gt; 教材结构图 95 &gt; 自建概念 70 &gt;
模型重建 60 &gt; 能力底座 45 &gt; 上游 40。
完整账本在仓库的 <code>docs/prereq-conflicts.md</code>。</p>
{table(["留（谁赢）", "", "丢（谁输）", ""], conf_rows)}

<h2><span class="n">05</span>可疑的上游先修边（{len(sus)} 条）</h2>
<p class="note">命中「册序倒挂 / 下位当前置 / 方法当前置 / 应用实例当前置」等规则的边。
命中 2 条以上的最该先看。页面上这些边带「可疑」标记，<b>但不删</b>。</p>
{table(["前置", "册", "", "后继", "册", "命中规则", "证据条数"], sus_rows)}

<h2><span class="n">06</span>已裁决的上游错误（{len(adj_rows)} 条）</h2>
<p class="note">逐条拿模型 + 教材两个独立证据核过的上游错误边。
改的是页面上用的派生边集，<b>上游原件一字未动</b>。</p>
{table(["前置", "", "后继", "处置", "理由"], adj_rows)}

<div class="foot">
数据源：<b>K12-KGraph</b>（北京大学 PKU-DCAI，arXiv:2605.09635，CC BY-NC-SA 4.0）。
原件落盘在 <code>data/raw/</code>，<b>一字未改</b>；全部校验在 <code>data/normalized/</code> 上跑。<br>
教材顺序按人教版排（教材只用来核对顺序，不用来生成知识点）。<br>
本页由 <code>python3 src/build_quality.py</code> 生成，数字全部来自 <code>data/normalized/</code> 下的实跑结果。<br>
生成时间：{__import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M")}
</div>
</div>
</body>
</html>
"""

    OUT.write_text(doc, encoding="utf-8")
    print(f"数据质量页 → {OUT.relative_to(BASE)}  ({OUT.stat().st_size//1024} KB)")
    print(f"  倒挂 {len(rev)} · 覆盖缺口 {len(miss)} · 方向冲突 {len(conf)} "
          f"· 环剪 {len(cyc)} · 可疑 {len(sus)} · 已裁决 {len(adj_rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
