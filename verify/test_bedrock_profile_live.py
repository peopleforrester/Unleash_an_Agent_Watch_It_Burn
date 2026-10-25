# ABOUTME: Live check that the CONTEXT cluster's BurritoBot answers through its own tagged Bedrock application
# ABOUTME: profile (#513, #562): profiles and tags, live ModelConfigs, the rendered agent config, one chat turn.
# SUITE: e2e (needs kubectl, the aws CLI, CONTEXT and credentials for the cluster's account; spends one chat turn)
#
# The offline half (test_bedrock_profile_check.py) proves the judges fail on a cluster that still calls the system
# id. This runs bedrock_profile_check.py for real. The cluster is CONTEXT, never the current-context; its name is
# read from CONTEXT when that is an EKS cluster ARN, else WIB_CLUSTER names it. The account and region are
# WIB_DEFAULT_ACCOUNT (default accen-dev) and WIB_REGION (default us-west-2), the defaults fleet.sh uses.
# Nothing here skips: no CONTEXT, no tool or no credentials is a failure with the reason printed.
import importlib.util
import os
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("bedrock_profile_check", REPO / "verify" / "bedrock_profile_check.py")
bpc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bpc)

context = os.environ.get("CONTEXT", "")
if not context:
    print("FAIL: CONTEXT is not set: name the kube-context of the attendee cluster to check", file=sys.stderr)
    sys.exit(1)
argv = ["--context", context, "--profile", os.environ.get("WIB_DEFAULT_ACCOUNT", "accen-dev"),
        "--region", os.environ.get("WIB_REGION", "us-west-2"), "--namespace", os.environ.get("NAMESPACE", "agent")]
if os.environ.get("WIB_CLUSTER"):
    argv += ["--cluster", os.environ["WIB_CLUSTER"]]
rc = bpc.main(argv)
if rc != 0:
    print(f"FAIL: the agent on {context} is not shown answering through its tagged application profile (exit {rc}); "
          "see the FAIL lines above", file=sys.stderr)
    sys.exit(1)
