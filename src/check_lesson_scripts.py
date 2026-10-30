#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""讲解稿协议自检（不信任稿子，自己逐条验）。

判定语义对齐 `docs/lesson-script-protocol.md`：
  · **照抄**（必须逐字相同）：id / version / name / formulas / page.image / page.where
  · **自己写但不许编造**：kicker / hook / definition / quote / page.lines / chain / scenes / explain.lines
      · definition  → 与素材包的 definition **相似度 ≥0.60**（不是逐字，是不许凭空另编）
      · quote.text  → 必须**逐字**出现在素材包的 quotes[] 里（残骸可以不写这个字段）
      · chain       → 除「现在学的」自己以外，每个名字都必须在素材包 prereq 里
      · explain.lines → 必须与 scenes[].text **逐字一致**（页面文字版 = 视频配音版）
  · **页码**：用素材包的 page.printed（印刷页码），不许写扫描页
  · **数字汉字** / **字数** / **钩子长度** / **五场结构** / **版本不串**

用法：python3 src/check_lesson_scripts.py [id ...]
不带参数就检查全部。
"""
import difflib
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
        # ⚠️ 判据是**相似度**，不是「有几个字一样」——
        #   「≥6 字公共子串」一句话就能绕过：
        #   在一段完全跑偏的定义里嵌 8 个来自素材包的字，判据照样绿
        #   （verifier 实测：讲压强/密度的定义 + 「受到向上的力，」→ 31/31 全绿）。
        #   相似度看的是「整体说的是不是同一件事」。
        #   真实数据分布：43 份稿子的相似度**最低 0.90**（中位数 1.00），
        #   绕过样本 0.12 —— 阈值 0.60 两侧都很宽裕。
        dd = dr.get('definition') or ''
        sd = d.get('definition') or ''
        sim = difflib.SequenceMatcher(None, sd, dd).ratio() if (sd and dd) else 0.0
        ok(sim >= 0.60, 'definition 与素材包的定义相似度 ≥0.60（不是另编的）',
           f'{sim:.2f}')

        # ── quote（如果有）：逐字来自教材原话 ──
        # ⚠️ **「不在素材包 quotes 里」不等于「错」** ——
        #   有些概念（教材原话层根本没抽到句子）的原话是**照着教材原页图**抄的。
        #   verifier 实测：浮力那条被当成「无源引文」删掉的句子，
        #   逐字印在 data/pages/physics-8b/53.webp 上：
        #     「冰山、游船、鸭子都受到重力的作用，但却没有因此而沉入水底，
        #       这表明水对它们有一个向上托起的力。浸在液体中的物体受到向上的力，
        #       这个力叫做浮力。」
        #   它是**真教材原话**，只是不在 concept-text 层里。
        #   所以：不在素材包里时，必须显式标 `from_page: true`（来自原页图），
        #   让人知道「这句要人工核对」；既不逐字存在、又没标 → 判红。
        q = d.get('quote')
        if q:
            qt = q.get('text', '')
            srcs = [x.get('text', '') for x in (dr.get('quotes') or [])]
            # ⚠️ **子串也算** ——
            #   写稿的人常常只取长句里**干净的那一段**
            #   （例：「计算公式如下:发首率二萌发种子数_全部被测种子数一般种子的发芽率
            #     在90%以上才适合用于播种。」→ 稿子引的是后面那句干净的话）。
            #   那是**逐字**，不是改写 —— 只是没引整句。
            if any(qt in x for x in srcs):
                ok(True, 'quote.text 在素材包的某条原话里逐字出现', qt[:28])
            else:
                ok(bool(q.get('from_page')),
                   'quote 不在素材包里 → 必须标 from_page（来自教材原页图，待人工核对）',
                   f"from_page={q.get('from_page')}")
            ok('扫描页' not in json.dumps(q, ensure_ascii=False), 'quote.src 用的是印刷页码')
        else:
            ok(True, '没写 quote 字段（教材原话是残骸时可以省）')

        # ── 前置链：只能用真前置 / 真后继 ──
        # ── 前置链：方向不能谎报 ──
        # ⚠️ **方向不由 tag 决定** ——
        #   tag 是**自由表述**（「式子的底子」「怎么查」「更基础的那种」），
        #   不是「先会它/接着学」这种固定词表。原来拿 tag 判方向，
        #   判据既漏又误：verifier 实测把真前置换成真后继、tag 不动 → 31/31 全绿；
        #   而实际数据里 tag="怎么查"/"怎么理" 的两条**本来就是真后继**，
        #   被判成「把后继说成前置」→ 假警报。
        #
        #   方向真正由**素材包的 chain_title** 决定（视频和页面画的就是它）：
        #     「学它之前要先会」→ 这些是真前置
        #     「接下来会学」    → 这些是真后继
        #   而学生看到的是**第四场的台词**，所以还要看台词说不说同一件事。
        pre = {x.get('name') for x in (dr.get('prereq') or []) if isinstance(x, dict)}
        suc = {x.get('name') for x in (dr.get('successor') or []) if isinstance(x, dict)}
        chain = [x for x in (d.get('chain') or []) if isinstance(x, dict)]
        names = {x.get('name') for x in chain
                 if x.get('name') and x.get('name') != d.get('name')}
        missing = names - pre - suc
        ok(not missing, 'chain 里的名字都在素材包的前置/后继里',
           str(sorted(missing)[:3]))
        no_tag = [x.get('name') for x in chain if x.get('name') != d.get('name')
                  and not str(x.get('tag') or '').strip()]
        ok(not no_tag, '每个 chain 成员都标了说明', ' | '.join(map(str, no_tag[:3])))
        # 方向：素材包的 chain_title 说是前置还是后继
        title = dr.get('chain_title') or ''
        is_fwd = '接下来' in title          # 往后学
        wrong = ({n for n in names if n in pre} if is_fwd
                 else {n for n in names if n in suc and n not in pre})
        ok(not wrong, '链的方向跟素材包一致（不谎报先后）',
           str(sorted(wrong)[:3]))
        # 台词说的方向也要跟链一致 —— 那才是学生真正读到的那句话
        s3 = next((sc.get('text', '') for sc in scenes if sc.get('id') == 's3_chain'), '')
        if is_fwd:
            ok(any(k in s3 for k in ('往下', '接下来', '再学', '之后', '接着')),
               '第四场台词说的是「往后学」，跟链一致', s3[:26])
        else:
            ok(any(k in s3 for k in ('之前', '先会', '先要', '得先', '要先')),
               '第四场台词说的是「先会」，跟链一致', s3[:26])
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
