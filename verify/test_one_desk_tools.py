# ABOUTME: Holds #1159: the Night Before probe, the trace seeds and the desk reset all target the KubeCon pair's one
# ABOUTME: desk, support.burritobot.co, and the reset clears it only from inside the desk's own pod, keeping fixed tickets.
"""Offline checks for #1159, part of #1145 (one support desk and one deployments page for both KubeCon bots).

Three parts, with no cluster and no network beyond localhost:
  1. the desk the probe's one-desk beat and the trace seeds expect is the one each profile's ai-layer gives its bot, as
     kustomize writes it: desk-relay on kubecon-private, whose public desk is support.burritobot.co, the room's desk host
     (verify/support_desk_hosts.py), and the in-cluster fake-ticket on kubecon-community, which labels the private
     cluster's token-carrying reports `private`;
  2. the real ticket_site.py's POST /desk-reset (#1144's clear, built here on the one desk): from the pod's loopback it
     clears every deploy row, keeps every ticket unless asked, then clears the filed ones, the room's and the presenters'
     HC-9xx, and keeps every fixed ticket; through a proxy, from any pod address, on the deployments host or with a bad
     body it changes nothing, and the console refuses the path on the desk's public server;
  3. fleet.sh desk-reset, with fake aws and a kubectl whose exec runs the in-pod script against that real desk: it clears
     the page on watch-it-burn-community and refuses the private cluster, its standby and an attendee seat.
verify/test_fleet_standbys.sh holds where desk-reset and the watcher's desk-link go once a standby takes a KubeCon role.
"""
from __future__ import annotations

import importlib.util
import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile
import threading
import urllib.error
import urllib.parse
import urllib.request

import yaml

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
# fleet.sh runs behind fakes of its own; anything past them to a real aws, kubectl, eksctl, terraform or helm would log
# the call and fail, even when the test is run by hand (verify/no_cloud.py).
import no_cloud  # noqa: E402
no_cloud.setup()
import kubecon_probe as kp  # noqa: E402
import stage_traces as st  # noqa: E402
import support_desk_hosts as sdh  # noqa: E402
from bootstrap_chart import (DESK_REMOTE_COMPONENT, PUBLIC_DESK_COMPONENT, REPO, ai_layer_for,  # noqa: E402
                             all_profiles, app_names)

AI = REPO / "gitops/ai-layer"
FLEET = REPO / "infra/terraform/fleet/fleet.sh"
RES = [d for d in yaml.safe_load_all((AI / "resources.yaml").read_text(encoding="utf-8")) if isinstance(d, dict)]

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  ({detail})" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def container(deploy: str, name: str, components: list[str]) -> dict:
    """One container of a Deployment as kustomize writes it: resources.yaml's, then each component's env patch merged
    by name. Returns the container with its env as {name: entry}."""
    dep = next(d for d in RES if d.get("kind") == "Deployment" and d["metadata"]["name"] == deploy)
    ct = next(c for c in dep["spec"]["template"]["spec"]["containers"] if c["name"] == name)
    env = {e["name"]: e for e in ct.get("env") or []}
    for comp in components:
        doc = yaml.safe_load((AI / comp / "kustomization.yaml").read_text(encoding="utf-8"))
        for p in doc.get("patches") or []:
            if (p.get("target") or {}).get("name") != deploy:
                continue
            for pc in yaml.safe_load(p["patch"])["spec"]["template"]["spec"]["containers"]:
                if pc["name"] == name:
                    env.update({e["name"]: e for e in pc.get("env") or []})
    return {**ct, "env": env}


def components_of(profile: str) -> list[str]:
    app = yaml.safe_load(ai_layer_for(profile))
    return list((app["spec"]["source"].get("kustomize") or {}).get("components") or [])


print("== the desk the probe and the seeds expect is the one each KubeCon profile gives its bot ==")
profiles = [p for p in all_profiles() if "ai-layer" in app_names(p)]
check("kubecon-private and kubecon-community both render the ai-layer",
      {"kubecon-private", "kubecon-community"} <= set(profiles), str(profiles))
for profile in profiles:
    url = container("workshop-mcp", "shim", components_of(profile))["env"].get("TICKET_SITE_URL", {}).get("value")
    want = kp.DESK_RELAY_URL if profile == "kubecon-private" else kp.IN_CLUSTER_DESK
    check(f"{profile}: the bot's TICKET_SITE_URL is the {'relay' if want == kp.DESK_RELAY_URL else 'in-cluster desk'} "
          "the probe's one-desk beat expects", url == want, f"{url} != {want}")
relay = [d for d in yaml.safe_load_all((AI / PUBLIC_DESK_COMPONENT / "desk-relay.yaml").read_text(encoding="utf-8")) if d]
relay_env = {e["name"]: e.get("value") for d in relay if d["kind"] == "Deployment"
             for c in d["spec"]["template"]["spec"]["containers"] for e in c.get("env") or []}
check("the relay's public desk is kp.PUBLIC_DESK, which the admin judge holds the relay's /healthz to",
      relay_env.get("DESK_PUBLIC_URL") == kp.PUBLIC_DESK, str(relay_env.get("DESK_PUBLIC_URL")))
check("and kp.PUBLIC_DESK is the desk host the run-of-show gives the room, the community cluster's",
      kp.PUBLIC_DESK == f"https://{sdh.DESKS['watch-it-burn-community'][0]}", kp.PUBLIC_DESK)
check("the trace seeds record that desk, the one their HC-666 read and Joker report go to",
      st.SEED_DESK == kp.PUBLIC_DESK and dict(st.PREFLIGHT).get("one-desk") is kp._desk)
site = container("fake-ticket", "site", components_of("kubecon-community"))
check("kubecon-community's desk is the container the probe's DESK_ENV_CHECK execs into",
      kp.DESK_ENV_CHECK[kp.DESK_ENV_CHECK.index("-c") + 1] == site["name"] == "site"
      and "deploy/fake-ticket" in kp.DESK_ENV_CHECK)
check("it labels the token's reports kp.DESK_REMOTE_CLUSTER and reads the token from kp.DESK_TOKEN_SECRET",
      site["env"].get("DESK_REMOTE_CLUSTER", {}).get("value") == kp.DESK_REMOTE_CLUSTER
      and site["env"].get("DESK_REPORT_TOKEN", {}).get("valueFrom", {}).get("secretKeyRef", {}).get("name")
      == kp.DESK_TOKEN_SECRET, json.dumps(site["env"])[:300])
check("kubecon-community adds the remote-reports component and kubecon-private does not",
      DESK_REMOTE_COMPONENT in components_of("kubecon-community")
      and DESK_REMOTE_COMPONENT not in components_of("kubecon-private"))
check("the bot's container is the one the probe's DESK_CHECK execs into",
      kp.DESK_CHECK[kp.DESK_CHECK.index("-c") + 1] == "shim" and "deploy/workshop-mcp" in kp.DESK_CHECK)


print("== the desk's /desk-reset, on the real ticket_site.py ==")
spec = importlib.util.spec_from_file_location("ticket_site_1159", AI / "ticket_site.py")
ts = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ts)
server = ts.Server(("127.0.0.1", 0), ts.Handler)
threading.Thread(target=server.serve_forever, daemon=True).start()
DESK = f"http://127.0.0.1:{server.server_address[1]}"


def post(path: str, body: bytes, headers: dict | None = None, host: str = "support.burritobot.co") -> tuple[int, dict | str]:
    req = urllib.request.Request(DESK + path, data=body, method="POST", headers={"Host": host, **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            raw = r.read().decode()
            code = r.status
    except urllib.error.HTTPError as e:
        raw, code = e.read().decode(), e.code
    try:
        return code, json.loads(raw)
    except ValueError:
        return code, raw


def stock() -> None:
    """A practice run's leftovers on an emptied desk: two room tickets, a presenter ticket, a row from each cluster."""
    ts.LANDINGS.clear()
    ts.clear_filed_tickets()
    for text in ("my order is late", "the salsa is too hot"):
        post("/submit", urllib.parse.urlencode({"body": text}).encode(),
             {"Content-Type": "application/x-www-form-urlencoded"})
    post("/presenter-ticket", json.dumps({"body": "the presenters' demo ticket"}).encode(),
         {"Content-Type": "application/json"})
    ts.record_landing("joker-agatha-the-gargoyle", True, "", "registry.burritobot.co/x", "", "Deployment", "community")
    ts.record_landing("joker-agatha-the-gargoyle", True, "", "registry.burritobot.co/x", "", "Deployment", "private")


def filed() -> list[str]:
    return sorted(k for k in ts.TICKETS if k not in ts.FIXED_TICKETS)


stock()
check("the practice run left two room tickets, a presenter HC-9xx and a row from each cluster",
      len(filed()) == 3 and any(ts.is_presenter_ticket(k) for k in filed()) and len(ts.LANDINGS) == 2,
      f"{filed()} {len(ts.LANDINGS)}")
before = (filed(), len(ts.LANDINGS))
for why, headers, host in (("through a proxy that names a client (the console's X-Forwarded-For)",
                            {"X-Forwarded-For": "203.0.113.9"}, "support.burritobot.co"),
                           ("on the deployments host", {}, "deployments.burritobot.co")):
    code, _ = post(ts.DESK_RESET_PATH, b"{}", {"Content-Type": "application/json", **headers}, host)
    check(f"a reset {why} is refused and changes nothing", code in (403, 404) and (filed(), len(ts.LANDINGS)) == before,
          str(code))
check("a pod address, the bot's tool pod or the console's, may not reset; only the pod's own loopback, unproxied",
      not ts.reset_allowed("10.0.3.7", None) and not ts.reset_allowed("127.0.0.1", "10.0.3.7")
      and ts.reset_allowed("127.0.0.1", None) and ts.reset_allowed("::1", ""))
for body in (b"[]", b'{"tickets": "yes"}', b"not json"):
    code, _ = post(ts.DESK_RESET_PATH, body, {"Content-Type": "application/json"})
    check(f"a reset with body {body!r} is a 400 and changes nothing", code == 400 and (filed(), len(ts.LANDINGS)) == before,
          str(code))
code, got = post(ts.DESK_RESET_PATH, b"{}", {"Content-Type": "application/json"})
check("from the loopback, the reset clears both clusters' rows and keeps every ticket by default",
      code == 200 and got == {"rows_cleared": 2, "tickets_cleared": 0, "rows_left": 0, "filed_left": 3,
                              "fixed_kept": len(ts.FIXED_TICKETS)} and ts.LANDINGS == [] and filed() == before[0], str(got))
check("so the deployments page reads empty", ts.deployments() == [])
code, got = post(ts.DESK_RESET_PATH, json.dumps({"tickets": True}).encode(), {"Content-Type": "application/json"})
check("with tickets, it clears every filed ticket, the presenters' HC-9xx included, and keeps every fixed one",
      code == 200 and got["tickets_cleared"] == 3 and got["filed_left"] == 0 and filed() == []
      and all(k in ts.TICKETS for k in ts.FIXED_TICKETS) and ts.ROOM_TICKET_ID in ts.TICKETS, str(got))
_, again = post("/presenter-ticket", json.dumps({"body": "the next run's demo ticket"}).encode(),
                {"Content-Type": "application/json"})
check("and the presenter range starts again at HC-900", isinstance(again, dict) and again.get("id") == "HC-900", str(again))
console = (AI / "console.conf").read_text(encoding="utf-8")
desk_server = console[console.index("server_name ~^support("):]
desk_server = desk_server[:desk_server.index("\n}\n")]
check("the console refuses /desk-reset on the desk's public server",
      re.search(r"location = /desk-reset \{\s*deny all;", desk_server) is not None, desk_server[:400])


print("== fleet.sh desk-reset, its in-pod script run against the real desk ==")
FAKE_AWS = r'''#!/usr/bin/env bash
args=("$@"); out=""; name=""
for ((i=0; i<${#args[@]}; i++)); do
  [[ "${args[$i]}" == --kubeconfig ]] && out="${args[$((i+1))]}"
  [[ "${args[$i]}" == --name ]] && name="${args[$((i+1))]}"
done
printf 'current-context: arn:aws:eks:us-west-2:111122223333:cluster/%s\n' "${name}" >"${out}"
echo "${name}" >>"${FETCHES}"
'''
# kubectl: the context is read from the isolated kubeconfig; an exec into the desk's pod runs the script it was given
# with this test's desk in place of the pod's loopback port, so the request still comes from 127.0.0.1.
FAKE_KUBECTL = r'''#!/usr/bin/env python3
import json, os, subprocess, sys
a = sys.argv[1:]
with open(os.environ["CALLS"], "a") as f:
    f.write(json.dumps(a) + "\n")
if a[:2] == ["config", "current-context"]:
    print(open(os.environ["KUBECONFIG"]).read().split(": ", 1)[1].strip()); sys.exit(0)
if "exec" in a and "--" in a:
    cmd = a[a.index("--") + 1:]
    cmd[2] = cmd[2].replace("http://127.0.0.1:8080", os.environ["DESK"])
    sys.exit(subprocess.run([sys.executable] + cmd[1:]).returncode)
sys.exit(1)
'''
with tempfile.TemporaryDirectory() as t:
    fakebin = pathlib.Path(t, "bin")
    fakebin.mkdir()
    for tool, src in (("aws", FAKE_AWS), ("kubectl", FAKE_KUBECTL)):
        (fakebin / tool).write_text(src)
        (fakebin / tool).chmod(0o755)
    calls, fetches = pathlib.Path(t, "calls"), pathlib.Path(t, "fetches")
    states = pathlib.Path(t, "states")
    states.mkdir()

    def desk_reset(*args: str) -> subprocess.CompletedProcess:
        for p in (calls, fetches):
            p.write_text("")
        env = {**os.environ, "PATH": f"{fakebin}:{os.environ['PATH']}", "CALLS": str(calls), "FETCHES": str(fetches),
               "DESK": DESK, "KUBECONFIG": "/nonexistent-shared-config", "WIB_STATE_DIR": str(states), "TMPDIR": t}
        return subprocess.run(["bash", "-c", f"source '{FLEET}' >/dev/null 2>&1; cmd_desk_reset \"$@\"", "desk-reset",
                               *args], cwd=FLEET.parent, env=env, capture_output=True, text=True, timeout=120)

    check("fleet.sh dispatches desk-reset", "desk-reset) cmd_desk_reset" in FLEET.read_text(encoding="utf-8"))
    stock()
    r = desk_reset()
    out = r.stdout + r.stderr
    check("desk-reset clears the one page on watch-it-burn-community, from inside its desk's pod, keeping tickets",
          r.returncode == 0 and fetches.read_text().split() == ["watch-it-burn-community"] and ts.LANDINGS == []
          and len(filed()) == 3 and "cleared 2 deploy row(s) and 0 filed ticket(s)" in out, out)
    every = [json.loads(line) for line in calls.read_text().splitlines()]
    execs = [c for c in every if "exec" in c]
    check("with one exec, into fake-ticket's site container in agent, on the cluster's own context",
          len(execs) == 1 and execs[0][:8] == ["--context", "arn:aws:eks:us-west-2:111122223333:cluster/watch-it-burn-community",
                                              "-n", "agent", "exec", "deploy/fake-ticket", "-c", "site"], str(execs))
    check("and no call on any Secret, the agent/terminal-auth login above all (#1074)",
          not [c for c in every if "secret" in c or "terminal-auth" in " ".join(c)])
    stock()
    r = desk_reset("--tickets")
    check("desk-reset --tickets clears the filed tickets too, and keeps every fixed one",
          r.returncode == 0 and filed() == [] and ts.LANDINGS == [] and all(k in ts.TICKETS for k in ts.FIXED_TICKETS),
          r.stdout + r.stderr)
    for name in ("watch-it-burn-private", "watch-it-burn-private-b01", "watch-it-burn-007"):
        stock()
        r = desk_reset(name)
        check(f"desk-reset refuses {name} and reaches no cluster: the public desk is the one it clears",
              r.returncode == 2 and f"REFUSING {name}" in r.stdout + r.stderr and not fetches.read_text()
              and not calls.read_text() and len(ts.LANDINGS) == 2, r.stdout + r.stderr)
    ts.LANDINGS.clear()
    real_handler = ts.Handler.do_POST

    def no_route(self):  # a desk from before this change: /desk-reset is its plain 404
        if urllib.parse.urlsplit(self.path).path == ts.DESK_RESET_PATH:
            self._send(404, {"error": "not found"})
            return
        real_handler(self)

    ts.Handler.do_POST = no_route
    r = desk_reset()
    ts.Handler.do_POST = real_handler
    check("a desk that has no /desk-reset yet fails the reset and says to sync the ai-layer",
          r.returncode == 1 and "NOT reset" in r.stdout + r.stderr and "sync the ai-layer" in r.stdout + r.stderr,
          r.stdout + r.stderr)

server.shutdown()
print("== offline means offline ==")
_calls = no_cloud.calls()
check("no check above called aws, kubectl, eksctl, terraform or helm", not _calls, _calls)

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All one-desk tool checks passed.")
