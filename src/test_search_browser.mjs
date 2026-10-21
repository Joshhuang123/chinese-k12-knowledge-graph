/* 搜索功能的端到端测试：直接开真页面，用真 Chrome。
 *
 * 为什么不用 node 拼装：n.x/n.y/n.z 是页面运行时算出来的，
 * payload 里根本没有。脚手架里重跑一遍布局 = 又维护了一份运行时，
 * 模板一改就测一个不存在的东西。所以这里只测**可观测的效果**：
 * 结果列表、卡片、焦点节点最终出现在画面正中。
 *
 * 断言的依据：draw() 把焦点节点画成「白心 + #ff3d7f 洋红环」，
 * 而 flyTo 解出的相机角度保证它的投影落在 (W/2, H/2)。
 *
 * 跑法（puppeteer-core 刻意不进 package.json —— 整个项目没有 npm 依赖，
 * 不想为一个测试把 Node 工具链变成跑图谱的前置条件）：
 *
 *   npm install puppeteer-core@23 --prefix /tmp/kg-test
 *   NODE_PATH=/tmp/kg-test/node_modules node src/test_search_browser.mjs
 *
 * createRequire 会从本文件所在目录逐级向上找 node_modules，所以如果
 * ~/node_modules 里已经有一份，直接跑即可，不用设 NODE_PATH。
 * 实在找不到，上面那行会打印这段指引并以 exit 2 退出。
 *
 * Chrome 路径可用 CHROME 环境变量覆盖（默认是 macOS 的安装位置）。
 */
import { createRequire } from 'node:module';
import { readFileSync } from 'node:fs';
import { resolve, dirname } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const require = createRequire(import.meta.url);
let puppeteer;
try {
  puppeteer = require('puppeteer-core');
} catch {
  console.error(
    '找不到 puppeteer-core。请先装：\n' +
    '  npm install puppeteer-core@23 --prefix /tmp/kg-test\n' +
    '  NODE_PATH=/tmp/kg-test/node_modules node ' + fileURLToPath(import.meta.url)
  );
  process.exit(2);
}

const BASE = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const PAGE = pathToFileURL(resolve(BASE, 'viz/知识图谱3D.html')).href;
const CHROME = process.env.CHROME || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';

const ACC = [0xff, 0x3d, 0x7f];   // 焦点环的颜色

let pass = 0, fail = 0;
function ok(c, label, extra = '') {
  if (c) { pass++; console.log(`  ✓ ${label}`); }
  else { fail++; console.log(`  ✗ ${label}${extra ? '\n      ' + extra : ''}`); }
}
const sleep = ms => new Promise(r => setTimeout(r, ms));

const browser = await puppeteer.launch({
  executablePath: CHROME,
  headless: true,
  args: ['--allow-file-access-from-files', '--no-sandbox',
         '--disable-background-timer-throttling', '--disable-renderer-backgrounding',
         '--force-device-scale-factor=1'],
});
const page = await browser.newPage();
await page.setViewport({ width: 1600, height: 1000, deviceScaleFactor: 1 });

const errors = [];
page.on('pageerror', e => errors.push(String(e)));
page.on('console', m => { if (m.type() === 'error') errors.push('console: ' + m.text()); });

await page.goto(PAGE, { waitUntil: 'load' });
await sleep(1200);

// 采样画面正中一小块：数白心像素和洋红环像素
const sampleCenter = () => page.evaluate((acc) => {
  const cv = document.getElementById('c');
  const g = cv.getContext('2d');
  const cx = Math.round(cv.width / 2), cy = Math.round(cv.height / 2);
  const R = 26;
  const img = g.getImageData(cx - R, cy - R, R * 2, R * 2).data;
  let white = 0, pink = 0, lit = 0;
  for (let i = 0; i < img.length; i += 4) {
    const [r, gg, b, a] = [img[i], img[i + 1], img[i + 2], img[i + 3]];
    if (a < 20) continue;
    lit++;
    if (r > 200 && gg > 200 && b > 200) white++;
    const near = (x, y) => Math.abs(x - y) <= 70;
    if (near(r, acc[0]) && near(gg, acc[1]) && near(b, acc[2])) pink++;
  }
  const n = (R * 2 * R * 2);
  return { white, pink, lit, total: n };
}, ACC);

console.log(`页面已开：${PAGE}\n`);

console.log('[1] 页面无脚本错误');
ok(errors.length === 0, '没有 JS 报错 / 控制台错误', errors.slice(0, 3).join('\n      '));

console.log('\n[1b] 页面自洽：标题里的数字必须是真实规模');
{
  // 这条是被真抓出来的：模板 <title> 原来写死「1,590 个知识点」——
  // 那是 Marble 的规模，我们是 7,938。已经上线了才发现。
  // 根因是硬编码数字会漂移，所以在这加一道守卫。
  //
  // **判据后来收紧了。** 原来只查「标题里有画布点数」，
  // 但画布上多出来的 68 个是我们补的 L0 能力节点和 derived 概念 ——
  // 「中国的孩子在学什么 · 8,006 个知识点」把它们算成了教材知识点。
  // 现在标题用**教材知识点数**（上游 Concept/Skill/Experiment），
  // 而这个数**由测试自己从 graph.json 数出来**，不看页面给的数 ——
  // 页面自己报一个数再拿来跟它自己比，等于没测。
  const meta = await page.evaluate(() => {
    const D = JSON.parse(document.getElementById('data').textContent);
    return { N: D.nodes.length, total: D.total, title: document.title,
             icon: document.querySelector('link[rel="icon"]')?.href || '' };
  });
  const g = JSON.parse(readFileSync(resolve(BASE, 'data/normalized/graph.json'), 'utf8'));
  const upstream = g.nodes.filter(n =>
    ['Concept', 'Skill', 'Experiment'].includes(n.label)).length;
  ok(meta.total === upstream,
     `payload.total（${meta.total}）等于 graph.json 里的上游知识点数（${upstream}）`,
     `total=${meta.total} upstream=${upstream}`);
  const want = upstream.toLocaleString('en-US');
  ok(meta.title.includes(want),
     `标题含教材知识点数 ${want}（不是画布点数 ${meta.N.toLocaleString('en-US')}）`,
     meta.title);
  ok(!/1,590|1,127|5,255/.test(meta.title), '标题里没有别的项目的遗留数字', meta.title);
  // **标题的口径必须跟页面主体一致。**
  // 原来只替换了 <h1>（「中国的孩子」），<title> 漏了 ——
  // 浏览器标签页上写着「全世界孩子在学什么」，页面主体却是「中国的孩子」，
  // 自己跟自己打架；分享链接时标签页那句最先被看见。
  ok(!/全世界/.test(meta.title), '标签页标题里没有「全世界」', meta.title);
  ok(/中国的孩子/.test(meta.title), '标签页标题是「中国的孩子在学什么」', meta.title);
  const h1 = await page.evaluate(() => document.querySelector('#head h1')?.textContent || '');
  ok(!/全世界/.test(h1) && /中国的孩子/.test(h1),
     `页面大标题也是「中国的孩子」（实际「${h1.replace(/\s+/g, '')}」）`);
  ok(meta.icon.startsWith('data:image/svg+xml'), 'favicon 内联（单文件自包含，不会 404）');
}

console.log('\n[1c] 无外部资源请求（file:// 之外的引用一律不许有）');
{
  const ext = [];
  page.on('request', r => { const u = r.url(); if (!u.startsWith('file:') && !u.startsWith('data:')) ext.push(u); });
  await page.reload({ waitUntil: 'load' });
  await sleep(1500);
  ok(ext.length === 0, `没有引用任何外部文件${ext.length ? '：' + ext.slice(0, 3).join(', ') : ''}`,
     ext.slice(0, 3).join('\n      '));
}

console.log('\n[1d] 标题字形必须是无衬线（不能悄悄变成宋体）');
{
  // 量字宽没用——CJK 全角，width 一律相同。改用像素指纹：
  // 同一句话分别按 sans-serif 和 serif 渲染，比对灰度指纹。
  const res = await page.evaluate(() => {
    const T = '中国的孩子在学什么。';
    const cv = document.createElement('canvas'); cv.width = 700; cv.height = 90;
    const g = cv.getContext('2d');
    const fp = s => {
      g.clearRect(0, 0, 700, 90);
      g.fillStyle = '#000'; g.fillRect(0, 0, 700, 90);
      g.font = '400 60px ' + s; g.fillStyle = '#fff'; g.textBaseline = 'top';
      g.fillText(T, 4, 4);
      const d = g.getImageData(0, 0, 700, 90).data;
      let h = 0; for (let i = 0; i < d.length; i += 4) h = (h * 31 + d[i]) | 0;
      return h;
    };
    const h1 = getComputedStyle(document.querySelector('#head h1')).fontFamily;
    return { sans: fp('sans-serif'), serif: fp('serif'), actual: fp(h1), h1 };
  });
  ok(res.sans !== res.serif, '基准成立：sans-serif 与 serif 在本页确实渲染成不同字形');
  ok(res.actual === res.sans, 'h1 渲染结果与 sans-serif 一致（不是宋体）', res.h1);
}

console.log('\n[2] 搜索框存在且可聚焦');
await page.click('#q');
ok(await page.evaluate(() => document.activeElement.id === 'q'), '点击后焦点在输入框');

console.log('\n[3] 输入中文名出结果');
await page.type('#q', '光合作用', { delay: 25 });
await sleep(250);
let res = await page.evaluate(() => ({
  on: document.getElementById('res').classList.contains('on'),
  items: [...document.querySelectorAll('#res .r')].map(e => ({
    name: e.querySelector('span:nth-child(2)').textContent,
    book: e.querySelector('.bk').textContent,
  })),
  input: document.getElementById('q').value,
}));
ok(res.input === '光合作用', `输入框内容正确（${res.input}）`);
ok(res.on, '结果框展开');
ok(res.items.length > 0, `有 ${res.items.length} 条结果`);
ok(res.items.some(x => x.name.includes('光合')), '结果里有「光合作用」', JSON.stringify(res.items));
ok(res.items.every(x => x.book && x.book.includes('·')), '每条都带册次标签', JSON.stringify(res.items.map(x => x.book)));

console.log('\n[4] Enter 跳转：卡片弹出 + 焦点节点落到画面正中');
await page.keyboard.press('Enter');
await sleep(1800);   // 相机 lerp 0.09/帧，给足收敛时间

const card = await page.evaluate(() => {
  const c = document.getElementById('card');
  return { on: c.classList.contains('on'), text: (c.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 120) };
});
ok(card.on, '详情卡弹出');
ok(card.text.includes('光合'), '卡片内容是光合作用', card.text);
ok(await page.evaluate(() => !document.getElementById('res').classList.contains('on')), '跳转后结果框收起');

const before = await sampleCenter();
ok(before.white > 0, `画面正中 ${before.white} 个白心像素 —— 焦点节点确实被画在最中间`, JSON.stringify(before));
ok(before.pink > 30, `焦点环 ${before.pink} 个洋红像素（白心周围）`, JSON.stringify(before));

console.log('\n[5] 前置链被高亮（activeSet 非空 → 其余节点压暗）');
const dim = await page.evaluate(() => {
  const cv = document.getElementById('c');
  const g = cv.getContext('2d');
  const d = g.getImageData(0, 0, cv.width, cv.height).data;
  let bright = 0;
  for (let i = 0; i < d.length; i += 4) {
    if (d[i + 3] > 60 && d[i] > 150 && d[i + 1] > 60 && d[i + 1] < 200 && d[i + 2] < 150) bright++;
  }
  return bright;
});
ok(dim > 200, `画面里有 ${dim} 个高亮（洋红=前置链 / 学科色）像素，说明 activeSet 不是空的`);

console.log('\n[6] 键盘：↑↓ 选择 / / 聚焦 / Esc 关闭');
await page.keyboard.press('Escape');
await page.click('#q');
await page.evaluate(() => { document.getElementById('q').value = ''; document.getElementById('q').dispatchEvent(new Event('input')); });
await page.type('#q', '方程', { delay: 20 });
await sleep(200);
const nRes = await page.evaluate(() => document.querySelectorAll('#res .r').length);
ok(nRes > 1, `「方程」有 ${nRes} 条结果，可以用方向键选`);
const sel0 = await page.evaluate(() => [...document.querySelectorAll('#res .r')].findIndex(e => e.classList.contains('sel')));
await page.keyboard.press('ArrowDown');
const sel1 = await page.evaluate(() => [...document.querySelectorAll('#res .r')].findIndex(e => e.classList.contains('sel')));
ok(sel0 === 0 && sel1 === 1, `↓ 把选中项从第 ${sel0} 条移到第 ${sel1} 条`);
await page.keyboard.press('Escape');
ok(await page.evaluate(() => !document.getElementById('res').classList.contains('on')), 'Esc 收起结果框');
await page.evaluate(() => document.getElementById('q').blur());
await page.keyboard.press('/');
ok(await page.evaluate(() => document.activeElement.id === 'q'), '按 / 聚焦搜索框');

console.log('\n[7] 册次搜索');
await page.evaluate(() => { document.getElementById('q').value = ''; });
await page.type('#q', '五上', { delay: 20 });
await sleep(200);
const bk = await page.evaluate(() => [...document.querySelectorAll('#res .r .bk')].map(e => e.textContent));
ok(bk.length > 0 && bk.every(x => x.startsWith('五上')), `册次搜索命中且全是五上（${bk.length} 条）`, JSON.stringify(bk));

console.log('\n[8] 无匹配');
// **先打开一个节点的卡片**，再搜不存在的词。
// 不先打开的话卡片本来就是关的，这条断言恒为真 ——
// 判别力为零，撤掉修复它也不会红。
await page.evaluate(() => { document.getElementById('q').value = ''; });
await page.type('#q', '小数加法', { delay: 20 });
await sleep(300);
await page.keyboard.press('Enter');
await sleep(1200);
const cardWasOpen = await page.evaluate(() =>
  document.getElementById('card').classList.contains('on'));
ok(cardWasOpen, '先打开一个节点的卡片（后面要验证它被收掉）');
await page.evaluate(() => { document.getElementById('q').value = ''; });
await page.type('#q', 'qqqq不存在', { delay: 20 });
await sleep(300);
ok(await page.evaluate(() => document.getElementById('res').textContent.includes('没有匹配')), '给出「没有匹配」提示');
// **搜不到时，上一个节点的卡片必须收掉。**
// 原来卡片还停在上一次搜的内容上，看着像「搜到了这个」，
// 实际展示的是上一条 —— 用户会以为页面卡了。
ok(await page.evaluate(() => !document.getElementById('card').classList.contains('on')),
   '搜不到时把上一个节点的卡片收掉（别残留）');

console.log('\n[8a] 已修正的边不能同时出现在前置和后继');
{
  // 「三角形的高」的上游边原来是「三角形的高 → 三角形」（方向反了）。
  // 修正成「三角形 → 三角形的高」时，**只加了反向边，没删原边**，
  // 结果同一对节点在卡片上同时出现在「要先会」和「学会后能学」两栏里 ——
  // 它既是因又是果，一眼就看出矛盾。
  await page.evaluate(() => { document.getElementById('q').value = ''; });
  await page.type('#q', '三角形的高', { delay: 20 });
  await sleep(300);
  await page.keyboard.press('Enter');
  await sleep(1500);
  const dup = await page.evaluate(() => {
    // **`.ct[data-b="pre"]` 是标题，行是它的兄弟，不是后代。**
    // 用后代选择器 `.ct[data-b="pre"] .dep` 一个都取不到 ——
    // 断言恒为「无重叠」，判别力为零，撤掉修复也不会红。
    const names = sel => {
      const t = document.querySelector(`#cChain .ct[data-b="${sel}"]`);
      const out = [];
      let el = t && t.nextElementSibling;
      while (el && !el.classList.contains('ct')) {
        out.push(...[...el.querySelectorAll('.dep .t')].map(e => e.textContent.trim()));
        el = el.nextElementSibling;
      }
      return out;
    };
    const pre = names('pre'), post = names('post');
    return { pre, post, both: pre.filter(x => post.includes(x)) };
  });
  ok(dup.both.length === 0,
     `前置与后继里没有同一个节点（重叠：${dup.both.join('、') || '无'}）`);
}

console.log('\n[8b] 别名能搜到 + 教材里更早的排前面');
{
  // 别名：L0 能力的别名（「观察力」「生活经验」「规范操作」…）
  // 是模型在盲测里实际说的词，全量跑完 1,700+ 次；
  // 主名却是「观察与发现规律」。搜「观察力」搜不到，
  // 等于**最常被提到的名字反而搜不着**。
  await page.evaluate(() => { document.getElementById('q').value = ''; });
  await page.type('#q', '观察力', { delay: 20 });
  await sleep(300);
  const aliasHit = await page.evaluate(() => {
    const r = document.querySelector('#res .r');
    return r ? r.textContent.replace(/\s+/g, ' ').trim() : '';
  });
  ok(/观察与发现规律/.test(aliasHit), `搜别名「观察力」能搜到「观察与发现规律」（实际「${aliasHit}」）`);

  // 排序：搜「光合作用」有初中生物和高中化学两个。
  // 原来按「被依赖度」排，**高中化学**（0.214）排在**初中生物**前面 ——
  // 被依赖度反映的是图谱里多少条边指向它，不是教学上的早晚。
  await page.evaluate(() => { document.getElementById('q').value = ''; });
  await page.type('#q', '光合作用', { delay: 20 });
  await sleep(300);
  const first = await page.evaluate(() => {
    const r = document.querySelector('#res .r');
    return r ? r.textContent.replace(/\s+/g, ' ').trim() : '';
  });
  ok(/七上/.test(first) && !/必修二/.test(first),
     `搜「光合作用」第一条是初中生物那个，不是高中化学（实际「${first}」）`);
}

console.log('\n[8c] 二维知识脉络：能打开、分层正确、能钻取');
{
  await page.evaluate(() => { document.getElementById('q').value = ''; });
  await page.type('#q', '二次函数', { delay: 20 });
  await sleep(300);
  await page.keyboard.press('Enter');
  await sleep(1400);
  await page.click('#cMap');
  await sleep(800);
  const m = await page.evaluate(() => {
    const svg = document.getElementById('mapSvg');
    const cols = [...document.querySelectorAll('#mapSvg .mcol')].map(e => e.textContent);
    const nodes = [...document.querySelectorAll('#mapSvg .mnode')];
    // 圆点的 x 坐标集合 = 实际用到的列
    const xs = [...new Set(nodes.map(n => Math.round(+n.querySelector('circle').getAttribute('cx'))))].sort((a,b)=>a-b);
    return {
      open: !document.getElementById('map').hidden,
      name: document.getElementById('mapName').textContent,
      sub: document.getElementById('mapSub').textContent,
      cols, xs, nNodes: nodes.length,
      nEdges: document.querySelectorAll('#mapSvg .medge').length,
      // 纵向不能全挤在一行：圆的 cy 必须有多个不同值
      ys: [...new Set(nodes.map(n => +n.querySelector('circle').getAttribute('cy')))].length,
      // 文字不能叠在一起：同一列内相邻两个圆的 y 差要够放一行字
      rowGap: (() => {
        const byX = {};
        for (const n of nodes) {
          const k = Math.round(+n.querySelector('circle').getAttribute('cx'));
          (byX[k] = byX[k] || []).push(+n.querySelector('circle').getAttribute('cy'));
        }
        let min = 1e9;
        for (const arr of Object.values(byX)) {
          arr.sort((a,b)=>a-b);
          for (let i=1;i<arr.length;i++) min = Math.min(min, arr[i]-arr[i-1]);
        }
        return min;
      })(),
    };
  });
  ok(m.open, '点「知识脉络」能打开二维视图');
  ok(m.name === '二次函数', `中心节点是当前知识点（${m.name}）`);
  ok(m.cols.length >= 3, `至少三列：先修 / 当前 / 后继（${m.cols.join(' | ')}）`);
  ok(m.cols.some(c => c.includes('先修')) && m.cols.some(c => c.includes('后继')),
     '先修在左、后继在右');
  ok(m.ys >= 3, `节点纵向铺开，不是挤在一行（${m.ys} 个不同的 y）`);
  ok(m.rowGap >= 18, `同列相邻节点间距够放标签（最小 ${m.rowGap}px）`);
  ok(m.nNodes > 10 && m.nEdges > 5, `图里有内容（${m.nNodes} 节点 / ${m.nEdges} 边）`);

  // **每条线都要真的接到点上。**
  // 原来边的起点 y 用了水平的平移函数 tx()，节点圆心用的是 ty() ——
  // 差了一个 (minX - minY)，整张图的线全接歪，看着像「没连上」。
  // 这条断言量的是「边的起点离最近节点圆心多远」：应落在圆半径附近。
  const wired = await page.evaluate(() => {
    const ns = [...document.querySelectorAll('#mapSvg .mnode')].map(g => {
      const c = g.querySelector('circle');
      return { x: +c.getAttribute('cx'), y: +c.getAttribute('cy') };
    });
    const bad = [];
    document.querySelectorAll('#mapSvg .medge').forEach((p, i) => {
      const n = p.getAttribute('d').match(/-?\d+(\.\d+)?/g).map(Number);
      const M = [n[0], n[1]];
      let dm = 1e9;
      for (const v of ns) dm = Math.min(dm, Math.hypot(v.x - M[0], v.y - M[1]));
      if (dm > 12) bad.push({ i, d: +dm.toFixed(1) });
    });
    return { total: document.querySelectorAll('#mapSvg .medge').length, bad };
  });
  ok(wired.bad.length === 0,
     `每条线都接到点上（${wired.total} 条线，断开 ${wired.bad.length} 条` +
     `${wired.bad.length ? '：' + wired.bad.slice(0,3).map(b=>b.d+'px').join(',') : ''}）`);

  // **方向要看得见**：箭头（三角形）数量 = 边数量，且分界线把先修/后继分开
  const dir = await page.evaluate(() => {
    const arrows = document.querySelectorAll('#mapSvg path[fill]:not([fill="none"])').length;
    const div = document.querySelectorAll('#mapSvg line').length;
    return { arrows, div };
  });
  ok(dir.arrows >= wired.total, `每条边都有箭头（${dir.arrows} 个三角 / ${wired.total} 条边）`);
  ok(dir.div >= 1, '先修区与后继区之间有分界线');

  // 钻取：点一个非中心节点，应以它为新中心
  const drill = await page.evaluate(() => {
    const g = [...document.querySelectorAll('#mapSvg .mnode')].find(e => !e.classList.contains('center'));
    const nm = g.querySelector('text').textContent;
    g.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    return { nm, now: document.getElementById('mapName').textContent };
  });
  ok(drill.now === drill.nm, `点节点能以它为新中心（${drill.nm} → ${drill.now}）`);

  // Esc 关闭
  await page.keyboard.press('Escape');
  await sleep(200);
  ok(await page.evaluate(() => document.getElementById('map').hidden), 'Esc 能关闭脉络视图');
}

console.log('\n[8c-2] 脉络视图画的每条线都必须在图谱里真实存在');
{
  // **这条断言是本轮修 ISSUE-25 F1/F2 时加的。**
  // 原来脉络视图把所有节点直连到根（`edges.push([nid, root, ...])`），
  // 画出来的线有一半以上在图谱里根本不存在 ——
  // 真实关系「正比例函数 → 函数 → 二次函数」被画成「正比例函数 ──→ 二次函数」。
  // 线是断言不是画法偏好：看图的人会得出图谱没说过的话。
  //
  // 判别力：把模板改回直连根，这一条立刻红（实测 56.9% 的线对不上）。
  const probes = ['二次函数', '函数', '光合作用', '电流', '细胞', '力'];
  let checked = 0, bad = 0, pushed = 0, details = [];
  for (const kw of probes) {
    await page.evaluate(() => { const q = document.getElementById('q'); q.value = ''; q.dispatchEvent(new Event('input')); });
    await page.click('#q');
    await page.type('#q', kw, { delay: 15 });
    await sleep(300);
    await page.keyboard.press('Enter');
    await sleep(1400);
    await page.click('#cMap');
    await sleep(900);
    const r = await page.evaluate(() => {
      const KG = window.__kg;
      // 图谱里真实存在的边：payload 的 [后继, 先修, ...]
      const real = new Set();
      for (const e of KG.D.edges) real.add(e[1] + '>' + e[0]);
      const edges = [...document.querySelectorAll('#mapSvg .medge')];
      const bad = edges.filter(p => !real.has(p.dataset.a + '>' + p.dataset.b));
      // 直接前置必须落在「先修 1 层」那一列，不能被推到更远
      const root = KG.NODES.findIndex(n => n.zh === document.getElementById('mapName').textContent);
      const direct = new Set((KG.pre.get(root) || []).map(r => r[0]));
      const cols = new Map();
      for (const g of document.querySelectorAll('#mapSvg .mnode')) {
        const cx = +g.querySelector('circle').getAttribute('cx');
        cols.set(cx, (cols.get(cx) || 0) + 1);
      }
      const xs = [...cols.keys()].sort((a, b) => a - b);
      // 第 1 层的列 = 中心左边最近的那一列
      const oneLayerX = xs.length >= 2 ? xs[1] : null;
      const pushed = [...document.querySelectorAll('#mapSvg .mnode')].filter(g => {
        const id = +g.dataset.id;
        if (!direct.has(id)) return false;
        return +g.querySelector('circle').getAttribute('cx') !== oneLayerX;
      }).map(g => KG.NODES[+g.dataset.id].zh);
      return { total: edges.length, bad: bad.length, pushed, rootFound: root >= 0 };
    });
    checked += r.total; bad += r.bad; pushed += r.pushed.length;
    if (r.bad) details.push(`${kw}: ${r.bad}/${r.total} 条对不上`);
    if (r.pushed.length) details.push(`${kw}: 直接前置被推远 ${r.pushed.join('、')}`);
    await page.keyboard.press('Escape');
    await sleep(250);
  }
  ok(bad === 0, `脉络视图的 ${checked} 条线全部在图谱里存在（对不上 ${bad} 条）`,
     details.join('\n      '));
  ok(pushed === 0, `直接前置全部落在「先修 1 层」列（被推远 ${pushed} 个）`,
     details.join('\n      '));
}

console.log('\n[8c-3] 7 档来源色一个都不能少，线的来源要有图例');
{
  // 原来 MAP_SRC_COLOR 只有 6 个颜色，tier6「教材结构图」回退成
  // tier0「上游」的灰 —— 恰恰是最该跟别的档区分的那一档。
  const c = await page.evaluate(() => {
    // 从页面上量：取一条 tier6 的边，看它渲成什么色
    const KG = window.__kg;
    const six = KG.D.edges.find(e => e[2] === 6);
    const zero = KG.D.edges.find(e => e[2] === 0);
    return { hasSix: !!six, hasZero: !!zero };
  });
  ok(c.hasSix, 'payload 里有 tier6（教材结构图）的边');

  // 打开一个含 tier6 边的节点的脉络，量它的线色
  await page.evaluate(() => { const q = document.getElementById('q'); q.value = ''; q.dispatchEvent(new Event('input')); });
  await page.click('#q');
  await page.type('#q', '不等式', { delay: 15 });
  await sleep(300);
  await page.keyboard.press('Enter');
  await sleep(1400);
  await page.click('#cMap');
  await sleep(900);
  const r = await page.evaluate(() => {
    const KG = window.__kg;
    const real = new Set();
    for (const e of KG.D.edges) real.add(e[1] + '>' + e[0]);
    const out = { tier6: null, tier0: null };
    for (const p of document.querySelectorAll('#mapSvg .medge')) {
      const src = +p.dataset.src;
      if (src === 6 && out.tier6 === null) out.tier6 = p.getAttribute('stroke');
      if (src === 0 && out.tier0 === null) out.tier0 = p.getAttribute('stroke');
    }
    out.legend = document.getElementById('mapLegend').classList.contains('on');
    out.legendText = document.getElementById('mapLegend').textContent.replace(/\s+/g, ' ').trim();
    return out;
  });
  ok(r.tier6 !== null, '脉络视图里画出了 tier6 的边');
  ok(r.tier6 && r.tier6 !== r.tier0,
     `tier6（教材结构图）的线色跟 tier0（上游）不一样（${r.tier6} vs ${r.tier0}）`);
  ok(r.legend, '按来源着色时，脉络视图里有线的来源图例');
  ok(/教材结构图/.test(r.legendText) || !/上游/.test(r.legendText),
     `图例里的档位名跟实际用到的档位对得上（${r.legendText.slice(0, 60)}）`);
  await page.keyboard.press('Escape');
  await sleep(250);
}

console.log('\n[8c-4] 「卡在哪」：先修闭包要排得出优先级');
{
  // 这是本项目真正要回答的那个问题：
  // 「朋友最近在二次函数上卡住，是因为什么前置的缺失」。
  // 脉络视图给的是「有哪些前置」（事实），这个面板给的是「先补哪一块」（判断）。
  await page.evaluate(() => { const q = document.getElementById('q'); q.value = ''; q.dispatchEvent(new Event('input')); });
  await page.click('#q');
  await page.type('#q', '二次函数', { delay: 20 });
  await sleep(300);
  await page.keyboard.press('Enter');
  await sleep(1400);
  await page.click('#cGap');
  await sleep(800);
  const g = await page.evaluate(() => {
    const KG = window.__kg;
    const items = [...document.querySelectorAll('#gapList li[data-id]')].map(li => ({
      id: +li.dataset.id,
      name: li.querySelector('.nm').textContent,
      score: parseFloat(li.querySelector('.sc').textContent),
      why: li.querySelector('.why').textContent.replace(/\s+/g, ' ').trim(),
    }));
    // 排出来的必须是**真祖先**（沿先修边能走到）
    const anc = new Set();
    let fr = [KG.cardId()];
    for (let d = 0; d < 3; d++) {
      const nx = [];
      for (const u of fr) for (const r of (KG.pre.get(u) || [])) {
        if (!anc.has(r[0])) { anc.add(r[0]); nx.push(r[0]); }
      }
      fr = nx;
    }
    return {
      open: !document.getElementById('gap').hidden,
      name: document.getElementById('gapName').textContent,
      sub: document.getElementById('gapSub').textContent,
      items,
      notAncestor: items.filter(i => !anc.has(i.id)).map(i => i.name),
      sorted: items.every((v, i, a) => i === 0 || a[i-1].score >= v.score),
      rootFirst: items.length ? items[0].why.includes('根') || items[0].why.includes('很早') : false,
    };
  });
  ok(g.open, '「卡在哪」面板能打开');
  ok(g.name === '二次函数', `面板中心是当前知识点（${g.name}）`);
  ok(g.items.length > 0, `排出了 ${g.items.length} 个候选`);
  ok(g.notAncestor.length === 0,
     `排出来的每个候选都是真的先修祖先（不是祖先的：${g.notAncestor.join('、') || '无'}）`);
  ok(g.sorted, '候选按分数降序');
  ok(g.rootFirst, '排在最前面的是「链的根」或「很早学」的（最该先补的那块）');
  ok(/直接前置/.test(g.items[0].why) || /隔 \d+ 层/.test(g.items[0].why),
     `第一条给了人话理由（${g.items[0].why.slice(0, 50)}）`);

  // ── 视觉层：面板里要能看到教材原书的公式和图 ──────────────────
  // 「卡在哪」原来只给「先补哪一块」���判断。
  // 有了视觉层之后，每条候选底下能直接看到**教材原书上写着什么式子**、
  // **画了什么图** —— 这才是「要补的那一块」的真实内容。
  const vis = await page.evaluate(() => {
    const KG = window.__kg;
    const lis = [...document.querySelectorAll('#gapList li[data-id]')];
    const blocks = lis.map(li => ({
      id: +li.dataset.id,
      vbs: [...li.querySelectorAll('.vb')].map(vb => ({
        head: (vb.querySelector('.vh')?.textContent || '').trim(),
        text: (vb.textContent || '').replace(/\s+/g, ' ').trim(),
      })),
    }));
    const withVis = blocks.filter(b => b.vbs.length);
    // LaTeX 残留：这些字符在纯文本里不该出现
    const latexish = blocks.flatMap(b => b.vbs.map(v => v.text))
      .filter(t => /\\(frac|sqrt|left|right|begin|text|overline|cdot)|\^\{|_\{|\{|\$/.test(t));
    // 「据图」标注：图描述必须有
    const figBlocks = blocks.flatMap(b => b.vbs).filter(v => v.head.includes('图'));
    const marked = figBlocks.filter(v => v.text.includes('据图'));
    return {
      hasMap: !!(KG.vision && Object.keys(KG.vision).length),
      mapSize: KG.vision ? Object.keys(KG.vision).length : 0,
      total: blocks.length,
      withVis: withVis.length,
      sample: withVis[0] || null,
      latexish: latexish.slice(0, 3),
      figCount: figBlocks.length,
      markedCount: marked.length,
      // 面板里某条的公式，要跟 payload 里那个概念的公式对得上
      consistent: withVis.length ? (() => {
        const v = KG.vision[withVis[0].id];
        const page = withVis[0].vbs.map(x => x.text).join(' ');
        return !v || !v[0] || !v[0].length ||
               v[0].some(f => page.includes(f));
      })() : false,
    };
  });
  ok(vis.hasMap, `payload 里有视觉层数据（${vis.mapSize} 个概念）`);

  // ── 教材自己标的难点（「思考」「探究」框）──────────────────
  // 这是**教材编委会标的**，不是模型推断的 —— 面板里必须有。
  const hrd = await page.evaluate(() => {
    const KG = window.__kg;
    const h = KG.hard || {};
    const lis = [...document.querySelectorAll('#gapList li[data-id]')];
    const blocks = lis.map(li => ({
      id: +li.dataset.id,
      txt: [...li.querySelectorAll('.vh2')].map(v => v.textContent.replace(/\s+/g, ' ').trim()),
    }));
    const withH = blocks.filter(b => b.txt.length);
    return {
      mapSize: Object.keys(h).length,
      total: blocks.length,
      withH: withH.length,
      sample: withH[0] || null,
      // 题干里不能有 LaTeX 源码漏出来
      latex: withH.flatMap(b => b.txt).filter(t => /\\(frac|sqrt|neq|le|ge|text)|\$|\^\{/.test(t)),
    };
  });
  ok(hrd.mapSize > 100, `payload 里有教材标的难点（${hrd.mapSize} 个概念）`);
  ok(hrd.withH > 0,
     `「卡在哪」面板里有 ${hrd.withH}/${hrd.total} 条候选显示了教材标的难点`);
  ok(hrd.latex.length === 0,
     `教材难点的题干里没有 LaTeX 源码（漏出 ${hrd.latex.length} 处）`,
     hrd.latex.slice(0, 2).join(' / '));
  if (hrd.sample) {
    console.log(`      例：${hrd.sample.txt[0].slice(0, 76)}`);
  }
  ok(vis.withVis > 0,
     `「卡在哪」面板里有 ${vis.withVis}/${vis.total} 条候选带上了教材公式或图`);
  ok(vis.latexish.length === 0,
     `公式是给人看的纯文本（没有 LaTeX 残留：${vis.latexish.join(' / ') || '无'}）`);
  ok(vis.figCount > 0 && vis.markedCount === vis.figCount,
     `图描述都标了「据图」（${vis.markedCount}/${vis.figCount}）`);
  ok(vis.consistent, '面板上显示的公式跟 payload 里那个概念的公式对得上');
  if (vis.sample) {
    console.log(`      例：${vis.sample.vbs[0].head} → ${vis.sample.vbs[0].text.slice(0, 70)}`);
  }

  // 选题卡：复制出来的内容要能直接进内容生产
  const card = await page.evaluate(() => {
    const KG = window.__kg;
    // 复用面板里的生成逻辑：复制按钮走剪贴板，这里直接取文本
    const btn = document.getElementById('gapCopy');
    return { hasBtn: !!btn, label: btn?.textContent };
  });
  ok(card.hasBtn, '有「复制选题卡」按钮');

  await page.keyboard.press('Escape');
  await sleep(200);
  ok(await page.evaluate(() => document.getElementById('gap').hidden), 'Esc 能关闭「卡在哪」');
  // **面板开着时按 Esc，不能把底下的卡片也关了。**
  // 主 IIFE 的全局 Escape 处理器在 window 上，会 `card.classList.remove('on')`。
  // 连锁后果实测过：卡片一关，「知识脉络」按钮就点不动了（pointer-events:none），
  // 脉络视图根本开不起来 —— 看着像功能坏了，其实是 Esc 的副作用。
  ok(await page.evaluate(() => document.getElementById('card').classList.contains('on')),
     '按 Esc 关面板后，卡片还在（没被全局 Escape 一起关掉）');
  const stillOpens = await page.evaluate(() => {
    document.getElementById('cMap').click();
    return !document.getElementById('map').hidden;
  });
  ok(stillOpens, '关掉面板后，「知识脉络」仍然点得开');
  await page.keyboard.press('Escape');
  await sleep(200);
}

console.log('\n[8c-5] 多版本教材：卡片的「其他版本教材里的位置」');
{
  // 图谱按人教版排，但上海用沪教版、湖南用湘教版……
  // 「九上 22.2 二次函数」这个说法对用别的教材的学生没有意义，
  // 得告诉他「你那本里是第几节」。
  await page.evaluate(() => { const q = document.getElementById('q'); q.value = ''; q.dispatchEvent(new Event('input')); });
  await page.click('#q');
  await page.type('#q', '相交线', { delay: 20 });
  await sleep(400);
  await page.keyboard.press('Enter');
  await sleep(1500);
  const r = await page.evaluate(() => {
    const el = document.getElementById('cAlt');
    const KG = window.__kg;
    return {
      hidden: el.hidden,
      text: el.textContent.replace(/\s+/g, ' ').trim(),
      // payload 里确实带着多版本数据
      hasPayload: !!(KG.D.altpos && Object.keys(KG.D.altpos).length),
      rows: el.querySelectorAll('.arow').length,
    };
  });
  ok(r.hasPayload, 'payload 里带了多版本对照数据');
  ok(!r.hidden && r.rows > 0, `「其他版本教材里的位置」这一栏有内容（${r.rows} 行）`);
  ok(/冀教版|沪科技版/.test(r.text),
     `栏里出现了别的出版社的版本名（${r.text.slice(0, 50)}）`);
  // 没有对照的概念不该显示这一栏
  await page.evaluate(() => { const q = document.getElementById('q'); q.value = ''; q.dispatchEvent(new Event('input')); });
  await page.click('#q');
  await page.type('#q', '光合作用', { delay: 20 });
  await sleep(400);
  await page.keyboard.press('Enter');
  await sleep(1400);
  const noAlt = await page.evaluate(() => document.getElementById('cAlt').hidden);
  ok(noAlt, '没有对照的概念不显示这一栏（不占地方）');
}

console.log('\n[8d] 配色：点和线的颜色都能选');
{
  await page.click('#tPal');
  await sleep(300);
  ok(await page.evaluate(() => !document.getElementById('pal').hidden), '配色面板能打开');
  const def = await page.evaluate(() => ({
    pc: document.querySelector('#pal [data-pc][aria-pressed="true"]')?.dataset.pc,
    lc: document.querySelector('#pal [data-lc][aria-pressed="true"]')?.dataset.lc,
  }));
  ok(def.pc === 'subject' && def.lc === 'source',
     `默认是 点:学科 / 线:来源（实际 ${def.pc}/${def.lc}）`);

  // 点的配色换维度 → 图例必须跟着换
  await page.click('#pal [data-pc="stage"]');
  await sleep(300);
  const lg = await page.evaluate(() =>
    [...document.querySelectorAll('#legendRows .row')].map(e => e.textContent.trim()));
  ok(lg.length === 3 && lg[0].includes('小学') && lg[2].includes('高中'),
     `点的配色换维度后图例跟着换（${lg.join(' / ')}）`);

  // 线的配色换「方向」→ 脉络里只剩两种颜色（先修 / 后继）
  await page.click('#pal [data-lc="dir"]');
  await sleep(300);
  await page.evaluate(() => { document.getElementById('q').value = ''; });
  await page.type('#q', '二次函数', { delay: 20 });
  await sleep(300);
  await page.keyboard.press('Enter');
  await sleep(1400);
  await page.click('#cMap');
  await sleep(800);
  const cols = await page.evaluate(() =>
    [...new Set([...document.querySelectorAll('#mapSvg .medge')].map(e => e.getAttribute('stroke')))]);
  ok(cols.length === 2, `线按方向着色，只剩两种颜色（先修/后继）（实际 ${cols.length} 种：${cols.join(',')}）`);

  // 记住选择：刷新后还在
  await page.reload({ waitUntil: 'load' });
  await sleep(1200);
  const kept = await page.evaluate(() => ({
    pc: localStorage.getItem('kg.pc'), lc: localStorage.getItem('kg.lc') }));
  ok(kept.pc === 'stage' && kept.lc === 'dir',
     `配色选择被记住了（${kept.pc}/${kept.lc}）`);
  // 复位，免得影响后面的用例
  await page.evaluate(() => { localStorage.setItem('kg.pc','subject');
                               localStorage.setItem('kg.lc','source'); });
}

console.log('\n[9] 跨学段抽检：锥形从底到顶都要能飞准');
{
  // 单验一个节点不算数。锥形底部（小学，半径小、y 很负）和顶部（高中，半径大、y 很正）
  // 是解算的两端，flyTo 算出的 ph 会分别逼近 -1.35 和 +1.35 的钳制边界，容易翻车。
  const probes = ['数数', '三角形', '浮力', '光合作用', '函数', '牛顿第二定律', '电解质'];
  let locked = 0, details = [];
  for (const kw of probes) {
    await page.evaluate(() => { document.getElementById('q').value = ''; document.getElementById('q').dispatchEvent(new Event('input')); });
    await page.type('#q', kw, { delay: 12 });
    await sleep(180);
    const picked = await page.evaluate(() => {
      const it = [...document.querySelectorAll('#res .r')]
        .find(e => e.querySelector('span:nth-child(2)').textContent.trim() === document.getElementById('q').value.trim());
      return !!it;
    });
    if (!picked) { details.push(`${kw}: 搜不到同名节点，跳过`); continue; }
    await page.keyboard.press('Enter');
    await sleep(1500);
    const s = await sampleCenter();
    const hit = s.white > 0;
    if (hit) locked++;
    details.push(`${kw}: 白心 ${s.white} 环 ${s.pink}`);
  }
  ok(locked >= 5, `${locked}/${probes.length} 个节点成功飞正`, details.join('\n      '));
}

console.log('\n[10] 窄屏必须保留搜索，且不能被底部抽屉压住署名');
{
  // 这条断言原来写的是「≤900px 时 #find 隐藏」——它锁定的正是一个错误行为。
  // 当时给的理由是「触屏没键盘」，那句话是错的：点输入框会拉起软键盘。
  // 实测 iPhone 13 上标题区只占 242×149，下面空着 450px，空间从来不是问题；
  // 而 7,938 个点，窄屏用户除了搜索没有任何办法找到知识点。
  await page.setViewport({ width: 390, height: 844, deviceScaleFactor: 1, isMobile: true, hasTouch: true });
  await page.reload({ waitUntil: 'load' });
  await sleep(1200);

  ok(await page.evaluate(() => getComputedStyle(document.getElementById('find')).display !== 'none'),
     '390px 宽时搜索框仍然可见');
  const fs = await page.evaluate(() => parseFloat(getComputedStyle(document.getElementById('q')).fontSize));
  ok(fs >= 16, `输入框字号 ${fs}px ≥ 16px（iOS 更小会强制放大整页）`);

  await page.tap('#q');
  await page.type('#q', '元素周期律', { delay: 15 });
  await sleep(350);
  const n = await page.evaluate(() => document.querySelectorAll('#res .r').length);
  ok(n > 0, `触摸输入出结果 ${n} 条`);
  const rh = await page.evaluate(() => Math.round(Math.min(...[...document.querySelectorAll('#res .r')].map(e => e.getBoundingClientRect().height))));
  ok(rh >= 44, `结果条目高度 ${rh}px ≥ 44px（Apple HIG 的触控下限）`);

  await (await page.$('#res .r')).tap();
  await sleep(1600);
  const g = await page.evaluate(() => {
    const c = document.getElementById('card').getBoundingClientRect();
    const a = document.getElementById('attr').getBoundingClientRect();
    // 署名现在跟着标题走，判据是它不能落在卡片区域里
    const overlaps = !(a.bottom <= c.top || a.top >= c.bottom);
    return { cTop: Math.round(c.top), cBot: Math.round(c.bottom), aTop: Math.round(a.top),
             aBot: Math.round(a.bottom), overlaps, vh: innerHeight };
  });
  ok(g.cBot <= g.vh + 1, `详情卡完整在视口内（${g.cTop}~${g.cBot} / ${g.vh}）`);
  ok(!g.overlaps, `署名（${g.aTop}~${g.aBot}）没被卡片（${g.cTop}~${g.cBot}）盖住`);
  await page.setViewport({ width: 1600, height: 1000, deviceScaleFactor: 1 });
  await sleep(300);
}

console.log('\n[11] 搜索过程中没有新的脚本报错');
ok(errors.length === 0, '全程零 JS 错误', errors.slice(0, 5).join('\n      '));


// ── README 里的测试项数不能烂 ─────────────────────────────────
// 手抄的数字会过期。2026-10-21 同步 README 时就发现「103 项」早就该是 82 项。
// **这条断言只能放在这里**：只有跑完的人才知道真实通过数是多少，
// 数源码里的 ok( 调用行数是不准的（这个文件就有跑不到的分支）。
{
  const rd = readFileSync(resolve(BASE, 'README.md'), 'utf8');
  const want = '| `src/test_search_browser.mjs` | 90 |';
  if (!rd.includes(want)) {
    console.log(`  ✗ README 里的 浏览器 测试项数不是 90`);
    console.log(`      README 里没找到「${want}」`);
    fail++;
  } else {
    console.log(`  ✓ README 里的 浏览器 测试项数是 90（与本次实跑一致）`);
    pass++;
  }
}
await browser.close();
console.log(`\n${'='.repeat(52)}\n通过 ${pass}，失败 ${fail}`);
process.exit(fail ? 1 : 0);
