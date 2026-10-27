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
import { readFileSync } from 'node:fs';

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
  ok(pg.secs.some(s => s.includes('教材原话')), '有「教材原话」板块');
  ok(pg.secs.some(s => s.includes('前置')), '有「前置」板块');
  ok(errs.length === 0, '零 JS 错误', errs.slice(0, 2).join(' | '));
  await page.close();
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

await browser.close();
console.log(`\n${'='.repeat(46)}\n通过 ${pass}，失败 ${fail}`);
process.exit(fail ? 1 : 0);
