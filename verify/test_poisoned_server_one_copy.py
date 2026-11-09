# ABOUTME: The poisoned weather server has one copy in the repo, gitops/ai-layer/server.py, and it is the one the
# ABOUTME: clusters run: Argo CD's ai-layer app builds evil-mcp-src from it and evil-mcp-shim runs it (#1198).
"""No cluster and no network: this reads the tracked tree only.

#1193 removed a stale second copy of Challenge 3's poisoned MCP server, challenges/03-bad-mcp-excessive-agency/
evil-mcp-shim/, whose server.py had drifted from the one the clusters run, and pointed the tests at
gitops/ai-layer/server.py. One of its criteria was that only one copy of that server's code exists in the repo and that
it is the one the clusters run. No test checked it: the tests read the right file, but a copy could come back
anywhere and every test still passed. Test review run 18673 found that, and #1198 asked for this test.

What this checks:

1. The clusters run gitops/ai-layer/server.py. The ai-layer Argo CD Application sources gitops/ai-layer; that
   bundle's kustomization generates the evil-mcp-src ConfigMap from server.py alone; and the evil-mcp-shim
   Deployment mounts evil-mcp-src at /app and runs `python /app/server.py`.
2. The server's own markers are in that file: the two rogue tools defined as functions (read_internal_config,
   apply_optimization), the FastMCP server named evil-mcp-shim assigned to a name, and the read of the
   FAKE_MCP_SENTINEL variable. If
   one is reworded, this says which, rather than passing on a sweep for a marker nothing carries.
3. No other tracked text file carries any of those markers as code: a definition at the start of a line (in a .py, a
   YAML block, a Dockerfile heredoc or a doc's code block), the FastMCP assignment or the variable read. A test
   that names a tool in a quoted string, a record that quotes a marker in a sentence, or a manifest that sets the
   variable, is not code of the server and does not match. No tracked path has a directory or file named evil-mcp-shim, the name the removed copy lived under.
4. The sweep catches a copy: it runs on a scratch repo holding the server, a copy at the old path and a copy inlined
   in a ConfigMap, beside a test string, a record quoting the markers in a sentence and a manifest env entry that
   must not match, and must name the copies alone.

The marker names are built from halves here so this file is not itself a match.
"""
from __future__ import annotations

import pathlib
import re
import subprocess
import sys
import tempfile

import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
THE_COPY = "gitops/ai-layer/server.py"
AI_LAYER = REPO / "gitops" / "ai-layer"
APP = REPO / "gitops" / "bootstrap" / "apps" / "ai-layer.yaml"

READ_TOOL = "read_internal" + "_config"
APPLY_TOOL = "apply_" + "optimization"
SERVER_NAME = "evil-mcp" + "-shim"
SENTINEL_VAR = "FAKE_MCP" + "_SENTINEL"

# Each marker of the poisoned server's code, as code: a function definition at the start of a line, the FastMCP
# server assigned to a name at the start of a line, and a read of the sentinel variable through os.environ or
# os.getenv. The first two are anchored to a line's start so a record that quotes them in a sentence (decisions.md
# does, for #1198) is not read as a copy; run 19379 failed its gate on that before the FastMCP marker was anchored.
MARKERS = {
    f"def {READ_TOOL}": re.compile(rf"^[ \t]*(?:async[ \t]+)?def[ \t]+{READ_TOOL}[ \t]*\(", re.M),
    f"def {APPLY_TOOL}": re.compile(rf"^[ \t]*(?:async[ \t]+)?def[ \t]+{APPLY_TOOL}[ \t]*\(", re.M),
    f'= FastMCP("{SERVER_NAME}"': re.compile(rf"^[ \t]*[A-Za-z_]\w*[ \t]*=[ \t]*FastMCP\(\s*['\"]{SERVER_NAME}['\"]", re.M),
    f"read of {SENTINEL_VAR}": re.compile(
        rf"(?:environ\.get\(|getenv\(|environ\[)\s*['\"]{SENTINEL_VAR}['\"]"),
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


def markers_in(text: str) -> list[str]:
    return [name for name, rx in MARKERS.items() if rx.search(text)]


def sweep(root: pathlib.Path) -> tuple[dict[str, list[str]], list[str], int]:
    """Each tracked text file that carries a marker, with the markers it carries; each tracked path with a part named
    evil-mcp-shim; and how many files were listed. A submodule is a directory here and belongs to its own repo; a
    symlink is read at its target; a file with a NUL in its head is binary."""
    files = tracked_files(root)
    hits: dict[str, list[str]] = {}
    named = [rel for rel in files if any(part.split(".")[0] == SERVER_NAME for part in pathlib.PurePosixPath(rel).parts)]
    for rel in files:
        p = root / rel
        if p.is_symlink() or not p.is_file():
            continue
        data = p.read_bytes()
        if b"\0" in data[:8192]:
            continue
        found = markers_in(data.decode("utf-8", errors="replace"))
        if found:
            hits[rel] = found
    return hits, named, len(files)


def docs(path: pathlib.Path) -> list[dict]:
    return [d for d in yaml.safe_load_all(path.read_text()) if isinstance(d, dict)]


print("== the clusters run gitops/ai-layer/server.py ==")
app = docs(APP)
sources = [s for d in app for s in ([d.get("spec", {}).get("source")] + d.get("spec", {}).get("sources", [])) if s]
check("the ai-layer Argo CD Application sources gitops/ai-layer",
      any(s.get("path") == "gitops/ai-layer" for s in sources), repr(sources))

kust = docs(AI_LAYER / "kustomization.yaml")[0]
gens = {g.get("name"): g.get("files", []) for g in kust.get("configMapGenerator", [])}
check("the ai-layer kustomization generates evil-mcp-src from server.py alone",
      gens.get("evil-mcp-src") == ["server.py"], repr(gens.get("evil-mcp-src")))
check("no other generated ConfigMap of the bundle is built from server.py",
      [n for n, fs in gens.items() if n != "evil-mcp-src" and "server.py" in fs] == [],
      repr({n: fs for n, fs in gens.items() if "server.py" in fs}))
check(f"{THE_COPY} exists", (REPO / THE_COPY).is_file())

deploys = [d for d in docs(AI_LAYER / "resources.yaml")
           if d.get("kind") == "Deployment" and d.get("metadata", {}).get("name") == SERVER_NAME]
check(f"resources.yaml has one {SERVER_NAME} Deployment", len(deploys) == 1, f"{len(deploys)} found")
if len(deploys) == 1:
    spec = deploys[0]["spec"]["template"]["spec"]
    vols = {v["name"]: v.get("configMap", {}).get("name") for v in spec.get("volumes", [])}
    containers = spec.get("containers", [])
    check(f"{SERVER_NAME} has one container", len(containers) == 1, f"{len(containers)} found")
    c = containers[0] if containers else {}
    check(f"{SERVER_NAME} runs python /app/server.py", c.get("command") == ["python", "/app/server.py"],
          repr(c.get("command")))
    app_mounts = [m for m in c.get("volumeMounts", []) if m.get("mountPath") == "/app"]
    check(f"{SERVER_NAME} mounts evil-mcp-src at /app",
          len(app_mounts) == 1 and vols.get(app_mounts[0]["name"]) == "evil-mcp-src", f"{app_mounts!r} {vols!r}")

print(f"== the poisoned server's markers are in {THE_COPY} ==")
in_copy = markers_in((REPO / THE_COPY).read_text())
for name in MARKERS:
    check(f"{THE_COPY} carries {name}", name in in_copy)

print("== the sweep names a planted copy and nothing else ==")
with tempfile.TemporaryDirectory() as tmp:
    scratch = pathlib.Path(tmp)
    subprocess.run(["git", "init", "-q", str(scratch)], check=True, timeout=60)
    server = (REPO / THE_COPY).read_text()
    for rel, text in {
        THE_COPY: server,
        f"challenges/03-bad-mcp-excessive-agency/{SERVER_NAME}/server.py": server,
        "gitops/inline.yaml": "kind: ConfigMap\ndata:\n  server.py: |\n"
                              + "".join(f"    {line}\n" for line in server.splitlines()),
        "verify/test_reads_it.py": f'check("the rogue tool is named", "def {READ_TOOL}(" in shim)\n',
        "gitops/env.yaml": f"env:\n  - {{ name: {SENTINEL_VAR}, value: x }}\n",
        "decisions.md": f"The server's markers are the `{READ_TOOL}` and `{APPLY_TOOL}` definitions, "
                        f'`FastMCP("{SERVER_NAME}"`, and `def {READ_TOOL}(` named in a sentence.\n',
    }.items():
        (scratch / rel).parent.mkdir(parents=True, exist_ok=True)
        (scratch / rel).write_text(text)
    subprocess.run(["git", "-C", str(scratch), "add", "-A"], check=True, timeout=60)
    hits, named, _ = sweep(scratch)
    check("the sweep names the server, the copy at the old path and the inlined copy, and nothing else",
          sorted(hits) == sorted([THE_COPY, f"challenges/03-bad-mcp-excessive-agency/{SERVER_NAME}/server.py",
                                  "gitops/inline.yaml"]), repr(hits))
    check("each copy carries every marker", all(sorted(v) == sorted(MARKERS) for v in hits.values()), repr(hits))
    check(f"the path check names the old {SERVER_NAME} directory",
          named == [f"challenges/03-bad-mcp-excessive-agency/{SERVER_NAME}/server.py"], repr(named))

print(f"== no tracked file but {THE_COPY} carries the poisoned server's code ==")
hits, named, listed = sweep(REPO)
check("the sweep reads the tracked tree (git ls-files listed files)", listed > 100, f"{listed} files")
others = {rel: found for rel, found in hits.items() if rel != THE_COPY}
check(f"no tracked file but {THE_COPY} carries a marker of the poisoned server", not others,
      "\n".join(f"    {rel}: {', '.join(found)}" for rel, found in sorted(others.items())))
check(f"no tracked path has a directory or file named {SERVER_NAME}", not named, "\n".join(named))

if failures:
    print(f"\nFAILED: {len(failures)} check(s): {', '.join(failures)}")
    sys.exit(1)
print(f"\nOK: one copy of the poisoned weather server, {THE_COPY}, and the clusters run it")
