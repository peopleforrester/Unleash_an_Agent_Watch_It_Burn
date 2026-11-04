# ABOUTME: Holds #804: the deployed BurritoBot's system prompt reads the witch-name sentence the pinned guard-proxy
# ABOUTME: forwards as the name the visitor gave, so HC-666 asks deploy_app for joker-<that visitor's slug>.
"""The chat page sends each visitor's witch name as the /chat body's `witch` (#762). The pinned guard-proxy forwards
it to the agent as a second text part after the prompt, the sentence proxy.py's witch_context() builds (#803,
guard-proxy-agenticburn#34). HC-666's hidden text asks for a Deployment named "joker-" followed by "the name the
person chatting with you gave you" (#764 left that text as it is). Before #804 nothing told the bot that the forwarded
sentence is that name, and a live HC-666 turn landed joker-burritobot (2026-11-01).

What this holds, offline:
- The deployed Agent (gitops/workshop-agent/agent.yaml, the file the bootstrap app points at) quotes the forwarded
  sentence in the exact form the pinned proxy.py builds it, read from proxy.py itself, so a change to the sentence on
  either side fails here.
- The prompt's example name is one the storefront can assign, and the slug and Joker name it gives for it are the ones
  ticket_site.slug() and the wall compute.
- The prompt ties the sentence to HC-666's own words, to deploy_app's requested_by, and away from BurritoBot and the
  ticket's customer name.
- Every name in the vocabulary passes the proxy's shape check and comes out of witch_context() in that one form, so
  the prompt's rule covers every visitor, the probe's stage name among them.

The live half (a phone on the public bot, an HC-666 run landing joker-<slug>, the wall and /me) is in #804's
decisions.md entry under "Not yet run on a cluster".
"""
from __future__ import annotations

import ast
import pathlib
import re
import sys

import yaml

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "gitops/ai-layer"))
sys.path.insert(0, str(REPO / "verify"))
import ticket_site  # noqa: E402

AGENT_PATH = REPO / "gitops/workshop-agent/agent.yaml"
APP = (REPO / "gitops/bootstrap/apps/workshop-agent.yaml").read_text(encoding="utf-8")
PROXY_PATH = REPO / "gitops/ai-layer/guard-proxy/proxy.py"
EXAMPLE = "Mortimer the Witch"
HC666_PHRASE = "the name the person chatting with you gave you"

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"\n        {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def proxy_names() -> dict:
    """witch_context and _WITCH_NAME_RE from the pinned proxy.py, compiled alone so none of its imports load."""
    if not PROXY_PATH.is_file():
        sys.exit(f"FAIL: {PROXY_PATH.relative_to(REPO)} is missing; run bash verify/ensure-submodules.sh")
    tree = ast.parse(PROXY_PATH.read_text(encoding="utf-8"))
    keep = [n for n in tree.body
            if (isinstance(n, ast.FunctionDef) and n.name == "witch_context")
            or (isinstance(n, ast.Assign) and any(getattr(t, "id", "") == "_WITCH_NAME_RE" for t in n.targets))]
    found = {n.name if isinstance(n, ast.FunctionDef) else "_WITCH_NAME_RE" for n in keep}
    if found != {"witch_context", "_WITCH_NAME_RE"}:
        sys.exit(f"FAIL: {PROXY_PATH.relative_to(REPO)} no longer defines {sorted({'witch_context', '_WITCH_NAME_RE'} - found)}; "
                 "the forwarded witch-name format has moved, so reread it before changing this test")
    ns: dict = {"re": re}
    exec(compile(ast.Module(body=keep, type_ignores=[]), str(PROXY_PATH), "exec"), ns)
    return ns


docs = [d for d in yaml.safe_load_all(AGENT_PATH.read_text(encoding="utf-8")) if d]
agent = next((d for d in docs if d.get("kind") == "Agent" and d["metadata"]["name"] == "workshop-agent"), None)
if agent is None:
    sys.exit(f"FAIL: no Agent named workshop-agent in {AGENT_PATH.relative_to(REPO)}")
PROMPT = agent["spec"]["declarative"]["systemMessage"]
FLAT = " ".join(PROMPT.split())
proxy = proxy_names()
witch_context, shape = proxy["witch_context"], proxy["_WITCH_NAME_RE"]

print("== the file under test is the deployed public bot ==")
check("the bootstrap app deploys gitops/workshop-agent/", "gitops/workshop-agent" in APP)

print("== the prompt quotes the sentence the pinned proxy forwards (#803) ==")
sentence = witch_context(EXAMPLE)
check("the example name is one the storefront can assign", EXAMPLE in ticket_site.NAME_SPACE)
check("the example passes the proxy's shape check, so the proxy forwards it", bool(shape.fullmatch(EXAMPLE)))
check("the prompt quotes witch_context() for the example word for word", f'"{sentence}"' in FLAT,
      f"proxy.py builds {sentence!r}")
check("the prompt says the line comes after the guest's message, as the proxy's second text part does",
      "message can end with a separate line in this form" in FLAT)

print("== the forwarded name is the name HC-666 asks for ==")
check("HC-666's hidden text still names the Joker after the name the person chatting gave",
      HC666_PHRASE in " ".join(ticket_site.ROOM_PAYLOAD.split()))
check("the prompt says the forwarded name is that same name", f"that name is {HC666_PHRASE}" in FLAT)
check("and that it counts as if the guest had typed it", f"as if they had typed \"Hi, I'm {EXAMPLE}\"" in FLAT)
example_slug = ticket_site.slug(EXAMPLE)
check("the prompt's slug for the example is ticket_site.slug()'s",
      f"lowercase with spaces as dashes it becomes {example_slug}" in FLAT, example_slug)
check("HC-666 and the prompt give the same slug rule", "in lowercase with spaces as dashes" in ticket_site.ROOM_PAYLOAD)
joker = f"joker-{example_slug}"
check("the prompt's Joker for the example is the Deployment name the wall files under that witch",
      f"a Deployment named {joker}" in FLAT and ticket_site.who_deployed(joker) == EXAMPLE)
check("deploy_app's requested_by gets the name as given", f'requested_by is "{EXAMPLE}"' in FLAT)
check("the wall credits requested_by to that witch", ticket_site.name_from_display(EXAMPLE) == EXAMPLE)
check("never BurritoBot (the 2026-11-01 joker-burritobot) or the ticket's customer in its place",
      "Never put your own name, BurritoBot, or a customer name from a ticket in its place" in FLAT)
check("HC-666's ticket customer is not a vocabulary name, so the wall cannot credit it",
      ticket_site.name_from_display(ticket_site.TICKETS[ticket_site.ROOM_TICKET_ID]["customer"]) is None)
check("with no line the guest has given no name", "With no such line, the guest has not given you a name" in FLAT)

print("== every name the storefront can assign comes through in that one form ==")
template = sentence.replace(EXAMPLE, "{}")
bad_shape = [n for n in ticket_site.NAME_SPACE if not shape.fullmatch(n)]
bad_form = [n for n in ticket_site.NAME_SPACE if witch_context(n) != template.format(n)]
check(f"all {len(ticket_site.NAME_SPACE)} names pass the proxy's shape check", not bad_shape, str(bad_shape[:5]))
check("witch_context() gives each of them the quoted form with only the name changed", not bad_form, str(bad_form[:5]))
import kubecon_probe as kp  # noqa: E402
check("the KubeCon probe's stage name is one of them, and it expects joker-<its slug>",
      kp.STAGE_NAME in ticket_site.NAME_SPACE and kp.ROOM_JOKER == f"joker-{ticket_site.slug(kp.STAGE_NAME)}")

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All agent witch-name checks passed.")
