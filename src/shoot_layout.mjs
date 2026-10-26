/* 三站布局**肉眼对比**截图 —— 布局参数改了，自动指标全绿不等于画面没问题。
 *
 *   node src/shoot_layout.mjs <outdir> <html> [...]
 *
 * 每个站点截一张 1440×900 的图（首帧、相机停在默认角度）。
 */
import { createRequire } from 'node:module';
import { resolve, dirname } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { mkdirSync } from 'node:fs';

const require = createRequire(import.meta.url);
const puppeteer = require('puppeteer-core');
const CHROME = process.env.CHROME || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';

const [outdir, ...files] = process.argv.slice(2);
if (!outdir || !files.length) {
  console.error('用法: node src/shoot_layout.mjs <outdir> <html> [...]');
  process.exit(2);
}
mkdirSync(outdir, { recursive: true });

const browser = await puppeteer.launch({
  executablePath: CHROME, headless: true,
  args: ['--no-sandbox', '--disable-background-timer-throttling'],
});

for (const f of files) {
  const page = await browser.newPage();
  await page.setViewport({ width: 1440, height: 900, deviceScaleFactor: 1 });
  await page.goto(pathToFileURL(resolve(f)).href, { waitUntil: 'load' });
  await new Promise(r => setTimeout(r, 3000));
  const name = f.replace(/\.html$/, '').replace(/^.*\//, '');
  const out = resolve(outdir, `${name}.png`);
  await page.screenshot({ path: out });
  console.log(out);
  await page.close();
}

await browser.close();
