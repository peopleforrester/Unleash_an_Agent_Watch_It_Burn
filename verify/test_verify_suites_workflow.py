# ABOUTME: Holds .github/workflows/verify-suites.yml (#1020): push to agent/** and staging only, never a pull_request
# ABOUTME: trigger, both jobs on the tanjiro runner, each running its suite after verify/ci-base-sha.sh. Offline.
"""Offline.

#1020 moved hecaton's validation of this repo from netcup onto a self-hosted runner on Tanjiro. The repo is public, so
a pull_request or pull_request_target trigger would run a fork's code on Michael's machine; a push comes only from an
account with write access. Hecaton's dispatcher pushes each candidate to agent/<issue>-<run> and waits for the two
checks on that SHA, so a paths filter, a skipped step or a cancelled job would leave it waiting or let a red suite
read green.

#1047: the tools tier reads issues with gh (verify/gh_comments.py, #863), which never reads anonymously, so the e2e
job sets GH_TOKEN to the run's own token and widens its permissions to contents and issues, both read. The offline
job reads no issue and keeps the workflow's contents: read alone. Before the tier, the e2e job runs
verify/ci_chromium_libs.py, which unpacks the libraries and fonts Playwright's Chromium needs and Tanjiro lacks.

The checker runs first on copies of the workflow, each broken one way, so a check that stopped matching reads as that
and not as a pass. verify/ci-base-sha.sh is then run in throwaway repositories: an agent branch gets the merge base,
a commit already in staging gets no HECATON_BASE_SHA (so #1018's runners run whole), and a missing GITHUB_ENV or an
unrelated history fails.
"""
from __future__ import annotations

import copy
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
WORKFLOW = REPO / ".github" / "workflows" / "verify-suites.yml"
BASE_SCRIPT = REPO / "verify" / "ci-base-sha.sh"
LABELS = ["self-hosted", "Linux", "X64", "tanjiro"]
BRANCHES = {"agent/**", "staging"}
SUITES = {"offline": "bash verify/run-tests.sh", "e2e-tools": "bash verify/run-e2e-tools.sh"}
BASE_STEP = "bash verify/ci-base-sha.sh"
GH_TOKEN = "${{ github.token }}"
E2E_PERMISSIONS = {"contents": "read", "issues": "read"}
CHROMIUM_STEP = 'python3 verify/ci_chromium_libs.py "$RUNNER_TEMP/chromium-libs"'

failures: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(("PASS " if ok else "FAIL ") + label + (f"\n     {detail}" if detail and not ok else ""))
    if not ok:
        failures.append(label)


def triggers(doc: dict) -> dict:
    """The `on:` block as a dict of event to settings; PyYAML reads the bare key `on` as True."""
    on = doc.get("on", doc.get(True))
    if isinstance(on, str):
        return {on: None}
    if isinstance(on, list):
        return {e: None for e in on}
    return dict(on or {})


def problems(doc: dict, text: str) -> list[str]:
    """Every way the workflow breaks #1020's rules, as one line each; empty when it holds."""
    found: list[str] = []
    on = triggers(doc)
    if set(on) != {"push"}:
        found.append(f"triggers are {sorted(map(str, on))}, not push alone")
    for event in on:
        if "pull_request" in str(event):
            found.append(f"a {event} trigger runs a fork's code on Tanjiro")
    push = on.get("push") or {}
    if not isinstance(push, dict) or set(push) != {"branches"}:
        found.append(f"push carries {sorted(push) if isinstance(push, dict) else push!r}, not branches alone "
                     "(a paths or tags filter would leave the dispatcher waiting on a check that never starts)")
    elif set(push["branches"] or []) != BRANCHES:
        found.append(f"push branches are {push['branches']}, not {sorted(BRANCHES)}")
    # A trigger can also arrive through a key the parse above does not look at; no line outside a comment names one.
    for n, line in enumerate(text.splitlines(), 1):
        if re.search(r"pull_request", line.split("#", 1)[0]):
            found.append(f"line {n} names pull_request outside a comment: {line.strip()}")
    if re.search(r"\bsecrets\.", text):
        found.append("the workflow reads a secret; a public repo's self-hosted job holds none")
    if doc.get("permissions") != {"contents": "read"}:
        found.append(f"permissions are {doc.get('permissions')!r}, not contents: read")

    jobs = doc.get("jobs") or {}
    # #1047: the tools tier reads issues with gh, so the e2e job hands gh the run's own token, read-only.
    e2e = jobs.get("e2e-tools") if isinstance(jobs.get("e2e-tools"), dict) else {}
    if (e2e.get("env") or {}).get("GH_TOKEN") != GH_TOKEN:
        found.append(f"e2e-tools: env GH_TOKEN is {(e2e.get('env') or {}).get('GH_TOKEN')!r}, not {GH_TOKEN}, so "
                     "verify/gh_comments.py finds no token and the tier's issue reads fail (#1047)")
    if e2e.get("permissions") != E2E_PERMISSIONS:
        found.append(f"e2e-tools: permissions are {e2e.get('permissions')!r}, not {E2E_PERMISSIONS}")
    # #1047: Chromium's libraries and fonts are unpacked for the job before the tier, which needs them.
    e2e_runs = [str(s.get("run", "")).strip() for s in (e2e.get("steps") or [])]
    if CHROMIUM_STEP not in e2e_runs:
        found.append(f"e2e-tools: no step runs `{CHROMIUM_STEP}`, so Chromium cannot start on Tanjiro (#1047)")
    elif SUITES["e2e-tools"] in e2e_runs and e2e_runs.index(CHROMIUM_STEP) > e2e_runs.index(SUITES["e2e-tools"]):
        found.append(f"e2e-tools: `{CHROMIUM_STEP}` runs after the suite")
    if "permissions" in (jobs.get("offline") or {}):
        found.append("offline: has its own permissions; it reads nothing beyond the checkout")
    if set(jobs) != set(SUITES):
        found.append(f"jobs are {sorted(jobs)}, not {sorted(SUITES)}")
    for name, job in jobs.items():
        if not isinstance(job, dict) or "uses" in job:
            found.append(f"{name}: not a job with its own steps")
            continue
        if job.get("runs-on") != LABELS:
            found.append(f"{name}: runs-on is {job.get('runs-on')!r}, not {LABELS}")
        for key in ("if", "continue-on-error", "strategy", "needs"):
            if key in job:
                found.append(f"{name}: has `{key}`, which can skip the suite or let its failure pass")
        timeout = job.get("timeout-minutes")
        if not isinstance(timeout, int) or isinstance(timeout, bool) or not 0 < timeout <= 360:
            found.append(f"{name}: timeout-minutes is {timeout!r}, not a whole number of minutes up to 360")
        conc = job.get("concurrency")
        if not isinstance(conc, dict):
            found.append(f"{name}: no concurrency block")
        else:
            if "${{ github.ref }}" not in str(conc.get("group", "")):
                found.append(f"{name}: concurrency group {conc.get('group')!r} is not per ref")
            if conc.get("cancel-in-progress", False) is not False:
                found.append(f"{name}: cancel-in-progress is {conc.get('cancel-in-progress')!r}; a push must queue")
            if conc.get("queue") != "max":
                found.append(f"{name}: queue is {conc.get('queue')!r}; without max a third push cancels the second")
        steps = job.get("steps") or []
        runs = [str(s.get("run", "")).strip() for s in steps]
        want = SUITES.get(name)
        if want and want not in runs:
            found.append(f"{name}: no step runs `{want}`")
        if BASE_STEP not in runs:
            found.append(f"{name}: no step runs `{BASE_STEP}`, so HECATON_BASE_SHA is never set")
        elif want in runs and runs.index(BASE_STEP) > runs.index(want):
            found.append(f"{name}: `{BASE_STEP}` runs after the suite")
        for s in steps:
            if str(s.get("run", "")).strip() in (want, BASE_STEP):
                for key in ("if", "continue-on-error", "env", "working-directory", "shell"):
                    if key in s:
                        found.append(f"{name}: the step `{s['run'].strip()}` has `{key}`")
            uses = str(s.get("uses") or "")
            if uses and not re.fullmatch(r"[\w.-]+/[\w.-]+@[0-9a-f]{40}", uses):
                found.append(f"{name}: `{uses}` is not pinned to a commit SHA")
    return found


# The checker, on copies broken one way each.
if not WORKFLOW.is_file():
    print(f"FAIL: {WORKFLOW.relative_to(REPO)} is missing; nothing runs the suites on Tanjiro", file=sys.stderr)
    sys.exit(1)
text = WORKFLOW.read_text()
doc = yaml.safe_load(text)
on_key = "on" if "on" in doc else True


def broken(edit) -> dict:
    d = copy.deepcopy(doc)
    edit(d)
    return d


cases = {
    "a pull_request trigger": lambda d: d[on_key].update({"pull_request": None}),
    "a pull_request_target trigger": lambda d: d[on_key].update({"pull_request_target": {"branches": ["staging"]}}),
    "a workflow_dispatch trigger": lambda d: d[on_key].update({"workflow_dispatch": None}),
    "a paths filter on push": lambda d: d[on_key]["push"].update({"paths": ["verify/**"]}),
    "main among the branches": lambda d: d[on_key]["push"]["branches"].append("main"),
    "the offline job off the tanjiro label": lambda d: d["jobs"]["offline"].update(
        {"runs-on": ["self-hosted", "Linux", "X64", "netcup"]}),
    "the e2e job on a hosted runner": lambda d: d["jobs"]["e2e-tools"].update({"runs-on": "ubuntu-latest"}),
    "no offline suite step": lambda d: d["jobs"]["offline"].update(
        {"steps": [s for s in d["jobs"]["offline"]["steps"] if s.get("run", "").strip() != SUITES["offline"]]}),
    "no e2e suite step": lambda d: d["jobs"]["e2e-tools"].update(
        {"steps": [s for s in d["jobs"]["e2e-tools"]["steps"] if s.get("run", "").strip() != SUITES["e2e-tools"]]}),
    "the e2e job removed": lambda d: d["jobs"].pop("e2e-tools"),
    "continue-on-error on the suite step": lambda d: [s.update({"continue-on-error": True})
                                                      for s in d["jobs"]["offline"]["steps"]
                                                      if s.get("run", "").strip() == SUITES["offline"]],
    "no timeout": lambda d: d["jobs"]["offline"].pop("timeout-minutes"),
    "cancel-in-progress": lambda d: d["jobs"]["e2e-tools"]["concurrency"].update({"cancel-in-progress": True}),
    "a group not per ref": lambda d: d["jobs"]["offline"]["concurrency"].update({"group": "verify-suites"}),
    "the default single-slot queue": lambda d: d["jobs"]["offline"]["concurrency"].pop("queue"),
    "no base step": lambda d: d["jobs"]["e2e-tools"].update(
        {"steps": [s for s in d["jobs"]["e2e-tools"]["steps"] if s.get("run", "").strip() != BASE_STEP]}),
    "an action on a tag": lambda d: d["jobs"]["offline"]["steps"][0].update({"uses": "actions/checkout@v7"}),
    "no GH_TOKEN on the e2e job": lambda d: d["jobs"]["e2e-tools"].pop("env"),
    "an empty GH_TOKEN on the e2e job": lambda d: d["jobs"]["e2e-tools"]["env"].update({"GH_TOKEN": ""}),
    "the e2e job without issues: read": lambda d: d["jobs"]["e2e-tools"]["permissions"].pop("issues"),
    "issues: write on the e2e job": lambda d: d["jobs"]["e2e-tools"]["permissions"].update({"issues": "write"}),
    "contents: write on the e2e job": lambda d: d["jobs"]["e2e-tools"]["permissions"].update({"contents": "write"}),
    "permissions on the offline job": lambda d: d["jobs"]["offline"].update({"permissions": {"issues": "read"}}),
    "no Chromium libraries step": lambda d: d["jobs"]["e2e-tools"].update(
        {"steps": [s for s in d["jobs"]["e2e-tools"]["steps"] if s.get("run", "").strip() != CHROMIUM_STEP]}),
    "the Chromium libraries step after the suite": lambda d: d["jobs"]["e2e-tools"].update(
        {"steps": [s for s in d["jobs"]["e2e-tools"]["steps"] if s.get("run", "").strip() != CHROMIUM_STEP]
         + [s for s in d["jobs"]["e2e-tools"]["steps"] if s.get("run", "").strip() == CHROMIUM_STEP]}),
}
for what, edit in cases.items():
    got = problems(broken(edit), text)
    check(f"the checker fails a workflow with {what}", bool(got))
check("the checker fails a text that names pull_request outside a comment",
      bool(problems(doc, text + "\n# a comment is fine\nx: pull_request\n")))
check("the checker fails a text that reads a secret", bool(problems(doc, text + "\n# ${{ secrets.TOKEN }}\n")))

# The workflow itself.
got = problems(doc, text)
check("verify-suites.yml holds every rule of #1020", not got, "\n     ".join(got))


# verify/ci-base-sha.sh in throwaway repositories.
def git(cwd: Path, *args: str) -> str:
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@t", "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1"}
    return subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True,
                          env=env).stdout.strip()


def commit(cwd: Path, name: str) -> str:
    (cwd / name).write_text(name)
    git(cwd, "add", name)
    git(cwd, "commit", "-q", "-m", name)
    return git(cwd, "rev-parse", "HEAD")


def base_sha(cwd: Path, env_file: Path | None) -> tuple[int, str, str]:
    env = {k: v for k, v in os.environ.items() if k != "GITHUB_ENV"}
    env.update({"GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1"})
    if env_file is not None:
        env["GITHUB_ENV"] = str(env_file)
    r = subprocess.run(["bash", str(BASE_SCRIPT)], cwd=cwd, env=env, capture_output=True, text=True)
    return r.returncode, r.stdout + r.stderr, env_file.read_text() if env_file and env_file.exists() else ""


with tempfile.TemporaryDirectory() as tmp:
    t = Path(tmp)
    origin, work = t / "origin.git", t / "work"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "staging", str(origin)], check=True)
    subprocess.run(["git", "init", "-q", "-b", "staging", str(work)], check=True)
    git(work, "remote", "add", "origin", str(origin))
    fork = commit(work, "a")
    git(work, "push", "-q", "origin", "staging")
    git(work, "checkout", "-q", "-b", "agent/1020-1")
    commit(work, "b")
    commit(work, "c")
    # Staging moves on after the branch was cut, so the merge base is neither tip.
    git(work, "checkout", "-q", "staging")
    commit(work, "d")
    git(work, "push", "-q", "origin", "staging")
    git(work, "reset", "-q", "--hard", fork)
    git(work, "checkout", "-q", "agent/1020-1")

    rc, out, env = base_sha(work, t / "env1")
    check("an agent branch gets HECATON_BASE_SHA, the merge base with origin/staging",
          rc == 0 and env == f"HECATON_BASE_SHA={fork}\n", f"exit {rc}, wrote {env!r}: {out}")

    git(work, "checkout", "-q", "--detach", "origin/staging")
    rc, out, env = base_sha(work, t / "env2")
    check("a commit already in staging leaves HECATON_BASE_SHA unset, so the suites run whole",
          rc == 0 and env == "" and "left unset" in out, f"exit {rc}, wrote {env!r}: {out}")

    git(work, "checkout", "-q", "agent/1020-1")
    rc, out, _ = base_sha(work, None)
    check("no GITHUB_ENV fails, naming it", rc == 1 and "GITHUB_ENV" in out, f"exit {rc}: {out}")

    git(work, "checkout", "-q", "--orphan", "agent/unrelated")
    commit(work, "e")
    rc, out, env = base_sha(work, t / "env3")
    check("a history with nothing in common with staging fails", rc == 1 and env == "", f"exit {rc}: {out}")

    git(work, "remote", "set-url", "origin", str(t / "missing.git"))
    git(work, "checkout", "-q", "agent/1020-1")
    rc, out, env = base_sha(work, t / "env4")
    check("an origin that cannot be fetched fails", rc == 1 and env == "", f"exit {rc}: {out}")

if failures:
    print(f"\n{len(failures)} check(s) failed", file=sys.stderr)
    sys.exit(1)
print("\nverify-suites.yml and ci-base-sha.sh hold")
