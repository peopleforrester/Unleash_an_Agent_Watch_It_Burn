# ABOUTME: Runs the pinned weaver from e2e-tools.lock on weaver/registry (#710): `weaver registry check` passes, a typo'd
# ABOUTME: ref fails it, and the resolved HTTP SERVER span carries session.id and witb.guard.decision with its six members.
# SUITE: e2e
# E2E TIER: tools (no cluster, no AWS: the pinned weaver, which fetches OTel semconv v1.37.0 from GitHub)
"""The check .github/workflows/weaver-registry-check.yml runs, run by the gate's E2E command as well.

The workflow only runs on GitHub, and a hecaton run had no weaver binary, so #559 could not check the registry and
filed #710. weaver is now in verify/e2e-tools.lock at the workflow's version and SHA-256 (test_e2e_tools_tier.py holds
that), and this test runs it:

  - `weaver registry check --registry weaver/registry/` exits 0, which resolves every ref against the upstream
    semantic conventions manifest.yaml pins and runs weaver's built-in policies;
  - the same check on a copy whose witb.guard.decision ref is misspelt exits non-zero, so a pass means something;
  - `weaver registry resolve` puts session.id (a string, from semconv) and witb.guard.decision (an enum of
    input_blocklist, input_classifier, topic, rate_limit, budget and output_redacted) on span.witb.guard_proxy.http.

The registry's lockstep with proxy.py is test_weaver_registry_lockstep.py's, offline. Fails when WEAVER is unset or is
not the lock's version: run verify/run-e2e-tools.sh, which fetches it and sets WEAVER.
"""
from __future__ import annotations

import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

import yaml

REPO = pathlib.Path(__file__).resolve().parent.parent
REGISTRY = REPO / "weaver/registry"
LOCK = REPO / "verify/e2e-tools.lock"
DECISIONS = ["input_blocklist", "input_classifier", "topic", "rate_limit", "budget", "output_redacted"]

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"\n        {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def done() -> None:
    if failures:
        print(f"\nFAILED: {len(failures)} check(s)")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    print("\nweaver registry check passes on the guard-proxy span contract.")


weaver = os.environ.get("WEAVER", "")
pinned = re.search(r"^weaver\s+v(\S+)", LOCK.read_text(), re.M)
if not weaver or not os.access(weaver, os.X_OK):
    print(f"WEAVER is {weaver!r}, not an executable weaver: run verify/run-e2e-tools.sh, which fetches the pinned one",
          file=sys.stderr)
    sys.exit(1)
version = subprocess.run([weaver, "--version"], capture_output=True, text=True, timeout=60)
check(f"WEAVER is the weaver e2e-tools.lock pins ({version.stdout.strip()})",
      bool(pinned) and version.returncode == 0 and version.stdout.split() == ["weaver", pinned.group(1)],
      version.stdout + version.stderr)


def registry_check(registry: pathlib.Path) -> subprocess.CompletedProcess:
    return subprocess.run([weaver, "registry", "check", "--registry", str(registry)],
                          capture_output=True, text=True, timeout=600)


print("== weaver registry check ==")
r = registry_check(REGISTRY)
check(f"weaver registry check passes on weaver/registry (exit {r.returncode})", r.returncode == 0,
      (r.stdout + r.stderr)[-3000:])

with tempfile.TemporaryDirectory() as t:
    bad = pathlib.Path(t) / "registry"
    shutil.copytree(REGISTRY, bad)
    spans = bad / "guard-proxy-spans.yaml"
    text = spans.read_text()
    check("the copy has the witb.guard.decision ref to misspell", "- ref: witb.guard.decision\n" in text)
    spans.write_text(text.replace("- ref: witb.guard.decision\n", "- ref: witb.guard.decisoin\n"))
    r = registry_check(bad)
    check(f"a misspelt ref fails the check (exit {r.returncode})", r.returncode != 0, (r.stdout + r.stderr)[-3000:])

print("== the resolved HTTP SERVER span ==")
with tempfile.TemporaryDirectory() as t:
    out = pathlib.Path(t) / "resolved.yaml"
    r = subprocess.run([weaver, "registry", "resolve", "--registry", str(REGISTRY), "--output", str(out)],
                       capture_output=True, text=True, timeout=600)
    check(f"weaver registry resolve succeeds (exit {r.returncode})", r.returncode == 0 and out.is_file(),
          (r.stdout + r.stderr)[-3000:])
    resolved = yaml.safe_load(out.read_text()) if out.is_file() else {}
groups = {g["id"]: g for g in (resolved or {}).get("groups", [])}
http = {a["name"]: a for a in groups.get("span.witb.guard_proxy.http", {}).get("attributes", [])}
check(f"span.witb.guard_proxy.http resolves with its attributes ({sorted(http)})",
      {"http.request.method", "url.path", "http.response.status_code", "session.id", "witb.guard.decision"}
      <= set(http))
session = http.get("session.id", {})
check("session.id resolves to semconv's string attribute, conditionally required",
      session.get("type") == "string" and "conditionally_required" in (session.get("requirement_level") or {}),
      str(session))
decision = http.get("witb.guard.decision", {})
members = [m.get("value") for m in (decision.get("type") or {}).get("members", [])] \
    if isinstance(decision.get("type"), dict) else []
check(f"witb.guard.decision resolves to an enum of the six guards ({members})", sorted(members) == sorted(DECISIONS))
check("witb.guard.decision is conditionally required",
      "conditionally_required" in (decision.get("requirement_level") or {}), str(decision.get("requirement_level")))

done()
