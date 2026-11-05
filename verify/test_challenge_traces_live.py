# ABOUTME: Live check of #760: the newest ml_app:burritobot trace of each KubeCon challenge in Whitney's sandbox org has
# ABOUTME: the shape verify/challenge-trace-shapes.yaml writes down. GETs only, with watch-it-burn/datadog's read-only pair.
# SUITE: e2e (needs AWS access to watch-it-burn/datadog, and each challenge played on a KubeCon cluster in the window)
"""The live half of #760. The offline half is test_challenge_traces.py.

The pair is read as WIB_DEFAULT_ACCOUNT (default accen-dev) in WIB_REGION (default us-west-2), as
test_dd_traces_live.py reads it; a dispatched run sources $HECATON_CLUSTER_ENV first. WIB_CHALLENGE_TRACES_HOURS
(default 24) is the window, and WIB_CHALLENGE_TRACES_TAG, when set, narrows it to one cluster
(k8s.cluster.name:burritobot-private). Nothing skips: no AWS, a refused key, another org or any challenge whose
newest trace is not the shape is a FAIL, each with its reason and its trace link.
"""
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import challenge_traces  # noqa: E402

profile = os.environ.get("WIB_DEFAULT_ACCOUNT", "accen-dev")
region = os.environ.get("WIB_REGION", "us-west-2")
hours = os.environ.get("WIB_CHALLENGE_TRACES_HOURS", "24")
tag = os.environ.get("WIB_CHALLENGE_TRACES_TAG", "")
argv = ["--profile", profile, "--region", region, "--hours", hours, *(["--tag", tag] if tag else [])]
print(f"== each challenge's newest ml_app:burritobot trace, as {profile} in {region}, last {hours} h"
      + (f", {tag}" if tag else "") + " ==")
rc = challenge_traces.main(argv)
if rc != 0:
    print("FAIL: " + ("the traces could not be read (reason above)" if rc == 2 else
                      "a challenge's newest trace is not the shape challenge-trace-shapes.yaml writes down "
                      "(each FAIL above, with its link)"), file=sys.stderr)
    sys.exit(1)
print("Every challenge's newest trace has its shape.")
