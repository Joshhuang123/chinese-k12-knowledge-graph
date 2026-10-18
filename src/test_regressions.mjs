/* 回归测试：这一批是**真 bug**，不是风格偏好。
 * 每个都有「修好之前实测复现」和「修好之后实测消失」两份证据。
 * 写在这里是为了以后改代码时它们不会再悄悄回来。
 *
 * 跑法见文件末尾，跑法和 test_search_browser.mjs 一样。
 */
import { createRequire } from 'node:module';
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
  ok(swings === 0, `焦点节点没有来回摆动（横越画面中线 ${swings} 次；每多绕一圈就多一次）`);
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
  ok(/共 [\d,]+ 条匹配/.test(cnt), '命中很多时给出总数（修之前「概念」6574 条只显示 8 行且无提示）');
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

await browser.close();
console.log(`\n${'='.repeat(52)}\n通过 ${pass}，失败 ${fail}`);
process.exit(fail ? 1 : 0);
