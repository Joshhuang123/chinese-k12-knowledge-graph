import { createRequire } from 'node:module';
const require = createRequire(import.meta.url);
const puppeteer = require('puppeteer-core');
const sleep = ms => new Promise(r => setTimeout(r, ms));
const LOCAL = 'file://' + process.cwd() + '/learn.html';

const b = await puppeteer.launch({
  executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
  headless: true,
  args: ['--no-sandbox', '--no-proxy-server', '--proxy-bypass-list=*'],
});
const p = await b.newPage();
await p.setViewport({ width: 1280, height: 1400 });
const errs = [];
p.on('pageerror', e => errs.push(String(e)));

await p.goto(LOCAL + '?v=rjb', { waitUntil: 'load' });
await sleep(3500);
const info = await p.evaluate(() => {
  const n = window.LEARN_DATA.nodes.find(x => x.n === '浮力');
  return n ? { i: n.i } : null;
});
await p.goto(LOCAL + `?v=rjb&c=${info.i}`, { waitUntil: 'load' });
await sleep(3000);

const r = await p.evaluate(() => {
  const vid = document.querySelector('.vid video');
  const cards = [...document.querySelectorAll('.card h2')].map(h => h.textContent.trim());
  const expl = [...document.querySelectorAll('.expl')].map(e => e.textContent);
  return {
    cards,
    video: vid ? { src: vid.getAttribute('src'), w: vid.naturalWidth, dur: vid.duration } : null,
    explCount: expl.length,
    explFirst: expl[0] || '',
  };
});
console.log('板块:', JSON.stringify(r.cards, null, 0));
console.log('视频:', JSON.stringify(r.video));
console.log('讲解段数:', r.explCount);
console.log('讲解第一段:', r.explFirst);
console.log(errs.length ? 'JS 错误: ' + errs.slice(0, 2).join(' | ') : '零 JS 错误 ✓');
await p.screenshot({ path: '/tmp/learn-with-video.png', fullPage: false });
await b.close();
