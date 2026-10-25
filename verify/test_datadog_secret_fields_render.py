# ABOUTME: Runs verify/datadog-secret-fields.sh with the real kubectl rendering its go-template over client-side
# ABOUTME: Secrets holding sentinel values: it reports names and set/empty only, and no value reaches its output (#594).
# SUITE: e2e (needs kubectl: the template is kubectl's to render)
# E2E TIER: tools (no cluster, no AWS: run-e2e-tools.sh runs it with the pinned tools, #572)
#
# Why. test_datadog_secret_fields.py holds that the script asks for its go-template and nothing value-bearing,
# against a shim that answers with canned lines. Whether that template really emits names and never values is
# kubectl's behaviour, so this renders it with the pinned kubectl. A thin wrapper turns the script's
# `get secret datadog-secret -n <ns>` into `create secret generic --dry-run=client` over this file's
# fixtures, which kubectl builds and renders locally with KUBECONFIG=/dev/null. No cluster is reached.
from __future__ import annotations

import os
import pathlib
import shutil
import stat
import subprocess
import sys
import tempfile

REPO = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = REPO / "verify" / "datadog-secret-fields.sh"
failures: list[str] = []


def check(name: str, ok: bool) -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    if not ok:
        failures.append(name)


KUBECTL = shutil.which("kubectl")
if not KUBECTL:
    print("FAIL: kubectl is not on PATH (run through verify/run-e2e-tools.sh, which puts the pinned one first)",
          file=sys.stderr)
    sys.exit(1)

# The wrapper keeps the script's own -o go-template=... argument and hands it to the real kubectl unchanged.
WRAPPER = """#!/usr/bin/env bash
ns=""; out=""; prev=""
for a in "$@"; do
    [[ "${prev}" == "-n" ]] && ns="${a}"
    [[ "${prev}" == "-o" ]] && out="${a}"
    prev="${a}"
done
[[ -n "${out}" ]] || { echo "wrapper: the script passed no -o output format" >&2; exit 3; }
f="${FIXTURES}/${ns}"
[[ -f "${f}" ]] || { echo 'Error from server (NotFound): secrets "datadog-secret" not found' >&2; exit 1; }
mapfile -t lits <"${f}"
exec "${REAL_KUBECTL}" create secret generic datadog-secret -n "${ns}" "${lits[@]}" --dry-run=client -o "${out}"
"""
API, APP = "SENTINEL-API-7f3c9a", "SENTINEL-APP-41d0e2"


def run(fixtures: dict[str, list[str]]) -> tuple[int, str]:
    with tempfile.TemporaryDirectory() as tmp:
        t = pathlib.Path(tmp)
        (t / "bin").mkdir()
        (t / "fx").mkdir()
        w = t / "bin" / "kubectl"
        w.write_text(WRAPPER)
        w.chmod(w.stat().st_mode | stat.S_IEXEC)
        for ns, lits in fixtures.items():
            (t / "fx" / ns).write_text("\n".join(lits) + "\n")
        env = {**os.environ, "PATH": f"{t / 'bin'}:{os.environ['PATH']}", "KUBECONFIG": "/dev/null",
               "FIXTURES": str(t / "fx"), "REAL_KUBECTL": KUBECTL}
        p = subprocess.run(["bash", str(SCRIPT), "ctx-render"], env=env, capture_output=True, text=True)
        return p.returncode, p.stdout + p.stderr


full = [f"--from-literal=api-key={API}", f"--from-literal=app-key={APP}"]
rc, out = run({ns: full for ns in ("datadog", "monitoring", "security")})
print(out)
check("real kubectl render, both keys set everywhere: exits 0 with a PASS per namespace",
      rc == 0 and out.count("PASS") == 3 and "fields: api-key,app-key" in out)
check("neither sentinel value, nor its base64, appears in the output",
      not any(s in out for s in (API, APP, "U0VOVElORUwt")))

rc, out = run({"datadog": full, "monitoring": full,
               "security": [f"--from-literal=api-key={API}", "--from-literal=app-key="]})
print(out)
check("real kubectl render, app-key empty in security: exits non-zero and reports it empty",
      rc != 0 and "missing: app-key(empty)" in out and API not in out)

if failures:
    print(f"\n{len(failures)} check(s) failed", file=sys.stderr)
    sys.exit(1)
print("\ndatadog-secret-fields.sh render: all checks passed")
