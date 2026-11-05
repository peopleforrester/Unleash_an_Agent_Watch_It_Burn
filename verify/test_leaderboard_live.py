# ABOUTME: Live check that the challenge leaderboard is applied to the instructor Datadog org with this repo's table
# ABOUTME: and that every column fills for a cluster walked through challenges 1 to 6 (#489, #862). Read-only.
# SUITE: e2e (needs AWS access to watch-it-burn/datadog, the live instructor Datadog org with the leaderboard applied, and a cluster walked through challenges 1 to 6 in the last 4 hours)
#
# test_leaderboard.py holds every column to the code that emits its signal, offline. test_fleet_monitors_live.py
# proves the leaderboard is loaded, and its --data step reads the fleet dashboard only, because the leaderboard is
# blank until the room plays. This is the step for after the room plays: `fleet_monitors.py --board`, which finds
# the leaderboard in the org, fails if its table differs from leaderboard.yaml, sends the table's whole request in
# one scalar query (the way query_table joins metrics, logs and spans on kube_cluster_name), and fails on any column
# that is not filled for a named cluster over the widget's 4 hours: green under its conditional format, or a bill
# above 0.
#
# The clusters are WIB_LEADERBOARD_CLUSTERS (default burritobot-private, the KubeCon cluster with Falco; column 3
# never fills on the Community cluster, which has none). Each must have been walked through challenges 1 to 6, with
# the fix installed and the attack re-run for 5 and 6, within 4 hours before this runs. The account and region are
# explicit, WIB_DEFAULT_ACCOUNT (default accen-dev) and WIB_REGION (default us-west-2), as in fleet.sh. Nothing here
# skips: no AWS, no secret, no leaderboard in the org or a blank cell is a failure with the reason printed.
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
clusters = [c.strip() for c in os.environ.get("WIB_LEADERBOARD_CLUSTERS", "burritobot-private").split(",")
            if c.strip()]
if not clusters:
    print("FAIL: WIB_LEADERBOARD_CLUSTERS names no cluster", file=sys.stderr)
    sys.exit(1)
print(f"== the challenge leaderboard fills for {', '.join(clusters)} ({fm.SECRET_ID} as {profile} in {region}) ==")
rc = fm.main(["--profile", profile, "--region", region, "--board", *[a for c in clusters for a in ("--cluster", c)]])
if rc != 0:
    print("FAIL: the challenge leaderboard is not in the instructor org as this repo defines it, or a column is blank\n"
          "      for a named cluster (each MISSING, DRIFT or BLANK line above). MISSING or DRIFT: apply it with\n"
          "      WIB_FLEET_MONITORS_APP_KEY=<key> infra/terraform/fleet/fleet.sh monitors --apply --session START/END.\n"
          "      BLANK: walk that cluster through the challenge inside the last 4 hours and re-run; a column that stays\n"
          "      blank after that is a wrong name, fixed in leaderboard.yaml and verify/test_leaderboard.py together.",
          file=sys.stderr)
    sys.exit(1)
print(f"The challenge leaderboard is in the instructor org as leaderboard.yaml defines it, and every column is\n"
      f"filled for {', '.join(clusters)}.")
