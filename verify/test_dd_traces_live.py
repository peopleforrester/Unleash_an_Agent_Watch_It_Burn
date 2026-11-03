# ABOUTME: Live check of #759: the newest ml_app:burritobot trace is readable from Whitney's sandbox org with
# ABOUTME: watch-it-burn/datadog's read-only pair, as a dispatched run reads it. Read-only, GETs only.
# SUITE: e2e (needs AWS access to watch-it-burn/datadog, and a BurritoBot /chat on either KubeCon cluster in the last day)
"""The live half of #759. The offline half is test_dd_traces.py.

The pair is read as WIB_DEFAULT_ACCOUNT (default accen-dev) in WIB_REGION (default us-west-2), as
test_datadog_sandbox_live.py reads it; a dispatched run sources $HECATON_CLUSTER_ENV first. WIB_DD_TRACES_MINUTES
(default 1440) is the window: drive one /chat on either KubeCon cluster within it first. Nothing skips: no AWS, a
refused scope (named) or no trace in the window is a FAIL with the reason.
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
print("A BurritoBot trace and its APM spans were read from the sandbox org with the read-only pair.")
