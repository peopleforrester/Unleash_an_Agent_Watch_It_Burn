# ABOUTME: Holds #1190 on the gate's E2E command: run-e2e-tools.sh, scoped by HECATON_BASE_SHA, runs no tier test and
# ABOUTME: fetches nothing for a doc-only range, only the tier tests a code range touches, the whole tier on a lock change.
"""Offline. Michael, 2026-11-08, on #1190: "I only need changes that warrant a full end-to-end run... If the change
warrants it then it goes end-to-end." The promotion gate runs `bash verify/run-e2e-tools.sh` with HECATON_BASE_SHA set
to main's SHA (hecaton#619), so the range is origin/main..tip, and scope_tests.py decides which tier tests it runs.

The real runner, run-tests.sh and scope_tests.py are copied into a fixture repo of three offline and four tier tests,
committed, and driven on each range with HECATON_BASE_SHA on the commit before it:

1. A doc-only range (decisions.md, PROGRESS.md, the run-of-show, the /kubecon page's copy) runs the offline tests that
   read those files and no tier test, the always one included, and the fetch script, curl and the Terraform cache are
   never reached. A tier test reads each of those files, so this holds the prose rule and not an empty map.
2. A code range (a chart value and the page's event.js, beside the page's copy) runs the tier tests that read the code
   and the always one, and leaves the one that reads only decisions.md; the tools are fetched.
3. A change to verify/e2e-tools.lock runs every tier test and the whole offline suite, naming the lock.
4. A tier test that fails is named first, before the timings, with its kept log and the command that reruns it alone;
   that command runs it alone, with no offline suite, and passes once the cause is fixed. A failing offline test is
   named the same way, its rerun its own python3 command, and still nothing is fetched on a doc-only range.

It also holds scope_tests.PROSE to prose_gate.PUBLIC_PROSE, the ai-isms gate's own list, the kept logs out of git,
and CLAUDE.md's word to a dispatched run: scope the tier to the change, and fix and rerun one failed test alone.
"""
from __future__ import annotations

import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

REPO = pathlib.Path(__file__).resolve().parent.parent
VERIFY = REPO / "verify"
sys.path.insert(0, str(VERIFY))
import prose_gate  # noqa: E402
import scope_tests as st  # noqa: E402
import tf_plugin_cache  # noqa: E402

# The fixture runners' artifact root, outside the checkout and removed when this test exits.
ARTIFACTS = tf_plugin_cache.scratch("gate-scope-artifacts-")

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"\n        {detail[-3000:]}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


print("== the tier's prose is the ai-isms gate's ==")
check(f"scope_tests.PROSE {st.PROSE} is prose_gate.PUBLIC_PROSE {prose_gate.PUBLIC_PROSE}",
      tuple(st.PROSE) == tuple(prose_gate.PUBLIC_PROSE))
ignored = subprocess.run(["git", "-C", str(REPO), "check-ignore", "-q", "verify/.e2e-logs/test_x.py.log"])
check("the runner's kept logs (verify/.e2e-logs/) are ignored by git, so a failure never reads as a change",
      ignored.returncode == 0)

print("== CLAUDE.md tells a run to scope the tier, and to fix and rerun one failed test alone ==")
AGENTS = (REPO / "AGENTS.md").read_text(encoding="utf-8")
flat = " ".join(AGENTS.split())
item7 = re.search(r"^7\. \*\*A failed test is fixed and rerun alone.*?(?=^\d+\. |^\S|\Z)", AGENTS, re.M | re.S)
seven = " ".join(item7.group(0).split()) if item7 else ""
check("Dispatched runs has an item: a failed test is fixed and rerun alone, never the whole script",
      "never the whole script" in seven, seven)
check("it names the kept logs and both rerun commands",
      "`verify/.e2e-logs/`" in seven and "`bash verify/run-e2e-tools.sh <test>`" in seven
      and "`python3 verify/<test>`" in seven, seven)
check("it says never to rerun the whole script, naming run 18622", "Never rerun the whole script" in seven
      and "run 18622" in seven and "#1190" in seven, seven)
check("the scoping paragraph says the whole tier runs only on FULL, and a doc-only range runs none and fetches nothing",
      "the whole tier only when that selection says FULL" in flat and "selects no tier test" in flat
      and "with no tier test run and no tool fetched" in flat, flat[:0])
check("the polling item scopes a run's own command to its change",
      '`HECATON_BASE_SHA="$(git merge-base origin/staging HEAD)"`' in flat)

READS = "import pathlib, sys\nREPO = pathlib.Path(__file__).resolve().parents[1]\n"


def reader(*paths: str, fail_on: str = "") -> str:
    """A fixture test that reads each path, and fails when the first holds fail_on."""
    body = READS + "".join(f'text = (REPO / "{p}").read_text()\nprint("read {p}")\n' for p in reversed(paths))
    if fail_on:
        body += f'if "{fail_on}" in text:\n    print("{paths[0]} holds {fail_on}")\n    sys.exit(1)\n'
    return body


TIER_HEAD = "# SUITE: e2e\n# E2E TIER: tools\n"
OFFLINE = {
    "test_records.py": reader("decisions.md", "PROGRESS.md", fail_on="BROKEN RECORD"),
    "test_page.py": reader("gitops/ai-layer/web/kubecon.html"),
    "test_values.py": reader("gitops/app/values.yaml"),
}
TIER = {
    "test_tier_records.py": reader("decisions.md"),
    "test_tier_page.py": reader("gitops/ai-layer/web/kubecon.html", "facilitation/kubecon-run-of-show.md"),
    "test_tier_render.py": reader("gitops/app/values.yaml", fail_on="broken: true"),
    "test_tier_always.py": READS + 'print("read the whole tree")\n',
}
FILES = {
    "decisions.md": "# Decisions\n",
    "PROGRESS.md": "# Progress\n",
    "facilitation/kubecon-run-of-show.md": "# Run of show\n",
    "gitops/ai-layer/web/kubecon.html": '<html><body><p>KubeCon</p><script src="event.js"></script></body></html>\n',
    "gitops/ai-layer/web/event.js": "const room = 1;\n",
    "gitops/app/values.yaml": "replicas: 1\n",
    "verify/e2e-tools.lock": "kyverno 1.0.0 0000 https://example.invalid/kyverno.tgz kyverno\n",
}
MAP = """full:
  - verify/run-tests.sh
  - verify/run-e2e-tools.sh
  - verify/scope_tests.py
  - verify/no-cloud.sh
  - verify/ensure-submodules.sh
  - verify/fetch-e2e-tools.sh
  - verify/e2e-tools.lock
  - verify/playwright_browsers.py
  - verify/tf_plugin_cache.py
  - verify/artifact_cache.py
unread:
  - facilitation
bounds: {}
always:
  test_tier_always.py: the fixture's stand-in for a render that reads the whole tree
reads: {}
"""
# Each stub logs its call, so a fetch or a download reached on a doc-only range is seen.
LOGGING_STUB = '#!/bin/sh\necho "$(basename "$0") $*" >>"$CALL_LOG"\nexit 0\n'
NODE24 = ('#!/bin/sh\necho "node $*" >>"$CALL_LOG"\n'
          'case "$1" in -p) echo 24 ;; --version) echo v24.22.0 ;; esac\n')
FETCH_STUB = '#!/usr/bin/env bash\necho "fixture fetch ran" >>"$CALL_LOG"\n'
TF_STUB = 'import os, sys\nopen(os.environ["CALL_LOG"], "a").write("tf_plugin_cache.py\\n")\nprint(sys.argv[0] + ".cache")\n'


def git(root: pathlib.Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, check=True).stdout.strip()


def fixture(tmp: pathlib.Path) -> pathlib.Path:
    root = tmp / "repo"
    v = root / "verify"
    v.mkdir(parents=True)
    for name in ("run-tests.sh", "run-e2e-tools.sh", "scope_tests.py", "no-cloud.sh", "ensure-submodules.sh"):
        shutil.copy2(VERIFY / name, v / name)
    (v / "fetch-e2e-tools.sh").write_text(FETCH_STUB)
    (v / "playwright_browsers.py").write_text("import sys\nsys.exit(0)\n")
    (v / "tf_plugin_cache.py").write_text(TF_STUB)
    (v / "artifact_cache.py").write_text("")
    for rel, text in FILES.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text)
    for name, body in OFFLINE.items():
        (v / name).write_text(body)
    for name, body in TIER.items():
        (v / name).write_text(TIER_HEAD + body)
    (v / "scope-map.yaml").write_text(MAP)
    git(tmp, "init", "-q", "-b", "main", str(root))
    git(root, "config", "user.email", "fixture@example.invalid")
    git(root, "config", "user.name", "fixture")
    git(root, "add", "-A")
    r = subprocess.run([sys.executable, str(v / "scope_tests.py"), "write"], capture_output=True, text=True,
                       env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
    check(f"scope_tests.py write fills the fixture map (exit {r.returncode})", r.returncode == 0, r.stderr)
    r = subprocess.run([sys.executable, str(v / "scope_tests.py"), "check"], capture_output=True, text=True,
                       env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
    check(f"and scope_tests.py check then finds it current (exit {r.returncode})", r.returncode == 0, r.stdout)
    written = (v / "scope-map.yaml").read_text()
    check("a tier test reads each doc of the doc-only range, so only the prose rule can leave the tier out",
          all(f"  {t}:\n" in written for t in ("test_tier_records.py", "test_tier_page.py"))
          and "    - decisions.md\n" in written and "    - gitops/ai-layer/web/kubecon.html\n" in written, written)
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "base")
    return root


def change(root: pathlib.Path, edits: dict[str, str]) -> str:
    """Commit the edits (text appended to each file) and return the commit before them, the range's base."""
    base = git(root, "rev-parse", "HEAD")
    for rel, text in edits.items():
        p = root / rel
        p.write_text(p.read_text() + text)
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "change " + ", ".join(edits))
    return base


def env_for(tmp: pathlib.Path, base: str | None) -> dict[str, str]:
    env = {"PATH": f"{tmp / 'bin'}:{os.environ['PATH']}", "HOME": str(tmp), "TMPDIR": str(tmp),
           "CALL_LOG": str(tmp / "calls.log"), "E2E_TOOLS_LOG_DIR": str(tmp / "kept-logs"),
           "WIB_ARTIFACT_CACHE": str(pathlib.Path(ARTIFACTS.name) / "artifacts"), "PYTHONDONTWRITEBYTECODE": "1"}
    if base is not None:
        env["HECATON_BASE_SHA"] = base
    return env


def run(root: pathlib.Path, tmp: pathlib.Path, base: str | None, *args: str) -> tuple[int, str, list[str]]:
    """The runner's exit, its output (stdout then stderr) and every logged call to a fetch, a tool or the cache."""
    bindir = tmp / "bin"
    bindir.mkdir(exist_ok=True)
    for name in ("curl", "tar", "unzip", "sha256sum", "xz", "uv", "jq", "openssl"):
        (bindir / name).write_text(LOGGING_STUB)
        (bindir / name).chmod(0o755)
    (bindir / "node").write_text(NODE24)
    (bindir / "node").chmod(0o755)
    calls = tmp / "calls.log"
    calls.write_text("")
    r = subprocess.run(["bash", str(root / "verify" / "run-e2e-tools.sh"), *args], capture_output=True, text=True,
                       env=env_for(tmp, base), timeout=300)
    return r.returncode, r.stdout + r.stderr, calls.read_text().splitlines()


def select(root: pathlib.Path, tmp: pathlib.Path, base: str) -> list[str]:
    r = subprocess.run([sys.executable, str(root / "verify" / "scope_tests.py"), "select", "tools"],
                       capture_output=True, text=True, env=env_for(tmp, base))
    return r.stdout.split()


def ran(out: str) -> set[str]:
    return {line[3:-3] for line in out.splitlines() if line.startswith("== ") and line.endswith(" ==")}


OFFLINE_CHECK = "run-tests.sh (the offline suite)"
ALL_TIER = set(TIER)

with tempfile.TemporaryDirectory() as t:
    tmp = pathlib.Path(t)
    root = fixture(tmp)
    vdir = root / "verify"

    print("== a doc-only range runs the offline tests that read it, no tier test, and fetches nothing ==")
    base = change(root, {"decisions.md": "\nA record.\n", "PROGRESS.md": "\n- a line\n",
                         "facilitation/kubecon-run-of-show.md": "\nRow 9.\n",
                         "gitops/ai-layer/web/kubecon.html": "<p>New copy for the room.</p>\n"})
    plan = select(root, tmp, base)
    check(f"scope_tests.py select tools says SCOPED with no tier test ({plan})", plan == ["SCOPED"])
    rc, out, calls = run(root, tmp, base)
    check(f"the runner passes, running the offline suite alone (exit {rc})",
          rc == 0 and ran(out) == {OFFLINE_CHECK, "test_records.py", "test_page.py"}, out)
    check("no tier test runs, the always one included", not ran(out) & ALL_TIER, out)
    check("nothing is fetched, no tool is called and no Terraform cache is named", calls == []
          and "Terraform provider cache:" not in out and "fixture fetch ran" not in out, "\n".join(calls) + "\n" + out)
    check("it says why: the paths are prose, and no tier test reads what is left",
          "4 of the changed paths are prose (.md, .mdx, .html), which selects no tier test" in out
          and "no tier test reads what the change touched, so the tools are neither checked for nor fetched" in out
          and "0 of the 4 tier tests" in out, out)

    print("== a code range runs the tier tests that read the code, and leaves the rest ==")
    base = change(root, {"gitops/app/values.yaml": "image: app:2\n", "gitops/ai-layer/web/event.js": "const n = 2;\n",
                         "gitops/ai-layer/web/kubecon.html": "<p>More copy.</p>\n"})
    plan = select(root, tmp, base)
    want = ["SCOPED", "test_tier_always.py", "test_tier_page.py", "test_tier_render.py"]
    check(f"scope_tests.py select tools names the render, the page (by event.js) and the always test ({plan})",
          plan[:1] == ["SCOPED"] and sorted(plan[1:]) == want[1:])
    rc, out, calls = run(root, tmp, base)
    check(f"the runner runs those three and the offline tests that read the range (exit {rc})",
          rc == 0 and ran(out) == {OFFLINE_CHECK, "test_values.py", "test_page.py", "test_tier_always.py",
                                   "test_tier_page.py", "test_tier_render.py"}, out)
    check("the tier test that reads only decisions.md does not run", "test_tier_records.py" not in ran(out), out)
    check("the tools are fetched, since tier tests run", "fixture fetch ran" in calls, "\n".join(calls))
    check("and it says 3 of the 4 tier tests ran", "3 of the 4 tier tests; the other 1 read nothing it touched" in out,
          out)

    print("== a change to the tools lock runs the whole tier ==")
    base = change(root, {"verify/e2e-tools.lock": "# a comment\n"})
    plan = select(root, tmp, base)
    check(f"scope_tests.py select tools says FULL ({plan})", plan == ["FULL"])
    rc, out, calls = run(root, tmp, base)
    check(f"the runner runs every tier test and every offline test (exit {rc})",
          rc == 0 and ran(out) == {OFFLINE_CHECK, *OFFLINE, *ALL_TIER}, out)
    check("naming the lock as why, and fetching the tools",
          "verify/e2e-tools.lock: it is in the map's full list" in out and "fixture fetch ran" in calls, out)

    print("== a failed tier test is named first with its log, and rerun alone ==")
    base = change(root, {"gitops/app/values.yaml": "broken: true\n"})
    rc, out, calls = run(root, tmp, base)
    kept = tmp / "kept-logs" / "test_tier_render.py.log"
    rerun = f"rerun it alone: bash {vdir}/run-e2e-tools.sh test_tier_render.py"
    check(f"the runner fails (exit {rc})", rc == 1, out)
    first = next((line for line in out.splitlines() if "test_tier_render.py" in line), "")
    check("the first line that names the failed test says it failed and gives its log",
          first == f"FAILED: test_tier_render.py (exit 1); its log: {kept}", first)
    check("its log is kept and holds what the test printed",
          kept.is_file() and "gitops/app/values.yaml holds broken: true" in kept.read_text(), out)
    summary = out.split("\nFAILED, each with its log; fix it and rerun that one alone, never the whole script:\n", 1)
    check("the failures are listed before the timings, each with its log and its rerun command",
          len(summary) == 2 and summary[1].startswith(f"  test_tier_render.py (exit 1)\n    log: {kept}\n    {rerun}\n")
          and "\nThe slowest checks:\n" in summary[1] and "\nThe slowest checks:\n" not in summary[0], out)

    rc, out, calls = run(root, tmp, base, "test_tier_render.py")
    check(f"the rerun command runs that test alone, with no offline suite, and still fails (exit {rc})",
          rc == 1 and ran(out) == {"test_tier_render.py"}
          and "1 checks ran (the 1 tier tests named, no offline suite)" in out and "fixture fetch ran" in calls, out)
    (root / "gitops/app/values.yaml").write_text("replicas: 1\nimage: app:2\n")
    git(root, "commit", "-qam", "fix values")
    rc, out, calls = run(root, tmp, base, "test_tier_render.py")
    check(f"fixed, the same command passes and the kept log is gone (exit {rc})",
          rc == 0 and ran(out) == {"test_tier_render.py"} and not kept.exists(), out)
    rc, out, calls = run(root, tmp, None, "test_records.py")
    check(f"a name that is not a tier test fails, naming it, before anything runs (exit {rc})",
          rc == 1 and "test_records.py is not a `# E2E TIER: tools` test" in out and not ran(out), out)

    print("== a failed offline test on a doc-only range is named with its own rerun command, and nothing is fetched ==")
    base = change(root, {"decisions.md": "BROKEN RECORD\n"})
    rc, out, calls = run(root, tmp, base)
    kept = tmp / "kept-logs" / "run-tests.sh.log"
    check(f"the runner fails on the offline suite alone (exit {rc})",
          rc == 1 and ran(out) == {OFFLINE_CHECK, "test_records.py"}, out)
    check("it names the offline suite first, with its kept log, and the failed test's own command",
          f"FAILED: {OFFLINE_CHECK} (exit 1); its log: {kept}" in out
          and f"    rerun it alone: python3 {vdir}/test_records.py\n" in out
          and kept.is_file() and "decisions.md holds BROKEN RECORD" in kept.read_text(), out)
    check("and nothing is fetched", calls == [], "\n".join(calls))

print()
if failures:
    print(f"{len(failures)} FAILED")
    sys.exit(1)
print("ALL PASS")
