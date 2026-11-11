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

#1200: the e2e job installs Node with actions/setup-node before the suite, at a major run-e2e-tools.sh accepts (24 or
later; 26 since #1200), so the node harnesses never run on a Node the tier refuses.

#1313: before the suite, the e2e job writes TMPDIR=$RUNNER_TEMP to GITHUB_ENV. Unset, run-e2e-tools.sh takes the
checkout's tmp/, 119 bytes on Tanjiro, and a Terraform provider's socket under it passes Linux's 107-byte limit, so no
provider started and the tier's three terraform tests failed on staging aa2c7dcd.

#1113: staging tests only its newest tip. The workflow-level concurrency group is the workflow and the ref, and on a
staging push `cancel-in-progress` is true, so a newer push cancels the queued and running run before it. On an
agent/** push the group carries the run id and `cancel-in-progress` is false, so no candidate's checks are cancelled
(the dispatcher reads a cancelled check as red). The test evaluates both expressions for a staging push and for two
pushes to one agent branch, rather than matching their text, and GitHub's refusal of `queue: max` beside
`cancel-in-progress: true` in one block is checked on every block.

#1195: a commit already in staging is scoped by its newest first-parent ancestor whose verify-suites run on staging
finished success, not by github.event.before (#1189), since a newer staging push cancels the run before it (#1113)
and a cancelled push's changes then fell in no run's scope. The base step reads the runs with gh and the job's
token, so the workflow and the e2e job carry actions: read and the step gets GH_TOKEN.

The checker runs first on copies of the workflow, each broken one way, so a check that stopped matching reads as that
and not as a pass. verify/ci-base-sha.sh is then run in throwaway repositories, with a stub gh on PATH that answers
the Actions API from a file the test writes: an agent branch gets the merge base and never calls gh; a staging tip
whose push before it was cancelled gets the last green first-parent ancestor, and the cancelled push's file is in the
diff from that base; a green run that is the commit itself, a second parent, another branch, another event or a
force-pushed commit is never the base; no green ancestor leaves HECATON_BASE_SHA unset (so #1018's runners run
whole); and a missing GITHUB_ENV, GH_TOKEN or GITHUB_REPOSITORY, a failed or malformed API answer, an unrelated
history or an unreachable origin fails.

#1325: the e2e job failed in the base step on a TLS handshake timeout reading the Actions API, on staging 49387d36 and
again on 92f5514c. A read that gets no answer, a 429 or a 5xx is tried again after waits of 5, 15, 30 and 60 s, five
tries in all (a stub sleep stands in for the waits); a read GitHub answered with any other status fails at once.

#1330: on staging 3da68e84 the base step's fetch of staging got no answer and git waited out curl's 300 s connect
timeout. The fetch now runs under timeout with a 120 s limit and is tried again after the same waits. A stub git
passes every call through to git but fails or hangs the first fetches, and a stub timeout logs its call and, for the
hang, shortens the limit so the real timeout kills the hung fetch in seconds.
"""
from __future__ import annotations

import copy
import json
import os
import re
import shutil
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
# The job's token, which the base step reads staging's green runs with (#1195).
BASE_ENV = {"GH_TOKEN": GH_TOKEN}
WORKFLOW_PERMISSIONS = {"contents": "read", "actions": "read"}
E2E_PERMISSIONS = {"contents": "read", "issues": "read", "actions": "read"}
CHROMIUM_STEP = 'python3 verify/ci_chromium_libs.py "$RUNNER_TEMP/chromium-libs"'
# #1313: the e2e job's TMPDIR is the job's temp directory; the checkout's tmp/ is too long for a provider's socket.
TMPDIR_STEP = 'echo "TMPDIR=$RUNNER_TEMP" >> "$GITHUB_ENV"'
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
    if doc.get("permissions") != WORKFLOW_PERMISSIONS:
        found.append(f"permissions are {doc.get('permissions')!r}, not {WORKFLOW_PERMISSIONS}: the offline job's base "
                     "step reads staging's runs with actions: read (#1195)")
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
    # #1313: unset, TMPDIR is the checkout's tmp/, 119 bytes on Tanjiro, where no Terraform provider can start.
    if TMPDIR_STEP not in e2e_runs:
        found.append(f"e2e-tools: no step runs `{TMPDIR_STEP}`, so the suite's TMPDIR is the checkout's tmp/, too long "
                     "for a Terraform provider's socket (#1313)")
    elif SUITES["e2e-tools"] in e2e_runs and e2e_runs.index(TMPDIR_STEP) > e2e_runs.index(SUITES["e2e-tools"]):
        found.append(f"e2e-tools: `{TMPDIR_STEP}` runs after the suite (#1313)")
    # #1200: the node harnesses run on the Node on PATH, which run-e2e-tools.sh refuses only below 24, so the e2e job
    # installs a Node major of 24 or later (26 today) before the suite.
    e2e_steps = e2e.get("steps") or []
    node_steps = [i for i, st in enumerate(e2e_steps) if str(st.get("uses") or "").startswith("actions/setup-node@")]
    if not node_steps:
        found.append("e2e-tools: no actions/setup-node step, so the tier runs on whatever Node the runner has (#1200)")
    for i in node_steps:
        version = str((e2e_steps[i].get("with") or {}).get("node-version", ""))
        if not re.fullmatch(r"\d+", version) or int(version) < 24:
            found.append(f"e2e-tools: setup-node installs node-version {version!r}, not a major of 24 or later, "
                         "which run-e2e-tools.sh refuses (#1200)")
        if SUITES["e2e-tools"] in e2e_runs and i > e2e_runs.index(SUITES["e2e-tools"]):
            found.append("e2e-tools: setup-node runs after the suite")
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
                found.append(f"{name}: the step `{BASE_STEP}` does not get env {BASE_ENV}, so it cannot read "
                             "staging's green runs (#1195)")
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
    "no GH_TOKEN on the offline job's base step (#1195)": lambda d: next(
        st for st in d["jobs"]["offline"]["steps"] if str(st.get("run", "")).strip() == BASE_STEP).pop("env"),
    "PUSH_BEFORE back on the e2e job's base step (#1195)": lambda d: next(
        st for st in d["jobs"]["e2e-tools"]["steps"] if str(st.get("run", "")).strip() == BASE_STEP)["env"].update(
        {"PUSH_BEFORE": "${{ github.event.before }}"}),
    "the workflow without actions: read (#1195)": lambda d: d["permissions"].pop("actions"),
    "actions: write on the workflow": lambda d: d["permissions"].update({"actions": "write"}),
    "the e2e job without actions: read (#1195)": lambda d: d["jobs"]["e2e-tools"]["permissions"].pop("actions"),
    "an empty GH_TOKEN on the e2e job": lambda d: d["jobs"]["e2e-tools"]["env"].update({"GH_TOKEN": ""}),
    "the e2e job without issues: read": lambda d: d["jobs"]["e2e-tools"]["permissions"].pop("issues"),
    "issues: write on the e2e job": lambda d: d["jobs"]["e2e-tools"]["permissions"].update({"issues": "write"}),
    "contents: write on the e2e job": lambda d: d["jobs"]["e2e-tools"]["permissions"].update({"contents": "write"}),
    "permissions on the offline job": lambda d: d["jobs"]["offline"].update({"permissions": {"issues": "read"}}),
    "Node 22 on the e2e job (#1200)": lambda d: [st["with"].update({"node-version": "22"})
                                                 for st in d["jobs"]["e2e-tools"]["steps"]
                                                 if str(st.get("uses", "")).startswith("actions/setup-node@")],
    "no setup-node step on the e2e job (#1200)": lambda d: d["jobs"]["e2e-tools"].update(
        {"steps": [st for st in d["jobs"]["e2e-tools"]["steps"]
                   if not str(st.get("uses", "")).startswith("actions/setup-node@")]}),
    "no Chromium libraries step": lambda d: d["jobs"]["e2e-tools"].update(
        {"steps": [s for s in d["jobs"]["e2e-tools"]["steps"] if s.get("run", "").strip() != CHROMIUM_STEP]}),
    "the Chromium libraries step after the suite": lambda d: d["jobs"]["e2e-tools"].update(
        {"steps": [s for s in d["jobs"]["e2e-tools"]["steps"] if s.get("run", "").strip() != CHROMIUM_STEP]
         + [s for s in d["jobs"]["e2e-tools"]["steps"] if s.get("run", "").strip() == CHROMIUM_STEP]}),
    "no TMPDIR step on the e2e job (#1313)": lambda d: d["jobs"]["e2e-tools"].update(
        {"steps": [s for s in d["jobs"]["e2e-tools"]["steps"] if s.get("run", "").strip() != TMPDIR_STEP]}),
    "the TMPDIR step after the suite (#1313)": lambda d: d["jobs"]["e2e-tools"].update(
        {"steps": [s for s in d["jobs"]["e2e-tools"]["steps"] if s.get("run", "").strip() != TMPDIR_STEP]
         + [s for s in d["jobs"]["e2e-tools"]["steps"] if s.get("run", "").strip() == TMPDIR_STEP]}),
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


# What gh prints on stderr when a read gets no answer, as staging 49387d36's e2e job printed it (#1325), and when
# GitHub answers with an error status.
NO_ANSWER = ('Get "https://api.github.com/repos/owner/repo/actions/workflows/verify-suites.yml/runs": '
             'net/http: TLS handshake timeout')


def http_error(status: int) -> str:
    return f"gh: Error (HTTP {status})"


# What git printed when staging 3da68e84's e2e job's fetch got no answer (#1330).
FETCH_NO_ANSWER = ("fatal: unable to access 'https://github.com/owner/repo/': "
                   "Connection timed out after 300028 milliseconds")
# The script's own limit on one fetch, and the call it makes under timeout; the stub timeout logs the call.
FETCH_LIMIT_S = "120"
FETCH_CALL = f"-k 10 {FETCH_LIMIT_S} git fetch --no-tags --prune origin +refs/heads/staging:refs/remotes/origin/staging"
# The limit the stub timeout puts in place of the script's for a fetch made to hang, so the real timeout kills it in
# seconds, not minutes; the fetches after it keep the script's own limit.
HANG_LIMIT_S = "3"
REAL = {name: shutil.which(name) for name in ("git", "timeout", "sleep")}
for _name, _path in REAL.items():
    if not _path:
        sys.exit(f"{_name} is not on PATH; the base step's stubs pass through to it")


def base_sha(cwd: Path, env_file: Path | None, runs: object | None = None, *, token: bool = True,
             repo: bool = True, gh_fails: int = 0, gh_err: str = NO_ANSWER, fetch_fails: int = 0,
             fetch_hangs: bool = False) -> tuple[int, str, str]:
    """Runs ci-base-sha.sh in `cwd` with a stub gh first on PATH that logs its arguments to GH_LOG and prints `runs`
    as JSON. Its first `gh_fails` calls instead print `gh_err` on stderr and exit 1. A stub sleep logs each wait to
    SLEEP_LOG and returns at once. A stub git passes every call to the real git, but logs each fetch to FETCH_LOG and
    makes its first `fetch_fails` fetches print FETCH_NO_ANSWER and exit 128, or, with `fetch_hangs`, wait until the
    real timeout kills them. A stub timeout logs its arguments to TIMEOUT_LOG and runs the real timeout with them,
    the limit replaced by HANG_LIMIT_S for those hanging fetches alone. Returns the exit code, the output and what the script wrote
    to `env_file`; the gh calls, the waits, the fetches and the timeout calls are left on base_sha.gh_calls,
    base_sha.sleeps, base_sha.fetches and base_sha.timeouts."""
    stub = cwd.parent / "stub"
    stub.mkdir(exist_ok=True)
    (stub / "gh").write_text('#!/usr/bin/env bash\nprintf "%s\\n" "$*" >>"$GH_LOG"\n'
                             'if (( $(wc -l <"$GH_LOG") <= GH_STUB_FAIL )); then\n'
                             '    printf "%s\\n" "$GH_STUB_ERR" >&2; exit 1\nfi\ncat "$GH_STUB_RUNS"\n')
    (stub / "sleep").write_text('#!/usr/bin/env bash\nprintf "%s\\n" "$*" >>"$SLEEP_LOG"\n')
    (stub / "git").write_text(
        '#!/usr/bin/env bash\nif [[ "$1" == fetch ]]; then\n    printf "%s\\n" "$*" >>"$FETCH_LOG"\n'
        '    if (( $(wc -l <"$FETCH_LOG") <= FETCH_STUB_FAIL )); then\n'
        f'        [[ -z "$FETCH_STUB_HANG" ]] || exec "{REAL["sleep"]}" 600\n'
        '        printf "%s\\n" "$FETCH_STUB_ERR" >&2; exit 128\n    fi\nfi\n'
        f'exec "{REAL["git"]}" "$@"\n')
    # The script calls `timeout -k <s> <limit> <command...>`; the stub keeps the kill-after and swaps the limit. The
    # checks below hold every logged call to FETCH_CALL, so a call in another shape fails there by name.
    (stub / "timeout").write_text(
        '#!/usr/bin/env bash\nprintf "%s\\n" "$*" >>"$TIMEOUT_LOG"\n'
        'kill_after="$2" limit="$3"; shift 3\n'
        'if [[ -n "$FETCH_STUB_HANG" ]] && (( $(wc -l <"$TIMEOUT_LOG") <= FETCH_STUB_FAIL )); then\n'
        '    limit="$HANG_LIMIT_S"\nfi\n'
        f'exec "{REAL["timeout"]}" -k "$kill_after" "$limit" "$@"\n')
    for name in ("gh", "sleep", "git", "timeout"):
        (stub / name).chmod(0o755)
    (stub / "runs.json").write_text(runs if isinstance(runs, str) else json.dumps(runs or {"workflow_runs": []}))
    log, sleeps, fetches, timeouts = stub / "gh.log", stub / "sleep.log", stub / "fetch.log", stub / "timeout.log"
    for f in (log, sleeps, fetches, timeouts):
        f.write_text("")
    drop = ("GITHUB_ENV", "PUSH_BEFORE", "GH_TOKEN", "GITHUB_TOKEN", "GITHUB_REPOSITORY", "GH_STUB_FAIL", "GH_STUB_ERR")
    env = {k: v for k, v in os.environ.items() if k not in drop}
    env.update({"GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1", "PATH": f"{stub}:{env.get('PATH', '')}",
                "GH_LOG": str(log), "GH_STUB_RUNS": str(stub / "runs.json"), "SLEEP_LOG": str(sleeps),
                "GH_STUB_FAIL": str(gh_fails), "GH_STUB_ERR": gh_err, "FETCH_LOG": str(fetches),
                "TIMEOUT_LOG": str(timeouts), "FETCH_STUB_FAIL": str(fetch_fails), "FETCH_STUB_ERR": FETCH_NO_ANSWER,
                "FETCH_STUB_HANG": "1" if fetch_hangs else "", "HANG_LIMIT_S": HANG_LIMIT_S})
    if token:
        env["GH_TOKEN"] = "stub-token"
    if repo:
        env["GITHUB_REPOSITORY"] = "owner/repo"
    if env_file is not None:
        env["GITHUB_ENV"] = str(env_file)
    r = subprocess.run(["bash", str(BASE_SCRIPT)], cwd=cwd, env=env, capture_output=True, text=True)
    base_sha.gh_calls = log.read_text().splitlines()
    base_sha.sleeps = sleeps.read_text().splitlines()
    base_sha.fetches = fetches.read_text().splitlines()
    base_sha.timeouts = timeouts.read_text().splitlines()
    return r.returncode, r.stdout + r.stderr, env_file.read_text() if env_file and env_file.exists() else ""


def run(sha: str, conclusion: str | None = "success", branch: str = "staging", event: str = "push") -> dict:
    """One workflow run as the Actions API lists it."""
    return {"head_sha": sha, "head_branch": branch, "event": event,
            "status": "completed" if conclusion else "in_progress", "conclusion": conclusion}


with tempfile.TemporaryDirectory() as tmp:
    t = Path(tmp)
    origin, work = t / "origin.git", t / "work"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "staging", str(origin)], check=True)
    subprocess.run(["git", "init", "-q", "-b", "staging", str(work)], check=True)
    git(work, "remote", "add", "origin", str(origin))
    fork = commit(work, "a")
    git(work, "push", "-q", "origin", "staging")
    git(work, "checkout", "-q", "-b", "agent/1020-1")
    second = commit(work, "b")
    commit(work, "c")
    # Staging moves on after the branch was cut: s2 is a push whose run the next push cancelled (#1113), s3 merges the
    # agent branch, so its second parent is an ancestor but not a first-parent one, and s4 is the tip being run.
    git(work, "checkout", "-q", "staging")
    s2 = commit(work, "cancelled-push.txt")
    git(work, "merge", "-q", "--no-ff", "-m", "s3", "agent/1020-1")
    s3 = git(work, "rev-parse", "HEAD")
    s4 = commit(work, "s4")
    git(work, "push", "-q", "origin", "staging")
    # A commit that was on staging until a force push, so no ancestor of s4.
    git(work, "checkout", "-q", "-b", "gone", s2)
    gone = commit(work, "gone")
    git(work, "checkout", "-q", "staging")
    git(work, "branch", "-q", "-f", "agent/1020-2", fork)
    git(work, "checkout", "-q", "agent/1020-2")
    agent_tip = commit(work, "e")

    rc, out, env = base_sha(work, t / "env1", token=False, repo=False)
    check("an agent branch gets HECATON_BASE_SHA, the merge base with origin/staging",
          rc == 0 and env == f"HECATON_BASE_SHA={fork}\n", f"exit {rc}, wrote {env!r}: {out}")
    check("an agent branch past staging never calls gh", base_sha.gh_calls == [], f"gh got {base_sha.gh_calls}")
    check(f"the fetch of staging runs under timeout with a {FETCH_LIMIT_S} s limit, once when it works (#1330)",
          base_sha.timeouts == [FETCH_CALL] and len(base_sha.fetches) == 1 and base_sha.sleeps == [],
          f"timeout got {base_sha.timeouts}, {len(base_sha.fetches)} fetch(es), slept {base_sha.sleeps}")

    # #1330: a fetch that fails or gets no answer is tried again after each of these waits, five tries in all.
    waits = ["5", "15", "30", "60"]
    for fails in (1, 2, 4):
        rc, out, env = base_sha(work, t / f"env-fetch-{fails}", token=False, repo=False, fetch_fails=fails)
        check(f"a fetch of staging that failed {fails} time(s) gets the merge base on try {fails + 1} (#1330)",
              rc == 0 and env == f"HECATON_BASE_SHA={fork}\n" and len(base_sha.fetches) == fails + 1
              and base_sha.sleeps == waits[:fails] and "git fetch try 1 of 5 got exit 128" in out
              and FETCH_NO_ANSWER in out,
              f"exit {rc}, wrote {env!r}, {len(base_sha.fetches)} fetch(es), slept {base_sha.sleeps}: {out}")
    rc, out, env = base_sha(work, t / "env-fetch-all", token=False, repo=False, fetch_fails=5)
    check("a fetch of staging that fails on all five tries exits 1, naming the tries (#1330)",
          rc == 1 and env == "" and len(base_sha.fetches) == 5 and base_sha.sleeps == waits
          and "could not fetch staging from origin on 5 tries" in out,
          f"exit {rc}, wrote {env!r}, {len(base_sha.fetches)} fetch(es), slept {base_sha.sleeps}: {out}")
    # The fetch that hung on staging 3da68e84, here killed by the real timeout at HANG_LIMIT_S.
    rc, out, env = base_sha(work, t / "env-fetch-hang", token=False, repo=False, fetch_fails=1, fetch_hangs=True)
    check("a fetch of staging that hangs is cut off at the limit and tried again (#1330)",
          rc == 0 and env == f"HECATON_BASE_SHA={fork}\n" and len(base_sha.fetches) == 2
          and base_sha.timeouts == [FETCH_CALL] * 2 and base_sha.sleeps == waits[:1]
          and f"git fetch try 1 of 5 got no answer in {FETCH_LIMIT_S} s" in out,
          f"exit {rc}, wrote {env!r}, timeout got {base_sha.timeouts}, slept {base_sha.sleeps}: {out}")

    git(work, "checkout", "-q", "--detach", s4)
    # The answer as the API might give it, newest first: s4 still running, s3 failed, s2 cancelled, and green runs
    # that must never be the base (another branch, another event, a second parent, a force-pushed commit), then s1.
    noise = [run(s4, None), run(s3, "failure"), run(s3, "success", branch="agent/1020-1"),
             run(s2, "cancelled"), run(s2, "success", event="workflow_dispatch"), run(gone), run(second),
             run(agent_tip, branch="agent/1020-2")]
    rc, out, env = base_sha(work, t / "env2", {"workflow_runs": noise + [run(fork)]})
    check("a staging tip after a cancelled run gets the newest green first-parent ancestor, s1 (#1195)",
          rc == 0 and env == f"HECATON_BASE_SHA={fork}\n", f"exit {rc}, wrote {env!r}: {out}")
    scope = git(work, "diff", "--name-only", env.strip().partition("=")[2] or s4, s4).split()
    check("the cancelled run's change is in the next run's scope (#1195)", "cancelled-push.txt" in scope,
          f"the diff from {env.strip()!r} to the tip names {scope}; the push before the tip would give "
          f"{git(work, 'diff', '--name-only', s3, s4).split()}")
    calls = base_sha.gh_calls
    check("the base step reads this workflow's green staging push runs from the Actions API",
          len(calls) == 1 and calls[0].startswith("api repos/owner/repo/actions/workflows/verify-suites.yml/runs?")
          and all(q in calls[0] for q in ("branch=staging", "event=push", "status=success")), f"gh got {calls}")

    rc, out, env = base_sha(work, t / "env3", {"workflow_runs": [run(s4)] + noise + [run(fork)]})
    check("a green run on the commit itself (a rerun) is not its own base",
          rc == 0 and env == f"HECATON_BASE_SHA={fork}\n", f"exit {rc}, wrote {env!r}: {out}")
    rc, out, env = base_sha(work, t / "env4", {"workflow_runs": [run(s3)] + noise + [run(fork)]})
    check("the newest green first-parent ancestor wins over an older one",
          rc == 0 and env == f"HECATON_BASE_SHA={s3}\n", f"exit {rc}, wrote {env!r}: {out}")
    for label, runs in (("no green first-parent ancestor", {"workflow_runs": noise}),
                        ("no runs at all", {"workflow_runs": []})):
        rc, out, env = base_sha(work, t / f"env-{label[:5]}", runs)
        check(f"a staging tip with {label} leaves HECATON_BASE_SHA unset, so the suites run whole",
              rc == 0 and env == "" and "left unset" in out, f"exit {rc}, wrote {env!r}: {out}")
    for label, kw, word in (("no GH_TOKEN", {"token": False}, "GH_TOKEN"),
                            ("no GITHUB_REPOSITORY", {"repo": False}, "GITHUB_REPOSITORY"),
                            ("a gh api call that fails on every try", {"gh_fails": 99}, "on 5 tries"),
                            ("an API answer with no workflow_runs", {"runs": "{}"}, "workflow_runs")):
        rc, out, env = base_sha(work, t / f"env-{word[:6]}", **{"runs": {"workflow_runs": [run(fork)]}, **kw})
        check(f"a staging tip with {label} fails, naming it", rc == 1 and env == "" and word in out,
              f"exit {rc}, wrote {env!r}: {out}")

    # #1325: a read that gets no answer, a 429 or a 5xx is tried again after each of the same waits, five tries in all;
    # any other status GitHub answered fails at once.
    green = {"workflow_runs": [run(s3)] + noise + [run(fork)]}
    for case, (label, err) in enumerate((("no answer (a TLS handshake timeout)", NO_ANSWER),
                                         ("an HTTP 502", http_error(502)), ("an HTTP 429", http_error(429)))):
        for fails in (1, 2, 4):
            rc, out, env = base_sha(work, t / f"env-retry-{case}-{fails}", green, gh_fails=fails, gh_err=err)
            check(f"a staging tip whose first {fails} gh api read(s) got {label} gets its base on try {fails + 1}",
                  rc == 0 and env == f"HECATON_BASE_SHA={s3}\n" and len(base_sha.gh_calls) == fails + 1
                  and base_sha.sleeps == waits[:fails] and "try 1 of 5 got" in out,
                  f"exit {rc}, wrote {env!r}, gh got {len(base_sha.gh_calls)} call(s), slept {base_sha.sleeps}: {out}")
        rc, out, env = base_sha(work, t / f"env-retry-{case}-all", green, gh_fails=5, gh_err=err)
        check(f"a staging tip whose five gh api reads all got {label} fails after the fifth, naming the tries",
              rc == 1 and env == "" and len(base_sha.gh_calls) == 5 and base_sha.sleeps == waits
              and "on 5 tries" in out and err in out,
              f"exit {rc}, wrote {env!r}, gh got {len(base_sha.gh_calls)} call(s), slept {base_sha.sleeps}: {out}")
    for status in (401, 403, 404, 422):
        rc, out, env = base_sha(work, t / f"env-http-{status}", green, gh_fails=1, gh_err=http_error(status))
        check(f"a gh api read GitHub answered with HTTP {status} fails at once, with no second try",
              rc == 1 and env == "" and len(base_sha.gh_calls) == 1 and base_sha.sleeps == []
              and f"HTTP {status}, which is not retried" in out,
              f"exit {rc}, wrote {env!r}, gh got {len(base_sha.gh_calls)} call(s), slept {base_sha.sleeps}: {out}")

    git(work, "checkout", "-q", "agent/1020-2")
    rc, out, _ = base_sha(work, None)
    check("no GITHUB_ENV fails, naming it", rc == 1 and "GITHUB_ENV" in out, f"exit {rc}: {out}")

    git(work, "checkout", "-q", "--orphan", "agent/unrelated")
    commit(work, "f")
    rc, out, env = base_sha(work, t / "env5")
    check("a history with nothing in common with staging fails", rc == 1 and env == "", f"exit {rc}: {out}")

    git(work, "remote", "set-url", "origin", str(t / "missing.git"))
    git(work, "checkout", "-q", "agent/1020-2")
    rc, out, env = base_sha(work, t / "env6")
    check("an origin that cannot be fetched fails after five tries", rc == 1 and env == ""
          and len(base_sha.fetches) == 5 and "could not fetch staging from origin on 5 tries" in out,
          f"exit {rc}, {len(base_sha.fetches)} fetch(es): {out}")

    # A staging that is one root commit has no ancestor to scope by.
    origin2, work2 = t / "origin2.git", t / "work2"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "staging", str(origin2)], check=True)
    subprocess.run(["git", "init", "-q", "-b", "staging", str(work2)], check=True)
    git(work2, "remote", "add", "origin", str(origin2))
    root = commit(work2, "root")
    git(work2, "push", "-q", "origin", "staging")
    rc, out, env = base_sha(work2, t / "env7", {"workflow_runs": [run(root)]})
    check("a staging that is one root commit leaves HECATON_BASE_SHA unset",
          rc == 0 and env == "" and "left unset" in out, f"exit {rc}, wrote {env!r}: {out}")

if failures:
    print(f"\n{len(failures)} check(s) failed", file=sys.stderr)
    sys.exit(1)
print("\nverify-suites.yml and ci-base-sha.sh hold")
