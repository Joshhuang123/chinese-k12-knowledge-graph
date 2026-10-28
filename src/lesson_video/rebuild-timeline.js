#!/usr/bin/env node
// rebuild-timeline.js —— TTS 回来后用真实音频时长重建时间轴
//
//   node rebuild-timeline.js <timeline.json> <audio_dir>
//
// 为什么要重建：prep.js 的时长是字数估算，只用来排骨架。真值必须来自 ffprobe。
//
// 坑：改过某句音频后必须先删掉该句旧的 mp3，否则脚本会跳过重合成，
// 时间戳全新、所有检查都正常，成片却成了字幕与配音对不上。

const fs = require('fs');
const path = require('path');
const { execFileSync } = require('child_process');

function dur(file) {
  const out = execFileSync('ffprobe', [
    '-v', 'error',
    '-show_entries', 'format=duration',
    '-of', 'default=nw=1:nk=1',
    file,
  ], { encoding: 'utf8' });
  return parseFloat(out.trim());
}

function main() {
  const [tlPath, audioDir] = process.argv.slice(2);
  if (!tlPath || !audioDir) {
    console.error('用法: node rebuild-timeline.js <timeline.json> <audio_dir>');
    process.exit(1);
  }

  const tl = JSON.parse(fs.readFileSync(tlPath, 'utf8'));
  const { GAP, SCENE_GAP, TAIL } = tl.constants;

  const missing = tl.sentences.filter(s => !fs.existsSync(path.join(audioDir, `${s.key}.mp3`)));
  if (missing.length) {
    console.error(`缺 ${missing.length} 句音频:`);
    missing.forEach(s => console.error('  ' + s.key));
    process.exit(1);
  }

  // 真实时长写回
  let speech = 0, silence = 0;
  for (const s of tl.sentences) {
    const d = dur(path.join(audioDir, `${s.key}.mp3`));
    s.dur = +d.toFixed(3);
    s.est = false;
    speech += d;
  }

  // 排布：句内无缝，句间 GAP，场间 SCENE_GAP，片尾 TAIL
  const byScene = new Map();
  for (const s of tl.sentences) {
    if (!byScene.has(s.scene)) byScene.set(s.scene, []);
    byScene.get(s.scene).push(s);
  }

  let t = 0;
  tl.scenes.forEach((sc, si) => {
    const list = byScene.get(si) || [];
    sc.start = +t.toFixed(3);
    list.forEach((s, i) => {
      s.start = +t.toFixed(3);
      t += s.dur;
      s.end = +t.toFixed(3);
      if (i < list.length - 1) { t += GAP; silence += GAP; }
    });
    t += SCENE_GAP; silence += SCENE_GAP;
    sc.end = +t.toFixed(3);
  });

  const total = +(t - SCENE_GAP + TAIL).toFixed(3);
  tl.total = total;
  tl.built = 'rebuild-real';
  tl.audioSummary = {
    speech: +speech.toFixed(3),
    silence: +silence.toFixed(3),
    tail: TAIL,
    rate: +(speech / speech * 1000 / 1000).toFixed(3), // 占位，下面用真实语速
  };
  const chars = tl.sentences.reduce((a, s) => a + s.text.replace(/\s+/g, '').length, 0);
  tl.audioSummary.chars = chars;
  tl.audioSummary.pureSpeechRate = +(chars / speech).toFixed(3);   // 纯语音语速
  tl.audioSummary.endToEndRate = +(chars / total).toFixed(3);     // 端到端速率

  fs.writeFileSync(tlPath, JSON.stringify(tl, null, 2));

  const m = Math.floor(total / 60), s = (total % 60).toFixed(3);
  console.log(`句数    : ${tl.sentences.length}`);
  console.log(`总字数  : ${chars}`);
  console.log(`语音时长: ${speech.toFixed(3)}s`);
  console.log(`静音    : ${silence.toFixed(3)}s (含片尾 ${TAIL}s)`);
  console.log(`成片时长: ${total.toFixed(3)}s = ${m} 分 ${s} 秒`);
  console.log(`纯语音语速: ${tl.audioSummary.pureSpeechRate} 字/秒  <-- 校对稿子长度用这个`);
  console.log(`端到端速率: ${tl.audioSummary.endToEndRate} 字/秒  <-- 全系列口径是 5.01`);
  if (total > 90) console.log(`!! 短片红线 90 秒，超了 ${(total - 90).toFixed(1)} 秒`);
}

main();
