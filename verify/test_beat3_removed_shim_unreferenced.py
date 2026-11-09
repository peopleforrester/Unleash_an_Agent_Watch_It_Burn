# ABOUTME: Nothing that deploys, verifies or documents Challenge 4 / Beat 3 points at the removed copy of the poisoned
# ABOUTME: server under challenges/03-bad-mcp-excessive-agency (#1193): a tracked-tree sweep for its paths (#1199).
"""No cluster and no network: this reads the tracked tree only.

#1193 deleted the folder that held a stale copy of Beat 3's poisoned MCP server under
challenges/03-bad-mcp-excessive-agency (its server.py, Dockerfile and k8s-manifest.yaml), and one of its criteria was
that nothing that deploys, verifies or documents Challenge 4 / Beat 3 points at the removed files. The tests it
changed read gitops/ai-layer/server.py, so a test that read the old path would fail, but no test held a manifest, a
doc, a script or verify/scope-map.yaml to that. Test review run 18673 found the gap, and #1199 asked for this test.

What this checks:

1. No tracked text file, outside the history records, names the removed folder or its files as a path:
   - the folder by its full path, with or without a file after it;
   - one of its three files under the folder's name (`<folder>/server.py`, `/Dockerfile`, `/k8s-manifest.yaml`);
   - the folder's name alone as a directory (`<folder>/` followed by a quote, backtick, bracket, space or line end);
   - the folder's name as a relative path (`./<folder>`, `../<folder>`);
   - the image the deleted manifest named and the deleted Dockerfile built (`REGISTRY/<folder>`, `<folder>@sha256:`).
   The live server keeps the name: the Deployment, Service, label, agentgateway target, `deploy/<name>` in a command
   and a slash-separated list of component names are not paths to the folder and do not match.
2. The history records are the only files left out: decisions.md, PROGRESS.md and PROJECT_STATE.md record what was
   there and what was removed, and verify/test_poisoned_server_one_copy.py's docstring tells #1193's story (that test
   fails if the folder comes back). Each file left out must still be tracked, so the list cannot outlive its files.
3. No tracked path lies under the removed folder, and Challenge 3's FACILITATOR.md says where the code is now,
   gitops/ai-layer/server.py.
4. The sweep catches a pointer: it runs on a scratch repo holding the shapes the base before #1193 had (the
   scope-map entry, a test's read, a manifest comment, a doc table cell, the images.lock row) and the shapes a build
   would use (a relative build context, a workflow context), beside the live names that must not match, and must name
   the pointers alone.

The folder's name is built from halves here so this file is not itself a match.
"""
from __future__ import annotations

import pathlib
import re
import subprocess
import sys
import tempfile

REPO = pathlib.Path(__file__).resolve().parents[1]
NAME = "evil-mcp" + "-shim"
BEAT_DIR = "challenges/03-bad-mcp-excessive-agency"
FOLDER = f"{BEAT_DIR}/{NAME}"
REMOVED_FILES = ("server.py", "Dockerfile", "k8s-manifest.yaml")
THE_COPY = "gitops/ai-layer/server.py"

# Files that record history and may name the removed folder: each with why.
HISTORY = {
    "decisions.md": "the append-only record of #1193's removal and earlier entries that named the folder",
    "PROGRESS.md": "the dated progress log",
    "PROJECT_STATE.md": "the cycle record",
    "verify/test_poisoned_server_one_copy.py": "its docstring tells #1193's removal; it fails if the folder returns",
}

N = re.escape(NAME)
FORMS = {
    "the folder's full path": re.compile(re.escape(FOLDER) + r"(?![\w.-])"),
    "a removed file under the folder's name": re.compile(
        rf"(?<![\w.-]){N}/(?:{'|'.join(re.escape(f) for f in REMOVED_FILES)})(?![\w.-])"),
    "the folder's name alone as a directory": re.compile(rf"(?<![\w./-]){N}/(?=[\s`'\")\],;|]|$)", re.M),
    "the folder as a relative path": re.compile(rf"(?<![\w.])\.{{1,2}}/{N}(?![\w.-])"),
    "the removed manifest's image": re.compile(rf"REGISTRY/{N}(?![\w.-])|(?<![\w.-]){N}@sha256:"),
}

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"\n{detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def tracked_files(root: pathlib.Path) -> list[str]:
    r = subprocess.run(["git", "-C", str(root), "ls-files", "-z"], capture_output=True, timeout=120)
    if r.returncode != 0:
        sys.exit(f"FAILED: git ls-files exited {r.returncode} in {root}: {r.stderr.decode(errors='replace').strip()}")
    return sorted(p for p in r.stdout.decode().split("\0") if p)


def pointers_in(text: str) -> list[tuple[int, str, str]]:
    """Each (line number, form, line) where a line names the removed folder as a path."""
    out = []
    for i, line in enumerate(text.splitlines(), 1):
        for form, rx in FORMS.items():
            if rx.search(line):
                out.append((i, form, line.strip()[:160]))
    return out


def sweep(root: pathlib.Path) -> tuple[dict[str, list[tuple[int, str, str]]], list[str], list[str]]:
    """Each tracked text file outside HISTORY with a pointer to the folder; each tracked path under the folder; and
    every tracked path. A submodule is a directory here and belongs to its own repo, a symlink is skipped, and a file
    with a NUL in its head is binary."""
    files = tracked_files(root)
    under = [rel for rel in files if rel == FOLDER or rel.startswith(FOLDER + "/")]
    hits: dict[str, list[tuple[int, str, str]]] = {}
    for rel in files:
        if rel in HISTORY:
            continue
        p = root / rel
        if p.is_symlink() or not p.is_file():
            continue
        data = p.read_bytes()
        if b"\0" in data[:8192]:
            continue
        found = pointers_in(data.decode("utf-8", errors="replace"))
        if found:
            hits[rel] = found
    return hits, under, files


print("== the sweep names a planted pointer and nothing else ==")
POINTERS = {
    "verify/scope-map.yaml": f"  test_beat03_c7.py:\n    - {FOLDER}/server.py\n",
    "verify/test_reads_old.py": f'SHIM_PY = (REPO / BEAT_DIR / "{NAME}/server.py").read_text()\n',
    f"{BEAT_DIR}/plant-fake-secret.yaml": f"  # via secretKeyRef (see {NAME}/k8s-manifest.yaml) and returned.\n",
    "docs/READINESS-CHECKLIST.md": f"| C7 | Rogue MCP | `toggle-mcp-authz-on.sh` + `{NAME}/` | ok |\n",
    "images.lock": f"REGISTRY/{NAME}@sha256:REPLACE_AT_BUILD - not-an-image:challenge-03-placeholder -\n",
    f"{BEAT_DIR}/build.sh": f"docker build -t shim ./{NAME}\n",
    ".github/workflows/shim.yaml": f"      context: {FOLDER}\n",
    "gitops/kustomization.yaml": f"resources:\n  - ../../{FOLDER}/k8s-manifest.yaml\n",
}
LIVE_NAMES = {
    "gitops/ai-layer/resources.yaml": f"  name: {NAME}\n  labels: {{ app: {NAME} }}\n"
                                      f"  selector: {{ matchLabels: {{ app: {NAME} }} }}\n",
    "gitops/ai-layer/agentgateway.yaml": f"  host: http://{NAME}.agent.svc.cluster.local:8000/mcp\n",
    "challenges/LAB-TEXT.md": f"> kubectl -n agent exec deploy/{NAME} -- cat /app/server.py\n",
    "docs/live.txt": f"deployment.apps/{NAME} restarted\ntracking id ai-layer:apps/Deployment:agent/{NAME}\n",
    "prds/26.md": f"| Skip KubeArmor/ESO/Backstage/{NAME}/customer-stream | See meta-PRD |\n",
    f"{BEAT_DIR}/FACILITATOR.md": f"served by **{NAME}**, whose code is `{THE_COPY}` (the one copy).\n",
    "backstage/catalog/burritobot.yaml": f"    backstage.io/kubernetes-label-selector: app={NAME}\n",
    "decisions.md": f"`{FOLDER}/` held a June copy, and `REGISTRY/{NAME}@sha256:REPLACE_AT_BUILD`.\n",
}
with tempfile.TemporaryDirectory() as tmp:
    scratch = pathlib.Path(tmp)
    subprocess.run(["git", "init", "-q", str(scratch)], check=True, timeout=60)
    for rel, text in {**POINTERS, **LIVE_NAMES}.items():
        (scratch / rel).parent.mkdir(parents=True, exist_ok=True)
        (scratch / rel).write_text(text)
    subprocess.run(["git", "-C", str(scratch), "add", "-A"], check=True, timeout=60)
    hits, under, _ = sweep(scratch)
    check("the sweep names each planted pointer and no live name or history record",
          sorted(hits) == sorted(POINTERS), "\n".join(f"    {rel}: {v}" for rel, v in sorted(hits.items())))
    (scratch / FOLDER).mkdir(parents=True)
    (scratch / FOLDER / "server.py").write_text("print('stale')\n")
    subprocess.run(["git", "-C", str(scratch), "add", "-A"], check=True, timeout=60)
    _, under, _ = sweep(scratch)
    check("the path check names a file restored under the removed folder", under == [f"{FOLDER}/server.py"],
          repr(under))

print("== the files left out are history records, and still tracked ==")
hits, under, files = sweep(REPO)
check("the sweep reads the tracked tree (git ls-files listed files)", len(files) > 100, f"{len(files)} files")
for rel, why in HISTORY.items():
    check(f"{rel} is tracked ({why})", rel in files)

print(f"== nothing that deploys, verifies or documents Beat 3 points at {FOLDER}/ ==")
check(f"no tracked text file outside the history records names {FOLDER}/ or its files as a path", not hits,
      "\n".join(f"    {rel}:{i}: {form}: {line}" for rel, v in sorted(hits.items()) for i, form, line in v))
check(f"no tracked path lies under {FOLDER}/", not under, "\n".join(under))
check(f"{FOLDER} is not a directory in the checkout", not (REPO / FOLDER).exists())
facilitator = (REPO / BEAT_DIR / "FACILITATOR.md").read_text()
check(f"{BEAT_DIR}/FACILITATOR.md names {THE_COPY} as the poisoned server's code", f"`{THE_COPY}`" in facilitator)
check(f"{THE_COPY} exists", (REPO / THE_COPY).is_file())

if failures:
    print(f"\nFAILED: {len(failures)} check(s): {', '.join(failures)}")
    sys.exit(1)
print(f"\nOK: nothing outside the history records points at the removed {FOLDER}/")
