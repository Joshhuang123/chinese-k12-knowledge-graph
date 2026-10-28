#!/usr/bin/env node
// tts.js —— 串行 TTS，指数退避，参数走 --args-file
//
//   node tts.js <sentences.json> <audio_dir>
//
// 为什么串行：上游限流严重，批量并发必吃 429，宁可慢。
// 为什么退避：attempt * 5 秒，最多重试 6 次。
// 为什么 --args-file：绕开 shell 转义，中文和括号音色名都不需要手工转义。

const fs = require('fs');
const os = require('os');
const path = require('path');
const { execFileSync } = require('child_process');

const VOICE = 'Chinese (Mandarin)_Reliable_Executive';
// 限流很重：**吃 429 用固定 30 秒心跳**，不用 attempt*5 的指数退避
// （越打越碎，11l 实测）。重试放到 80 次（每句最多约 40 分钟）。
const MAX_RETRY = 80;
// 语速倍率。09s 竖版要「紧凑、语速快一点」，但字数不砍内容，
// 所以用 speed 参数提速而不是压稿子——两者的失真方向不一样：
// 砍稿子会伤论证链，提速只是语流更密。
// 语速变了，「纯语音语速 / 端到端速率」两个口径也跟着变，
// 别拿本期数字去套全系列 5.01。
const SPEED = process.env.SPEED ? +process.env.SPEED : 1;

const sleep = ms => new Promise(r => setTimeout(r, ms));

function rawCall(tool, args, tag) {
  const argsFile = path.join(os.tmpdir(), `mctts_${process.pid}_${tag}.json`);
  fs.writeFileSync(argsFile, JSON.stringify(args), 'utf8');
  try {
    const stdout = execFileSync(
      'mcode-tools',
      ['connector', 'call', tool, '--args-file', argsFile],
      { encoding: 'utf8', maxBuffer: 64 * 1024 * 1024, stdio: ['ignore', 'pipe', 'pipe'] }
    );
    const i = stdout.indexOf('{');
    if (i < 0) throw new Error('stdout 不是 JSON: ' + stdout.slice(0, 200));
    return JSON.parse(stdout.slice(i));
  } finally {
    try { fs.unlinkSync(argsFile); } catch {}
  }
}

// 注意：get_asset_url 是 mcode-tools 的顶层命令，不是 connector tool。
// 写成 connector__matrix__get_asset_url 会一直报 error，重试六次也没用。
function assetUrl(nodeId) {
  const stdout = execFileSync('mcode-tools', ['get_asset_url', nodeId], {
    encoding: 'utf8', maxBuffer: 8 * 1024 * 1024, stdio: ['ignore', 'pipe', 'pipe'],
  });
  const i = stdout.indexOf('{');
  if (i < 0) throw new Error('get_asset_url 不是 JSON: ' + stdout.slice(0, 200));
  return JSON.parse(stdout.slice(i));
}

async function withBackoff(fn, label) {
  for (let attempt = 1; attempt <= MAX_RETRY; attempt++) {
    try {
      return await fn();
    } catch (e) {
      const msg = String(e.message || e).slice(0, 200);
      if (attempt === MAX_RETRY) throw new Error(`${label} 重试 ${MAX_RETRY} 次仍失败: ${msg}`);
      // 429（限流）走固定心跳 + 抖动，其它错误按 5s 步进。
      // **抖动是必要的**：整点重试会一次次撞进同一个限流窗口。
      const wait = /429|rate|限流|too many/i.test(msg)
        ? 25 + Math.floor(Math.random() * 20) : attempt * 5;
      console.log(`  ! ${label} 第 ${attempt} 次失败(${msg})，${wait}s 后重试`);
      await sleep(wait * 1000);
    }
  }
}

async function download(url, dest) {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`下载失败 HTTP ${res.status}`);
  const buf = Buffer.from(await res.arrayBuffer());
  fs.writeFileSync(dest, buf);
  return buf.length;
}

async function main() {
  const [sentPath, outDir] = process.argv.slice(2);
  if (!sentPath || !outDir) {
    console.error('用法: node tts.js <sentences.json> <audio_dir>');
    process.exit(1);
  }

  const sentences = JSON.parse(fs.readFileSync(sentPath, 'utf8'));
  fs.mkdirSync(outDir, { recursive: true });

  const only = process.env.ONLY_KEY || null;   // 调试单句
  const list = only ? sentences.filter(s => s.key === only) : sentences;

  console.log(`音色: ${VOICE}`);
  console.log(`待合成: ${list.length} 句（串行）\n`);

  const manifest = [];

  for (const [i, s] of list.entries()) {
    const mp3 = path.join(outDir, `${s.key}.mp3`);
    if (fs.existsSync(mp3) && fs.statSync(mp3).size > 1024 && !process.env.FORCE) {
      console.log(`[${i + 1}/${list.length}] ${s.key} 已存在，跳过`);
      manifest.push({ key: s.key, file: mp3, cached: true });
      continue;
    }

    process.stdout.write(`[${i + 1}/${list.length}] ${s.key} `);

    const res = await withBackoff(async () => {
      const r = rawCall('connector__matrix__synthesize_speech', {
        text: s.text,
        voice_id: VOICE,
        ...(SPEED !== 1 ? { speed: SPEED } : {}),
        output_file: `${s.key}.mp3`,
      }, s.key);
      if (!r || !r.node_id) throw new Error(JSON.stringify(r).slice(0, 200));
      return r;
    }, s.key);

    const urlRes = await withBackoff(() => assetUrl(res.node_id), `${s.key}_url`);

    const bytes = await withBackoff(() => download(urlRes.download_url, mp3), `${s.key}_dl`);

    console.log(`OK ${(bytes / 1024).toFixed(0)}KB  ${s.text.slice(0, 18)}…`);
    manifest.push({ key: s.key, file: mp3, bytes, cached: false });

    // 句与句之间留 1 秒，避免触发上游限流
    if (i < list.length - 1) await sleep(1000);
  }

  fs.writeFileSync(path.join(outDir, 'manifest.json'), JSON.stringify(manifest, null, 2));
  console.log(`\n完成 ${manifest.length} 句 → ${outDir}`);
}

main().catch(e => {
  console.error('TTS 失败:', e.message || e);
  process.exit(1);
});
