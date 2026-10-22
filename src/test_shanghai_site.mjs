// 验证上海版站点能不能用
import { createRequire } from 'node:module';
import { resolve, dirname } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { readFileSync } from 'node:fs';

const require = createRequire(import.meta.url);
const puppeteer = require('puppeteer-core');
const BASE = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const PAGE = pathToFileURL(resolve(BASE, 'shanghai.html')).href;
const CHROME = process.env.CHROME || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const sleep = ms => new Promise(r => setTimeout(r, ms));

let pass = 0, fail = 0;
const ok = (c, l) => c ? (pass++, console.log(`  ✓ ${l}`)) : (fail++, console.log(`  ✗ ${l}`));

const browser = await puppeteer.launch({
  executablePath: CHROME, headless: true,
  args: ['--no-sandbox', '--disable-background-timer-throttling', '--force-device-scale-factor=1'],
});
const page = await browser.newPage();
await page.setViewport({ width: 1600, height: 1000 });
const errs = [];
page.on('pageerror', e => errs.push(String(e)));
page.on('console', m => { if (m.type() === 'error') errs.push(m.text()); });
await page.goto(PAGE, { waitUntil: 'load' });
await sleep(2200);

const KG = await page.evaluate(() => {
  const K = window.__kg;
  return {
    has: !!K,
    nodes: K?.D?.nodes?.length || 0,
    edges: K?.D?.edges?.length || 0,
    cns: K?.D?.cns?.length || 0,
    chs: K?.D?.chs?.length || 0,
    vision: Object.keys(K?.D?.vision || {}).length,
    hard: Object.keys(K?.D?.hard || {}).length,
    title: document.title,
  };
});
console.log('[1] 页面起来了');
ok(KG.has, 'window.__kg 存在');
ok(KG.nodes > 300, `节点 ${KG.nodes} 个`);
ok(KG.edges > 50, `边 ${KG.edges} 条`);
ok(KG.cns > 400, `单元链 ${KG.cns} 个`);
ok(KG.chs > 50, `章 ${KG.chs} 个`);
ok(KG.vision > 300, `带教材公式的节点 ${KG.vision} 个`);
ok(KG.hard > 200, `带教材难点的节点 ${KG.hard} 个`);
ok(/上海/.test(KG.title), `标题带「上海」（${KG.title}）`);

console.log('\n[2] 搜索 + 「卡在哪」');
await page.click('#q');
await page.type('#q', '二次函数', { delay: 20 });
await sleep(400);
await page.keyboard.press('Enter');
await sleep(1600);
const card = await page.evaluate(() => ({
  open: document.getElementById('card')?.classList.contains('on'),
  name: document.querySelector('#cZh')?.textContent || '',
}));
ok(card.open, '搜「二次函数」卡片打开了');
ok(card.name.includes('二次函数'), `卡片是「${card.name}」`);

await page.click('#cGap');
await sleep(900);
const gap = await page.evaluate(() => {
  const lis = [...document.querySelectorAll('#gapList li[data-id]')];
  return {
    open: !document.getElementById('gap').hidden,
    n: lis.length,
    withVb: lis.filter(li => li.querySelector('.vb')).length,
    withHard: lis.filter(li => li.querySelector('.vh2')).length,
    sample: lis[0]?.textContent.replace(/\s+/g, ' ').slice(0, 120) || '',
  };
});
ok(gap.open, '「卡在哪」面板打开了');
ok(gap.n > 0, `排出了 ${gap.n} 个候选`);
ok(gap.withVb > 0, `${gap.withVb} 个候选带上了教材公式/图`);
ok(gap.withHard > 0, `${gap.withHard} 个候选带上了教材标的难点`);
console.log(`      例：${gap.sample}`);

console.log('\n[3] 零 JS 错误');
ok(errs.length === 0, `零 JS 错误（${errs.length} 个）`);
if (errs.length) console.log('     ', errs.slice(0, 3));

// ── 教材位置：沪教版必须有「哪本书哪一节」 ──────────────────────
// 这一条判别力很强：
//   · 匹配没做 → 教材公式/位置整块空
//   · cns 契约写错（第三位塞了版别而不是学科下标）→ 「下一单元」跳到别处
console.log('\n[4] 教材位置与「上一/下一单元」');
await page.click('#gapClose');
await sleep(300);
await page.evaluate(() => { document.getElementById('q').value = ''; });
await page.click('#q');
await page.type('#q', '整式', { delay: 20 });
await sleep(400);
await page.keyboard.press('Enter');
await sleep(1500);
const pos = await page.evaluate(() => ({
  eyebrow: document.getElementById('cEyebrow')?.textContent || '',
  desc: document.getElementById('cDesc')?.textContent || '',
  ord: document.querySelector('#cChain [data-b="ord"]')?.textContent || '',
  ordRows: [...document.querySelectorAll('#cChain .ord2 .dep')].map(b => b.textContent.replace(/\s+/g, ' ').trim()),
  hasVb: !!document.querySelector('#cChain .vb, #cChain .vh2'),
}));
ok(pos.eyebrow.includes('沪教版'), `卡片眉标写的是沪教版（${pos.eyebrow}）`);
ok(pos.eyebrow.includes('七上'), `册次写的是「七上」（${pos.eyebrow}）`);
ok(/教材位置：第\s*\d+\s*章/.test(pos.desc), `描述里写得出教材位置（${pos.desc.slice(0, 46)}）`);
ok(pos.ord.includes('教材顺序'), `卡片上有「教材顺序」这一栏（${pos.ord}）`);
ok(pos.ordRows.length >= 1, `上一/下一单元可点（${pos.ordRows.join(' | ').slice(0, 60)}）`);

// 不可点的单元行（<div class="dep flat">，里面没有可点的概念）点下去
// **不能报错** —— 它没有 data-jump，`+b.dataset.jump` 是 NaN，
// `jump(NaN)` 的两道闸都拦不住，NODES[NaN] 是 undefined，n.x 直接抛。
// 这是主站也有的 bug，上海版第一次点「上一单元」才撞出来。
const flat = await page.evaluate(() => {
  const d = document.querySelector('#cChain .dep.flat');
  if (!d) return false;
  d.click();
  return true;
});
await sleep(600);
if (flat) {
  ok(errs.length === 0, `点不可点的单元行不报错（${errs.length} 个错误）`);
  if (errs.length) console.log('     ', errs.slice(0, 2));
} else {
  console.log('      （这一册没有空单元行，跳过）');
}

// 点「上一/下一单元」要真的跳到**另一个**知识点。
// 比名字不够 —— 不同册次的同名概念会撞（人教和沪教都有「整式」），
// 所以比的是节点下标。
const beforeId = await page.evaluate(() => window.__kg.cardId());
if (pos.ordRows.length) {
  await page.evaluate(() => document.querySelector('#cChain .ord2 button.dep')?.click());
  await sleep(1200);
  const after = await page.evaluate(() => ({
    id: window.__kg.cardId(),
    name: document.getElementById('cZh')?.textContent || '',
  }));
  ok(after.id !== beforeId, `点「上一/下一单元」跳到了另一个节点（${beforeId} → ${after.id} ${after.name}）`);
} else {
  ok(false, '上一/下一单元没渲染出来，跳转没法测');
}

console.log('\n[5] 五四学制：沪教版六年级已经是初中');
const stages = await page.evaluate(() => {
  const K = window.__kg;
  const out = { six: null, seven: null, hk7: null, pre: 0 };
  for (const n of K.NODES) {
    if (n.a1 === 6 && n.dz.startsWith('沪教版') && !out.six) out.six = { dz: n.dz, stg: n.stg, name: n.zh };
    if (n.a1 === 7 && n.dz.startsWith('沪教版') && !out.seven) out.seven = { dz: n.dz, stg: n.stg, name: n.zh };
    if (n.dz.startsWith('沪科版') && !out.hk7) out.hk7 = { dz: n.dz, stg: n.stg, name: n.zh };
    if (n.dz.startsWith('人教版')) out.pre++;
  }
  return out;
});
ok(stages.six !== null, `找到了沪教版六年级的点（${stages.six?.name}）`);
ok(stages.six?.stg === 1, `沪教版六年级算「初中」而不是「小学」（${stages.six?.name}）`);
ok(stages.seven?.stg === 1, `沪教版七年级是「初中」（${stages.seven?.name}）`);
ok(stages.hk7?.stg === 1, `沪科版七年级是「初中」（${stages.hk7?.name}）`);
ok(stages.pre > 0, `人教版前置补充节点 ${stages.pre} 个`);

// ── 教材公式挂的是「下标」不是「id」 ───────────────────────────
// 之前挂成 id，页面上一个公式都显示不出来（静默失败）。
const vb = await page.evaluate(() => {
  const K = window.__kg;
  const j = K.NODES.findIndex(n => n.zh === '二次函数');
  return { has: !!(K.vision[j]), keys: Object.keys(K.vision).length };
});
ok(vb.has, '「二次函数」的教材公式挂在正确的下标上');
ok(vb.keys > 300, `payload 里有 ${vb.keys} 个带教材数据的节点`);

// ── 其他学科 ────────────────────────────────────────────────
// 上海的孩子不止学数学。物理/化学/生物/科学都要在，
// 而且**教材顺序链不能跨版别** —— 沪教版七上和沪科版七上是两套教材，
// 「上一单元」从一套跳到另一套就是错的。
console.log('\n[6] 其他学科与版别');
const subj = await page.evaluate(() => {
  const K = window.__kg;
  const byS = {};
  for (const n of K.NODES) {
    const s = K.SUBJ[n.s]?.zh || '?';
    byS[s] = (byS[s] || 0) + 1;
  }
  // 每个教材顺序链的组内是不是只有一套版别
  const CNS = K.D.cns;
  const groups = {};
  CNS.forEach((c, i) => { (groups[c[2]] = groups[c[2]] || []).push(c[1]); });
  // 判据不能靠「义务教育」四个字 —— 短的册次标签（沪教版·七上）
  // 里没有那四个字，会把义务教育误判成高中。
  const mixed = Object.entries(groups).filter(([, titles]) =>
    new Set(titles.map(t => t.includes('普通高中') ? '高中' : '义务')).size > 1).length;
  return { byS, groups: Object.keys(groups).length, mixed };
});
const names = Object.keys(subj.byS);
ok(names.length >= 4, `画布上有 ${names.length} 个学科/版别组合（${names.join(' · ')}）`);
ok(names.some(n => n.includes('物理')), '物理在');
ok(names.some(n => n.includes('化学')), '化学在');
ok(names.some(n => n.includes('生物')), '生物在');
ok(subj.mixed === 0, `教材顺序链没有跨学段串（${subj.mixed} 组串了）`);

// 物理的教材位置要能读出来
await page.evaluate(() => { document.getElementById('q').value = ''; });
await page.click('#q');
await page.type('#q', '浮力', { delay: 20 });
await sleep(500);
await page.keyboard.press('Enter');
await sleep(1600);
const phys = await page.evaluate(() => ({
  open: document.getElementById('card')?.classList.contains('on'),
  eyebrow: document.getElementById('cEyebrow')?.textContent || '',
  desc: document.getElementById('cDesc')?.textContent || '',
}));
ok(phys.open, '搜「浮力」卡片打开了');
ok(/沪科版|沪教版/.test(phys.eyebrow), `「浮力」标的是上海教材（${phys.eyebrow}）`);
ok(/教材位置|\d/.test(phys.desc), `「浮力」写得出教材位置（${phys.desc.slice(0, 40)}）`);

// ── 学习路径 ────────────────────────────────────────────────
console.log('\n[7] 学习路径：沪教版版的先修顺序');
await page.evaluate(() => { document.getElementById('q').value = ''; });
await page.click('#q');
await page.type('#q', '浮力', { delay: 20 });
await sleep(500);
await page.keyboard.press('Enter');
await sleep(1600);
await page.click('#cPath');
await sleep(1000);
const path = await page.evaluate(() => {
  const lis = [...document.querySelectorAll('#pathList li[data-id]')];
  const depths = lis.map(li => {
    const m = li.textContent.match(/离目标\s*(\d+)\s*层/);
    return m ? +m[1] : -1;
  });
  return {
    open: !document.getElementById('path').hidden,
    n: lis.length,
    nondecreasing: depths.every((d, i) => i === 0 || depths[i - 1] >= d),
    hasPos: lis.filter(li => /沪教版|沪科版/.test(li.textContent)).length,
    sample: lis[0]?.textContent.replace(/\s+/g, ' ').trim().slice(0, 100) || '',
  };
});
ok(path.open, '学习路径面板打开了');
ok(path.n > 2, `排出了 ${path.n} 个前置`);
ok(path.nondecreasing, '顺序是从最基础开始');
ok(path.hasPos > 0, `${path.hasPos} 个前置标出了上海教材的位置`);
console.log(`      例：${path.sample}`);

// ── README 里的测试项数不能烂 ────────────────────────────────
{
  const rd = readFileSync(resolve(BASE, 'README.md'), 'utf8');
  const want = '| `src/test_shanghai_site.mjs` | 42 |';
  ok(rd.includes(want), `README 里的 上海版 测试项数是 42（${rd.includes(want) ? '一致' : '不一致'}）`);
}

await page.screenshot({ path: resolve(BASE, 'data/pdf-cache/work/shanghai-site.png') });
await browser.close();
console.log(`\n通过 ${pass}，失败 ${fail}`);
process.exit(fail ? 1 : 0);
