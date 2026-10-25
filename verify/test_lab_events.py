# ABOUTME: The lab progress markers (#150) are one contract in five places: the page that sends them, the nginx
# ABOUTME: route, the collector pipeline that enforces them, the dashboard that reads them, and the attendee overlay.
"""Pins the fleet-analytics path end to end, offline.

The failure this prevents is a drift between halves that are each fine on their own: the page sends an
attribute the collector's keep-list strips, so a dashboard column is empty all session; or the attendee overlay
forgets the lab pipelines, so every student's clicks land in the student's own org instead of the instructor's;
or a route that is reachable from the internet starts accepting spans the collector does not police. None of
those breaks anything a student can see, which is exactly why nobody would notice before the post-mortem.

The behaviour of lab-events.js itself (payload shape, control transitions) is run under node in
test_lab_events_behaviour.py, in the E2E suite.
"""
from __future__ import annotations

import json
import pathlib
import re
import sys

import yaml

REPO = pathlib.Path(__file__).resolve().parent.parent
JS = (REPO / "gitops/ai-layer/web/lab-events.js").read_text(encoding="utf-8")
LAB = (REPO / "gitops/ai-layer/web/lab.html").read_text(encoding="utf-8")
BB = (REPO / "gitops/ai-layer/web/burritbot.html").read_text(encoding="utf-8")
CONF = (REPO / "gitops/ai-layer/console.conf").read_text(encoding="utf-8")
KUST = yaml.safe_load((REPO / "gitops/ai-layer/kustomization.yaml").read_text(encoding="utf-8"))
sys.path.insert(0, str(REPO / "verify"))
import collector_render  # noqa: E402  the config each profile's collector runs, overlay included (#500)
DASH_PATH = REPO / "infra/terraform/dashboards/fleet-analytics.json"
TF = (REPO / "infra/terraform/dashboards/main.tf").read_text(encoding="utf-8")

failures: list[str] = []


def check(name: str, cond: bool) -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        failures.append(name)


# Comments document what is NOT sent, by name, so the code checks below read the code only.
CODE = "\n".join(l for l in JS.split("\n") if not l.strip().startswith("//"))
EVENTS = set(re.findall(r"'(lab\.[a-z]+(?:\.[a-z]+)?)'", CODE))
SENT_KEYS = set(re.findall(r"'((?:witb\.lab|session)\.[a-z_]+)'", CODE))
# The lab pipelines live in the Datadog overlay (they have nowhere to go without Datadog), so the checks read
# the config a collector actually runs on each profile with datadog-secret present.
CFG = collector_render.collector_config("instructor", True)
PIPES = CFG["service"]["pipelines"]
ATTENDEE = collector_render.collector_config("attendee", True)["service"]["pipelines"]

print("== the page is shipped and started ==")
check("lab-events.js is in the console-src ConfigMap",
      any(g["name"] == "console-src" and "web/lab-events.js" in g["files"] for g in KUST["configMapGenerator"]))
check("lab.html loads lab-events.js", '<script src="lab-events.js"></script>' in LAB)
check("lab.html starts it with the friendly name and the role, and nothing else",
      re.search(r"WIBLab\.start\(\{alias:[^}]*ident[^}]*,\s*role:role\}\)", LAB) is not None)
check("the e-mail (?user=) is never handed to it", not re.search(r"WIBLab\.start\([^)]*user", LAB))
steps = re.findall(r'(<div class="(step[^"]*)"[^>]*>)\s*<div class="h"><div class="num">([^<]*)<', LAB)
check(f"every guide step ({len(steps)}) resolves to a challenge id (a cN class, a numeric .num, or data-lab)",
      len(steps) == LAB.count('<div class="step') and len(steps) >= 11
      and all(re.search(r'\bc\d\b', cls) or num.isdigit() or 'data-lab=' in tag for tag, cls, num in steps))

print("== what the page sends ==")
check(f"it emits the documented events {sorted(EVENTS)}",
      EVENTS == {"lab.session.start", "lab.heartbeat", "lab.step.open", "lab.hint.open", "lab.command.send",
                 "lab.feedback.open", "lab.control.installed", "lab.control.removed"})
check("it posts only to /lab-events (and reads /controls)",
      set(re.findall(r"'(/[a-z-]+)'", CODE)) == {"/lab-events", "/controls"})
check("it never reads the query string", "location.search" not in CODE and "URLSearchParams" not in CODE)
# The command blocks include the student's Datadog login; their text must never be read, only their position.
check("it never reads element text other than a step number",
      re.findall(r"\.(textContent|innerText|innerHTML|value)\b", CODE) == ["textContent"]
      and "num.textContent" in CODE)
check("no hover or pointer tracking", not re.search(r"mouse(over|move|enter)|pointer(move|over)|'hover'", CODE))
check("Global Privacy Control and Do Not Track switch it off", "globalPrivacyControl" in CODE and "doNotTrack" in CODE)
check("it has a single off switch", re.search(r"^\s*var ENABLED = (true|false);", JS, re.M) is not None)
# Question 693 (decisions.md, 2026-10-25): Michael decided the markers stay OFF until the lab's privacy warning
# tells attendees what is recorded. Turning them on is a change to this line AND to the warning, together, so
# whoever flips it also updates this check with the wording that was agreed.
check("the markers are OFF until the disclosure wording is settled (question 693)",
      re.search(r"^\s*var ENABLED = false;", JS, re.M) is not None)
check("the service is in the BurritoBot family", "'burritobot-lab'" in CODE)

print("== every badge control maps to its challenge ==")
badge_keys = {k for k in re.findall(r"key:'([a-z_]+)'", BB)} - {"falco"}
mapped = dict(re.findall(r"^\s+([a-z_]+): '(\d)',?$", JS, re.M))
check(f"the page maps every BurritoBot badge control except Falco {sorted(badge_keys)}", badge_keys <= set(mapped))
check("each mapping is a real challenge, 1 to 8", all(v in "12345678" for v in mapped.values()))

print("== the nginx route ==")
m = re.search(r"location = /lab-events \{(.*?)\n  \}", CONF, re.S)
route = m.group(1) if m else ""
check("/lab-events exists", bool(route))
check("POST only", "limit_except POST { deny all; }" in route)
check("bodies are capped", re.search(r"client_max_body_size \d+k;", route) is not None)
check("rate-capped, with the zone declared at http level",
      "limit_req zone=wib_lab_events" in route and re.search(r"^limit_req_zone .* zone=wib_lab_events:", CONF, re.M) is not None)
check("resolved at request time, so a missing collector cannot stop the console starting",
      "resolver " in route and re.search(r"set \$wib_lab_otlp http://[^;]+:4319;", route) is not None
      and "proxy_pass $wib_lab_otlp/v1/traces;" in route)
check("it targets the lab receiver, never the main OTLP port", ":4318" not in route and ":4317" not in route)
check("no client address is forwarded", "X-Forwarded-For" not in route and "X-Real-IP" not in route)

print("== the collector enforces the contract ==")
check("a dedicated otlp/lab receiver on 4319", CFG["receivers"]["otlp/lab"]["protocols"]["http"]["endpoint"].endswith(":4319"))
check("the Service exposes 4319 on every profile",
      all(collector_render.helm_values(p)["ports"].get("otlp-lab", {}).get("servicePort") == 4319
          for p in collector_render.PROFILE_APP))
check("no other pipeline reads otlp/lab", [p for p, c in PIPES.items() if "otlp/lab" in c.get("receivers", [])] == ["traces/lab"])
check("traces/lab reads only otlp/lab", PIPES["traces/lab"]["receivers"] == ["otlp/lab"])
procs = PIPES["traces/lab"]["processors"]
check("the contract runs before anything else touches the span",
      procs[:3] == ["memory_limiter", "filter/lab_contract", "transform/lab_contract"])
filt = CFG["processors"]["filter/lab_contract"]["traces"]
check("non-lab spans are dropped", any("not IsMatch(name" in c and "lab" in c for c in filt["span"]))
check("span events are dropped", bool(filt.get("spanevent")))
stmts = {g["context"]: g["statements"] for g in CFG["processors"]["transform/lab_contract"]["trace_statements"]}
check("the resource is reset to burritobot-lab",
      'keep_keys(attributes, ["service.name"])' in stmts["resource"]
      and 'set(attributes["service.name"], "burritobot-lab")' in stmts["resource"])
keep = next((s for s in stmts["span"] if s.startswith("keep_keys(")), "")
KEPT = set(re.findall(r'"([a-z_.]+)"', keep))
check(f"the collector keep-list equals what the page sends {sorted(SENT_KEYS)}", KEPT == SENT_KEYS)
check("attribute values are truncated", any(s.startswith("truncate_all(attributes,") for s in stmts["span"]))
dims = {d["name"] for d in CFG["connectors"]["span_metrics/lab"]["dimensions"]}
check("session.id is not a metric dimension (cardinality)", "session.id" not in dims)
check("every metric dimension is an attribute the page sends", dims <= SENT_KEYS)
check("the lab connector feeds the lab metrics pipeline",
      "span_metrics/lab" in PIPES["traces/lab"]["exporters"] and PIPES["metrics/lab"]["receivers"] == ["span_metrics/lab"])
check("on an instructor cluster both lab pipelines export to its own org (the instructor org)",
      PIPES["traces/lab"]["exporters"] == ["datadog", "span_metrics/lab", "debug"]
      and PIPES["metrics/lab"]["exporters"] == ["datadog", "debug"])

print("== attendee clusters ship the markers to the instructor org only ==")
check("traces/lab -> datadog/admin, not the student's org",
      ATTENDEE.get("traces/lab", {}).get("exporters") == ["datadog/admin", "span_metrics/lab", "debug"])
check("metrics/lab -> datadog/admin, not the student's org",
      ATTENDEE.get("metrics/lab", {}).get("exporters") == ["datadog/admin", "debug"])
check("the attendee lab pipelines process exactly as the instructor ones do",
      all(ATTENDEE[k]["receivers"] == PIPES[k]["receivers"] and ATTENDEE[k]["processors"] == PIPES[k]["processors"]
          for k in ("traces/lab", "metrics/lab")))

print("== without Datadog the markers go nowhere ==")
# relay.yaml carries the lab pipelines exporting to debug and the lab connector only, so a cluster with no
# datadog-secret receives the markers and drops them; the Datadog overlay is what adds an org (#500's rule:
# an overlay changes exporter lists only). The Community (burn) cluster's overlay adds its own org, which
# the fleet dashboard leaves out by default because that cluster is shared by the whole room.
for prof in collector_render.PROFILE_APP:
    pipes = collector_render.collector_config(prof, False)["service"]["pipelines"]
    check(f"{prof}, no datadog-secret: the lab pipelines export to debug only",
          pipes["traces/lab"]["exporters"] == ["span_metrics/lab", "debug"] and pipes["metrics/lab"]["exporters"] == ["debug"])
burn = collector_render.collector_config("burn", True)["service"]["pipelines"]
check("burn with datadog-secret: the lab pipelines go to its own org",
      burn["traces/lab"]["exporters"][0] == "datadog" and burn["metrics/lab"]["exporters"][0] == "datadog")

print("== the dashboard reads what is sent ==")
dash = json.loads(DASH_PATH.read_text(encoding="utf-8"))
blob = json.dumps(dash)
check("the Terraform module manages it", 'file("${path.module}/fleet-analytics.json")' in TF)
used_events = set(re.findall(r"span\.name:(lab\.[a-z.]+?)[,}]", blob))
check(f"every lab event the dashboard reads is one the page emits {sorted(used_events)}", used_events and used_events <= EVENTS)
check("it shows progress (fixes), stalls (hints) and presence (heartbeats)",
      {"lab.control.installed", "lab.hint.open", "lab.heartbeat"} <= used_events)
used_tags = set(re.findall(r"\b(witb\.lab\.[a-z_]+)\b", blob)) - {"witb.lab.calls"}
check(f"every witb.lab tag it groups or filters by is a metric dimension {sorted(used_tags)}", used_tags <= dims)
check("the metric name matches the connector namespace",
      "witb.lab.calls" in blob and CFG["connectors"]["span_metrics/lab"]["namespace"] == "witb.lab")
tv = {t["name"]: t["prefix"] for t in dash["template_variables"]}
check("cluster and role template variables", tv == {"cluster": "kube_cluster_name", "role": "witb.lab.role"})
# By cluster NAME: an admin cluster's lab opened without ?role= reports role=student.
check("it defaults to the attendee clusters",
      next(t["default"] for t in dash["template_variables"] if t["name"] == "cluster") == "watch-it-burn-attendee-*")
queries = re.findall(r'"query": "([^"]+)"', blob)
check("every lab metric query honours $cluster and $role",
      all("$cluster" in q and "$role" in q for q in queries if "witb.lab.calls" in q))
check("the fork bomb and guardrail catches are on it",
      "Fork Bomb In Workload Container" in blob and "input_blocklist_hit" in blob)

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    sys.exit(1)
print("All lab-events checks passed.")
