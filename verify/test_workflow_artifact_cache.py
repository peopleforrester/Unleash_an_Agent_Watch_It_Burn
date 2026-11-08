# ABOUTME: Holds every workflow job that fetches a pinned artifact to the runner's artifact cache outside the workspace
# ABOUTME: (#1123): verify/ci-artifact-cache.sh first, no curl, no spared in-workspace cache. Runs the script. Offline.
"""Offline.

#1115 asks that a pinned artifact reach the network once per host, and #1123 is its part for the CI runners, tanjiro-wsl2
and megumi-wsl2. Every workflow job under .github/workflows/ that fetches a pinned artifact runs
`bash verify/ci-artifact-cache.sh` before its first fetch. That script sets WIB_ARTIFACT_CACHE to
$RUNNER_TOOL_CACHE/wib-artifacts, the runner's own directory beside its job workspaces, and refuses a path inside
$GITHUB_WORKSPACE or a checkout. Before #1123 the e2e job kept its downloads in the workspace's verify/.tools and its
clean step spared that directory; now the clean step removes everything git does not track.

What this holds, on the parsed workflows:
  - every job of every workflow is in JOBS, as fetching a pinned artifact or not, and a job listed as not fetching
    that runs a fetch fails, so a new job cannot pass by being left out;
  - a fetching job runs the cache step, bare, once, after checkout and before its first fetch;
  - nothing sets WIB_ARTIFACT_CACHE or HECATON_TOOLS_CACHE any other way, and no cache variable names the workspace;
  - no curl or wget reaches anything but loopback (a pinned file comes through verify/artifact-cache.sh), and every
    archive is unpacked under $RUNNER_TEMP, not the workspace;
  - no `git clean` spares a path, and a self-hosted job (whose workspace persists) cleans it after checkout.
The checker runs first on copies of the workflows, each broken one way, so a check that stopped matching reads as
that and not as a pass.

Then the script itself runs in throwaway runner layouts: Tanjiro's (/srv/gha-agent/<repo>/_work, read from a green
run's log on 2026-11-08), a megumi-like one under a home directory, and GitHub-hosted's /opt/hostedtoolcache. In
each it writes WIB_ARTIFACT_CACHE=<tool cache>/wib-artifacts to GITHUB_ENV and creates it. A job in a second workspace
on the same runner then gets the artifact the first job fetched with no fetch of its own, after the clean step,
read from the workflow, has emptied the first workspace. Each way the path can go wrong fails, names it, and writes
nothing to GITHUB_ENV.
"""
from __future__ import annotations

import copy
import hashlib
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "verify"))
import artifact_cache  # noqa: E402
WORKFLOWS = REPO / ".github" / "workflows"
SCRIPT = REPO / "verify" / "ci-artifact-cache.sh"
CACHE_CLI = REPO / "verify" / "artifact-cache.sh"
CACHE_STEP = "bash verify/ci-artifact-cache.sh"

# Every job, and whether it fetches a pinned artifact (#1116's sense: a tool, provider, chart, package or image with a
# version, digest or checksum). A job not here fails, so a new one is classed when it is added.
JOBS = {
    ("build-web-terminal.yml", "build"): False,       # docker builds images/web-terminal; its base images are #1122's
    ("iam-policy.yml", "check"): True,                # PyYAML, e2e-tools.lock, the Terraform provider mirror
    ("keep-sample-app-tag.yml", "tag"): False,        # puts a pinned manifest on a ghcr.io tag; it fetches nothing to use
    ("plan-policy.yml", "check"): True,               # PyYAML, tools.yaml's binaries, the Terraform provider mirror
    ("push-jokers.yml", "jokers"): True,              # crane from e2e-tools.lock
    ("verify-suites.yml", "offline"): True,           # PyYAML
    ("verify-suites.yml", "e2e-tools"): True,         # PyYAML, e2e-tools.lock, charts, providers, packages
    ("weaver-registry-check.yml", "check"): True,     # weaver, pinned by WEAVER_SHA256
}
# A step that fetches a pinned artifact, or runs a suite or script that does.
FETCH = re.compile(r"fetch-e2e-tools\.sh|artifact-cache\.sh|artifact_cache|package_cache\.py|tf_plugin_cache\.py|"
                   r"install-tools\.py|run-e2e-tools\.sh|run-tests\.sh|e2e-tools\.lock|\bcurl\b|\bwget\b|"
                   r"pip3?[ ]install|uv[ ]pip|helm (pull|repo)|terraform init")
CACHE_VARS = ("WIB_ARTIFACT_CACHE", "HECATON_TOOLS_CACHE", "TF_PLUGIN_CACHE_DIR", "PLAYWRIGHT_BROWSERS_PATH",
              "XDG_CACHE_HOME")
LOOPBACK = re.compile(r"https?://(127\.0\.0\.1|localhost)[:/]")

failures: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(("PASS " if ok else "FAIL ") + label + (f"\n     {detail}" if detail and not ok else ""))
    if not ok:
        failures.append(label)


def code_lines(run: str) -> list[str]:
    """A run script's lines without shell comments, so a comment naming curl is not a fetch."""
    return [ln for ln in (l.strip() for l in run.splitlines()) if ln and not ln.startswith("#")]


def env_problems(where: str, env: object) -> list[str]:
    found = []
    for key, value in (env or {}).items() if isinstance(env, dict) else []:
        if key in ("WIB_ARTIFACT_CACHE", "HECATON_TOOLS_CACHE"):
            found.append(f"{where}: env sets {key}; only {CACHE_STEP} names the artifact cache")
        elif key in CACHE_VARS and re.search(r"github\.workspace|GITHUB_WORKSPACE", str(value)):
            found.append(f"{where}: env {key} is {value!r}, inside the workspace")
    return found


def problems(docs: dict[str, dict]) -> list[str]:
    """Every way the workflows break #1123's rules, one line each; empty when they hold."""
    found: list[str] = []
    seen = set()
    for wf, doc in sorted(docs.items()):
        found += env_problems(wf, doc.get("env"))
        for name, job in (doc.get("jobs") or {}).items():
            where = f"{wf} {name}"
            seen.add((wf, name))
            if not isinstance(job, dict) or "steps" not in job:
                found.append(f"{where}: not a job with its own steps")
                continue
            found += env_problems(where, job.get("env"))
            steps = job.get("steps") or []
            runs = [str(s.get("run", "")) for s in steps]
            for i, s in enumerate(steps):
                found += env_problems(f"{where} step {i + 1}", s.get("env"))
            fetching = [i for i, r in enumerate(runs) if any(FETCH.search(ln) for ln in code_lines(r))]
            if (wf, name) not in JOBS:
                found.append(f"{where}: not in JOBS; class it as fetching a pinned artifact or not")
            elif not JOBS[(wf, name)] and fetching:
                found.append(f"{where}: is listed as fetching nothing pinned, but step {fetching[0] + 1} runs "
                             f"{code_lines(runs[fetching[0]])[0]!r}")
            checkout = next((i for i, s in enumerate(steps) if str(s.get("uses", "")).startswith("actions/checkout@")),
                            None)
            cache = [i for i, r in enumerate(runs) if r.strip() == CACHE_STEP]
            if JOBS.get((wf, name)):
                first = next((i for i in fetching if i not in cache), None)
                if len(cache) != 1:
                    found.append(f"{where}: runs `{CACHE_STEP}` {len(cache)} times, not once")
                else:
                    c = cache[0]
                    extra = sorted(set(steps[c]) - {"name", "run"})
                    if extra:
                        found.append(f"{where}: the cache step has {extra}, which can skip it or change its env")
                    if checkout is None or c < checkout:
                        found.append(f"{where}: the cache step runs before checkout, where the script is not there")
                    if first is not None and c > first:
                        found.append(f"{where}: the cache step runs after step {first + 1}, its first fetch")
            for i, r in enumerate(runs):
                at = f"{where} step {i + 1}"
                for ln in code_lines(r):
                    if re.search(r"\b(WIB_ARTIFACT_CACHE|HECATON_TOOLS_CACHE)=", ln):
                        found.append(f"{at}: sets the artifact cache itself ({ln}); only {CACHE_STEP} does")
                    if any(v in ln for v in CACHE_VARS) and re.search(r"GITHUB_WORKSPACE|github\.workspace", ln):
                        found.append(f"{at}: points a cache inside the workspace: {ln}")
                    if re.search(r"\b(curl|wget)\b", ln) and not LOOPBACK.search(ln):
                        found.append(f"{at}: fetches with curl or wget ({ln}); a pinned file comes through "
                                     "verify/artifact-cache.sh get")
                    if re.search(r"\btar\s+-?\w*x", ln) and not re.search(r'-C\s+"?\$\{?RUNNER_TEMP\}?/', ln):
                        found.append(f"{at}: unpacks an archive outside $RUNNER_TEMP, into the workspace: {ln}")
                    if re.search(r"\bgit clean\b", ln) and re.search(r"\s(-e|--exclude)\b|\s-\w*e", ln):
                        found.append(f"{at}: `{ln}` spares a path in the workspace")
                    if "verify/.tools/dl" in ln:
                        found.append(f"{at}: names verify/.tools/dl, the per-workspace download cache #1118 removed")
            labels = job.get("runs-on")
            if "self-hosted" in (labels if isinstance(labels, list) else [labels]):
                clean = next((i for i, r in enumerate(runs) if "git clean -ffdx" in code_lines(r)), None)
                if clean is None or checkout is None or clean < checkout:
                    found.append(f"{where}: no step after checkout runs a bare `git clean -ffdx`, and a self-hosted "
                                 "runner keeps the workspace from the job before")
    for wf, name in sorted(set(JOBS) - seen):
        found.append(f"JOBS lists {wf} {name}, which no workflow has")
    return found


docs = {p.name: yaml.safe_load(p.read_text(encoding="utf-8")) for p in sorted(WORKFLOWS.glob("*.yml"))}
check("the workflows are read", len(docs) >= 7 and all(isinstance(d, dict) for d in docs.values()), str(list(docs)))


def broken(edit) -> dict[str, dict]:
    d = copy.deepcopy(docs)
    edit(d)
    return d


def steps_of(d: dict, wf: str, job: str) -> list[dict]:
    return d[wf]["jobs"][job]["steps"]


def without_cache(d: dict, wf: str, job: str) -> None:
    d[wf]["jobs"][job]["steps"] = [s for s in steps_of(d, wf, job) if str(s.get("run", "")).strip() != CACHE_STEP]


def move_cache_last(d: dict, wf: str, job: str) -> None:
    s = steps_of(d, wf, job)
    d[wf]["jobs"][job]["steps"] = [x for x in s if x.get("run", "").strip() != CACHE_STEP] + \
        [x for x in s if x.get("run", "").strip() == CACHE_STEP]


def edit_run(d: dict, wf: str, job: str, old: str, new: str) -> None:
    hits = [s for s in steps_of(d, wf, job) if old in str(s.get("run", ""))]
    if not hits:
        print(f"FAIL: the anchor {old!r} is not in {wf} {job}; the test's broken copy cannot be built", file=sys.stderr)
        sys.exit(1)
    for s in hits:
        s["run"] = s["run"].replace(old, new)


cases = {
    "the offline job without the cache step": lambda d: without_cache(d, "verify-suites.yml", "offline"),
    "the e2e job's cache step after its suite": lambda d: move_cache_last(d, "verify-suites.yml", "e2e-tools"),
    "plan-policy without the cache step": lambda d: without_cache(d, "plan-policy.yml", "check"),
    "push-jokers without the cache step": lambda d: without_cache(d, "push-jokers.yml", "jokers"),
    "weaver without the cache step": lambda d: without_cache(d, "weaver-registry-check.yml", "check"),
    "the cache step twice": lambda d: steps_of(d, "iam-policy.yml", "check").append({"run": CACHE_STEP}),
    "the cache step behind an if": lambda d: [s.update({"if": "false"}) for s in steps_of(d, "iam-policy.yml", "check")
                                              if s.get("run", "").strip() == CACHE_STEP],
    "the cache set in the workspace by hand": lambda d: edit_run(
        d, "iam-policy.yml", "check", "python verify/package_cache.py",
        'echo "WIB_ARTIFACT_CACHE=$GITHUB_WORKSPACE/.cache" >> "$GITHUB_ENV"\npython verify/package_cache.py'),
    "the cache under the runner's temp, set by hand": lambda d: edit_run(
        d, "plan-policy.yml", "check", "python verify/package_cache.py",
        'WIB_ARTIFACT_CACHE="$RUNNER_TEMP/wib-artifacts" python verify/package_cache.py'),
    "a job env naming the cache": lambda d: d["plan-policy.yml"]["jobs"]["check"].update(
        {"env": {"WIB_ARTIFACT_CACHE": "/srv/cache"}}),
    "a workflow env with HECATON_TOOLS_CACHE": lambda d: d["verify-suites.yml"].update(
        {"env": {"HECATON_TOOLS_CACHE": "/srv/cache"}}),
    "a step env with a plugin cache in the workspace": lambda d: steps_of(d, "verify-suites.yml", "e2e-tools")[-1]
        .update({"env": {"TF_PLUGIN_CACHE_DIR": "${{ github.workspace }}/.tf"}}),
    "the clean step sparing verify/.tools": lambda d: edit_run(
        d, "verify-suites.yml", "offline", "git clean -ffdx\n", "git clean -ffdx -e verify/.tools/\n"),
    "the clean step sparing a cache with --exclude": lambda d: edit_run(
        d, "verify-suites.yml", "e2e-tools", "git clean -ffdx\n", "git clean -ffdx --exclude=.cache\n"),
    "a self-hosted job with no clean step": lambda d: d["verify-suites.yml"]["jobs"]["e2e-tools"].update(
        {"steps": [s for s in steps_of(d, "verify-suites.yml", "e2e-tools")
                   if "git clean -ffdx" not in str(s.get("run", ""))]}),
    "crane fetched with curl": lambda d: edit_run(
        d, "push-jokers.yml", "jokers", 'archive="$(bash verify/artifact-cache.sh get "${sha}" "${url}")"',
        'curl -fsSL -o "${RUNNER_TEMP}/crane.tar.gz" "${url}"; archive="${RUNNER_TEMP}/crane.tar.gz"'),
    "weaver fetched with wget": lambda d: edit_run(
        d, "weaver-registry-check.yml", "check", 'archive="$(bash', 'wget -q "$url"\n          archive="$(bash'),
    "weaver unpacked in the workspace": lambda d: edit_run(
        d, "weaver-registry-check.yml", "check", 'tar -xJf "${archive}" -C "${RUNNER_TEMP}/weaver"',
        'tar -xJf "${archive}"'),
    "the per-workspace download cache named": lambda d: edit_run(
        d, "iam-policy.yml", "check", "bash verify/fetch-e2e-tools.sh",
        "mkdir -p verify/.tools/dl\n          bash verify/fetch-e2e-tools.sh"),
    "a fetching job not in JOBS": lambda d: d["push-jokers.yml"]["jobs"].update(
        {"more": copy.deepcopy(d["push-jokers.yml"]["jobs"]["jokers"])}),
    "a job listed as not fetching that fetches": lambda d: steps_of(d, "build-web-terminal.yml", "build").append(
        {"run": "bash verify/fetch-e2e-tools.sh"}),
    "a listed job removed": lambda d: d["keep-sample-app-tag.yml"]["jobs"].pop("tag"),
}
for what, edit in cases.items():
    got = problems(broken(edit))
    check(f"the checker fails workflows with {what}", bool(got))
check("the checker passes a comment that names curl",
      not problems(broken(lambda d: edit_run(d, "iam-policy.yml", "check", "bash verify/fetch-e2e-tools.sh",
                                             "# curl is not used here\n          bash verify/fetch-e2e-tools.sh"))))

got = problems(docs)
check("every workflow job that fetches a pinned artifact uses the runner's cache outside the workspace (#1123)",
      not got, "\n     ".join(got))


# verify/ci-artifact-cache.sh, in throwaway runner layouts.
def git(cwd: Path, *args: str) -> None:
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@t", "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1"}
    subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True, env=env)


def checkout(path: Path) -> Path:
    """A job workspace: a git checkout whose verify/.tools is ignored, as this repo's is."""
    path.mkdir(parents=True)
    git(path, "init", "-q", "-b", "staging")
    (path / ".gitignore").write_text("verify/.tools/\n")
    git(path, "add", ".gitignore")
    git(path, "commit", "-q", "-m", "init")
    return path


def job_env(tmp: Path, tool: Path | None, workspace: Path | None, env_file: Path | None, **extra: str) -> dict:
    env = {k: v for k, v in os.environ.items()
           if k not in ("GITHUB_ENV", "GITHUB_WORKSPACE", "RUNNER_TOOL_CACHE", "WIB_ARTIFACT_CACHE",
                        "HECATON_TOOLS_CACHE", "XDG_CACHE_HOME", "ARTIFACT_FETCH_LOG")}
    env.update({"HOME": str(tmp / "home"), "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1"})
    for key, value in (("RUNNER_TOOL_CACHE", tool), ("GITHUB_WORKSPACE", workspace), ("GITHUB_ENV", env_file)):
        if value is not None:
            env[key] = str(value)
    env.update(extra)
    return env


def cache_step(env: dict, cwd: Path) -> tuple[int, str]:
    r = subprocess.run(["bash", str(SCRIPT)], cwd=cwd, env=env, capture_output=True, text=True, timeout=60)
    return r.returncode, r.stdout + r.stderr


def read_env(env_file: Path) -> str:
    return env_file.read_text() if env_file.exists() else ""


clean_run = next(s["run"] for s in docs["verify-suites.yml"]["jobs"]["e2e-tools"]["steps"]
                 if "git clean -ffdx" in str(s.get("run", "")))
payload = b"a pinned artifact, as e2e-tools.lock pins one\n"
sha = hashlib.sha256(payload).hexdigest()

# The runner layouts sit outside every worktree, as a runner's do; hecaton points TMPDIR inside the run's worktree.
try:
    scratch = artifact_cache.scratch_dir("workflow-artifact-cache-test-")
except artifact_cache.ArtifactCacheError as e:
    print(f"FAIL: {e}", file=sys.stderr)
    sys.exit(1)
with tempfile.TemporaryDirectory(dir=scratch) as tmp_name:
    tmp = Path(tmp_name)
    (tmp / "home").mkdir()
    source = tmp / "upstream" / "tool.tar.gz"
    source.parent.mkdir()
    source.write_bytes(payload)
    url = source.as_uri()

    layouts = {
        "tanjiro": tmp / "srv/gha-agent/Unleash_an_Agent_Watch_It_Burn/_work",
        "megumi": tmp / "home/michael/actions-runner/_work",
        "GitHub-hosted": None,
    }
    for runner, work in layouts.items():
        if work is None:
            tool, ws_a, ws_b = tmp / "opt/hostedtoolcache", tmp / "home/runner/work/R/R", tmp / "home/runner/work/S/S"
        else:
            tool, ws_a, ws_b = work / "_tool", work / "R/R", work / "S/S"
        tool.mkdir(parents=True)
        checkout(ws_a)
        checkout(ws_b)
        want = tool.resolve() / "wib-artifacts"

        env_a = tmp / f"{runner}-env-a"
        rc, out = cache_step(job_env(tmp, tool, ws_a, env_a), ws_a)
        check(f"{runner}: the cache step writes WIB_ARTIFACT_CACHE=<tool cache>/wib-artifacts and creates it",
              rc == 0 and read_env(env_a) == f"WIB_ARTIFACT_CACHE={want}\n" and want.is_dir(),
              f"exit {rc}, wrote {read_env(env_a)!r}: {out}")
        check(f"{runner}: the cache is outside the job workspace", ws_a.resolve() not in want.parents)

        # The first job on the runner fetches the artifact into the cache, from its workspace's verify/.tools run.
        cache_env = {"WIB_ARTIFACT_CACHE": str(want)}
        r = subprocess.run(["bash", str(CACHE_CLI), "get", sha, url], cwd=ws_a, capture_output=True, text=True,
                           timeout=60, env=job_env(tmp, tool, ws_a, None, **cache_env))
        got = Path(r.stdout.strip()) if r.returncode == 0 else None
        check(f"{runner}: a pinned fetch lands in the runner's cache, by its SHA-256",
              got == want / "sha256" / sha and got.read_bytes() == payload, f"exit {r.returncode}: {r.stderr}")
        log = want / "fetch.log"
        fetched = log.read_text() if log.exists() else ""

        # The clean step, as the workflow has it, empties the workspace of verify/.tools and leaves the cache.
        (ws_a / "verify/.tools/dl").mkdir(parents=True)
        (ws_a / "verify/.tools/dl/old.zip").write_bytes(b"a per-workspace copy")
        (ws_a / "verify/.tools/bin").mkdir()
        (ws_a / "verify/.tools/bin/tool").write_bytes(b"#!/bin/sh\n")
        c = subprocess.run(["bash", "-c", clean_run], cwd=ws_a, capture_output=True, text=True, timeout=60,
                           env=job_env(tmp, tool, ws_a, None))
        check(f"{runner}: the workflow's clean step removes verify/.tools, downloads and binaries alike",
              c.returncode == 0 and not (ws_a / "verify").exists(), f"exit {c.returncode}: {c.stderr}")
        check(f"{runner}: the runner's cache outlives the clean step", (want / "sha256" / sha).is_file())

        # A later job in another workspace on the same runner: the same path, and the artifact with no fetch.
        env_b = tmp / f"{runner}-env-b"
        rc, out = cache_step(job_env(tmp, tool, ws_b, env_b), ws_b)
        check(f"{runner}: a job in another workspace gets the same cache path",
              rc == 0 and read_env(env_b) == read_env(env_a), f"exit {rc}, wrote {read_env(env_b)!r}: {out}")
        source.rename(source.with_suffix(".gone"))
        r = subprocess.run(["bash", str(CACHE_CLI), "get", sha, url], cwd=ws_b, capture_output=True, text=True,
                           timeout=60, env=job_env(tmp, tool, ws_b, None, **cache_env))
        source.with_suffix(".gone").rename(source)
        check(f"{runner}: that job gets the artifact from the cache, with the source gone and no fetch logged",
              r.returncode == 0 and Path(r.stdout.strip()) == want / "sha256" / sha
              and (log.read_text() if log.exists() else "") == fetched and fetched.count("\n") == 1,
              f"exit {r.returncode}: {r.stderr}; fetch log {fetched!r}")

    # Each way the path can go wrong: exit 1, named, and nothing written to GITHUB_ENV.
    work = tmp / "bad/_work"
    ws = checkout(work / "R/R")
    tool = work / "_tool"
    tool.mkdir(parents=True)
    other = checkout(tmp / "bad/another-checkout")
    (work / "_link").symlink_to(ws / "cache", target_is_directory=True)  # dangling: the script must not create it
    bad = {
        "no RUNNER_TOOL_CACHE": (job_env(tmp, None, ws, None), "RUNNER_TOOL_CACHE is not set"),
        "an empty RUNNER_TOOL_CACHE": (job_env(tmp, None, ws, None, RUNNER_TOOL_CACHE=""), "RUNNER_TOOL_CACHE is not set"),
        "a relative RUNNER_TOOL_CACHE": (job_env(tmp, None, ws, None, RUNNER_TOOL_CACHE="_work/_tool"), "not an absolute"),
        "no GITHUB_ENV": (job_env(tmp, tool, ws, None), "GITHUB_ENV is not set"),
        "no GITHUB_WORKSPACE": (job_env(tmp, tool, None, None), "GITHUB_WORKSPACE is not set"),
        "a tool cache inside the workspace": (job_env(tmp, ws / "_tool", ws, None), "inside the job workspace"),
        "a tool cache that links into the workspace": (job_env(tmp, work / "_link", ws, None), "inside the job workspace"),
        "a tool cache inside another checkout": (job_env(tmp, other / "_tool", ws, None), "refuses"),
        "a HECATON_TOOLS_CACHE that takes precedence": (job_env(tmp, tool, ws, None, HECATON_TOOLS_CACHE=str(tmp / "h")),
                                                        "HECATON_TOOLS_CACHE"),
    }
    for i, (what, (env, why)) in enumerate(bad.items()):
        env_file = tmp / f"bad-env-{i}"
        if what != "no GITHUB_ENV":
            env["GITHUB_ENV"] = str(env_file)
        rc, out = cache_step(env, ws)
        check(f"the cache step fails on {what}, naming it, and writes nothing",
              rc == 1 and "CI ARTIFACT CACHE FAILED" in out and why in out and read_env(env_file) == "",
              f"exit {rc}, wrote {read_env(env_file)!r}: {out}")
    check("a refused path inside the workspace is never created",
          not (ws / "_tool").exists() and not (ws / "cache").exists(), str(sorted(p.name for p in ws.iterdir())))

scratch.rmdir()

if failures:
    print(f"\n{len(failures)} check(s) failed", file=sys.stderr)
    sys.exit(1)
print("\nevery pinned fetch in .github/workflows reads the runner's artifact cache, outside the workspace")
