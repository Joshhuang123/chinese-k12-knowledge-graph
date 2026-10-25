/* 数据一览页的端到端测试：真 Chrome 开真页面。 */
import { createRequire } from 'node:module';
import { resolve, dirname } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const require = createRequire(import.meta.url);
let puppeteer;
try { puppeteer = require('puppeteer-core'); }
catch { console.error('需要 puppeteer-core'); process.exit(2); }

const BASE = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const PAGE = pathToFileURL(resolve(BASE, 'data.html')).href;
const CHROME = process.env.CHROME || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';

let pass = 0, fail = 0;
const ok = (c, l, e = '') => c ? (pass++, console.log(`  ✓ ${l}`)) : (fail++, console.log(`  ✗ ${l}${e ? '\n      ' + e : ''}`));

const browser = await puppeteer.launch({
  executablePath: CHROME, headless: true,
  args: ['--no-sandbox', '--disable-background-timer-throttling'],
});
const page = await browser.newPage();
await page.setViewport({ width: 1280, height: 900 });
const errs = [];
page.on('pageerror', e => errs.push(String(e)));
page.on('console', m => { if (m.type() === 'error') errs.push(m.text()); });
await page.goto(PAGE, { waitUntil: 'load' });
await new Promise(r => setTimeout(r, 400));

console.log('【1】页面起来了');
ok(errs.length === 0, `运行期无报错（${JSON.stringify(errs)}）`);
const title = await page.title();
ok(title.includes('数据一览'), `标题对（${title}）`);

console.log('\n【2】数据集都在');
const n = await page.$$eval('.ds', els => els.length);
ok(n >= 30, `渲染了 ${n} 个数据集卡片（应 ≥30）`);
const stats = await page.$$eval('.stat b', els => els.map(e => e.textContent));
ok(stats.length === 4, `概览四个数字（${stats.join(' / ')}）`);

console.log('\n【3】搜索能过滤');
await page.type('#q', '先修边');
await new Promise(r => setTimeout(r, 300));
const shown = await page.$$eval('.ds', els => els.filter(e => e.style.display !== 'none').length);
ok(shown > 0 && shown < n, `搜「先修边」筛出 ${shown} / ${n} 个`);
const cnt = await page.$eval('#cnt', e => e.textContent);
ok(cnt.includes('先修边'), `计数行更新了（${cnt}）`);

console.log('\n【4】搜不到的不该显示');
await page.click('#q', { clickCount: 3 });
await page.type('#q', 'zzzz不存在的东西');
await new Promise(r => setTimeout(r, 300));
const shown0 = await page.$$eval('.ds', els => els.filter(e => e.style.display !== 'none').length);
ok(shown0 === 0, `搜不存在的词 → 显示 0 个（实际 ${shown0}）`);

console.log('\n【5】展开样本');
await page.click('#q', { clickCount: 3 });
await page.type('#q', 'learn-cards');
await new Promise(r => setTimeout(r, 300));
await page.click('.ds:not([style*="none"]) summary');
await new Promise(r => setTimeout(r, 200));
const openN = await page.$$eval('details[open]', els => els.length);
ok(openN > 0, `能展开看字段和样本（${openN} 个展开）`);
const hasSample = await page.$$eval('.sample', els => els.length);
ok(hasSample > 0, `样本行渲染出来了（${hasSample} 个）`);

console.log('\n【6】导航链接');
const links = await page.$$eval('.nav a', els => els.map(e => e.getAttribute('href')));
ok(links.includes('./') && links.includes('./quality.html') && links.includes('./shanghai.html'),
   `导航齐全（${links.join(' ')}）`);

await page.screenshot({ path: '/tmp/data_browser.png', fullPage: false });
console.log('\n截图 → /tmp/data_browser.png');
await browser.close();
console.log(`\n通过 ${pass}，失败 ${fail}`);
process.exit(fail ? 1 : 0);
