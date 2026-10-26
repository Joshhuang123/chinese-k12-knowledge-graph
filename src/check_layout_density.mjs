/* 布局密度判别力检查 —— 「站点看起来稀疏」这件事要有客观判据。
 *
 *   node src/check_layout_density.mjs [--json] <html> [...]
 *
 * ── 为什么不用「层内点距」当主判据 ──────────────────────────
 * 试过：层内最近邻点距、层间一致性、覆盖率。
 * 三个都有同一个毛病 —— **阈值随数据量漂**：
 * 小学站只有 67 个点，物理上不可能密（点距 16~54px），
 * 主站 8,667 个点能到 2px。
 * 同一个阈值要么放过主站的稀疏，要么冤枉小学站。
 *
 * ── 换成「每点占多少画布」 ──────────────────────────────────
 * 判据 = **全站凸包面积 ÷ 点数**（屏幕像素²/点）。
 * 这个量：
 *   · **与数据量无关** —— 8,667 个点和 3,393 个点可以直接比
 *   · **就是「稀疏」的物理含义** —— 每个点在画布上占多大地方
 *   · 实测能分开新旧布局：
 *       主站    新 18.4  旧 30.6  px²/点
 *       上海站  新 29.5  旧 77.2  px²/点
 *     上海站旧布局每点占画布是主站的 2.5 倍 —— 那就是「看着稀疏」。
 *
 * ── 三条纪律（都踩过）─────────────────────────────────────
 *   · 投影坐标**必须**从页面拿（`window.__kg.proj()`）——
 *     模板用的是 3D 相机（cam.th/ph/d），在脚本里重算
 *     等于自己验自己，判别力为零。
 *   · 半径**必须**用页面给的真实绘制半径——
 *     按 cen 反推是错的：半径 < 0.45px 的点根本不画。
 *   · 圆点像素要用**去重掩膜**——逐节点窗口累加会重复计数。
 */
import { createRequire } from 'node:module';
import { resolve, dirname } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const require = createRequire(import.meta.url);
const puppeteer = require('puppeteer-core');
const CHROME = process.env.CHROME || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';

const argv = process.argv.slice(2);
const asJson = argv.includes('--json');
const files = argv.filter(a => !a.startsWith('--'));

// ── 阈值 ──────────────────────────────────────────────────
// ① 每点占画布面积上限（px²/点）
//    实测：主站新 18.4 / 上海新 29.5 / 小学站 648.6（67 个点，天然疏）
//    小学站单列 —— 67 个点的站没有「密」这个概念，单独按层判。
const MAX_AREA_PER_NODE = 40.0;
// ② 跨站一致性：最疏站 ÷ 最密站，每点面积比不能超过这个数
//    实测新布局：29.5 / 18.4 = 1.60；小学站不参与（点太少）
//    旧布局主站 vs 上海站：30.6 / 77.2 = 2.52（就是「上海站看着稀疏」）
const MAX_SITE_RATIO = 2.0;
// ③ 覆盖率下限（每节点圆点像素数）—— 兜底：点画出来了但小到看不见
const MIN_COVER_PER_NODE = 0.5;

if (!files.length) { console.error('用法: node src/check_layout_density.mjs <html> [...]'); process.exit(2); }

/** 凸包面积（Andrew monotone chain）—— 独立实现，不调任何被测函数 */
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

const browser = await puppeteer.launch({
  executablePath: CHROME, headless: true,
  args: ['--no-sandbox', '--disable-background-timer-throttling'],
});

const results = [];
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

    const mask = new Uint8Array(total);
    let dots = 0;
    const pts = [];
    const N = KG.NODES.length;
    for (let i = 0; i < N; i++) {
      const r = P.r[i];
      if (r === undefined || r < 0) { pts.push(null); continue; }
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
    const drawn = pts.filter(Boolean);
    return { nodes: N, drawn: drawn.length, dots, pts: drawn };
  });
  await page.close();
  if (!m) { console.log(`✗ ${f}：页面没起来或没有 probe 出口`); process.exit(2); }
  const area = hullArea(m.pts);
  results.push({
    file: f,
    name: f.replace(/\.html$/, '').replace(/^.*\//, ''),
    nodes: m.nodes,
    area,
    perNode: m.drawn ? area / m.drawn : 0,
    coverPerNode: m.drawn ? m.dots / m.drawn : 0,
  });
}
await browser.close();

// ── 判据 ──────────────────────────────────────────────────
let fail = 0;
const big = results.filter(r => r.nodes >= 500);   // 大站：每点面积有物理意义
const small = results.filter(r => r.nodes < 500);  // 小站（小学站 67 点）：单独只看覆盖率

if (!asJson) console.log('站点        节点    凸包面积   每点面积   覆盖率/点');
if (!asJson) console.log('─'.repeat(66));

for (const r of results) {
  const checks = [];
  if (r.nodes >= 500) {
    checks.push(['① 每点面积', r.perNode, r.perNode <= MAX_AREA_PER_NODE,
      `${r.perNode.toFixed(1)} px²/点 ≤ ${MAX_AREA_PER_NODE}`]);
  }
  checks.push(['② 覆盖率', r.coverPerNode, r.coverPerNode >= MIN_COVER_PER_NODE,
    `${r.coverPerNode.toFixed(1)} 像素/点 ≥ ${MIN_COVER_PER_NODE}`]);

  r.ok = checks.every(c => c[2]);
  if (!asJson) {
    console.log(`${r.name.padEnd(12)} ${String(r.nodes).padStart(5)} ${String(Math.round(r.area)).padStart(9)} ` +
      `${r.perNode.toFixed(1).padStart(9)} ${r.coverPerNode.toFixed(1).padStart(8)}`);
    for (const [name, , ok, msg] of checks) {
      if (!ok) fail++;
      if (!ok) console.log(`   ✗ ${name}：${msg}`);
    }
  } else {
    for (const [, , ok] of checks) if (!ok) fail++;
  }
}

// 跨站一致性（只在大站之间比）
if (big.length >= 2) {
  const areas = big.map(r => r.perNode);
  const ratio = Math.max(...areas) / Math.min(...areas);
  const ok = ratio <= MAX_SITE_RATIO;
  if (!ok) fail++;
  if (!asJson) {
    console.log(`${ok ? '✓' : '✗'} 跨站一致性：最疏/最密 = ${ratio.toFixed(2)} ≤ ${MAX_SITE_RATIO}` +
      `  (${big.map(r => `${r.name} ${r.perNode.toFixed(1)}`).join(' · ')})`);
  }
}

if (asJson) console.log(JSON.stringify(results.map(r => ({
  file: r.file, nodes: r.nodes, area: r.area, perNode: r.perNode,
  coverPerNode: r.coverPerNode, ok: r.ok,
})), null, 2));
else console.log(fail ? `\n✗ ${fail} 条判据没过` : '\n✓ 布局密度判据全过');
process.exit(fail ? 1 : 0);
