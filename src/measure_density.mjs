/* 三个站的**实际视觉密度**测量 —— 不靠算术，靠像素。
 *
 *   node src/measure_density.mjs <html> [...]
 *
 * 做法：开真页面 → 画布渲染完 → 统计画布上有多少「亮像素」、
 * 节点圆点占多少像素、以及节点之间的空白面积。
 * 稀疏 = 同样的画布里点更少、点之间空隙更大。
 *
 * ⚠️ 三条纪律（都是踩过的坑）：
 *
 * 1. **不重算投影**。模板用的是 3D 相机（cam.th/ph/d），
 *    在这里用 n.x/n.y 朴素正交投影算出来的位置全是错的 ——
 *    实测中位点距会算出 0.1px 这种荒谬值。
 *    模板通过 `window.__kg.proj()` 交出自己的真实投影坐标。
 *
 * 2. **用真实绘制半径**。半径是 `(1.5 + cen*7.5)/k*0.52`，
 *    而且 < 0.45px 的点**根本不画**。
 *    按 cen 反推 = 自己验自己；按节点数猜 = 凭空编。
 *    模板通过 `window.__kg.proj().r` 交出每个点这一帧的真实半径。
 *
 * 3. **去重掩膜**。v1 用「逐节点窗口累加」统计圆点像素，
 *    重叠区域被重复计数（主站 751,442 ≈ 画布像素的一半），
 *    那个数只能用于**同节点集之间**的相对比较。
 *    v2 用集合语义的掩膜 → 真正的「圆点覆盖了画布多少」。
 */
import { createRequire } from 'node:module';
import { resolve, dirname } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const require = createRequire(import.meta.url);
const puppeteer = require('puppeteer-core');
const CHROME = process.env.CHROME || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';

const files = process.argv.slice(2);
if (!files.length) { console.error('用法: node src/measure_density.mjs <html> [...]'); process.exit(2); }

const browser = await puppeteer.launch({
  executablePath: CHROME, headless: true,
  args: ['--no-sandbox', '--disable-background-timer-throttling'],
});

console.log('站点视觉密度实测（画布像素统计 · 真实投影 + 去重掩膜）\n');
console.log('站点        节点   已画点   圆点覆盖   覆盖率   中位点距   最疏层');
console.log('─'.repeat(80));

for (const f of files) {
  const page = await browser.newPage();
  await page.setViewport({ width: 1440, height: 900, deviceScaleFactor: 1 });
  await page.goto(pathToFileURL(resolve(f)).href, { waitUntil: 'load' });
  await new Promise(r => setTimeout(r, 2500));
  const m = await page.evaluate(() => {
    const cv = document.getElementById('c');
    const KG = window.__kg;
    if (!cv || !KG || !KG.proj) return null;
    const P = KG.proj();
    const g = cv.getContext('2d');
    const d = g.getImageData(0, 0, cv.width, cv.height).data;
    const total = cv.width * cv.height;
    let bright = 0;
    for (let i = 0; i < d.length; i += 4) {
      if (d[i + 3] > 40 && (d[i] > 55 || d[i + 1] > 55 || d[i + 2] > 55)) bright++;
    }

    const N = KG.NODES.length;
    // 去重掩膜
    const mask = new Uint8Array(total);
    let dots = 0, drawn = 0;
    const pts = [];
    for (let i = 0; i < N; i++) {
      const r = P.r[i];
      if (r === undefined || r < 0) { pts.push(null); continue; }  // 这一帧没画
      drawn++;
      const sx = P.x[i], sy = P.y[i];
      pts.push([sx, sy]);
      const rr = Math.max(1, r);
      const x0 = Math.max(0, Math.floor(sx - rr)), x1 = Math.min(cv.width, Math.ceil(sx + rr));
      const y0 = Math.max(0, Math.floor(sy - rr)), y1 = Math.min(cv.height, Math.ceil(sy + rr));
      for (let y = y0; y < y1; y++) {
        for (let x = x0; x < x1; x++) {
          const i4 = (y * cv.width + x) * 4;
          if (d[i4 + 3] > 40 && (d[i4] > 90 || d[i4 + 1] > 90 || d[i4 + 2] > 90)) {
            const p = y * cv.width + x;
            if (!mask[p]) { mask[p] = 1; dots++; }
          }
        }
      }
    }

    // 层内最近邻点距（画布像素）——「疏」的直接度量。
    // 只在同层内比：跨层永远隔着一整条带，距离没有意义。
    const byAge = new Map();
    for (let i = 0; i < N; i++) {
      if (!pts[i]) continue;
      const a = KG.NODES[i].a1;
      if (!byAge.has(a)) byAge.set(a, []);
      byAge.get(a).push(pts[i]);
    }
    const layerMedian = [];
    const dists = [];
    for (const list of byAge.values()) {
      if (list.length < 2) continue;
      const cell = 30, grid = new Map();
      for (const [x, y] of list) {
        const k = `${Math.floor(x / cell)},${Math.floor(y / cell)}`;
        if (!grid.has(k)) grid.set(k, []);
        grid.get(k).push([x, y]);
      }
      const ld = [];
      for (const [x, y] of list) {
        const gx = Math.floor(x / cell), gy = Math.floor(y / cell);
        let best = Infinity;
        for (let dx = -1; dx <= 1; dx++) {
          for (let dy = -1; dy <= 1; dy++) {
            const bucket = grid.get(`${gx + dx},${gy + dy}`);
            if (!bucket) continue;
            for (const [bx, by] of bucket) {
              if (bx === x && by === y) continue;
              const dd = Math.hypot(bx - x, by - y);
              if (dd < best) best = dd;
            }
          }
        }
        if (best < Infinity) { ld.push(best); dists.push(best); }
      }
      if (ld.length) {
        ld.sort((a, b) => a - b);
        layerMedian.push(ld[Math.floor(ld.length / 2)]);
      }
    }
    dists.sort((a, b) => a - b);
    const spacing = dists.length ? dists[Math.floor(dists.length / 2)] : 0;
    // 最疏的层 = 层内点距中位数最大的那一层
    const worst = layerMedian.length ? Math.max(...layerMedian) : 0;

    return { bright, total, dots, nodes: N, drawn, spacing, worst, layers: byAge.size };
  });
  await page.close();
  if (!m) { console.log(`${f.replace('.html', '').padEnd(12)}  (没有画布或没有 probe 出口)`); continue; }
  const covPct = m.dots / m.total * 100;
  const brightPct = m.bright / m.total * 100;
  console.log(
    `${f.replace('.html', '').padEnd(12)} ${String(m.nodes).padStart(5)} ${String(m.drawn).padStart(7)} ` +
    `${String(m.dots).padStart(9)} ${covPct.toFixed(2).padStart(7)}% ` +
    `${brightPct.toFixed(2).padStart(8)}% ${m.spacing.toFixed(1).padStart(8)} ${m.worst.toFixed(1).padStart(8)}`
  );
}

await browser.close();
