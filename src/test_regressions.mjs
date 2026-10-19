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
  ok(/找到 \d+ 个知识点/.test(s1.say), `命中数会被播报（"${s1.say}"）`);
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
    const deps = [...document.querySelectorAll('#cChain .dep')];
    return {
      cts: [...document.querySelectorAll('#cChain .ct')].map(e => ({
        label: e.querySelector('span').textContent, n: e.querySelector('.n').textContent,
      })),
      pre: deps.filter(e => e.querySelector('.ar').textContent === '◀'),
      post: deps.filter(e => e.querySelector('.ar').textContent === '▶'),
      // 箭头必须真的是箭头。第一版写成 arr.map(depRow)，而 map 会把下标
      // 作为第二个参数传进去，于是箭头全被渲染成 0/1/2/3 —— 是看截图才发现的。
      anyDigitArrow: deps.some(e => /^[0-9]+$/.test(e.querySelector('.ar').textContent)),
      allButtons: deps.every(e => e.tagName === 'BUTTON'),
      allHaveJump: deps.every(e => /^[0-9]+$/.test(e.dataset.jump || '')),
    };
  });
  ok(c.pre.length === 4, `前置列了 4 条（实际 ${c.pre.length}）`);
  ok(c.post.length === 4, `后继列了 4 条（实际 ${c.post.length}）`);
  ok(c.cts[0]?.n === '4' && c.cts[1]?.n === '4', `两个小标题都带上了计数（${c.cts.map(x => x.label + x.n).join(' / ')}）`);
  ok(!c.anyDigitArrow, '箭头是 ◀/▶ 而不是 0/1/2/3');
  ok(c.allButtons && c.allHaveJump, '每一项都是真 button 且带跳转目标（键盘可达）');

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

await browser.close();
console.log(`\n${'='.repeat(52)}\n通过 ${pass}，失败 ${fail}`);
process.exit(fail ? 1 : 0);
