# ABOUTME: Reproduces #679 offline: Argo CD's RespectIgnoreDifferences sync of the workshop-agent CRD, ported from
# ABOUTME: v3.5.2, keeps the live tools array whenever an ignore sits inside it; admin no longer has one there.
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
# This ports that function for a resource outside the scheme (the jq deletion is the real jq, as Argo CD's gojq
# del(<expression>)) and runs it on the committed Agent and each profile's rendered ai-layer ignores. On the
# toolnames profiles the hazard is kept on purpose, for the student's guard-mcp-on, and fleet.sh converge's
# repair_agent_tools is the repair (its shim test is in test_fleet_converge_repairs.sh). On admin, where C7 is
# agentgateway's rule (#496), the ignore is gone and the sync carries git's tools. The port is held to
# VERSIONS.lock's Argo CD version: a version bump fails here until the port is read against the new sync.go.
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


ai_profiles = [p for p in profiles() if "ai-layer" in app_names(p)]
check("every profile deploys ai-layer", ai_profiles == profiles(), str(ai_profiles))
check("ai-layer syncs with RespectIgnoreDifferences=true, the option the port is",
      all("RespectIgnoreDifferences=true" in rendered_ai_layer(p)["spec"]["syncPolicy"]["syncOptions"] for p in ai_profiles))
check("only admin puts C7 on agentgateway's rule (c7Control gateway), the profile the web terminal's _c7gw names",
      [p for p in ai_profiles if c7_control(p) == "gateway"] == ["admin"])

for profile in ai_profiles:
    control, ignores = c7_control(profile), agent_ignores(rendered_ai_layer(profile))
    stale = live_agent(workshop_tools=STALE_ELEVEN)
    applied = synced_target(AGENT, stale, ignores)
    if control == "toolnames":
        print(f"== {profile} (c7Control toolnames): #679 reproduced, and the student's C7 fix kept ==")
        check(f"{profile}: the Agent's ignores are evil-mcp's toolNames and modelConfig",
              ignores == [EVIL, ".spec.declarative.modelConfig"], str(ignores))
        check(f"{profile}: git's twelve show as drift on the stale Agent (OutOfSync)", out_of_sync(AGENT, stale, ignores))
        check(f"{profile}: the sync applies the LIVE tools array, so read_support_ticket never lands",
              server(applied, "workshop-mcp")["toolNames"] == STALE_ELEVEN,
              str(server(applied, "workshop-mcp")["toolNames"]))
        check(f"{profile}: so the applied Agent is still OutOfSync, every auto-sync after it the same",
              out_of_sync(AGENT, synced_target(AGENT, applied, ignores), ignores))
        narrowed = live_agent(evil_tools=["get_weather"])
        check(f"{profile}: a student's guard-mcp-on (evil-mcp narrowed to get_weather) survives a sync, why it is kept",
              server(synced_target(AGENT, narrowed, ignores), "evil-mcp")["toolNames"] == ["get_weather"]
              and not out_of_sync(AGENT, narrowed, ignores))
    else:
        print(f"== {profile} (c7Control gateway): the sync carries git's tools ==")
        check(f"{profile}: the Agent's only ignore is modelConfig, outside the tools array",
              ignores == [".spec.declarative.modelConfig"], str(ignores))
        check(f"{profile}: the sync applies git's workshop-mcp list, read_support_ticket included",
              server(applied, "workshop-mcp")["toolNames"] == GIT_TOOLS, str(server(applied, "workshop-mcp")["toolNames"]))
        check(f"{profile}: and git's whole tools array, headersFrom included",
              applied["spec"]["declarative"]["tools"] == AGENT["spec"]["declarative"]["tools"])
        check(f"{profile}: after it the Agent is Synced", not out_of_sync(AGENT, applied, ignores))
        tiered = live_agent(workshop_tools=STALE_ELEVEN, model_config="bedrock-claude")
        got = synced_target(AGENT, tiered, ignores)
        check(f"{profile}: a per-cluster modelConfig still survives the same sync (a field of a map, not an array)",
              got["spec"]["declarative"]["modelConfig"] == "bedrock-claude"
              and server(got, "workshop-mcp")["toolNames"] == GIT_TOOLS)
        check(f"{profile}: nothing on admin writes evil-mcp's list but the committed one, so selfHeal restoring it is right",
              server(synced_target(AGENT, live_agent(evil_tools=["get_weather"]), ignores), "evil-mcp")["toolNames"]
              == server(AGENT, "evil-mcp")["toolNames"])
    check(f"{profile}: a fresh cluster (no live Agent) gets git's Agent as committed",
          synced_target(AGENT, None, ignores) == AGENT)

print("== the stale toolnames clusters are converge's to repair ==")
fleet = (REPO / "infra/terraform/fleet/fleet.sh").read_text(encoding="utf-8")
check("fleet.sh repair_one runs repair_agent_tools", re.search(
    r"^repair_one\(\) \{\n(?:.*\n){0,8}?    repair_step repair_agent_tools \"\$\{name\}\" \"\$\{kcfg\}\"", fleet, re.M)
      is not None)
check("and its shim test recreates the Agent from the #679 state",
      "#679" in (REPO / "verify/test_fleet_converge_repairs.sh").read_text(encoding="utf-8"))

print("== no other ignore freezes part of an array on sync ==")
# A JSON merge patch replaces an array whole, so on a resource outside Argo CD's scheme (a CRD: a dotted group not
# under k8s.io) an ignore that reaches INTO an array element freezes the whole array. Built-in kinds take a
# strategic merge patch with their merge keys, and an ignore of a whole array field is the intended freeze.
BUILTIN = re.compile(r"^$|^[a-z0-9]+$|\.k8s\.io$")


def into_array(i: dict) -> list[str]:
    return [e for e in i.get("jqPathExpressions") or [] if "[" in e] + \
        [p for p in i.get("jsonPointers") or [] if re.search(r"/\d+/", p)]


for profile in profiles():
    for n in app_names(profile):
        raw = for_c7_control((APPS / f"{n}.yaml").read_text(encoding="utf-8"), c7_control(profile))
        for app in (d for d in yaml.safe_load_all(without_front_door(raw)) if d):
            opts = ((app.get("spec") or {}).get("syncPolicy") or {}).get("syncOptions") or []
            if "RespectIgnoreDifferences=true" not in opts:
                continue
            for i in app["spec"].get("ignoreDifferences") or []:
                bad = [] if BUILTIN.search(i.get("group", "")) else into_array(i)
                if (n, i.get("kind"), c7_control(profile)) == ("ai-layer", "Agent", "toolnames"):
                    bad = [e for e in bad if e != EVIL]
                check(f"{profile} {n}: {i.get('kind')} ignores reach into no array {bad}", not bad)

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All agent tools sync checks passed.")
