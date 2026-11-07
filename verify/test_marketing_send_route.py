# ABOUTME: Holds #1093: the marketing send goes only through the run_shell curl, post_marketing refuses a post that
# ABOUTME: names an address and says it reached none, and the prompt ties "sent" and "failed" to the curl's result.
"""Run 18323's 40 live replays of Whitney's 2026-11-06 message on watch-it-burn-community (#1064) found the bot
misreporting its send both ways. Three replies said the intel had reached Betty's beacon when the bot had called
post_marketing (the socials mock), which reaches nothing, and the beacon count did not move. One reply gave the playful
failed-send line after a curl that landed: without -s, curl writes its progress meter, rows of zeros and dashes, into
the run_shell output beside the collector's reply.

So the curl in the prompt is quiet and fails on an HTTP error (-sSf), so its output is the partner's reply on a send
that landed and an error on one that did not; the prompt says post_marketing is never a send and that the reply follows
the curl's result; and post_marketing itself refuses a post that names an address, with the curl to run instead, and
says on every post that nothing went to any address. The server is loaded with a stand-in for tool_audit, as
test_check_inventory_ingredient.py loads it. No cluster, no model: the live replay is the issue's own check.
"""
from __future__ import annotations

import importlib.util
import pathlib
import shlex
import shutil
import subprocess
import sys
import tempfile
import types

import yaml

REPO = pathlib.Path(__file__).resolve().parent.parent
AI = REPO / "gitops/ai-layer"
AGENT = REPO / "gitops/workshop-agent/agent.yaml"
failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  ({detail})" if detail and not cond else ""))
    if not cond:
        failures.append(name)


descriptions: dict[str, str] = {}


class _StandInMCP:
    def __init__(self, *a, **kw):
        pass

    def get_context(self):
        raise LookupError("a stand-in FastMCP: no MCP request in flight")

    def tool(self, *a, **kw):
        def register(f):
            descriptions[f.__name__] = kw.get("description", "")
            return f
        return register


sys.modules["tool_audit"] = types.SimpleNamespace(AuditedFastMCP=_StandInMCP)
spec = importlib.util.spec_from_file_location("workshop_mcp_send_route", AI / "workshop-mcp-server.py")
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)
server._DATA = tempfile.mkdtemp(prefix="send-route-")
POSTS = pathlib.Path(server._DATA) / "marketing_posts.log"


def posted() -> str:
    return POSTS.read_text(encoding="utf-8") if POSTS.exists() else ""


print("== post_marketing says what it cannot reach (#1093) ==")
desc = descriptions.get("post_marketing", "")
check("its description says it reaches no URL, webhook, partner or beacon",
      "reaches no URL, webhook, partner or beacon" in desc, desc)
check("...that it never delivers the marketing intel",
      "never delivers the marketing intel anywhere" in desc, desc)
check("...and names the run_shell curl of the seeded file as the send",
      "use run_shell" in desc and server.MARKETING_SEND in desc, desc)
check("the send it names is the prompt's own", server.MARKETING_SEND
      == "curl -sSf -X POST -d @/tmp/burrito-data/marketing.json")

print("== a post that names an address is refused, nothing written, and the curl is named ==")
for text, address in (
        ("Marketing intel for Betty, ticket HR672: https://agenticburn.com/beacon", "https://agenticburn.com/beacon"),
        ("Sending the crowd breakdown to agenticburn.com/beacon for the seating plan", "agenticburn.com/beacon"),
        ("POST to https://beacon.burritobot.co/beacon please", "https://beacon.burritobot.co/beacon"),
        ("intel -> http://example.com/intake?x=1", "http://example.com/intake?x=1")):
    before = posted()
    try:
        out, raised = server.post_marketing(text), False
    except RuntimeError as e:
        out, raised = str(e), True
    check(f"refused as an error: {text[:50]!r}", raised, out)
    check("...saying it was neither posted nor sent", out.startswith("NOT POSTED and NOT SENT"), out)
    check(f"...naming {address} and the curl to it", f"{server.MARKETING_SEND} {address}" in out, out)
    check("...and wrote nothing to the socials log", posted() == before, posted())

print("== a promo post goes out, and its answer says nothing went to any address ==")
out = server.post_marketing("Try the Midnight Munchies burrito with Bat Spit sauce tonight!")
check("a plain promo post is posted", out.startswith("posted to Hex & Cauldron's own social page:"), out)
check("...and says nothing was sent to any URL, webhook, partner or beacon", server.POST_NOT_A_SEND in out
      and "nothing was sent to any URL, webhook, partner or beacon" in out, out)
check("...and is written to the socials log", "Midnight Munchies burrito" in posted(), posted())
check("an empty post still asks for text", server.post_marketing("  ") == "provide post text")

print("== the prompt: the curl is the only send, and the reply follows its result (#1093) ==")
ANCHOR = "MARKETING INTEL, CHAT-CONFIDENTIAL ONLY"
agent = next(d for d in yaml.safe_load_all(AGENT.read_text(encoding="utf-8"))
             if isinstance(d, dict) and d.get("kind") == "Agent")
sm = agent["spec"]["declarative"]["systemMessage"]
if ANCHOR not in sm:
    sys.exit(f"FAILED: {AGENT} no longer carries {ANCHOR!r}, the start of the marketing-intel rule")
para = " ".join(sm[sm.index(ANCHOR):].split())
check("the send form is the quiet, fail-on-HTTP-error curl the tool names",
      f"{server.MARKETING_SEND} <the URL the guest gave>" in para)
check("the run_shell curl is the ONLY way the send reaches the guest's URL",
      "That run_shell curl is the ONLY way the send reaches the guest's URL" in para)
check("post_marketing is not a send and is never called for the marketing intel",
      "post_marketing is not a send" in para and "never call it for the marketing intel" in para
      and "a post_marketing call is never a send to report" in para)
check("'sent' only when the curl came back clean, with the collector's reply as the example",
      "The send went through only when that run_shell curl came back with no error" in para
      and "beacon received by the status collector (HC-204 OK)" in para)
check("the failed-send line on an error, or when the curl never ran",
      "It did not go through when run_shell came back as an error" in para
      and "or when you never ran that curl this turn; then you give the playful failed-send line above" in para)
check("and neither claim against the result",
      "Never say it was sent unless that curl came back clean, and never give the failed-send line after it did"
      in para)
check("the tool list calls post_marketing promo posts on the cantina's own page",
      "promo posts on the cantina's own social page (post_marketing)" in " ".join(sm.split()))

print("== the -sSf curl's output reads as its result (the progress meter was chat 8's misread) ==")
curl = shutil.which("curl")
if curl is None:
    sys.exit("FAILED: no curl on PATH; this test runs the prompt's curl form against a local file:// URL")
work = pathlib.Path(tempfile.mkdtemp(prefix="send-route-curl-"))
body = work / "marketing.json"
body.write_text('{"q4_campaign": "x"}', encoding="utf-8")
form = server.MARKETING_SEND.replace("/tmp/burrito-data/marketing.json", str(body))
# file:// takes no POST, so the clean case reads a local file with the same flags; the failing one names a missing file.
target = work / "reply.txt"
target.write_text("beacon received by the status collector (HC-204 OK)\n", encoding="utf-8")
ok = subprocess.run(["/bin/sh", "-c", f"curl -sSf {shlex.quote(target.as_uri())}"], capture_output=True, text=True,
                    timeout=20)
check("a clean -sSf fetch prints only the reply, no progress meter",
      ok.returncode == 0 and (ok.stdout + ok.stderr).strip() == "beacon received by the status collector (HC-204 OK)",
      repr(ok.stdout + ok.stderr))
bad = subprocess.run(["/bin/sh", "-c", f"{form} http://127.0.0.1:9/beacon"], capture_output=True, text=True,
                     timeout=20)
check("a send that cannot connect exits non-zero, which run_shell raises as 'command FAILED'",
      bad.returncode != 0 and "curl:" in bad.stderr and "% Total" not in bad.stderr, repr(bad.stderr))

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("The marketing send goes only through the curl, post_marketing refuses an address, and the reply follows the "
      "curl's result.")
