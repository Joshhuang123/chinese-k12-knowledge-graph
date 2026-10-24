#!/usr/bin/env python3
"""
把 3D 页面录成 mp4。

为什么不直接截屏连成视频：渲染器是按「帧数」累加旋转角的
（`if(spin && !dragging) TARGET.th += 0.0022;`），不是按时间。
每次启动的帧数不确定，直接截会得到一堆角度随机的帧。
所以这里给页面注入一个控制钩子，用 URL 参数把相机钉死在指定角度，
再逐帧截图 —— 角度是算出来的，不是碰运气撞出来的。

注入的钩子只做四件事：关掉自动旋转、把相机瞬间对到目标角度、
可选取中节点、可选打开信息卡。相机有缓动（cam += (TARGET-cam)*0.09），
但目标不再变，缓动几帧后就稳定了。

跑:  python3 src/record.py            # 完整两段式，约 10 分钟
     python3 src/record.py --test     # 只出 2 帧，用来验管线
输出: viz/rec/frames/*.png → viz/录屏.mp4
"""
import argparse
import json
import pathlib
import shutil
import os
import subprocess
import sys
import time

BASE = pathlib.Path(__file__).resolve().parent.parent
VIZ = BASE / "viz"
SRC = VIZ / "知识图谱3D.html"
REC = VIZ / "rec"
SHOTS = REC / "frames"
REC_HTML = REC / "_rec.html"
OUT = VIZ / "录屏.mp4"

# 与 test_*.mjs 同一个约定：CHROME 环境变量可覆盖（Linux/自定义路径）
CHROME = os.environ.get("CHROME", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
W, H = 1600, 1000
FPS = 24

# 注入脚本：URL 参数 → 页面状态。
#
# 必须注入到主脚本「内部」，不能挂在 </body> 后面。
# template.html 的主脚本整体包在 IIFE 里（(function(){ … })()），
# spin / TARGET / cam / setFocus / showCard 全是闭包内的局部绑定，
# 外部 script 根本够不着 —— 挂外面会静默失效：
# 参数没生效、画面照常渲染、截图看着正常，但聚焦和信息卡根本没出现。
#
# 出错时不吞异常，改为在页顶画一条红条。
# 截图里一眼就能看见，不会再出现「以为录好了其实没生效」。
HOOK = """
/* ---- rec-hook (injected inside the renderer's IIFE) ---- */
(function(){
  var q = new URLSearchParams(location.search);
  var fail = function(e){
    var d = document.createElement('div');
    d.textContent = 'REC-HOOK FAIL: ' + e;
    d.style.cssText = 'position:fixed;left:0;top:0;right:0;z-index:99999;' +
      'background:#e11d48;color:#fff;font:700 16px monospace;padding:8px';
    document.body.appendChild(d);
  };
  try{
    spin = false;
    if(q.has('th')) { TARGET.th = parseFloat(q.get('th')); cam.th = TARGET.th; }
    if(q.has('ph')) { TARGET.ph = parseFloat(q.get('ph')); cam.ph = TARGET.ph; }
    if(q.has('d'))  { TARGET.d  = parseFloat(q.get('d'));  cam.d  = TARGET.d;  }
    if(q.has('focus')){
      var f = parseInt(q.get('focus'), 10);
      if(!(f >= 0 && f < NODES.length)) throw new Error('focus 越界: ' + q.get('focus') + ' / N=' + NODES.length);
      setFocus(f);
    }
    if(q.has('card')) showCard(parseInt(q.get('card'), 10));
  }catch(e){ fail(e && e.message || e); }
})();
/* ---- end rec-hook ---- */
"""

SHOTS.mkdir(parents=True, exist_ok=True)


def build_html():
    """
    从成品页派生一个可控副本。只在派生件上注入，成品页永远不动。

    注入点：主脚本 IIFE 内部的 `loop();` 之前。
    末尾那个 `</script>` 不行 —— IIFE 在它之前就闭合了，注在那儿等于注到闭包外，
    结果就是参数静默失效、画面照常渲染、截图看着正常但聚焦根本没发生。
    `loop()` 之前是唯一「所有声明都已求值、动画还没开始」的位置。

    注入后必须自检：钩子要落在 `})();` 之前。宁可不做，也不能装作成功。
    """
    html = SRC.read_text(encoding="utf-8")
    end = html.rfind("</script>")
    if end < 0:
        sys.exit("成品页里找不到 </script>")
    anchor = html.rfind("\nloop();", 0, end)
    if anchor < 0:
        sys.exit("找不到 IIFE 末尾的 loop(); 锚点，模板结构变了")
    tail = html[anchor:end]
    # 锚点到 </script> 之间只该剩下 IIFE 的收尾，多了就说明锚点认错了
    if tail.replace("loop();", "").strip() not in ("})();", "}());"):
        sys.exit(f"loop(); 之后不是 IIFE 收尾，而是：{tail!r}")
    body = html[:anchor] + "\n" + HOOK + html[anchor:end] + html[end:]
    # 自检：钩子必须在 IIFE 闭合之前
    if body.find(HOOK[:40]) > body.rfind("})();"):
        sys.exit("注入自检失败：钩子落在 IIFE 外部")
    REC_HTML.write_text(body, encoding="utf-8")
    return REC_HTML


def pick_demo_node():
    """
    挑一个适合演示的节点。

    不能只按「直接先修数」排 —— 直接先修 5 个的节点，追溯上去可能只有一条短链，
    画面上一片黑，看不出这是知识图谱。按 traceBack 实际能追溯到的深度挑才好看。
    只在初中段里选：高亮色，且五上六下的数学跟小学没有先修边，演示效果差。
    """
    import re
    html = SRC.read_text(encoding="utf-8")
    m = re.search(r'<script id="data" type="application/json">(.*?)</script>', html, re.S)
    if not m:
        sys.exit("读不出 payload")
    d = json.loads(m.group(1).replace("<\\/", "</"))
    pre, unlocks = {}, {}
    for succ, p in d["edges"]:                 # edges 契约：[后继, 先修]
        pre.setdefault(succ, []).append(p)
        unlocks.setdefault(p, []).append(succ)

    CAP = 70                                   # 与页面 traceBack(id, 70) 的上限一致
    def depth(i):
        seen, stack = {i}, [i]
        while stack:
            for q in pre.get(stack.pop(), ()):
                if q not in seen:
                    seen.add(q)
                    if len(seen) > CAP:
                        return len(seen)
                    stack.append(q)
        return len(seen)

    best = None
    for n in d["nodes"]:
        if not n[9]:                           # core = 初中段
            continue
        nb, ub = len(pre.get(n[0], [])), len(unlocks.get(n[0], []))
        if nb < 2 or ub < 1:                    # 卡片上「先掌握 N 个 / 解锁 M 个」不能是 0 或 1
            continue
        dp = depth(n[0])
        if dp < 6:                              # 链太短，画面上撑不起「前置链」这件事
            continue
        score = dp * 10 + min(ub, 9)
        if best is None or score > best[0]:
            best = (score, n, dp, nb, ub)
    if best is None:
        sys.exit("没挑出合适的演示节点")
    _, n, dp, nb, ub = best
    print(f"演示节点: {n[1]}（{n[4]}）先修 {nb} 个 / 解锁 {ub} 个 / 追溯深度 {dp}")
    return n[0]


def shoot(html, params, out, budget=1600):
    """截一帧。--virtual-time-budget 让页面在快进的时间里稳定下来再截。"""
    out.parent.mkdir(parents=True, exist_ok=True)   # 目录不存在时 Chrome 会静默不写
    url = f"file://{html.resolve()}?{params}"
    cmd = [CHROME, "--headless", "--disable-gpu", "--hide-scrollbars",
           f"--window-size={W},{H}", f"--virtual-time-budget={budget}",
           f"--screenshot={out}", url]
    r = subprocess.run(cmd, capture_output=True)
    if not out.exists():
        sys.exit(f"截图失败: {url}\n{r.stderr.decode()[:400]}")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--test", action="store_true", help="只出 2 帧验管线")
    ap.add_argument("--budget", type=int, default=1600, help="每帧的虚拟时间预算(ms)")
    args = ap.parse_args()

    if not SRC.exists():
        sys.exit(f"先跑 build_viz.py，没有 {SRC}")
    html = build_html()

    if args.test:
        for i, th in enumerate((-0.62, 1.95)):
            shoot(html, f"th={th}", SHOTS / f"t{i:04d}.png", args.budget)
        print(f"测试帧已出: {SHOTS}")
        return

    for f in SHOTS.glob("*.png"):
        f.unlink()

    demo = pick_demo_node()
    plan = []          # (参数, 说明)

    # A 段：整体转一圈，看清锥形全貌
    N_A = 96
    for i in range(N_A):
        plan.append((f"th={-0.62 + 2*3.14159265*i/N_A:.4f}", "旋转"))

    # B 段：钉住视角，点开一个节点，展示前置链与信息卡
    N_B = 48
    for i in range(N_B):
        plan.append((f"th=1.95&focus={demo}&card={demo}&d=1380", "聚焦"))

    t0 = time.time()
    for i, (params, _tag) in enumerate(plan):
        shoot(html, params, SHOTS / f"{i:04d}.png", args.budget)
        if i % 12 == 0:
            el = time.time() - t0
            eta = el / (i + 1) * (len(plan) - i - 1)
            print(f"  {i+1}/{len(plan)}  已用 {el:.0f}s  预计还要 {eta:.0f}s", flush=True)

    cmd = ["ffmpeg", "-y", "-framerate", str(FPS), "-i", str(SHOTS / "%04d.png"),
           "-c:v", "libx264", "-preset", "slow", "-crf", "20",
           "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(OUT)]
    subprocess.run(cmd, check=True, capture_output=True)
    dur = len(plan) / FPS
    print(f"\n{len(plan)} 帧 / {FPS}fps = {dur:.1f}s")
    print(f"输出 {OUT}  ({OUT.stat().st_size/1024/1024:.1f} MB)")
    shutil.rmtree(SHOTS, ignore_errors=True)


if __name__ == "__main__":
    main()
