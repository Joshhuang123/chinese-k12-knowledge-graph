#!/usr/bin/env python3
"""密度提升的归因实验：布局 × cen 各自贡献多少。

背景：上海站视觉上稀疏，本轮同时改了两处 ——
  ① 模板布局自适应（层高按 √n、圈半径按点数）
  ② 上海站补 cen（原来硬编码 0.0，点半径全是 0.78px）

两处一起改，谁贡献了多少**不能靠猜**。
本脚本组装变体页面（同一份 payload，只换布局和 cen），
交给 measure_density.mjs 实测像素密度。

⚠️ 变体模板的造法：**从当前模板改布局常量**，
不从 git HEAD 取旧模板 —— 旧模板没有 probe 出口（__kg.proj），
测量脚本读不到真实投影，两个变体口径就不一致了，
那就不是「只改一个变量」了。

跑:  python3 src/ablate_density.py
输出: /tmp/ablate/*.html + 实测表
"""
import json
import pathlib
import re
import subprocess
import sys

BASE = pathlib.Path(__file__).resolve().parent.parent
TPL = BASE / "viz" / "template.html"
OUTDIR = pathlib.Path("/tmp/ablate")

RE_DATA = re.compile(r'<script id="data" type="application/json">(.*?)</script>', re.S)
SITES = ["index.html", "shanghai.html", "kx.html"]


def get_payload(path: pathlib.Path) -> str:
    h = path.read_text(encoding="utf-8")
    m = RE_DATA.search(h)
    if not m:
        raise SystemExit(f"payload 找不到: {path}")
    return m.group(1)


def zero_cen(payload: str) -> str:
    d = json.loads(payload)
    for n in d["nodes"]:
        n[8] = 0.0
    return json.dumps(d, ensure_ascii=False, separators=(",", ":"))


def to_old_layout(tpl: str) -> str:
    """把自适应布局换回写死布局（只动布局，不动别的）。"""
    marks = [
        ("const R_PER_SQRT = 4.54;",
         "const layerR = Math.max(R_MIN, R_PER_SQRT * Math.sqrt(Math.max(n, 1)));",
         "const layerR = 52 + ((age - A0) / (A1 - A0)) * 250;"),
        ("    node.y = LAYER_Y[li];",
         "    node.y = LAYER_Y[li];",
         "    node.y = (li - (AGES.length-1)/2) * 58;"),
        ("    const y = LAYER_Y[li];",
         "    const y = LAYER_Y[li];",
         "    const y = (li - (AGES.length-1)/2) * 58;"),
    ]
    for anchor, old, new in marks:
        if old not in tpl:
            raise SystemExit(f"模板里找不到：{old!r}（结构变了？）")
        tpl = tpl.replace(old, new, 1)
    return tpl


def main() -> int:
    OUTDIR.mkdir(parents=True, exist_ok=True)
    tpl_new = TPL.read_text(encoding="utf-8")
    tpl_old = to_old_layout(tpl_new)

    files = []
    for site in SITES:
        src = BASE / site
        if not src.exists():
            print(f"跳过 {site}（没构建）")
            continue
        payload = get_payload(src)
        payload_nocen = zero_cen(payload)
        tag = site.replace(".html", "")
        for vname, (tpl, pl) in {
            f"{tag}__new_cen":   (tpl_new, payload),
            f"{tag}__new_nocen": (tpl_new, payload_nocen),
            f"{tag}__old_cen":   (tpl_old, payload),
            f"{tag}__old_nocen": (tpl_old, payload_nocen),
        }.items():
            if "__DATA__" not in tpl:
                raise SystemExit(f"{vname}: 模板里没有 __DATA__ 占位")
            out = OUTDIR / f"{vname}.html"
            out.write_text(tpl.replace("__DATA__", pl), encoding="utf-8")
            # ⚠️ **导航链接的占位符也要替换** ——
            #   模板里的 5 条导航链接用的是 __LEARN_BASE__ 系列占位符
            #   （按产物所在深度给相对路径）。
            #   这些分析页输出到 /tmp，不上线，但占位符留着的话
            #   那个页子里的学习页链接是坏的（点进去是个不存在的路径）。
            for ph, page in (("__LEARN_BASE__", "learn.html"),
                             ("__LEARN_BASE_QUALITY__", "quality.html"),
                             ("__LEARN_BASE_DATA__", "data.html"),
                             ("__LEARN_BASE_SH__", "shanghai.html"),
                             ("__LEARN_BASE_KX__", "kx.html")):
                out.write_text(out.read_text(encoding="utf-8").replace(ph, "./" + page),
                               encoding="utf-8")
            files.append(str(out))

    print(f"实测中…（{len(files)} 个变体）\n")
    r = subprocess.run(
        ["node", str(BASE / "src" / "measure_density.mjs"), *files],
        capture_output=True, text=True,
    )
    print(r.stdout)
    if r.returncode != 0:
        print(r.stderr, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
