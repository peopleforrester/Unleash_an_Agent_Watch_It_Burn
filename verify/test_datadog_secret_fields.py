# ABOUTME: Offline checks for verify/datadog-secret-fields.sh (#594, PRD #13 M1): its key list covers every
# ABOUTME: datadog-secret reference under gitops/, and against a kubectl shim it passes, fails and never asks for a value.
"""Why this exists (#594).

PRD #13 Milestone 1 is done when datadog-secret exists where it is read and a verification command shows its
fields are present, without the values. verify/datadog-secret-fields.sh is that command. Three things can make
it lie, and each is held here without a cluster:

  - a consumer starts reading a key the script does not require, so the script says PASS on a secret that
    leaves that consumer without its credential: every secretKeyRef and keyName to datadog-secret in gitops/
    must be in REQUIRED_KEYS;
  - it reads a value: every kubectl call it makes must use its key-names-only go-template, never jsonpath,
    yaml, json or describe, and must name the context, never fall back to the current one (CLAUDE.md);
  - it passes when it should not: a missing secret, an absent key or an empty value each exit non-zero and
    name the namespace.

That kubectl itself renders the template to names only is test_datadog_secret_fields_render.py, in the tools tier.
"""
from __future__ import annotations

import os
import pathlib
import re
import stat
import subprocess
import sys
import tempfile

import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = REPO / "verify" / "datadog-secret-fields.sh"
failures: list[str] = []


def check(name: str, ok: bool) -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    if not ok:
        failures.append(name)


def bash_array(name: str) -> list[str]:
    m = re.search(rf"^{name}=\(([^)]*)\)", SCRIPT.read_text(), re.M)
    return m.group(1).split() if m else []


def refs(node, found: set[str]) -> None:
    """Every key a manifest or values file reads from datadog-secret, in either reference shape."""
    if isinstance(node, dict):
        if node.get("name") == "datadog-secret" and "key" in node:
            found.add(node["key"])
        if node.get("secretName") == "datadog-secret" and "keyName" in node:
            found.add(node["keyName"])
        for v in node.values():
            refs(v, found)
    elif isinstance(node, list):
        for v in node:
            refs(v, found)


# ---- the key list covers every reference ----
referenced: set[str] = set()
files_with_refs = []
for path in sorted((REPO / "gitops").rglob("*.yaml")):
    text = path.read_text()
    if "datadog-secret" not in text:
        continue
    keys: set[str] = set()
    for doc in yaml.load_all(text, Loader=yaml.BaseLoader):
        refs(doc, keys)
    if keys:
        files_with_refs.append(path.relative_to(REPO).as_posix())
    referenced |= keys

required = bash_array("REQUIRED_KEYS")
namespaces = bash_array("NAMESPACES")
check("the reference scan found the collector, falcosidekick and Datadog Agent references",
      {"gitops/otel-collector/values.yaml", "gitops/bootstrap/apps/falcosidekick.yaml",
       "gitops/manifests/datadog/datadog-agent.yaml"} <= set(files_with_refs))
check(f"REQUIRED_KEYS {required} covers every key gitops/ reads from datadog-secret {sorted(referenced)}",
      bool(required) and referenced <= set(required))
check(f"NAMESPACES {namespaces} are the three consumers' namespaces",
      namespaces == ["datadog", "monitoring", "security"])

# ---- behaviour against a kubectl shim ----
SHIM = """#!/usr/bin/env bash
printf '%s\\n' "$*" >>"${CALLS}"
ns=""; prev=""
for a in "$@"; do [[ "${prev}" == "-n" ]] && ns="${a}"; prev="${a}"; done
f="${FIXTURES}/${ns}"
[[ -f "${f}" ]] || { echo 'Error from server (NotFound): secrets "datadog-secret" not found' >&2; exit 1; }
cat "${f}"
"""
BOTH = "api-key=set\napp-key=set\n"


def run(fixtures: dict[str, str], *args: str) -> tuple[int, str, list[str]]:
    with tempfile.TemporaryDirectory() as tmp:
        t = pathlib.Path(tmp)
        (t / "bin").mkdir()
        (t / "fx").mkdir()
        shim = t / "bin" / "kubectl"
        shim.write_text(SHIM)
        shim.chmod(shim.stat().st_mode | stat.S_IEXEC)
        for ns, body in fixtures.items():
            (t / "fx" / ns).write_text(body)
        env = {**os.environ, "PATH": f"{t / 'bin'}:{os.environ['PATH']}", "CALLS": str(t / "calls"),
               "FIXTURES": str(t / "fx")}
        p = subprocess.run(["bash", str(SCRIPT), *args], env=env, capture_output=True, text=True)
        calls = (t / "calls").read_text().splitlines() if (t / "calls").exists() else []
        return p.returncode, p.stdout + p.stderr, calls


rc, out, calls = run({})
check("no context argument: exits non-zero, says so, and makes no kubectl call",
      rc != 0 and "kube-context" in out and not calls)

all_ns = {ns: BOTH for ns in ("datadog", "monitoring", "security")}
rc, out, calls = run(all_ns, "ctx-attendee-007")
check("every namespace has both keys set: exits 0 and reports PASS for each", rc == 0
      and all(re.search(rf"PASS\s+{ns}\s+datadog-secret fields: api-key,app-key", out)
              for ns in ("datadog", "monitoring", "security")))
check("one kubectl call per namespace, each naming the context it was given",
      len(calls) == 3 and all("--context ctx-attendee-007" in c for c in calls))
check("every call reads key names through the go-template, never a value-bearing output",
      all("-o go-template=" in c and "{{$k}}=" in c for c in calls)
      and not any(re.search(r"jsonpath|-o (yaml|json)\b|describe|base64", c) for c in calls))

rc, out, _ = run({**all_ns, "security": "api-key=set\n"}, "ctx")
check("app-key absent in security: exits non-zero and names the namespace and the key",
      rc != 0 and re.search(r"FAIL\s+security .*missing: app-key\(absent\)", out) is not None)

rc, out, _ = run({**all_ns, "datadog": "api-key=empty\napp-key=set\n"}, "ctx")
check("empty api-key in datadog: exits non-zero and says empty",
      rc != 0 and re.search(r"FAIL\s+datadog .*missing: api-key\(empty\)", out) is not None)

rc, out, _ = run({k: v for k, v in all_ns.items() if k != "monitoring"}, "ctx")
check("no datadog-secret in monitoring: exits non-zero and shows kubectl's NotFound",
      rc != 0 and re.search(r"FAIL\s+monitoring\s+datadog-secret not readable: .*NotFound", out) is not None)

if failures:
    print(f"\n{len(failures)} check(s) failed", file=sys.stderr)
    sys.exit(1)
print("\ndatadog-secret-fields.sh: all checks passed")
