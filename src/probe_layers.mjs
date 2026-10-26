/* 每层布局明细探针 —— 用来定判据阈值，不进产品。
 *
 *   node src/probe_layers.mjs <html> [...]
 *
 * 输出每层：点数 / 层半径 R / 层间距 / 层内中位最近邻点距 / R÷√n。
 * 「R÷√n 恒定」= 每层形状一致；「层内点距恒定」= 密度一致。
 */
import { createRequire } from 'node:module';
import { resolve, dirname } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const require = createRequire(import.meta.url);
const puppeteer = require('puppeteer-core');
const CHROME = process.env.CHROME || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';

const files = process.argv.slice(2);
const browser = await puppeteer.launch({
  executablePath: CHROME, headless: true,
  args: ['--no-sandbox', '--disable-background-timer-throttling'],
});

for (const f of files) {
  const page = await browser.newPage();
  await page.setViewport({ width: 1440, height: 900, deviceScaleFactor: 1 });
  await page.goto(pathToFileURL(resolve(f)).href, { waitUntil: 'load' });
  await new Promise(r => setTimeout(r, 2500));
  const rows = await page.evaluate(() => {
    const KG = window.__kg;
    const P = KG.proj();
    // 用世界坐标（n.x,n.z）算层半径，用投影坐标算点距
    const byAge = new Map();
    KG.NODES.forEach((n, i) => {
      const a = n.a1;
      if (!byAge.has(a)) byAge.set(a, []);
      byAge.get(a).push({
        wx: n.x, wz: n.z, sx: P.x[i], sy: P.y[i], r: P.r[i],
      });
    });
    const out = [];
    for (const [age, list] of [...byAge.entries()].sort((a, b) => a[0] - b[0])) {
      const n = list.length;
      // 层半径（世界坐标最大模）
      let R = 0;
      for (const p of list) R = Math.max(R, Math.hypot(p.wx, p.wz));
      // 层内中位最近邻（投影像素）
      const cell = 30, grid = new Map();
      for (const p of list) {
        const k = `${Math.floor(p.sx / cell)},${Math.floor(p.sy / cell)}`;
        if (!grid.has(k)) grid.set(k, []);
        grid.get(k).push(p);
      }
      const ds = [];
      for (const p of list) {
        const gx = Math.floor(p.sx / cell), gy = Math.floor(p.sy / cell);
        let best = Infinity;
        for (let dx = -1; dx <= 1; dx++) for (let dy = -1; dy <= 1; dy++) {
          const b = grid.get(`${gx + dx},${gy + dy}`);
          if (!b) continue;
          for (const q of b) {
            if (q === p) continue;
            const d = Math.hypot(q.sx - p.sx, q.sy - p.sy);
            if (d < best) best = d;
          }
        }
        if (best < Infinity) ds.push(best);
      }
      ds.sort((a, b) => a - b);
      out.push({
        age, n, R: +R.toFixed(1),
        rn: +(R / Math.sqrt(n)).toFixed(2),
        gap: null,
        med: ds.length ? +ds[Math.floor(ds.length / 2)].toFixed(1) : 0,
        y: +KG.NODES.find(x => x.a1 === age).y.toFixed(1),
      });
    }
    return out;
  });
  await page.close();
  console.log(`\n=== ${f.replace(/\.html$/, '').replace(/^.*\//, '')} ===`);
  console.log('age   点数      R    R÷√n   层y   层内中位点距');
  for (const r of rows) {
    console.log(
      `${String(r.age).padStart(4)} ${String(r.n).padStart(6)} ${String(r.R).padStart(7)} ` +
      `${String(r.rn).padStart(6)} ${String(r.y).padStart(6)} ${String(r.med).padStart(8)}`
    );
  }
  const med = rows.map(r => r.med).filter(v => v > 0);
  const rns = rows.map(r => r.rn);
  const cv = (a) => {
    if (a.length < 2) return 0;
    const mu = a.reduce((x, y) => x + y, 0) / a.length;
    const sd = Math.sqrt(a.reduce((x, y) => x + (y - mu) ** 2, 0) / a.length);
    return mu ? sd / mu : 0;
  };
  console.log(`  层内点距 CV = ${(cv(med) * 100).toFixed(1)}%   R÷√n CV = ${(cv(rns) * 100).toFixed(1)}%`);
}

await browser.close();
