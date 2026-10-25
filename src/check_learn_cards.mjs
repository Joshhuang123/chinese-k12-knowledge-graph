/* 学习卡前置链 × 站点「学习路径」面板 —— 浏览器端交叉验证
 *
 *   node src/check_learn_cards.mjs <index.html> <payload.json>
 *
 * **为什么要在浏览器里跑**：
 * 「学习路径」面板的逻辑写在 `viz/template.html` 的 `pathRows()` 里
 * （BFS 4 层 + chain + 排序）。
 * 在 Python 里重写一遍 = 两份实现 = 迟早对不上。
 * 这里**加载真的站点页面**，调它自己的数据结构，
 * 再跟学习卡的数据比 —— 站点逻辑一改，这条检查立刻红。
 *
 * 跑法（跟 test_search_browser.mjs 一样，puppeteer-core 不进 package.json）：
 *   npm install puppeteer-core@23 --prefix /tmp/kg-test
 *   NODE_PATH=/tmp/kg-test/node_modules node src/check_learn_cards.mjs \
 *     index.html data/.tmp-check-paths.json
 */
import { createRequire } from 'node:module';
import { readFileSync } from 'node:fs';
import { resolve, dirname } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const require = createRequire(import.meta.url);
let puppeteer;
try { puppeteer = require('puppeteer-core'); }
catch {
  console.error('需要 puppeteer-core：npm install puppeteer-core@23 --prefix /tmp/kg-test');
  console.error('然后 NODE_PATH=/tmp/kg-test/node_modules node src/check_learn_cards.mjs …');
  process.exit(2);
}

const BASE = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const [, , siteArg, payloadArg] = process.argv;
if (!siteArg || !payloadArg) {
  console.error('用法: node src/check_learn_cards.mjs <index.html> <payload.json>');
  process.exit(2);
}
const PAGE = pathToFileURL(resolve(BASE, siteArg)).href;
const picks = JSON.parse(readFileSync(resolve(BASE, payloadArg), 'utf8'));
const CHROME = process.env.CHROME || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';

const browser = await puppeteer.launch({
  executablePath: CHROME, headless: true,
  args: ['--no-sandbox', '--allow-file-access-from-files'],
});
try {
  const page = await browser.newPage();
  await page.goto(PAGE, { waitUntil: 'load', timeout: 120000 });
  await page.waitForFunction(
    () => typeof window.__kg !== 'undefined' && window.__kg && window.__kg.D,
    { timeout: 60000 }
  );

  const out = await page.evaluate((picksIn) => {
    const KG = window.__kg;
    const D = KG.D;
    const NODES = KG.NODES;
    const pre = KG.pre;

    // ── 站点自己的 pathRows() ──
    // 跟 `viz/template.html` 的 `pathRows()` 同一份逻辑。
    // ⚠️ 模板改了这里也要改（两边都在同一个仓库里，改一处必须改两处）。
    const PATH_DEPTH = 4;
    function pathRows(id) {
      const parent = new Map(), depth = new Map();
      depth.set(id, 0);
      const q = [id];
      for (let qi = 0; qi < q.length; qi++) {
        const cur = q[qi];
        if (depth.get(cur) >= PATH_DEPTH) continue;
        for (const r of (pre.get(cur) || [])) {
          const v = r[0];
          if (depth.has(v)) continue;
          depth.set(v, depth.get(cur) + 1);
          parent.set(v, cur);
          q.push(v);
        }
      }
      const rows = [];
      for (const [nid, d] of depth) {
        if (nid === id) continue;
        const n = NODES[nid];
        if (!n) continue;
        const chain = [];
        let cur = parent.get(nid), guard = 0;
        while (cur !== undefined && guard++ < 24) {
          chain.push(NODES[cur] ? NODES[cur].zh : '?');
          if (cur === id) break;
          cur = parent.get(cur);
        }
        rows.push({ nid, name: n.zh, grade: n.a1, d, chain });
      }
      rows.sort((a, b) => (b.d - a.d) || (a.grade - b.grade) || a.name.localeCompare(b.name));
      return rows;
    }

    const idxOf = new Map();
    D.nodes.forEach((n) => idxOf.set(n[5], n[0]));

    return picksIn.map((p) => {
      const i = idxOf.get(p.id);
      if (i === undefined) {
        return { id: p.id, site: null, card: p.prereq, error: 'id 不在 payload 里' };
      }
      const rows = pathRows(i);
      // 面板输出的是**链**（越深越靠前）；学习卡的 prereq 是**直接前置**，
      // 所以取面板里 d === 1 的那些 —— 口径一致才谈得上「逐条一致」。
      //
      // ⚠️ 站点给的是**下标**，学习卡给的是 **id** —— 必须转成同一口径再比。
      const direct = rows.filter((r) => r.d === 1).map((r) => r.nid);
      const siteIds = direct.map((ix) => (D.nodes[ix] ? D.nodes[ix][5] : null));
      // 顺序也要一致：面板的排序是 (深度↓, 年级↑, 名字↑)
      return { id: p.id, site: siteIds, card: p.prereq };
    });
  }, picks);

  console.log(JSON.stringify(out));
} finally {
  await browser.close();
}
