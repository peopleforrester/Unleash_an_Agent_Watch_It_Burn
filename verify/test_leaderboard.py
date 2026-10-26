# ABOUTME: Offline tests for the challenge leaderboard (#307): every column reads a signal this repo actually
# ABOUTME: emits, every row is a cluster and never a person, and the fleet loader carries it with the fleet dashboard.
"""Nothing here reaches Datadog. The leaderboard is a dashboard of log and metric queries, and a query on a
field nobody writes is the quietest failure there is: the cell stays blank, and on a projector a blank cell
reads as "nobody has done it yet". So every column is held to the code that produces its signal: the tool
audit line, the villain roster, the Falco rule, the guard-proxy events and the cost gauge.
"""
from __future__ import annotations

import json
import pathlib
import re
import sys

import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "infra" / "datadog-fleet"))
import fleet_monitors as fm  # noqa: E402

failures: list[str] = []


def check(name: str, cond: bool) -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        failures.append(name)


defs = fm.load_monitors()
FILTER = defs["cluster_filter"]
board = fm.load_dashboard(fm.LEADERBOARD_FILE)
fleet = fm.load_dashboard(fm.DASHBOARD_FILE)
tables = [w["definition"] for w in board["widgets"] if w["definition"]["type"] == "query_table"]
table = tables[0] if tables else {"requests": [{"queries": [], "formulas": []}]}
req = table["requests"][0]
queries = {q["name"]: q for q in req["queries"]}
formulas = {f["formula"]: f for f in req["formulas"]}
note = "\n".join(w["definition"].get("content", "") for w in board["widgets"] if w["definition"]["type"] == "note")

print("== the leaderboard is loaded with the fleet ==")
check("leaderboard.yaml validates clean", fm.validate_dashboard(board, FILTER) == [])
check("the loader carries both dashboards, the leaderboard by its own label",
      [label for label, _ in fm.DASHBOARDS] == ["fleet dashboard", "challenge leaderboard"]
      and dict(fm.DASHBOARDS)["challenge leaderboard"] == fm.LEADERBOARD_FILE)
check("its title differs from the fleet dashboard's (the loader matches dashboards by title)",
      board["title"] != fleet["title"])

print("== a projector view: one table, a row per cluster, rows that stay put ==")
check("one per-cluster table", len(tables) == 1)
check("every metric query is one row per kube_cluster_name",
      all(q["query"].count("by {kube_cluster_name}") == 1 for q in queries.values() if q["data_source"] == "metrics"))
check("every logs query is grouped by kube_cluster_name and nothing else",
      all([g["facet"] for g in q["group_by"]] == ["kube_cluster_name"]
          for q in queries.values() if q["data_source"] == "logs"))
check("every reporting cluster has a row, scored or not (the agent heartbeat anchors the join)",
      "datadog.agent.running" in queries.get("online", {}).get("query", ""))
check("rows are sorted by cluster name, so nobody's row jumps when somebody scores",
      req["sort"]["order_by"] == [{"type": "group", "name": "kube_cluster_name", "order": "asc"}])
check("it covers a whole session without anyone setting the time picker", table.get("time", {}).get("live_span") == "4h")
aliases = [f.get("alias") for f in req["formulas"]]
check(f"columns for challenges 1 to 6 ({aliases})",
      [a.split()[0] for a in aliases[1:]] == ["1", "2", "3", "4", "5", "6"])
for name in ("c1", "c2", "c3", "c5", "c6"):
    fmts = formulas.get(name, {}).get("conditional_formats", [])
    check(f"{name}: a done cell is green with the log count hidden",
          fmts == [{"comparator": ">=", "value": 1, "palette": "white_on_green", "hide_value": True}])
check("challenges 7 and 8 are not columns, and the board says why",
      not any(a.split()[0] in ("7", "8") for a in aliases) and "7 and 8 are not on the board" in note)

print("== cluster names, never people ==")
text = json.dumps(board)
check("no query or label names a person (no claim fields, no email)",
      not re.search(r"claimed_by|claimed_at|email|@[a-z0-9.-]+\.[a-z]{2,}\b", text, re.I))
groups = set()
for q in queries.values():
    if q["data_source"] == "logs":
        groups |= {g["facet"] for g in q["group_by"]}
    else:
        groups |= set(re.findall(r"by \{([^}]*)\}", q["query"]))
check(f"the only unit anything is grouped by is the cluster ({sorted(groups)})", groups == {"kube_cluster_name"})

print("== every column reads a signal the platform actually emits ==")
docs = [d for d in yaml.safe_load_all((REPO / "gitops/ai-layer/resources.yaml").read_text()) if d]
deployments = {d["metadata"]["name"] for d in docs if d.get("kind") == "Deployment"}
search = {n: q.get("search", {}).get("query", "") for n, q in queries.items()}

audit = (REPO / "gitops/ai-layer/tool_audit.py").read_text()
mcp = (REPO / "gitops/ai-layer/workshop-mcp-server.py").read_text()
lab = (REPO / "gitops/ai-layer/web/lab.html").read_text()
check("C1: workshop-mcp is a Deployment in the agent bundle", "workshop-mcp" in deployments)
check("C1: the tool audit writes event tool_invocation with a pre phase, tool_name and tool_input",
      'EVENT = "tool_invocation"' in audit and '"phase": "pre", "tool_input"' in audit and '"tool_name": name' in audit)
check("C1: workshop-mcp builds its server with the audit", "AuditedFastMCP" in mcp)
check("C1: run_shell's argument is `command`, which is the @tool_input.command the query reads",
      re.search(r"def run_shell\(command: str", mcp) is not None and "@tool_input.command:*beacon*" in search.get("c1", ""))
check("C1: the lab's beacon address contains the word the query matches", "agenticburn.com/beacon" in lab)
check("C1: only the pre line, which is the only one that carries the arguments",
      "@phase:pre" in search.get("c1", "") and '"phase": "post", "outcome"' in audit and "tool_input" not in audit.split('"phase": "post"', 1)[1].split("\n", 1)[0])

readme = (REPO / "images/villains/README.md").read_text()
roster = set(re.findall(r"`([a-z][a-z-]+)`", readme.split("## Roster", 1)[1].split("## How", 1)[0]))
m = re.search(r"short_image:\(([^)]*)\)", search.get("c2", ""))
named = set(m.group(1).split(" OR ")) if m else set()
check(f"C2: the query names exactly the villain roster ({len(roster)} images)", named == roster and len(roster) >= 3)
check("C2: the lab's three cover images are on the roster",
      {"promo-mascot", "festival-promo", "loyalty-rewards"} <= roster
      and all(f"docker.io/peopleforrester/{n}:latest" in lab for n in ("promo-mascot", "festival-promo", "loyalty-rewards")))
platform_images = set()
for f in (REPO / "gitops").rglob("*.yaml"):
    platform_images |= set(re.findall(r"image:\s*\"?([^\s\"#]+)", f.read_text(errors="replace")))
short = {re.split(r"[:@]", i.rsplit("/", 1)[-1])[0] for i in platform_images}
check("C2: no platform image shares a short name with a villain, so a running platform never scores",
      not (short & roster))

falco = (REPO / "gitops/bootstrap/apps/falco.yaml").read_text()
check("C3: Falco has the rule the query names", "- rule: Recipe Snoop In Agent Namespace" in falco
      and '@rule:"Recipe Snoop In Agent Namespace"' in search.get("c3", ""))
check("C3: Falco logs JSON, so the rule name is an attribute", "json_output: true" in falco)
check("C3: Falco runs in the security namespace the query filters on",
      re.search(r"destination:\s*\n(?:\s+\w+:.*\n)*?\s+namespace: security", falco) is not None
      and "kube_namespace:security" in search.get("c3", ""))

proxy = (REPO / "gitops/ai-layer/guard-proxy/proxy.py").read_text()
check("C4: guard-proxy exports gen_ai.client.cost", '"gen_ai.client.cost"' in proxy
      and "gen_ai.client.cost" in queries.get("c4", {}).get("query", ""))
check("C5/C6: guard-proxy is a Deployment in the agent bundle", "guard-proxy" in deployments)
check("C5: guard-proxy logs event output_scrub when the output guard redacts",
      'extra={"event": "output_scrub"}' in proxy and "@event:output_scrub" in search.get("c5", ""))
check("C6: guard-proxy logs both input-guard refusals",
      all(f'extra={{"event": "{e}"}}' in proxy for e in ("input_blocklist_hit", "input_classifier_block"))
      and "@event:(input_blocklist_hit OR input_classifier_block)" in search.get("c6", ""))
check("guard-proxy logs the event as a JSON attribute", 'payload["event"] = event' in proxy)

print("== validation catches the mistakes that would leave a column blank ==")
def broken(name, **over):
    b = json.loads(json.dumps(board))
    q = next(q for w in b["widgets"] for r in w["definition"].get("requests", []) for q in r["queries"] if q["name"] == name)
    q.update(over)
    return fm.validate_dashboard(b, FILTER)
check("a logs query not filtered to the fleet", any("not filtered" in p for p in broken("c3", search={"query": "@rule:x"})))
check("a logs query not grouped by cluster",
      any("not grouped" in p for p in broken("c5", group_by=[{"facet": "host", "limit": 500}])))

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All leaderboard checks passed.")
