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

await browser.close();
console.log(`\n${'='.repeat(52)}\n通过 ${pass}，失败 ${fail}`);
process.exit(fail ? 1 : 0);
