#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""修复被 iCloud 卸载成 dataless 的 .git/index。

为什么需要这个工具：
  本仓库在 `~/Documents` 下，而 `~/Documents` 开着 iCloud「桌面与文稿」同步。
  macOS 的「优化存储」会把**很少访问**的文件卸载成本地空壳（`dataless` 标记），
  读它要先从 iCloud 拉回来 —— 网络一慢，`git status` 就报：

      fatal: .git/index: unable to map index file: Operation timed out

  ⚠️ 这**不是仓库坏了**，只是文件内容不在本地。
  判据：`stat -f "%Sf" .git/index` 里出现 `dataless`。

怎么修（关键：不能用 `cp`）：
  `cp` 打开目标写入时，要先把 dataless 文件拉回来 → 一样超时。
  必须用**原子改名**（rename 不需要打开目标）：
    1. 在别处建一份新 index（`git read-tree HEAD` —— 只写不读旧 index）
    2. `os.replace()` 把它改名盖上去

用法：python3 src/fix_git_index.py [--check]
"""
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IDX = os.path.join(ROOT, '.git', 'index')


def is_dataless(path):
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        return False
    # macOS 的 UF_DATALESS 标志
    return bool(getattr(st, 'st_flags', 0) & 0x40000000)


def main():
    if not os.path.exists(IDX):
        print('没有 .git/index —— 这不是 git 仓库？')
        return 1
    st = os.stat(IDX)
    flags = st.st_flags if hasattr(st, 'st_flags') else 0
    dataless = bool(flags & 0x40000000)
    print(f'.git/index: {st.st_size} 字节 · dataless={dataless}')

    if '--check' in sys.argv:
        return 0

    if not dataless:
        print('index 是正常的，不需要修。')
        return 0

    with tempfile.NamedTemporaryFile(prefix='kgidx-', suffix='.new', delete=False) as tf:
        tmp = tf.name
    env = dict(os.environ, GIT_INDEX_FILE=tmp)
    subprocess.run(['git', 'read-tree', 'HEAD'], cwd=ROOT, env=env, check=True)
    shutil.copyfile(tmp, tmp + '.2')
    os.replace(tmp + '.2', IDX)          # ← 原子改名，不打开目标文件
    os.unlink(tmp)

    st2 = os.stat(IDX)
    still = bool(getattr(st2, 'st_flags', 0) & 0x40000000)
    print(f'已重建并原子替换 · {st2.st_size} 字节 · dataless={still}')
    if still:
        print('⚠️ 还是 dataless —— 可能是 iCloud 又把它卸载了，等网络恢复再跑一次。')
        return 1
    print('✅ git 可以用了。')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
