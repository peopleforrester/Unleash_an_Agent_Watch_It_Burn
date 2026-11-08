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

#1113: staging tests only its newest tip. The workflow-level concurrency group is the workflow and the ref, and on a
staging push `cancel-in-progress` is true, so a newer push cancels the queued and running run before it. On an
agent/** push the group carries the run id and `cancel-in-progress` is false, so no candidate's checks are cancelled
(the dispatcher reads a cancelled check as red). The test evaluates both expressions for a staging push and for two
pushes to one agent branch, rather than matching their text, and GitHub's refusal of `queue: max` beside
`cancel-in-progress: true` in one block is checked on every block.

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
# The tip before the push, which scopes a push to staging (#1189).
BASE_ENV = {"PUSH_BEFORE": "${{ github.event.before }}"}
GH_TOKEN = "${{ github.token }}"
E2E_PERMISSIONS = {"contents": "read", "issues": "read"}
CHROMIUM_STEP = 'python3 verify/ci_chromium_libs.py "$RUNNER_TEMP/chromium-libs"'
STAGING_REF = "refs/heads/staging"
AGENT_REF = "refs/heads/agent/1113-1"

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


def evaluate(value: object, ctx: dict[str, str]) -> object:
    """A workflow value with each `${{ }}` expression evaluated against `ctx`, the github context's fields.

    Only what this workflow's concurrency block uses is understood: github.<field>, string literals, == and !=, &&
    and ||, and format(). GitHub's && and || return an operand, as Python's and and or do, and '' is falsy in both. A
    value that is one whole expression keeps its type (a boolean stays a boolean); one with text around an expression
    becomes a string, as on GitHub. Anything else raises ValueError, so an expression this does not read fails.
    """
    if not isinstance(value, str):
        return value

    def one(expr: str) -> object:
        tokens = re.findall(r"\s+|'[^']*'|github\.[\w-]+|format|==|!=|&&|\|\||[(),]|.", expr)
        out = []
        for tok in tokens:
            if tok.isspace():
                continue
            if tok.startswith("github."):
                field = tok.split(".", 1)[1]
                if field not in ctx:
                    raise ValueError(f"github.{field} is not in the test's context")
                out.append(repr(ctx[field]))
            elif tok.startswith("'") or tok in ("==", "!=", "(", ")", ","):
                out.append(tok)
            elif tok == "&&":
                out.append(" and ")
            elif tok == "||":
                out.append(" or ")
            elif tok == "format":
                out.append("fmt")
            else:
                raise ValueError(f"`{tok}` in `{expr}` is not an expression this test reads")
        fmt = lambda s, *args: s.format(*args)  # noqa: E731
        return eval("".join(out), {"__builtins__": {}}, {"fmt": fmt})  # the repo's own workflow text

    parts = re.split(r"\$\{\{(.*?)\}\}", value)
    if len(parts) == 3 and parts[0] == "" and parts[2] == "":
        return one(parts[1])
    text = []
    for i, part in enumerate(parts):
        got = part if i % 2 == 0 else one(part)
        text.append(str(got).lower() if isinstance(got, bool) else str(got))
    return "".join(text)


def push_context(doc: dict, ref: str, run_id: str) -> dict[str, str]:
    return {"workflow": str(doc.get("name", "")), "ref": ref, "run_id": run_id, "sha": "0" * 40}


def concurrency_problems(doc: dict) -> list[str]:
    """#1113: how the workflow-level group behaves on a staging push and on two pushes to one agent branch."""
    found: list[str] = []
    conc = doc.get("concurrency")
    if not isinstance(conc, dict):
        return ["no workflow-level concurrency block, so superseded staging runs queue behind the runner (#1113)"]
    if set(conc) != {"group", "cancel-in-progress"}:
        found.append(f"workflow concurrency keys are {sorted(conc)}, not group and cancel-in-progress (#1113)")
    try:
        staging = [{k: evaluate(conc.get(k), push_context(doc, STAGING_REF, rid))
                    for k in ("group", "cancel-in-progress")} for rid in ("101", "102")]
        agent = [{k: evaluate(conc.get(k), push_context(doc, AGENT_REF, rid))
                  for k in ("group", "cancel-in-progress")} for rid in ("201", "202")]
    except (ValueError, SyntaxError, NameError, TypeError, IndexError, KeyError) as exc:
        return found + [f"the workflow concurrency block does not evaluate: {exc}"]
    want = f"{doc.get('name')}-{STAGING_REF}"
    if staging[0]["group"] != want or staging[1]["group"] != want:
        found.append(f"a staging push's group is {staging[0]['group']!r}, not {want!r}, the workflow and the ref, "
                     "so a newer staging push does not supersede the one before it (#1113)")
    if staging[0]["cancel-in-progress"] is not True:
        found.append(f"cancel-in-progress on a staging push is {staging[0]['cancel-in-progress']!r}, not true, so a "
                     "superseded staging run keeps the runner (#1113)")
    if agent[0]["cancel-in-progress"] is not False:
        found.append(f"cancel-in-progress on an agent/** push is {agent[0]['cancel-in-progress']!r}, not false; the "
                     "dispatcher reads a cancelled candidate check as red")
    if agent[0]["group"] == agent[1]["group"]:
        found.append(f"two pushes to one agent branch share the group {agent[0]['group']!r}, so the default single "
                     "pending slot cancels a queued candidate's run")
    if any(str(a["group"]).lower() == want.lower() for a in agent):
        found.append("an agent/** push lands in staging's group")
    if not all(AGENT_REF in str(a["group"]) and str(doc.get("name")) in str(a["group"]) for a in agent):
        found.append(f"an agent/** push's group {agent[0]['group']!r} does not name the workflow and the ref")
    return found


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
    found += concurrency_problems(doc)
    # GitHub rejects the whole workflow when one block pairs queue: max with cancel-in-progress true.
    blocks = [("the workflow", doc.get("concurrency"))] + [
        (name, job.get("concurrency")) for name, job in (doc.get("jobs") or {}).items() if isinstance(job, dict)]
    for where, block in blocks:
        if not isinstance(block, dict):
            continue
        if block.get("queue") == "max" and block.get("cancel-in-progress", False) is not False:
            found.append(f"{where}: queue max beside cancel-in-progress {block.get('cancel-in-progress')!r} is a "
                         "workflow validation error on GitHub")

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
                    if key in s and not (key == "env" and s["run"].strip() == BASE_STEP):
                        found.append(f"{name}: the step `{s['run'].strip()}` has `{key}`")
            if str(s.get("run", "")).strip() == BASE_STEP and (s.get("env") or {}) != BASE_ENV:
                found.append(f"{name}: the step `{BASE_STEP}` does not get env {BASE_ENV} (#1189)")
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
    "no workflow-level concurrency": lambda d: d.pop("concurrency"),
    "the workflow group not per ref": lambda d: d["concurrency"].update({"group": "${{ github.workflow }}"}),
    "the workflow group without the workflow": lambda d: d["concurrency"].update(
        {"group": d["concurrency"]["group"].replace("${{ github.workflow }}-", "")}),
    "one workflow group for every agent push": lambda d: d["concurrency"].update(
        {"group": "${{ github.workflow }}-${{ github.ref }}"}),
    "staging runs never cancelled": lambda d: d["concurrency"].update({"cancel-in-progress": False}),
    "every run cancelled, agent branches too": lambda d: d["concurrency"].update({"cancel-in-progress": True}),
    "cancel-in-progress keyed on main": lambda d: d["concurrency"].update(
        {"cancel-in-progress": "${{ github.ref == 'refs/heads/main' }}"}),
    "queue max on the workflow block": lambda d: d["concurrency"].update({"queue": "max"}),
    "queue max beside cancel in a job": lambda d: d["jobs"]["offline"]["concurrency"].update(
        {"cancel-in-progress": "${{ github.ref == 'refs/heads/staging' }}"}),
    "an expression the test cannot read": lambda d: d["concurrency"].update(
        {"cancel-in-progress": "${{ startsWith(github.ref, 'refs/heads/staging') }}"}),
    "no base step": lambda d: d["jobs"]["e2e-tools"].update(
        {"steps": [s for s in d["jobs"]["e2e-tools"]["steps"] if s.get("run", "").strip() != BASE_STEP]}),
    "an action on a tag": lambda d: d["jobs"]["offline"]["steps"][0].update({"uses": "actions/checkout@v7"}),
    "no GH_TOKEN on the e2e job": lambda d: d["jobs"]["e2e-tools"].pop("env"),
    "no PUSH_BEFORE on the offline job's base step (#1189)": lambda d: next(
        st for st in d["jobs"]["offline"]["steps"] if str(st.get("run", "")).strip() == BASE_STEP).pop("env"),
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

# The evaluator on its own, so a pass below means the expressions were read and not skipped.
ctx = push_context(doc, STAGING_REF, "7")
check("the evaluator reads a whole boolean expression as a boolean",
      evaluate("${{ github.ref == 'refs/heads/staging' }}", ctx) is True)
check("the evaluator joins text around expressions into a string",
      evaluate("a-${{ github.run_id }}-${{ github.ref != 'refs/heads/staging' && 'x' || '' }}", ctx) == "a-7-")
check("the evaluator reads format()", evaluate("${{ format('-run-{0}', github.run_id) }}", ctx) == "-run-7")

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


def base_sha(cwd: Path, env_file: Path | None, before: str | None = None) -> tuple[int, str, str]:
    env = {k: v for k, v in os.environ.items() if k not in ("GITHUB_ENV", "PUSH_BEFORE")}
    if before is not None:
        env["PUSH_BEFORE"] = before
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
    check("a commit already in staging with no PUSH_BEFORE leaves HECATON_BASE_SHA unset, so the suites run whole",
          rc == 0 and env == "" and "left unset" in out, f"exit {rc}, wrote {env!r}: {out}")

    # A push to staging (#1189): the tip before the push scopes it.
    d_tip = git(work, "rev-parse", "HEAD")
    rc, out, env = base_sha(work, t / "env5", fork)
    check("a push to staging gets HECATON_BASE_SHA, the tip before the push (#1189)",
          rc == 0 and env == f"HECATON_BASE_SHA={fork}\n", f"exit {rc}, wrote {env!r}: {out}")
    for label, before in (("all zeros, a new branch", "0" * 40), ("the commit itself", d_tip),
                          ("not in the history", "1" * 40), ("not an ancestor, a force push", git(work, "rev-parse", "agent/1020-1"))):
        rc, out, env = base_sha(work, t / f"env-{label[:3]}", before)
        check(f"a PUSH_BEFORE that is {label} leaves HECATON_BASE_SHA unset", rc == 0 and env == "" and "left unset" in out,
              f"exit {rc}, wrote {env!r}: {out}")

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
