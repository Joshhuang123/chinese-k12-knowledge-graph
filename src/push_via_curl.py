#!/usr/bin/env python3
"""
用 curl 推送到 GitHub —— 绕开 `gh api`。

## 为什么要有这个

`push_via_api.py` 走 `gh api`，而这台机器上 `gh api` 读 commit 时
**反复 EOF**（curl 打同一个 api.github.com 是 200）：

```
Get "https://api.github.com/repos/.../git/commits/xxx": EOF
```

GitHub API 走 HTTP/2，gh CLI 的连接在这个网络下容易被中途掐断；
curl 的 HTTP/1.1 + `--retry` 稳得多。

**token 仍从 gh 的本地 keyring 取**（`gh auth token` 不走网络），
所以认证方式没变。

**不重写推送逻辑**，只换传输层：把 `gh api` 换成 curl，
其余（blob → tree → commit → update ref）完全一样。

## 跑法

```bash
python3 src/push_via_curl.py
"""
import json
import pathlib
import subprocess
import sys
import time
import urllib.error
import urllib.request

BASE = pathlib.Path(__file__).resolve().parent.parent
API = "https://api.github.com/repos/Joshhuang123/chinese-k12-knowledge-graph"


def token():
    r = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True)
    t = r.stdout.strip()
    if not t:
        sys.exit("拿不到 token（gh auth token 失败）")
    return t


TOK = None
BLOB_CACHE = {}


def api(method, path, payload=None, tries=6):
    """curl 版的 GitHub API 调用。带重试 —— 网络抖是常态，不是意外。"""
    global TOK
    if TOK is None:
        TOK = token()
    url = path if path.startswith("http") else API + path
    body = json.dumps(payload).encode() if payload is not None else None
    last = None
    for i in range(tries):
        cmd = ["curl", "-sS", "-X", method, url,
               "-H", f"Authorization: Bearer {TOK}",
               "-H", "Accept: application/vnd.github+json",
               "-H", "X-GitHub-Api-Version: 2022-11-28",
               "--max-time", "60", "--retry", "2", "--retry-delay", "2",
               "-w", "\n%{http_code}"]
        if body is not None:
            cmd += ["-H", "Content-Type: application/json", "--data-binary", "@-"]
        # text=False：blob 内容是二进制，text=True 时 subprocess 会拿 str 去 encode
        r = subprocess.run(cmd, input=body, capture_output=True)
        out = r.stdout.decode("utf-8", "replace")
        code = out.rsplit("\n", 1)[-1].strip() if "\n" in out else "000"
        if code == "200" or code == "201":
            try:
                return json.loads(out.rsplit("\n", 1)[0])
            except json.JSONDecodeError:
                return None
        last = f"{code} {out[:200]}"
        if code in ("401", "403", "404", "422"):
            break                      # 这些重试没用
        time.sleep(2 + i * 2)
    raise RuntimeError(f"{method} {path} 失败: {last}")


def git(*a):
    r = subprocess.run(["git", "-c", "core.quotepath=false", *a],
                       cwd=BASE, capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else None


def main():
    head = git("rev-parse", "HEAD")
    if not head:
        sys.exit("拿不到本地 HEAD")
    print(f"本地 HEAD {head[:8]}")

    # 远端当前 commit
    try:
        cs = api("GET", f"/commits?per_page=1")
        remote = cs[0]["sha"] if cs else None
    except Exception as e:
        print(f"查远端失败：{e}")
        remote = None
    print(f"远端 main  {remote[:8] if remote else '（查不到）'}")

    if remote == head:
        print("✓ 已经是最新")
        return 0

    # 远端有、本地没有的 commit？
    if remote:
        r = subprocess.run(["git", "cat-file", "-e", remote],
                           cwd=BASE, capture_output=True)
        if r.returncode != 0:
            print(f"⚠ 远端 commit {remote[:8]} 本地没有，可能被 force 推过，先停下")
            return 1

    # 本地未推的 commit（从远端之后开始）
    if remote:
        rng = f"{remote}..{head}"
    else:
        rng = head
    commits = git("rev-list", "--reverse", rng)
    commits = (commits or "").split("\n")
    commits = [c for c in commits if c]
    print(f"待推 {len(commits)} 个 commit")

    for sha in commits:
        msg = git("log", "-1", "--format=%B", sha)
        aname = git("log", "-1", "--format=%an", sha)
        aemail = git("log", "-1", "--format=%ae", sha)
        when = git("log", "-1", "--format=%aI", sha)
        tree = git("rev-parse", f"{sha}^{{tree}}")
        parent = git("rev-parse", f"{sha}^")
        # blob
        files = git("ls-tree", "-r", "--name-only", sha).split("\n")
        tree_items = []
        for f in files:
            if not f.strip():
                continue
            mode, typ, blob = git("ls-tree", sha, "--", f).split("\t")[0].split()
            content = subprocess.run(["git", "cat-file", "blob", blob],
                                     cwd=BASE, capture_output=True).stdout
            # **blob 按内容缓存。** 10 个 commit 之间大部分文件没变，
            # 每个 commit 都重推一遍是白费 API 调用
            # （400 次调用 vs 实际只有 ~60 个不同内容）。
            key = blob            # 本地 blob sha 就是内容的 sha
            if key not in BLOB_CACHE:
                b = api("POST", "/git/blobs",
                        {"content": content.decode("utf-8", "replace"),
                         "encoding": "utf-8"})
                BLOB_CACHE[key] = b["sha"]
            tree_items.append({"path": f, "mode": mode, "type": "blob",
                               "sha": BLOB_CACHE[key]})
        # **不能带 base_tree** —— 那是本地 git 的 tree SHA，
        # 远端还没有（内容正是这次要推的），GitHub 会返回
        # 422 base_tree is not a valid tree oid。
        # 不带 base_tree 就是「用这批条目建一棵新树」，全量传。
        nt = api("POST", "/git/trees", {"tree": tree_items})
        c = api("POST", "/git/commits", {
            "message": msg, "tree": nt["sha"],
            "parents": [parent] if parent else [],
            # name / email / date 要**分开**传。
            # 合成 "名字 <邮箱>" 一串的话 GitHub 会回
            # 422 "email" wasn't supplied。
            "author": {"name": aname, "email": aemail, "date": when},
            "committer": {"name": aname, "email": aemail, "date": when},
        })
        r = api("PATCH", "/git/refs/heads/main", {
            "sha": c["sha"], "force": False})
        print(f"  ✓ {sha[:8]} → {c['sha'][:8]}  {msg.splitlines()[0][:40]}")

    print("\n推完，核对远端：")
    cs = api("GET", "/commits?per_page=1")
    print(f"  远端 main = {cs[0]['sha'][:8]}  本地 = {head[:8]}")
    print("✓ 一致" if cs[0]["sha"] == head else "✗ 不一致")
    return 0


if __name__ == "__main__":
    sys.exit(main())
