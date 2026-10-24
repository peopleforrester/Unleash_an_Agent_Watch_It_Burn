# ABOUTME: Alloy puts namespace, pod, container and app on every Loki stream (#464), so the #190 audit trail
# ABOUTME: is selectable by stream; checks the relabel wiring in gitops/apps/alloy.yaml and the queries that rely on it.
"""Offline. loki.source.kubernetes drops every __meta_ label and adds only job, so a config that forwards
discovery.kubernetes straight to it gives every stream the one label {job="loki.source.kubernetes.pods"}. A
query then cannot select the agent namespace or one pod and has to line-filter every stream in Loki.

What breaks it, silently in each case:
- loki.source.kubernetes reads discovery.kubernetes again, so the relabel is skipped;
- a rule is lost or retargeted, so the label a query selects on is missing and the query finds nothing;
- the app.kubernetes.io/name rule loses its `(.+)` regex, so a pod without that label gets app="" and loses
  the app label its `app` pod label gave it (workshop-mcp carries only `app`);
- a labelkeep or labeldrop strips the __meta_ labels loki.source.kubernetes needs to find the pod.

The relabel's runtime output was checked against Alloy v1.19.2 (the appVersion of chart 1.12.1) on static
targets when this was written; here the config is read as text, since the offline suite has no Alloy binary.
"""
from __future__ import annotations

import pathlib
import re
import sys

import yaml

REPO = pathlib.Path(__file__).resolve().parent.parent

failures: list[str] = []


def check(name: str, cond: bool) -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        failures.append(name)


def block(src: str, header: str) -> str:
    """The body of the first `header {...}` block, braces balanced; empty when absent."""
    start = src.find(header)
    if start < 0:
        return ""
    i = src.index("{", start)
    depth = 0
    for j in range(i, len(src)):
        depth += {"{": 1, "}": -1}.get(src[j], 0)
        if depth == 0:
            return src[i + 1:j]
    return ""


def attrs(body: str) -> dict[str, str]:
    return {k: v.strip() for k, v in re.findall(r"^\s*(\w+)\s*=\s*(.+?)\s*$", body, re.M)}


app = yaml.safe_load((REPO / "gitops/apps/alloy.yaml").read_text(encoding="utf-8"))
config = app["spec"]["source"]["helm"]["valuesObject"]["alloy"]["configMap"]["content"]

print("== the pod targets go through discovery.relabel before loki.source.kubernetes ==")
relabel = block(config, 'discovery.relabel "pods"')
source = block(config, 'loki.source.kubernetes "pods"')
check("there is a discovery.relabel \"pods\"", relabel != "")
check("it relabels the discovery.kubernetes pod targets",
      re.search(r"^\s*targets\s*=\s*discovery\.kubernetes\.pods\.targets\s*$", relabel, re.M) is not None)
check("loki.source.kubernetes reads the relabelled output, not the raw targets",
      attrs(source).get("targets") == "discovery.relabel.pods.output")

rules = []
rest = relabel
while (body := block(rest, "rule")) != "":
    rules.append(attrs(body))
    rest = rest[rest.index(body) + len(body):]

print("== each stream label comes from the pod's metadata ==")
WANT = {
    "namespace": "__meta_kubernetes_namespace",
    "pod": "__meta_kubernetes_pod_name",
    "container": "__meta_kubernetes_pod_container_name",
}
for target, meta in WANT.items():
    check(f"{target} is copied from {meta}", any(
        r.get("source_labels") == f'["{meta}"]' and r.get("target_label") == f'"{target}"'
        and r.get("action", '"replace"') == '"replace"' for r in rules))

app_rules = [r for r in rules if r.get("target_label") == '"app"']
sources = [r.get("source_labels") for r in app_rules]
check("app comes from the app pod label, then app.kubernetes.io/name overrides it",
      sources == ['["__meta_kubernetes_pod_label_app"]', '["__meta_kubernetes_pod_label_app_kubernetes_io_name"]'])
check("the app.kubernetes.io/name rule only fires when that label is set, so it never blanks app",
      len(app_rules) == 2 and app_rules[1].get("regex") == '"(.+)"')
check("no rule keeps or drops labels, so the __meta_ labels the source needs survive",
      not any(r.get("action") in ('"labelkeep"', '"labeldrop"', '"keep"', '"drop"') for r in rules))

print("== the audit trail is queried by stream ==")
resources = list(yaml.safe_load_all((REPO / "gitops/ai-layer/resources.yaml").read_text(encoding="utf-8")))
mcp = next((d for d in resources if d and d.get("kind") == "Deployment"
            and d["metadata"]["name"] == "workshop-mcp"), {})
tmpl = mcp.get("spec", {}).get("template", {})
check("workshop-mcp's pod carries app: workshop-mcp, which the queries select on",
      tmpl.get("metadata", {}).get("labels", {}).get("app") == "workshop-mcp")
check("its container is shim, which the live test expects on the stream",
      [c["name"] for c in tmpl.get("spec", {}).get("containers", [])] == ["shim"])

audit = (REPO / "gitops/ai-layer/tool_audit.py").read_text(encoding="utf-8")
live = (REPO / "verify/test_tool_audit_live.py").read_text(encoding="utf-8")
check("tool_audit.py documents the stream-selected query",
      '{namespace="agent", app="workshop-mcp"} |= "tool_invocation" | json' in audit)
check("the live test selects the workshop-mcp stream", """'{namespace="%s", app="workshop-mcp"} |= "%s" | json'""" in live)
check("neither line-filters every stream any more", '{job=~".+"}' not in audit and '{job=~".+"}' not in live)

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All Alloy label checks passed.")
