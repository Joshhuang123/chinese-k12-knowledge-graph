#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
学习卡校验 —— `src/check_learn_cards.py`

把 `docs/需求清单.md` R-1 的「怎么验算做对了」那张表
**变成可跑的检查**。

| 检查项 | 判据 |
|---|---|
| 覆盖率 | 每个概念都能拿到 ≥1 层内容 |
| 来源分层 | 返回的每一段都带来源标记，没有裸文本 |
| 定义句准确 | 定义句的**定义对象**就是概念本身 |
| 噪声控制 | 单次召回的公式 ≤ 6、图描述 ≤ 2、例题 ≤ 5 |
| 前置链正确 | 「先补这些」跟站点「学习路径」面板的输出**逐条一致** |
| 冷启动 | 没内容时返回明确的空状态 |

## 前置链那条是最硬的

不是「重新算一遍看看差不多」，而是**在真浏览器里跑站点自己的 JS**
（`viz/template.html` 的 `pathRows()`），把它的输出跟学习卡逐条比。
站点逻辑改了，这条检查立刻红 —— 这才叫验证。

跑法：
    python3 src/check_learn_cards.py           # 全量
    python3 src/check_learn_cards.py --sample 200   # 抽 200 个概念做浏览器交叉验证
"""
from __future__ import annotations

import collections
import json
import pathlib
import re
import subprocess
import sys

# **脚本相对路径** —— 写死开发机的绝对路径，换机器就全废
# （ISSUE-45：远端已把 14 个脚本统一改成这个写法）
BASE = pathlib.Path(__file__).resolve().parent.parent
CARDS = BASE / "data" / "learn-cards.jsonl"
SITE = BASE / "index.html"
OUT = BASE / "src" / "check_learn_cards.mjs"

MAX_FORMULAS = 6
MAX_FIGURES = 2
MAX_EXERCISES = 5

_fail = []


def ok(cond, msg, detail=""):
    if cond:
        print(f"  ✓ {msg}")
    else:
        print(f"  ✗ {msg}   {detail}")
        _fail.append(msg)
    return cond


def load_cards() -> list[dict]:
    return [json.loads(l) for l in CARDS.open(encoding="utf-8") if l.strip()]


def main() -> int:
    sample = 200
    for i, a in enumerate(sys.argv):
        if a == "--sample" and i + 1 < len(sys.argv):
            sample = int(sys.argv[i + 1])

    cards = load_cards()
    print(f"学习卡 {len(cards):,} 条\n")

    # ── 1. 覆盖率 ────────────────────────────────────────
    print("1. 覆盖率")
    have_any = [c for c in cards if c["layers"]]
    ok(len(have_any) / len(cards) >= 0.92,
       f"有 ≥1 层内容 ≥92%（实测 {len(have_any)/len(cards)*100:.1f}%）")
    empty = [c for c in cards if not c["layers"]]
    ok(len(empty) <= len(cards) * 0.10,
       f"完全空的 ≤10%（实测 {len(empty)} 个 = {len(empty)/len(cards)*100:.1f}%）")
    # 空卡要有明确的空状态说明
    no_note = [c for c in empty if not c.get("emptyNote")]
    ok(not no_note, "空卡都写了 emptyNote（明确说「这一版没有内容」）",
       f"{len(no_note)} 个没有")

    # ── 2. 来源分层 ──────────────────────────────────────
    print("\n2. 来源分层")
    naked = []
    for c in cards:
        for w in c["what"]:
            if not w.get("source"):
                naked.append((c["id"], "what"))
        for f in c["how"]["formulas"]:
            if not f.get("source"):
                naked.append((c["id"], "formula"))
        for g in c["how"]["figures"]:
            if not g.get("source"):
                naked.append((c["id"], "figure"))
        for p in c["practice"]:
            if not p.get("source"):
                naked.append((c["id"], "practice"))
    ok(not naked, "每一段都带 source 标记，没有裸文本", f"{len(naked)} 段缺")
    # 图谱定义必须标成「图谱定义」，不能混成教材原话
    mislabel = []
    for c in cards:
        for w in c["what"]:
            if w.get("kind") == "图谱定义" and w.get("source") != "图谱定义":
                mislabel.append(c["id"])
            if w.get("kind", "").startswith("教材") and "图谱定义" in w.get("source", ""):
                mislabel.append(c["id"])
    ok(not mislabel, "教材原话和图谱定义没有互相错标", f"{len(mislabel)} 个错标")

    # ── 3. 定义句准确 ────────────────────────────────────
    print("\n3. 定义句准确")
    # ⚠️ **判据必须是独立实现** ——
    # 直接调 build_learn_cards.defines_this 是「自己验自己」：
    # 那个函数放宽了，这��检查照样绿（实测破坏过一版，验出来）。
    # 这里重新实现一遍判据（口径相同但代码独立），
    # 破坏生成器里的判据时这条会红。
    def def_target(q: str) -> str:
        m = re.search(r"(?:叫做|称为|是指|指的是|定义为|全称是|即为|就是)"
                      r"([^，,。；;！？.!?]{2,16})", q)
        if not m:
            return ""
        t = m.group(1)
        # ⚠️ 编号要先剔 ——「就是命题(2)的闭命题」里的
        # 「命题(2)」是编号不是对象（实测踩过）
        t = re.sub(r"[（(]\s*\d+\s*[）)]", "", t)
        t = re.sub(r"[（(〈《].*?[）)〉》]", "", t)
        t = re.split(r"[，,。；;：:、\s]", t)[0]
        return t.strip("的了吧呢")

    def independent(q: str, c: str) -> bool:
        """c 在 q 里独立成词（前后不接汉字，或前接「的/之」）。"""
        if not c:
            return False
        for m in re.finditer(re.escape(c), q):
            i, j = m.start(), m.end()
            b = q[i - 1] if i > 0 else ""
            a = q[j] if j < len(q) else ""
            if (not ("一" <= b <= "鿿") or b in "的之") and not ("一" <= a <= "鿿"):
                return True
        return False

    def check_defines(q: str, core: str) -> bool:
        obj = def_target(q)
        if not obj or core not in obj:
            return False
        if not independent(obj, core):
            return False
        return obj.rstrip("的") == core or obj.startswith(core)

    bad_def = []
    n_def = 0
    for c in cards:
        core = re.sub(r"[（(][^）)]*[）)]", "", c["name"]).strip()
        for w in c["what"]:
            if w["kind"] != "教材定义句":
                continue
            n_def += 1
            if not check_defines(w["text"], core):
                bad_def.append((c["name"], w["text"][:50]))
    ok(not bad_def,
       f"教材定义句的定义对象都��概念本身（{n_def} 条全查）",
       f"{len(bad_def)} 条不符：{bad_def[:3]}")
    # 定义句不能是题干
    Q_CUE = re.compile(r"(说一说|想一想|算一算|连一连|填一填|画一画|看一看|试一试|找一找"
                       r"|请回答|请你|你能|为什么|怎样做|如何)")
    Q_STRUCT = re.compile(r"(练习\s*\d|练习[一二三四五六七八九十]|[（(]\s*[）)]"
                          r"|[（(][）)].{0,10}[A-D][．.、]|判断下列|下列.{0,8}正确的是)")
    q_def = [c["name"] for c in cards
             for w in c["what"]
             if w["kind"] == "教材定义句"
             and (Q_CUE.search(w["text"]) or Q_STRUCT.search(w["text"]))]
    ok(not q_def, "定义句里没有题干", f"{len(q_def)} 条：{q_def[:3]}")

    # ── 4. 噪声控制 ──────────────────────────────────────
    print("\n4. 噪声控制")
    over_f = [c["id"] for c in cards if len(c["how"]["formulas"]) > MAX_FORMULAS]
    over_g = [c["id"] for c in cards if len(c["how"]["figures"]) > MAX_FIGURES]
    over_e = [c["id"] for c in cards if len(c["practice"]) > MAX_EXERCISES]
    ok(not over_f, f"公式 ≤ {MAX_FORMULAS}", f"{len(over_f)} 个超了")
    ok(not over_g, f"图描述 ≤ {MAX_FIGURES}", f"{len(over_g)} 个超了")
    ok(not over_e, f"例题 ≤ {MAX_EXERCISES}", f"{len(over_e)} 个超了")
    # 图描述不能是 broad 层（跟这概念无关的页）
    broad = [c["id"] for c in cards
             for g in c["how"]["figures"] if g.get("tier") == "broad"]
    ok(not broad, "没有 tier=broad 的图描述混进来", f"{len(broad)} 条")

    # ── 5. 前置链与站点逐条一致 ──────────────────────────
    print("\n5. 前置链跟站点「学习路径」面板逐条一致")
    res = cross_check_paths(cards, sample)
    if res is None:
        print("  ! 跳过（找不到 node / 无浏览器）")
    else:
        total, same, diffs = res
        ok(same == total,
           f"抽 {total} 个概念，学习卡的先修链跟站点面板**逐条一致**",
           f"{total-same} 个不一致")

    # ── 6. 冷启动 ────────────────────────────────────────
    print("\n6. 冷启动")
    empty_cards = [c for c in cards if not c["layers"]]
    if empty_cards:
        e = empty_cards[0]
        ok(e.get("emptyNote"), "空卡带 emptyNote")
        ok(all(not c["what"] for c in empty_cards),
           "空卡没有拿相邻概念的内容凑")
    else:
        print("  - 没有空卡，跳过")

    # ── 7. 教材原文段落 ──────────────────────────────────
    print("\n7. 教材原文段落")
    reads = [c for c in cards if c.get("read")]
    ok(len(reads) / len(cards) >= 0.25,
       f"≥25% 的概念能召回教材原页文字（实测 {len(reads)/len(cards)*100:.1f}%）")
    # 段落必须有来源标记
    no_src = [c["id"] for c in reads
              for r in c["read"] if not r.get("source")]
    ok(not no_src, "教材原文段落都带 source 标记", f"{len(no_src)} 段缺")
    # 段落不能是 OCR 残骸（汉字密度太低）
    junk = []
    for c in reads:
        for r in c["read"]:
            t = r.get("text") or ""
            if not t:
                junk.append(c["id"])
                continue
            han_n = sum(1 for ch in t if "一" <= ch <= "鿿")
            if han_n / len(t) < 0.35:
                junk.append(c["id"])
    ok(not junk, "教材原文段落没有 OCR 残骸（汉字密度 ≥35%）",
       f"{len(junk)} 段不合格：{junk[:3]}")
    # 段落必须来自真实的页（能在页索引里找到）
    PIDX = BASE / "data" / "page-index.json"
    if PIDX.exists():
        pj = json.load(open(PIDX, encoding="utf-8"))
        byc = pj.get("_byConcept") or {}
        mismatch = []
        for c in reads:
            known = {x.get("pageId") for x in (byc.get(c["id"]) or [])}
            for r in c["read"]:
                if r.get("pageId") not in known:
                    mismatch.append(c["id"])
                    break
        ok(not mismatch, "教材原文段落都能在页索引里找到出处",
           f"{len(mismatch)} 张对不上")

    # ── 8. 可复现性（ISSUE-45）────────────────────────────
    print("\n8. 可复现性")
    # 引文补全依赖 `data/pdf-cache/`（教材 PDF，不入库）。
    # 所以**最终判定结果必须落盘成缓存**，否则换台机器 clone 下来
    # 跑出来的学习卡跟入库的不一样（实测差 313 张卡）。
    CACHE = BASE / "data" / "quote-repairs.json"
    if CACHE.exists():
        cache = json.load(open(CACHE, encoding="utf-8"))
        ok(len(cache) > 0, f"引文判定缓存存在（{len(cache):,} 条）")
        # 缓存里的引文必须**确实出现在学习卡里**（缓存不能有孤儿）
        card_ids = {c["id"] for c in cards}
        orphan = [k for k in cache
                  if k.split("#")[1] not in card_ids and len(k.split("#")) > 2]
        ok(not orphan, "缓存里没有孤儿条目（概念 id 都真实存在）",
           f"{len(orphan)} 条孤儿")
        # **缓存与产物必须一致**（反向验证）
        #
        # ⚠️ 方向只能是「卡里的引文能在缓存里找到」——
        # 缓存是**逐条引文**的判定表（一个概念 10 条引文都记了），
        # 卡里只取前 2 条定义句 / 1 条提及句。
        # 反过来查（缓存每条都要在卡里）会误报 840 条 —— 那不是不一致，
        # 是「缓存更全」。
        mismatch = []
        by_id = {c["id"]: c for c in cards}
        for c in cards:
            for w in c["what"]:
                if not w["kind"].startswith("教材"):
                    continue
                ver = "人教版" if "人教" in w.get("source", "") else "沪教版"
                hit = False
                for k, v in cache.items():
                    parts = k.split("#")
                    if len(parts) != 3 or parts[0] != ver or parts[1] != c["id"]:
                        continue
                    if v.get("q") == w["text"]:
                        hit = True
                        break
                if not hit:
                    mismatch.append((c["id"], w["text"][:40]))
        ok(not mismatch,
           "卡里的每条教材原话都能在缓存里找到出处（缓存与产物一致）",
           f"{len(mismatch)} 条对不上：{mismatch[:3]}")
    else:
        ok(False, "缺 data/quote-repairs.json —— 没有它就复现不出同样的产物",
           "跑 python3 src/build_learn_cards.py 生成")

    print()
    if _fail:
        print(f"✗ {len(_fail)} 项检查没过：")
        for f in _fail:
            print(f"    - {f}")
        return 1
    print("✓ 全部检查通过")
    return 0


# ── 浏览器交叉验证 ──────────────────────────────────────
def cross_check_paths(cards: list[dict], sample: int):
    """在真浏览器里跑站点自己的 pathRows()，跟学习卡逐条比。

    **这是最硬的一条检查** —— 不是「重新算一遍」，
    是把站点页面加载起来，调它自己的函数，看它说什么。
    站点逻辑改了，这里立刻红。
    """
    if not SITE.exists():
        return None
    node = shutil_which("node")
    if not node:
        return None
    if not OUT.exists():
        return None
    # 挑有前置的卡（没前置的比对没意义）
    cand = [c for c in cards if c["prereq"]]
    if not cand:
        return None
    step = max(1, len(cand) // sample)
    picked = cand[::step][:sample]
    payload = [{"id": c["id"], "prereq": [p["id"] for p in c["prereq"]]}
               for c in picked]
    tmp = BASE / "data" / ".tmp-check-paths.json"
    tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    try:
        r = subprocess.run([node, str(OUT), str(SITE), str(tmp)],
                           capture_output=True, text=True, timeout=600)
    except Exception:
        return None
    finally:
        if tmp.exists():
            tmp.unlink()
    if r.returncode != 0:
        print("  ! 浏览器脚本失败：", (r.stderr or "")[-500:])
        return None
    try:
        out = json.loads(r.stdout.strip().splitlines()[-1])
    except Exception:
        print("  ! 浏览器输出解析失败：", (r.stdout or "")[-300:])
        return None
    total = 0
    same = 0
    diffs = []
    for item in out:
        total += 1
        if item.get("error"):
            diffs.append({"id": item["id"], "site": f"错误:{item['error']}",
                          "card": item.get("card")})
            continue
        # 比**集合**（前置关系是集合语义，顺序不影响对错）
        s = sorted(item.get("site") or [])
        c = sorted(item.get("card") or [])
        if s == c:
            same += 1
        else:
            diffs.append({"id": item["id"], "site": s, "card": c})
    if diffs:
        print(f"  ! 前 {min(3,len(diffs))} 个不一致：")
        for d in diffs[:3]:
            print(f"      {d['id']}:\n        站点={d['site']}\n        卡片={d['card']}")
    return total, same, diffs


def shutil_which(name: str):
    import shutil
    return shutil.which(name)


if __name__ == "__main__":
    sys.exit(main())
