#!/usr/bin/env python3
"""
在 github.com:443 不通、但 api.github.com 通的环境下推送。

git push 走 github.com，这条链路在本机反复超时；GitHub 的 Git Data API 走
api.github.com，是通的。所以用 API 直接建 blob → tree → commit → ref。

为什么要这么绕：不是图省事，是为了让 **commit SHA 跟本地完全一致**。
SHA 由 tree、parent、作者名/邮箱/时间戳、提交信息共同决定；这四项原样传给
API，GitHub 算出来的 SHA 就跟本地 git 算出来的一模一样。本地与远端不会分叉，
以后网络通了直接 git push 也是 up to date，而不是要先 pull --rebase。

跑:  python3 src/push_via_api.py
"""
import base64
import datetime as dt
import json
import pathlib
import re
import subprocess
import sys

BASE = pathlib.Path(__file__).resolve().parent.parent
OWNER, REPO = "Joshhuang123", "chinese-k12-knowledge-graph"
API = f"https://api.github.com/repos/{OWNER}/{REPO}"


def git(*a):
    r = subprocess.run(["git", *a], cwd=BASE, capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else None


def git_path(*a):
    """
    处理文件路径的 git 调用。

    必须关掉 core.quotepath：默认 git 会把中文路径输出成八进制转义并加引号，
    「viz/录屏.mp4」会变成 "viz/\\345\\275\\225\\345\\261\\217.mp4"，
    拿这个字符串当真实路径去用，后面每一步都会错，而且不一定当场报错。
    """
    r = subprocess.run(["git", "-c", "core.quotepath=false", *a],
                       cwd=BASE, capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else None


def gh(method, path, payload=None):
    """走 gh CLI 调 API。它自带 token 和重试，不用自己管认证。"""
    cmd = ["gh", "api", "--method", method, path]
    if payload is not None:
        cmd += ["--input", "-"]
    r = subprocess.run(cmd, input=json.dumps(payload) if payload is not None else None,
                       capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f"{method} {path} 失败:\n{r.stderr[:500]}")
    return json.loads(r.stdout) if r.stdout.strip() else None


def bootstrap():
    """
    空仓库不允许建 blob（POST /git/blobs 返回 409 Git Repository is empty）。
    先用 Contents API 垫一个提交把仓库点亮，再走 Git Data API。

    这个垫底提交在最后 main 指向本地 commit 之后就成了不可达对象，
    会被 GitHub 回收，不留在历史里。它只是开锁用的，不是内容。

    判据必须是「仓库有没有提交」，**不能**是「.bootstrap 文件在不在」。
    原来用后者：而成功的推送恰恰会把 .bootstrap 从 main 上移除，
    于是仓库推过一次之后，判据必然为假 → 每次推送都误判成空仓库 →
    又垫一个。若后续 force-update 恰好失败（网络抖动），
    main 就卡在那个垫底提交上，SHA 和本地对不上、历史凭空多一个节点。
    实际踩过：EOF + 401 两次失败后，main 停在 df1af335(bootstrap)，
    而本地 HEAD 是别的 SHA。
    """
    # 查仓库有没有 commit。有就直接跳过初始化。
    # 注意 gh api 的选项必须放在端点**之前**，写成 endpoint --jq x -F y=1
    # 会被 gh 误解析（实测返回空串），然后被当成「仓库为空」去垫底 —— 比不判断更糟。
    chk = subprocess.run(
        ["gh", "api", f"{API}/commits?per_page=1", "--jq", "length"],
        capture_output=True, text=True)
    out = chk.stdout.strip()
    if chk.returncode == 0 and out.isdigit():
        if int(out) > 0:
            print("   仓库已有提交，跳过初始化")
            return
    else:
        # 判据本身没跑出结果时，绝不能默认「那就垫一个」。
        # 查不到 ≠ 空仓库，垫底是有副作用的写操作。
        err = chk.stderr.strip().replace("\n", " ")[:200]
        sys.exit(f"判断仓库是否为空时没有得到可解析的结果（stdout={out!r}）"
                 f"，不敢继续：\n{err or '(无 stderr)'}")
    r = subprocess.run(
        ["gh", "api", "--method", "PUT", f"{API}/contents/.bootstrap",
         "-f", "message=bootstrap", "-f", "content=Ym9vdHN0cmFwCg=="],
        capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f"初始化失败:\n{r.stderr[:300]}")
    print("   空仓库已点亮（垫底提交随后不可达）")


def commit_meta():
    """
    从 git 对象里取提交元数据，要原始字节，不能走 --format。

    两个坑：
    1. 提交信息末尾的换行是 git 对象的一部分。走 %B 再 strip 掉，
       重建出来的 commit 必然差一个 SHA —— tree 和 blob 全对，只有 commit 不对。
    2. 作者时间带时区，%aI 输出 ISO 8601 没问题，但要和对象里的
       <unix_ts> <tz> 严格等价，用 cat-file 的原始值最稳。
    """
    raw = subprocess.run(["git", "cat-file", "commit", "HEAD"],
                         cwd=BASE, capture_output=True).stdout
    head, _, msg = raw.partition(b"\n\n")
    # 格式固定为 `author 名字 <邮箱> unix时间戳 时区`，严格匹配。
    # 别用 rsplit 去剥尖括号 —— 尖括号在字符串中间，rstrip 削不掉，
    # 邮箱会带上尾巴传上去，commit 就对不上了。
    pat = re.compile(r"^(author|committer) (.+) <([^<>]+)> (\d+) ([+-]\d{4})$")
    meta = {}
    for line in head.decode("utf-8").splitlines():
        m = pat.match(line)
        if m:
            key, name, email, ts, tz = m.groups()
            meta[key] = {"name": name, "email": email,
                         "date": iso_from_git(int(ts), tz)}
    if set(meta) != {"author", "committer"}:
        sys.exit(f"提交头解析失败：{head.decode('utf-8')[:300]}")
    return meta["author"], meta["committer"], msg.decode("utf-8")


def iso_from_git(ts, tz):
    """
    git 对象里的时间是 `<unix秒> <±HHMM>`，API 要 ISO 8601。
    时区必须原样带过去：转成 UTC 再补 +00:00 是另一回事，
    同一个瞬间两种写法，GitHub 那边算出来就不是同一个字符串。
    """
    sign = 1 if tz[0] == "+" else -1
    off = dt.timedelta(hours=int(tz[1:3]), minutes=int(tz[3:5])) * sign
    return dt.datetime.fromtimestamp(ts, dt.timezone(off)).isoformat()


def main():
    head = git("rev-parse", "HEAD")
    local_tree = git("rev-parse", "HEAD^{tree}")
    author, committer, message = commit_meta()

    entries = []
    for line in git_path("ls-tree", "-r", "HEAD").splitlines():
        meta, path = line.split("\t", 1)
        mode, _typ, sha = meta.split()
        entries.append((mode, path, sha))
    print(f"本地 HEAD {head[:10]}  tree {local_tree[:10]}  {len(entries)} 个文件\n")

    print("⓪ 初始化仓库")
    bootstrap()

    # ── 1. blob：先确认工作区内容与 HEAD 一致，再逐个传 ──
    print("\n① 建 blob")
    blobs = {}
    for mode, path, sha in entries:
        # 工作区被改过就停：推上去会和本地分叉，而分叉在 github.com 不通时
        # 本地还拉不回来，等于把仓库搞成两套真相
        if git_path("hash-object", "--", path) != sha:
            sys.exit(f"{path} 工作区内容与 HEAD 不一致，先提交或还原再推")
        res = gh("POST", f"{API}/git/blobs",
                 {"content": base64.b64encode((BASE / path).read_bytes()).decode(),
                  "encoding": "base64"})
        if res["sha"] != sha:
            sys.exit(f"{path} blob 不一致: API {res['sha'][:10]} vs 本地 {sha[:10]}")
        blobs[path] = sha
        print(f"   ✓ {path}  {sha[:10]}")

    # ── 2. tree ──
    print("\n② 建 tree")
    tree = gh("POST", f"{API}/git/trees",
              {"base_tree": None,
               "tree": [{"path": p, "mode": m, "type": "blob", "sha": blobs[p]}
                        for m, p, _ in entries]})
    print(f"   API tree {tree['sha'][:10]}  本地 tree {local_tree[:10]}")
    if tree["sha"] != local_tree:
        sys.exit("tree 不一致，中止 —— 推上去会和本地分叉")

    # ── 3. commit：作者/时间/消息原样传，SHA 才能对上 ──
    # 父提交必须从本地读。写死空数组只在首个（根）提交时碰巧是对的，
    # 一旦有第二个提交就会算出另一个 SHA，而且报错信息只看得出「不一致」，
    # 看不出差在哪。
    parents = git("rev-list", "--parents", "-n", "1", head).split()[1:]
    print("\n③ 建 commit")
    print(f"   父提交: {parents or '（根提交）'}")
    c = gh("POST", f"{API}/git/commits",
           {"message": message, "tree": local_tree, "parents": parents,
            "author": author, "committer": committer})
    print(f"   API commit {c['sha'][:10]}  本地 commit {head[:10]}")
    if c["sha"] != head:
        sys.exit("commit SHA 不一致，中止")

    # ── 4. ref ──
    # 必须 force：本地是根提交（无 parent），而 main 指向垫底提交，
    # 两者无祖先关系，不 force 推不上去。force 在这里是安全的，
    # 被丢弃的只有刚建的那个垫底提交。
    print("\n④ 更新 main")
    gh("PATCH", f"{API}/git/refs/heads/main", {"sha": head, "force": True})
    print(f"   main -> {head[:10]}")

    # 垫底文件理应已经随 tree 一起消失（我们的 tree 里没有它）。
    # 用容错探测确认一下，别让一个 404 把脚本带崩。
    print("\n⑤ 收尾检查")
    r = subprocess.run(["gh", "api", f"{API}/contents/.bootstrap?ref=main"],
                       capture_output=True, text=True)
    if r.returncode == 0:
        sys.exit("垫底文件还在 main 上，需要手动删一次："
                 f"gh api --method DELETE '{API}/contents/.bootstrap?ref=main'")
    print("   ✓ 垫底文件已不在 main 上")


if __name__ == "__main__":
    main()
