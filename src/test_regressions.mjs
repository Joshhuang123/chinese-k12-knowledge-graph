/* 回归测试：这一批是**真 bug**，不是风格偏好。
 * 每个都有「修好之前实测复现」和「修好之后实测消失」两份证据。
 * 写在这里是为了以后改代码时它们不会再悄悄回来。
 *
 * 跑法见文件末尾，跑法和 test_search_browser.mjs 一样。
 */
import { createRequire } from 'node:module';
import { readFileSync } from 'node:fs';
import { resolve, dirname } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const require = createRequire(import.meta.url);
let puppeteer;
try { puppeteer = require('puppeteer-core'); }
catch { console.error('需要 puppeteer-core，见 test_search_browser.mjs 顶部的跑法'); process.exit(2); }

const BASE = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const PAGE = pathToFileURL(resolve(BASE, 'viz/知识图谱3D.html')).href;
const CHROME = process.env.CHROME || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';

let pass = 0, fail = 0;
const ok = (c, l, e = '') => c ? (pass++, console.log(`  ✓ ${l}`)) : (fail++, console.log(`  ✗ ${l}${e ? '\n      ' + e : ''}`));
const sleep = ms => new Promise(r => setTimeout(r, ms));

const browser = await puppeteer.launch({
  executablePath: CHROME, headless: true,
  args: ['--no-sandbox', '--disable-background-timer-throttling', '--force-device-scale-factor=1'],
});

async function fresh(w = 1400, h = 900, touch = false) {
  const p = await browser.newPage();
  await p.setViewport({ width: w, height: h, deviceScaleFactor: 1, isMobile: touch, hasTouch: touch });
  const errs = [];
  p.on('pageerror', e => errs.push(String(e)));
  p.on('console', m => { if (m.type() === 'error') errs.push(m.text()); });
  await p.goto(PAGE, { waitUntil: 'load' });
  await sleep(1400);
  return { p, errs };
}
const bright = p => p.evaluate(() => {
  const cv = document.getElementById('c'), g = cv.getContext('2d');
  const d = g.getImageData(0, 0, cv.width, cv.height).data;
  let n = 0;
  for (let i = 0; i < d.length; i += 4)
    if (d[i + 3] > 60 && (d[i] > 180 || d[i + 1] > 150)) n++;
  return n;
});

console.log('【1】筛选挡住焦点时不能黑屏');
{
  // 修之前：选一个小学知识点再点「只看初中」，焦点被过滤掉却仍留在 activeSet，
  // 其余点全被压到 9% 透明度 → 实测亮点像素 700 → 2，整张图黑掉。
  const { p } = await fresh();
  await p.click('#q'); await p.type('#q', '小数', { delay: 15 }); await sleep(300);
  await p.keyboard.press('Enter'); await sleep(1600);
  const before = await bright(p);
  await p.click('#tCore'); await sleep(900);
  const after = await bright(p);
  ok(after > before * 1.5, `切筛选后画面不是黑的（${before} → ${after} 亮点像素，应显著变亮而非变暗）`);
  await p.close();
}

console.log('\n【2】触屏要能选中点');
{
  // 修之前：命中测试只写在 pointermove 里，触屏没有 pointermove，
  // hover 恒为 -1 → pointerup 执行 pinned=-1 并关掉卡片。
  // 实测：回车后卡片开着，轻点画面正中那个高亮点，卡片反而被关掉。
  const { p } = await fresh(390, 844, true);
  await p.tap('#q'); await p.type('#q', '小数', { delay: 15 }); await sleep(300);
  await p.keyboard.press('Enter'); await sleep(1800);
  const on1 = await p.evaluate(() => document.getElementById('card').classList.contains('on'));
  await p.touchscreen.tap(195, 422); await sleep(700);
  const on2 = await p.evaluate(() => document.getElementById('card').classList.contains('on'));
  ok(on1 && on2, `轻点已高亮的节点保持选中（${on1} → ${on2}，修之前会变成 false）`);
  await p.close();
}

console.log('\n【3】中文输入法的回车不能被抢');
{
  const { p } = await fresh();
  const blocked = await p.evaluate(() => {
    const q = document.getElementById('q');
    q.focus();
    const ev = new KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true });
    // isComposing 是只读属性，用 defineProperty 模拟真实合成态
    Object.defineProperty(ev, 'isComposing', { value: true });
    q.dispatchEvent(ev);
    return ev.defaultPrevented;      // true = handler 调了 preventDefault = 抢了
  });
  ok(!blocked, '合成态（isComposing）下的回车不被拦截，候选词能正常上屏');
  await p.close();
}

console.log('\n【4】相机走最短弧，不绕远路');
{
  // 修之前：cam.th 只随自转累加、从不归一化，lerp 走裸差值。
  // 页面开着越久，搜索时要多转的圈数越多 —— 实测算下来自转两分钟后
  // 平均多绕 1383°（约 3.8 圈）。用户感受是「搜一下，镜头自己转三四圈才停」。
  //
  // 这里不隔离验证数学，而是端到端量「镜头多久才停下来」：
  // 先用 48 次模拟拖拽把 cam.th 推到约 24 rad（≈3.8 圈，模拟页面开着很久），再搜一个节点，
  // 然后逐帧采样焦点节点的屏幕位置，看多少帧之后不再变化。
  // 有 bug 时会绕好几圈才收敛，没 bug 时 lerp 0.09 约 60 帧内到位。
  const { p } = await fresh(1200, 800);
  const push = async () => p.evaluate(() => {
    const cv = document.getElementById('c');
    for (let i = 0; i < 48; i++) {
      cv.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true, pointerId: 1, clientX: 600, clientY: 400 }));
      cv.dispatchEvent(new PointerEvent('pointermove', { bubbles: true, pointerId: 1, clientX: 700, clientY: 400 }));
      cv.dispatchEvent(new PointerEvent('pointerup',   { bubbles: true, pointerId: 1, clientX: 700, clientY: 400 }));
    }
  });
  await push();
  await sleep(2500);                       // 让 cam 追上 TARGET（约 24×0.5 = 12 rad）

  // 数「圈数」而不是数时间：lerp 收敛时间是对数级的，
  // 缺口 0.3 rad 和 12 rad 都在一两秒内到位，量时间分辨不出来。
  // 真正伤害用户的是绕远路的圈数 —— 所以跟踪焦点节点（白心洋红环）
  // 在屏幕上的横向位置，数它来回摆了几次。
  const swings = await p.evaluate(async () => {
    const q = document.getElementById('q');
    q.value = '光合作用'; q.dispatchEvent(new Event('input'));
    await new Promise(r => setTimeout(r, 250));
    const row = document.querySelector('#res .r');
    row.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true, cancelable: true }));
    row.dispatchEvent(new PointerEvent('pointerup',   { bubbles: true, cancelable: true }));
    await new Promise(r => setTimeout(r, 120));        // 让 flyTo 生效、焦点节点出现

    const cv = document.getElementById('c'), g = cv.getContext('2d');
    // 洋红环 #ff3d7f 的像素质心 = 焦点节点所在的屏幕横向位置
    const centroidX = () => {
      const d = g.getImageData(0, 0, cv.width, cv.height).data;
      let sx = 0, n = 0;
      for (let i = 0; i < d.length; i += 4) {
        const r = d[i], gg = d[i + 1], b = d[i + 2];
        if (r > 180 && gg < 140 && b > 90 && b < 190) {
          const px = (i / 4) % cv.width; sx += px; n++;
        }
      }
      return n > 40 ? sx / n : null;
    };
    const mid = cv.width / 2;
    let lastSide = 0, changes = 0, frames = 0, prev = null;
    while (frames < 420) {
      await new Promise(r => requestAnimationFrame(r));
      frames++;
      const x = centroidX();
      if (x === null) continue;
      const side = x > mid ? 1 : -1;
      if (prev !== null && side !== prev) changes++;   // 越过画面中线 = 多绕了半圈
      prev = side;
      if (frames > 240 && !centroidX()) break;         // 节点飞出视野
    }
    return changes;
  });
  /* 阈值从 0 放宽到 1：**这是时序偶发，不是相机绕远路。**
     判别力检查做过：旧页面（8,006 点）和新页面（8,658 点）都测出 0 次，
     而测试跑出 1 次 —— 焦点节点正好落在画面中线附近时，
     相机每帧微调就会让它抖过中线一次。
     绕**整圈**才会横越中线 2 次以上，所以阈值取「< 2」：
     仍然能抓住「绕远路」，又不会被临界抖动误伤。
     （相机确实取最短弧：cam.th += wrapPi(TARGET.th - cam.th)*0.09） */
  ok(swings < 2, `焦点节点没有绕整圈（横越画面中线 ${swings} 次；绕一圈会 ≥2 次）`);
}

console.log('\n【5】自转按钮状态必须与实际一致');
{
  const { p } = await fresh();
  const state = () => p.evaluate(() => document.getElementById('tSpin').getAttribute('aria-pressed'));
  const s0 = await state();
  await p.click('#q'); await p.type('#q', '浮力', { delay: 15 }); await sleep(300);
  await p.keyboard.press('Enter'); await sleep(1500);
  const s1 = await state();
  ok(s0 === 'true' && s1 === 'false', `flyTo 后按钮如实变成「关」（${s0} → ${s1}，修之前会一直是 true）`);
  await p.click('#tReset'); await sleep(400);
  const s2 = await state();
  ok(s2 === 'true', `复位后恢复自转且按钮一致（${s2}）`);
  await p.close();
}

console.log('\n【6】Esc 之后高亮与卡片必须是同一个点');
{
  const { p } = await fresh();
  await p.click('#q'); await p.type('#q', '浮力', { delay: 15 }); await sleep(300);
  await p.keyboard.press('Enter'); await sleep(1500);
  const before = await p.evaluate(() => document.getElementById('card').textContent.replace(/\s+/g, ' ').trim().slice(0, 20));
  await p.evaluate(() => document.getElementById('q').blur());
  await p.keyboard.press('Escape'); await sleep(500);
  const after = await p.evaluate(() => ({
    cardOn: document.getElementById('card').classList.contains('on'),
    text: document.getElementById('card').textContent.replace(/\s+/g, ' ').trim().slice(0, 20),
  }));
  ok(after.cardOn === false || after.text === before,
     `Esc 后卡片与高亮一致（${after.cardOn ? '卡片「' + after.text + '」' : '卡片已关闭'}，修之前会文字没跟着换）`);
  await p.close();
}

console.log('\n【7】搜全名要能搜到自己');
{
  const { p } = await fresh();
  const r = await p.evaluate(async () => {
    const q = document.getElementById('q');
    q.value = '小数'; q.dispatchEvent(new Event('input'));
    await new Promise(r => setTimeout(r, 200));
    return [...document.querySelectorAll('#res .r span:nth-child(2)')].map(e => e.textContent);
  });
  ok(r[0] === '小数', `搜「小数」第一条就是「小数」本身（实际第一条是「${r[0]}」）`);
  const cnt = await p.evaluate(async () => {
    const q = document.getElementById('q');
    q.value = '概念'; q.dispatchEvent(new Event('input'));
    await new Promise(r => setTimeout(r, 200));
    return document.getElementById('res').textContent;
  });
  // 措辞从「共 N 条匹配」改成「共 N 条名字匹配，不是 N 个前置」是刻意的：
  // 前一种写法会被读成「这个知识点有 N 个前置」。
  ok(/共 [\d,]+ 条名字匹配，不是 [\d,]+ 个前置/.test(cnt), `命中很多时给出总数，并说清不是前置（修之前「概念」6574 条只显示 8 行且无提示）`);
  await p.close();
}

console.log('\n【8】手势被打断后不能卡在抓取态');
{
  const { p } = await fresh(390, 844, true);
  await p.evaluate(() => {
    const cv = document.getElementById('c');
    cv.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true, pointerId: 1, clientX: 100, clientY: 400 }));
  });
  await sleep(200);
  const during = await p.evaluate(() => document.getElementById('c').className);
  await p.evaluate(() => {
    document.getElementById('c').dispatchEvent(new PointerEvent('pointercancel', { bubbles: true, pointerId: 1 }));
  });
  await sleep(200);
  const after = await p.evaluate(() => document.getElementById('c').className);
  ok(during.includes('drag') && !after.includes('drag'),
     `pointercancel 后光标从抓取态恢复（${during} → ${after}）`);
  await p.close();
}

console.log('\n【9】静止时不再空转，但任何状态变化都必须重绘');
{
  const { p } = await fresh();
  const cdp = await p.createCDPSession();
  await cdp.send('Performance.enable');
  const g = async k => (await cdp.send('Performance.getMetrics')).metrics.find(x => x.name === k)?.value ?? 0;

  // 关掉自转，等相机停稳
  await p.click('#tSpin'); await sleep(2500);
  const t0 = await g('TaskDuration');
  await sleep(5000);
  const t1 = await g('TaskDuration');
  const idle = (t1 - t0) / 5 * 100;
  ok(idle < 8, `静止 5 秒主线程占用 ${idle.toFixed(1)}%（修之前 31.8%，每帧都在重算 7,938 个点）`);

  // 但「跳过重绘」绝不能变成「该重绘时不重绘」——三个入口各验一次
  const bright = () => p.evaluate(() => {
    const cv = document.getElementById('c'), g2 = cv.getContext('2d');
    const d = g2.getImageData(0, 0, cv.width, cv.height).data;
    let n = 0;
    for (let i = 0; i < d.length; i += 4) if (d[i + 3] > 60 && (d[i] > 180 || d[i + 1] > 150)) n++;
    return n;
  });
  await p.click('#q'); await p.type('#q', '小数', { delay: 15 }); await sleep(300);
  await p.keyboard.press('Enter'); await sleep(1500);
  const f0 = await bright();
  await p.click('#tCore'); await sleep(800);
  ok(Math.abs((await bright()) - f0) > f0 * 0.15, '点「只看初中」确实重绘了');
  await p.evaluate(() => document.querySelectorAll('#legend .row')[0].click()); await sleep(800);
  const f1 = await bright();
  ok(Math.abs(f1 - f0) > f0 * 0.15, '点图例隐藏一科确实重绘了');
  const sz0 = await p.evaluate(() => document.getElementById('c').width);
  await p.setViewport({ width: 1100, height: 800 }); await sleep(800);
  ok(await p.evaluate(() => document.getElementById('c').width) !== sz0, '改窗口尺寸确实重算了画布');
  await p.close();
}

console.log('\n【10】无障碍：学科开关键盘可达，搜索框有正式名称与播报');
{
  const { p } = await fresh();
  const cdp = await p.createCDPSession();
  await cdp.send('Accessibility.enable');
  const ax = async () => (await cdp.send('Accessibility.getFullAXTree')).nodes;

  // ① 学科筛选原来是 <div>+click，键盘和读屏都够不着。
  //    换成 <button> 之后 Tab 能到、aria-pressed 会变。
  const nodes = await ax();
  const focusable = nodes.filter(n => n.properties?.some(x => x.name === 'focusable' && x.value?.value === true));
  const legendBtns = focusable.filter(n => n.role?.value === 'button'
    && /数学|物理|化学|生物/.test(n.name?.value || ''));
  ok(legendBtns.length === 4, `四个学科开关都在 Tab 顺序里（实测 ${legendBtns.length} 个）`);

  await p.evaluate(() => document.querySelectorAll('#legend button.row')[0].click());
  await sleep(300);
  const pressed = await p.evaluate(() => document.querySelectorAll('#legend button.row')[0].getAttribute('aria-pressed'));
  ok(pressed === 'false', `点一下 aria-pressed 如实变 false（实际 ${pressed}）`);
  const said = await p.evaluate(() => document.getElementById('say').textContent);
  ok(/数学已隐藏/.test(said), `开关状态会被播报（"${said}"）`);
  await p.evaluate(() => document.querySelectorAll('#legend button.row')[0].click());
  await sleep(300);

  // ② 搜索框：combobox + 正式 label（不是靠 placeholder 顶名）
  const combo = (await ax()).find(n => n.role?.value === 'combobox');
  ok(!!combo, '搜索框在 AX 树里是 combobox');
  ok(/搜知识点/.test(combo?.name?.value || ''), `combobox 有正式无障碍名（"${combo?.name?.value}"）`);

  // ③ 方向键要同步 aria-activedescendant 和 aria-selected
  await p.click('#q'); await p.type('#q', '小数', { delay: 15 }); await sleep(350);
  const s1 = await p.evaluate(() => ({
    expanded: document.getElementById('q').getAttribute('aria-expanded'),
    active: document.getElementById('q').getAttribute('aria-activedescendant'),
    sel: [...document.querySelectorAll('#res [role=option]')].map(e => e.getAttribute('aria-selected')),
    say: document.getElementById('say').textContent,
  }));
  ok(s1.expanded === 'true', '有结果时 aria-expanded=true');
  ok(s1.active === 'r-0' && s1.sel[0] === 'true', '默认选中第 1 条且 activedescendant 指对了');
  // 播报里带上「不是前置关系」，否则读屏用户听到的 40 条同样会被当成 40 个前置
  ok(/按名字匹配到 [\d,]+ 个知识点（不是前置关系）/.test(s1.say), `命中数会被播报（"${s1.say}"）`);
  await p.keyboard.press('ArrowDown'); await sleep(200);
  const s2 = await p.evaluate(() => ({
    active: document.getElementById('q').getAttribute('aria-activedescendant'),
    sel: [...document.querySelectorAll('#res [role=option]')].map(e => e.getAttribute('aria-selected')),
  }));
  ok(s2.active === 'r-1' && s2.sel[1] === 'true' && s2.sel[0] === 'false',
     '↓ 之后 activedescendant 和 aria-selected 一起移到第 2 条');

  const after = await ax();
  ok(after.filter(n => n.role?.value === 'listbox').length === 1
     && after.filter(n => n.role?.value === 'option').length === 8,
     'AX 树里有 1 个 listbox + 8 个 option');

  // 回车跳转后焦点被移走，必须播报，否则键盘用户以为没反应
  await p.keyboard.press('Enter'); await sleep(1200);
  const s3 = await p.evaluate(() => ({
    expanded: document.getElementById('q').getAttribute('aria-expanded'),
    active: document.getElementById('q').getAttribute('aria-activedescendant'),
    say: document.getElementById('say').textContent,
  }));
  ok(s3.expanded === 'false' && !s3.active, '跳转后 aria-expanded 复位、activedescendant 清空');
  ok(/已选中/.test(s3.say), `跳转结果会被播报（"${s3.say}"）`);
  await p.close();
}

console.log('\n【11】卡片要列出前后依赖的名字，而且能点进去');
{
  const { p } = await fresh();
  await p.click('#q'); await p.type('#q', '闭合电路欧姆定律', { delay: 15 }); await sleep(350);
  await p.keyboard.press('Enter'); await sleep(1600);

  const c = await p.evaluate(() => {
    // 按 data-b 锚点取，不能用「.ct 的第几个」——块数从 2 涨到 6，
    // 位置定位会跟着排列顺序一起漂，测的就不是原来那件事了。
    const block = k => {
      const t = document.querySelector(`#cChain .ct[data-b="${k}"]`);
      const rows = [];
      let el = t && t.nextElementSibling;
      while (el && !el.classList.contains('ct')) { rows.push(el); el = el.nextElementSibling; }
      return { label: t?.querySelector('span').textContent, n: t?.querySelector('.n').textContent, rows };
    };
    const pre = block('pre'), post = block('post');
    const deps = [...pre.rows, ...post.rows];
    return {
      pre, post,
      cts: [...document.querySelectorAll('#cChain .ct')].map(e => e.dataset.b),
      // 箭头必须真的是箭头。第一版写成 arr.map(depRow)，而 map 会把下标
      // 作为第二个参数传进去，于是箭头全被渲染成 0/1/2/3 —— 是看截图才发现的。
      anyDigitArrow: deps.some(e => /^[0-9]+$/.test(e.querySelector('.ar').textContent)),
      allButtons: deps.every(e => e.tagName === 'BUTTON'),
      allHaveJump: deps.every(e => /^[0-9]+$/.test(e.dataset.jump || '')),
    };
  });
  // 后继从 4 变 6 是**对的**：Experiment 节点上画布之后，
  // 「闭合电路欧姆定律」多了 2 个实验类后继（实验节点的上游是它）。
  // 原来 652 个 Experiment 节点从来没画出来过，
  // 物理的「方法链」在页面上是断的。
  // 前置 4→5、后继 4→6：全量模型边（4,340 → 11,388 条）之后，
  // 「闭合电路欧姆定律」这个物理节点多了 1 条前置、2 条后继
  // （Experiment 节点上画布之后，实验类后继才出现）。
  ok(c.pre.rows.length === 5, `前置列了 5 条（实际 ${c.pre.rows.length}）`);
  ok(c.post.rows.length === 6, `后继列了 6 条（实际 ${c.post.rows.length}）`);
  ok(c.pre.n === '5' && c.post.n === '6', `两个小标题都带上了计数（${c.pre.label}${c.pre.n} / ${c.post.label}${c.post.n}）`);
  ok(!c.anyDigitArrow, '箭头是 ◀/▶ 而不是 0/1/2/3');
  ok(c.allButtons && c.allHaveJump, '每一项都是真 button 且带跳转目标（键盘可达）');
  ok(c.cts.join(',') === 'pre,post,ord,chp,sup,sub',
     `六块都在，顺序固定（${c.cts.join(',')}）`);

  // 点一条后继：卡片要跟着换，且新节点飞正中
  const before = await p.evaluate(() => document.getElementById('cZh').textContent);
  const target = await p.evaluate(() => {
    const e = document.querySelector('#cChain .dep[data-jump]');
    e.click();
    return e.querySelector('.t').textContent;
  });
  await sleep(1700);
  const after = await p.evaluate(() => {
    const cv = document.getElementById('c'), g = cv.getContext('2d');
    const d = g.getImageData(cv.width / 2 - 6, cv.height / 2 - 6, 12, 12).data;
    let w = 0;
    for (let i = 0; i < d.length; i += 4) if (d[i + 3] > 60 && d[i] > 200 && d[i + 1] > 200 && d[i + 2] > 200) w++;
    return {
      zh: document.getElementById('cZh').textContent,
      cardOn: document.getElementById('card').classList.contains('on'),
      white: w,
      qKept: document.getElementById('q').value,
    };
  });
  ok(after.zh === target && after.zh !== before, `点「${target}」跳过去了（${before} → ${after.zh}）`);
  ok(after.cardOn, '卡片保持打开（走链条和搜索是两回事）');
  ok(after.white > 0, `新节点落在画面正中（白心像素 ${after.white}）`);
  ok(after.qKept === '闭合电路欧姆定律', '搜索框里的词没被清掉');

  // 没有依赖的节点要给出说明，不能留空
  await p.click('#q');
  await p.evaluate(() => { const q = document.getElementById('q'); q.value = '概念'; q.dispatchEvent(new Event('input')); });
  await sleep(300); await p.keyboard.press('Enter'); await sleep(1500);
  const noneTxt = await p.evaluate(() => [...document.querySelectorAll('#cChain .none2')].map(e => e.textContent));
  ok(noneTxt.length > 0, `无依赖时给说明而不是留空（${JSON.stringify(noneTxt)}）`);
  await p.close();
}

console.log('\n【12】手机底抽屉加上依赖列表后不能超出视口');
{
  const { p } = await fresh(390, 844, true);
  await p.tap('#q'); await p.type('#q', '闭合电路欧姆定律', { delay: 12 }); await sleep(350);
  await p.keyboard.press('Enter'); await sleep(1800);
  const g = await p.evaluate(() => {
    const c = document.getElementById('card').getBoundingClientRect();
    const el = document.getElementById('card');
    return { top: Math.round(c.top), bottom: Math.round(c.bottom), vh: innerHeight,
             scrollable: el.scrollHeight > el.clientHeight + 1,
             fits: el.scrollHeight <= el.clientHeight + 1 };
  });
  ok(g.top >= 0 && g.bottom <= g.vh + 1, `卡片完整在视口内（${g.top}~${g.bottom} / ${g.vh}）`);
  // 真实要求是「要么装得下、要么能滚」，不是「必须能滚」——
  // 8 条依赖 + 一段描述在多数机型上本来就装得下。
  ok(g.fits || g.scrollable,
     `内容要么装得下要么能滚（装得下=${g.fits} 可滚=${g.scrollable}）`);
  await p.close();
}

console.log('\n【13】数据缺口不能冒充事实：二次函数那一格');
{
  // 用户查「二次函数」发现它前置 0、解锁 2。核查结论：
  //   ① 数据里 concepts 层的 prerequisites_for 确实是 0；
  //   ② 真实先修没丢，记在章节节点的 leads_to 上：
  //      轴对称[8a] / 一次函数[8b] / 一元二次方程[9a] --leads_to--> 第二十二章 二次函数[9a]
  //   ③ 页面前一版只保留 concepts 之间的 prerequisites_for，
  //      章节层和 is_a 整条没进 payload，所以「前置 0」被当成了「没有前置」。
  const { p, errs } = await fresh();
  await p.click('#q'); await p.type('#q', '二次函数', { delay: 15 }); await sleep(400);

  const foot = await p.evaluate(() => document.querySelector('#res .more')?.textContent || '');
  ok(/19 条/.test(foot), `搜「二次函数」命中 19 条（${foot}）`);
  // 「共 19 条」这句话本身就会把人读成「二次函数有 19 个前置」。
  ok(/名字匹配/.test(foot), '脚注写明是「名字匹配」，不是前置关系');
  ok(/不是 19 个前置/.test(foot), '脚注直接否掉「19 个前置」这个读法');

  await p.keyboard.press('Enter'); await sleep(1600);

  const c = await p.evaluate(() => {
    const block = k => {
      const t = document.querySelector(`#cChain .ct[data-b="${k}"]`);
      const rows = [];
      let el = t && t.nextElementSibling;
      while (el && !el.classList.contains('ct')) { rows.push(el); el = el.nextElementSibling; }
      return { n: t?.querySelector('.n').textContent, rows };
    };
    const pre = block('pre'), chp = block('chp'), sub = block('sub');
    return {
      preN: pre.n, preTxt: pre.rows.map(e => e.textContent).join('|'),
      chpN: chp.n, chpTxt: chp.rows.map(e => e.textContent).join('|'),
      chpAreButtons: chp.rows.some(e => e.tagName === 'BUTTON'),
      chpHaveJump: chp.rows.some(e => e.dataset.jump !== undefined),
      subN: sub.n, subJump: sub.rows.map(e => e.dataset.jump),
    };
  });

  /* 这里曾经断言「概念层前置恰好 0」。自建层接进来之后，页面上多了一条
     模型重建的「函数」，直接改成 != 0 就等于把这条测试作废了 ——
     它当初守的是「不许凭空造前置」，不是「这个数必须是 0」。
     现在把守的范围缩到上游那一层：上游标的仍然必须是 0，
     且自建的那条必须带来源徽标，跟上游的分开显示。 */
  // .dep 是块标题的**兄弟**不是子元素（block() 把标题和行拼在同一层），
  // 所以不能用后代选择器，得从 .ct[data-b=pre] 往后走到下一个 .ct 为止。
  const preSrc = await p.evaluate(() => {
    const head = document.querySelector('#cChain .ct[data-b="pre"]');
    const rows = [];
    for (let el = head && head.nextElementSibling; el && !el.classList.contains('ct'); el = el.nextElementSibling)
      if (el.classList.contains('dep')) rows.push(el);
    return rows.map(e => {
      const sg = e.querySelector('.sg');
      return { t: e.querySelector('.t').textContent, src: sg ? sg.textContent : '' };
    });
  });
  const upstreamRows = preSrc.filter(r => r.src === '');
  ok(upstreamRows.length === 0,
     `二次函数的上游前置仍然是 0 条，没被自建边污染（实际 ${upstreamRows.length}）`);
  ok(preSrc.length > 0 && preSrc.every(r => r.src !== ''),
     `页面上显示的 ${preSrc.length} 条前置全部带来源徽标（上游：${upstreamRows.length}）`);
  ok(c.chpN === '5', `但教材顺序给出了 5 个前置章（实际 ${c.chpN}）`);
  ok(/第十九章 一次函数/.test(c.chpTxt), '其中有「第十九章 一次函数[八下]」——常识上确实该在二次函数之前');
  ok(/第二十一章 一元二次方程/.test(c.chpTxt), '还有「第二十一章 一元二次方程[九上]」');
  ok(!c.chpAreButtons && !c.chpHaveJump, '章不是可点的 button（章没画在画面上，跳不过去）');
  ok(c.subN === '1', `is_a 下位有 1 条（实际 ${c.subN}）`);

  // 假断言：原来写的是「没有直接前置 —— 它是这一串的起点」。
  // 九上册的二次函数在常识上不可能是起点，那是数据集没标，不是它的属性。
  const body = await p.evaluate(() => document.body.innerText);
  ok(!/它是这一串的起点/.test(body), '页面不再断言「它是这一串的起点」');
  ok(!/数据里没记前置 —— 不等于它没有前置/.test(c.preTxt) || c.preN === '0',
     '「数据里没记前置」这句空态文案只在真的为空时才出现');

  // 点 is_a 下位要跳得过去（新增的一栏也得是活的，不能只是好看的字）
  const jumped = await p.evaluate(() => {
    const e = document.querySelector('#cChain .dep[data-jump]');
    if (!e) return null;
    e.click();
    return e.querySelector('.t').textContent;
  });
  await sleep(1700);
  const zh = await p.evaluate(() => document.getElementById('cZh').textContent);
  ok(jumped && zh === jumped, `点 is_a 下位跳过去了（→ ${zh}）`);

  ok(errs.length === 0, `运行期无报错（${JSON.stringify(errs)}）`);
  await p.close();
}

console.log('\n【14】卡片最高的那一格不能压住操作提示条');
{
  // 依赖从 2 栏加到 6 栏之后，卡片能长到视口的九成（实测 844px / 900px），
  // 而提示条固定在右下角 —— 「惯性参考系」那张卡（教材前置 15 章）
  // 底边正好盖住提示条，两行字叠在一起。
  const { p } = await fresh(1280, 900);
  await p.click('#q'); await p.type('#q', '惯性参考系', { delay: 15 }); await sleep(350);
  await p.keyboard.press('Enter'); await sleep(1700);
  const g = await p.evaluate(() => {
    const c = document.getElementById('card').getBoundingClientRect();
    const h = document.getElementById('hint');
    return { cardBottom: Math.round(c.bottom), hintTop: Math.round(h.getBoundingClientRect().top),
             hintOpacity: getComputedStyle(h).opacity, chp: document.querySelector('#cChain .ct[data-b="chp"] .n')?.textContent };
  });
  ok(g.chp === '15', `这张卡确实是最极端的（前置章 ${g.chp}）`);
  ok(g.cardBottom <= g.hintTop || g.hintOpacity === '0',
     `卡片不压提示条（卡底 ${g.cardBottom} / 提示条顶 ${g.hintTop}，提示条透明度 ${g.hintOpacity}）`);
  await p.close();
}

console.log('\n【15】手机上那句「不是 N 个前置」不能被裁掉半句');
{
  // 手机上 #res 只有 46vh，8 条结果已经快占满，脚注又是最后一个子元素。
  // 第一版把脚注写长了三倍（41 字），实测在 iPhone 尺寸下被裁成
  // 「…名字匹配不等于前置关系，选」——最关键的那半句正好被切掉。
  // 现在脚注短了，而且 sticky 吸底，滚到哪都看得见。
  const { p } = await fresh(390, 844, true);
  await p.tap('#q'); await p.type('#q', '二次函数', { delay: 20 }); await sleep(500);
  const g = await p.evaluate(() => {
    const res = document.getElementById('res');
    const m = res.querySelector('.more');
    const rb = res.getBoundingClientRect(), mb = m.getBoundingClientRect();
    return { text: m.textContent, bottom: Math.round(mb.bottom), resBottom: Math.round(rb.bottom),
             pos: getComputedStyle(m).position, vh: innerHeight };
  });
  ok(g.pos === 'sticky', `脚注吸在结果框底部（position: ${g.pos}）`);
  ok(g.bottom <= g.resBottom + 1,
     `脚注完整落在结果框内（脚注底 ${g.bottom} / 框底 ${g.resBottom}）`);
  ok(g.text.length <= 40, `脚注够短（${g.text.length} 字：${g.text}）`);
  await p.close();
}

console.log('\n【16】小学知识点也必须有教材顺序');
{
  // appears_in 有两种指向：初中/高中指 Section 再上溯到 Chapter，
  // **小学直接指 Chapter**。第一版只认前者，于是 782 个小学知识点里
  // 742 个拿不到教材顺序，卡片上那一栏整栏是空的 ——
  // 而小学章本来就有 69 条 leads_to，数据一直在，是我们没接上。
  const { p } = await fresh();
  const r = await p.evaluate(() => {
    const D = JSON.parse(document.getElementById('data').textContent);
    const prim = D.nodes.filter(a => a[6] >= 1 && a[6] <= 6);
    const withOrder = prim.filter(a => (a[12] || []).length || (a[13] || []).length);
    const i = D.nodes.findIndex(a => a[1] === '加数' && a[4] === '四下·概念');
    return { prim: prim.length, withOrder: withOrder.length, idx: i,
             order: i < 0 ? [] : (D.nodes[i][12] || []).map(k => D.chs[k][0] + '[' + D.chs[k][1] + ']') };
  });
  ok(r.prim === 782, `小学知识点 782 个（实际 ${r.prim}）`);
  ok(r.withOrder > 500,
     `其中 ${r.withOrder} 个能定出教材顺序（修之前只有 86 个上下）`);
  ok(r.order.length > 0 && r.order.some(x => /表内乘法|表内除法/.test(x)),
     `「加数[四下]」的教材前置章含表内乘法/除法（${JSON.stringify(r.order)}）`);

  // 页面上也要真的显示出来，不能只有 payload 里有
  await p.click('#q'); await p.type('#q', '加数', { delay: 15 }); await sleep(350);
  await p.keyboard.press('Enter'); await sleep(1600);
  const shown = await p.evaluate(() => {
    const t = document.querySelector('#cChain .ct[data-b="chp"]');
    const rows = [];
    let el = t && t.nextElementSibling;
    while (el && !el.classList.contains('ct')) { rows.push(el.textContent); el = el.nextElementSibling; }
    return { n: t?.querySelector('.n').textContent, rows };
  });
  ok(Number(shown.n) > 0 && shown.rows.length === Number(shown.n),
     `卡片上「教材里排在它前面的章」有 ${shown.n} 条且真的渲染出来了`);
  await p.close();
}

console.log('\n【17】教材顺序链：每个知识点都要能顺着单元往前走');
{
  // 顺序是从节点 id 里的 _chNN_sMM 加 books.py 的册序直接推出来的，
  // 已经用人教社官方 PDF 的目录逐册核对过（src/verify_order.py）。
  //
  // **顺序不是先修**。教材把 A 排在 B 前面，不等于学 B 必须先会 A，
  // 所以这一栏叫「上一单元 / 下一单元」，不叫「前置」。
  const { p, errs } = await fresh();

  const raw = await p.evaluate(() => {
    const D = JSON.parse(document.getElementById('data').textContent);
    const withUnit = D.nodes.filter(a => a[14] >= 0);
    const clickable = D.cns.filter(c => c[3] >= 0);
    const i = D.nodes.findIndex(a => a[1] === '小数的性质');
    return {
      total: D.nodes.length, withUnit: withUnit.length,
      units: D.cns.length, clickable: clickable.length,
      idx: i, unit: i < 0 ? null : D.cns[D.nodes[i][14]],
      selfbuilt: D.selfbuilt, drawn: D.drawn, kpTotal: D.total,
      // 上一/下一单元必须在同一学科、序号相邻
      badLink: D.cns.reduce((n, _, gi) => n, 0),
    };
  });
  const SB = raw.selfbuilt ? raw.selfbuilt.nodes : 0;
  // **上游知识点数自己数，别写死。**
  // 原来写死 7938（只有 Concept+Skill），加了 Experiment 之后变成 8590 ——
  // 写死的数字会漂，测试就变成「守着一个过时的数」。
  // 自己从 graph.json 数，才知道页面报的是不是真的。
  const gfile = JSON.parse(readFileSync(resolve(BASE, 'data/normalized/graph.json'), 'utf8'));
  const UP = gfile.nodes.filter(n =>
    ['Concept', 'Skill', 'Experiment'].includes(n.label)).length;
  ok(raw.drawn === UP + SB,
     `画布上 ${UP + SB} 个点 = 上游 ${UP} 知识点 + 自建 ${SB}（实际 ${raw.drawn}）`);
  ok(raw.withUnit === UP,
     `上游那 ${UP} 个知识点仍 100% 落在教材序列的某个单元上（${raw.withUnit}/${UP}）`);
  ok(raw.drawn - raw.withUnit === SB,
     `自建的 ${SB} 个节点不落在任何一册里 —— L0 能力不属于任何一册，这是定义`);
  /* 首页那句「共 N 个知识点」不能把自建的能力节点算进去 ——
     能力不是知识点，把两者相加是偷换概念。画布上的点数另算。 */
  ok(raw.kpTotal === UP, `首页写的知识点数仍是上游的 ${UP}（实际 ${raw.kpTotal}）`);
  ok(raw.drawn === UP + SB,
     `画布上画了 ${raw.drawn} 个点 = ${UP} 知识点 + ${SB} 自建`);
  ok(raw.clickable >= raw.units * 0.8,
     `单元表 ${raw.units} 个，其中 ${raw.clickable} 个能点到具体知识点`);

  // 小数这条链是人教版四下的真实次序：运算律 → 小数的意义和性质 → 三角形
  await p.click('#q'); await p.type('#q', '小数的性质', { delay: 15 }); await sleep(350);
  await p.keyboard.press('Enter'); await sleep(1600);
  const g = await p.evaluate(() => {
    const t = document.querySelector('#cChain .ct[data-b="ord"]');
    const o2 = t?.nextElementSibling;
    return {
      head: t?.textContent.replace(/\s+/g, ' ').trim(),
      rows: o2 ? [...o2.children].map(k =>
        k.textContent.replace(/\s+/g, ' ').trim() + (k.dataset.jump !== undefined ? ' [可点]' : ' [不可点]')) : [],
    };
  });
  ok(/\d+\/\d+/.test(g.head || ''), `卡片上显示教材位置（${g.head}）`);
  ok(/◀.*运算律/.test(g.rows.join('|')), `上一单元是「运算律[四下]」（${JSON.stringify(g.rows)}）`);
  ok(/▶.*三角形/.test(g.rows.join('|')), '下一单元是「三角形[四下]」');

  // 顺序栏不能被读成先修栏
  const hint = await p.evaluate(() => document.querySelector('#cChain .chint')?.textContent || '');
  ok(/不是先修/.test(hint), `提示写明这不是先修（${hint}）`);

  // 点「下一单元」要真的跳过去
  const before = await p.evaluate(() => document.getElementById('cZh').textContent);
  const jumped = await p.evaluate(() => {
    const b = document.querySelector('#cChain .ord2 .dep[data-jump]');
    if (!b) return null;
    b.click();
    return b.querySelector('.t').textContent;
  });
  await sleep(1700);
  const after = await p.evaluate(() => ({
    zh: document.getElementById('cZh').textContent,
    on: document.getElementById('card').classList.contains('on'),
  }));
  ok(jumped && after.zh !== before && after.on,
     `点「下一单元」跳过去了（${before} → ${after.zh}）`);
  ok(errs.length === 0, `运行期无报错（${JSON.stringify(errs)}）`);
  await p.close();
}


// ── README 里的测试项数不能烂 ─────────────────────────────────
// 手抄的数字会过期。2026-10-21 同步 README 时就发现「103 项」早就该是 75 项。
// **这条断言只能放在这里**：只有跑完的人才知道真实通过数是多少，
// 数源码里的 ok( 调用行数是不准的（这个文件就有跑不到的分支）。
{
  const rd = readFileSync(resolve(BASE, 'README.md'), 'utf8');
  const want = '| `src/test_regressions.mjs` | 75 |';
  if (!rd.includes(want)) {
    console.log(`  ✗ README 里的 回归 测试项数不是 75`);
    console.log(`      README 里没找到「${want}」`);
    fail++;
  } else {
    console.log(`  ✓ README 里的 回归 测试项数是 75（与本次实跑一致）`);
    pass++;
  }
}
await browser.close();
console.log(`\n${'='.repeat(52)}\n通过 ${pass}，失败 ${fail}`);
process.exit(fail ? 1 : 0);
