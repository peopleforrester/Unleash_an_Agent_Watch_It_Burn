# ABOUTME: Live check that the workshop-agent's pinned Bedrock model answers in the delivery account and region,
# ABOUTME: is Active through the delivery date and has room-sized quota (#453). Spends one ~10-token Converse call.
# SUITE: e2e (needs the aws CLI and credentials for the delivery account)
#
# The offline half (test_model_pin_check.py) proves the judges fail on a bad pin. This runs the check for real.
# The account and region are explicit, never the ambient AWS default: WIB_DEFAULT_ACCOUNT (default accen-dev,
# where every roster cluster lives) and WIB_REGION (default us-west-2), the same defaults fleet.sh uses.
# Nothing here skips: no aws CLI or no credentials is a failure with the reason printed.
import importlib.util
import os
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("model_pin_check", REPO / "verify" / "model_pin_check.py")
mpc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mpc)

profile = os.environ.get("WIB_DEFAULT_ACCOUNT", "accen-dev")
region = os.environ.get("WIB_REGION", "us-west-2")
rc = mpc.main(["--profile", profile, "--region", region])
if rc != 0:
    print(f"FAIL: the pinned model is not fit to go on stage as {profile} in {region} (exit {rc}); "
          "see the FAIL lines above", file=sys.stderr)
    sys.exit(1)
