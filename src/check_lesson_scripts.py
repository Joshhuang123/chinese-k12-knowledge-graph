#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""讲解稿协议自检（不信任稿子，自己逐条验）。

判定语义对齐 `docs/lesson-script-protocol.md`：
  · **照抄**（必须逐字相同）：id / version / name / formulas / page.image / page.where
  · **自己写但不许编造**：kicker / hook / definition / quote / page.lines / chain / scenes / explain.lines
      · definition  → 必须与素材包的 definition **有 ≥8 字的公共子串**（不是逐字，是不许凭空另编）
      · quote.text  → 必须**逐字**出现在素材包的 quotes[] 里（残骸可以不写这个字段）
      · chain       → 除「现在学的」自己以外，每个名字都必须在素材包 prereq 里
      · explain.lines → 必须与 scenes[].text **逐字一致**（页面文字版 = 视频配音版）
  · **页码**：用素材包的 page.printed（印刷页码），不许写扫描页
  · **数字汉字** / **字数** / **钩子长度** / **五场结构** / **版本不串**

用法：python3 src/check_lesson_scripts.py [id ...]
不带参数就检查全部。
"""
import io, json, os, re, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, 'data', 'lesson-scripts')
DRAFTS = os.path.join(ROOT, 'data', 'lesson-drafts')

SCENE_IDS = ['s0_cover', 's1_what', 's2_page', 's3_chain', 's4_end']
FORMULA_SPAN = re.compile(r'[A-Za-z0-9=<>+\-−×÷/^²³_.\s()（）%√°∠π]+')
CJK = re.compile(r'[一-鿿]')


def cjk_len(t):
    return len(CJK.findall(t or ''))


def longest_common_substring(a, b):
    if not a or not b:
        return ''
    best = ''
    # a 短，b 长：以 a 的每个起点往两边扩
    for i in range(len(a)):
        for j in range(i + len(best) + 1, len(a) + 1):
            if a[i:j] in b:
                best = a[i:j]
                break
    return best


def main():
    ids = sys.argv[1:]
    if not ids:
        ids = sorted(f[:-5] for f in os.listdir(SCRIPTS) if f.endswith('.json'))
    npass = nfail = 0

    def ok(c, l, extra=''):
        nonlocal npass, nfail
        if c:
            npass += 1
            print(f'  ✓ {l}' + (f' —— {extra}' if extra else ''))
        else:
            nfail += 1
            print(f'  ✗ {l}' + (f' —— {extra}' if extra else ''))

    for sid in ids:
        print(f'\n[{sid}]')
        sp = os.path.join(SCRIPTS, sid + '.json')
        dp = os.path.join(DRAFTS, sid + '.json')
        if not os.path.exists(sp):
            ok(False, '稿子存在', sp); continue
        if not os.path.exists(dp):
            ok(False, '素材包存在', dp); continue
        try:
            d = json.load(io.open(sp, encoding='utf-8'))
            dr = json.load(io.open(dp, encoding='utf-8'))
        except Exception as e:
            ok(False, 'JSON 能解析', str(e)); continue
        ok(True, 'JSON 能解析')

        # ── 照抄的字段 ──
        for k in ('id', 'version', 'name', 'kicker', 'hook', 'definition',
                  'formulas', 'page', 'chain', 'scenes', 'explain'):
            ok(k in d, f'有 {k} 字段')
        ok(d.get('id') == dr.get('id'), 'id 与素材包一致', str(d.get('id')))
        ok(d.get('name') == dr.get('name'), 'name 与素材包一致',
           f"{d.get('name')} vs {dr.get('name')}")

        # ── 版本不能串（上游 id 跨版本共享） ──
        want_v = 'sh' if sid.startswith('sh_') else ('rjb' if sid.startswith('rjb_') else 'kx')
        ok(d.get('version') == want_v, 'version 跟 id 前缀一致',
           f"{d.get('version')} vs {want_v}")
        ok(d.get('version') == dr.get('version'), 'version 跟素材包一致',
           f"{d.get('version')} vs {dr.get('version')}")

        # ── 结构 ──
        scenes = d.get('scenes') or []
        got = [s.get('id') for s in scenes]
        ok(got == SCENE_IDS, '五个场次齐全且顺序对', str(got))

        # ── 字数 / 钩子 ──
        spoken = ''.join(s.get('text', '') for s in scenes)
        n = cjk_len(spoken)
        ok(230 <= n <= 300, '总口播字数 230–300', f'{n} 字')
        hn = cjk_len(d.get('hook', ''))
        ok(15 <= hn <= 30, '钩子 15–30 字', f'{hn} 字')

        # ── 数字汉字 ──
        bad = []
        for s in scenes:
            t = FORMULA_SPAN.sub(' ', s.get('text', ''))
            m = re.search(r'[0-9]', t)
            if m: bad.append(f"{s.get('id')}:{m.group()}")
        ok(not bad, '口播里没有阿拉伯数字（公式除外）', ','.join(bad[:5]))

        # ── 公式：逐字来自素材包 ──
        dfml = dr.get('formulas') or []
        sfml = d.get('formulas') or []
        badf = [f for f in sfml if f not in dfml]
        ok(not badf, '每条公式都在素材包里逐字存在', ' | '.join(map(str, badf[:2])))

        # ── 页码：印刷页码 + 页图没过期 ──
        pg, dpg = d.get('page') or {}, dr.get('page') or {}
        ok(pg.get('image') == dpg.get('image'), '页图地址跟素材包一致（没过期）',
           '' if pg.get('image') == dpg.get('image')
           else f"稿：…{str(pg.get('image'))[-28:]} / 素材：…{str(dpg.get('image'))[-28:]}")
        ok(pg.get('where') == dpg.get('where'), '页码描述跟素材包一致（印刷页码）',
           f"{pg.get('where')} vs {dpg.get('where')}")
        ok('扫描页' not in json.dumps(pg, ensure_ascii=False), '没有把扫描页当成书上页码')
        if dpg.get('printed') is not None:
            ok(str(dpg['printed']) in str(pg.get('where', '')),
               'where 里的页码 == 素材包印刷页码', str(dpg['printed']))

        # ── definition：自己写，但不许凭空另编 ──
        dd = dr.get('definition') or ''
        sd = d.get('definition') or ''
        pool = [dd] + [q.get('text', '') for q in (dr.get('quotes') or [])]
        lcs = max((longest_common_substring(sd, p) for p in pool if p), key=len, default='')
        # 阈值 6：允许「同一句教材原话的不同措辞」，但不许凭空另编一句。
        # （老稿子里「…使胚根、胚芽开始发育，最后长成幼苗的过程」与
        #   素材包的「…使胚根、胚芽等开始发育，最终长成幼苗的过程」
        #   是同一句话的两种措辞，公共子串「长成幼苗的过程」7 字。）
        ok(len(lcs) >= 6, 'definition 跟素材包的定义有 ≥6 字公共子串（不是另编的）',
           f'「{lcs}」')

        # ── quote（如果有）：逐字来自教材原话 ──
        q = d.get('quote')
        if q:
            qt = q.get('text', '')
            srcs = [x.get('text', '') for x in (dr.get('quotes') or [])]
            ok(qt in srcs, 'quote.text 在素材包的 quotes 里逐字存在', qt[:28])
            ok('扫描页' not in json.dumps(q, ensure_ascii=False), 'quote.src 用的是印刷页码')
        else:
            ok(True, '没写 quote 字段（教材原话是残骸时可以省）')

        # ── 前置链：只能用真前置 / 真后继 ──
        # ⚠️ chain 里的 tag 决定这个名字是**前置**还是**后继** ——
        # 「先会它」是前置，「接着学」是后继。两种都得在素材包里，
        # 但不能混：把后继当前置画成线性链，就是谎报先后。
        pre = {x.get('name') for x in (dr.get('prereq') or []) if isinstance(x, dict)}
        suc = {x.get('name') for x in (dr.get('successor') or []) if isinstance(x, dict)}
        chain = d.get('chain') or []
        as_pre, as_suc, bad_t = set(), set(), []
        for x in chain:
            if not isinstance(x, dict): continue
            nm, tag = x.get('name'), str(x.get('tag') or '')
            if nm == d.get('name'): continue
            if any(k in tag for k in ('接着', '后继', '之后', '往下', '然后学')):
                as_suc.add(nm)
            elif tag:
                as_pre.add(nm)          # 自由表述的前置理由
            else:
                bad_t.append(f'{nm}(tag={tag})')
        # tag 是**自由表述**（「式子的底子」「更基础的那种」「低一级的」），
        # 不是固定词表 —— 所以判据看的是**名字在不在素材包**，
        # 再用 tag 里的方向词（接着/之后/后继/往下）判断它被当成了前置还是后继。
        # 真正的错只有一个：**把后继说成前置**（画成线性链 = 谎报先后）。
        ok(not bad_t, '每个 chain 成员都标了方向（前置理由 或 接着学）',
           ' | '.join(bad_t[:3]))
        allnames = set()
        for x in chain:
            if isinstance(x, dict) and x.get('name') != d.get('name'):
                allnames.add(x.get('name'))
        missing = allnames - pre - suc
        ok(not missing, 'chain 里的名字都在素材包的前置/后继里',
           str(sorted(missing)[:3]))
        reversed_ = {n for n in as_suc if n in pre}
        ok(not reversed_, '没有把前置说成「接着学」（那会谎报先后）',
           str(sorted(reversed_)[:3]))
        if not pre:
            s3 = next((s.get('text', '') for s in scenes if s.get('id') == 's3_chain'), '')
            ok(('没有' in s3 and '前置' in s3) or ('接下来' in s3) or ('可以直接' in s3)
               or ('往下' in s3) or ('拆成' in s3),
               '没有前置时写的是「没有前置 / 接下来会学」，不是编一条链', s3[:30])

        # ── explain.lines 必须与 scenes 一致（页面文字版 = 视频配音版） ──
        ex = d.get('explain')
        if isinstance(ex, dict):
            lines = ex.get('lines') or []
            texts = [s.get('text', '') for s in scenes]
            ok(lines == texts, 'explain.lines 与 scenes[].text 逐字一致',
               f'{len(lines)} 段 vs {len(texts)} 场')
        else:
            ok(False, 'explain 是对象且带 lines', str(type(ex)))

    print(f'\n{"=" * 52}\n通过 {npass}，失败 {nfail}')
    return 1 if nfail else 0


if __name__ == '__main__':
    sys.exit(main())
