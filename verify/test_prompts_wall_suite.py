# ABOUTME: Offline check of verify/prompts_wall_suite.py and its live test (#937): stub gh and uv on PATH show the
# ABOUTME: wall repo's `uv run ruff check . && uv run pytest` is run as written, and that each way it fails turns red.
"""Offline. The real run is verify/test_prompts_wall_suite_e2e.py, in the live suite.

Each case puts a stub gh and a stub uv alone on PATH. The gh stub answers `gh api <path>` from files named for the
path, as GitHub would answer the commit and tarball reads, or exits as told, as the hecaton host's read-only gh does
when it refuses `gh api`. The uv stub records the directory, arguments and environment it was run with, and fails
the step that the unpacked source's `fail_step` file names, so whether the suite passes is decided by the fetched
tree, as it is in the real repo.
"""
from __future__ import annotations

import io
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tarfile
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import prompts_wall_suite as wall  # noqa: E402

E2E = HERE / "test_prompts_wall_suite_e2e.py"
SHA_MAIN = "a" * 40
SHA_STAGING = "b" * 40

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail and not ok else ""))
    if not ok:
        failures.append(name)


def make_tar(files: dict[str, str], top: str | None = "peopleforrester-prompts-agenticburn-x") -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for name, body in files.items():
            data = body.encode()
            info = tarfile.TarInfo(f"{top}/{name}" if top else name)
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def wall_tree(fail_step: str = "") -> dict[str, str]:
    files = {"pyproject.toml": '[project]\nname = "prompts-agenticburn"\n', "app.py": "", "test_app.py": ""}
    if fail_step:
        files["fail_step"] = fail_step
    return files


class Stubs:
    """A bin directory holding stub gh and uv, and what they recorded."""

    def __init__(self, root: pathlib.Path, gh: bool = True, uv: bool = True) -> None:
        self.bin = root / "bin"
        self.answers = root / "answers"
        self.bin.mkdir()
        self.answers.mkdir()
        self.gh_log = root / "gh-args"
        self.uv_log = root / "uv-calls"
        self.gh_cfg = root / "gh.json"
        self.gh_cfg.write_text("{}")
        if gh:
            self._script("gh", f"""
import json, pathlib, sys
pathlib.Path({str(self.gh_log)!r}).open("a").write(json.dumps(sys.argv[1:]) + "\\n")
cfg = json.loads(pathlib.Path({str(self.gh_cfg)!r}).read_text())
if "exit" in cfg:
    sys.stderr.write(cfg.get("stderr", ""))
    sys.exit(cfg["exit"])
if sys.argv[1:2] != ["api"]:
    sys.stderr.write("stub gh: only api\\n")
    sys.exit(1)
ans = pathlib.Path({str(self.answers)!r}) / sys.argv[2].replace("/", "_")
if not ans.exists():
    sys.stderr.write("gh: Not Found (HTTP 404)\\n")
    sys.exit(1)
sys.stdout.buffer.write(ans.read_bytes())
""")
        if uv:
            self._script("uv", f"""
import json, os, pathlib, sys
step = sys.argv[2] if len(sys.argv) > 2 else ""
pathlib.Path({str(self.uv_log)!r}).open("a").write(json.dumps(
    {{"cwd": os.getcwd(), "args": sys.argv[1:], "env": sorted(os.environ), "uv_cache": os.environ.get("UV_CACHE_DIR")}}) + "\\n")
fail = pathlib.Path("fail_step")
if fail.exists() and fail.read_text().strip() == step:
    print(f"stub uv: {{step}} failed")
    sys.exit(1)
print(f"stub uv: {{step}} ok")
""")

    def _script(self, name: str, body: str) -> None:
        p = self.bin / name
        p.write_text(f"#!{sys.executable}\n{body}")
        p.chmod(0o755)

    def answer(self, api_path: str, data: bytes) -> None:
        (self.answers / api_path.replace("/", "_")).write_bytes(data)

    def publish(self, ref: str, sha: str, tree: dict[str, str]) -> None:
        self.answer(f"repos/{wall.WALL_REPO}/commits/{ref}", (sha + "\n").encode())
        self.answer(f"repos/{wall.WALL_REPO}/tarball/{sha}", make_tar(tree, f"peopleforrester-prompts-agenticburn-{sha}"))

    def gh_calls(self) -> list[list[str]]:
        return [json.loads(ln) for ln in self.gh_log.read_text().splitlines()] if self.gh_log.exists() else []

    def uv_calls(self) -> list[dict]:
        return [json.loads(ln) for ln in self.uv_log.read_text().splitlines()] if self.uv_log.exists() else []


def with_path(bindir: pathlib.Path, fn, extra_env: dict[str, str] | None = None):
    old = dict(os.environ)
    os.environ["PATH"] = str(bindir)
    os.environ.update(extra_env or {})
    try:
        return fn()
    finally:
        os.environ.clear()
        os.environ.update(old)


def error_of(fn) -> str:
    try:
        fn()
    except wall.WallSuiteError as e:
        return str(e)
    return ""


print("== the command is #927's, step for step ==")
check("COMMAND reads `uv run ruff check . && uv run pytest`", wall.COMMAND == "uv run ruff check . && uv run pytest",
      wall.COMMAND)
check("the branches run are main and staging", wall.WALL_REFS == ("main", "staging"), str(wall.WALL_REFS))

print("== a tree whose lint and tests pass ==")
with tempfile.TemporaryDirectory() as td:
    root = pathlib.Path(td)
    s = Stubs(root)
    s.publish("main", SHA_MAIN, wall_tree())
    sha = with_path(s.bin, lambda: wall.resolve("main"))
    check("resolve reads the branch tip's sha", sha == SHA_MAIN, sha)
    check("resolve asks gh api for the commit", s.gh_calls()[-1:] == [
        ["api", f"repos/{wall.WALL_REPO}/commits/main", "--jq", ".sha"]], str(s.gh_calls()))
    dest = root / "unpacked"
    dest.mkdir()
    src = with_path(s.bin, lambda: wall.fetch(SHA_MAIN, dest))
    check("fetch reads the tarball at that sha", s.gh_calls()[-1] == ["api", f"repos/{wall.WALL_REPO}/tarball/{SHA_MAIN}"],
          str(s.gh_calls()[-1]))
    check("fetch returns the tree's top directory", (src / "pyproject.toml").is_file() and src.parent == dest, str(src))
    steps = with_path(s.bin, lambda: wall.run_suite(src),
                      {"CONTEXT": "watch-it-burn-community", "FEED_URL": "http://x", "UV_CACHE_DIR": str(root / "c")})
    calls = s.uv_calls()
    check("uv runs `run ruff check .`, then `run pytest`",
          [c["args"] for c in calls] == [["run", "ruff", "check", "."], ["run", "pytest"]], str(calls))
    check("both run in the unpacked tree", all(pathlib.Path(c["cwd"]) == src for c in calls), str(calls))
    check("passed() holds when both exit 0", wall.passed(steps), str(steps))
    env = set(calls[0]["env"]) if calls else set()
    check("the caller's CONTEXT and FEED_URL do not reach the suite", not env & {"CONTEXT", "FEED_URL"}, str(env))
    check("PATH and UV_CACHE_DIR do", {"PATH", "UV_CACHE_DIR"} <= env, str(env))
    want_cache = wall.package_cache.installer_env()["UV_CACHE_DIR"]
    check(f"UV_CACHE_DIR is the uv cache in the host artifact cache, not the caller's (#1121): {want_cache}",
          bool(calls) and calls[0].get("uv_cache") == want_cache and want_cache != str(root / "c"),
          str(calls[0].get("uv_cache") if calls else None))

for step_name, ran in (("ruff", 1), ("pytest", 2)):
    print(f"== a tree whose {step_name} step fails ==")
    with tempfile.TemporaryDirectory() as td:
        root = pathlib.Path(td)
        s = Stubs(root)
        s.publish("main", SHA_MAIN, wall_tree(step_name))
        dest = root / "u"
        dest.mkdir()
        src = with_path(s.bin, lambda: wall.fetch(SHA_MAIN, dest))
        steps = with_path(s.bin, lambda: wall.run_suite(src))
        check(f"passed() is false when {step_name} fails", not wall.passed(steps), str(steps))
        check(f"{ran} step(s) ran, as `&&` stops at the failure", len(steps) == ran and not steps[-1].ok, str(steps))
        check("the failing step's output is kept", f"{step_name} failed" in steps[-1].output, steps[-1].output)

print("== what stops the suite from running names itself ==")
with tempfile.TemporaryDirectory() as td:
    root = pathlib.Path(td)
    s = Stubs(root, uv=False)
    got = with_path(s.bin, lambda: error_of(lambda: wall.run_suite(root)))
    check("no uv on PATH is an error naming uv", got.startswith("no uv on PATH"), got)
with tempfile.TemporaryDirectory() as td:
    root = pathlib.Path(td)
    s = Stubs(root, gh=False)
    got = with_path(s.bin, lambda: error_of(lambda: wall.resolve("main")))
    check("no gh on PATH is an error naming gh", got.startswith("no gh on PATH"), got)
with tempfile.TemporaryDirectory() as td:
    root = pathlib.Path(td)
    s = Stubs(root)
    s.gh_cfg.write_text(json.dumps({"exit": 1, "stderr": "REFUSED gh api is not a read-only command this allows\n"}))
    got = with_path(s.bin, lambda: error_of(lambda: wall.resolve("main")))
    check("the gate's refusal of gh api is an error quoting it", "REFUSED gh api" in got and "exit 1" in got, got)
    s.gh_cfg.write_text("{}")
    got = with_path(s.bin, lambda: error_of(lambda: wall.resolve("main")))
    check("a 404 from GitHub is an error quoting it", "HTTP 404" in got, got)
    s.answer(f"repos/{wall.WALL_REPO}/commits/main", b'{"message": "Bad credentials"}')
    got = with_path(s.bin, lambda: error_of(lambda: wall.resolve("main")))
    check("an answer that is not a sha is an error", "not a commit sha" in got, got)

print("== a tarball that is not one GitHub tree is refused ==")
cases = {
    "two top directories": make_tar({"a/pyproject.toml": "", "b/x": ""}, None),
    "a path out of the destination": make_tar({"top/pyproject.toml": "", "top/../../evil": "x"}, None),
    "no pyproject.toml at the top": make_tar({"app.py": ""}),
    "bytes that are not gzip": b"not a tarball",
}
for label, data in cases.items():
    with tempfile.TemporaryDirectory() as td:
        dest = pathlib.Path(td) / "u"
        dest.mkdir()
        got = error_of(lambda: wall.unpack(data, dest))
        check(f"{label}: refused", bool(got), "unpacked without an error")
        check(f"{label}: nothing lands outside the destination",
              not (pathlib.Path(td) / "evil").exists() and not (pathlib.Path(td).parent / "evil").exists())

print("== the live test, end to end on stubs ==")


RUN_DIRS: list[str] = []


def run_e2e(trees: dict[str, tuple[str, dict[str, str]]]) -> tuple[int, str, Stubs, pathlib.Path]:
    td = tempfile.mkdtemp()
    RUN_DIRS.append(td)
    root = pathlib.Path(td)
    s = Stubs(root)
    for ref, (sha, tree) in trees.items():
        s.publish(ref, sha, tree)
    # The suite's uv cache is the host artifact cache's (#1121), whose root must be outside every worktree, and TMPDIR
    # (so td) is inside this one on a hecaton run.
    cache = str(wall.package_cache.artifact_cache.scratch_dir("wib-wall-cache-"))
    RUN_DIRS.append(cache)
    p = subprocess.run([sys.executable, str(E2E)], capture_output=True, text=True, timeout=120,
                       env={"PATH": str(s.bin), "HOME": td, "TMPDIR": td, "WIB_ARTIFACT_CACHE": cache})
    return p.returncode, p.stdout + p.stderr, s, root


rc, out, s, _ = run_e2e({"main": (SHA_MAIN, wall_tree()), "staging": (SHA_STAGING, wall_tree())})
check("both branches green: exit 0", rc == 0, out)
check("both branches green: each sha ran the two steps", len(s.uv_calls()) == 4, str(len(s.uv_calls())))
check("both branches green: it says the command passes", "passes in peopleforrester/prompts-agenticburn" in out, out)

rc, out, s, _ = run_e2e({"main": (SHA_MAIN, wall_tree()), "staging": (SHA_MAIN, wall_tree())})
check("one commit on both branches: exit 0, run once", rc == 0 and len(s.uv_calls()) == 2, out)

rc, out, s, _ = run_e2e({"main": (SHA_MAIN, wall_tree()), "staging": (SHA_STAGING, wall_tree("pytest"))})
check("staging's pytest fails: exit 1", rc == 1, out)
check("staging's pytest fails: the failure names staging and the step",
      "FAIL  staging: `uv run pytest`" in out and "FAIL  main" not in out, out)

rc, out, s, _ = run_e2e({"main": (SHA_MAIN, wall_tree("ruff")), "staging": (SHA_STAGING, wall_tree())})
check("main's ruff fails: exit 1, naming main's ruff step", rc == 1 and "FAIL  main: `uv run ruff check .`" in out,
      out)
check("main's ruff fails: pytest is named as not run", "not run, since `&&` stops at the first failure: uv run pytest"
      in out, out)

rc, out, s, _ = run_e2e({"main": (SHA_MAIN, wall_tree())})
check("a branch gh cannot read: exit 1, naming the branch", rc == 1 and "@staging" in out and "HTTP 404" in out, out)

for td in RUN_DIRS:
    shutil.rmtree(td, ignore_errors=True)

print("== it sits in the live suite, not the tools tier the gate runs ==")
head = E2E.read_text().splitlines()
check("the live test carries `# SUITE: e2e`", any(ln.startswith("# SUITE: e2e") for ln in head))
check("the live test carries no `# E2E TIER: tools` line (the gate's gh refuses gh api)",
      not any(ln.startswith("# E2E TIER: tools") for ln in head))

if failures:
    print(f"\nFAILED: {len(failures)} check(s): {failures}", file=sys.stderr)
    sys.exit(1)
print("\nAll prompts-agenticburn suite checks pass.")
