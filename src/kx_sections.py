#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
用**视觉模型**读小学科学每一节的首节页，判断：
  1. 这一节是不是一个「可教的知识概念」（而不是活动/回顾/制作）
  2. 它对应上游图谱里的哪个概念（同义词/上位词）

为什么要读页面，不能只看节名
----------------------------
节名筛不出概念：同样是「节名」，
  「磁铁的磁极」是概念，「不倒翁」是对象，「蚕出生了」是活动过程，
  「建造微型植物工厂」是项目，「模拟探索：到火星上去」是任务。
**光看名字只能猜，读了页面才知道这一节实际在讲什么。**
页面是教材原文（一手），节名只是目录里的一个标题。

而且判据「这一节讲的是哪个概念」—— 有了这个答案，
「蚕出生了」→「家蚕」、「不倒翁」→「重心」这类**同义对齐**才能做出来。

跑法：python3 src/kx_sections.py
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import subprocess
import sys
import time

BASE = pathlib.Path("/Users/huangjunhai/Documents/个人/项目/中文知识图谱")
TOC = BASE / "data" / "kx-toc.json"
GRAPH = BASE / "data" / "normalized" / "graph.json"
IMG = BASE / "data" / "pdf-cache" / "kx"
OUT = BASE / "data" / "kx-sections.json"

PROMPT = """这是一页中国小学教材《科学》的正文页。这一页属于下面这一节：

节标题：{section}
所属单元：{unit}
教材：{bookzh}

请判断这一节**实际在讲什么**，只输出 JSON：

{{"isConcept": true 或 false,
  "concept": "这一节的核心知识概念",
  "summary": "一句话说明这一节讲什么（30 字以内）",
  "type": "概念" 或 "活动" 或 "回顾" 或 "制作" 或 "项目"}}

规则：
- 如果这一节是活动、动手制作、单元回顾、观察记录、实验探究过程、
  综合性项目（比如「蚕出生了」「建造微型植物工厂」「模拟探索：到火星上去」）
  → isConcept 填 false，type 填对应的类型，concept 填空字符串
- 如果这一节在讲一个可以单独教的知识点（磁铁的磁极、推力和拉力、雾和云…）
  → isConcept 填 true，type 填 "概念"
- **concept 是这个知识点本身的名字，2-6 个字**：
    「不倒翁」不是概念（那是个玩具），「重心」才是
    「金鱼」不是概念（那是个动物），「动物的身体特征」才是
    「蚕出生了」不是概念（那是过程），「家蚕的生活史」才是
  用教材自己的说法，不要编。
- summary 用教材的话，不要补充页面上没有的内容
- 这一页如果只是目录/扉页/空白页，输出 {{"isConcept": false, "concept": "", "summary": "非正文页", "type": "空白"}}"""

UA = {"User-Agent": "Mozilla/5.0"}


def upload(path: pathlib.Path) -> str:
    r = subprocess.run(["mcode-tools", "upload_temp_url", str(path), "--mime-type", "image/jpeg"],
                       capture_output=True, text=True, timeout=180)
    i = r.stdout.find("{")
    if i < 0:
        return ""
    try:
        return json.loads(r.stdout[i:])["temp_url"]
    except Exception:
        return ""


def call_batch(items: list[tuple[str, str, str]]) -> list[str]:
    """items = [(section, url, unit)] → 每个的 JSON 文本"""
    info = []
    for section, url, unit in items:
        info.append({
            "url": url,
            "prompt": PROMPT.replace("{section}", section).replace("{unit}", unit),
        })
    args = {"image_info": info}
    p = pathlib.Path("/tmp/kx_sec_args.json")
    p.write_text(json.dumps(args, ensure_ascii=False), encoding="utf-8")
    r = subprocess.run(["mcode-tools", "connector", "call",
                        "connector__matrix__describe_images", "--args-file", str(p)],
                       capture_output=True, text=True, timeout=900)
    i = r.stdout.find("{")
    if i < 0:
        return []
    try:
        d = json.loads(r.stdout[i:])
    except Exception:
        return []
    out = []
    for res in d.get("results") or []:
        out.append(res.get("description") or "")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch", type=int, default=10)
    args = ap.parse_args()

    toc = json.load(open(TOC, encoding="utf-8"))
    graph = json.load(open(GRAPH, encoding="utf-8"))
    upnames = sorted({n.get("name") or "" for n in graph["nodes"]
                      if n.get("label") in ("Concept", "Skill", "Experiment")
                      and (n.get("name") or "")})
    # 给模型一份上游概念表做对齐参考（太长就截断）
    vocab = "、".join(upnames[:1200])
    print(f"上游概念词表 {len(upnames)} 个，给模型前 1200 个做参考")

    # 已经挂上上游概念的节不做这一轮（它们已经对齐过了）
    rows = [json.loads(l) for l in open(BASE / "data" / "concept-vision-kx.jsonl", encoding="utf-8")]
    done_secs = set()
    for r in rows:
        for bk, v in r["perBook"].items():
            if v.get("section"):
                done_secs.add((bk, v["section"]))

    # 收集待判定的节：每一节的首节页
    tasks = []
    for bk in sorted(toc):
        off = toc[bk].get("_offset", 0)
        for u in toc[bk]["units"]:
            for s in u["sections"]:
                nm = s.get("name") or ""
                if not nm or "回顾" in nm or "复习" in nm:
                    continue
                if (bk, nm) in done_secs:
                    continue
                pg = s.get("startPage")
                if not isinstance(pg, int):
                    continue
                scan = pg + off        # 印刷页码 → 扫描序号
                f = IMG / bk / f"p{scan:03d}.jpg"
                if not f.exists():
                    continue
                tasks.append({
                    "book": bk, "unit": u.get("name") or "", "section": nm,
                    "page": pg, "scanPage": scan, "file": str(f),
                    "bookZh": f"{bk.replace('s6-','')}",
                })
    print(f"待判定的节：{len(tasks)}")

    # 上传
    for t in tasks:
        if not t.get("url"):
            t["url"] = upload(pathlib.Path(t["file"]))
    tasks = [t for t in tasks if t.get("url")]
    print(f"上传成功 {len(tasks)} 页")

    # 分批调用
    results = {}
    B = args.batch
    for i in range(0, len(tasks), B):
        chunk = tasks[i:i + B]
        items = [(t["section"], t["url"], t["unit"]) for t in chunk]
        outs = call_batch(items)
        for t, o in zip(chunk, outs + [""] * (len(chunk) - len(outs))):
            m = re.search(r"\{.*\}", o or "", re.S)
            d = {}
            if m:
                try:
                    d = json.loads(m.group(0))
                except Exception:
                    d = {}
            results.setdefault(f"{t['book']}|{t['section']}", []).append({
                "book": t["book"], "unit": t["unit"], "section": t["section"],
                "page": t["page"], "scanPage": t["scanPage"],
                "bookZh": t["bookZh"],
                **d,
            })
        print(f"  {min(i+B, len(tasks))}/{len(tasks)}", flush=True)

    # 落盘
    out = []
    for k, v in results.items():
        for x in v:
            x["vocab"] = None      # 不存词表，太大
            out.append(x)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n→ {OUT}（{len(out)} 条）")
    ncon = sum(1 for x in out if x.get("isConcept"))
    print(f"判定为概念的：{ncon} / {len(out)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
