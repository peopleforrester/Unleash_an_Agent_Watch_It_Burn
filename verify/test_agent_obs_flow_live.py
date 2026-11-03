# ABOUTME: Live check of #783's read-back criterion (#813): a fresh chat on each KubeCon bot shows up in Agent
# ABOUTME: Observability under its own session, read back through the Datadog LLM Observability API.
# SUITE: e2e (needs AWS access to watch-it-burn/datadog, both KubeCon bots answering on the public internet, and Datadog)
"""The live half of #813. The offline half is test_agent_obs_flow.py, which runs the same code against fakes.

It runs `verify/agent_obs_flow.py chat --own-session` on both KubeCon bots: attackme.burritobot.co (the room's, on
burritobot-public) and burritobot-private.burritobot.co (the presenters', on burritobot-private). Each gets one
fresh chat, "What are your hours?" with the probe marker so the room's feed skips it, under a session id of its own.
Then the LLM Observability spans API is polled for ml_app:burritobot spans on that bot's k8s.cluster.name tagged
with that session, for up to WIB_AO_WAIT seconds (default 600; Datadog documents a 3 to 5 minute delay). It passes
only when both chats' own spans are read back, and prints their trace ids. Another visitor's chat on the same
cluster does not count, so a busy room cannot hide a broken flow.

It fails, never skips: no aws CLI, an unreadable watch-it-burn/datadog (no session, a refused secret), a Datadog
refusal (the 403 names the endpoint), a bot that does not answer, a cluster that sends nothing (#783's symptom), and
a cluster whose spans arrive without the chat's session are each a FAIL with the reason.

What it spends: two model calls, one per bot, about a cent of Bedrock in all, which counts on each bot's /cost until
the counter is reset (run-of-show, "Reset the community bot"). It changes nothing on either cluster.

The pair is read as WIB_DEFAULT_ACCOUNT (default accen-dev) in WIB_REGION (default us-west-2), as
test_dd_traces_live.py reads it; a dispatched run sources $HECATON_CLUSTER_ENV first.

Usage: [WIB_DEFAULT_ACCOUNT=accen-dev] [WIB_REGION=us-west-2] [WIB_AO_WAIT=600] python3 verify/test_agent_obs_flow_live.py
"""
import os
import pathlib
import shutil
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import agent_obs_flow as af  # noqa: E402

if shutil.which("aws") is None:
    print("FAIL: the aws CLI is not on PATH, so watch-it-burn/datadog's read pair cannot be read", file=sys.stderr)
    sys.exit(1)

profile = os.environ.get("WIB_DEFAULT_ACCOUNT", "accen-dev")
region = os.environ.get("WIB_REGION", "us-west-2")
wait = os.environ.get("WIB_AO_WAIT", "600")
print(f"== a fresh chat on each KubeCon bot, read back from Agent Observability as {profile} in {region} ==")
print(f"   bots: {', '.join(f'{h} ({af.cluster_for(h)})' for h in af.DEFAULT_HOSTS)}; waiting up to {wait}s each")
try:
    rc = af.main(["chat", "--profile", profile, "--region", region, "--wait", wait, "--own-session"])
except (RuntimeError, OSError) as e:  # no session, a refused secret, a 403 (named), Datadog unreachable
    print(f"FAIL: Datadog could not be read: {e}", file=sys.stderr)
    sys.exit(1)
if rc != 0:
    print("FAIL: a fresh chat did not show up in Agent Observability on every cluster (each FAIL line above names "
          "the bot and why)", file=sys.stderr)
    sys.exit(1)
print("A fresh chat on burritobot-public and on burritobot-private each showed up in Agent Observability under its "
      "own session, read back through the Datadog API.")
