#!/usr/bin/env bash
#
# 拉取 K12-KGraph 原始数据，并逐个验 SHA-256。
#
#   ./fetch.sh
#   ./fetch.sh --force     # 已有文件也重新拉
#
# 为什么不在仓库里直接带数据：
#   原件是 CC BY-NC-SA 4.0，署名 + 非商用 + 相同方式共享。
#   塞进仓库等于替上游做了一次再分发，许可链就断了。
#   这里只写下载和校验，出处交给 README 和本文件的抬头。
#
# 数据出处：
#   K12-KGraph · 北京大学 PKU-DCAI
#   Hao Liang, Qihan Lin, Mingrui Chen, Hengyi Feng, Zhaoyang Han,
#   Xiaochen Ma, Zhen Hao Wong, Meiyi Qiang, Linzhuang Sun, Wentao Zhang
#   arXiv:2605.09635 (v4) · NeurIPS 2026 Evaluations & Datasets Track
#   数据集: https://huggingface.co/datasets/lhpku20010120/K12-KGraph
#
# 为什么默认走 hf-mirror：
#   直连 huggingface.co 在部分网络下不通，hf-mirror 是同一份文件的镜像。
#   先试官方地址，失败自动回退，两个都不通就报错退出，不要静默拿到半个文件。

set -euo pipefail

REPO="lhpku20010120/K12-KGraph"
DEST="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/data/raw"
MIRROR="https://hf-mirror.com"
OFFICIAL="https://huggingface.co"

FORCE=0
[ "${1:-}" = "--force" ] && FORCE=1

# 站点只探一次，不逐个文件探。
# 官方站在部分网络下不通，每个文件都探一次的话，6 个文件要先白等 90 秒
# 才轮得到镜像 —— 能下但让人以为卡死了。
pick_base() {
  echo -n "  探测 huggingface.co … " >&2
  if curl -fsSI --connect-timeout 8 -o /dev/null "$OFFICIAL/datasets/$REPO/resolve/main/K12-KGraph/global_KG/nodes.json"; then
    echo "直连可用" >&2; echo "$OFFICIAL"; return 0
  fi
  echo "不通，改用 hf-mirror" >&2; echo "$MIRROR"
}

# 文件  SHA-256（2026-10-18 取自 v4 配套数据）
read -r -d '' MANIFEST <<'EOF' || true
b7b2bea4a16467b59e30102c8efacfd29c1194703c5792c456ea5d4664aea264  global_KG/edges.json
99d7d4b86e7c92f601bd7e9f35e712443d15b848c68d1ecb196681e52a640cda  global_KG/nodes.json
c775d68709aaca2c40dbb50fad1e8e9374ac192302fa3856c76b022c012a8996  subject_specific_KG/biology.json
6441ec8e247f85350c0b3f594cde65ac9511e8b280ae7f8e093a1d59c82f3059  subject_specific_KG/chemistry.json
00ed25179bb4ad096c53b3965fe84a32afa708850de85db5ea4c9e0bacec8f14  subject_specific_KG/math.json
2108bcb685554ecb9e9cf61234d45c8accc9416624b8e52819d1ca7583055766  subject_specific_KG/physics.json
EOF

echo "数据源: $REPO"
echo "目标:   $DEST"
echo

mkdir -p "$DEST"

fetch_one() {
  local rel="$1" out="$DEST/$1" base="$2"
  mkdir -p "$(dirname "$out")"

  if [ -s "$out" ] && [ "$FORCE" -eq 0 ]; then
    echo "  已存在，跳过: $rel"
    return 0
  fi
  # 下载到 .part 再改名：中断的半个文件绝不能顶着正式文件名存在
  if curl -fsSL --connect-timeout 15 -o "$out.part" "$base/datasets/$REPO/resolve/main/K12-KGraph/$rel"; then
    mv "$out.part" "$out"
    echo "  已拉取: $rel  (来自 $base)"
    return 0
  fi
  rm -f "$out.part"
  echo "  ✗ 拉取失败: $rel" >&2
  return 1
}

BASE="$(pick_base)"
echo "用这个源: $BASE"
echo

# 注意：管道会开子 shell，循环里的非零退出会传不出来。
# 所以这里用 for + 临时文件，不走管道。
TMPMAN="$(mktemp)"
trap 'rm -f "$TMPMAN"' EXIT
echo "$MANIFEST" > "$TMPMAN"
rc=0
while read -r sum rel; do
  [ -z "${rel:-}" ] && continue
  fetch_one "$rel" "$BASE" || rc=1
done < "$TMPMAN"
[ "$rc" -eq 0 ] || { echo "有文件没拉下来，先别往下跑。" >&2; exit 1; }

echo
echo "── 校验 SHA-256 ──"
fail=0
while read -r sum rel; do
  [ -z "${rel:-}" ] && continue
  f="$DEST/$rel"
  if [ ! -f "$f" ]; then
    echo "  ✗ 缺失: $rel"; fail=1; continue
  fi
  got="$(shasum -a 256 "$f" | cut -d' ' -f1)"
  if [ "$got" = "$sum" ]; then
    echo "  ✓ $rel"
  else
    echo "  ✗ $rel"
    echo "      期望 $sum"
    echo "      实际 $got"
    fail=1
  fi
done <<< "$MANIFEST"

echo
if [ "$fail" -ne 0 ]; then
  echo "校验未通过：文件与预期不符，不要基于这批数据往下跑。"
  exit 1
fi

echo "全部一致。接下来："
echo "  python3 src/normalize.py    # 原件 → 归一化"
echo "  python3 src/validate.py     # 校验（当前会 exit 1：上游有 2 个环）"
echo "  python3 src/build_viz.py    # 生成 viz/知识图谱3D.html"
