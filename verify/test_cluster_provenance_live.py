# ABOUTME: Live check of #979's provenance finding (#1043): asks AWS whether each roster cluster was built from aws/cluster,
# ABOUTME: and fails unless both read as built, import is the choice, and no register entry calls either unmanaged.
# SUITE: e2e
"""Needs python3, PyYAML, the aws CLI and credentials for fleet.sh's WIB_DEFAULT_ACCOUNT profile (accen-dev), where
roster.tsv says every roster cluster lives. A missing tool, profile or answer fails the test; nothing is skipped.

For each community and admin row of infra/terraform/fleet/roster.tsv (watch-it-burn-community and
watch-it-burn-private), it runs

    python3 infra/terraform/fleet/import-state.py provenance <WIB_DEFAULT_ACCOUNT> <name> --region <WIB_REGION>

which reads the cluster, its node groups and its VPC in AWS, and fails unless the command exits 0 with every mark
held, `verdict: built from infra/terraform/aws/cluster`, `choice: import`, `register: no entry covers it` and
`follows: yes`. That is #979's choice for both, made in docs/floor.md ("Rebuilding a lost state"). A cluster rebuilt
some other way, a mark the root stops leaving, or a register entry that comes to cover either, fails here.
verify/test_cluster_provenance.py holds the same command offline against a recording of these answers.

It only reads: describe-cluster, list-nodegroups, describe-vpcs and get-caller-identity. Every call names --profile
and --region.
"""
from __future__ import annotations

import pathlib
import re
import shutil
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = REPO / "infra/terraform/fleet/import-state.py"
FLEET_SH = REPO / "infra/terraform/fleet/fleet.sh"
ROSTER = REPO / "infra/terraform/fleet/roster.tsv"
failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"\n{detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def setting(var: str) -> str:
    m = re.search(rf'^{var}="\$\{{{var}:-([^}}]*)\}}"$', FLEET_SH.read_text(encoding="utf-8"), re.M)
    if not m or not m.group(1):
        sys.exit(f"FAIL: {FLEET_SH.relative_to(REPO)} has no {var}=\"${{{var}:-...}}\" default to read")
    return m.group(1)


if shutil.which("aws") is None:
    sys.exit("FAIL: the aws CLI is not on PATH; this check asks AWS and cannot run without it")
profile, region = setting("WIB_DEFAULT_ACCOUNT"), setting("WIB_REGION")
if "Every roster cluster lives in WIB_DEFAULT_ACCOUNT" not in ROSTER.read_text(encoding="utf-8"):
    sys.exit(f"FAIL: anchor missing: {ROSTER.relative_to(REPO)} no longer says every roster cluster lives in "
             "WIB_DEFAULT_ACCOUNT, which is where this check looks for them")
names = [ln.split("|")[0] for ln in ROSTER.read_text(encoding="utf-8").splitlines()
         if ln.strip() and not ln.startswith("#") and ln.split("|")[1:2] in (["community"], ["admin"])]
check("roster.tsv names watch-it-burn-community and watch-it-burn-private",
      sorted(names) == ["watch-it-burn-community", "watch-it-burn-private"], f"names {names}")

print(f"Provenance from AWS ({profile}, {region}):")
for name in names:
    p = subprocess.run([sys.executable, str(SCRIPT), "provenance", profile, name, "--region", region],
                       capture_output=True, text=True, timeout=300)
    out = p.stdout + p.stderr
    print("\n".join(f"    {ln}" for ln in out.strip().splitlines()))
    lines = dict(ln.split(": ", 1) for ln in p.stdout.splitlines() if re.match(r"^(verdict|choice|register|follows): ", ln))
    check(f"{name}: provenance exits 0", p.returncode == 0, f"exit {p.returncode}")
    check(f"{name}: all seven marks held, none missing",
          sum(ln.startswith("  held ") for ln in p.stdout.splitlines()) == 7 and "MISSING" not in p.stdout)
    check(f"{name}: built from infra/terraform/aws/cluster",
          lines.get("verdict") == "built from infra/terraform/aws/cluster")
    check(f"{name}: so it is imported, not registered", lines.get("choice") == "import")
    check(f"{name}: and no register entry covers it", lines.get("register") == "no entry covers it")
    check(f"{name}: the choice follows", lines.get("follows") == "yes")

if failures:
    print(f"\nFAIL: {len(failures)} check(s): " + "; ".join(failures))
    sys.exit(1)
print("\nPASS: cluster provenance, live")
