# ABOUTME: Reproduces #679 offline: Argo CD v3.5.2's RespectIgnoreDifferences sync of the workshop-agent CRD, ported,
# ABOUTME: keeps the live tools array; ai-layer now syncs without it, so git's tools land on every profile.
#
# Why (#679). Git gave workshop-mcp twelve tools, read_support_ticket among them (#640), and both KubeCon clusters
# kept the older eleven. ai-layer showed Agent/workshop-agent OutOfSync, every auto-sync said serverside-applied,
# and the live list never changed. The cause is in Argo CD's controller/sync.go at v3.5.2, normalizeTargetResources:
# with RespectIgnoreDifferences=true it copies each ignored field from live into the target it applies, as the
# merge patch from the normalized live object to the live one. The Agent is a CRD, not in Argo CD's scheme, so that
# patch is an RFC 7386 JSON merge patch, which cannot name one element of an array: an ignore on evil-mcp's
# toolNames puts the WHOLE live tools array in the patch. restoreNonIgnoredFields, which repairs that collateral,
# walks maps only, and the tools array is a leaf to it, so the live array is what gets applied.
#
# The same copy froze guard-proxy's env on both clusters (a6af457's CONSOLE_ORIGIN). A Deployment is in the scheme,
# so there the copy is a strategic merge patch, and its $setElementOrder directive takes the env list's order from
# live: an entry appended by hand stays where live has it, the structured-merge diff still sees git's order, and the
# Deployment is OutOfSync for good. That was run with Argo CD's own code (k8s.io/apimachinery v0.36.1, decisions.md
# #679); this file holds the rule it leads to, that no app syncing with RespectIgnoreDifferences ignores anything
# inside a list. ai-layer has three such ignores, so it syncs without the option, with ApplyOutOfSyncOnly instead.
#
# This ports that function for a resource outside the scheme (the jq deletion is the real jq, as Argo CD's gojq
# del(<expression>)) and runs it on the committed Agent and each profile's rendered ai-layer ignores: once with the
# option the clusters had, which reproduces #679, and once with the committed syncOptions, which apply git's Agent.
# The port is held to VERSIONS.lock's Argo CD version: a version bump fails here until the port is read against the
# new sync.go.
from __future__ import annotations

import copy
import json
import pathlib
import re
import shutil
import subprocess
import sys

import yaml

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from bootstrap_chart import (APPS, IMAGE_REGISTRY, LAB_PLATFORM_GHCR, REPO, REVISION, app_names,  # noqa: E402
                             c7_control, for_c7_control, profiles, without_front_door)

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail and not ok else ""))
    if not ok:
        failures.append(name)


JQ = shutil.which("jq")
if not JQ:
    print("FAIL: jq is not on PATH; Argo CD's jqPathExpressions are jq, and this runs them as jq does", file=sys.stderr)
    sys.exit(1)

PORTED_FROM = "v3.5.2"
EVIL = '.spec.declarative.tools[] | select(.mcpServer.name == "evil-mcp") | .mcpServer.toolNames'
# What both KubeCon clusters carried on 2026-10-29: git's list before 0633ab0, the same eleven toggle-mcp-authz-on.sh's
# GOOD_TOOL held before cb296cb.
STALE_ELEVEN = ["lookup_customer_records", "check_inventory", "reorder_supply", "get_order_history",
                "get_marketing_intel", "search_web", "post_marketing", "get_vault_entry", "list_services",
                "deploy_app", "run_shell"]


# ---- the port: Argo CD v3.5.2 controller/sync.go, for a resource outside the scheme ------------------------------
def jq_delete(obj: dict, expression: str) -> dict:
    """Argo CD's jq normalizer: del(<expression>); a failing expression leaves the object as it was."""
    r = subprocess.run([JQ, "-c", f"del({expression})"], input=json.dumps(obj), capture_output=True, text=True)
    return json.loads(r.stdout) if r.returncode == 0 and r.stdout.strip() else obj


def normalize(obj: dict | None, expressions: list[str]) -> dict | None:
    if obj is None:
        return None
    for e in expressions:
        obj = jq_delete(obj, e)
    return obj


def create_merge_patch(a: dict, b: dict) -> dict:
    """jsonpatch.CreateMergePatch (evanphx/json-patch getDiff): maps recurse, anything else, arrays included, whole."""
    into: dict = {}
    for k, bv in b.items():
        if k not in a or type(a[k]) is not type(bv):
            into[k] = bv
        elif isinstance(bv, dict):
            d = create_merge_patch(a[k], bv)
            if d:
                into[k] = d
        elif a[k] != bv:
            into[k] = bv
    for k in a:
        if k not in b:
            into[k] = None
    return into


def apply_merge_patch(doc, patch):
    """jsonpatch.MergePatch, RFC 7386."""
    if not isinstance(patch, dict):
        return copy.deepcopy(patch)
    out = copy.deepcopy(doc) if isinstance(doc, dict) else {}
    for k, v in patch.items():
        if v is None:
            out.pop(k, None)
        else:
            out[k] = apply_merge_patch(out.get(k), v)
    return out


def restore_non_ignored_fields(patched: dict, original: dict, normalized_target: dict, normalized_live) -> None:
    """restoreNonIgnoredFields: undoes replace collateral, recursing through maps only."""
    for k, ov in original.items():
        pv, nv = patched.get(k), normalized_target.get(k)
        if k in patched and isinstance(pv, dict) and isinstance(ov, dict) and isinstance(nv, dict):
            nl = normalized_live.get(k) if isinstance(normalized_live, dict) else None
            restore_non_ignored_fields(pv, ov, nv, nl if isinstance(nl, dict) else None)
            continue
        if k in normalized_target and nv == ov and (k not in patched or pv != ov):
            patched[k] = ov
    for k in list(patched):
        if k not in original and isinstance(normalized_live, dict) and k in normalized_live:
            del patched[k]


def synced_target(target: dict, live: dict | None, expressions: list[str]) -> dict:
    """normalizeTargetResources for one resource: what a RespectIgnoreDifferences sync applies."""
    normalized_target = normalize(target, expressions)
    if live is None:
        return target
    normalized_live = normalize(live, expressions)
    live_for_patch = {k: v for k, v in live.items() if k != "status"}
    normalized_live_for_patch = {k: v for k, v in normalized_live.items() if k != "status"}
    patched = apply_merge_patch(normalized_target, create_merge_patch(normalized_live_for_patch, live_for_patch))
    restore_non_ignored_fields(patched, target, normalized_target, normalized_live)
    return patched


def out_of_sync(target: dict, live: dict, expressions: list[str]) -> bool:
    """The diff Argo CD shows: the two objects with the ignored fields deleted, spec compared."""
    return normalize(target, expressions)["spec"] != normalize(live, expressions)["spec"]


# ---- the inputs: the committed Agent, and each profile's rendered ai-layer ignores -------------------------------
print(f"== the port is of the Argo CD the clusters run ({PORTED_FROM}) ==")
lock = (REPO / "VERSIONS.lock").read_text(encoding="utf-8")
argocd = re.search(r"^argocd\s+chart \S+ / app (v\S+)", lock, re.M)
check(f"VERSIONS.lock's argocd app is {PORTED_FROM}, the sync.go this ports (a bump: re-read normalizeTargetResources)",
      argocd is not None and argocd.group(1) == PORTED_FROM, argocd.group(1) if argocd else "no argocd line")

AGENT = next(d for d in yaml.safe_load_all((REPO / "gitops/ai-layer/resources.yaml").read_text(encoding="utf-8"))
             if d and d.get("kind") == "Agent" and d["metadata"]["name"] == "workshop-agent")


def server(agent: dict, name: str) -> dict:
    return next(t["mcpServer"] for t in agent["spec"]["declarative"]["tools"] if t["mcpServer"]["name"] == name)


GIT_TOOLS = server(AGENT, "workshop-mcp")["toolNames"]
check("git's workshop-mcp list is the stale eleven plus read_support_ticket (#640)",
      [t for t in GIT_TOOLS if t != "read_support_ticket"] == STALE_ELEVEN and "read_support_ticket" in GIT_TOOLS)


def rendered_ai_layer(profile: str) -> dict:
    raw = without_front_door(for_c7_control((APPS / "ai-layer.yaml").read_text(encoding="utf-8"), c7_control(profile)))
    return yaml.safe_load(raw.replace(REVISION, "0" * 40).replace(IMAGE_REGISTRY, LAB_PLATFORM_GHCR))


def agent_ignores(app: dict) -> list[str]:
    return [e for i in app["spec"].get("ignoreDifferences") or []
            if i.get("group") == "kagent.dev" and i.get("kind") == "Agent" and i.get("name") in (None, "workshop-agent")
            for e in i.get("jqPathExpressions") or []]


def live_agent(workshop_tools: list[str] | None = None, evil_tools: list[str] | None = None,
               model_config: str | None = None) -> dict:
    """The committed Agent as a cluster holds it, with the server's own fields, and the given live edits."""
    live = copy.deepcopy(AGENT)
    live["metadata"].update({"namespace": "agent", "uid": "8d0c6f0e", "resourceVersion": "4242", "generation": 7})
    live["status"] = {"observedGeneration": 7, "conditions": [{"type": "Ready", "status": "True"}]}
    if workshop_tools is not None:
        server(live, "workshop-mcp")["toolNames"] = list(workshop_tools)
    if evil_tools is not None:
        server(live, "evil-mcp")["toolNames"] = list(evil_tools)
    if model_config is not None:
        live["spec"]["declarative"]["modelConfig"] = model_config
    return live


RESPECT = "RespectIgnoreDifferences=true"


def sync_options(app: dict) -> list[str]:
    return ((app.get("spec") or {}).get("syncPolicy") or {}).get("syncOptions") or []


def applied_by_sync(app: dict, target: dict, live: dict | None, expressions: list[str]) -> dict:
    """What one sync of this app applies for the resource: sync.go runs normalizeTargetResources only with the option."""
    return synced_target(target, live, expressions) if RESPECT in sync_options(app) else target


def in_sync_operation(app: dict, target: dict, live: dict | None, expressions: list[str]) -> bool:
    """Whether a sync applies the resource at all: with ApplyOutOfSyncOnly, only a missing or OutOfSync one."""
    if "ApplyOutOfSyncOnly=true" not in sync_options(app):
        return True
    return live is None or out_of_sync(target, live, expressions)


def after_sync(app: dict, target: dict, live: dict, expressions: list[str]) -> dict:
    return applied_by_sync(app, target, live, expressions) if in_sync_operation(app, target, live, expressions) else live


ai_profiles = [p for p in profiles() if "ai-layer" in app_names(p)]
check("every profile deploys ai-layer", ai_profiles == profiles(), str(ai_profiles))
check("only admin puts C7 on agentgateway's rule (c7Control gateway), the profile the web terminal's _c7gw names",
      [p for p in ai_profiles if c7_control(p) == "gateway"] == ["admin"])
for profile in ai_profiles:
    opts = sync_options(rendered_ai_layer(profile))
    check(f"{profile}: ai-layer syncs WITHOUT RespectIgnoreDifferences, so a sync applies git's objects (#679)",
          RESPECT not in opts, str(opts))
    check(f"{profile}: and with ApplyOutOfSyncOnly, so a sync leaves every Synced resource as it is",
          "ApplyOutOfSyncOnly=true" in opts, str(opts))
    check(f"{profile}: server-side apply with Force and selfHeal stay, so a git change still lands by itself",
          "ServerSideApply=true" in opts and "Force=true" in opts
          and rendered_ai_layer(profile)["spec"]["syncPolicy"]["automated"] == {"prune": True, "selfHeal": True})

for profile in ai_profiles:
    app = rendered_ai_layer(profile)
    old = copy.deepcopy(app)
    old["spec"]["syncPolicy"]["syncOptions"] = [o for o in sync_options(app) if o != "ApplyOutOfSyncOnly=true"] + [RESPECT]
    control, ignores = c7_control(profile), agent_ignores(app)
    stale = live_agent(workshop_tools=STALE_ELEVEN)
    print(f"== {profile} (c7Control {control}) ==")
    if control == "toolnames":
        check(f"{profile}: the Agent's ignores are evil-mcp's toolNames and modelConfig",
              ignores == [EVIL, ".spec.declarative.modelConfig"], str(ignores))
        frozen = after_sync(old, AGENT, stale, ignores)
        check(f"{profile}: #679 reproduced: with RespectIgnoreDifferences the sync applies the LIVE tools array",
              server(frozen, "workshop-mcp")["toolNames"] == STALE_ELEVEN, str(server(frozen, "workshop-mcp")["toolNames"]))
        check(f"{profile}: so the Agent stays OutOfSync, every auto-sync after it the same",
              out_of_sync(AGENT, after_sync(old, AGENT, frozen, ignores), ignores))
    else:
        check(f"{profile}: the Agent's only ignore is modelConfig, outside the tools array",
              ignores == [".spec.declarative.modelConfig"], str(ignores))
    check(f"{profile}: git's twelve show as drift on the stale Agent (OutOfSync), so selfHeal syncs it",
          out_of_sync(AGENT, stale, ignores))
    applied = after_sync(app, AGENT, stale, ignores)
    check(f"{profile}: the sync applies git's workshop-mcp list, read_support_ticket included",
          server(applied, "workshop-mcp")["toolNames"] == GIT_TOOLS, str(server(applied, "workshop-mcp")["toolNames"]))
    check(f"{profile}: and git's whole tools array, headersFrom included", applied["spec"]["declarative"]["tools"]
          == AGENT["spec"]["declarative"]["tools"])
    check(f"{profile}: after it the Agent is Synced", not out_of_sync(AGENT, applied, ignores))

    narrowed = live_agent(evil_tools=["get_weather"], model_config="bedrock-claude")
    if control == "toolnames":
        check(f"{profile}: a student's guard-mcp-on (evil-mcp narrowed to get_weather) shows no drift, so no selfHeal",
              not out_of_sync(AGENT, narrowed, ignores))
        kept = after_sync(app, AGENT, narrowed, ignores)
        check(f"{profile}: and a sync of anything else leaves it, with a per-cluster modelConfig, as the student set it",
              server(kept, "evil-mcp")["toolNames"] == ["get_weather"]
              and kept["spec"]["declarative"]["modelConfig"] == "bedrock-claude")
        both = live_agent(workshop_tools=STALE_ELEVEN, evil_tools=["get_weather"])
        reset = after_sync(app, AGENT, both, ignores)
        check(f"{profile}: the price: a commit that changes the Agent resets guard-mcp-on to git's full rogue list",
              server(reset, "evil-mcp")["toolNames"] == server(AGENT, "evil-mcp")["toolNames"]
              and server(reset, "workshop-mcp")["toolNames"] == GIT_TOOLS)
    else:
        check(f"{profile}: nothing on admin writes evil-mcp's list live, so a narrowed one is drift and selfHeal restores it",
              out_of_sync(AGENT, narrowed, ignores)
              and server(after_sync(app, AGENT, narrowed, ignores), "evil-mcp")["toolNames"]
              == server(AGENT, "evil-mcp")["toolNames"])
        tiered = live_agent(model_config="bedrock-claude")
        check(f"{profile}: a per-cluster modelConfig alone shows no drift, so a sync leaves it",
              not out_of_sync(AGENT, tiered, ignores)
              and after_sync(app, AGENT, tiered, ignores)["spec"]["declarative"]["modelConfig"] == "bedrock-claude")
    check(f"{profile}: a fresh cluster (no live Agent) gets git's Agent as committed",
          after_sync(app, AGENT, None, ignores) == AGENT)

print("== the stale clusters are converge's to repair until this reaches them ==")
fleet = (REPO / "infra/terraform/fleet/fleet.sh").read_text(encoding="utf-8")
check("fleet.sh repair_one runs repair_agent_tools", re.search(
    r"^repair_one\(\) \{\n(?:.*\n){0,8}?    repair_step repair_agent_tools \"\$\{name\}\" \"\$\{kcfg\}\"", fleet, re.M)
      is not None)
check("and repair_ai_layer_rollout, which judges a rollout by the hashed ConfigMap names, not the sync phase",
      re.search(r"^repair_one\(\) \{\n(?:.*\n){0,10}?    repair_step repair_ai_layer_rollout ", fleet, re.M) is not None)
shim = (REPO / "verify/test_fleet_converge_repairs.sh").read_text(encoding="utf-8")
check("and their shim test recreates the Agent from the #679 state and finds the missing hashed ConfigMaps",
      "#679" in shim and "repair_ai_layer_rollout" in shim)

print("== no app that syncs with RespectIgnoreDifferences ignores anything inside a list ==")
# The copy from live replaces a list whole on a CRD (a JSON merge patch) and takes its order from live on a built-in
# kind (a strategic merge patch's $setElementOrder). An ignore of a whole field, a list included (kyverno-policies'
# /spec/validationActions, the root's /metadata/finalizers), is copied whole, which is what it means.
ELEMENT = re.compile(r"\[\]|\[\s*-?\d")


def into_list(i: dict) -> list[str]:
    return [e for e in i.get("jqPathExpressions") or [] if ELEMENT.search(e)] + \
        [p for p in i.get("jsonPointers") or [] if re.search(r"/(\d+|-)(/|$)", p)]


check("the rule finds the three list ignores ai-layer has (so it would catch them were the option back)",
      sum(len(into_list(i)) for i in rendered_ai_layer("attendee")["spec"]["ignoreDifferences"]) == 3)
check("and reads a map key in brackets as no list (agentgateway-c7-config's .data[\"config.yaml\"])",
      not into_list({"jqPathExpressions": ['.data["config.yaml"]']}))
for profile in profiles():
    for n in app_names(profile):
        raw = for_c7_control((APPS / f"{n}.yaml").read_text(encoding="utf-8"), c7_control(profile))
        for app in (d for d in yaml.safe_load_all(without_front_door(raw)) if d):
            if RESPECT not in sync_options(app):
                continue
            for i in app["spec"].get("ignoreDifferences") or []:
                bad = into_list(i)
                check(f"{profile} {n}: {i.get('kind')} ignores reach into no list {bad}", not bad)

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All agent tools sync checks passed.")
