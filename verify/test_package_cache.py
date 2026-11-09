# ABOUTME: verify/package_cache.py serves python.lock's wheels from the host artifact cache and installs them offline
# ABOUTME: with --require-hashes, and every Python and Node install in verify/, scripts/, infra/ and CI goes through it.
"""Offline, with uv stubbed and the fetcher counted (#1121). What it holds:

- verify/python.lock parses, locks exactly the environments ENVS names, pins each one's own requirements at the
  versions ENVS asks for, and is in the form `write` renders. Each caller's pin is the lock's: playwright_browsers'
  PLAYWRIGHT, the workshop-mcp image's mcp and pyyaml on its Python, the llm-guard tests' llm-guard, segno, and
  infra/policy/plan/tools.yaml's Checkov and moto on plan-policy.yml's Python.
- infra/policy/plan/install-tools.py installs each of tools.yaml's Python tools by package_cache.install() into a fresh
  venv with pip (the plan-policy job has no uv), and refuses a tools.yaml pin the lock does not hold (#1185).
- best_wheel() picks the wheel a CPython prefers on manylinux x86_64, and none it cannot install.
- wheelhouse(): a miss is fetched once per wheel and linked under its file name, with a requirements.txt that pins each
  by `--hash=sha256:`; a warm fill makes no fetch and leaves the fetch log as it was; a cached wheel whose bytes no
  longer match fails by name with both sums, is left in place and is not fetched again; a download that does not
  match is refused and nothing is linked.
- environment() and install() run uv (or pip) offline, with no index, no build and --require-hashes, on that
  wheelhouse, with uv's and pip's caches in the artifact root; a second call builds nothing, and a cached wheel that
  changed fails the call even with the environment built. An interpreter on another Python is refused before any
  install.
- Nothing in verify/, scripts/, infra/ or .github/workflows/ installs a Python or Node package any other way: every
  `uv run --with`, `pip install` and `npm`/`yarn` install found is one of the few named here, each with why. The
  scan's pattern is held against the install lines it must catch, install-tools.py's pip call before #1185 among them.
- The Node install, run-e2e.sh's `corepack yarn install --immutable`, takes node_env() first, whose caches are in the
  artifact root with a checksum mismatch thrown, and the Backstage yarn.lock records a checksum for every package.

verify/test_package_cache_e2e.py runs real uv and yarn on the same paths, on loopback.
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import subprocess
import sys

import yaml

VERIFY = pathlib.Path(__file__).resolve().parent
REPO = VERIFY.parent
sys.path.insert(0, str(VERIFY))
import artifact_cache  # noqa: E402
import package_cache as pc  # noqa: E402
import playwright_browsers  # noqa: E402

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"\n        {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def refusal(fn) -> str:
    try:
        fn()
    except (pc.PackageCacheError, artifact_cache.ArtifactCacheError) as e:
        return str(e)
    return ""


print("== python.lock: the environments ENVS names, at the versions they ask for ==")
LOCK_TEXT = pc.LOCK.read_text(encoding="utf-8")
lock = pc.read_lock()
check(f"it locks exactly ENVS' environments ({sorted(lock)})", sorted(lock) == sorted(pc.ENVS))
check("it is in the form `package_cache.py write` renders", pc.render(lock) == LOCK_TEXT)
for name, spec in pc.ENVS.items():
    wheels = lock.get(name, [])
    check(f"{name}: every wheel is for Python {spec.python}", bool(wheels) and {w.python for w in wheels} == {spec.python})
    for req in spec.requires:
        m = re.fullmatch(r"([A-Za-z0-9_.-]+)(?:\[[^\]]+\])?==(\S+)", req)
        check(f"{name}: {req} is an exact pin", m is not None)
        if m:
            got = next((w.version for w in wheels if pc.normalize(w.name) == pc.normalize(m.group(1))), None)
            check(f"{name}: python.lock pins {m.group(1)} at {m.group(2)} ({got})", got == m.group(2))
    bad = [w.filename for w in wheels if pc.best_wheel([w.filename], spec.python) is None]
    check(f"{name}: each of its {len(wheels)} wheels installs on Python {spec.python} on manylinux x86_64", bad == [],
          str(bad))

print("== each caller's pin is the lock's ==")
check(f"playwright_browsers.PLAYWRIGHT ({playwright_browsers.PLAYWRIGHT}) is the lock's",
      playwright_browsers.PLAYWRIGHT == f"playwright=={pc.pinned('playwright', 'playwright')}")
dockerfile = (REPO / "images/workshop-mcp/Dockerfile").read_text(encoding="utf-8")
for pkg in ("mcp", "pyyaml"):
    pin = re.search(rf"'{pkg}==([0-9.]+)'", dockerfile)
    check(f"the mcp environment pins images/workshop-mcp's {pkg} ({pin.group(1) if pin else '?'})",
          bool(pin) and pc.pinned("mcp", pkg) == pin.group(1))
py = re.search(r"^FROM \S*python[:-](\d+\.\d+)", dockerfile, re.M)
check(f"the mcp environment is on the image's Python ({py.group(1) if py else '?'})",
      bool(py) and pc.ENVS["mcp"].python == py.group(1))
llm_guard = pc.pinned("llm-guard", "llm-guard")
for f in ("test_injection_classifier.py", "test_input_pii_guard_llm_guard.py"):
    m = re.search(r'^LLM_GUARD = "([0-9.]+)"', (VERIFY / f).read_text(encoding="utf-8"), re.M)
    check(f"{f}'s LLM_GUARD is the lock's llm-guard ({llm_guard})", bool(m) and m.group(1) == llm_guard)
import topic_cases  # noqa: E402

check(f"topic_cases.CLASSIFIER's llm_guard is the lock's ({llm_guard})", topic_cases.CLASSIFIER["llm_guard"] == llm_guard)
check("the llm-guard environment takes torch's CPU build", pc.pinned("llm-guard", "torch") == "2.14.0+cpu")
check("the segno environment pins segno 1.6.6, decisions.md's pin (#451)", pc.pinned("segno", "segno") == "1.6.6")
PLAN = REPO / "infra/policy/plan"
plan_tools = yaml.safe_load((PLAN / "tools.yaml").read_text(encoding="utf-8"))["python"]
plan_wf = (REPO / ".github/workflows/plan-policy.yml").read_text(encoding="utf-8")
plan_py = re.search(r"python-version: '(\d+\.\d+)'", plan_wf)
check(f"tools.yaml names Python tools ({sorted(plan_tools)})", sorted(plan_tools) == ["checkov", "moto"])
for name, spec in plan_tools.items():
    env = spec.get("env")
    check(f"tools.yaml's {name} names a lock environment ({env})", env in pc.ENVS and env in lock)
    if env in lock:
        check(f"the {env} environment pins tools.yaml's {name} {spec.get('version')} ({pc.pinned(env, name)})",
              pc.pinned(env, name) == str(spec.get("version")))
        check(f"the {env} environment is on plan-policy.yml's Python ({plan_py.group(1) if plan_py else '?'})",
              bool(plan_py) and pc.ENVS[env].python == plan_py.group(1))
check("the moto environment takes moto's server extra, which moto_server needs",
      pc.ENVS["moto"].requires == ("moto[server]==5.2.4",))

print("== best_wheel: the wheel the interpreter prefers ==")
cases = [
    ("an interpreter-specific wheel over the pure one",
     ["aiohttp-3.14.5-py3-none-any.whl", "aiohttp-3.14.5-cp312-cp312-manylinux2014_x86_64.manylinux_2_17_x86_64.whl"],
     "3.12", "aiohttp-3.14.5-cp312-cp312-manylinux2014_x86_64.manylinux_2_17_x86_64.whl"),
    ("the newest abi3 and glibc it accepts",
     ["c-1-cp37-abi3-manylinux_2_17_x86_64.whl", "c-1-cp37-abi3-manylinux_2_28_x86_64.whl",
      "c-1-cp39-abi3-manylinux_2_17_x86_64.whl", "c-1-cp39-abi3-manylinux_2_28_x86_64.whl"],
     "3.12", "c-1-cp39-abi3-manylinux_2_28_x86_64.whl"),
    ("the nearest older py3X tag when there is none for its own minor",
     ["m-0.70.15-py310-none-any.whl", "m-0.70.15-py311-none-any.whl", "m-0.70.15-py39-none-any.whl"],
     "3.12", "m-0.70.15-py311-none-any.whl"),
    ("no wheel for another CPython", ["y-1-cp313-cp313-manylinux_2_17_x86_64.whl"], "3.12", None),
    ("no wheel for a glibc newer than 2.28", ["y-1-cp312-cp312-manylinux_2_34_x86_64.whl"], "3.12", None),
    ("no bare linux_x86_64 wheel", ["y-1-cp312-cp312-linux_x86_64.whl"], "3.12", None),
    ("no wheel for another machine", ["y-1-cp312-cp312-manylinux_2_17_aarch64.whl"], "3.12", None),
]
for what, names, python, want in cases:
    got = pc.best_wheel(names, python)
    check(f"{what} ({got})", got == want)

print("== the lock's own refusals ==")
GOOD = "e  3.13  a  1.0  " + "a" * 64 + "  https://x.invalid/a-1.0-py3-none-any.whl\n"
for what, text, want in (
    ("a short line", "e 3.13 a 1.0\n", "want `env python package version sha256 url`"),
    ("a sum that is not a SHA-256", GOOD.replace("a" * 64, "abc"), "is not a SHA-256"),
    ("a URL that is not https", GOOD.replace("https://", "http://"), "is not an https URL of a wheel"),
    ("an sdist", GOOD.replace("-py3-none-any.whl", ".tar.gz"), "is not an https URL of a wheel"),
    ("a package twice in one environment", GOOD + GOOD, "a is pinned twice in e"),
    ("an environment on two Pythons", GOOD + GOOD.replace("3.13", "3.12").replace("  a  ", "  b  "),
     "e is locked for Python 3.13 above, not 3.12"),
):
    err = refusal(lambda: pc.parse_lock(text))
    check(f"{what} is refused by line ({err})", want in err and "line " in err)
check("an environment the lock does not hold is refused, naming those it does",
      "python.lock has no environment 'nope'" in refusal(lambda: pc.env_wheels("nope", lock)))

# ----------------------------------------------------------------------------------------- fixtures and stubs
SCRATCH = artifact_cache.scratch_dir("wib-package-cache-test-")
BLOBS = {"alpha-1.0-py3-none-any.whl": b"alpha wheel bytes\n", "beta-2.0-py3-none-any.whl": b"beta wheel bytes\n"}
SUMS = {f: artifact_cache.hashlib.sha256(b).hexdigest() for f, b in BLOBS.items()}
PY = f"{sys.version_info[0]}.{sys.version_info[1]}"
FIXTURE_LOCK = pc.parse_lock("".join(
    f"fx  {PY}  {f.split('-')[0]}  {f.split('-')[1]}  {SUMS[f]}  https://fixture.invalid/{f}\n" for f in BLOBS))
FETCHES: list[str] = []
SERVE: dict[str, bytes] = dict(BLOBS)


def fetch(url: str, out) -> None:
    FETCHES.append(url)
    out.write(SERVE[url.rsplit("/", 1)[-1]])


def no_fetch(url: str, out) -> None:
    raise AssertionError(f"fetched {url}")


def stub_uv(bindir: pathlib.Path, log: pathlib.Path) -> None:
    """A uv that logs each call with its UV_CACHE_DIR, finds this interpreter, and makes a venv of links to it."""
    bindir.mkdir(parents=True, exist_ok=True)
    (bindir / "uv").write_text(f"""#!{sys.executable}
import json, os, pathlib, sys
a = sys.argv[1:]
with open({str(log)!r}, "a") as f:
    f.write(json.dumps({{"args": a, "uv_cache": os.environ.get("UV_CACHE_DIR")}}) + "\\n")
if a[:2] == ["python", "find"]:
    print({sys.executable!r})
elif a[:1] == ["venv"]:
    b = pathlib.Path(a[-1]) / "bin"
    b.mkdir(parents=True, exist_ok=True)
    for n in ("python", "tool"):
        (b / n).unlink(missing_ok=True)
        (b / n).symlink_to({sys.executable!r})
""")
    (bindir / "uv").chmod(0o755)


def uv_calls(log: pathlib.Path) -> list[dict]:
    return [json.loads(x) for x in log.read_text().splitlines()] if log.exists() else []


def fetch_log(root: pathlib.Path) -> list[str]:
    p = root / "fetch.log"
    return p.read_text().splitlines() if p.exists() else []


PATH = os.environ["PATH"]
try:
    print("== wheelhouse: a miss fetched once, a hit re-checked, a changed hit refused ==")
    root = SCRATCH / "root"
    house = pc.wheelhouse("fx", root=root, lock=FIXTURE_LOCK, fetch=fetch)
    check(f"a cold fill fetches each wheel once ({len(FETCHES)})",
          sorted(FETCHES) == sorted(f"https://fixture.invalid/{f}" for f in BLOBS))
    check("the wheelhouse is in the artifact root, outside every worktree",
          house.parent == root / "packages" / "wheels" and artifact_cache.worktree_of(house) is None, str(house))
    for f in BLOBS:
        link = house / f
        check(f"{f} is linked to its cache entry by its sum",
              link.is_symlink() and pathlib.Path(os.readlink(link)) == artifact_cache.path_for(SUMS[f], root))
    req = (house / "requirements.txt").read_text()
    check("requirements.txt pins each wheel by version and SHA-256",
          req == "".join(f"{f.split('-')[0]}=={f.split('-')[1]} --hash=sha256:{SUMS[f]}\n" for f in sorted(BLOBS)), req)
    log_before = fetch_log(root)
    check("each fetch is a fetch-log line", len(log_before) == len(BLOBS), str(log_before))
    FETCHES.clear()
    again = pc.wheelhouse("fx", root=root, lock=FIXTURE_LOCK, fetch=no_fetch)
    check("a warm fill fetches nothing and leaves the fetch log as it was",
          again == house and FETCHES == [] and fetch_log(root) == log_before)
    entry = artifact_cache.path_for(SUMS["alpha-1.0-py3-none-any.whl"], root)
    entry.write_bytes(b"alpha wheel bytes, changed\n")
    err = refusal(lambda: pc.wheelhouse("fx", root=root, lock=FIXTURE_LOCK, fetch=fetch))
    check("a cached wheel whose bytes changed fails the fill, naming the wheel and both sums",
          "fx: alpha 1.0 (alpha-1.0-py3-none-any.whl)" in err and SUMS["alpha-1.0-py3-none-any.whl"] in err
          and artifact_cache.sha256_of(entry) in err, err)
    check("and it is not fetched again, nor deleted", FETCHES == [] and entry.read_bytes() == b"alpha wheel bytes, changed\n"
          and fetch_log(root) == log_before)
    entry.write_bytes(BLOBS["alpha-1.0-py3-none-any.whl"])

    cold = SCRATCH / "cold"
    SERVE["beta-2.0-py3-none-any.whl"] = b"other bytes under the pinned name\n"
    err = refusal(lambda: pc.wheelhouse("fx", root=cold, lock=FIXTURE_LOCK, fetch=fetch))
    check("a download that does not match its pin is refused, naming both sums",
          "does not match its pin" in err and SUMS["beta-2.0-py3-none-any.whl"] in err, err)
    house_cold = cold / "packages" / "wheels" / f"fx-{pc.digest(FIXTURE_LOCK['fx'])}"
    check("and neither it nor a link to it is kept",
          not artifact_cache.path_for(SUMS["beta-2.0-py3-none-any.whl"], cold).exists()
          and not (house_cold / "beta-2.0-py3-none-any.whl").exists())
    SERVE.update(BLOBS)

    print("== environment(): uv, offline, no index, no build, --require-hashes, its cache in the artifact root ==")
    bindir, log = SCRATCH / "bin", SCRATCH / "uv.log"
    stub_uv(bindir, log)
    os.environ["PATH"] = f"{bindir}:{PATH}"
    FETCHES.clear()
    venv = pc.environment("fx", root=root, lock=FIXTURE_LOCK, fetch=no_fetch)
    calls = uv_calls(log)
    installs = [c for c in calls if c["args"][:2] == ["pip", "install"]]
    check("it builds a venv and makes one install", [c["args"][0] for c in calls] == ["python", "venv", "pip"],
          str([c["args"] for c in calls]))
    want = ["pip", "install", "--no-config", "--python", str(venv / "bin" / "python"), "--offline", "--no-index",
            "--no-build", "--find-links", str(house), "--require-hashes", "-r", str(house / "requirements.txt")]
    check("the install reads the wheelhouse alone, offline, hash-checked", bool(installs) and installs[0]["args"] == want,
          str(installs))
    check("uv's cache is in the artifact root",
          {c["uv_cache"] for c in calls} == {str(root / "packages" / "uv-cache")}, str({c["uv_cache"] for c in calls}))
    check("the environment is in the artifact root, named for the environment and its lock",
          venv.parent == root / "packages" / "envs" and venv.name.startswith("fx-"), str(venv))
    pc.environment("fx", root=root, lock=FIXTURE_LOCK, fetch=no_fetch)
    check("a second call builds nothing", len(uv_calls(log)) == len(calls) + 1, str(uv_calls(log)[len(calls):]))
    entry.write_bytes(b"alpha wheel bytes, changed again\n")
    n = len(uv_calls(log))
    err = refusal(lambda: pc.environment("fx", root=root, lock=FIXTURE_LOCK, fetch=no_fetch))
    check("with the environment built, a cached wheel that changed still fails the call", "does not match its pin" in err,
          err)
    check("before uv runs", len(uv_calls(log)) == n)
    entry.write_bytes(BLOBS["alpha-1.0-py3-none-any.whl"])

    print("== run: the CLI prefix runs the program from the environment ==")
    rc = pc.run_cmd("playwright", root)
    check("run_cmd names this interpreter, package_cache.py, the environment and the root",
          rc == [sys.executable, str(VERIFY / "package_cache.py"), "run", "playwright", "--root", str(root), "--"], str(rc))
    inside = REPO / "tmp" / "package-cache-root-1121"
    r = subprocess.run([sys.executable, str(VERIFY / "package_cache.py"), "run", "fx", "--root", str(inside), "--",
                        "python"], capture_output=True, text=True)
    check("a --root inside a worktree is refused before anything runs",
          r.returncode == 1 and "is inside the git worktree" in r.stderr and not inside.exists(), r.stderr)
    r = subprocess.run([sys.executable, str(VERIFY / "package_cache.py"), "run", "nope", "--root", str(root), "--",
                        "python"], capture_output=True, text=True)
    check("an environment the lock does not hold fails by name",
          r.returncode == 1 and r.stderr.startswith("PACKAGE CACHE FAILED: python.lock has no environment 'nope'"),
          r.stderr)

    print("== install(): into a given interpreter, with uv or pip ==")
    n = len(uv_calls(log))
    pc.install("fx", sys.executable, root=root, lock=FIXTURE_LOCK, fetch=no_fetch)
    new = uv_calls(log)[n:]
    check("with uv: one offline, hash-checked install into that interpreter",
          [c["args"] for c in new] == [pc.uv_install_cmd(sys.executable, house)[1:]], str(new))
    pipcmd = pc.pip_install_cmd(sys.executable, house)
    check("with pip: --no-index, --only-binary=:all:, the wheelhouse and --require-hashes",
          all(a in pipcmd for a in ("--no-index", "--only-binary=:all:", "--require-hashes", str(house)))
          and pipcmd[1:4] == ["-m", "pip", "install"])
    check("pip's cache is in the artifact root",
          pc.installer_env(root)["PIP_CACHE_DIR"] == str(root / "packages" / "pip-cache"))
    other = "3.12" if PY != "3.12" else "3.13"
    wrong = pc.parse_lock(f"fx  {other}  alpha  1.0  {SUMS['alpha-1.0-py3-none-any.whl']}  "
                          "https://fixture.invalid/alpha-1.0-py3-none-any.whl\n")
    n = len(uv_calls(log))
    err = refusal(lambda: pc.install("fx", sys.executable, root=root, lock=wrong, fetch=no_fetch))
    check("an interpreter on another Python is refused before any install",
          f"fx is locked for Python {other}, and {sys.executable} is Python {PY}" in err and len(uv_calls(log)) == n, err)
finally:
    os.environ["PATH"] = PATH
    subprocess.run(["chmod", "-R", "u+w", str(SCRATCH)], check=False)
    subprocess.run(["rm", "-rf", str(SCRATCH)], check=False)

print("== install-tools.py: each Python tool from its lock environment, hash-checked, into its own venv ==")
import importlib.util  # noqa: E402
import types  # noqa: E402

spec_ = importlib.util.spec_from_file_location("install_tools", PLAN / "install-tools.py")
install_tools = importlib.util.module_from_spec(spec_)
spec_.loader.exec_module(install_tools)
CALLS: list[tuple] = []
real_install, real_subprocess = install_tools.package_cache.install, install_tools.subprocess
install_tools.package_cache.install = lambda env, python, **kw: CALLS.append(("install", env, python, kw))
install_tools.subprocess = types.SimpleNamespace(run=lambda cmd, **kw: CALLS.append(("run", cmd, kw)))
tool_root = artifact_cache.scratch_dir("wib-install-tools-test-")
try:
    tool_bin = tool_root / "bin"
    tool_bin.mkdir()
    install_tools.python_tool("moto", plan_tools["moto"], tool_root, tool_bin)
    venv = tool_root / "venvs" / "moto"
    want = [("run", [sys.executable, "-m", "venv", "--clear", str(venv)], {"check": True}),
            ("install", "moto", str(venv / "bin" / "python"), {"pip": True})]
    check("it makes a fresh venv, then installs the moto environment into it with package_cache.install(pip=True)",
          CALLS == want, str(CALLS))
    link = tool_bin / "moto_server"
    check("and links the tool's command into bin/",
          link.is_symlink() and pathlib.Path(os.readlink(link)) == venv / "bin" / "moto_server")
    CALLS.clear()
    try:
        install_tools.python_tool("moto", {**plan_tools["moto"], "version": "0.0.1"}, tool_root, tool_bin)
        err = ""
    except SystemExit as e:
        err = str(e)
    check("a tools.yaml version the lock does not pin is refused, naming both, before anything installs",
          "tools.yaml pins 0.0.1" in err and f"pins {pc.pinned('moto', 'moto')}" in err and CALLS == [], err or str(CALLS))
    try:
        install_tools.python_tool("moto", {**plan_tools["moto"], "env": "nope"}, tool_root, tool_bin)
        err = ""
    except SystemExit as e:
        err = str(e)
    check("an environment the lock does not hold is refused by name", "python.lock has no environment 'nope'" in err
          and CALLS == [], err)
finally:
    install_tools.package_cache.install, install_tools.subprocess = real_install, real_subprocess
    subprocess.run(["rm", "-rf", str(tool_root)], check=False)

print("== Node: yarn's caches in the artifact root, a mismatch thrown ==")
ne = pc.node_env(pathlib.Path("/r"))
check("node_env puts yarn's global cache and corepack's home in the artifact root, and throws on a mismatch",
      ne == {"YARN_ENABLE_GLOBAL_CACHE": "true", "YARN_GLOBAL_FOLDER": "/r/packages/yarn",
             "YARN_CHECKSUM_BEHAVIOR": "throw", "COREPACK_HOME": "/r/packages/corepack"}, str(ne))
rune2e = (VERIFY / "run-e2e.sh").read_text(encoding="utf-8")
body = re.search(r"^backstage_e2e\(\) \{\n(.*?)^\}", rune2e, re.M | re.S)
b = body.group(1) if body else ""
check("run-e2e.sh's Backstage install reads package_cache.py node-env, failing when it fails",
      'node_env="$(python3 "${SCRIPT_DIR}/package_cache.py" node-env)" || return 1' in b)
check("and exports it before `corepack yarn install --immutable`",
      0 <= b.find('export "${k}=${v}"; done <<<"${node_env}"') < b.find("corepack yarn install --immutable"))
BACKSTAGE = REPO / "images/watch-it-burn-backstage"
yarnlock = (BACKSTAGE / "yarn.lock").read_text(encoding="utf-8")
entries = [e for e in re.split(r"\n\n+", yarnlock) if "\n  resolution: " in e]
hard_npm = [e for e in entries if "linkType: hard" in e and re.search(r'resolution: "[^"]+@npm:', e)]
summed = re.compile(r"^  checksum: \S+/[0-9a-f]{128}$", re.M)
conditional = re.compile(r"^  conditions: ", re.M)
plain = [e for e in hard_npm if not conditional.search(e)]
unsummed = [e.splitlines()[0] for e in plain if not summed.search(e)]
check(f"the Backstage yarn.lock records a checksum for each of its {len(plain)} registry packages that has no "
      "platform condition", len(plain) > 1000 and unsummed == [], str(unsummed[:5]))
# Yarn 4 writes no checksum for a package with a `conditions:` line (a platform's native binary, such as
# @esbuild/linux-x64) even with supportedArchitectures naming linux x64 (tried in run 18530), so those are the only
# entries without one. They are counted here so a new one shows in the output; the app's conditional-checksums plugin
# and lock check them instead (#1167, held in test_yarn_pins.py).
cond_unsummed = [e.splitlines()[0] for e in hard_npm if conditional.search(e) and not summed.search(e)]
print(f"        ({len(cond_unsummed)} platform-conditional entries carry no checksum, as Yarn 4 writes them)")
rc_yml = yaml.safe_load((BACKSTAGE / ".yarnrc.yml").read_text(encoding="utf-8")) or {}
check("its .yarnrc.yml sets no checksum behavior, cache folder or global-cache switch of its own",
      not {"checksumBehavior", "cacheFolder", "enableGlobalCache", "globalFolder"} & set(rc_yml), str(sorted(rc_yml)))

print("== nothing in verify/, scripts/, infra/ or .github/workflows/ installs a package another way ==")
# `"pip3?"\)?,\s*"install"` catches an argv that names pip by path, as install-tools.py's did before #1185.
INSTALL = re.compile(r'\buv\s+run\b|"uv",\s*"run"|"--with",|\bpip3?\s+install\b|"pip3?"\)?,\s*"install"'
                     r'|\buv\s+pip\s+(?:install|sync)\b|\buvx\b|\bpipx\b|\bnpm\s+(?:ci|install|i)\b|\bnpx\b'
                     r'|\byarn\s+(?:add|install)\b|\bpnpm\b')
MUST_CATCH = [
    'subprocess.run([str(venv / "bin" / "pip"), "install", "--quiet", f"{spec[\'package\']}=={spec[\'version\']}"],',
    'python3 -m venv /tmp/qr && /tmp/qr/bin/pip install segno==1.6.6',
    '[sys.executable, "-m", "pip", "install", "checkov==3.3.30"]',
    'uv run --with checkov==3.3.30 checkov', 'uvx checkov', 'npm ci', 'npx foo', 'yarn install',
]
missed = [ln for ln in MUST_CATCH if not INSTALL.search(ln)]
check("the scan catches each install line it is for, install-tools.py's pip call before #1185 among them",
      missed == [], str(missed))
# Each file allowed to name one, and why. The rest of these files name none.
ALLOWED = {
    "verify/package_cache.py": "the helper itself builds the hash-checked install commands",
    "verify/test_package_cache.py": "this test",
    "verify/test_package_cache_e2e.py": "the end-to-end half of this test",
    "verify/run-e2e.sh": "`corepack yarn install --immutable`, after node-env, held above",
    "verify/test_e2e_toolchain.py": "quotes run-e2e.sh's yarn line, which it holds",
    "verify/yarn_pins.py": "`write` runs the app's yarn in a scratch project on a loopback registry of tarballs it "
                           "checked against npm's dist.integrity, to record the conditional checksums (#1167)",
    "verify/test_yarn_pins_e2e.py": "runs the app's yarn and its conditional-checksums plugin on a loopback registry",
    "verify/test_yarn_pins.py": "quotes run-e2e.sh's and the Backstage README's yarn install lines, which it holds",
    "verify/prompts_wall_suite.py": "runs prompts-agenticburn's own `uv run` command as written, on that repo's "
                                    "uv.lock, whose hashes uv checks, with UV_CACHE_DIR the artifact root's",
    "verify/test_prompts_wall_suite.py": "quotes that command",
    "verify/test_prompts_wall_suite_e2e.py": "quotes that command",
    "verify/test_wall_clock_burst_sister_e2e.py": "`uv run --frozen` on a sister repo's own uv.lock, whose hashes uv "
                                                  "checks, with UV_CACHE_DIR the artifact root's",
}
tracked = subprocess.run(["git", "-C", str(REPO), "ls-files", "verify", "scripts", "infra", ".github/workflows"],
                         capture_output=True, text=True, check=True).stdout.split()
found: dict[str, list[str]] = {}
for rel in tracked:
    p = REPO / rel
    if rel == "verify/scope-map.yaml" or p.suffix in (".lock", ".png", ".svg", ".jpg", ".gz", ".tgz") or not p.is_file():
        continue
    try:
        text = p.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        continue
    hits = [f"{n}: {ln.strip()}" for n, ln in enumerate(text.splitlines(), 1) if INSTALL.search(ln)]
    if hits:
        found[rel] = hits
stray = {k: v for k, v in found.items() if k not in ALLOWED}
check("no other file runs `uv run`, `uv run --with`, `pip install`, `uvx`, `pipx`, `npm`/`yarn` installs or `npx`",
      stray == {}, json.dumps(stray, indent=1))
check(f"the scan reads infra/ ({sum(r.startswith('infra/') for r in tracked)} files), install-tools.py among them",
      "infra/policy/plan/install-tools.py" in tracked)
for rel in ("verify/prompts_wall_suite.py", "verify/test_wall_clock_burst_sister_e2e.py"):
    check(f"{rel} sets UV_CACHE_DIR to the artifact root's",
          'package_cache.installer_env()["UV_CACHE_DIR"]' in (REPO / rel).read_text(encoding="utf-8"))
users = [rel for rel in tracked if rel.endswith(".py") and "package_cache.run_cmd(" in (REPO / rel).read_text(encoding="utf-8")]
for rel in ("verify/playwright_browsers.py", "verify/test_audience_page_e2e.py", "verify/test_check_inventory_schema_e2e.py",
            "verify/test_weather_feed_e2e.py", "verify/test_deployments_witch_line_e2e.py",
            "verify/test_recipe_pantry_gate_e2e.py", "verify/test_tool_audit_live.py", "verify/test_turn_guard_e2e.py",
            "verify/test_injection_classifier.py", "verify/test_input_pii_guard_llm_guard.py",
            "verify/test_topic_classifier.py", "verify/injection_config_matrix.py"):
    check(f"{rel} runs its packages through package_cache.run_cmd()", rel in users)

print("== the CI jobs install PyYAML from the lock, hash-checked, with the artifact root set first ==")
for wf in sorted((REPO / ".github/workflows").glob("*.yml")):
    doc = yaml.safe_load(wf.read_text(encoding="utf-8"))
    for job_name, job in (doc.get("jobs") or {}).items():
        runs = [s.get("run", "") for s in job.get("steps") or []]
        joined = "\n".join(runs)
        if "package_cache.py install" not in joined:
            continue
        at = next(i for i, r in enumerate(runs) if "package_cache.py install" in r)
        root_set = next((i for i, r in enumerate(runs) if r.strip() == "bash verify/ci-artifact-cache.sh"),
                        None)
        check(f"{wf.name} {job_name}: WIB_ARTIFACT_CACHE is set by verify/ci-artifact-cache.sh before the install (#1123)",
              root_set is not None and root_set < at)
        check(f"{wf.name} {job_name}: it installs the pyyaml environment",
              re.search(r"package_cache\.py install pyyaml --python \S", joined) is not None)
        uses_uv = any("setup-uv" in (s.get("uses") or "") for s in job.get("steps") or [])
        check(f"{wf.name} {job_name}: with uv where the job sets uv up, else with pip",
              ("--pip" in joined) != uses_uv)
        py = re.search(r"python-version: '(\d+\.\d+)'", wf.read_text()) or re.search(r"uv venv --python (\d+\.\d+)", joined)
        check(f"{wf.name} {job_name}: on the Python the pyyaml environment is locked for ({pc.ENVS['pyyaml'].python})",
              bool(py) and py.group(1) == pc.ENVS["pyyaml"].python)

if failures:
    print(f"\nFAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("\nAll package cache checks passed.")
