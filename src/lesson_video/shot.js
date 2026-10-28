#!/usr/bin/env node
// shot.js —— **每句一帧**截屏（不是逐帧）
//
//   node shot.js <timeline.json> <slide.final.html> <out_dir>
//
// 为什么不用逐帧
// --------------
// 讲义视频是**静态幻灯片**：一场里画面不动，只有字幕在换。
// 逐帧渲染 60 秒 × 30fps = 1800 张 PNG，一个视频要 3–5 分钟 ——
// 批量做几十条根本跑不动。
//
// 改成「每句截一帧」：
//   截图数 = 句数（约 10–14 张）
//   字幕**烤进画面**，所以每句必须单独出一张
//   拼接时按真值时长给每张图对应时长（mux-shots.sh）
//
// 判据：每张图必须真的画完了才截 ——
// 等 document.body.dataset.t 等于目标值。漏了会抓到上一句的画面，
// 字幕和配音对不上，而且**所有检查都显示正常**。

const fs = require('fs');
const path = require('path');
const puppeteer = require('puppeteer-core');

const CHROME = process.env.CHROME ||
  '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const here = __dirname;

async function main() {
  const [tlPath, htmlPath, outDir] = process.argv.slice(2);
  if (!tlPath || !htmlPath || !outDir) {
    console.error('用法: node shot.js <timeline.json> <slide.final.html> <out_dir>');
    process.exit(1);
  }
  const tl = JSON.parse(fs.readFileSync(tlPath, 'utf8'));
  fs.mkdirSync(outDir, { recursive: true });

  const W = tl.meta.width, H = tl.meta.height;
  console.log(`${W}×${H} · ${tl.sentences.length} 句 · 共 ${tl.total.toFixed(2)}s`);

  const browser = await puppeteer.launch({
    executablePath: CHROME,
    headless: 'new',
    args: ['--no-sandbox', '--disable-gpu', '--force-device-scale-factor=1',
      '--hide-scrollbars', '--font-render-hinting=none'],
  });
  const page = await browser.newPage();
  await page.setViewport({ width: W, height: H, deviceScaleFactor: 1 });
  await page.goto('file://' + path.resolve(htmlPath), { waitUntil: 'load' });
  await page.evaluate(() => document.fonts && document.fonts.ready);

  // 位图核查：教材页图加载失败会让画面留白，必须在这里发现
  const bad = await page.evaluate(() =>
    [...document.querySelectorAll('img')]
      .filter(el => !(+el.getAttribute('width') > 0 || el.naturalWidth > 0))
      .map(el => el.getAttribute('src')));
  if (bad.length) {
    console.error('!! 页图没加载: ' + bad.join(', '));
    process.exit(1);
  }
  const unloaded = await page.evaluate(async () => {
    const imgs = [...document.querySelectorAll('img')];
    await Promise.all(imgs.map(i => i.complete ? null :
      new Promise(r => { i.onload = r; i.onerror = r; setTimeout(r, 15000); })));
    return imgs.filter(i => !i.naturalWidth).map(i => i.getAttribute('src'));
  });
  if (unloaded.length) {
    console.error('!! 页图加载失败（naturalWidth=0）: ' + unloaded.join(', '));
    process.exit(1);
  }

  for (const [i, s] of tl.sentences.entries()) {
    // 取这一句的**中点** —— 字幕在这一句全程可见
    const t = +(s.start + (s.dur || 0) / 2).toFixed(3);
    const file = path.join(outDir, String(i).padStart(3, '0') + '.png');
    await page.evaluate((tt) => window.render(tt), t);
    await page.waitForFunction(
      (tt) => document.body.dataset.t === tt, {}, t.toFixed(3), { timeout: 15000 });
    await page.screenshot({ path: file, type: 'png' });
    process.stdout.write(`\r  截图 ${i + 1}/${tl.sentences.length}   `);
  }
  console.log('\n完成');
  await browser.close();
}

main().catch(e => { console.error(e); process.exit(1); });
