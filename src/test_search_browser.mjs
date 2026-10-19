/* 搜索功能的端到端测试：直接开真页面，用真 Chrome。
 *
 * 为什么不用 node 拼装：n.x/n.y/n.z 是页面运行时算出来的，
 * payload 里根本没有。脚手架里重跑一遍布局 = 又维护了一份运行时，
 * 模板一改就测一个不存在的东西。所以这里只测**可观测的效果**：
 * 结果列表、卡片、焦点节点最终出现在画面正中。
 *
 * 断言的依据：draw() 把焦点节点画成「白心 + #ff3d7f 洋红环」，
 * 而 flyTo 解出的相机角度保证它的投影落在 (W/2, H/2)。
 *
 * 跑法（puppeteer-core 刻意不进 package.json —— 整个项目没有 npm 依赖，
 * 不想为一个测试把 Node 工具链变成跑图谱的前置条件）：
 *
 *   npm install puppeteer-core@23 --prefix /tmp/kg-test
 *   NODE_PATH=/tmp/kg-test/node_modules node src/test_search_browser.mjs
 *
 * createRequire 会从本文件所在目录逐级向上找 node_modules，所以如果
 * ~/node_modules 里已经有一份，直接跑即可，不用设 NODE_PATH。
 * 实在找不到，上面那行会打印这段指引并以 exit 2 退出。
 *
 * Chrome 路径可用 CHROME 环境变量覆盖（默认是 macOS 的安装位置）。
 */
import { createRequire } from 'node:module';
import { readFileSync } from 'node:fs';
import { resolve, dirname } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const require = createRequire(import.meta.url);
let puppeteer;
try {
  puppeteer = require('puppeteer-core');
} catch {
  console.error(
    '找不到 puppeteer-core。请先装：\n' +
    '  npm install puppeteer-core@23 --prefix /tmp/kg-test\n' +
    '  NODE_PATH=/tmp/kg-test/node_modules node ' + fileURLToPath(import.meta.url)
  );
  process.exit(2);
}

const BASE = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const PAGE = pathToFileURL(resolve(BASE, 'viz/知识图谱3D.html')).href;
const CHROME = process.env.CHROME || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';

const ACC = [0xff, 0x3d, 0x7f];   // 焦点环的颜色

let pass = 0, fail = 0;
function ok(c, label, extra = '') {
  if (c) { pass++; console.log(`  ✓ ${label}`); }
  else { fail++; console.log(`  ✗ ${label}${extra ? '\n      ' + extra : ''}`); }
}
const sleep = ms => new Promise(r => setTimeout(r, ms));

const browser = await puppeteer.launch({
  executablePath: CHROME,
  headless: true,
  args: ['--allow-file-access-from-files', '--no-sandbox',
         '--disable-background-timer-throttling', '--disable-renderer-backgrounding',
         '--force-device-scale-factor=1'],
});
const page = await browser.newPage();
await page.setViewport({ width: 1600, height: 1000, deviceScaleFactor: 1 });

const errors = [];
page.on('pageerror', e => errors.push(String(e)));
page.on('console', m => { if (m.type() === 'error') errors.push('console: ' + m.text()); });

await page.goto(PAGE, { waitUntil: 'load' });
await sleep(1200);

// 采样画面正中一小块：数白心像素和洋红环像素
const sampleCenter = () => page.evaluate((acc) => {
  const cv = document.getElementById('c');
  const g = cv.getContext('2d');
  const cx = Math.round(cv.width / 2), cy = Math.round(cv.height / 2);
  const R = 26;
  const img = g.getImageData(cx - R, cy - R, R * 2, R * 2).data;
  let white = 0, pink = 0, lit = 0;
  for (let i = 0; i < img.length; i += 4) {
    const [r, gg, b, a] = [img[i], img[i + 1], img[i + 2], img[i + 3]];
    if (a < 20) continue;
    lit++;
    if (r > 200 && gg > 200 && b > 200) white++;
    const near = (x, y) => Math.abs(x - y) <= 70;
    if (near(r, acc[0]) && near(gg, acc[1]) && near(b, acc[2])) pink++;
  }
  const n = (R * 2 * R * 2);
  return { white, pink, lit, total: n };
}, ACC);

console.log(`页面已开：${PAGE}\n`);

console.log('[1] 页面无脚本错误');
ok(errors.length === 0, '没有 JS 报错 / 控制台错误', errors.slice(0, 3).join('\n      '));

console.log('\n[1b] 页面自洽：标题里的数字必须是真实规模');
{
  // 这条是被真抓出来的：模板 <title> 原来写死「1,590 个知识点」——
  // 那是 Marble 的规模，我们是 7,938。已经上线了才发现。
  // 根因是硬编码数字会漂移，所以在这加一道守卫。
  //
  // **判据后来收紧了。** 原来只查「标题里有画布点数」，
  // 但画布上多出来的 68 个是我们补的 L0 能力节点和 derived 概念 ——
  // 「中国的孩子在学什么 · 8,006 个知识点」把它们算成了教材知识点。
  // 现在标题用**教材知识点数**（上游 Concept/Skill/Experiment），
  // 而这个数**由测试自己从 graph.json 数出来**，不看页面给的数 ——
  // 页面自己报一个数再拿来跟它自己比，等于没测。
  const meta = await page.evaluate(() => {
    const D = JSON.parse(document.getElementById('data').textContent);
    return { N: D.nodes.length, total: D.total, title: document.title,
             icon: document.querySelector('link[rel="icon"]')?.href || '' };
  });
  const g = JSON.parse(readFileSync(resolve(BASE, 'data/normalized/graph.json'), 'utf8'));
  const upstream = g.nodes.filter(n =>
    ['Concept', 'Skill', 'Experiment'].includes(n.label)).length;
  ok(meta.total === upstream,
     `payload.total（${meta.total}）等于 graph.json 里的上游知识点数（${upstream}）`,
     `total=${meta.total} upstream=${upstream}`);
  const want = upstream.toLocaleString('en-US');
  ok(meta.title.includes(want),
     `标题含教材知识点数 ${want}（不是画布点数 ${meta.N.toLocaleString('en-US')}）`,
     meta.title);
  ok(!/1,590|1,127|5,255/.test(meta.title), '标题里没有别的项目的遗留数字', meta.title);
  ok(meta.icon.startsWith('data:image/svg+xml'), 'favicon 内联（单文件自包含，不会 404）');
}

console.log('\n[1c] 无外部资源请求（file:// 之外的引用一律不许有）');
{
  const ext = [];
  page.on('request', r => { const u = r.url(); if (!u.startsWith('file:') && !u.startsWith('data:')) ext.push(u); });
  await page.reload({ waitUntil: 'load' });
  await sleep(1500);
  ok(ext.length === 0, `没有引用任何外部文件${ext.length ? '：' + ext.slice(0, 3).join(', ') : ''}`,
     ext.slice(0, 3).join('\n      '));
}

console.log('\n[1d] 标题字形必须是无衬线（不能悄悄变成宋体）');
{
  // 量字宽没用——CJK 全角，width 一律相同。改用像素指纹：
  // 同一句话分别按 sans-serif 和 serif 渲染，比对灰度指纹。
  const res = await page.evaluate(() => {
    const T = '中国的孩子在学什么。';
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
    const h1 = getComputedStyle(document.querySelector('#head h1')).fontFamily;
    return { sans: fp('sans-serif'), serif: fp('serif'), actual: fp(h1), h1 };
  });
  ok(res.sans !== res.serif, '基准成立：sans-serif 与 serif 在本页确实渲染成不同字形');
  ok(res.actual === res.sans, 'h1 渲染结果与 sans-serif 一致（不是宋体）', res.h1);
}

console.log('\n[2] 搜索框存在且可聚焦');
await page.click('#q');
ok(await page.evaluate(() => document.activeElement.id === 'q'), '点击后焦点在输入框');

console.log('\n[3] 输入中文名出结果');
await page.type('#q', '光合作用', { delay: 25 });
await sleep(250);
let res = await page.evaluate(() => ({
  on: document.getElementById('res').classList.contains('on'),
  items: [...document.querySelectorAll('#res .r')].map(e => ({
    name: e.querySelector('span:nth-child(2)').textContent,
    book: e.querySelector('.bk').textContent,
  })),
  input: document.getElementById('q').value,
}));
ok(res.input === '光合作用', `输入框内容正确（${res.input}）`);
ok(res.on, '结果框展开');
ok(res.items.length > 0, `有 ${res.items.length} 条结果`);
ok(res.items.some(x => x.name.includes('光合')), '结果里有「光合作用」', JSON.stringify(res.items));
ok(res.items.every(x => x.book && x.book.includes('·')), '每条都带册次标签', JSON.stringify(res.items.map(x => x.book)));

console.log('\n[4] Enter 跳转：卡片弹出 + 焦点节点落到画面正中');
await page.keyboard.press('Enter');
await sleep(1800);   // 相机 lerp 0.09/帧，给足收敛时间

const card = await page.evaluate(() => {
  const c = document.getElementById('card');
  return { on: c.classList.contains('on'), text: (c.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 120) };
});
ok(card.on, '详情卡弹出');
ok(card.text.includes('光合'), '卡片内容是光合作用', card.text);
ok(await page.evaluate(() => !document.getElementById('res').classList.contains('on')), '跳转后结果框收起');

const before = await sampleCenter();
ok(before.white > 0, `画面正中 ${before.white} 个白心像素 —— 焦点节点确实被画在最中间`, JSON.stringify(before));
ok(before.pink > 30, `焦点环 ${before.pink} 个洋红像素（白心周围）`, JSON.stringify(before));

console.log('\n[5] 前置链被高亮（activeSet 非空 → 其余节点压暗）');
const dim = await page.evaluate(() => {
  const cv = document.getElementById('c');
  const g = cv.getContext('2d');
  const d = g.getImageData(0, 0, cv.width, cv.height).data;
  let bright = 0;
  for (let i = 0; i < d.length; i += 4) {
    if (d[i + 3] > 60 && d[i] > 150 && d[i + 1] > 60 && d[i + 1] < 200 && d[i + 2] < 150) bright++;
  }
  return bright;
});
ok(dim > 200, `画面里有 ${dim} 个高亮（洋红=前置链 / 学科色）像素，说明 activeSet 不是空的`);

console.log('\n[6] 键盘：↑↓ 选择 / / 聚焦 / Esc 关闭');
await page.keyboard.press('Escape');
await page.click('#q');
await page.evaluate(() => { document.getElementById('q').value = ''; document.getElementById('q').dispatchEvent(new Event('input')); });
await page.type('#q', '方程', { delay: 20 });
await sleep(200);
const nRes = await page.evaluate(() => document.querySelectorAll('#res .r').length);
ok(nRes > 1, `「方程」有 ${nRes} 条结果，可以用方向键选`);
const sel0 = await page.evaluate(() => [...document.querySelectorAll('#res .r')].findIndex(e => e.classList.contains('sel')));
await page.keyboard.press('ArrowDown');
const sel1 = await page.evaluate(() => [...document.querySelectorAll('#res .r')].findIndex(e => e.classList.contains('sel')));
ok(sel0 === 0 && sel1 === 1, `↓ 把选中项从第 ${sel0} 条移到第 ${sel1} 条`);
await page.keyboard.press('Escape');
ok(await page.evaluate(() => !document.getElementById('res').classList.contains('on')), 'Esc 收起结果框');
await page.evaluate(() => document.getElementById('q').blur());
await page.keyboard.press('/');
ok(await page.evaluate(() => document.activeElement.id === 'q'), '按 / 聚焦搜索框');

console.log('\n[7] 册次搜索');
await page.evaluate(() => { document.getElementById('q').value = ''; });
await page.type('#q', '五上', { delay: 20 });
await sleep(200);
const bk = await page.evaluate(() => [...document.querySelectorAll('#res .r .bk')].map(e => e.textContent));
ok(bk.length > 0 && bk.every(x => x.startsWith('五上')), `册次搜索命中且全是五上（${bk.length} 条）`, JSON.stringify(bk));

console.log('\n[8] 无匹配');
await page.evaluate(() => { document.getElementById('q').value = ''; });
await page.type('#q', 'qqqq不存在', { delay: 20 });
await sleep(200);
ok(await page.evaluate(() => document.getElementById('res').textContent.includes('没有匹配')), '给出「没有匹配」提示');

console.log('\n[9] 跨学段抽检：锥形从底到顶都要能飞准');
{
  // 单验一个节点不算数。锥形底部（小学，半径小、y 很负）和顶部（高中，半径大、y 很正）
  // 是解算的两端，flyTo 算出的 ph 会分别逼近 -1.35 和 +1.35 的钳制边界，容易翻车。
  const probes = ['数数', '三角形', '浮力', '光合作用', '函数', '牛顿第二定律', '电解质'];
  let locked = 0, details = [];
  for (const kw of probes) {
    await page.evaluate(() => { document.getElementById('q').value = ''; document.getElementById('q').dispatchEvent(new Event('input')); });
    await page.type('#q', kw, { delay: 12 });
    await sleep(180);
    const picked = await page.evaluate(() => {
      const it = [...document.querySelectorAll('#res .r')]
        .find(e => e.querySelector('span:nth-child(2)').textContent.trim() === document.getElementById('q').value.trim());
      return !!it;
    });
    if (!picked) { details.push(`${kw}: 搜不到同名节点，跳过`); continue; }
    await page.keyboard.press('Enter');
    await sleep(1500);
    const s = await sampleCenter();
    const hit = s.white > 0;
    if (hit) locked++;
    details.push(`${kw}: 白心 ${s.white} 环 ${s.pink}`);
  }
  ok(locked >= 5, `${locked}/${probes.length} 个节点成功飞正`, details.join('\n      '));
}

console.log('\n[10] 窄屏必须保留搜索，且不能被底部抽屉压住署名');
{
  // 这条断言原来写的是「≤900px 时 #find 隐藏」——它锁定的正是一个错误行为。
  // 当时给的理由是「触屏没键盘」，那句话是错的：点输入框会拉起软键盘。
  // 实测 iPhone 13 上标题区只占 242×149，下面空着 450px，空间从来不是问题；
  // 而 7,938 个点，窄屏用户除了搜索没有任何办法找到知识点。
  await page.setViewport({ width: 390, height: 844, deviceScaleFactor: 1, isMobile: true, hasTouch: true });
  await page.reload({ waitUntil: 'load' });
  await sleep(1200);

  ok(await page.evaluate(() => getComputedStyle(document.getElementById('find')).display !== 'none'),
     '390px 宽时搜索框仍然可见');
  const fs = await page.evaluate(() => parseFloat(getComputedStyle(document.getElementById('q')).fontSize));
  ok(fs >= 16, `输入框字号 ${fs}px ≥ 16px（iOS 更小会强制放大整页）`);

  await page.tap('#q');
  await page.type('#q', '元素周期律', { delay: 15 });
  await sleep(350);
  const n = await page.evaluate(() => document.querySelectorAll('#res .r').length);
  ok(n > 0, `触摸输入出结果 ${n} 条`);
  const rh = await page.evaluate(() => Math.round(Math.min(...[...document.querySelectorAll('#res .r')].map(e => e.getBoundingClientRect().height))));
  ok(rh >= 44, `结果条目高度 ${rh}px ≥ 44px（Apple HIG 的触控下限）`);

  await (await page.$('#res .r')).tap();
  await sleep(1600);
  const g = await page.evaluate(() => {
    const c = document.getElementById('card').getBoundingClientRect();
    const a = document.getElementById('attr').getBoundingClientRect();
    // 署名现在跟着标题走，判据是它不能落在卡片区域里
    const overlaps = !(a.bottom <= c.top || a.top >= c.bottom);
    return { cTop: Math.round(c.top), cBot: Math.round(c.bottom), aTop: Math.round(a.top),
             aBot: Math.round(a.bottom), overlaps, vh: innerHeight };
  });
  ok(g.cBot <= g.vh + 1, `详情卡完整在视口内（${g.cTop}~${g.cBot} / ${g.vh}）`);
  ok(!g.overlaps, `署名（${g.aTop}~${g.aBot}）没被卡片（${g.cTop}~${g.cBot}）盖住`);
  await page.setViewport({ width: 1600, height: 1000, deviceScaleFactor: 1 });
  await sleep(300);
}

console.log('\n[11] 搜索过程中没有新的脚本报错');
ok(errors.length === 0, '全程零 JS 错误', errors.slice(0, 5).join('\n      '));

await browser.close();
console.log(`\n${'='.repeat(52)}\n通过 ${pass}，失败 ${fail}`);
process.exit(fail ? 1 : 0);
