#!/usr/bin/env node
// build-audio.js —— 按真值时间轴把 20 句 mp3 拼成一条整轨 wav
//
//   node build-audio.js <timeline.json> <audio_dir> <out.wav>
//
// 不能用 concat demuxer 直接拼 mp3：每句编码参数不完全一致，
// 拼出来会有爆音。统一转 48k 立体声 PCM 再拼。
// 静音单独生成 WAV 填句间/场间间隙，位置严格按 timeline 的 start。

const fs = require('fs');
const path = require('path');
const { execFileSync } = require('child_process');

const SR = 48000, CH = 2;

function run(args) {
  return execFileSync('ffmpeg', ['-hide_banner', '-loglevel', 'error', '-y', ...args],
    { encoding: 'utf8', maxBuffer: 64 * 1024 * 1024 });
}

function main() {
  const [tlPath, audioDir, outWav] = process.argv.slice(2);
  if (!tlPath || !audioDir || !outWav) {
    console.error('用法: node build-audio.js <timeline.json> <audio_dir> <out.wav>');
    process.exit(1);
  }

  const tl = JSON.parse(fs.readFileSync(tlPath, 'utf8'));
  const tmp = fs.mkdtempSync(path.join(require('os').tmpdir(), 'mcaudio-'));
  const parts = [];

  const silence = (sec, name) => {
    const f = path.join(tmp, name);
    run(['-f', 'lavfi', '-i',
      `anullsrc=r=${SR}:cl=stereo:d=${sec.toFixed(3)}`,
      '-c:a', 'pcm_s16le', f]);
    return f;
  };

  let cur = 0, n = 0;
  for (const s of tl.sentences) {
    const gapSec = s.start - cur;
    if (gapSec > 0.001) { parts.push({ f: silence(gapSec, `g${n}.wav`), dur: gapSec }); cur += gapSec; }
    const src = path.join(audioDir, `${s.key}.mp3`);
    const wav = path.join(tmp, `s${n}.wav`);
    run(['-i', src, '-ar', String(SR), '-ac', String(CH),
      '-c:a', 'pcm_s16le', wav]);
    // 以 ffprobe 实测时长为准，不信任时间轴里抄的 dur
    const d = parseFloat(execFileSync('ffprobe', [
      '-v', 'error', '-show_entries', 'format=duration',
      '-of', 'default=nw=1:nk=1', wav], { encoding: 'utf8' }).trim());
    parts.push({ f: wav, dur: d });
    cur += d;
    n++;
  }

  const tailSec = tl.total - cur;
  if (tailSec > 0.001) parts.push({ f: silence(tailSec, 'tail.wav'), dur: tailSec });

  // concat demuxer 对同参数 WAV 是安全的
  const listFile = path.join(tmp, 'list.txt');
  fs.writeFileSync(listFile, parts.map(p => `file '${p.f.replace(/'/g, "'\\''")}'`).join('\n'));

  run(['-f', 'concat', '-safe', '0', '-i', listFile,
    '-ar', String(SR), '-ac', String(CH), '-c:a', 'pcm_s16le', outWav]);

  const got = parseFloat(execFileSync('ffprobe', [
    '-v', 'error', '-show_entries', 'format=duration',
    '-of', 'default=nw=1:nk=1', outWav], { encoding: 'utf8' }).trim());

  const expect = Math.ceil(tl.total * SR) / SR;
  const diff = Math.abs(got - tl.total);
  console.log(`拼轨完成 → ${outWav}`);
  console.log(`片段     : ${parts.length} (${n} 句 + ${parts.length - n} 静音)`);
  console.log(`时间轴   : ${tl.total.toFixed(3)}s`);
  console.log(`实测     : ${got.toFixed(3)}s  (差 ${(diff * 1000).toFixed(0)}ms)`);
  if (diff > 0.05) {
    console.error(`!! 音轨与时间轴相差 ${diff.toFixed(3)}s，会导致音画错位`);
    process.exit(1);
  }
}

main();
