# ABOUTME: Live check of #759: the newest ml_app:burritobot trace is readable from Whitney's sandbox org with
# ABOUTME: watch-it-burn/datadog's pair, as a dispatched run reads it; its key is read-only, new and as made. GETs only.
# SUITE: e2e (needs AWS access to watch-it-burn/datadog, and a BurritoBot /chat on either KubeCon cluster in the last day)
"""The live half of #759. The offline half is test_dd_traces.py.

The pair is read as WIB_DEFAULT_ACCOUNT (default accen-dev) in WIB_REGION (default us-west-2), as
test_datadog_sandbox_live.py reads it; a dispatched run sources $HECATON_CLUSTER_ENV first. WIB_DD_TRACES_MINUTES
(default 1440) is the window: drive one /chat on either KubeCon cluster within it first. Nothing skips: no AWS, a
refused scope (named) or no trace in the window is a FAIL with the reason. The last step is #890's: the pair is a new
credential, made for the secret and neither rotated nor revoked since (dd_traces.py --credential).
"""
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import dd_traces  # noqa: E402

profile = os.environ.get("WIB_DEFAULT_ACCOUNT", "accen-dev")
region = os.environ.get("WIB_REGION", "us-west-2")
minutes = os.environ.get("WIB_DD_TRACES_MINUTES", "1440")
print(f"== the newest ml_app:{dd_traces.ML_APP} trace in the sandbox org, as {profile} in {region}, "
      f"last {minutes} minutes ==")
rc = dd_traces.main(["--profile", profile, "--region", region, "--minutes", minutes, "--traces", "1", "--apm"])
if rc != 0:
    print("FAIL: no BurritoBot trace could be read from the sandbox org (reason above)", file=sys.stderr)
    sys.exit(1)
print("== the pair's application key, as the org lists it ==")
if dd_traces.main(["--profile", profile, "--region", region, "--scopes"]) != 0:
    print("FAIL: the pair's application key is not shown read-only (reason above)", file=sys.stderr)
    sys.exit(1)
print("== the pair is new: made for the secret, not rotated or revoked (#890) ==")
if dd_traces.main(["--profile", profile, "--region", region, "--credential"]) != 0:
    print("FAIL: the pair is not shown to be a new credential left as it was made (reason above)", file=sys.stderr)
    sys.exit(1)
print("A BurritoBot trace and its APM spans were read from the sandbox org with the read-only pair.")
