#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
把**讲解稿**做成讲解视频，并挂到学习页上。

一条视频的完整链路
------------------
    data/lesson-scripts/<id>.json     ← 人写的讲解稿（唯一的手写输入）
        ↓ script.json
    prep.js                切句、排骨架时间轴
        ↓ sentences.json
    tts.js                 串行 TTS（音色 Chinese (Mandarin)_Reliable_Executive）
        ↓ audio/*.mp3
    rebuild-timeline.js    用 ffprobe 实测时长重排时间轴
        ↓ timeline.json（真值）
    build-audio.js         按真值拼成一条整轨 wav
        ↓ 音轨.wav
    inject.js              把时间轴 + 讲解稿注入模板
        ↓ slide.final.html
    shot.js                **每句截一张**（不是逐帧）
        ↓ shots/*.png
    mux-shots.sh           ffmpeg 合成
        ↓ video/<id>.mp4
    data/learn-videos.json + data/learn-explains.js

跑:
    python3 src/build_lesson_videos.py              # 只做还没做过的
    python3 src/build_lesson_videos.py --only <id>  # 只做一条
    python3 src/build_lesson_videos.py --list       # 看看有哪些稿子

**为什么讲解稿是唯一手写输入**：稿子同时是视频的配音脚本**和**页面上的文字讲解。
视频是稿子的配音版 —— 两者永远一致，不会出现「视频讲一套、页面写另一套」。
"""
import argparse
import json
import pathlib
import shutil
import subprocess
import sys
import time

BASE = pathlib.Path(__file__).resolve().parent.parent
LV = BASE / "src" / "lesson_video"
SCRIPTS = BASE / "data" / "lesson-scripts"
WORK = LV / "work"
OUTDIR = BASE / "video"
VIDEOS_JSON = BASE / "data" / "learn-videos.json"
EXPLAINS_JS = BASE / "data" / "learn-explains.js"

FPS = 24
W, H = 1920, 1080


def run(cmd, cwd=None, quiet=False):
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if p.returncode != 0:
        print((p.stdout or "") + (p.stderr or ""), file=sys.stderr)
        raise SystemExit(f"命令失败（退出码 {p.returncode}）: {' '.join(str(c) for c in cmd)}")
    if not quiet and p.stdout.strip():
        print(p.stdout.rstrip())
    return p.stdout


def load_lesson(path: pathlib.Path):
    d = json.loads(path.read_text(encoding="utf-8"))
    for k in ["id", "name", "scenes", "explain"]:
        if k not in d:
            raise SystemExit(f"{path.name}: 缺字段 {k}")
    if len(d["scenes"]) != 5:
        raise SystemExit(f"{path.name}: 场景数应为 5（封面/是什么/教材原页/前置/结尾），"
                         f"实际 {len(d['scenes'])}")
    return d


def build_script_json(L, out_path: pathlib.Path):
    """讲解稿 → script.json（prep.js 的输入）"""
    script = {
        "meta": {
            "title": L["name"],
            "episode": "learn",
            "orientation": "horizontal",
            "width": W, "height": H, "fps": FPS,
            "date": time.strftime("%Y-%m-%d"),
        },
        "scenes": [{"id": s["id"], "title": s["title"], "text": s["text"]}
                   for s in L["scenes"]],
    }
    out_path.write_text(json.dumps(script, ensure_ascii=False, indent=1), encoding="utf-8")


def build_one(L, force=False, keep=False):
    cid = L["id"]
    ver = L.get("version") or "sh"
    # ⚠️ **成品文件名必须带版本** —— 上游 id 跨版本共享，
    # 同名 id 的两个版本会写到同一个 mp4 上，后一个覆盖前一个。
    stem = f"{ver}_{cid}"
    wd = WORK / stem
    out_mp4 = OUTDIR / f"{stem}.mp4"
    if out_mp4.exists() and not force:
        print(f"  · {cid}: 已存在，跳过")
        return out_mp4, None
    # ⚠️ **音频要留着** —— TTS 撞限流时每句要等 25–45 秒，
    # 改个模板就重跑一遍 TTS 是纯浪费（一条 11 句的稿子要 3.5 分钟）。
    # 只有音频不在时才清目录重来。
    if wd.exists() and not (wd / "audio").is_dir():
        shutil.rmtree(wd)
    wd.mkdir(parents=True, exist_ok=True)
    (wd / "audio").mkdir(exist_ok=True)
    (wd / "shots").mkdir(exist_ok=True)

    build_script_json(L, wd / "script.json")

    run(["node", str(LV / "prep.js"), str(wd / "script.json"), str(wd)], cwd=str(wd))

    t0 = time.time()
    run(["node", str(LV / "tts.js"), str(wd / "sentences.json"), str(wd / "audio")],
        cwd=str(wd))
    tts_s = time.time() - t0

    run(["node", str(LV / "rebuild-timeline.js"), str(wd / "timeline.json"),
         str(wd / "audio")], cwd=str(wd))
    tl = json.loads((wd / "timeline.json").read_text(encoding="utf-8"))

    run(["node", str(LV / "build-audio.js"), str(wd / "timeline.json"),
         str(wd / "audio"), str(wd / "音轨.wav")], cwd=str(wd))

    # ⚠️ 页图路径要转成**绝对路径** —— slide.final.html 在 work/<id>/ 里，
    # 相对路径会指错地方。
    L2 = json.loads(json.dumps(L))
    if L2.get("page") and L2["page"].get("image"):
        img = L2["page"]["image"]
        # ⚠️ **http(s) 开头的不要当本地路径拼** ——
        # 沪教版的页图是**平台官方外链**（仓库里不存教材内容），
        # `BASE / "https://..."` 会拼成一个不存在的本地路径，图直接裂。
        if not img.startswith(("http://", "https://")):
            img = str((BASE / img).resolve())
        L2["page"]["image"] = img
    (wd / "lesson.json").write_text(json.dumps(L2, ensure_ascii=False), encoding="utf-8")
    run(["node", str(LV / "inject.js"), str(LV / "slide.html"),
         str(wd / "timeline.json"), str(wd / "slide.final.html"),
         str(wd / "lesson.json")], cwd=str(wd))

    run(["node", str(LV / "shot.js"), str(wd / "timeline.json"),
         str(wd / "slide.final.html"), str(wd / "shots")], cwd=str(wd))

    OUTDIR.mkdir(exist_ok=True)
    # **poster = 第一张截图（封面帧）** ——
    # 页面上的播放器是 preload="none"（省流量），不加载就是个黑框。
    # 给张封面帧，学生一眼知道这视频讲什么。
    shot0 = wd / "shots" / "000.png"
    poster = OUTDIR / f"{stem}.jpg"
    if shot0.exists():
        try:
            from PIL import Image
            Image.open(shot0).convert("RGB").save(poster, "JPEG", quality=72)
        except Exception:
            poster = None

    run(["bash", str(LV / "mux-shots.sh"), str(wd / "timeline.json"),
         str(wd / "shots"), str(wd / "音轨.wav"), str(out_mp4)], cwd=str(wd))

    dur = round(tl["total"])
    print(f"  ✓ {cid}: {dur}s · {out_mp4.stat().st_size/1024/1024:.1f} MB · TTS 用了 {tts_s/60:.1f} 分钟")

    if not keep:
        shutil.rmtree(wd / "shots", ignore_errors=True)
    return out_mp4, dur


def _probe_duration(mp4):
    try:
        out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                              "-of", "default=nw=1:nk=1", str(mp4)],
                             capture_output=True, text=True)
        return int(round(float(out.stdout.strip())))
    except Exception:
        return 0


def write_indexes(ids):
    """把做好的视频挂进 learn-videos.json，并导出讲解稿文字版"""
    vids = json.loads(VIDEOS_JSON.read_text(encoding="utf-8")) if VIDEOS_JSON.exists() else {}
    expl = {}
    for cid in ids:
        # ids 里带版本前缀（形如 rjb_math_9b_rjb_cpt1）
        sc = SCRIPTS / f"{cid}.json"
        if not sc.exists():
            continue
        L = json.loads(sc.read_text(encoding="utf-8"))
        mp4 = OUTDIR / f"{cid}.mp4"   # cid 已含版本前缀
        if not mp4.exists():
            continue
        dur = _probe_duration(mp4)
        # ⚠️ 键必须是 **'<版本>:<概念id>'** ——
        # 上游 id 跨版本共享（沪教的 3,503 个 id 在人教版里全都同名），
        # 但指向不同的教材位置。用裸 id 挂，人教版的视频会出现在沪教版页面上。
        ver = L.get("version") or "sh"
        key = f"{ver}:{L['id']}"
        # 清掉可能存在的旧裸键（早期版本用过裸 id —— 跨版本会挂错）
        vids.pop(L["id"], None)
        entry = {
            "mp4": f"video/{cid}.mp4",
            "title": L["name"],
            "dur": f"{dur//60}:{dur%60:02d}" if dur else "",
        }
        poster = OUTDIR / f"{cid}.jpg"
        if poster.exists():
            entry["poster"] = f"video/{cid}.jpg"
        vids[key] = entry
        expl[key] = {"lines": L["explain"]["lines"], "from": L["explain"].get("from", "")}

    VIDEOS_JSON.write_text(json.dumps(vids, ensure_ascii=False, indent=2), encoding="utf-8")
    # ⚠️ **两个文件必须一起写** ——
    #   data/learn-videos.json  → build_learn_site.py 读的（合并进 rec["v"]）
    #   data/learn-videos.js    → 页面运行时读的（window.LEARN_VIDEOS）
    # 以前只有一个 .js（手写的模板），构建脚本只写 .json ——
    # 结果做好的视频**页面上一条也挂不上**（查不到就不显示）。
    (BASE / "data" / "learn-videos.js").write_text(
        "window.LEARN_VIDEOS=" + json.dumps(vids, ensure_ascii=False, separators=(",", ":")) + ";\n",
        encoding="utf-8")
    EXPLAINS_JS.write_text("window.LEARN_EXPLAINS=" +
                            json.dumps(expl, ensure_ascii=False, separators=(",", ":")) + ";\n",
                            encoding="utf-8")
    print(f"\n索引更新：{VIDEOS_JSON.name}（{len(vids)} 条）· {EXPLAINS_JS.name}（{len(expl)} 条）")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="只做这一条（概念 id）")
    ap.add_argument("--force", action="store_true", help="已有的也重做")
    ap.add_argument("--list", action="store_true", help="列出手写稿")
    ap.add_argument("--keep", action="store_true", help="保留工作目录")
    args = ap.parse_args()

    SCRIPTS.mkdir(parents=True, exist_ok=True)
    files = sorted(SCRIPTS.glob("*.json"))
    if args.list:
        for f in files:
            L = json.loads(f.read_text(encoding="utf-8"))
            print(f"  {f.stem:28s} {L.get('name','?'):16s} {L.get('version','?')}")
        print(f"\n共 {len(files)} 份稿子")
        return 0
    if not files:
        print("没有讲解稿。先写 data/lesson-scripts/<id>.json")
        return 0
    if args.only:
        files = [f for f in files if f.stem == args.only or f.stem.endswith("_" + args.only)]
        if not files:
            print(f"没有 {args.only} 的稿子")
            return 1

    print(f"讲解视频管线 · {W}×{H} @ {FPS}fps\n")
    done = []
    for f in files:
        L = load_lesson(f)
        try:
            build_one(L, force=args.force, keep=args.keep)
            # ⚠️ 存的是 **版本前缀过的 stem**（rjb_<id>）——
            # write_indexes 要按它找稿子文件和成品 mp4。
            done.append(f"{L.get('version') or 'sh'}_{L['id']}")
        except SystemExit as e:
            print(f"  ✗ {L['id']}: {e}")
    write_indexes(done)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
