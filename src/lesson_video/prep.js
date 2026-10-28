#!/usr/bin/env node
// prep.js —— script.json → 骨架 timeline.json + TTS 句表
//
// 唯一的人写输入是 script.json；这里负责按句号切句、分配 key、生成骨架时间轴。
// 时间轴里的 start/end 在 TTS 回来前是占位值，真值由 rebuild-timeline.js 填。
//
//   node prep.js <script.json> <outdir>
//
// 时长常量与全系列一致，改了会全片错位：
const GAP      = 0.30;    // 句间静音
const SCENE_GAP= 0.75;    // 场间静音
const TAIL     = 2.751;   // 片尾
const RATE     = 5.01;    // 字/秒，仅用于骨架预估，TTS 后以真值为准

const fs = require('fs');
const path = require('path');

// 按句号切句；分号也切，因为它天然是分句边界，能让字幕跟得更准。
// 保留标点本身，TTS 需要它做断句。
function splitSentences(text) {
  return text
    .replace(/\s+/g, ' ')
    .split(/(?<=[。；])/)
    .map(s => s.trim())
    .filter(Boolean);
}

function main() {
  const [scriptPath, outdir] = process.argv.slice(2);
  if (!scriptPath || !outdir) {
    console.error('用法: node prep.js <script.json> <outdir>');
    process.exit(1);
  }

  const script = JSON.parse(fs.readFileSync(scriptPath, 'utf8'));
  fs.mkdirSync(outdir, { recursive: true });

  const sentences = [];
  const scenes = [];
  let t = 0;
  let idx = 0;

  for (const sc of script.scenes) {
    const start = t;
    const parts = splitSentences(sc.text);

    parts.forEach((p, i) => {
      const key = `${sc.id}_${i}`;
      const est = p.length / RATE;
      sentences.push({
        key,
        scene: idx,
        text: p,
        audio: `audio/${key}.mp3`,
        start: +t.toFixed(3),
        end: +(t + est).toFixed(3),
        est: true,
      });
      t += est + GAP;
    });

    // 最后一句后面不加句间 GAP，改成场间 SCENE_GAP
    t = t - GAP + SCENE_GAP;

    scenes.push({
      idx,
      id: sc.id,
      title: sc.title,
      start: +start.toFixed(3),
      end: +t.toFixed(3),
      sentFrom: parts.length ? `${sc.id}_0` : null,
      sentTo: parts.length ? `${sc.id}_${parts.length - 1}` : null,
    });
    idx++;
  }

  const total = +(t - SCENE_GAP + TAIL).toFixed(3);

  const timeline = {
    total,
    meta: script.meta,
    constants: { GAP, SCENE_GAP, TAIL },
    scenes,
    sentences,
    built: 'prep-skeleton',
  };

  fs.writeFileSync(path.join(outdir, 'timeline.json'), JSON.stringify(timeline, null, 2));

  // TTS 句表：扁平、只带 key 和 text，方便串行朗读脚本消费
  const ttsList = sentences.map(s => ({ key: s.key, text: s.text, scene: s.scene }));
  fs.writeFileSync(path.join(outdir, 'sentences.json'), JSON.stringify(ttsList, null, 2));

  const totalChars = script.scenes.reduce((a, s) => a + s.text.replace(/\s+/g, '').length, 0);

  console.log(`场数      : ${scenes.length}`);
  console.log(`句数      : ${sentences.length}`);
  console.log(`口播字数  : ${totalChars}`);
  console.log(`骨架预估  : ${total.toFixed(3)}s  (TTS 后以真实音频为准)`);
  console.log(`句表      : ${path.join(outdir, 'sentences.json')}`);
}

main();
