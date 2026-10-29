# ABOUTME: Holds the trace walk-through's Grafana view (#500) to the spans it reads, one Tempo panel per guardrail
# ABOUTME: beat (C5, C6, C7), and to the run-of-show: the segment its row is titled for, the beats' order, the URL.
"""Why this exists (#500, #675).

The trace walk-through shows that each guardrail did its job, for the beats just run: the C5 reply that came back
redacted, the C6 injection blocked at zero tokens, the C7 call that never reached read_internal_config. Datadog
Agent Observability is the primary surface and needs a Datadog org pool (#454); without one the run-of-show
falls back to a Grafana view on the private cluster, which reads Tempo.

A TraceQL query that names a span or an attribute nobody emits returns an empty panel, and an empty panel on
stage reads as "the guardrail did nothing". So each query is checked here against the code that produces what
it looks for, not just for being present. The queries themselves were run against Tempo 3.0.3 (the deployed
version) on synthetic traces of these shapes when this was written, each returning only its own trace; that
needs a Tempo binary and stays out of the offline suite.

The row kept the seven-segment plan's "Segment 6" title, in that plan's C6, C5, C7 order, after the run-of-show
moved the walk-through to segment 5 and the challenges to C5, C6, C7 (#675). So the segment number and the beat
order are read from the run-of-show's headings, not written here, and the file is named for the walk-through
rather than for a segment number.
"""
from __future__ import annotations

import json
import pathlib
import re
import sys

import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
failures: list[str] = []


def check(name: str, cond: bool) -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        failures.append(name)


cm = yaml.safe_load((REPO / "observability-idp/grafana/dashboards/agent-observability.yaml").read_text(encoding="utf-8"))
dash = json.loads(cm["data"]["agent-observability.json"])
tables = [p for p in dash["panels"] if p.get("type") == "table"]
beat = {t: next((p for p in tables if p["title"].startswith(t + ":")), None) for t in ("C6", "C5", "C7")}
other = next((p for p in tables if p["title"].startswith("C7, the other half")), None)


def query(p) -> str:
    return " ".join(t.get("query", "") for t in (p or {}).get("targets", []))


PROXY = (REPO / "gitops/ai-layer/guard-proxy/proxy.py").read_text(encoding="utf-8")
chat = PROXY[PROXY.index("def _handle_chat"):]
chat = chat[:chat.index("def log_message")]

print("== the dashboard ships to the admin cluster's Grafana ==")
check("the dashboard ConfigMap carries the sidecar label", cm["metadata"]["labels"].get("grafana_dashboard") == "1")
apps = yaml.safe_load((REPO / "gitops/bootstrap/apps/grafana-dashboards.yaml").read_text(encoding="utf-8"))
check("grafana-dashboards syncs this directory", apps["spec"]["source"]["path"] == "observability-idp/grafana/dashboards")
sys.path.insert(0, str(REPO / "verify"))
from bootstrap_chart import deploys  # noqa: E402
check("the admin profile lists it", deploys("admin", "grafana-dashboards.yaml"))

print("== one Tempo panel per beat ==")
for t, p in beat.items():
    check(f"a {t} panel exists", p is not None)
check("the C7 companion panel exists", other is not None)
check("every beat panel reads the Tempo datasource (uid tempo)",
      all(p and p["datasource"].get("uid") == "tempo" and all(x["datasource"]["uid"] == "tempo" for x in p["targets"])
          for p in [*beat.values(), other]))
check("every beat query is TraceQL", all(p and all(x.get("queryType") == "traceql" for x in p["targets"])
                                             for p in [*beat.values(), other]))
check("the default range covers a whole walk-through (30 minutes or more)",
      re.fullmatch(r"now-(\d+)m", dash["time"]["from"]) is not None and int(dash["time"]["from"][4:-1]) >= 30)

print("== C6: a /chat root with no agent.forward under it ==")
q6 = query(beat["C6"])
check("C6 selects guard-proxy's /chat root and excludes traces that forwarded to the agent",
      re.search(r'\{ name = "agent\.forward" \} !<< \{[^}]*resource\.service\.name = "burritobot"[^}]*span\.url\.path = "/chat"', q6) is not None)
check("C6 leaves out the 400 for an empty prompt", "span.http.response.status_code = 200" in q6)
check("guard-proxy names its forward span agent.forward", 'start_as_current_span("agent.forward"' in chat)
check("guard-proxy's server span carries url.path", 'set_attribute("url.path", self.path)' in PROXY)
check("guard-proxy's service name is burritobot",
      "service.name=burritobot," in (REPO / "gitops/ai-layer/resources.yaml").read_text(encoding="utf-8"))
# The input guards return before the forward exists; if a later edit moved the forward up, every request would
# carry an agent.forward and the C6 panel would go empty.
first_forward = chat.index('start_as_current_span("agent.forward"')
check("both /chat input guards answer before any agent.forward span is opened",
      0 < chat.index('"input_blocklist_hit"') < first_forward and 0 < chat.index('"input_classifier_block"') < first_forward)
check("a guarded /chat answer reports zero input tokens", '"guarded": True, "input_tokens": 0' in chat)

print("== C5: the root span carries the reply the user got ==")
q5 = query(beat["C5"])
check("C5 matches the root's gen_ai.output.messages on the redaction marker",
      "span.gen_ai.output.messages =~" in q5 and "REDACTED" in q5 and "blocked by the output guardrail" in q5)
scrub_at = chat.index("output_scrub(reply)")
root_out = chat.index('_root_span.set_attribute("gen_ai.output.messages"')
check("guard-proxy sets the root's output AFTER the output guard rewrote the reply", root_out > scrub_at)
check("the chat child span keeps the model's own reply (set before the guard)",
      chat.index('chat_span.set_attribute("gen_ai.output.messages"') < scrub_at)
check("guard-proxy's hard-block reply is the text C5 matches", '"[blocked by the output guardrail]"' in chat)
res = (REPO / "gitops/ai-layer/resources.yaml").read_text(encoding="utf-8")
check("llm-guard's output Regex scanner redacts (it writes [REDACTED])", re.search(r"type: Regex[\s\S]*?redact: true", res) is not None)
# guard-proxy writes the message attributes itself whenever its mode is any capturing one (EVENT_ONLY included),
# so the check is the deployed mode against the set proxy.py accepts, on the guard-proxy Deployment.
gp = next(d for d in yaml.safe_load_all(res) if d and d.get("kind") == "Deployment" and d["metadata"]["name"] == "guard-proxy")
gp_env = {e["name"]: e.get("value") for c in gp["spec"]["template"]["spec"]["containers"] for e in c.get("env") or []}
accepted = re.search(r"_CAPTURE_CONTENT = _CAPTURE_MODE in \(([^)]*)\)", PROXY)
check("guard-proxy captures message content, so C5 and C7 have messages to match",
      accepted is not None and f'"{gp_env.get("OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT")}"' in accepted.group(1))

print("== C7: the weather-tool ask, with and without read_internal_config under it ==")
q7, q7b = query(beat["C7"]), query(other)
check("C7 finds the weather-tool ask with no execute_tool read_internal_config under it",
      q7.startswith('{ name = "execute_tool read_internal_config" } !<< {') and 'span.gen_ai.input.messages =~ ".*weather tool.*"' in q7)
check("its companion finds the /chat traces that did reach the tool",
      q7b.startswith('{ name = "execute_tool read_internal_config" } << {') and 'span.url.path = "/chat"' in q7b)
prompt = (REPO / "challenges/03-bad-mcp-excessive-agency/agent-prompt.txt").read_text(encoding="utf-8")
check("the C7 prompt says 'weather tool'", "weather tool" in prompt)
check("the lab's C7 prompt says it too", "weather tool" in (REPO / "gitops/ai-layer/web/lab.html").read_text(encoding="utf-8"))
shim = (REPO / "challenges/03-bad-mcp-excessive-agency/evil-mcp-shim/server.py").read_text(encoding="utf-8")
check("the rogue tool is named read_internal_config", "def read_internal_config(" in shim)

print("== the run-of-show names the surface and the URL ==")
ros = (REPO / "facilitation/kubecon-na-2026-run-of-show.md").read_text(encoding="utf-8")
# Since #687 each challenge's fix shows its own trace and there is no walk-through segment; the run-of-show's
# "The trace view without Datadog" section decides the surface, and the row is titled "Traces" to match.
heads = list(re.finditer(r"^### (.*)$", ros, re.M))
walk = next((h for h in heads if h.group(1).startswith("The trace view without Datadog")), None)
check("the run-of-show has the trace view section", walk is not None)
nxt = next((h for h in heads if h.start() > walk.start()), None)
seg = ros[walk.start():nxt.start() if nxt else len(ros)]
fleet = (REPO / "infra/terraform/fleet/fleet.sh").read_text(encoding="utf-8")
shared = re.search(r'SHARED_ADMIN_HOST="([a-z0-9.-]+)"', fleet).group(1)
url = f"https://grafana-{shared}/d/{dash['uid']}"
check(f"it names {url}, the presenters' shared cluster", url in seg)
check("the console routes grafana-<cluster> to Grafana",
      "grafana-[a-z0-9-]+" in (REPO / "gitops/ai-layer/console.conf").read_text(encoding="utf-8"))
check("it says Datadog when the pool is live and Grafana when not",
      "**Which surface is shown.**" in seg and "**Datadog pool live:**" in seg and "**No pool live:**" in seg)
check("it walks each beat's panel", all(f"**{b}:**" in seg for b in ("C5", "C6", "C7")))
check("it no longer says the fallback is undecided", "fall back to Grafana or Tempo and say" not in seg)

print("== the beats' row is titled Traces, in the challenges' run order ==")
# The order the room sees the beats is /kubecon's (Challenge 1 is C5, Challenge 3 C6, Challenge 4 C7).
_kc = (REPO / "gitops/ai-layer/web/kubecon.html").read_text(encoding="utf-8")
run_order = [b for b in re.findall(r'data-beat="(C\d)"', _kc) if b in ("C5", "C6", "C7")]
check("the stage runs C5, C6 and C7, in that order", run_order == ["C5", "C6", "C7"])
rows = [p for p in dash["panels"] if p.get("type") == "row"]
row = next((p for p in rows if "did each guardrail do its job?" in p["title"]), None)
check("the dashboard has the guardrail beats' row", row is not None)
title = row["title"]
check("the row is titled Traces, not for a segment that no longer exists", title.startswith("Traces:"))
check(f"the row lists the beats in the stage's order ({', '.join(run_order)})",
      f"({', '.join(run_order)}, newest first)" in title)
laid_out = [p["title"].split(":")[0] for p in sorted((beat[t] for t in run_order),
                                                      key=lambda p: (p["gridPos"]["y"], p["gridPos"]["x"]))]
check("the row's beat panels are laid out in that order", laid_out == run_order)
walked = sorted(run_order, key=lambda b: seg.index(f"**{b}:**"))
check("the section walks the panels in that order", walked == run_order)
check("the section names the row by its title", 'the "Traces" row' in seg)
rdy = (REPO / "docs/KUBECON-ABSTRACT-READINESS.md").read_text(encoding="utf-8")
check("the readiness file no longer notes a stale row title", 'still titled "Segment' not in rdy)

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All trace walk-through view checks passed.")
