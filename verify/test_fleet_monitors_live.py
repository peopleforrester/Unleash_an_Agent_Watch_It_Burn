# ABOUTME: Live check that the instructor Datadog org holds exactly the fleet monitors and dashboard this
# ABOUTME: repo defines (#267). Read-only. Fails when the org, the keys or AWS are unreachable.
# SUITE: e2e (needs AWS access to watch-it-burn/datadog and the live instructor Datadog org)
#
# The offline half (test_fleet_monitors.py) proves the definitions are right. This proves they are LOADED:
# a monitor that only exists in the repo watches nothing, and "No Monitors" on the Datadog page is exactly
# the state #267 was filed from. It runs `fleet.sh monitors --check`, which compares every monitor's query
# and the dashboard title with the repo and prints each monitor's current state.
#
# The account and region are explicit, never the ambient AWS default: WIB_DEFAULT_ACCOUNT (default
# accen-dev, where the instructor org secret lives) and WIB_REGION (default us-west-2), the same defaults
# fleet.sh uses. Nothing here skips: no AWS, no secret or no org is a failure with the reason printed.
import os
import pathlib
import shutil
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "infra" / "datadog-fleet"))
import fleet_monitors as fm  # noqa: E402

if shutil.which("aws") is None:
    print("FAIL: the aws CLI is not on PATH, so the instructor org keys cannot be read", file=sys.stderr)
    sys.exit(1)

profile = os.environ.get("WIB_DEFAULT_ACCOUNT", "accen-dev")
region = os.environ.get("WIB_REGION", "us-west-2")
print(f"== instructor org fleet monitors ({fm.SECRET_ID} as {profile} in {region}) ==")
rc = fm.main(["--profile", profile, "--region", region, "--check"])
if rc != 0:
    print("FAIL: the instructor org does not hold the fleet monitors this repo defines. Load them with\n"
          "      infra/terraform/fleet/fleet.sh monitors --apply --session START/END", file=sys.stderr)
    sys.exit(1)
print("The instructor org holds every fleet monitor and the fleet dashboard.")
