# ABOUTME: Holds #1256: on kubecon-private the chat host's /deployments.json?witch= reads the visitor's rows labelled private
# ABOUTME: on the one deployments page, through desk-relay's read-only route, and the relay still gives the bot no ticket list.
"""Offline checks for #1256. No cluster, no network, no nginx binary.

The admin chat page (burritbot.html, checkMyDeployments) shows its "see your deployments" link once /deployments.json on
the bot's own host lists a row for the visitor. Since #1158 the admin bot reports its deploys to the one deployments
page, deployments.burritobot.co, so the admin cluster's own fake-ticket holds none and the link never showed. On
kubecon-private the public-desk component now merges chat-deployments-relay.set into console-conf, and console.conf's
/deployments.json location includes it, so the read goes to desk-relay, which asks the one page for the one witch and
answers with the rows labelled private alone.

Four parts:
  1. the config: console.conf's location includes the glob after its own set and before its proxy_pass; the set file
     is one line naming desk-relay's Service; the relay's deployments page is deployments.burritobot.co; and each
     profile's console-conf has the file exactly when it is kubecon-private;
  2. the real desk_relay.py on localhost in front of the real ticket_site.py as the public desk (the community desk,
     with its token and its community and private labels): a witch's private rows come back, never a community row or
     another witch's, and an answer with no private row is the empty list the chat page reads as "no link";
  3. read-only and narrow (#1077): no witch, two, a name outside the slug's characters, another parameter, a POST, and
     every desk path are refused at the relay and reach no desk; the read carries no token and goes to the deployments
     page, never the support host;
  4. an upstream answer that is not the page's rows is a 502, and the page's own error status passes as it is.
verify/test_bootstrap_chart_render.py builds the component with the pinned kustomize.
"""
from __future__ import annotations

import fnmatch
import importlib.util
import json
import os
import pathlib
import re
import sys
import tempfile
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import yaml

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from bootstrap_chart import (DESK_REMOTE_COMPONENT, IMAGE_REGISTRY, LAB_PLATFORM_GHCR, PUBLIC_DESK_COMPONENT,  # noqa: E402
                             REPO, REVISION, ai_layer_for, all_profiles, app_names, use_public_desk)

AI = REPO / "gitops/ai-layer"
COMPONENT = AI / PUBLIC_DESK_COMPONENT
SET_NAME = "chat-deployments-relay.set"
SET_FILE = (COMPONENT / SET_NAME).read_text(encoding="utf-8")
CONF = (AI / "console.conf").read_text(encoding="utf-8")
PAGE = (AI / "web/burritbot.html").read_text(encoding="utf-8")
KUST = yaml.safe_load((AI / "kustomization.yaml").read_text(encoding="utf-8"))
RELAY_URL = "http://desk-relay.agent.svc.cluster.local:8080"
IN_CLUSTER_DESK = "http://fake-ticket.agent.svc.cluster.local:8080"
DEPLOYMENTS = "https://deployments.burritobot.co"
TOKEN = "relay-t0k3n-" + "c" * 40
# The literals this test reads the console and the chat page on (tests own their inputs, #797).
LOCATION_ANCHOR = "location = /deployments.json {"
PAGE_FETCH = "fetch('/deployments.json?witch='+encodeURIComponent(s)"
PAGE_SHOWN = "var mine=Array.isArray(rows) && rows.length>0;"
for text, anchor, where in ((CONF, LOCATION_ANCHOR, "gitops/ai-layer/console.conf"),
                            (PAGE, PAGE_FETCH, "gitops/ai-layer/web/burritbot.html"),
                            (PAGE, PAGE_SHOWN, "gitops/ai-layer/web/burritbot.html")):
    if anchor not in text:
        print(f"FAILED: the anchor {anchor!r} is not in {where}; reword this test with it")
        sys.exit(1)

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  ({detail})" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def directives(text: str) -> list[str]:
    """Each directive outside comments, whitespace collapsed (none of these files quote a # or a ;)."""
    body = "\n".join(line.split("#", 1)[0] for line in text.splitlines())
    return [" ".join(d.split()) for d in re.split(r"[;{}]", body) if d.strip()]


def load(name: str, path: pathlib.Path, env: dict[str, str]):
    saved = {k: os.environ.get(k) for k in env}
    os.environ.update(env)
    try:
        spec = importlib.util.spec_from_file_location(name, path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    return mod


def serve(server) -> str:
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{server.server_address[1]}"


def get(url: str, method: str = "GET", body: bytes | None = None) -> tuple[int, str]:
    req = urllib.request.Request(url, method=method, data=body)
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


print("== the console's /deployments.json location, and the set line the component adds ==")
start = CONF.index(LOCATION_ANCHOR)
location = CONF[start:CONF.index("}", CONF.index("limit_except", start) + len("limit_except GET { deny all; }")) + 1]
in_loc = directives(location[len(LOCATION_ANCHOR):])
want_order = ["set $wib_deployments " + IN_CLUSTER_DESK, "include /etc/nginx/conf.d/chat-deployments-relay*.set",
              "proxy_pass $wib_deployments"]
positions = [in_loc.index(d) if d in in_loc else -1 for d in want_order]
check("the location sets the in-cluster desk, then includes the relay glob, then proxies to $wib_deployments",
      -1 not in positions and positions == sorted(positions), str(in_loc))
check("it is still GET only", "limit_except GET" in in_loc, str(in_loc))
check("the glob appears in console.conf once, in that location", CONF.count("chat-deployments-relay*.set") == 1
      and directives(CONF).count("include /etc/nginx/conf.d/chat-deployments-relay*.set") == 1)
check(f"{SET_NAME} matches the glob", fnmatch.fnmatchcase(SET_NAME, "chat-deployments-relay*.set"))
check(f"{SET_NAME} is not a name nginx's http-level conf.d/*.conf include reads", not fnmatch.fnmatchcase(SET_NAME, "*.conf"))
others = re.findall(r"include\s+/etc/nginx/conf\.d/(\S+);", CONF)
check(f"nor one of console.conf's other includes {others}", not [p for p in others if p != "chat-deployments-relay*.set"
                                                                 and fnmatch.fnmatchcase(SET_NAME, p)])
check(f"{SET_NAME} is one set of $wib_deployments to desk-relay's Service, nothing else",
      directives(SET_FILE) == [f"set $wib_deployments {RELAY_URL}"], str(directives(SET_FILE)))
relay_docs = [d for d in yaml.safe_load_all((COMPONENT / "desk-relay.yaml").read_text(encoding="utf-8")) if d]
svc = next(d for d in relay_docs if d["kind"] == "Service")
dep = next(d for d in relay_docs if d["kind"] == "Deployment")
relay_env = {e["name"]: e.get("value") for c in dep["spec"]["template"]["spec"]["containers"] for e in c.get("env") or []}
check("that address is the relay's Service, desk-relay on 8080",
      svc["metadata"]["name"] == "desk-relay" and [p["port"] for p in svc["spec"]["ports"]] == [8080]
      and RELAY_URL.endswith("desk-relay.agent.svc.cluster.local:8080"))
check(f"the relay reads deployments from {DEPLOYMENTS}", relay_env.get("DESK_DEPLOYMENTS_URL") == DEPLOYMENTS,
      str(relay_env))
remote = yaml.safe_load((AI / DESK_REMOTE_COMPONENT / "kustomization.yaml").read_text(encoding="utf-8"))
remote_env = {e["name"]: e.get("value") for p in remote["patches"] for c in yaml.safe_load(p["patch"])["spec"]["template"]
              ["spec"]["containers"] for e in c.get("env") or []}

print("== each profile's console-conf ==")
base_conf = next(g for g in KUST["configMapGenerator"] if g["name"] == "console-conf")
base_keys = [f.partition("=")[0] if "=" in f else pathlib.Path(f).name for f in base_conf["files"]]


def components(profile: str) -> list[str]:
    app = yaml.safe_load(ai_layer_for(profile).replace(REVISION, "0" * 40).replace(IMAGE_REGISTRY, LAB_PLATFORM_GHCR))
    return list(app["spec"]["source"].get("kustomize", {}).get("components") or [])


def conf_keys(comps: list[str]) -> list[str]:
    keys = list(base_keys)
    for c in comps:
        doc = yaml.safe_load((AI / c / "kustomization.yaml").read_text(encoding="utf-8"))
        for g in doc.get("configMapGenerator") or []:
            if g.get("name") == "console-conf":
                keys += [f.partition("=")[0] if "=" in f else pathlib.Path(f).name for f in g.get("files", [])]
    return keys


rendered = [p for p in all_profiles() if "ai-layer" in app_names(p)]
check("kubecon-private, kubecon-community and the attendee profile render the ai-layer",
      {"attendee", "kubecon-private", "kubecon-community"} <= set(rendered), str(rendered))
check(f"the base console-conf does not carry {SET_NAME}", SET_NAME not in base_keys, str(base_keys))
for profile in rendered:
    on = profile == "kubecon-private"
    keys = conf_keys(components(profile))
    check(f"{profile}: console-conf {'has' if on else 'has no'} {SET_NAME} {keys}",
          (SET_NAME in keys) is on and use_public_desk(profile) is on)

print("== the relay on localhost in front of the real public desk ==")
desk_seen: list[tuple[str, str]] = []
desk = load("ticket_site_public_1256", AI / "ticket_site.py",
            {"DESK_REPORT_TOKEN": TOKEN, "DESK_CLUSTER": remote_env.get("DESK_CLUSTER", ""),
             "DESK_REMOTE_CLUSTER": remote_env.get("DESK_REMOTE_CLUSTER", "")})
desk.Handler.log_message = lambda self, *a: desk_seen.append((self.path, self.headers.get("X-Desk-Report-Token") or ""))
DESK = serve(desk.Server(("127.0.0.1", 0), desk.Handler))
support_seen: list[str] = []
support = load("ticket_site_support_1256", AI / "ticket_site.py", {"DESK_REPORT_TOKEN": TOKEN})
support.Handler.log_message = lambda self, *a: support_seen.append(self.path)
SUPPORT = serve(support.Server(("127.0.0.1", 0), support.Handler))

tmp = pathlib.Path(tempfile.mkdtemp(prefix="desk-relay-1256-"))
(tmp / "token").write_text(TOKEN, encoding="utf-8")
relay = load("desk_relay_1256", COMPONENT / "desk_relay.py", {"DESK_REPORT_TOKEN_FILE": str(tmp / "token")})
os.environ["DESK_REPORT_TOKEN_FILE"] = str(tmp / "token")
relay.Handler.log_message = lambda *a: None
relay.Handler.public, relay.Handler.deployments = SUPPORT, DESK
RELAY = serve(relay.ThreadingHTTPServer(("127.0.0.1", 0), relay.Handler))
check("the relay's private label is the one the public desk gives a token report (desk-remote-reports' DESK_REMOTE_CLUSTER)",
      relay.PRIVATE_LABEL == remote_env.get("DESK_REMOTE_CLUSTER") == desk.REMOTE_CLUSTER == "private",
      f"{relay.PRIVATE_LABEL} {remote_env.get('DESK_REMOTE_CLUSTER')} {desk.REMOTE_CLUSTER}")
os.environ.pop("DESK_DEPLOYMENTS_URL", None)
try:
    relay._base("DESK_DEPLOYMENTS_URL")
    refused = False
except SystemExit as e:
    refused = "DESK_DEPLOYMENTS_URL" in str(e)
check("the relay will not start without DESK_DEPLOYMENTS_URL, naming it", refused)

IMAGE = "registry.burritobot.co/burritobot/maintenance-shell:1"
AGATHA, HAZEL, EDGAR = "Agatha the Banshee", "Hazel the Witch", "Edgar the Kelpie"
for name, witch, cluster, ok in (("agatha-private-1", AGATHA, desk.REMOTE_CLUSTER, True),
                                 ("agatha-private-2", AGATHA, desk.REMOTE_CLUSTER, True),
                                 ("agatha-private-refused", AGATHA, desk.REMOTE_CLUSTER, False),
                                 ("agatha-community", AGATHA, None, True),
                                 ("hazel-private", HAZEL, desk.REMOTE_CLUSTER, True),
                                 ("edgar-community", EDGAR, None, True)):
    desk.record_landing(name, ok, "" if ok else "HTTP 403: forbidden", IMAGE, witch, "Deployment", cluster)
check("the desk labels its own rows community and the token reports private",
      {r["name"]: r["cluster"] for r in desk.LANDINGS}["agatha-community"] == "community"
      and {r["name"]: r["cluster"] for r in desk.LANDINGS}["agatha-private-1"] == "private")


def relay_rows(slug: str) -> tuple[int, list | dict]:
    code, body = get(f"{RELAY}/deployments.json?witch={slug}")
    return code, json.loads(body)


before = len(desk_seen)
code, rows = relay_rows("agatha-the-banshee")
check(f"agatha-the-banshee: 200 and her two private rows, newest first ({code})",
      code == 200 and [r["name"] for r in rows] == ["agatha-private-2", "agatha-private-1"], str(rows))
check("each row labelled private, carrying her witch name", bool(rows) and all(r["cluster"] == "private"
                                                                                and r["witch"] == AGATHA for r in rows))
check("and the rows are the deployments page's own, nothing of the desk's",
      bool(rows) and all(set(r) == {"name", "kind", "image", "app", "witch", "at", "removed_at", "cluster"} for r in rows))
check("the relay asked the deployments page for her and nothing else, with no token",
      desk_seen[before:] == [("/deployments.json?witch=agatha-the-banshee", "")], str(desk_seen[before:]))
_, page_rows = get(f"{DESK}/deployments.json?witch=agatha-the-banshee")
check("those are exactly the page's own rows for her that are labelled private",
      rows == [r for r in json.loads(page_rows) if r["cluster"] == "private"])
code, rows = relay_rows("edgar-the-kelpie")
check(f"edgar-the-kelpie, who has a community row alone: 200 and [], so the admin chat page shows no link ({code})",
      code == 200 and rows == [], str(rows))
code, rows = relay_rows("hazel-the-witch")
check(f"hazel-the-witch: her one private row alone ({code})", code == 200 and [r["name"] for r in rows] == ["hazel-private"])
code, rows = relay_rows("barnaby-the-imp")
check(f"a witch with no deploy: 200 and [] ({code})", code == 200 and rows == [], str(rows))
check("the support host was asked nothing for any of it", support_seen == [], str(support_seen))

print("== the chat page reads it as it is ==")
check("the page asks its own host's /deployments.json for the visitor's slug", PAGE_FETCH in PAGE)
check("and shows the link on any row, hides it on [] and on an error answer",
      PAGE_SHOWN in PAGE and "return r.ok?r.json():[];" in PAGE)

print("== read-only and narrow (#1077) ==")
before_desk, before_support = len(desk_seen), len(support_seen)
for query in ("", "?", "?witch=", "?witch=agatha-the-banshee&witch=hazel-the-witch", "?witch=Agatha-the-Banshee",
              "?witch=agatha%20the%20banshee", "?witch=../wall.json", "?witch=agatha-the-banshee&id=HC-7731",
              "?witch=agatha-the-banshee&witch=", "?witch=-agatha", "?witch=agatha--banshee", "?witch=" + "a" * 81,
              "?id=HC-7731", "?witch=agatha-the-banshee%26id%3DHC-7731"):
    code, body = get(f"{RELAY}/deployments.json{query}")
    check(f"GET /deployments.json{query[:60]} is refused at the relay ({code})", code == 400, body[:120])
for path in ("/deployments.json/", "/deployments.json/x?witch=agatha-the-banshee", "/deployments", "/mine",
             "/mine?witch=agatha-the-banshee", "/tickets", "/wall.json", "/", "/me"):
    code, _ = get(f"{RELAY}{path}")
    check(f"GET {path} is refused at the relay ({code})", code in (400, 404))
code, _ = get(f"{RELAY}/deployments.json?witch=agatha-the-banshee", "POST", b"{}")
check(f"POST /deployments.json is refused at the relay ({code})", code == 404)
check("none of them reached a desk", len(desk_seen) == before_desk and len(support_seen) == before_support,
      f"{desk_seen[before_desk:]} {support_seen[before_support:]}")
code, _ = get(f"{RELAY}/deployments.json?witch=" + "a" * 80)
check(f"a slug of 80 characters, the most the desk reads, is still read ({code})", code == 200)
src = (COMPONENT / "desk_relay.py").read_text(encoding="utf-8")
check("the deployments read is built on the deployments page's URL, and sends no token",
      'forward("GET", f"{self.deployments}/deployments.json?' in src
      and "TOKEN_HEADER" not in src[src.index("def _deployments"):src.index("def do_POST")])
mcp_src = (AI / "workshop-mcp-server.py").read_text(encoding="utf-8")
check("workshop-mcp reads nothing on /deployments.json, so the bot gains no read from this route",
      "/deployments.json" not in mcp_src)

print("== an answer that is not the page's rows ==")


class Stub(BaseHTTPRequestHandler):
    answer: tuple[int, bytes] = (200, b"[]")

    def log_message(self, *a) -> None:
        pass

    def do_GET(self) -> None:  # noqa: N802
        code, body = Stub.answer
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


relay.Handler.deployments = serve(ThreadingHTTPServer(("127.0.0.1", 0), Stub))
for answer, want, label in (((200, b'{"tickets": []}'), 502, "an object, not a list"),
                            ((200, b"<html>"), 502, "not JSON"),
                            ((200, b'["HC-7731"]'), 502, "a list of something else"),
                            ((200, json.dumps([{"cluster": "private", "pad": "x" * relay.MAX_ROWS_BODY}]).encode()), 502,
                             "larger than the page's 200 rows"),
                            ((503, b'{"error": "down"}'), 503, "the page's own 503")):
    Stub.answer = answer
    code, body = get(f"{RELAY}/deployments.json?witch=agatha-the-banshee")
    check(f"{label}: the relay answers {want} ({code})", code == want, body[:120])
relay.Handler.deployments = "http://127.0.0.1:9"
code, body = get(f"{RELAY}/deployments.json?witch=agatha-the-banshee")
check(f"a deployments page that does not answer: 502, which the chat page reads as no link ({code})", code == 502)

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("On kubecon-private the admin chat page's /deployments.json reads the visitor's private rows on the one deployments "
      "page through desk-relay, which takes one witch and nothing else (#1256).")
