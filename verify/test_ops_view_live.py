# ABOUTME: Live check that the shared ops view (#308) reads all three of its sources: provisioning claims, the apex
# ABOUTME: routing table with each console's /cost, and the instructor org. Read-only. Fails when any is unreachable.
# SUITE: e2e (needs the provisioning admin token, AWS access to watch-it-burn/datadog, and the network)
#
# The offline half (test_ops_view.py) proves the join against fakes. This proves the fakes are the real shapes:
# the export CSV's header, roster.json, the scalar query API's response for the leaderboard's own queries. It runs
# `fleet.sh ops --json` the way a presenter does, so the token is resolved the normal way (railway login, the
# secret store, or WIB_ADMIN_TOKEN) and the account and region are fleet.sh's explicit defaults, WIB_DEFAULT_ACCOUNT
# and WIB_REGION. Every source is required: one that cannot be read is a failure with its reason printed.
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

REPO = pathlib.Path(__file__).resolve().parents[1]
FLEET = REPO / "infra/terraform/fleet/fleet.sh"

if shutil.which("aws") is None:
    print("FAIL: the aws CLI is not on PATH, so the instructor org keys cannot be read", file=sys.stderr)
    sys.exit(1)

page = pathlib.Path(tempfile.mkdtemp()) / "ops-view.html"
r = subprocess.run(["bash", str(FLEET), "ops", "--json"], capture_output=True, text=True, timeout=300,
                   env={**os.environ, "WIB_OPS_HTML": str(page)})
if r.returncode == 1 and not r.stdout.strip():
    print(f"FAIL: fleet.sh ops did not start:\n{r.stderr.strip()}", file=sys.stderr)
    sys.exit(1)
try:
    doc = json.loads(r.stdout)
except ValueError:
    print(f"FAIL: fleet.sh ops --json did not print JSON (exit {r.returncode}):\n{r.stdout[:500]}\n{r.stderr[-500:]}",
          file=sys.stderr)
    sys.exit(1)

print(f"== ops view at {doc['at']} ==")
print(f"  summary: {doc['summary']}")
for src, why in doc["errors"].items():
    print(f"  UNAVAILABLE {src}: {why}", file=sys.stderr)
if doc["errors"] or r.returncode != 0:
    print("FAIL: the ops view could not read every source; see above", file=sys.stderr)
    sys.exit(1)
if not page.exists():
    print("FAIL: fleet.sh ops wrote no HTML page", file=sys.stderr)
    sys.exit(1)
print(f"The ops view read claims, routes and the instructor org: {len(doc['rows'])} clusters.")
