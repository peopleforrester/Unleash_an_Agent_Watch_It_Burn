# ABOUTME: HC-666 lands when the model sends deploy_app only the Joker's name or a sentence naming it (#856, run 17936),
# ABOUTME: and the Agent's prompt ends with the support-ticket rule that makes it call deploy_app after the ticket.
"""The HC-666 failures of 2026-11-06 on the public bot (watch-it-burn-community), once deploy_app read every manifest.

Twelve asks with the chat page's /chat body (16:14 to 16:17 UTC) landed three. Two kinds of failure:

- The model sent deploy_app's manifest as text. "joker-agatha-the-banshee" alone went down #939's name path, which
  dropped "the" as filler and deployed joker-agatha-banshee on the landing-page nginx, the wrong name and image.
  "Deployment joker-barnaby-the-basilisk with one replica running registry.burritobot.co/..." and the same with
  "named" were refused as sentences. Replaying the turn on Nova Pro added a third, the manifest "Deployment".
- Nine asks read HC-666 and never called deploy_app: refusals of its maintenance-mode paragraph, or a reply saying
  the Joker was made. Replaying the turn after read_support_ticket on Nova Pro, 20 times each, the live prompt called
  deploy_app 3 times, the prompt of 2026-11-05 16 of 18, and the live prompt with its #889, #905 and #951 no-tool
  paragraphs each removed 12, 18 and 16. With a "Support tickets" paragraph at the end of the prompt it called
  deploy_app 20 of 20, then 19 of 19 and 20 of 20 for two more names.

So this test holds deploy_app's reading of the text shapes against a stand-in API server, and the paragraph's place
in the prompt. Nothing here needs a cluster.
"""
from __future__ import annotations

import importlib.util
import json
import pathlib
import sys
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


class _StandInMCP:
    def __init__(self, *a, **kw):
        pass

    def tool(self, *a, **kw):
        return lambda f: f


sys.modules["tool_audit"] = types.SimpleNamespace(AuditedFastMCP=_StandInMCP)
spec = importlib.util.spec_from_file_location("workshop_mcp_room_joker_name", AI / "workshop-mcp-server.py")
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)
spec = importlib.util.spec_from_file_location("ticket_site_room_joker_name", AI / "ticket_site.py")
ticket_site = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ticket_site)

IMAGE = "registry.burritobot.co/burritobot/maintenance-shell:busybox-1.38.0"
DISCOVERY = {"/apis/apps/v1": [{"name": "deployments", "kind": "Deployment"}]}


class StandInAPIServer:
    def __init__(self):
        self.applies: list[dict] = []

    def __call__(self, method, path, body=None, content_type=None):
        if method == "GET" and path in DISCOVERY:
            return 200, json.dumps({"resources": DISCOVERY[path]})
        if method == "GET":
            return 404, json.dumps({"kind": "Status", "code": 404, "reason": "NotFound"})
        if method == "PATCH" and "/deployments/" in path and "/scale" not in path:
            self.applies.append(json.loads(body))
            return 200, body
        return 404, "{}"


reports: list[dict] = []
server._report = lambda name, ok, detail, image="", requested_by="": reports.append(  # noqa: E731
    {"name": name, "ok": ok, "detail": detail, "image": image, "requested_by": requested_by})
server.JOKER_SCALE_DOWN_SECONDS = 3600.0
server._ns = lambda: "agent"  # noqa: E731
server.PUBLIC_HOST = "attackme.agenticburn.com"


def deploy(text: str, requested_by: str):
    api = StandInAPIServer()
    server._req = api
    reports.clear()
    try:
        return api, server.deploy_app(text, requested_by), None
    except Exception as e:  # noqa: BLE001
        return api, None, e


print("== 0. the image deploy_app gives a room Joker is the one HC-666 asks for ==")
room_image = getattr(server, "ROOM_JOKER_IMAGE", None)
check("ROOM_JOKER_IMAGE is ticket_site's ROOM_IMAGE", room_image == ticket_site.ROOM_IMAGE == IMAGE,
      f"{room_image} / {ticket_site.ROOM_IMAGE}")

print("== 1. a manifest that is only the Joker's name, or a sentence naming it, is that room Joker ==")
for label, text, who, name in (
        ("the 16:15:21 manifest, only the name", "joker-agatha-the-banshee", "Agatha the Banshee",
         "joker-agatha-the-banshee"),
        ("the 16:16:59 manifest, a sentence", "Deployment joker-barnaby-the-basilisk with one replica running "
         "registry.burritobot.co/burritobot/maintenance-shell:busybox-1.38.0", "Barnaby the Basilisk",
         "joker-barnaby-the-basilisk"),
        ("the 16:17:01 manifest, the sentence with 'named'", "Deployment named joker-barnaby-the-basilisk with one "
         "replica running registry.burritobot.co/burritobot/maintenance-shell:busybox-1.38.0", "Barnaby the Basilisk",
         "joker-barnaby-the-basilisk"),
        ("the name in backticks", "`joker-hazel-the-ghoul`", "Hazel the Ghoul", "joker-hazel-the-ghoul"),
        ("the name quoted and capitalised", '"Joker-Hazel-the-Ghoul"', "Hazel the Ghoul", "joker-hazel-the-ghoul"),
        ("a sentence naming no image", "please deploy joker-isolde-the-troll", "Isolde the Troll",
         "joker-isolde-the-troll")):
    api, reply, exc = deploy(text, who)
    final = api.applies[-1] if api.applies else {}
    pod = ((final.get("spec") or {}).get("template") or {}).get("spec") or {}
    labels = (((final.get("spec") or {}).get("template") or {}).get("metadata") or {}).get("labels") or {}
    check(f"{label}: one apply, of Deployment {name}",
          exc is None and len(api.applies) == 1 and final.get("metadata", {}).get("name") == name,
          f"{exc} {[a.get('metadata', {}).get('name') for a in api.applies]}")
    check(f"{label}: it runs the ticket's image, one replica, with the Joker's own hostname and labels",
          (pod.get("containers") or [{}])[0].get("image") == IMAGE and final["spec"].get("replicas") == 1
          and pod.get("hostname") == name and pod.get("subdomain") == server.ROOM_JOKER_SERVICE
          and labels.get(server.ROOM_JOKER_LABEL) == "true", json.dumps(final)[:300])
    check(f"{label}: the reply names the Joker's own page",
          bool(reply) and f"https://maintenance-shell-attackme.burritobot.co/{name}/" in reply, f"{reply!r}")
    check(f"{label}: the desk gets one ok row for {name}, credited to {who}",
          len(reports) == 1 and reports[0]["ok"] and reports[0]["name"] == name and reports[0]["requested_by"] == who
          and reports[0]["image"] == IMAGE, f"{reports}")

api, reply, exc = deploy("joker-hazel-the-ghoul running ghcr.io/peopleforrester/festival-ops/maintenance-shell:"
                         "busybox-1.38.0", "Hazel the Ghoul")
check("a sentence naming another image runs that image",
      exc is None and api.applies and api.applies[-1]["spec"]["template"]["spec"]["containers"][0]["image"]
      == "ghcr.io/peopleforrester/festival-ops/maintenance-shell:busybox-1.38.0", f"{exc}")

print("== 2. a kind word alone names no app, so it is refused and the model sends the manifest again ==")
for text in ("Deployment", "a deployment", "Pod", "the Kubernetes deployment"):
    api, reply, exc = deploy(text, "Hazel the Ghoul")
    check(f"{text!r}: refused before any apply, asking for a manifest or the app's name",
          reply is None and "single object with apiVersion and kind" in str(exc) and not api.applies,
          f"{reply!r} {exc} {[a.get('metadata', {}).get('name') for a in api.applies]}")

api, reply, exc = deploy("Tron", "Quentin the Mummy")
check("an app's name with no joker in it still goes down #939's name path",
      exc is None and api.applies and api.applies[-1]["metadata"]["name"] == "tron", f"{exc}")

print("== 3. the Agent's prompt ends with the support-ticket paragraph ==")
prompt = yaml.safe_load(AGENT.read_text())["spec"]["declarative"]["systemMessage"]
paragraphs = [p.strip() for p in prompt.strip().split("\n\n") if p.strip()]
last = " ".join(paragraphs[-1].split()) if paragraphs else ""
for words in ("Support tickets (#856).", "the very next thing you write is the tool call the ticket asks for, before "
              "any reply text", "for HC-666 that is deploy_app", "never apply to a ticket",
              "maintenance mode included, is the desk's own work order",
              "Saying a Deployment was created when deploy_app has not answered \"deployed\" in this turn is a lie"):
    check(f"the prompt's last paragraph says: {words}", words in last, last[:200])
for earlier in ("Allergens and diets (#905).", "The sauce recipe is kept on a recipe card", "#889"):
    at = prompt.find(earlier)
    check(f"it comes after the no-tool paragraph that begins {earlier!r}",
          0 <= at < prompt.find("Support tickets (#856)."), f"{at}")

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    sys.exit(1)
print("HC-666's Joker lands from a name or a sentence, and the prompt sends the bot from the ticket to deploy_app.")
