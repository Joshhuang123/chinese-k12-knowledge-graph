#!/usr/bin/env bash
# mux-shots.sh —— 幻灯片截图（每句一张）+ 音轨 → 成片
#
#   bash mux-shots.sh <timeline.json> <shots_dir> <音轨.wav> <out.mp4>
#
# 为什么用 concat demuxer 而不是 xfade：
#   讲义视频是**静态幻灯片**，硬切反而干净（交叉溶解会把字幕叠在一起）。
#   每张图给一段真实时长，时长来自 timeline（ffprobe 实测的音频时长）。
set -euo pipefail

TL="$1"; SHOTS="$2"; AUDIO="$3"; OUT="$4"
[ -f "$TL" ] || { echo "!! 缺 $TL" >&2; exit 1; }
[ -f "$AUDIO" ] || { echo "!! 缺 $AUDIO" >&2; exit 1; }
[ -d "$SHOTS" ] || { echo "!! 缺 $SHOTS" >&2; exit 1; }

# ⚠️ 必须转绝对路径 —— `node -e require(x)` 里 x 不带 ./ 会被当成**模块名**，
# 相对路径直接报 MODULE_NOT_FOUND（而且退出码不是 1，很容易被忽略）。
TL_ABS=$(cd "$(dirname "$TL")" && pwd)/$(basename "$TL")
SHOTS_ABS=$(cd "$SHOTS" && pwd)

FPS=$(node -e 'console.log(require(process.argv[1]).meta.fps)' "$TL_ABS")
W=$(node -e 'console.log(require(process.argv[1]).meta.width)' "$TL_ABS")
H=$(node -e 'console.log(require(process.argv[1]).meta.height)' "$TL_ABS")
N=$(node -e 'console.log(require(process.argv[1]).sentences.length)' "$TL_ABS")

# ⚠️ macOS 的 mktemp 要求 X 在**末尾**（XXXXXX.txt 会当成已存在的文件名）
LIST=$(mktemp /tmp/muxlist.XXXXXX)
node -e '
const fs=require("fs");
const tl=JSON.parse(fs.readFileSync(process.argv[1],"utf8"));
const dir=process.argv[2];
const n=tl.sentences.length;
const durs=tl.sentences.map(s=>+(s.dur!=null?s.dur:(s.end-s.start)).toFixed(3));
// ⚠️ 画面总时长必须**正好等于**时间轴总长。
// concat demuxer 的时长只到「最后一句」为止，片尾静音（TAIL）在画面里没有对应，
// 合成时 -shortest 会按短的那个截 —— 结果**片尾被剪掉 3.5 秒**。
// 办法：把差额补给最后一帧，让它多停一会儿。
const sum=durs.reduce((a,b)=>a+b,0);
const tail=+(tl.total-sum).toFixed(3);
if (tail>0) durs[n-1]=+(durs[n-1]+tail).toFixed(3);
const lines=[];
durs.forEach((d,i)=>{
  const f=dir+"/"+String(i).padStart(3,"0")+".png";
  if(!fs.existsSync(f)){ console.error("缺图: "+f); process.exit(1); }
  lines.push("file \x27"+f.replace(/'"'"'/g,"'"'"'\\'"'"''"'"'")+"\x27");
  lines.push("duration "+d.toFixed(3));
});
// concat demuxer 要求最后一张再写一遍（否则最后一帧时长被丢）
lines.push("file \x27"+dir+"/"+String(n-1).padStart(3,"0")+".png\x27");
fs.writeFileSync(process.argv[3], lines.join("\n")+"\n");
console.log("  画面时长 "+durs.reduce((a,b)=>a+b,0).toFixed(3)+"s（时间轴 "+tl.total.toFixed(3)+"s）");
' "$TL_ABS" "$SHOTS_ABS" "$LIST"

TOTAL=$(node -e 'console.log(require(process.argv[1]).total)' "$TL_ABS")
echo "合成 ${N} 张幻灯片 · ${W}×${H} @ ${FPS}fps · 时间轴 ${TOTAL}s"

ffmpeg -hide_banner -loglevel error -y \
  -f concat -safe 0 -i "$LIST" \
  -i "$AUDIO" \
  -c:v libx264 -preset slow -crf 21 -pix_fmt yuv420p \
  -r "$FPS" -g 50 \
  -c:a aac -b:a 160k -ar 48000 -ac 2 \
  -movflags +faststart -shortest \
  "$OUT"

rm -f "$LIST"
echo "合成完成 → $OUT"
ffprobe -v error -show_entries format=duration,size -of default=nw=1 "$OUT" | sed 's/^/  /'
