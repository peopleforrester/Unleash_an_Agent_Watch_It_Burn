# ABOUTME: Holds #1157 and #1209: the public desk takes a deploy report or cluster read from outside only with its token,
# ABOUTME: a read greys only its own cluster's rows, and every profile but kubecon-community renders no remote route.
"""Offline checks for #1157, the desk's half of #1145 (one deployments page for both KubeCon clusters), and #1209.

deployments.burritobot.co is served by the community cluster's fake-ticket. For the private cluster's deploys to show
there too, that desk takes reports from outside the cluster at POST /remote-landed, a route only the
desk-remote-reports component publishes (the kubecon-community profile's desk.remoteReports). The desk records a report
there only when its X-Desk-Report-Token header carries the token in DESK_REPORT_TOKEN, and labels each row with the
cluster it came from. With no token, and on every other profile, the desk and the console are as they were.

Since #1209 the private cluster's reader (#1050) posts what that cluster still runs to POST /remote-cluster-read, with
the same token, and the desk applies it to the rows labelled private alone, as an in-cluster /cluster-read is applied
to the rows labelled community alone: a community read never greys a private row, and a private read never a community
one.

Three parts, with no cluster and no network:
  1. the real ticket_site.py on localhost, loaded once with no token and once with one, every report over HTTP;
  2. console.conf's support-desk server and the component's route file, read as nginx reads them;
  3. each profile's ai-layer Application rendered as the chart writes it (bootstrap_chart.py, no Helm), and its
     console-conf keys and fake-ticket env as kustomize builds them from the components it lists.
verify/test_bootstrap_chart_render.py builds the same component with the pinned Helm and kustomize.
"""
from __future__ import annotations

import fnmatch
import importlib.util
import json
import os
import pathlib
import re
import sys
import threading
import time
import urllib.error
import urllib.request

import yaml

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from bootstrap_chart import (APPS, DESK_REMOTE_COMPONENT, IMAGE_REGISTRY, LAB_PLATFORM_GHCR, REPO,  # noqa: E402
                             REVISION, ai_layer_for, all_profiles, app_names, desk_remote_reports)

AI = REPO / "gitops/ai-layer"
COMPONENT = AI / DESK_REMOTE_COMPONENT
CONF = (AI / "console.conf").read_text(encoding="utf-8")
LOCATIONS = (COMPONENT / "desk-remote-report.locations").read_text(encoding="utf-8")
KUST = yaml.safe_load((AI / "kustomization.yaml").read_text(encoding="utf-8"))
COMP = yaml.safe_load((COMPONENT / "kustomization.yaml").read_text(encoding="utf-8"))
RES = [d for d in yaml.safe_load_all((AI / "resources.yaml").read_text(encoding="utf-8")) if isinstance(d, dict)]
# The console.conf headings this test cuts the support desk's server block on (tests own their inputs, #797).
DESK_ANCHOR = "# Challenge 6's ticket desk (2026-10-28 call, #685)"
PAGE_ANCHOR = "# Challenge 2's deployments page (#773)"
for anchor in (DESK_ANCHOR, PAGE_ANCHOR):
    if anchor not in CONF:
        print(f"FAILED: the anchor {anchor!r} is not in gitops/ai-layer/console.conf; reword this test with it")
        sys.exit(1)
DESK_SERVER = CONF[CONF.index(DESK_ANCHOR):CONF.index(PAGE_ANCHOR)]
CONF_DIR = "/etc/nginx/conf.d/"
TOKEN = "t0k3n-" + "a" * 40
HEADER = "X-Desk-Report-Token"
SUPPORT = "support.burritobot.co"
DEPLOYMENTS = "deployments.burritobot.co"

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  ({detail})" if detail and not cond else ""))
    if not cond:
        failures.append(name)


class Desk:
    """ticket_site.py loaded with this environment and served on localhost."""

    def __init__(self, label: str, env: dict[str, str]) -> None:
        for k in ("DESK_REPORT_TOKEN", "DESK_CLUSTER", "DESK_REMOTE_CLUSTER"):
            os.environ.pop(k, None)
        os.environ.update(env)
        spec = importlib.util.spec_from_file_location(f"ticket_site_remote_{label}", AI / "ticket_site.py")
        self.site = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.site)
        for k in env:
            os.environ.pop(k, None)
        self.site.Handler.log_message = lambda *a: None
        self.server = self.site.Server(("127.0.0.1", 0), self.site.Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"

    def post(self, path: str, body, host: str = SUPPORT, headers: dict | None = None) -> tuple[int, dict]:
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        req = urllib.request.Request(self.url + path, data=data, method="POST",
                                     headers={"Content-Type": "application/json", "Host": host, **(headers or {})})
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status, json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            raw = e.read()
            try:
                return e.code, json.loads(raw or b"{}")
            except ValueError:
                return e.code, {}

    def get(self, path: str, host: str = DEPLOYMENTS) -> tuple[int, str]:
        req = urllib.request.Request(self.url + path, headers={"Host": host})
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status, r.read().decode()
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode()

    def rows(self, query: str = "") -> list[dict]:
        return json.loads(self.get("/deployments.json" + query)[1])

    def names(self) -> set[str]:
        return {r["name"] for r in self.site.LANDINGS}


def report(name: str, witch: str = "Hazel the Witch", **extra) -> dict:
    return {"name": name, "ok": True, "detail": "", "image": "registry.burritobot.co/burritobot/maintenance-shell:1",
            "requested_by": witch, "kind": "Deployment", **extra}


print("== with no token configured, the desk takes no remote report and reads as before ==")
plain = Desk("plain", {})
check("ticket_site.py reads no token, no own label and the default remote label",
      plain.site.REMOTE_TOKEN == "" and plain.site.LOCAL_CLUSTER == "" and plain.site.REMOTE_CLUSTER == "remote",
      f"{plain.site.REMOTE_TOKEN!r} {plain.site.LOCAL_CLUSTER!r} {plain.site.REMOTE_CLUSTER!r}")
for headers, why in (({}, "no token header"), ({HEADER: TOKEN}, "a token header"), ({HEADER: ""}, "an empty one")):
    code, body = plain.post("/remote-landed", report("joker-hazel-the-witch"), headers=headers)
    check(f"POST /remote-landed with {why} is the desk's plain 404", (code, body) == (404, {"error": "not found"}),
          f"{code} {body}")
check("and records nothing", plain.site.LANDINGS == [], str(plain.site.LANDINGS))
code, row = plain.post("/landed", report("joker-hazel-the-witch"))
check("in-cluster /landed still records a row, with its witch name", code == 200 and row.get("witch") == "Hazel the Witch",
      f"{code} {row}")
check("the row's cluster is empty: this desk has no label", row.get("cluster") == "", str(row))
rows = plain.rows()
check("/deployments.json carries the row with its witch name and an empty cluster",
      len(rows) == 1 and rows[0].get("witch") == "Hazel the Witch" and rows[0].get("cluster") == "", str(rows))
code, page = plain.get("/")
script = page[page.find("<script>"):page.find("</script>")]
check("the deployments page shows a row's cluster only when it has one, so this page reads as it did",
      "if(x.cluster){" in script and "k.textContent=x.cluster" in script, script[-600:])
check("/remote-landed under the deployments host is a 404 too",
      plain.post("/remote-landed", report("x"), host=DEPLOYMENTS, headers={HEADER: TOKEN})[0] == 404)
for headers, why in (({}, "no token header"), ({HEADER: TOKEN}, "a token header")):
    code, body = plain.post("/remote-cluster-read", {"taken_at": time.time() + 5, "ok": True, "kinds": {"Deployment": []}},
                            headers=headers)
    check(f"POST /remote-cluster-read with {why} is the desk's plain 404", (code, body) == (404, {"error": "not found"}),
          f"{code} {body}")
check("and marks nothing", not [r for r in plain.site.LANDINGS if r["removed_at"]], str(plain.site.LANDINGS))
plain.server.shutdown()

print("== with the token configured, only a report that carries it is recorded ==")
desk = Desk("token", {"DESK_REPORT_TOKEN": TOKEN + "\n", "DESK_CLUSTER": "community", "DESK_REMOTE_CLUSTER": "private"})
check("the token is read without the Secret's trailing newline, and the labels from the env",
      desk.site.REMOTE_TOKEN == TOKEN and desk.site.LOCAL_CLUSTER == "community"
      and desk.site.REMOTE_CLUSTER == "private")
refused = (({}, "no token header"), ({HEADER: ""}, "an empty token"), ({HEADER: "wrong"}, "a wrong token"),
           ({HEADER: TOKEN[:-1]}, "the token less its last character"), ({HEADER: TOKEN + "x"}, "the token and more"),
           ({"Authorization": f"Bearer {TOKEN}"}, "the token as a bearer Authorization instead"))
for i, (headers, why) in enumerate(refused):
    code, body = desk.post("/remote-landed", report(f"joker-refused-{i}"), headers=headers)
    check(f"a remote report with {why} is a 401", code == 401 and HEADER in body.get("error", ""), f"{code} {body}")
check("and none of them is recorded", desk.site.LANDINGS == [], str(desk.names()))
code, row = desk.post("/remote-landed", report("joker-edgar-the-kelpie", "Edgar the Kelpie"), headers={HEADER: TOKEN})
check("a remote report with the token is recorded", code == 200 and row.get("name") == "joker-edgar-the-kelpie",
      f"{code} {row}")
check("under the remote cluster's label, with its witch name", row.get("cluster") == "private"
      and row.get("witch") == "Edgar the Kelpie", str(row))
code, row = desk.post("/remote-landed", report("joker-mabel-the-imp", "Mabel the Imp", cluster="community"),
                      headers={HEADER: f"  {TOKEN} "})
check("a report naming a cluster of its own is still labelled by the token it came with",
      code == 200 and row.get("cluster") == "private", f"{code} {row}")
code, body = desk.post("/remote-landed", b"not json", headers={HEADER: TOKEN})
check("a remote report that is not JSON is a 400, as on /landed", code == 400, f"{code} {body}")
code, body = desk.post("/remote-landed", report("x"), host=DEPLOYMENTS, headers={HEADER: TOKEN})
check("POST /remote-landed under the deployments host is a 404: that host takes no reports", code == 404, str(code))
code, row = desk.post("/landed", report("joker-hazel-the-witch"))
check("in-cluster /landed is unchanged and labels its row with this cluster",
      code == 200 and row.get("cluster") == "community" and row.get("witch") == "Hazel the Witch", f"{code} {row}")

print("== each deployments row and /deployments.json entry carries its cluster beside its witch name ==")
rows = desk.rows()
check("three rows, newest first", [r["name"] for r in rows]
      == ["joker-hazel-the-witch", "joker-mabel-the-imp", "joker-edgar-the-kelpie"], str(rows))
check("every entry has a witch name and a cluster", all(r.get("witch") and r.get("cluster") for r in rows), str(rows))
check("the room's row reads community, the presenters' rows private",
      [(r["witch"], r["cluster"]) for r in rows]
      == [("Hazel the Witch", "community"), ("Mabel the Imp", "private"), ("Edgar the Kelpie", "private")], str(rows))
mine = desk.rows("?witch=edgar-the-kelpie")
check("one witch's rows keep their cluster", [(r["name"], r["cluster"]) for r in mine]
      == [("joker-edgar-the-kelpie", "private")], str(mine))
code, chat = desk.get("/deployments.json", host="attackme.burritobot.co")
check("the chat page's own /deployments.json carries the cluster too",
      code == 200 and [r["cluster"] for r in json.loads(chat)] == ["community", "private", "private"], chat[:300])
code, page = desk.get("/")
check("the deployments page styles the cluster tag", code == 200 and ".cluster{" in page)

print("== a cluster read greys its own cluster's rows alone: in-cluster for community, with the token for private ==")


def read(names: list[str], at: float | None = None) -> dict:
    return {"taken_at": time.time() + 1 if at is None else at, "ok": True, "kinds": {"Deployment": names}}


def removed(d: Desk) -> set[str]:
    return {r["name"] for r in d.site.LANDINGS if r["removed_at"]}


for i, (headers, why) in enumerate(refused):
    code, body = desk.post("/remote-cluster-read", read([]), headers=headers)
    check(f"a remote cluster read with {why} is a 401", code == 401 and HEADER in body.get("error", ""),
          f"{code} {body}")
check("and none of them marks a row", removed(desk) == set(), str(removed(desk)))
code, body = desk.post("/remote-cluster-read", b"not json", headers={HEADER: TOKEN})
check("a remote cluster read that is not JSON is a 400, as on /cluster-read", code == 400, f"{code} {body}")
code, body = desk.post("/remote-cluster-read", {"taken_at": "now", "ok": True, "kinds": {}}, headers={HEADER: TOKEN})
check("a remote cluster read the desk cannot read is a 400 naming why", code == 400 and "taken_at" in body.get("error", ""),
      f"{code} {body}")
code, body = desk.post("/remote-cluster-read", read([]), host=DEPLOYMENTS, headers={HEADER: TOKEN})
check("POST /remote-cluster-read under the deployments host is a 404", code == 404, str(code))
check("and still no row is marked", removed(desk) == set(), str(removed(desk)))

# Rows of the same kind on both sides, one name landed on both (each cluster has its own Deployment of it).
desk.post("/landed", report("joker-shared-name", "Hazel the Witch"))
desk.post("/remote-landed", report("joker-shared-name", "Edgar the Kelpie"), headers={HEADER: TOKEN})
community = {r["name"] for r in desk.rows() if r["cluster"] == "community"}
private = {r["name"] for r in desk.rows() if r["cluster"] == "private"}
check("both clusters have rows, and one name is on each side", "joker-shared-name" in community & private
      and len(community) == 2 and len(private) == 3, f"{community} {private}")
code, body = desk.post("/remote-cluster-read", read(["joker-mabel-the-imp"]), headers={HEADER: TOKEN})
check("a private read that lists one private row marks the other private rows, the shared name's included",
      code == 200 and set(body.get("marked", [])) == {"joker-edgar-the-kelpie", "joker-shared-name"}, f"{code} {body}")
rows = desk.rows()
check("a private read never marks a community row: both community rows, the shared name's included, are as they were",
      all(not r["removed_at"] for r in rows if r["cluster"] == "community")
      and {r["name"] for r in rows if r["cluster"] == "community"} == community, str(rows))
check("the private row it listed is not marked", [r["removed_at"] for r in rows if r["name"] == "joker-mabel-the-imp"]
      == [""], str(rows))
code, body = desk.post("/cluster-read", read([]))
check("an in-cluster community read that lists no Deployment marks exactly the community rows",
      code == 200 and set(body.get("marked", [])) == community, f"{code} {body}")
rows = desk.rows()
check("a community read never marks a private row: the listed private row is still not marked",
      [r["removed_at"] for r in rows if r["name"] == "joker-mabel-the-imp"] == [""], str(rows))
code, body = desk.post("/remote-cluster-read", read([], at=time.time() - 3600), headers={HEADER: TOKEN})
check("a private read taken before the rows landed marks nothing, as on /cluster-read",
      code == 200 and body == {"applied": True, "marked": []}, f"{code} {body}")
code, body = desk.post("/remote-cluster-read", {"taken_at": time.time() + 1, "ok": False, "kinds": {}},
                       headers={HEADER: TOKEN})
check("a failed private read is applied to no row", code == 200 and body == {"applied": False, "marked": []},
      f"{code} {body}")
code, body = desk.post("/remote-cluster-read", read([]), headers={HEADER: TOKEN})
check("a later private read that lists nothing marks the last private row, and nothing else",
      code == 200 and body.get("marked") == ["joker-mabel-the-imp"], f"{code} {body}")
check("every row is now greyed on the page, each by its own cluster's read",
      all(r["removed_at"] for r in desk.rows()), str(desk.rows()))
desk.server.shutdown()

print("== a desk whose two labels are unset: a remote read covers only rows labelled remote ==")
bare = Desk("bare", {"DESK_REPORT_TOKEN": TOKEN})
bare.post("/landed", report("joker-own-row"))
bare.post("/remote-landed", report("joker-their-row"), headers={HEADER: TOKEN})
code, body = bare.post("/remote-cluster-read", read([]), headers={HEADER: TOKEN})
check("a remote read marks the remote row and not the desk's own unlabelled row",
      code == 200 and body.get("marked") == ["joker-their-row"], f"{code} {body}")
code, body = bare.post("/cluster-read", read([]))
check("and the in-cluster read marks the desk's own row and not the remote one",
      code == 200 and body.get("marked") == ["joker-own-row"], f"{code} {body}")
bare.server.shutdown()

print("== the console: the support-desk server includes a route file only the component ships ==")
inc = re.findall(r"^\s*include\s+(\S+);", DESK_SERVER, re.M)
check("the support-desk server includes one pattern under conf.d", len(inc) == 1 and inc[0].startswith(CONF_DIR), str(inc))
pattern = inc[0][len(CONF_DIR):] if inc else ""
check("the pattern is a glob, so nginx starts when no file matches it", any(c in pattern for c in "*?["), pattern)
check("it cannot match nginx's own *.conf includes or the ConfigMap's ..data entries",
      not pattern.endswith(".conf") and not pattern.startswith("."), pattern)
check("console.conf includes nothing anywhere else", len(re.findall(r"^\s*include\s", CONF, re.M)) == 1)
check("console.conf has no /remote-landed or /remote-cluster-read route of its own",
      "location = /remote-landed" not in CONF and "location = /remote-cluster-read" not in CONF)
check("and still refuses /landed and /cluster-read from outside on the support server",
      re.search(r"location = /landed \{\s*deny all;", DESK_SERVER) is not None
      and re.search(r"location = /cluster-read \{\s*deny all;", DESK_SERVER) is not None)
gen = COMP.get("configMapGenerator") or []
check("the component merges one file into console-conf",
      gen == [{"name": "console-conf", "behavior": "merge", "files": ["desk-remote-report.locations"]}], str(gen))
check("and that file's name matches the include", fnmatch.fnmatchcase("desk-remote-report.locations", pattern), pattern)
locs = re.findall(r"^location\s+(\S+)\s+(\S+)\s+\{", LOCATIONS, re.M)
check("the file holds two locations, the exact /remote-landed and /remote-cluster-read",
      locs == [("=", "/remote-landed"), ("=", "/remote-cluster-read")], str(locs))
blocks = dict(re.findall(r"^location = (\S+) \{\n(.*?)^\}", LOCATIONS, re.M | re.S))
check("each location's block was read", sorted(blocks) == ["/remote-cluster-read", "/remote-landed"], str(sorted(blocks)))
for path, block in sorted(blocks.items()):
    check(f"{path}: POST only", "limit_except POST { deny all; }" in block)
    check(f"{path}: refused at the console without the token header",
          'if ($http_x_desk_report_token = "") { return 401; }' in block)
    check(f"{path}: and passed to the in-cluster desk, which checks the token",
          re.search(r"set \$(\w+) http://fake-ticket\.agent\.svc\.cluster\.local:8080;\s*proxy_pass \$\1;", block)
          is not None)
check("/remote-landed takes a deploy report's 4k, /remote-cluster-read a cluster read's 512k, the desk's MAX_READ_BODY",
      "client_max_body_size 4k;" in blocks.get("/remote-landed", "")
      and "client_max_body_size 512k;" in blocks.get("/remote-cluster-read", "")
      and "MAX_READ_BODY = 512 * 1024" in (AI / "ticket_site.py").read_text(encoding="utf-8"))
check("the file has no server or http block of its own", re.search(r"^\s*(server|http)\s*\{", LOCATIONS, re.M) is None)
patches = COMP.get("patches") or []
env = {}
for p in patches:
    if p.get("target") == {"kind": "Deployment", "name": "fake-ticket"}:
        doc = yaml.safe_load(p["patch"])
        env = {e["name"]: e for c in doc["spec"]["template"]["spec"]["containers"] for e in c.get("env") or []}
check("the component patches fake-ticket alone", [p.get("target") for p in patches]
      == [{"kind": "Deployment", "name": "fake-ticket"}], str(patches))
check("with the labels community and private", env.get("DESK_CLUSTER", {}).get("value") == "community"
      and env.get("DESK_REMOTE_CLUSTER", {}).get("value") == "private", str(env))
check("and the token from the desk-report-token Secret, optional, so a cluster without it still starts",
      env.get("DESK_REPORT_TOKEN", {}).get("valueFrom") == {"secretKeyRef": {"name": "desk-report-token", "key": "token",
                                                                             "optional": True}}, str(env))
site = [d for d in RES if d.get("kind") == "Deployment" and d["metadata"]["name"] == "fake-ticket"]
base_env = [e for c in site[0]["spec"]["template"]["spec"]["containers"] for e in c.get("env") or []] if site else None
check("the base fake-ticket Deployment carries none of it", base_env == [], str(base_env))

print("== each profile's render: the attendee profile, and every one but kubecon-community, has no remote route ==")
base_conf = next((g for g in KUST["configMapGenerator"] if g["name"] == "console-conf"), {})
base_keys = [f.partition("=")[0] if "=" in f else pathlib.Path(f).name for f in base_conf.get("files", [])]
check("the base console-conf is default.conf alone", base_keys == ["default.conf"], str(base_keys))


def ai_layer_components(profile: str) -> list[str]:
    app = yaml.safe_load(ai_layer_for(profile).replace(REVISION, "0" * 40).replace(IMAGE_REGISTRY, LAB_PLATFORM_GHCR))
    return list(app["spec"]["source"].get("kustomize", {}).get("components") or [])


def console_conf_keys(components: list[str]) -> list[str]:
    keys = list(base_keys)
    for c in components:
        doc = yaml.safe_load((AI / c / "kustomization.yaml").read_text(encoding="utf-8"))
        for g in doc.get("configMapGenerator") or []:
            if g.get("name") == "console-conf":
                keys += [f.partition("=")[0] if "=" in f else pathlib.Path(f).name for f in g.get("files", [])]
    return keys


rendered = [p for p in all_profiles() if "ai-layer" in app_names(p)]
check("the attendee profile renders the ai-layer", "attendee" in rendered, str(rendered))
for profile in rendered:
    comps = ai_layer_components(profile)
    on = profile == "kubecon-community"
    check(f"{profile}: desk.remoteReports is {on}", desk_remote_reports(profile) is on)
    check(f"{profile}: the ai-layer {'adds' if on else 'does not add'} the desk-remote-reports component {comps}",
          (DESK_REMOTE_COMPONENT in comps) is on)
    matched = [k for k in console_conf_keys(comps) if fnmatch.fnmatchcase(k, pattern)]
    check(f"{profile}: console-conf {'has the remote route file' if on else 'has no file the include matches'} "
          f"{matched}", matched == (["desk-remote-report.locations"] if on else []))

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("The public desk takes a remote deploy report or cluster read only with its token, labels every row with its "
      "cluster, greys a row only from its own cluster's read, and only kubecon-community publishes the routes.")
