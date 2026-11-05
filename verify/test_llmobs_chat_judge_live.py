# ABOUTME: Live judge of #746's five checks (#771): the newest BurritoBot /chat that called read_support_ticket and
# ABOUTME: deploy_app, read from the LLM Observability spans API in Whitney's sandbox org with the read-only pair. GETs only.
# SUITE: e2e (needs AWS access to watch-it-burn/datadog, and a BurritoBot /chat on either KubeCon cluster in the window)
"""The live half of #771. The offline half is test_llmobs_chat_judge.py, which judges a recorded payload.

Whitney's done-when list on #746, read on a live trace: one root row per chat; the prompt and the final reply on it;
read_support_ticket and deploy_app under it; a duration covering the whole chat; tokens and an estimated cost, with
no cost_estimate_status:skipped_tokens_missing. verify/llmobs_chat_judge.py holds the checks and says which fields of
the spans API each one reads.

The pair is read as WIB_DEFAULT_ACCOUNT (default accen-dev) in WIB_REGION (default us-west-2), as
test_datadog_sandbox_live.py and test_dd_traces_live.py read it; a dispatched run sources $HECATON_CLUSTER_ENV
first. WIB_LLMOBS_JUDGE_MINUTES (default 1440) is the window. Drive one chat with the HC-666 support-ticket prompt on
either KubeCon bot within it first. Nothing skips: no AWS, a refused read (the 403 names the permission) or no /chat
in the window is a FAIL with the reason.

Usage: [WIB_DEFAULT_ACCOUNT=accen-dev] [WIB_REGION=us-west-2] [WIB_LLMOBS_JUDGE_MINUTES=1440] \
           python3 verify/test_llmobs_chat_judge_live.py
"""
import os
import pathlib
import shutil
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import llmobs_chat_judge as judge  # noqa: E402

if shutil.which("aws") is None:
    print("FAIL: the aws CLI is not on PATH, so watch-it-burn/datadog's read pair cannot be read", file=sys.stderr)
    sys.exit(1)

profile = os.environ.get("WIB_DEFAULT_ACCOUNT", "accen-dev")
region = os.environ.get("WIB_REGION", "us-west-2")
minutes = os.environ.get("WIB_LLMOBS_JUDGE_MINUTES", "1440")
print(f"== #746's five checks on the newest BurritoBot /chat in the sandbox org, as {profile} in {region}, "
      f"last {minutes} minutes ==")
if judge.main(["--profile", profile, "--region", region, "--minutes", minutes]) != 0:
    print("FAIL: the newest BurritoBot /chat does not meet #746's five checks in Agent Observability (each FAIL "
          "above names the check and why)", file=sys.stderr)
    sys.exit(1)
print("The newest BurritoBot /chat meets #746's five checks in Agent Observability.")
