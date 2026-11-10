# ABOUTME: Offline check that no script or test names the system's temp directories (#1261): each uses TMPDIR, else the
# ABOUTME: checkout's ignored tmp/, and removes what it made on exit. The documented exceptions are listed below, each with why.
"""On netcup the system temp directory is a tmpfs, so whatever a run or a test leaves there is RAM. On 2026-11-09 two
`wib-tf-plugins-*` directories of about 840 MB each sat there from the IAM render tests, which made a new Terraform
plugin directory per process with tempfile and never removed it, and dispatched runs had left more in the dispatcher's
private one. Michael: no run and no test works in /tmp; everything is cleaned up after it runs unless it is a
deliberate, managed cache.

What this holds, over every tracked script and test in the repo (shell, Python, JavaScript, TypeScript, Dockerfiles and
the workflows; not the submodules, which are their own repos, nor the vendored Yarn release):

  1. No line names /tmp, /var/tmp or /dev/shm as a path: not a literal file there, not `mktemp -p /tmp`, not a
     `/tmp/...XXXX` template, not `${TMPDIR:-/tmp}`. A path inside a pod or an image build is not the host's, and each
     such line is an exception below, named by file and by the words on the line, with the reason. A new line that
     names one fails here, so it is either changed to TMPDIR or added below with its reason.
  2. Every shell script that calls a bare `mktemp` (no -p, no template with a directory in it) sets
     TMPDIR="${TMPDIR:-<checkout>/tmp}" first, so with no TMPDIR it still writes under the checkout's ignored tmp/.
  3. Every shell script that calls mktemp removes what it made on an EXIT trap, which runs on success and on failure.
  4. Every Python file has an rmtree for each tempfile.mkdtemp() it calls (here or through atexit), and every
     mkstemp() or NamedTemporaryFile(delete=False) is unlinked or renamed into place.
  5. Both runners export the TMPDIR fallback, so every test they start inherits it.
  6. artifact_cache.scratch_dir(), the outside-a-worktree scratch the cache tests use, tries TMPDIR and then the
     user's cache directory, never a system temp directory; before #1261 it fell through to /tmp whenever hecaton's
     TMPDIR sat inside the worktree, which is every run.
"""
from __future__ import annotations

import os
import pathlib
import re
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(HERE))
import artifact_cache  # noqa: E402

# It runs fleet.sh, so the cloud tools are stubs and the credentials cleared, even run by hand (#859, no_cloud.py).
import no_cloud  # noqa: E402
no_cloud.setup()

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail and not ok else ""))
    if not ok:
        failures.append(name)


# A system temp directory named as a path: at the start of a word, after a quote, `=`, `(`, `:`, `,`, `[`, `@`, a
# backtick or the `-` of ${VAR:-...}, and not followed by more of a name (/tmpfoo). ${REPO}/tmp, <worktree>/tmp and
# $HOME/tmp are under another directory and do not match.
SYSTEM_TEMP = re.compile(r"(?:^|[\s\"'=(:,\[@`-])(/tmp|/var/tmp|/dev/shm)(?![\w.-])")

SCRIPT_SUFFIXES = {".sh", ".bash", ".py", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".go"}
SELF = "verify/test_no_system_temp_paths.py"

# Lines that name a system temp directory on purpose: (file, or "*" for any file; words on the line; why).
EXCEPTIONS: list[tuple[str, str, str]] = [
    ("*", "/tmp/burrito-data",
     "the workshop-mcp pod's seeded data directory, baked by images/workshop-mcp/Dockerfile; the C2 and C3 beats read "
     "it inside the pod, so the path is the container's, not the host's"),
    ("gitops/ai-layer/workshop-mcp-server.py", "/tmp is writable",
     "the server runs in the workshop-mcp pod, whose /tmp is the pod's own and the one writable path there"),
    ("gitops/ai-layer/workshop-mcp-server.py", "/tmp/body.json",
     "the hint run_shell gives the agent, for a file in the pod"),
    ("verify/test_turn_guard.py", "/tmp/body.json", "reads that hint from workshop-mcp-server.py"),
    ("verify/test_trace_shape_e2e.py", "@/tmp/customers.json", "an agent's curl in a recorded trace, run in the pod"),
    ("verify/test_pantry_shut_record.py", '"ls /tmp"', "an agent's command in a fake audit record, run in the pod"),
    ("verify/test_stage_traces.py", 'command="ls /tmp"', "an agent's command in a fake audit record, run in the pod"),
    ("verify/test_reset_bot.sh", '"mountPath":"/tmp"', "the guard-proxy pod's emptyDir mount in a fake pod spec"),
    ("verify/test_local_inference.py", "/dev/shm", "the vLLM pod's memory-backed mount the manifest must carry"),
    ("verify/test_vllm_fit_probe.py", "/dev/shm", "the vLLM pod's shared memory, named in the probe's docstring"),
    ("verify/test_challenge_fallbacks.py", "/tmp", "the check that the fallback scripts write nothing there"),
    ("verify/test_kubecon_c3_recipe_block.py", "mkdir -p (/tmp/",
     "reads the pod's data directories from images/workshop-mcp/Dockerfile"),
    ("verify/test_kubecon_c3_recipe_block.py", '"/tmp" not in recon',
     "the check that the recon card names none of the pod's folders"),
    ("verify/test_stage_switch_night_before.py", "--kubeconfig /tmp/kubecon.kubeconfig",
     "reads the presenter's command in facilitation/kubecon-na-2026-run-of-show.md, which runs on a presenter's "
     "laptop, not on netcup"),
]


def excepted(rel: str, line: str) -> bool:
    return any(f in ("*", rel) and words in line for f, words, _ in EXCEPTIONS)


def hits(text: str) -> list[str]:
    return [ln.strip() for ln in text.splitlines() if SYSTEM_TEMP.search(ln)]


def is_script(rel: str) -> bool:
    p = pathlib.PurePosixPath(rel)
    if "/.yarn/releases/" in f"/{rel}":
        return False
    return (p.suffix in SCRIPT_SUFFIXES or p.name.startswith("Dockerfile") or p.name == "Makefile"
            or (rel.startswith(".github/workflows/") and p.suffix in (".yml", ".yaml")))


tracked = subprocess.run(["git", "-C", str(REPO), "ls-files", "-z"], capture_output=True, text=True,
                         check=True).stdout.split("\0")
scripts = sorted(rel for rel in tracked if rel and is_script(rel) and (REPO / rel).is_file()
                 and not (REPO / rel).is_symlink())


def read(rel: str) -> str:
    try:
        return (REPO / rel).read_text()
    except UnicodeDecodeError:
        return ""


print("== the pattern finds a system temp path, and only that ==")
for s in ("cp x /tmp/x", 'mktemp -d -p /tmp', 'mktemp /tmp/wib.XXXX', '"${TMPDIR:-/tmp}"', 'dir="/var/tmp"',
          "f = '/dev/shm/x'", "cd /tmp", "(/tmp)", "x=`ls /tmp`"):
    check(f"flags {s!r}", bool(hits(s)))
for s in ('"${REPO}/tmp/x"', "<worktree>/tmp/hecaton", "$HOME/tmp", "/tmpfoo", "verify/.tools/tmp", "./tmp/x",
          "the system temp directory"):
    check(f"passes {s!r}", not hits(s))
check("an exception covers only its own file and words",
      excepted("verify/test_turn_guard.py", "curl -d @/tmp/body.json")
      and not excepted("verify/test_turn_guard.py", "open('/tmp/x')")
      and not excepted("verify/run-tests.sh", "curl -d @/tmp/body.json"))

print(f"== no tracked script or test names a system temp directory ({len(scripts)} files) ==")
# The repo root holds no script today (its files are Markdown, YAML and locks), so a script added there is scanned
# with the rest: the list is every tracked file, not a list of directories.
check("the scan covers verify/, images/ and infra/, and reads the whole tracked tree, the repo root with it",
      any(r.startswith("verify/") for r in scripts) and any(r.startswith("images/") for r in scripts)
      and any(r.startswith("infra/") for r in scripts) and is_script("setup.sh") and is_script("Dockerfile"),
      str(len(scripts)))
found: list[str] = []
used: set[tuple[str, str]] = set()
for rel in scripts:
    if rel == SELF:
        continue
    for line in hits(read(rel)):
        cover = [(f, w) for f, w, _ in EXCEPTIONS if f in ("*", rel) and w in line]
        if cover:
            used.update(cover)
        else:
            found.append(f"{rel}: {line[:160]}")
check("none outside the documented exceptions (use $TMPDIR, else the checkout's ignored tmp/, or add the line to "
      "EXCEPTIONS with why)", not found, "\n    " + "\n    ".join(found))
stale = [f"{f}: {w}" for f, w, _ in EXCEPTIONS if (f, w) not in used]
check("every exception still matches a line, so none outlives what it excused", not stale, "; ".join(stale))

print("== a shell script's mktemp falls back to the checkout's tmp/ and is removed on exit ==")
MKTEMP = re.compile(r"\$\(\s*mktemp\b([^)]*)\)")
no_fallback, no_trap = [], []
shells = [r for r in scripts if r.endswith((".sh", ".bash"))]
for rel in shells:
    text = read(rel)
    calls = MKTEMP.findall(text)
    if not calls:
        continue
    bare = [a for a in calls if "-p" not in a.split() and "/" not in a]
    if bare and "TMPDIR:-" not in text:
        no_fallback.append(rel)
    if not re.search(r"\btrap\b[^\n]*\bEXIT\b", text):
        no_trap.append(rel)
check("each script with a bare mktemp sets TMPDIR=\"${TMPDIR:-<checkout>/tmp}\"", not no_fallback, ", ".join(no_fallback))
check("each script that calls mktemp removes it on an EXIT trap", not no_trap, ", ".join(no_trap))
check("fleet.sh, run directly, puts every mktemp in one scratch directory it removes on exit",
      'FLEET_SCRATCH="$(mktemp -d "${TMPDIR:-${REPO_ROOT}/tmp}/fleet.XXXXXX")"' in read("infra/terraform/fleet/fleet.sh")
      and 'export TMPDIR="${FLEET_SCRATCH}"' in read("infra/terraform/fleet/fleet.sh")
      and """rm -rf "${FLEET_SCRATCH}"' EXIT""" in read("infra/terraform/fleet/fleet.sh"))

# fleet.sh run for real: start-check's curl is a stub that writes down the TMPDIR it was given and fails, so the verb
# fails too. Every mktemp fleet.sh makes takes that TMPDIR, so where the stub saw it is where they land.
import tempfile  # noqa: E402
with tempfile.TemporaryDirectory(prefix="no-temp-1261-fleet-") as fx:
    fx = pathlib.Path(fx)
    (fx / "bin").mkdir()
    (fx / "tmp").mkdir()
    (fx / "bin" / "curl").write_text('#!/usr/bin/env bash\nprintf "%s\\n" "$TMPDIR" >>"$SEEN"\n'
                                     'mktemp >>"$SEEN"\nexit 7\n')
    (fx / "bin" / "curl").chmod(0o755)
    env = {"PATH": f"{fx / 'bin'}:{os.environ['PATH']}", "HOME": str(fx), "TMPDIR": str(fx / "tmp"),
           "SEEN": str(fx / "seen"), "WIB_LOG_DIR": str(fx / "logs"), "WIB_STATE_DIR": str(fx / "states")}
    r = subprocess.run(["bash", str(REPO / "infra/terraform/fleet/fleet.sh"), "start-check"], capture_output=True,
                       text=True, env=env, timeout=120)
    seen = (fx / "seen").read_text().split() if (fx / "seen").exists() else []
    scratch = pathlib.Path(seen[0]) if seen else None
    check("fleet.sh hands its verbs a TMPDIR of its own, a fleet.* directory under the caller's",
          r.returncode == 1 and scratch is not None and scratch.parent == fx / "tmp"
          and scratch.name.startswith("fleet.") and all(pathlib.Path(s).parent in (scratch,) for s in seen[1::2]),
          f"rc={r.returncode} seen={seen} {r.stderr[-400:]}")
    check("and removes it, with what was made in it, when the verb fails", scratch is not None and not scratch.exists()
          and not any((fx / "tmp").iterdir()), str(list((fx / "tmp").iterdir())))

print("== a Python temp directory or file is removed ==")
# A helper that hands the directory it made to its caller, who removes it.
HANDS_BACK = {"verify/artifact_cache.py": "scratch_dir() returns the directory, and each caller removes it"}
leaky = []
for rel in scripts:
    if not rel.endswith(".py") or rel == SELF or rel in HANDS_BACK:
        continue
    text = read(rel)
    # One removal per directory: a file with two mkdtemp calls and one rmtree leaves one behind.
    made, removed = text.count("mkdtemp("), text.count("rmtree")
    if made > removed:
        leaky.append(f"{rel}: {made} mkdtemp call(s), {removed} rmtree")
    if ("mkstemp(" in text or "delete=False" in text) and not re.search(r"unlink|os\.remove|os\.replace|\.rename\(|\.replace\(", text):
        leaky.append(f"{rel}: mkstemp or delete=False with no unlink or rename")
check("every mkdtemp is removed and every kept temp file unlinked or renamed into place", not leaky, "; ".join(leaky))

print("== both runners hand every test the fallback ==")
# Only an unset TMPDIR is set here, and only then is mkdir run: a fixture that runs a runner with nothing but its own
# bin on PATH (test_e2e_tools_tier.py's no-node case) sets TMPDIR and has no mkdir.
FALLBACK = ('if [[ -z "${TMPDIR:-}" ]]; then\n    TMPDIR="$(cd "${SCRIPT_DIR}/.." && pwd)/tmp"\n    mkdir -p "${TMPDIR}"\n'
            'fi\nexport TMPDIR\n')
for runner in ("verify/run-tests.sh", "verify/run-e2e-tools.sh"):
    text = read(runner)
    check(f"{runner} exports TMPDIR, else the checkout's tmp/, before any test runs",
          FALLBACK in text and text.index(FALLBACK) < text.index("$(mktemp"))
check("the checkout's tmp/ is ignored", "/tmp/" in read(".gitignore").splitlines())

print("== the cache tests' scratch tries TMPDIR, then the user's cache directory, never a system temp directory ==")
home = REPO / "tmp" / "no-such-home"
check("with TMPDIR set: TMPDIR first, then the user's cache directory",
      artifact_cache.scratch_parents({"TMPDIR": "/scratch/t", "HOME": "/home/u"})
      == [pathlib.Path("/scratch/t"), pathlib.Path("/home/u/.cache/unleash-watch-it-burn")])
check("with no TMPDIR: only the user's cache directory (XDG_CACHE_HOME when set)",
      artifact_cache.scratch_parents({"XDG_CACHE_HOME": "/x", "HOME": "/home/u"})
      == [pathlib.Path("/x/unleash-watch-it-burn")])
check("with nothing set: nowhere, so scratch_dir raises", artifact_cache.scratch_parents({}) == [])
try:
    artifact_cache.scratch_dir("no-temp-1261-", {})
    raised = ""
except artifact_cache.ArtifactCacheError as e:
    raised = str(e)
check("and its error says why", "neither TMPDIR, XDG_CACHE_HOME nor HOME is set" in raised, raised)
# A hecaton run's TMPDIR sits inside the worktree, so scratch_dir passes it over for the user's cache directory.
inside = REPO / "tmp" / "scratch-1261"
got = artifact_cache.scratch_dir("no-temp-1261-", {"TMPDIR": str(inside), "HOME": os.environ.get("HOME", "")})
try:
    want_parent = pathlib.Path(os.environ["HOME"]) / ".cache" / "unleash-watch-it-burn"
    check("a TMPDIR inside the worktree is passed over for the user's cache directory",
          got.parent == want_parent and got.is_dir() and artifact_cache.worktree_of(got) is None, str(got))
    check("and nothing is made inside the worktree", not inside.exists())
finally:
    got.rmdir()
check("no scratch candidate is a system temp directory",
      not any(str(p) in ("/tmp", "/var/tmp", "/dev/shm")
              for p in artifact_cache.scratch_parents({"HOME": os.environ.get("HOME", "/")})))

print("== offline means offline ==")
_calls = no_cloud.calls()
check("no check above called aws, kubectl, eksctl, terraform or helm", not _calls, _calls)

if failures:
    print(f"\nFAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("\nNo script or test names a system temp directory, and each removes what it makes.")
