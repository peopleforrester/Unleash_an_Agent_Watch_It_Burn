# ABOUTME: Live check that the instructor Datadog org holds exactly the fleet monitors and dashboards this
# ABOUTME: repo defines (#267, #307), and that every query returns data for every cluster (#485, #706). Read-only.
# SUITE: e2e (needs AWS access to watch-it-burn/datadog, the live instructor Datadog org, and the clusters shipping with a recent /chat)
#
# The offline half (test_fleet_monitors.py) proves the definitions are right. This proves they are LOADED:
# a monitor that only exists in the repo watches nothing, and "No Monitors" on the Datadog page is exactly
# the state #267 was filed from. It runs `fleet.sh monitors --check`, which compares every monitor's query
# and the dashboard title with the repo and prints each monitor's current state.
#
# Then it proves they are FED, which a loaded monitor on a wrong name is not: it runs `fleet.sh monitors --data`
# for every cluster in WIB_FLEET_CLUSTERS (default burritobot-public,burritobot-private, the two KubeCon
# clusters in Whitney's sandbox org, #629). Every monitor that fires on absence must have a group for each
# cluster in a state other than No Data, every monitor that fires on a rising count must have its signal answer
# for each, and every query on the fleet dashboard must answer for each over its widget's window. The traces
# and spend columns only fill after a chat: drive one /chat on each cluster within 5 minutes before running it.
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
clusters = [c.strip() for c in os.environ.get("WIB_FLEET_CLUSTERS", "burritobot-public,burritobot-private").split(",")
            if c.strip()]
print(f"== instructor org fleet monitors ({fm.SECRET_ID} as {profile} in {region}) ==")
rc = fm.main(["--profile", profile, "--region", region, "--check"])
if rc != 0:
    print("FAIL: the instructor org does not hold the fleet monitors this repo defines. Load them with\n"
          "      WIB_FLEET_MONITORS_APP_KEY=<key> infra/terraform/fleet/fleet.sh monitors --apply --session START/END",
          file=sys.stderr)
    sys.exit(1)
print(f"\n== every query returns data for {', '.join(clusters)} ==")
rc = fm.main(["--profile", profile, "--region", region, "--data", *[a for c in clusters for a in ("--cluster", c)]])
if rc != 0:
    print("FAIL: a fleet monitor or fleet-dashboard query returns nothing for a cluster (each NO DATA line above).\n"
          "      Traces or spend blank: send one /chat on that cluster and re-run within 5 minutes. Anything else\n"
          "      blank is a wrong name, fixed in infra/datadog-fleet/ and verify/test_fleet_monitors.py together.",
          file=sys.stderr)
    sys.exit(1)
print("The instructor org holds every fleet monitor, the fleet dashboard and the challenge leaderboard,\n"
      f"and every monitor and fleet-dashboard query answers for {', '.join(clusters)}.")
