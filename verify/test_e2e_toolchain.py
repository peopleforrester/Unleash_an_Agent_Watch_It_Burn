# ABOUTME: The E2E gate's toolchain (#440, #524): Node 24 and the yarn 4 the Backstage app pins through corepack,
# ABOUTME: and run-e2e.sh runs to its prerequisite check and fails loudly, never skips, when something is missing.
"""Holds what #440 made true about the machine the E2E gate runs on, offline.

#440 gave the dispatch machine Node 24 with corepack and no global yarn. `verify/run-e2e.sh` requires `node` and
`corepack`, fails unless Node's major is 24, and runs `corepack yarn` in the Backstage app. That only gives yarn 4
while two pins hold: `"packageManager": "yarn@4.x"` in the Backstage `package.json`, which corepack reads, and
`yarnPath` in `.yarnrc.yml`, which must name the same release, committed to the repo. Drop either, or let them
disagree, and `corepack yarn` runs some other yarn, or none. Nothing under verify/ checked either pin.

The other half of #440 was running `run-e2e.sh` once. That run is in decisions.md: it exits 1 in its
prerequisite check, Node and yarn no longer among the missing. A past run cannot be tested, so this runs the
script itself in an empty toolchain made up for it, and checks the behaviour that run relied on. With nothing on
PATH it exits 1 and lists node, corepack and CONTEXT as missing. With a Node 22 on PATH it names the version
it found. With Node 24 and corepack on PATH neither is listed, and it still exits 1 on what remains. Every
case stops in the prerequisite check, before anything runs: CONTEXT is unset, so no kubectl is ever called.

Since #585 run-e2e.sh fetches kyverno, conftest, terraform, kubectl and helm itself, and since #654 otelcol-contrib
too, so none of the six is ever listed as missing from PATH. With no curl, tar, unzip or sha256sum it cannot fetch them, and it says so instead.
What a fetch does inside run-e2e.sh is held in test_e2e_tools_tier.py, next to the fetch's own fixtures.
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

REPO = pathlib.Path(__file__).resolve().parent.parent
RUN_E2E = REPO / "verify" / "run-e2e.sh"
BACKSTAGE = REPO / "images" / "watch-it-burn-backstage"
BASH = shutil.which("bash")

failures: list[str] = []


def check(name: str, cond: bool) -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        failures.append(name)


rune2e = RUN_E2E.read_text()

print("== yarn 4: the Backstage pin corepack resolves ==")
package = json.loads((BACKSTAGE / "package.json").read_text())
pm = re.fullmatch(r"yarn@(\d+)\.(\d+)\.(\d+)", package.get("packageManager", ""))
check(f"package.json pins packageManager to an exact yarn ({package.get('packageManager')!r})", pm is not None)
version = ".".join(pm.groups()) if pm else ""
check(f"the pinned yarn is yarn 4 ({version or 'none'})", bool(pm) and pm.group(1) == "4")

yarnrc = (BACKSTAGE / ".yarnrc.yml").read_text()
yp = re.search(r"^yarnPath:\s*(\S+)\s*$", yarnrc, re.M)
yarn_path = yp.group(1) if yp else ""
check(f".yarnrc.yml yarnPath names the packageManager release ({yarn_path or 'none'})",
      bool(version) and yarn_path == f".yarn/releases/yarn-{version}.cjs")
release = BACKSTAGE / yarn_path if yarn_path else None
tracked = bool(yarn_path) and subprocess.run(
    ["git", "-C", str(BACKSTAGE), "ls-files", "--error-unmatch", "--", yarn_path],
    capture_output=True).returncode == 0
check("the yarnPath release is committed, not left to a local download", tracked)
check(f"the committed release is yarn {version or '?'} itself",
      bool(release) and release.is_file() and f'version:"{version}"' in release.read_text(errors="replace"))
check("run-e2e.sh runs corepack yarn inside the Backstage app, where corepack reads that pin",
      'BACKSTAGE_DIR="${SCRIPT_DIR}/../images/watch-it-burn-backstage"' in rune2e
      and 'cd "${BACKSTAGE_DIR}"' in rune2e and "corepack yarn install --immutable" in rune2e)

print("== Node 24: the gate's Node is the Backstage image's ==")
gate_major = re.search(r"""process\.versions\.node\.split\("\."\)\[0\]'\)" != "(\d+)" ]]""", rune2e)
gate_major = gate_major.group(1) if gate_major else ""
check(f"run-e2e.sh requires Node 24 ({gate_major or 'no Node check found'})", gate_major == "24")
image = re.search(r"^FROM node:(\d+)\b", (BACKSTAGE / "packages/backend/Dockerfile").read_text(), re.M)
check(f"the Backstage image runs the Node major the gate requires (node:{image.group(1) if image else '?'})",
      bool(image) and image.group(1) == gate_major)
engines = package.get("engines", {}).get("node", "")
check(f"package.json engines accept Node {gate_major or '?'} ({engines!r})",
      bool(gate_major) and gate_major in re.split(r"\s*\|\|\s*", engines))

print("== run-e2e.sh runs, and fails loudly in its prerequisite check ==")


def run_e2e(stubs: dict[str, str]) -> subprocess.CompletedProcess:
    """Runs run-e2e.sh with a PATH holding only `dirname` and the given stub tools, in an empty environment."""
    with tempfile.TemporaryDirectory() as tmp:
        bindir = pathlib.Path(tmp) / "bin"
        bindir.mkdir()
        os.symlink(shutil.which("dirname"), bindir / "dirname")
        for tool, body in stubs.items():
            stub = bindir / tool
            stub.write_text(f"#!{BASH}\n{body}\n")
            stub.chmod(0o755)
        return subprocess.run([BASH, str(RUN_E2E)], capture_output=True, text=True, timeout=60,
                              env={"PATH": str(bindir), "HOME": tmp})


def node_stub(full: str) -> str:
    return f'case "$1" in -p) echo {full.split(".")[0]} ;; --version) echo v{full} ;; *) exit 1 ;; esac'


CANNOT_RUN = "E2E SUITE CANNOT RUN; this is a failure, not a skip"
bare = run_e2e({})
check(f"with no toolchain it exits 1 (exit {bare.returncode})", bare.returncode == 1)
check("it says it cannot run, as a failure and not a skip", CANNOT_RUN in bare.stderr)
for item in ("node is not on PATH", "corepack is not on PATH", "CONTEXT is not set", "curl is not on PATH",
             "unzip is not on PATH", "sha256sum is not on PATH", "uv is not on PATH",
             "the pinned kyverno, conftest, terraform, kubectl, helm and otelcol-contrib were not fetched: "
             "fetch-e2e-tools.sh needs curl, tar, unzip and sha256sum"):
    check(f"it lists what is missing: {item}", f"  - {item}" in bare.stderr)
# The six pinned tools come from fetch-e2e-tools.sh (#585, #654), never from PATH, so PATH is never asked for them.
for tool in ("kubectl", "helm", "kyverno", "conftest", "terraform", "otelcol-contrib"):
    check(f"it never asks for {tool} on PATH",
          not any(tool in line and "not on PATH" in line for line in bare.stderr.splitlines()))
check("it runs no check before the prerequisites pass", "E2E checks ran" not in bare.stdout + bare.stderr)

old = run_e2e({"node": node_stub("22.11.0"), "corepack": "exit 0"})
check(f"with Node 22 on PATH it exits 1 (exit {old.returncode})", old.returncode == 1)
check("it names the Node it found and the Node 24 it needs",
      "node v22.11.0 is on PATH; the Backstage suite needs Node 24" in old.stderr)

ready = run_e2e({"node": node_stub("24.22.0"), "corepack": "exit 0"})
check(f"with Node 24 and corepack on PATH it still exits 1 on the rest (exit {ready.returncode})",
      ready.returncode == 1 and CANNOT_RUN in ready.stderr)
check("Node 24 and corepack are not listed as missing",
      "node is not on PATH" not in ready.stderr and "corepack is not on PATH" not in ready.stderr
      and "needs Node 24" not in ready.stderr)
check("no global yarn is asked for", "yarn" not in ready.stderr)

if failures:
    print(f"\nFAILED: {len(failures)} check(s)")
    sys.exit(1)
print("\nAll E2E toolchain checks passed.")
