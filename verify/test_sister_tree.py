# ABOUTME: Holds verify/sister_tree.py offline (#1027): it lists only directories, at the ref asked, from a local git repo
# ABOUTME: the test builds; retries a network error and then names it; fails at once on any other; never reads the API.
"""In run 17993 the tools tier failed test_platform_baseline_sister.py on GitHub's anonymous REST quota, which every
run on the host shares (#1027). The sister's listing now comes from a shallow, blob-free git clone through
sister_tree.read(). This builds a repo shaped like the sister's solution/platform, with a file and a submodule under a
layer that must not be listed, and a second branch with other contents, and reads it over file://. The retries run
against a stub runner that fails as told before handing the call to git; the waits are recorded, never slept."""
from __future__ import annotations

import os
import pathlib
import re
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import sister_tree  # noqa: E402

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail and not ok else ""))
    if not ok:
        failures.append(name)


GIT_ENV = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
           "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid"}


def git(repo: pathlib.Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True,
                          env=GIT_ENV).stdout


def write(repo: pathlib.Path, rel: str, text: str = "x\n") -> None:
    p = repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


def build(root: pathlib.Path) -> str:
    """A repo with branch main shaped like the sister and branch other holding one layer; its file:// URL."""
    repo = root / "sister"
    repo.mkdir()
    git(repo, "init", "--quiet", "--initial-branch=main")
    for rel in ["README.md", "solution/platform/README.md", "solution/platform/0-bootstrap/root/app.yaml",
                "solution/platform/1-foundation/cert-manager/values.yaml", "solution/platform/1-foundation/keda/a.yaml",
                "solution/platform/1-foundation/notes.md", "solution/platform/2-ai-plane/litellm/values.yaml",
                "solution/platform/docs/x.md"]:
        write(repo, rel)
    git(repo, "add", "-A")
    # A submodule under a layer: a gitlink (mode 160000) is a commit, not a tree, and no component.
    git(repo, "update-index", "--add", "--cacheinfo",
        "160000,1111111111111111111111111111111111111111,solution/platform/1-foundation/vendored")
    git(repo, "commit", "--quiet", "-m", "main")
    git(repo, "checkout", "--quiet", "-b", "other")
    git(repo, "rm", "--quiet", "-r", "solution/platform/1-foundation", "solution/platform/2-ai-plane")
    write(repo, "solution/platform/9-only-here/thing/a.yaml")
    git(repo, "add", "-A")
    git(repo, "commit", "--quiet", "-m", "other")
    git(repo, "checkout", "--quiet", "main")
    return repo.as_uri()


def failing_runner(fail_times: int, stderr: str, calls: list[list[str]]):
    """A runner whose first `fail_times` clone calls exit 128 with `stderr`; every other call runs for real."""
    state = {"left": fail_times}

    def run(cmd, **kw):
        calls.append(list(cmd))
        if "clone" in cmd and state["left"] > 0:
            state["left"] -= 1
            return subprocess.CompletedProcess(cmd, 128, "", stderr)
        return subprocess.run(cmd, **kw)
    return run


def no_sleep(waits: list[float]):
    return waits.append


with tempfile.TemporaryDirectory() as td:
    url = build(pathlib.Path(td))
    said: list[str] = []

    print("== the listing holds directories only, at the ref asked ==")
    tree = sister_tree.read(url, "main", "solution/platform", sleep=no_sleep([]), say=said.append)
    check("the top level lists the four directories under solution/platform, and not its README",
          tree[""] == ["0-bootstrap", "1-foundation", "2-ai-plane", "docs"], str(tree.get("")))
    check("a layer lists its component directories, not the file or the submodule beside them",
          tree["1-foundation"] == ["cert-manager", "keda"], str(tree.get("1-foundation")))
    check("each top-level directory has its own listing, and there is no other key",
          sorted(tree) == ["", "0-bootstrap", "1-foundation", "2-ai-plane", "docs"]
          and tree["2-ai-plane"] == ["litellm"] and tree["docs"] == [], str(tree))
    check("a read that worked first time prints no retry", said == [], str(said))
    other = sister_tree.read(url, "other", "solution/platform", sleep=no_sleep([]), say=said.append)
    check("the ref is honoured: branch other's tree is read, not main's",
          other[""] == ["0-bootstrap", "9-only-here", "docs"] and other["9-only-here"] == ["thing"], str(other))
    check("an empty path lists the repo's root", sister_tree.read(url, "main", "")[""] == ["solution"])

    print("== a ref or path that is not there fails at once, with git's words ==")
    calls: list[list[str]] = []
    waits: list[float] = []
    try:
        sister_tree.read(url, "no-such-branch", "solution/platform", run=failing_runner(0, "", calls),
                         sleep=no_sleep(waits))
        got = "no error"
    except sister_tree.SisterReadError as e:
        got = str(e)
    check("a missing ref raises SisterReadError naming the ref and git's words",
          "at no-such-branch failed (attempt 1 of 4)" in got and "no-such-branch" in got.split(": ", 1)[-1], got)
    check("a missing ref is not retried", len([c for c in calls if "clone" in c]) == 1 and waits == [], str(calls))
    try:
        sister_tree.read(url, "main", "solution/nowhere")
        got = "no error"
    except sister_tree.SisterReadError as e:
        got = str(e)
    check("a missing path raises SisterReadError naming HEAD:<path>", "HEAD:solution/nowhere" in got, got)

    print("== a network error is retried, each retry printed, and then the read goes on ==")
    calls, waits, said = [], [], []
    tree = sister_tree.read(url, "main", "solution/platform",
                            run=failing_runner(2, "fatal: unable to access 'https://github.com/x/y.git/': "
                                                  "Could not resolve host: github.com\n", calls),
                            sleep=no_sleep(waits), say=said.append)
    check("two failed name lookups, then a clone that works, read the whole tree",
          tree["1-foundation"] == ["cert-manager", "keda"], str(tree))
    check("it waited BACKOFF's first two waits, in order", waits == list(sister_tree.BACKOFF[:2]), str(waits))
    check("each retry is printed with the attempt and git's words",
          len(said) == 2 and "attempt 1 of 4" in said[0] and "attempt 2 of 4" in said[1]
          and all("RETRY" in s and "Could not resolve host" in s for s in said), str(said))
    check("each clone attempt asks for one commit with no blobs and no checkout",
          all({"--depth", "1", "--filter=blob:none", "--no-checkout", "--branch", "main"} <= set(c)
              for c in calls if "clone" in c), str(calls))

    print("== the last network error fails, naming every attempt ==")
    calls, waits, said = [], [], []
    try:
        sister_tree.read(url, "main", "solution/platform",
                         run=failing_runner(99, "error: RPC failed; HTTP 503 curl 22 The requested URL returned "
                                                "error: 503\nfatal: expected flush after ref listing\n", calls),
                         sleep=no_sleep(waits), say=said.append)
        got = "no error"
    except sister_tree.SisterReadError as e:
        got = str(e)
    check("a 503 on every attempt raises after ATTEMPTS clones",
          len([c for c in calls if "clone" in c]) == sister_tree.ATTEMPTS, str(len(calls)))
    check("the error names the last attempt and git's words", f"attempt {sister_tree.ATTEMPTS} of "
          f"{sister_tree.ATTEMPTS}" in got and "503" in got, got)
    check("it waited every BACKOFF wait, and printed one retry for each", waits == list(sister_tree.BACKOFF)
          and len(said) == len(sister_tree.BACKOFF), f"{waits} {said}")

    print("== a timed-out clone is a network error ==")
    calls, waits = [], []

    def timing_out(cmd, **kw):
        calls.append(list(cmd))
        if "clone" in cmd and len(calls) == 1:
            raise subprocess.TimeoutExpired(cmd, sister_tree.TIMEOUT)
        return subprocess.run(cmd, **kw)
    tree = sister_tree.read(url, "main", "solution/platform", run=timing_out, sleep=no_sleep(waits), say=[].append)
    check("a clone that timed out is tried again, and the second reads the tree",
          tree[""][:1] == ["0-bootstrap"] and waits == [sister_tree.BACKOFF[0]], f"{tree} {waits}")

print("== which words are a network error ==")
for text in ["fatal: unable to access 'https://github.com/a/b.git/': Could not resolve host: github.com",
             "fatal: unable to access 'https://github.com/a/b.git/': Failed to connect to github.com port 443",
             "fatal: unable to access 'https://github.com/a/b.git/': Connection timed out after 300001 milliseconds",
             "fatal: unable to access 'https://github.com/a/b.git/': gnutls_handshake() failed: Error in the pull",
             "fatal: unable to access 'https://github.com/a/b.git/': The requested URL returned error: 429",
             "error: RPC failed; curl 56 Recv failure: Connection reset by peer",
             "fatal: early EOF", "fatal: the remote end hung up unexpectedly"]:
    check(f"network: {text[-60:]}", sister_tree.is_network_error(text))
for text in ["warning: Could not find remote branch nope to clone.\nfatal: Remote branch nope not found in upstream "
             "origin", "remote: Repository not found.\nfatal: repository 'https://github.com/a/b.git/' not found",
             "fatal: could not read Username for 'https://github.com': terminal prompts disabled",
             "fatal: Not a valid object name HEAD:solution/nowhere",
             "fatal: unable to access 'https://github.com/a/b.git/': The requested URL returned error: 403"]:
    check(f"not network: {text.splitlines()[-1][-60:]}", not sister_tree.is_network_error(text))

print("== the sister test reads through sister_tree, and nothing reads the REST API ==")
for name in ["test_platform_baseline_sister.py", "sister_tree.py"]:
    src = (HERE / name).read_text(encoding="utf-8")
    code = "\n".join(ln for ln in src.splitlines() if not ln.lstrip().startswith("#"))
    code = re.sub(r'"""[\s\S]*?"""', "", code)
    check(f"{name} has no urllib read and no api.github.com URL in its code",
          "urllib" not in code and "urlopen" not in code and "api.github.com" not in code
          and "GITHUB_TOKEN" not in code)
sister_src = (HERE / "test_platform_baseline_sister.py").read_text(encoding="utf-8")
check("test_platform_baseline_sister.py reads with sister_tree.read and fails on SisterReadError",
      "sister_tree.read(" in sister_src and "except sister_tree.SisterReadError" in sister_src)
check("test_platform_baseline_sister.py stays in the tools tier",
      "\n# E2E TIER: tools\n" in sister_src and "\n# SUITE: e2e" in sister_src)
check("sister_tree's clone never prompts for a sign-in", sister_tree._env().get("GIT_TERMINAL_PROMPT") == "0")

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All sister_tree checks passed.")
