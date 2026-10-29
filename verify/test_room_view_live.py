# ABOUTME: Live check that the room's read-only Datadog view (#665) is built in Whitney's sandbox org as this repo
# ABOUTME: defines it, shared open and unexpired, and that its public URL answers a phone with no login. Read-only.
# SUITE: e2e (needs AWS access to watch-it-burn/datadog, the live sandbox org, and infra/datadog-room/share.json)
#
# The offline half (test_room_view.py) proves the definition is fenced to burritobot-public. This proves it is LIVE:
# `room_view.py --check` compares the dashboard's queries with room_view.yaml, reads the public share (open, active,
# nothing selectable, expiring no later than the repo says) and fetches the public URL with no credentials. Until
# Whitney builds the view (room_view.py --apply, which writes share.json), it fails and says so.
#
# The account and region are explicit, never the ambient AWS default: WIB_DEFAULT_ACCOUNT (default accen-dev, where
# watch-it-burn/datadog lives) and WIB_REGION (default us-west-2), the same defaults fleet.sh uses. Nothing here
# skips: no AWS, no secret, no org or no share is a failure with the reason printed.
import os
import pathlib
import shutil
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "infra" / "datadog-room"))
import room_view as rv  # noqa: E402

if shutil.which("aws") is None:
    print("FAIL: the aws CLI is not on PATH, so the sandbox org keys cannot be read", file=sys.stderr)
    sys.exit(1)

profile = os.environ.get("WIB_DEFAULT_ACCOUNT", "accen-dev")
region = os.environ.get("WIB_REGION", "us-west-2")
print(f"== the room's read-only view (keys from watch-it-burn/datadog as {profile} in {region}) ==")
rc = rv.main(["--profile", profile, "--region", region, "--check"])
if rc != 0:
    print("FAIL: the sandbox org does not hold the room view this repo defines. Build it with\n"
          "      WIB_ROOM_VIEW_APP_KEY=<Whitney's write key> python3 infra/datadog-room/room_view.py "
          f"--profile {profile} --region {region} --apply\n"
          "      and commit infra/datadog-room/share.json", file=sys.stderr)
    sys.exit(1)
print("The room view is live, scoped to burritobot-public, and opens with no login.")
