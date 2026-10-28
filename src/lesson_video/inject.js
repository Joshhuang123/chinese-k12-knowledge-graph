#!/usr/bin/env node
// inject.js —— 把真值 timeline.json（+ 讲解稿）注入模板，产出 slide.final.html
//
//   node inject.js <slide.html> <timeline.json> [slide.final.html] [lesson.json]
//
// __TIMELINE__ / __LESSON__ 是替换锚点，不要手工填。

const fs = require('fs');

function main() {
  const [scenePath, tlPath, outPath, lessonPath] = process.argv.slice(2);
  if (!scenePath || !tlPath) {
    console.error('用法: node inject.js <slide.html> <timeline.json> [out] [lesson.json]');
    process.exit(1);
  }
  const out = outPath || scenePath.replace(/\.html$/, '.final.html');

  const html = fs.readFileSync(scenePath, 'utf8');
  const tl = fs.readFileSync(tlPath, 'utf8');

  if (!html.includes('__TIMELINE__')) {
    console.error('!! 模板里没有 __TIMELINE__ 锚点');
    process.exit(1);
  }
  // </script> 出现在 JSON 里会提前关闭 script 标签，必须转义
  const safe = tl.replace(/<\/script>/gi, '<\\/script>');
  let out2 = html.replace('__TIMELINE__', safe);

  if (html.includes('__LESSON__')) {
    if (!lessonPath) {
      console.error('!! 模板里有 __LESSON__ 锚点，但没给讲解稿');
      process.exit(1);
    }
    const lesson = fs.readFileSync(lessonPath, 'utf8').replace(/<\/script>/gi, '<\\/script>');
    out2 = out2.replace('__LESSON__', lesson);
  }

  fs.writeFileSync(out, out2);
  const meta = JSON.parse(tl);
  console.log(`注入完成 → ${out}`);
  console.log(`总时长 ${meta.total}s · 场 ${meta.scenes.length} · 句 ${meta.sentences.length}`);
  console.log(`构建标记: ${meta.built}`);
}

main();
