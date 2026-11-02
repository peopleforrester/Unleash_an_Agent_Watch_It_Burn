# ABOUTME: Holds verify/lab_live_clusters.py, the clusters test_lab_pipeline_live.py runs against (#587), to the names
# ABOUTME: infra/datadog-cluster-identity.sh writes and to what harvest pass 6 makes a row of.
"""Offline. The live check reads cluster-identity's cluster-name and datadog-cluster-name off the cluster and asks
lab_live_clusters.kind() whether it may run there, and whether pass 6 should give it a row. This runs the identity
script against a kubectl shim for each roster name, so a rename there that the live check does not follow fails here
rather than on the cluster.
"""
from __future__ import annotations

import os
import pathlib
import re
import subprocess
import sys
import tempfile

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "verify"))
import lab_live_clusters  # noqa: E402

IDENTITY = REPO / "infra/datadog-cluster-identity.sh"
LIVE = (REPO / "verify/test_lab_pipeline_live.py").read_text(encoding="utf-8")
PASS6 = (REPO / "scripts/harvest/06-lab-progress.py").read_text(encoding="utf-8")

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        failures.append(name)
        if detail:
            print(f"        {detail}")


def datadog_name(eks: str) -> str:
    """The datadog-cluster-name the identity script writes for an EKS name, read from its kubectl calls."""
    with tempfile.TemporaryDirectory(dir=REPO / "verify") as d:
        log = pathlib.Path(d) / "calls"
        shim = pathlib.Path(d) / "kubectl"
        shim.write_text(f'#!/usr/bin/env bash\necho "$*" >> "{log}"\n'
                        '[[ "$*" == *apply* ]] && cat >/dev/null\nexit 0\n')
        shim.chmod(0o755)
        env = {**os.environ, "PATH": f"{d}:{os.environ['PATH']}", "CLUSTER_NAME": eks,
               "CONTEXT": f"arn:aws:eks:us-west-2:111122223333:cluster/{eks}"}
        env.pop("WITB_DD_ADMIN_API_KEY", None)
        subprocess.run(["bash", str(IDENTITY)], env=env, capture_output=True, text=True, check=True)
        names = {m.group(1) for line in log.read_text().splitlines()
                 for m in [re.search(r"--from-literal=datadog-cluster-name=(\S+)", line)] if m}
    return names.pop() if len(names) == 1 else f"<{len(names)} names>"


print("== the live check runs on the clusters the identity script names, each as its kind ==")
pass6 = re.compile(re.search(r'STUDENT_CLUSTER = re\.compile\(r"([^"]+)"\)', PASS6).group(1))
for eks, want in (("watch-it-burn-attendee-007", "attendee"), ("watch-it-burn-attendee-042", "attendee"),
                  ("watch-it-burn-community", "instructor"), ("watch-it-burn-private", "instructor"),
                  ("watch-it-burn-community-b01", "instructor"), ("watch-it-burn-private-b02", "instructor"),
                  ("watch-it-burn-whitney-admin", ""), ("watch-it-burn-alpha", "")):
    dd = datadog_name(eks)
    got = lab_live_clusters.kind(eks, dd)
    check(f"{eks} ({dd}) is {want or 'refused'}", got == want, f"kind() said {got!r}")
    if want:
        # attendee means pass 6 writes it a row; instructor means pass 6 leaves it out, which the live check asserts.
        check(f"  and pass 6 {'makes a row of' if want == 'attendee' else 'leaves out'} {dd}",
              bool(pass6.search(dd)) == (want == "attendee"))

print("== a name pair the identity script would never write is refused ==")
for eks, dd in (("watch-it-burn-attendee-007", "burritobot-attendee-008"),
                ("watch-it-burn-attendee-007", "burritobot-private"),
                ("watch-it-burn-community", "burritobot-private"),
                ("watch-it-burn-private", "burritobot-attendee-001"),
                ("other-attendee-007", "burritobot-attendee-007"),
                ("", "")):
    check(f"{eks or '(none)'} with {dd or '(none)'}", lab_live_clusters.kind(eks, dd) == "")

print("== the live check asks this module, and holds an instructor cluster to one org ==")
check("test_lab_pipeline_live.py decides the cluster with lab_live_clusters.kind",
      "lab_live_clusters.kind(CLUSTER, DD_CLUSTER)" in LIVE)
check("on an instructor cluster it requires the cluster's own key to be the instructor org's",
      bool(re.search(r'if KIND == "instructor":\n(?:[^\n]*\n){0,3}?[^\n]*\bONE_ORG\)', LIVE)))
check("and pass 6 gives an attendee cluster a row and an instructor cluster none",
      'if KIND == "attendee":' in LIVE and "csv_path.exists() and not rows" in LIVE)

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All lab live-cluster checks passed.")
