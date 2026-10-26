/* 找一个跟数据量无关的「稀疏」度量 —— 试几个候选，看哪个能区分新旧布局。
 *
 *   node src/probe_metrics.mjs <html> [...]
 *
 * 候选：
 *   A. 屏幕空间凸包面积 ÷ 点数      ← 「每个点占多少画布」
 *   B. 层内中位最近邻点距（投影像素）
 *   C. 层内最近邻点距 ÷ 该层理论下限（R/√n）
 *   D. 密集层（n≥150）的层内点距
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

function hullArea(pts) {
  if (pts.length < 3) return 0;
  const p = pts.slice().sort((a, b) => a[0] - b[0] || a[1] - b[1]);
  const cross = (o, a, b) => (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0]);
  const lower = [];
  for (const q of p) {
    while (lower.length >= 2 && cross(lower[lower.length - 2], lower[lower.length - 1], q) <= 0) lower.pop();
    lower.push(q);
  }
  const upper = [];
  for (let i = p.length - 1; i >= 0; i--) {
    const q = p[i];
    while (upper.length >= 2 && cross(upper[upper.length - 2], upper[upper.length - 1], q) <= 0) upper.pop();
    upper.push(q);
  }
  lower.pop(); upper.pop();
  const hull = lower.concat(upper);
  let a = 0;
  for (let i = 0; i < hull.length; i++) {
    const j = (i + 1) % hull.length;
    a += hull[i][0] * hull[j][1] - hull[j][0] * hull[i][1];
  }
  return Math.abs(a) / 2;
}

for (const f of files) {
  const page = await browser.newPage();
  await page.setViewport({ width: 1440, height: 900, deviceScaleFactor: 1 });
  await page.goto(pathToFileURL(resolve(f)).href, { waitUntil: 'load' });
  await new Promise(r => setTimeout(r, 2500));
  const raw = await page.evaluate(() => {
    const KG = window.__kg;
    const P = KG.proj();
    const byAge = new Map();
    KG.NODES.forEach((n, i) => {
      if (P.r[i] === undefined || P.r[i] < 0) return;
      if (!byAge.has(n.a1)) byAge.set(n.a1, []);
      byAge.get(n.a1).push([P.x[i], P.y[i]]);
    });
    const layers = [...byAge.entries()].map(([age, list]) => ({ age, n: list.length, pts: list }));
    // 每层凸包面积（屏幕像素）
    return { layers, total: KG.NODES.length, drawn: layers.reduce((a, l) => a + l.n, 0) };
  });
  await page.close();

  const name = f.replace(/\.html$/, '').replace(/^.*\//, '');
  const allPts = raw.layers.flatMap(l => l.pts);
  const area = hullArea(allPts);
  console.log(`\n=== ${name} ===`);
  console.log(`  A. 全站凸包面积 ${area.toFixed(0)} px² · 点数 ${raw.drawn} → 每点 ${(area / raw.drawn).toFixed(1)} px²/点`);

  // 每层：凸包面积/点数 + 层内点距
  const rows = [];
  for (const l of raw.layers) {
    if (l.n < 2) continue;
    const la = hullArea(l.pts);
    const cell = 30, grid = new Map();
    for (const [x, y] of l.pts) {
      const k = `${Math.floor(x / cell)},${Math.floor(y / cell)}`;
      if (!grid.has(k)) grid.set(k, []);
      grid.get(k).push([x, y]);
    }
    const ds = [];
    for (const [x, y] of l.pts) {
      const gx = Math.floor(x / cell), gy = Math.floor(y / cell);
      let best = Infinity;
      for (let dx = -1; dx <= 1; dx++) for (let dy = -1; dy <= 1; dy++) {
        const b = grid.get(`${gx + dx},${gy + dy}`);
        if (!b) continue;
        for (const [bx, by] of b) {
          if (bx === x && by === y) continue;
          const dd = Math.hypot(bx - x, by - y);
          if (dd < best) best = dd;
        }
      }
      if (best < Infinity) ds.push(best);
    }
    ds.sort((a, b) => a - b);
    rows.push({ age: l.age, n: l.n, per: la / l.n, med: ds[Math.floor(ds.length / 2)] || 0 });
  }
  const dense = rows.filter(r => r.n >= 150);
  const perMed = rows.map(r => r.per).sort((a, b) => a - b);
  console.log(`  每点面积中位 ${perMed[Math.floor(perMed.length / 2)]?.toFixed(1)} px²  (层间 max/min = ${(Math.max(...perMed) / Math.min(...perMed)).toFixed(2)})`);
  if (dense.length) {
    console.log(`  D. 密集层(n≥150) 层内点距 max = ${Math.max(...dense.map(r => r.med)).toFixed(1)}px  [${dense.map(r => `${r.n}点:${r.med.toFixed(1)}`).join(' ')}]`);
  }
}

await browser.close();
