#!/usr/bin/env python3
"""
探针：用大模型重建一个知识点的先修关系，跟已有数据对账。

**为什么要有这个探针**

现有数据（K12-KGraph）的概念层先修边只覆盖了 30.3%（5,524/7,938 个知识点
没有入边）。补法有两条：向上游要，或者自己重建。

自己重建的想法是：用大模型逐个知识点地问「学它之前必须先会什么」。
但这条路**最大的风险不是准不准，是看起来准**——
上游 3,703 条先修边里 189 组共用同一句教材原文，257 对边中只有 1 对
真是环，组级精确率 0.5%。也就是说：一句看起来有理有据的话，
可以同时支撑两条互相矛盾或毫不相干的边。

所以重建之前必须先量三件事，量不出来就没有下一步：

| 指标 | 含义 | 为什么重要 |
|---|---|---|
| **可映射率** | 模型说的概念名，有多少能在我们 7,938 个节点里对上 | 对不上就等于在造新词，跨版本没法复用 |
| **召回率** | 数据里已有的前置，模型提到了多少 | 低了说明模型比原数据集还稀疏，补不了 |
| **一致率** | 模型提到的、有多少数据里确实有 | 低了说明两套答案冲突，不能直接覆盖 |

**盲测**：不给模型看任何已有边。只给「概念名 + 定义 + 学科」。
给了就等于让它抄答案，一致率会假到没有意义。

## 跑法

```bash
python3 src/probe_llm_prereq.py                    # 默认 16 个抽样知识点
python3 src/probe_llm_prereq.py --n 40            # 扩大样本
python3 src/probe_llm_prereq.py --show             # 逐条打印模型说了什么
```

一条样本 = 一次模型调用。M3 单次约 3–8 秒，16 条约 1–2 分钟。
"""
import argparse
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import time

import yaml

BASE = pathlib.Path(__file__).resolve().parent.parent
GRAPH = BASE / "data" / "normalized" / "graph.json"
LLM = pathlib.Path.home() / ".minimax/.builtin-skills/llm-call/scripts/llm_call.py"

# 分层抽样：四个学科都要有，且刻意混入「数据里本来就没有前置」的那些——
# 那正是要补的地方，如果模型在这类知识点上还给不出东西，这条路就不通。
SAMPLE = [
    # —— 数据里本来就没有前置的（要补的就是这类）——
    "math_9a_rjb_cpt16",    # 二次函数[九上]      前置 0
    "math_4b_rjb_cpt1",     # 加数[四下]          小学，前置 0
    "math_3b_rjb_cpt1",     # 小数[三下]          小学，前置 0
    "physics_8b_rjb_cpt51", # 浮力[八下]          前置 0
    # —— 数据里前置正常的（看能不能还原出来）——
    "math_8b_rjb_cpt50",    # 一次函数[八下]
    "physics_9_rjb_cpt76",  # 欧姆定律[九年级]
    "physics_8b_rjb_cpt33", # 压强[八下]
    "biology_7a_rjb_cpt1",  # 生物[七上]          概念层入口
]

SYSTEM = """你是一位中国 K12 理化生数课程的教研员。
任务：判断学习一个知识点之前，必须先掌握哪些知识。

**硬要求**
1. 只输出 JSON，不要任何解释文字、不要 markdown 代码块。
2. 「必须先会」的标准是**严格定义上的必要条件**：不懂 A 就无法理解 B。
   「教材上排在前面」「同一个单元」「通常一起学」都不算。
   宁可少列也不要凑数 —— 凑数会把 30% 的真实覆盖率变成 90% 的噪音。
3. 必须从下面这份候选清单里选名字，不许自己造词。
4. 每个前置要给出**理由**，理由必须说明「不懂它为什么就学不了」，
   不能写「它是基础」「教材先学」这种空话。

输出格式：
{"prereq":[{"name":"候选清单里的原名","why":"一句话，说清不懂它为什么就学不了"}]}

候选清单里没有的，即使你觉得该有，也不要写。"""


def load():
    g = json.load(open(GRAPH, encoding="utf-8"))
    return g["nodes"], {e["from"]: [] for e in g["edges"]}, {e["to"]: [] for e in g["edges"]}


def _config_with_real_key():
    """脚本只从 config.yaml 读 apiKey，而那份文件里是占位符 sk-xxx。

    所以临时拼一份 config：把环境里的真 key 注进去，交给 llm_call.py 用，
    跑完立刻删。**不打印 key，不落进项目目录**（写在 /tmp，权限 600）。
    这是唯一一处碰凭据的地方，探针本身不需要知道 key 的值。
    """
    key = os.environ.get("MINIMAX_API_KEY", "")
    if not key:
        return None, "环境里没有 MINIMAX_API_KEY"
    cfg = yaml.safe_load(open(pathlib.Path.home() / ".minimax/config.yaml", encoding="utf-8"))
    for prov in cfg.get("provider", {}).values():
        prov.setdefault("options", {})["apiKey"] = key
    fd, path = tempfile.mkstemp(prefix="kg-llm-", suffix=".yaml")
    os.chmod(path, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        yaml.safe_dump(cfg, f, allow_unicode=True)
    return path, None


def ask(node, candidates, model, cfg_path, max_tokens=2048, timeout=180):
    desc = (node.get("props") or {}).get("definition") or ""
    cand = "\n".join(f"- {c['name']}（{c['bookZh']}）" for c in candidates)
    user = (f"知识点：{node['name']}（{node['bookZh']}·{node['subjectZh']}）\n"
            f"定义：{desc or '（无）'}\n\n"
            f"候选清单（前置必须从这里选）：\n{cand}\n\n"
            f"请给出「{node['name']}」的必须先会项。")
    cmd = [sys.executable, str(LLM), "-m", model, "-s", SYSTEM, "-p", user,
           "--config", cfg_path,
           "--max-tokens", str(max_tokens), "--timeout", str(timeout), "--json"]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 60)
    if r.returncode != 0:
        return None, (r.stderr or "")[-300:]
    try:
        payload = json.loads(r.stdout)
    except Exception:
        # 少数情况下模型会在 JSON 前后带话，这里抠出第一段 JSON
        t = r.stdout.strip()
        i, j = t.find("{"), t.rfind("}")
        if i < 0 or j <= i:
            return None, "返回里找不到 JSON"
        payload = json.loads(t[i:j + 1])
    text = payload.get("content") or ""
    if isinstance(text, list):                       # 有些协议返回内容块
        text = "".join(b.get("text", "") for b in text if isinstance(b, dict))
    i, j = text.find("{"), text.rfind("}")
    if i < 0 or j <= i:
        return None, f"模型没给 JSON：{text[:200]}"
    try:
        return json.loads(text[i:j + 1]), None
    except Exception as e:
        return None, f"JSON 解析失败：{e}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=10, help="抽样几个知识点")
    ap.add_argument("--model", default="minimax/MiniMax-M3")
    ap.add_argument("--show", action="store_true", help="逐条打印")
    args = ap.parse_args()

    nodes, out_e, in_e = load()
    byid = {n["id"]: n for n in nodes}
    ids = [i for i in SAMPLE if i in byid][: args.n]
    if not ids:
        print("抽样 id 都不在数据里，先修 data/normalized/graph.json")
        return 2

    cfg_path, cerr = _config_with_real_key()
    if cerr:
        print(cerr)
        return 2

    allnames = {}
    for n in nodes:
        if n["label"] in ("Concept", "Skill") and n["name"].strip():
            allnames.setdefault(n["name"], []).append(n)

    n_map = n_hit = n_rec = n_exist = 0
    rows = []
    for tid in ids:
        node = byid[tid]
        # 候选清单：同学科全部，排除自己 —— 不跨学科，避免模型编跨学科依赖
        cands = [n for n in nodes
                 if n["subject"] == node["subject"] and n["id"] != tid
                 and n["label"] in ("Concept", "Skill") and n["name"].strip()]
        if len(cands) > 900:
            cands = cands[:900]
        t0 = time.time()
        res, err = ask(node, cands, args.model, cfg_path)
        dt = time.time() - t0
        if err:
            print(f"  ✗ {node['name']}  {err}")
            rows.append((node["name"], None, None, None, None, dt, err))
            if '401' in err or 'token' in err.lower():
                print("     鉴权就挂了，后面几条不用跑了")
                break
            continue

        got = res.get("prereq") or []
        gold = [byid[e["from"]]["name"] for e in in_e.get(tid, [])]
        goldset = set(gold)
        mapped = [g for g in got if g.get("name") in allnames]
        hits = [g for g in mapped if g["name"] in goldset]
        n_map += len(mapped)
        n_hit += len(hits)
        n_rec += len(goldset)
        n_exist += len(mapped)
        rows.append((node["name"], len(gold), len(got), len(mapped), len(hits), dt, None))
        if args.show:
            print(f"\n  【{node['name']}】{node['bookZh']}  {dt:.1f}s")
            print(f"    数据里已有前置 {len(goldset)}: {gold}")
            for g in got:
                mark = "✓对上" if g.get("name") in goldset else ("·有名字" if g.get("name") in allnames else "✗不在清单")
                print(f"    [{mark}] {g.get('name')}  ← {g.get('why','')}")

    os.unlink(cfg_path)          # 临时 config 里有真 key，跑完立刻删

    print("\n" + "=" * 56)
    ok = sum(1 for r in rows if r[6] is None)
    print(f"样本 {len(ids)} 个，成功 {ok} 个")
    if n_exist:
        print(f"可映射率（模型说的名字能在图里对上） {n_map}/{n_exist} = {100*n_map/n_exist:.0f}%"
              f"  ← 跨版本复用的前提")
    if n_rec:
        print(f"召回率（数据里已有的前置被提到）     {n_hit}/{n_rec} = {100*n_hit/n_rec:.0f}%")
    if n_map:
        print(f"一致率（模型说的确实存在）           {n_hit}/{n_map} = {100*n_hit/n_map:.0f}%")
    print("\n读法：一致率越高越可信，但它同时越说明模型在抄常识；"
          "召回率低说明补不上缺口；可映射率低说明模型在造词，跨版本用不了。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
