#!/usr/bin/env node
// render.js —— 无头 Chrome 逐帧截图
//
//   node render.js                 全渲
//   W=6 node render.js             6 并发
//   FROM=233.8 TO=249 node render.js   只重渲这一段
//
// 两个必须做对的地方：
//  1. 每帧必须等 document.body.dataset.t 等于目标值再截图。
//     漏了会抓到上一帧，画面与音频错位且所有检查都显示正常。
//  2. 帧号补零到固定宽度，否则文件排序乱序。

const fs = require('fs');
const path = require('path');
const puppeteer = require('puppeteer-core');

const CHROME = process.env.CHROME ||
  '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const FPS = +(process.env.FPS || 30);
const WORKERS = +(process.env.W || 6);
const FROM = process.env.FROM !== undefined ? +process.env.FROM : null;
const TO = process.env.TO !== undefined ? +process.env.TO : null;

const here = __dirname;
const tlPath = path.join(here, 'timeline.json');
const scenePath = path.join(here, 'scene.final.html');
const outDir = path.join(here, 'frames');

async function main() {
  const tl = JSON.parse(fs.readFileSync(tlPath, 'utf8'));
  const TOTAL = tl.total;
  const total = Math.ceil(TOTAL * FPS);

  const i0 = FROM !== null ? Math.max(0, Math.floor(FROM * FPS)) : 0;
  const i1 = TO !== null ? Math.min(total, Math.ceil(TO * FPS)) : total;

  fs.mkdirSync(outDir, { recursive: true });

  const W = tl.meta.width, H = tl.meta.height;
  console.log(`分辨率 ${W}×${H} · ${FPS}fps · 总帧 ${total} (0 → ${(total / FPS).toFixed(3)}s)`);
  console.log(`本次 ${i1 - i0} 帧 · ${WORKERS} 并发`);
  if (!fs.existsSync(scenePath)) {
    console.error('!! 缺 scene.final.html，先跑 inject.js');
    process.exit(1);
  }

  const browser = await puppeteer.launch({
    executablePath: CHROME,
    headless: 'new',
    args: ['--no-sandbox', '--disable-gpu', '--force-device-scale-factor=1',
      '--hide-scrollbars', '--font-render-hinting=none'],
  });

  let done = 0, failed = 0;
  const t0 = Date.now();

  const worker = async (page, idx) => {
    for (let i = idx; i < i1; i += WORKERS) {
      const t = i / FPS;
      const file = path.join(outDir, String(i).padStart(6, '0') + '.png');
      try {
        await page.evaluate((tt) => window.render(tt), t);
        // 等这一帧真的画完
        await page.waitForFunction(
          (tt) => document.body.dataset.t === tt, {}, t.toFixed(3), { timeout: 15000 });
        await page.screenshot({ path: file, type: 'png' });
        done++;
        if (done % 250 === 0) {
          const el = (Date.now() - t0) / 1000;
          console.log(`  ${done}/${i1 - i0}  ${(done / el).toFixed(1)} fps`);
        }
      } catch (e) {
        failed++;
        console.error(`  ! 帧 ${i} (t=${t.toFixed(3)}) 失败: ${e.message.slice(0, 120)}`);
      }
    }
  };

  const pages = [];
  for (let k = 0; k < WORKERS; k++) {
    const page = await browser.newPage();
    await page.setViewport({ width: W, height: H, deviceScaleFactor: 1 });
    await page.goto('file://' + scenePath, { waitUntil: 'load' });
    await page.evaluate(() => document.fonts && document.fonts.ready);
    // 位图核查：不要 await load 事件。
    // SVG <image> 若在挂监听器之前就已解码完，load 事件不会再触发，会死锁；
    // waitUntil:'load' 已保证资源就绪，这里只确认尺寸非 0。
    const bad = await page.evaluate(() =>
      [...document.querySelectorAll('image')]
        .filter(el => !(+el.getAttribute('width') > 0 && +el.getAttribute('height') > 0))
        .map(el => el.getAttribute('href')));
    if (bad.length) throw new Error('位图尺寸异常: ' + bad.join(', '));
    pages.push(page);
  }

  await Promise.all(pages.map((p, k) => worker(p, k)));
  await browser.close();

  const el = (Date.now() - t0) / 1000;
  console.log(`\n完成 ${done} 帧，用时 ${el.toFixed(1)}s (${(done / el).toFixed(1)} fps)`);
  if (failed) { console.error(`失败 ${failed} 帧`); process.exit(1); }

  // 连续性检查：不能有断号
  const files = fs.readdirSync(outDir).filter(f => f.endsWith('.png'))
    .map(f => +f.replace('.png', '')).sort((a, b) => a - b);
  const holes = [];
  for (let i = i0; i < i1; i++) if (!files.includes(i)) holes.push(i);
  if (holes.length) {
    console.error(`!! 缺帧 ${holes.length} 个，例如 ${holes.slice(0, 10).join(', ')}`);
    process.exit(1);
  }
  console.log(`帧号连续 ${i0}–${i1 - 1}，无断号`);
}

main().catch(e => { console.error(e); process.exit(1); });
