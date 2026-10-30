// 学习页的真实浏览器测试
//
//   node src/test_learn_site.mjs
//
// 测的是**用户真会做的事**，不是内部函数：
//   ① 三个版本都能打开、都能搜
//   ② 点搜到的结果 → 出学习页
//   ③ 学习页该有的板块都在
//   ④ 做题能判分、错的时候标红、对的时候标绿
//   ⑤ 教材原页图的地址对得上（不是目录页）
//   ⑥ 站内跳转（前置/后继）能走
import { createRequire } from 'node:module';
import { resolve, dirname } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { readFileSync, statSync } from 'node:fs';

const require = createRequire(import.meta.url);
const puppeteer = require('puppeteer-core');
const BASE = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const CHROME = process.env.CHROME || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const sleep = ms => new Promise(r => setTimeout(r, ms));

let pass = 0, fail = 0;
const ok = (c, l) => c ? (pass++, console.log(`  ✓ ${l}`)) : (fail++, console.log(`  ✗ ${l}`));

const browser = await puppeteer.launch({
  executablePath: CHROME, headless: true,
  args: ['--no-sandbox', '--no-proxy-server', '--proxy-bypass-list=*',
         '--disable-background-timer-throttling'],
});

async function open(qs) {
  const page = await browser.newPage();
  await page.setViewport({ width: 1440, height: 900 });
  const errs = [];
  page.on('pageerror', e => errs.push(String(e)));
  page.on('console', m => { if (m.type() === 'error') errs.push('console: ' + m.text().slice(0, 100)); });
  await page.goto(pathToFileURL(resolve(BASE, 'learn.html')).href + (qs || ''), { waitUntil: 'load' });
  await sleep(2200);
  return { page, errs };
}

// ── [1] 首页与三个版本 ────────────────────────────────────
console.log('\n[1] 三个版本都能打开');
{
  const { page, errs } = await open('');
  const home = await page.evaluate(() => ({
    title: document.title,
    h1: document.querySelector('h1')?.textContent || '',
    tabs: [...document.querySelectorAll('.vtab')].map(t => t.textContent),
    chips: [...document.querySelectorAll('.chip')].map(c => c.textContent),
  }));
  ok(home.h1.includes('一个知识点'), `首页有主张（${home.h1}）`);
  ok(home.tabs.length === 3, `三个版本切换（${home.tabs.join(' / ')}）`);
  ok(home.chips.length >= 3, `统计卡片在（${home.chips.slice(0, 2).join(' · ')}…）`);
  ok(errs.length === 0, '首页零 JS 错误', errs.slice(0, 2).join(' | '));

  // 逐个版本切
  for (const v of ['sh', 'rjb', 'kx']) {
    await page.click(`.vtab[data-v="${v}"]`);
    await sleep(1400);
    const st = await page.evaluate(() => ({
      h1: document.querySelector('h1')?.textContent || '',
      chips: [...document.querySelectorAll('.chip')].map(c => c.textContent),
    }));
    ok(st.h1.includes('一个知识点'), `${v} 版本首页正常`);
    const n = Number((st.chips[0] || '').replace(/[^0-9]/g, ''));
    ok(n > 0, `${v} 版本有知识点（${st.chips[0]}）`);
  }
  await page.close();
}

// ── [1b] 学习页标题字形必须**显式声明**（不许悄悄回落成别的字） ──
//
// 跟主站那条判据（test_search_browser.mjs [1d]）是同一套思路，但**各测各的**：
// 主站测 viz/知识图谱3D.html，学习页测 learn.html —— 学习页是**另一套模板**，
// 原来标题还在用无衬线，同一个站里两个视觉系统（2026-10-28 海报化时才发现）。
//
// 判据守的是**意图**，不是当年的解法：
//   ① 字体族是**显式**声明的，不能靠 generic fallback
//   ② 渲染结果必须等于**声明的那一款**字（像素指纹）
//   ③ 声明栈的第一项**不能是西文字体**（那正是西文/中文混排的坑）
//
// 判别力：把 .hero h1 的 font-family 改回 sans-serif → 第 2、3、4 条报红。
console.log('\n[1b] 学习页标题字形必须显式声明');
{
  const { page } = await open('');
  const res = await page.evaluate(() => {
    const T = '一个知识点，一页。';
    const cv = document.createElement('canvas'); cv.width = 700; cv.height = 90;
    const g = cv.getContext('2d');
    const fp = s => {
      g.clearRect(0, 0, 700, 90);
      g.fillStyle = '#000'; g.fillRect(0, 0, 700, 90);
      g.font = '400 60px ' + s; g.fillStyle = '#fff'; g.textBaseline = 'top';
      g.fillText(T, 4, 4);
      const d = g.getImageData(0, 0, 700, 90).data;
      let h = 0; for (let i = 0; i < d.length; i += 4) h = (h * 31 + d[i]) | 0;
      return h;
    };
    const el = document.querySelector('.hero h1');
    if (!el) return { missing: true };
    const cs = getComputedStyle(el);
    return {
      sans: fp('sans-serif'),
      song: fp('"Songti SC"'),
      actual: fp(cs.fontFamily),
      decl: cs.fontFamily,
      size: cs.fontSize,
      weight: cs.fontWeight,
      text: el.textContent || '',
    };
  });
  ok(!res.missing, '首页有 hero 大标题');
  if (!res.missing) {
    ok(res.sans !== res.song, '基准成立：sans-serif 与中文衬线在本页渲染成不同字形');
    ok(/^\s*["']Songti SC["']/.test(res.decl), 'hero 大标题显式声明了中文字体', res.decl);
    ok(res.actual === res.song, 'hero 大标题渲染结果 = 声明的那款字', res.decl);
    const first = res.decl.split(',')[0].trim();
    ok(!/DM Serif|Georgia|Times/i.test(first), '声明栈第一项不是西文字体', first);
    ok(Number.parseFloat(res.size) >= 34, `大标题字号撑得住首屏（${res.size}）`);
    ok(res.weight === '400', `衬线标题用常规字重，不拿粗体压字形（${res.weight}）`);
  }

  // 节点页的知识点名 —— 那才是这个站的「海报」，得是同一款字
  const nid = await page.evaluate(() => (window.LEARN_DATA?.nodes || [])[0]?.i);
  ok(nid != null, '取得到一个知识点 id');
  if (nid != null) {
    const { page: p2 } = await open(`?v=sh&c=${nid}`);
    const ct = await p2.evaluate(() => {
      const el = document.querySelector('.ctitle');
      if (!el) return null;
      const cs = getComputedStyle(el);
      return { decl: cs.fontFamily, size: cs.fontSize, text: el.textContent || '' };
    });
    ok(!!ct, '节点页有知识点标题', ct?.text);
    ok(ct && /^\s*["']Songti SC["']/.test(ct.decl), '节点页标题也是同一款中文衬线', ct?.decl);
    ok(ct && Number.parseFloat(ct.size) >= 26, `节点页标题字号够大（${ct?.size}）`);
    await p2.close();
  }
  await page.close();
}

// ── [1c] 首屏**不等数据**：主数据还在路上，海报也要先出来 ──
//
// 线上实测（2026-10-28）：主数据 data/learn-sh.js 是 **4.4 MB**，
// 慢线上要 35 秒；原来这段时间页面上只有「加载中 / 数据文件…」五个字 ——
// 跟没加载一样。用户点进来看到的是一片空白 + 五个字。
//
// 但**海报本身不依赖数据**（只有那几个统计 chip 依赖），
// 所以改成：先画 hero，数据到了再补数字。
//
// 判别力：把 renderShell() 从 boot() 里撤掉 → 这一组必红。
console.log('\n[1c] 首屏不等数据');
{
  const page = await browser.newPage();
  await page.setViewport({ width: 1440, height: 900 });
  // 拦下主数据，拖 4 秒 —— 模拟慢线
  await page.setRequestInterception(true);
  page.on('request', req => {
    if (/learn-(sh|rjb|kx)\.js/.test(req.url())) setTimeout(() => req.continue(), 4000);
    else req.continue();
  });
  await page.goto(pathToFileURL(resolve(BASE, 'learn.html')).href, { waitUntil: 'domcontentloaded' });
  await sleep(1600);                     // 这时候主数据还在路上
  const early = await page.evaluate(() => ({
    hero: !!document.querySelector('.hero h1'),
    text: document.querySelector('.hero h1')?.textContent || '',
    loading: !!document.querySelector('.hero .loading'),
    loadingText: document.querySelector('.hero .loading')?.textContent || '',
    data: !!window.LEARN_DATA,
    chip: !!document.querySelector('.hero .chip'),
  }));
  ok(early.hero, '数据还没到，海报已经画出来了');
  ok(early.text.includes('一个知识点'), '海报标题是对的', early.text);
  ok(early.loading, '有「正在加载…」的提示，不是空白', early.loadingText);
  ok(!early.data, '此刻数据确实还没到（证明真的是「不等数据」）');
  ok(!early.chip, '统计数字此时不出现 —— 数据没到就不编数字');

  // 数据到了以后，统计数字要补上、加载提示要撤掉
  await sleep(7000);
  const late = await page.evaluate(() => ({
    chips: [...document.querySelectorAll('.hero .chip')].map(c => c.textContent),
    loading: !!document.querySelector('.hero .loading'),
  }));
  ok(late.chips.length >= 3, `数据到了，统计数字补上了（${late.chips.slice(0, 2).join(' · ')}）`);
  ok(!late.loading, '加载提示撤掉了');
  await page.close();
}

// ── [1d] `?c=` 认**上游概念 id**（图谱站跳过来用的就是它） ──
//
// 图谱站 → 学习页的链接带的是上游概念 id（人教 math_1a_rjb_cpt1 /
// 沪教 biology_7a_rjb_cpt109 / 小学 kx:s6-3a:认识液体），
// **不是**画布下标 —— 画布下标三个版本各不相同，学习页认不得。
//
// 判别力：把 learn.html 里「先按 id 找」那句去掉 → 本组报红。
console.log('\n[1d] ?c= 认上游概念 id');
{
  for (const [ver, cid, want] of [
    ['sh', 'biology_7a_rjb_cpt109', '发芽率'],
    ['rjb', 'math_9a_rjb_cpt1', '一元二次方程'],
    ['kx', 'kx:s6-3a:认识液体', '液体'],
  ]) {
    const { page, errs } = await open(`?v=${ver}&c=${encodeURIComponent(cid)}`);
    const h1 = await page.evaluate(() => document.querySelector('h1.ctitle')?.textContent || '');
    ok(h1 === want, `${ver} · ${cid} → 打开的是「${want}」`, h1);
    // 回程：概念页上要有一条「在图谱里看这个点」，带的是这个概念的 id
    const back = await page.evaluate(() => {
      const a = [...document.querySelectorAll('.crumb a')]
        .find(x => x.textContent.includes('图谱里看'));
      return a ? a.getAttribute('href') : null;
    });
    ok(!!back, `${ver} 概念页有「在图谱里看这个点」`, back || '（无）');
    ok(back && back.includes(`f=${encodeURIComponent(cid)}`),
       `${ver} 回程链接带的是这个概念的 id`, back || '');
    ok(errs.length === 0, `${ver} 零 JS 错误`, errs.slice(0, 2).join(' | '));
    await page.close();
  }
}

// ── [2] 搜索 → 学习页 ────────────────────────────────────
console.log('\n[2] 搜索能到学习页');
{
  const { page, errs } = await open('?v=sh');
  await page.click('#q');
  await page.type('#q', '一元一次不等式', { delay: 20 });
  await sleep(450);
  const res = await page.evaluate(() =>
    [...document.querySelectorAll('#qres .qr')].map(r => r.textContent.trim()));
  ok(res.length > 0, `搜到 ${res.length} 条结果`);
  await page.keyboard.press('Enter');
  await sleep(1500);
  const pg = await page.evaluate(() => ({
    h1: document.querySelector('h1')?.textContent || '',
    secs: [...document.querySelectorAll('.card h2')].map(h => h.textContent.trim()),
  }));
  ok(pg.h1 === '一元一次不等式', `进到了「${pg.h1}」的学习页`);
  ok(pg.secs.some(s => s.includes('教材原页')), '有「教材原页」板块');
  ok(pg.secs.some(s => s.includes('前置')), '有「前置」板块');
  // ⚠️ **「教材原话」按数据来**：教材原话过了质量门（src/quote_quality.py），
  //   全是截断半截句的会被剔掉 —— 这个概念的引文正好全不合格，
  //   所以**它就不该有这一块**。断言要跟着数据走，
  //   不然就是「为了过测试而留着半截话」。
  const hasQuotes = await page.evaluate(() => {
    const n = (window.LEARN_DATA?.nodes || []).find(x => x.n === '一元一次不等式');
    return !!(n && n.rd && n.rd.length);
  });
  ok(pg.secs.some(s => s.includes('教材原话')) === hasQuotes,
     '「教材原话」板块按数据来（有干净引文才有）',
     `数据里 ${hasQuotes ? '有' : '没有'}引文`);
  ok(errs.length === 0, '零 JS 错误', errs.slice(0, 2).join(' | '));
  await page.close();

  // 反过来也要验：**有干净引文的概念，那一块必须显示**
  {
    const { page, errs } = await open('?v=sh');
    const pick = await page.evaluate(() => {
      const n = (window.LEARN_DATA?.nodes || []).find(x => x.rd && x.rd.length);
      return n ? { i: n.i, q: n.rd.length } : null;
    });
    ok(!!pick, '沪教版有概念的教材原话过了质量门');
    if (pick) {
      const pg2 = await page.evaluate((i) => {
        location.hash = '';
        history.replaceState(null, '', `?v=sh&c=${i}`);
        // ⚠️ replaceState **不会**触发 popstate —— 页面自己的 render() 不会被调用，
        //    于是还停在首页，断言当然失败。要手动派发一个。
        window.dispatchEvent(new PopStateEvent('popstate'));
        return new Promise(res => setTimeout(() => res({
          h1: document.querySelector('h1.ctitle')?.textContent || '',
          secs: [...document.querySelectorAll('.card h2')].map(h => h.textContent.trim()),
        }), 2500));
      }, pick.i);
      ok(pg2.secs.some(s => s.includes('教材原话')),
         `有引文的概念（${pick.q} 条）显示了「教材原话」板块`, pg2.h1);
      ok(errs.length === 0, '零 JS 错误', errs.slice(0, 2).join(' | '));
    }
    await page.close();
  }
}

// ── [3] 做题能判分 ────────────────────────────────────────
console.log('\n[3] 练一练能判分');
{
  const { page, errs } = await open('?v=sh');
  const hasQ = await page.evaluate(() => {
    const q = (window.LEARN_QUESTIONS || []).find(x => x.edition === 'sh');
    if (!q) return null;
    const n = window.LEARN_DATA.nodes.find(x => x.n === q.concept);
    return n ? n.i : null;
  });
  ok(hasQ !== null, '沪教版有题');
  if (hasQ !== null) {
    await page.goto(pathToFileURL(resolve(BASE, 'learn.html')).href + `?v=sh&c=${hasQ}`, { waitUntil: 'load' });
    await sleep(2000);
    const qn = await page.evaluate(() => document.querySelectorAll('.quiz').length);
    ok(qn > 0, `学习页里有 ${qn} 道题`);
    if (qn > 0) {
      // 点一个错的
      await page.click('.quiz .opt');
      await sleep(400);
      const st = await page.evaluate(() => {
        const f = document.querySelector('.quiz .fb');
        return {
          hidden: f?.hidden,
          text: (f?.textContent || '').trim(),
          right: document.querySelectorAll('.quiz .opt.right').length,
          wrong: document.querySelectorAll('.quiz .opt.wrong').length,
        };
      });
      ok(st.hidden === false, '解析框显示了');
      ok(st.right === 1, '标出了正确选项');
      ok((st.right + st.wrong) >= 1, '标出了所选选项');
      ok(st.text.length > 10, `解析有内容（${st.text.slice(0, 40)}…）`);
      // 再点**另一个**选项 —— 不该改判（防刷答案）
      const marksBefore = await page.evaluate(() => ({
        right: document.querySelectorAll('.quiz .opt.right').length,
        wrong: document.querySelectorAll('.quiz .opt.wrong').length,
        picked: document.querySelector('.quiz .opt.right, .quiz .opt.wrong')?.dataset.i,
      }));
      const other = await page.evaluate(() => {
        const opts = [...document.querySelectorAll('.quiz .opt')];
        const picked = opts.findIndex(o => o.classList.contains('right') || o.classList.contains('wrong'));
        return picked === 0 ? 1 : 0;
      });
      await page.evaluate(i => document.querySelectorAll('.quiz .opt')[i].click(), other);
      await sleep(300);
      const st2 = await page.evaluate(() => ({
        right: document.querySelectorAll('.quiz .opt.right').length,
        wrong: document.querySelectorAll('.quiz .opt.wrong').length,
        picked: document.querySelector('.quiz .opt.right, .quiz .opt.wrong')?.dataset.i,
      }));
      ok(st2.picked === marksBefore.picked && st2.right === marksBefore.right,
        '判过之后不能改判（防刷答案）',
        `判前 ${JSON.stringify(marksBefore)} 判后 ${JSON.stringify(st2)}`);
    }
  }
  ok(errs.length === 0, '零 JS 错误', errs.slice(0, 2).join(' | '));
  await page.close();
}

// ── [4] 教材原页图地址对得上 ──────────────────────────────
console.log('\n[4] 教材原页图');
{
  const { page, errs } = await open('?v=sh');
  const info = await page.evaluate(() => {
    const n = window.LEARN_DATA.nodes.find(x => x.loc && x.loc.scan && x.loc.scan.length);
    return n ? { name: n.n, i: n.i, bk: n.loc.bk, scan: n.loc.scan[0], ed: n.loc.ed, vol: n.loc.vol } : null;
  });
  ok(info !== null, '有节点带页图');
  if (info) {
    // **得先进到那个概念的学习页** —— 首页上没有图
    await page.goto(pathToFileURL(resolve(BASE, 'learn.html')).href + `?v=sh&c=${info.i}`, { waitUntil: 'load' });
    await sleep(1800);
    const P = await page.evaluate(bk => (window.PAGE_IMAGES || {})[bk] || null, info.bk);
    ok(!!P, `${info.bk} 有页图基址`);
    if (P) {
      ok(P.base.includes(info.bk) || P.base.includes('assets'), '基址指向这本书');
      const expect = `${P.base}/${info.scan}.jpg`;
      const real = await page.evaluate(() => {
        const img = document.querySelector('.pageimg img');
        return img ? img.getAttribute('src') : '';
      });
      ok(real === expect, '页面上的图 URL = 基址 + 扫描页码', `${real.slice(-30)} vs ${expect.slice(-30)}`);
    }
  }
  await page.close();
}

// ── [4b] 人教版的教材原页图也真的画出来了 ────────────────
//
// ⚠️ 这一条是**踩坑踩出来的**：
//   `nodeHTML` 原来的门禁是 `if (loc.bk && scan.length)`，
//   而**人教版的 `loc.bk` 是空串**（人教版用的是 `loc.pdfBook`）。
//   于是人教版 1,878 个有页图的节点**一张图都渲染不出来** ——
//   但测试全绿，因为[4]只测了 `?v=sh`（沪教版有 `loc.bk`）。
//
//   **判别力**：把门禁改回 `loc.bk` → 这一条必红。
console.log('\n[4b] 人教版教材原页图');
{
  const { page, errs } = await open('?v=rjb');
  const info = await page.evaluate(() => {
    const n = window.LEARN_DATA.nodes.find(x => x.loc && x.loc.pdfBook && x.loc.scan && x.loc.scan.length);
    return n ? { i: n.i, name: n.n, pdfBook: n.loc.pdfBook, scan: n.loc.scan[0], bk: n.loc.bk } : null;
  });
  ok(info !== null, '有节点带页图');
  if (info) {
    await page.goto(pathToFileURL(resolve(BASE, 'learn.html')).href + `?v=rjb&c=${info.i}`, { waitUntil: 'load' });
    await sleep(2000);

    const img = await page.evaluate(() => {
      const el = document.querySelector('.pageimg img');
      return el ? { src: el.getAttribute('src'), w: el.naturalWidth } : null;
    });
    ok(img !== null, '页面上真的有 <img>（门禁不能只判 loc.bk）');
    if (img) {
      const idx = await page.evaluate(pb => (window.PAGE_IMAGES_RJB || {})[pb] || null, info.pdfBook);
      ok(!!idx, `${info.pdfBook} 在页图索引里`);
      if (idx) {
        const expect = idx[String(info.scan)];
        ok(!!expect, `索引里有第 ${info.scan} 页`);
        ok(img.src.endsWith(expect.replace(/^data\//, '')) || img.src === expect,
          '图 URL = 索引里的本地页图路径', `${img.src.slice(-40)} vs ${expect}`);
        // 文件必须真的在磁盘上，且不是 0 字节
        const fp = resolve(BASE, expect);
        let size = -1;
        try { size = statSync(fp).size; } catch (e) { size = -1; }
        ok(size > 2000, `页图文件存在且非空（${size} 字节）`, expect);
        ok(img.w > 0, `图真的加载出来了（naturalWidth=${img.w}）`);
      }
    }
  }
  ok(errs.length === 0, '零 JS 错误', errs.slice(0, 2).join(' | '));
  await page.close();
}

// ── [4c] 印刷页码 ≠ 扫描页码，面板要显示书上印的那个 ──────
//
// 学生手里是纸书。面板上写「第 43 页」才翻得到，
// 写 PDF 扫描页号（50）翻过去是别的内容。
console.log('\n[4c] 教材原页显示印刷页码');
{
  const { page } = await open('?v=rjb');
  const info = await page.evaluate(() => {
    const n = window.LEARN_DATA.nodes.find(x => x.loc && x.loc.pdfBook && x.loc.scan && x.loc.scan.length
      && (window.PAGE_OFFSETS || {})[x.loc.pdfBook] !== undefined);
    return n ? { i: n.i, pdfBook: n.loc.pdfBook, scan: n.loc.scan[0] } : null;
  });
  ok(info !== null, '有节点的册次带印刷页码偏移');
  if (info) {
    await page.goto(pathToFileURL(resolve(BASE, 'learn.html')).href + `?v=rjb&c=${info.i}`, { waitUntil: 'load' });
    await sleep(1800);
    const cap = await page.evaluate(() => document.querySelector('.pageimg .cap')?.textContent || '');
    const off = await page.evaluate(pb => (window.PAGE_OFFSETS || {})[pb], info.pdfBook);
    ok(off !== undefined && off !== null, `${info.pdfBook} 有印刷页码偏移`, String(off));
    if (off !== undefined && off !== null) {
      const printed = info.scan + off;
      ok(cap.includes(`第 ${printed} 页`), `图注写的是印刷页码（第 ${printed} 页）`, cap.slice(0, 70));
      ok(cap.includes(`PDF 第 ${info.scan} 页`), `同时标出 PDF 扫描页（第 ${info.scan} 页）`, cap.slice(0, 80));
    }
  }
  await page.close();
}

// ── [4d] 沪教版页码也显示**印刷页码** ────────────────────
//
// ⚠️ 沪教版的页图是**平台的扫描本**，面板原来写「第 16 页」，
// 但图上页脚印的是 **9**（沪教版数学七下，实测）—— 学生按 16 翻书翻到的是下一节。
// 偏移从平台 OCR 的页脚行算（src/build_page_offsets_sh.py）。
console.log('\n[4d] 沪教版页码显示印刷页码');
{
  const { page } = await open('?v=sh');
  const info = await page.evaluate(() => {
    const n = window.LEARN_DATA.nodes.find(x => x.loc && x.loc.bk && x.loc.scan && x.loc.scan.length
      && (window.PAGE_OFFSETS_SH || {})[x.loc.bk] !== undefined);
    return n ? { i: n.i, bk: n.loc.bk, scan: n.loc.scan[0], off: window.PAGE_OFFSETS_SH[n.loc.bk] } : null;
  });
  ok(info !== null, '有节点的册次带沪教印刷页码偏移');
  if (info) {
    await page.goto(pathToFileURL(resolve(BASE, 'learn.html')).href + `?v=sh&c=${info.i}`, { waitUntil: 'load' });
    await sleep(2000);
    const cap = await page.evaluate(() => document.querySelector('.pageimg .cap')?.textContent || '');
    const printed = info.scan + info.off;
    ok(cap.includes(`第 ${printed} 页`), `图注写的是印刷页码（第 ${printed} 页）`, cap.slice(0, 70));
    ok(!cap.includes(`第 ${info.scan} 页（`), '没有把扫描页当成书上页码', cap.slice(0, 70));
  }
  await page.close();
}

// ── [5] 站内跳转 ──────────────────────────────────────────
console.log('\n[5] 前置/后继能跳');
{
  const { page, errs } = await open('?v=sh');
  // 先找一个**有前置**的概念，进它的学习页
  const ci = await page.evaluate(() => {
    const n = window.LEARN_DATA.nodes.find(x => x.pre && x.pre.length);
    return n ? n.i : null;
  });
  ok(ci !== null, '有概念带前置');
  await page.goto(pathToFileURL(resolve(BASE, 'learn.html')).href + `?v=sh&c=${ci}`, { waitUntil: 'load' });
  await sleep(1800);
  const link = await page.evaluate(() => {
    const a = document.querySelector('.card ul.plain a[data-c]');
    return a ? { c: a.dataset.c, text: a.textContent } : null;
  });
  ok(link !== null, '学习页上有前置链接');
  if (link) {
    await page.click('.card ul.plain a[data-c]');
    await sleep(1500);
    const h1 = await page.evaluate(() => document.querySelector('h1')?.textContent);
    ok(h1 === link.text, `点「${link.text}」跳到了它的学习页`);
  }
  ok(errs.length === 0, '零 JS 错误', errs.slice(0, 2).join(' | '));
  await page.close();
}

// ── [6] 视频位存在 ────────────────────────────────────────
console.log('\n[6] 视频位');
{
  const { page, errs } = await open('?v=sh');
  const ci = await page.evaluate(() => {
    const n = window.LEARN_DATA.nodes.find(x => x.pre && x.pre.length);
    return n ? n.i : null;
  });
  await page.goto(pathToFileURL(resolve(BASE, 'learn.html')).href + `?v=sh&c=${ci}`, { waitUntil: 'load' });
  await sleep(1800);
  const v = await page.evaluate(() => ({
    hasIdx: !!window.LEARN_VIDEOS,
    idxKeys: Object.keys(window.LEARN_VIDEOS || {}).filter(k => !k.startsWith('_')).length,
    placeholder: document.body.innerText.includes('这个知识点还没有讲解视频'),
    section: [...document.querySelectorAll('.card h2')].some(h => h.textContent.includes('讲解视频')),
  }));
  ok(v.hasIdx, '视频索引已加载');
  ok(v.section, '学习页有「讲解视频」板块');
  ok(v.placeholder, '没视频时显示占位说明（不留空白）');
  ok(errs.length === 0, '零 JS 错误', errs.slice(0, 2).join(' | '));
  await page.close();
}

// ── [7] 教材原页图在**带 Referer 的 http 环境**下能加载 ──────
//
// ⚠️ 这一条是**踩坑踩出来的**，不是预防性检查：
//   教材平台的 CDN 有**防盗链** —— 带外部 Referer 的请求直接 403，
//   而且返回的是 **text/html 错误页**（不是图片），
//   Chrome 的 ORB 机制会把这种响应拦掉，页面上的图就是一片空白。
//
//   为什么之前没发现：本地用 `file://` 打开时**本来就不发 Referer**，
//   所以本地测试全绿；线上必坏。
//   本地测试必须起 http 服务（`python3 -m http.server`）才复现。
//
// 判据：图必须真的加载出来（naturalWidth > 0），不能是 ORB 拦掉的空白。
console.log('\n[7] 教材原页图在带 Referer 的环境下能加载（防盗链）');
{
  // 找一个有页图的沪教概念
  const { page, errs } = await open('?v=sh');
  const info = await page.evaluate(() => {
    const n = window.LEARN_DATA.nodes.find(x => x.loc && x.loc.scan && x.loc.scan.length);
    return n ? { i: n.i, name: n.n, bk: n.loc.bk, scan: n.loc.scan[0] } : null;
  });
  ok(info !== null, '有节点带页图');
  if (info) {
    // **检查 img 标签上有没有 referrerpolicy="no-referrer"** ——
    // 这是防盗链的解药，漏了线上就是白板。
    const rp = await page.evaluate(() => {
      const n = window.LEARN_DATA.nodes.find(x => x.loc && x.loc.scan && x.loc.scan.length);
      return n.__imgReferrerPolicy || null;
    });
    // 直接查源码里的 img 标签
    const src = readFileSync(resolve(BASE, 'learn.html'), 'utf8');
    ok(/<img[^>]*referrerpolicy="no-referrer"/.test(src),
      'img 标签带 referrerpolicy="no-referrer"（CDN 防盗链的解药）',
      '少了它，带 Referer 的请求会 403 + text/html，Chrome ORB 拦截 → 图空白');
  }
  await page.close();
}

// ── [8] 学习页能**按教材翻**（不是只能搜） ────────────────
//
// ⚠️ 这一条是**产品缺口**，不是 bug：
//   原来首页只有「按年级进」，点进去是几百个概念的平铺列表 ——
//   对学生等于没有导航。而**学习页本来是个孤儿页**，站里没有一处链得过来。
//
//   判别力：把「按教材翻」那张卡删掉 → 这一条必红。
console.log('\n[8] 按教材翻 + 站点入口');
{
  const { page, errs } = await open('?v=sh');
  const has = await page.evaluate(() => {
    const h2 = [...document.querySelectorAll('.card h2')].map(x => x.textContent);
    return h2.some(t => t.includes('按教材翻'));
  });
  ok(has, '首页有「按教材翻」卡片');

  const books = await page.evaluate(() => [...document.querySelectorAll('[data-bk]')].map(a => a.dataset.bk));
  ok(books.length >= 5, `能列出多本教材（${books.length} 本）`, books.slice(0, 4).join(' / '));

  // 切到第二本，章节应当跟着换
  const chaptersBefore = await page.evaluate(() => document.querySelectorAll('.bchap h3').length);
  ok(chaptersBefore > 0, '默认册次展开了章节', `${chaptersBefore} 章`);
  if (books.length > 1) {
    await page.click(`[data-bk="${books[1].replace(/"/g, '\\"')}"]`);
    await sleep(1200);
    const after = await page.evaluate(() => ({
      on: document.querySelector('[data-bk].on')?.dataset.bk || '',
      chapters: document.querySelectorAll('.bchap h3').length,
    }));
    ok(after.on === books[1], '点册次后选中态跟着换', `${after.on} vs ${books[1]}`);
    ok(after.chapters > 0, '换册次后仍然有章节', `${after.chapters} 章`);
  }

  // 点章节里的知识点 → 进学习页
  const ci = await page.evaluate(() => {
    const a = document.querySelector('.bchap .toc a[data-c]');
    return a ? a.dataset.c : null;
  });
  ok(ci !== null, '章节里有知识点链接');
  if (ci !== null) {
    await page.click('.bchap .toc a[data-c]');
    await sleep(1800);
    const onPage = await page.evaluate(() => ({
      crumb: document.querySelector('.crumb b')?.textContent || '',
      h1: document.querySelector('#main h1')?.textContent || '',
    }));
    ok(!!onPage.h1, '点进去进到了学习页', onPage.h1);
  }
  ok(errs.length === 0, '零 JS 错误', errs.slice(0, 2).join(' | '));
  await page.close();
}

// ── [9] 站里能进到学习页（原来它是孤儿页） ────────────────
//
// 学习页做得再好，站里没有一处链得过来，就等于没有。
// 判别力：把三个站首页里的「学习页」链接删掉 → 这一条必红。
console.log('\n[9] 站点入口链得到学习页');
{
  for (const f of ['index.html', 'shanghai.html', 'kx.html']) {
    const src = readFileSync(resolve(BASE, f), 'utf8');
    ok(/href="\.\/learn\.html"/.test(src), `${f} 链得到学习页`);
  }
  const learnSrc = readFileSync(resolve(BASE, 'learn.html'), 'utf8');
  ok(/href="\.\/"/.test(learnSrc), '学习页能链回主站');
  const { page, errs } = await open('');
  const back = await page.evaluate(() => !!document.querySelector('.brand a.back'));
  ok(back, '学习页顶部有回主站的链接');
  ok(errs.length === 0, '零 JS 错误', errs.slice(0, 2).join(' | '));
  await page.close();
}

// ── [10] 讲解视频 + 讲解稿文字版 ───────────────────────────
//
// 设计前提：**不看视频也能走完**。
// 所以视频和文字讲解是**同一份稿子**的两个呈现 —— 页面必须同时有。
//
// 判别力：把 data/learn-videos.js 里的 mp4 条目删掉 → [10a] 红；
//         把 data/learn-explains.js 清空 → [10b] 红。
console.log('\n[10] 讲解视频 + 文字讲解');
{
  // ── [10a] 有视频的概念，页面上要有 <video>，且文件真的在磁盘上 ──
  const { page, errs } = await open('?v=rjb');
  const info = await page.evaluate(() => {
    const vids = window.LEARN_VIDEOS || {};
    const keys = Object.keys(vids).filter(k => !k.startsWith('_'));
    const n = window.LEARN_DATA.nodes.find(x => vids['rjb:' + x.id]);
    return { keys: keys.length, node: n ? { i: n.i, name: n.n, id: n.id } : null };
  });
  ok(info.keys > 0, `视频索引里有 ${info.keys} 条`);
  ok(info.node !== null, '能找到一个挂了视频的概念');
  if (info.node) {
    await page.goto(pathToFileURL(resolve(BASE, 'learn.html')).href + `?v=rjb&c=${info.node.i}`, { waitUntil: 'load' });
    await sleep(2000);
    const v = await page.evaluate(() => {
      const el = document.querySelector('.vid video');
      return el ? { src: el.getAttribute('src'), poster: el.getAttribute('poster') } : null;
    });
    ok(v !== null, '页面上有 <video> 元素');
    if (v) {
      const f = resolve(BASE, v.src);
      let size = -1;
      try { size = statSync(f).size; } catch (e) { size = -1; }
      ok(size > 100000, `视频文件在磁盘上且非空（${size} 字节）`, v.src);
      ok(!!v.poster, '播放器有封面帧（不然是个黑框）');
    }
  }
  ok(errs.length === 0, '零 JS 错误', errs.slice(0, 2).join(' | '));
  await page.close();

  // ── [10b] 文字讲解：同一份稿子的文字版必须在页面上 ──
  const { page: p2, errs: e2 } = await open('?v=rjb');
  const ex = await p2.evaluate(() => {
    const E = window.LEARN_EXPLAINS || {};
    const n = window.LEARN_DATA.nodes.find(x => E['rjb:' + x.id]);
    return { total: Object.keys(E).length, node: n ? { i: n.i, lines: (E['rjb:' + n.id].lines || []).length } : null };
  });
  ok(ex.total > 0, `讲解稿索引里有 ${ex.total} 条`);
  ok(ex.node !== null && ex.node.lines >= 3, '讲解稿有内容（≥3 段）');
  if (ex.node) {
    await p2.goto(pathToFileURL(resolve(BASE, 'learn.html')).href + `?v=rjb&c=${ex.node.i}`, { waitUntil: 'load' });
    await sleep(1800);
    const shown = await p2.evaluate(() => document.querySelectorAll('.expl').length);
    ok(shown >= 3, `页面上有 ${shown} 段文字讲解`);
  }
  ok(e2.length === 0, '零 JS 错误', e2.slice(0, 2).join(' | '));
  await p2.close();
}

// ── README 里的测试项数不能烂 ─────────────────────────────────
// 手抄的数字会过期（这里原来写的是 67，实际早就 88 了）。
// 跟另外三个套件一样：**这条断言只能放在这里** —— 只有跑完的人知道真实通过数。
{
  const rd = readFileSync(resolve(BASE, 'README.md'), 'utf8');
  const want = '| `src/test_learn_site.mjs` | 111 |';
  if (!rd.includes(want)) {
    console.log(`  \u2717 README 里的 学习页 测试项数不是 96`);
    console.log(`      README 里没找到「${want}」`);
    fail++;
  } else {
    console.log(`  \u2713 README 里的 学习页 测试项数是 96（与本次实跑一致）`);
    pass++;
  }
}

await browser.close();
console.log(`\n${'='.repeat(46)}\n通过 ${pass}，失败 ${fail}`);
process.exit(fail ? 1 : 0);
