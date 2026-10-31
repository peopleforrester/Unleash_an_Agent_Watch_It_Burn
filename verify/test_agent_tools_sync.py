# ABOUTME: Shows git's Agent tools landing on every profile since #707: the workshop-agent Application keeps C7's ignore
# ABOUTME: and drops RespectIgnoreDifferences, whose Argo CD v3.5.2 sync (ported here) froze the whole tools array (#679).
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
# The fix (#707). The Agent left ai-layer for an Application of its own, gitops/bootstrap/apps/workshop-agent.yaml,
# which keeps the evil-mcp toolNames ignore (on the toolnames profiles) and the modelConfig ignore, and syncs without
# RespectIgnoreDifferences. An ignore without it works on the diff alone: a student's guard-mcp-on leaves the Agent
# Synced, so selfHeal has nothing to do, and a sync applies the committed Agent as git has it.
#
# This ports normalizeTargetResources for a resource outside the scheme (the jq deletion is the real jq, as Argo CD's
# gojq del(<expression>)), shows it still reproduces #679 under ai-layer's old options, and then runs selfHeal on the
# committed Agent with each profile's rendered workshop-agent ignores: git's tools land on attendee, burn, full and
# admin with no fleet.sh converge, a student's guard-mcp-on survives a selfHeal with no git change, and the two costs
# #707 accepted hold as recorded. The port is held to VERSIONS.lock's Argo CD version: a version bump fails here until
# the port is read against the new sync.go.
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


def sync_applies(target: dict, live: dict | None, expressions: list[str], respect: bool) -> dict:
    """What a sync applies: the RespectIgnoreDifferences merge above, or, without the option, the target as git has
    it. Argo CD applies the desired state as-is unless RespectIgnoreDifferences is set; ServerSideApply with Force
    writes every field the target holds, a field another manager took included (#349)."""
    return synced_target(target, live, expressions) if respect else target


def self_heal(target: dict, live: dict | None, expressions: list[str], respect: bool) -> dict:
    """The live Agent after selfHeal: automated sync runs only when the diff shows the Agent OutOfSync."""
    if live is not None and not out_of_sync(target, live, expressions):
        return live
    return sync_applies(target, live, expressions, respect)


# ---- the inputs: the committed Agent, and each profile's rendered workshop-agent Application ---------------------
print(f"== the port is of the Argo CD the clusters run ({PORTED_FROM}) ==")
lock = (REPO / "VERSIONS.lock").read_text(encoding="utf-8")
argocd = re.search(r"^argocd\s+chart \S+ / app (v\S+)", lock, re.M)
check(f"VERSIONS.lock's argocd app is {PORTED_FROM}, the sync.go this ports (a bump: re-read normalizeTargetResources)",
      argocd is not None and argocd.group(1) == PORTED_FROM, argocd.group(1) if argocd else "no argocd line")

AGENT_BUNDLE = REPO / "gitops/workshop-agent"
AGENT = next(d for d in yaml.safe_load_all((AGENT_BUNDLE / "agent.yaml").read_text(encoding="utf-8"))
             if d and d.get("kind") == "Agent" and d["metadata"]["name"] == "workshop-agent")


def server(agent: dict, name: str) -> dict:
    return next(t["mcpServer"] for t in agent["spec"]["declarative"]["tools"] if t["mcpServer"]["name"] == name)


GIT_TOOLS = server(AGENT, "workshop-mcp")["toolNames"]
GIT_EVIL = server(AGENT, "evil-mcp")["toolNames"]
GIT_MODEL = AGENT["spec"]["declarative"]["modelConfig"]
check("git's workshop-mcp list is the stale eleven plus read_support_ticket (#640)",
      [t for t in GIT_TOOLS if t != "read_support_ticket"] == STALE_ELEVEN and "read_support_ticket" in GIT_TOOLS)


def rendered(app_file: str, profile: str) -> dict:
    raw = without_front_door(for_c7_control((APPS / app_file).read_text(encoding="utf-8"), c7_control(profile)))
    return yaml.safe_load(raw.replace(REVISION, "0" * 40).replace(IMAGE_REGISTRY, LAB_PLATFORM_GHCR))


def agent_ignores(app: dict) -> list[str]:
    return [e for i in app["spec"].get("ignoreDifferences") or []
            if i.get("group") == "kagent.dev" and i.get("kind") == "Agent" and i.get("name") in (None, "workshop-agent")
            for e in i.get("jqPathExpressions") or []]


def sync_options(app: dict) -> list[str]:
    return ((app["spec"].get("syncPolicy") or {}).get("syncOptions")) or []


def wave(app: dict) -> int:
    return int((app["metadata"].get("annotations") or {}).get("argocd.argoproj.io/sync-wave", "0"))


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


def with_git(workshop_tools: list[str] | None = None, evil_tools: list[str] | None = None) -> dict:
    """The committed Agent after a git change to one of its tool lists."""
    target = copy.deepcopy(AGENT)
    if workshop_tools is not None:
        server(target, "workshop-mcp")["toolNames"] = list(workshop_tools)
    if evil_tools is not None:
        server(target, "evil-mcp")["toolNames"] = list(evil_tools)
    return target


NARROWED = ["get_weather"]  # what guard-mcp-on leaves evil-mcp on a toolnames cluster
TIER = "bedrock-sonnet"  # a live modelConfig tier patch (#598: no script applies one yet)

print("== the port still reproduces #679 under ai-layer's old options ==")
# ai-layer carried the Agent with these two ignores and RespectIgnoreDifferences=true until #707. If the port stops
# freezing the array here, it no longer models the sync, and every result below means nothing.
OLD_IGNORES = [EVIL, ".spec.declarative.modelConfig"]
stale = live_agent(workshop_tools=STALE_ELEVEN)
frozen = self_heal(AGENT, stale, OLD_IGNORES, respect=True)
check("with RespectIgnoreDifferences, git's twelve show as drift on the stale Agent (OutOfSync)",
      out_of_sync(AGENT, stale, OLD_IGNORES))
check("and the sync applies the LIVE tools array, so read_support_ticket never lands",
      server(frozen, "workshop-mcp")["toolNames"] == STALE_ELEVEN, str(server(frozen, "workshop-mcp")["toolNames"]))
check("so the Agent stays OutOfSync, every auto-sync after it the same",
      out_of_sync(AGENT, self_heal(AGENT, frozen, OLD_IGNORES, respect=True), OLD_IGNORES))

print("== the Agent is the workshop-agent Application's, out of ai-layer (#707) ==")
ai_layer_docs = [d for f in sorted((REPO / "gitops/ai-layer").glob("*.yaml"))
                 for d in yaml.safe_load_all(f.read_text(encoding="utf-8")) if isinstance(d, dict)]
check("no kagent Agent is left in gitops/ai-layer, so an ai-layer sync never touches it",
      not [d for d in ai_layer_docs if d.get("kind") == "Agent"])
kust = yaml.safe_load((AGENT_BUNDLE / "kustomization.yaml").read_text(encoding="utf-8"))
check("gitops/workshop-agent is a kustomize bundle of agent.yaml alone, in namespace agent",
      kust.get("resources") == ["agent.yaml"] and kust.get("namespace") == "agent")
deploying = [p for p in profiles() if "ai-layer" in app_names(p)]
check("every profile deploys ai-layer", deploying == profiles(), str(deploying))
check("and every profile that deploys ai-layer deploys workshop-agent",
      all("workshop-agent" in app_names(p) for p in deploying))
check("only admin puts C7 on agentgateway's rule (c7Control gateway), the profile the web terminal's _c7gw names",
      [p for p in deploying if c7_control(p) == "gateway"] == ["admin"])

for profile in deploying:
    app, ai_layer = rendered("workshop-agent.yaml", profile), rendered("ai-layer.yaml", profile)
    control, ignores, opts = c7_control(profile), agent_ignores(app), sync_options(app)
    respect = "RespectIgnoreDifferences=true" in opts
    print(f"== {profile} (c7Control {control}): the workshop-agent Application ==")
    check(f"{profile}: it sources gitops/workshop-agent", app["spec"]["source"]["path"] == "gitops/workshop-agent")
    check(f"{profile}: it syncs after ai-layer, whose ModelConfigs and RemoteMCPServers the Agent names "
          f"(wave {wave(app)} after {wave(ai_layer)})", wave(app) > wave(ai_layer))
    check(f"{profile}: selfHeal and prune are on",
          (app["spec"]["syncPolicy"].get("automated") or {}) == {"prune": True, "selfHeal": True})
    check(f"{profile}: it keeps ServerSideApply=true and Force=true (#349)",
          "ServerSideApply=true" in opts and "Force=true" in opts)
    check(f"{profile}: and leaves out RespectIgnoreDifferences, the option that froze the array (#679)", not respect)
    check(f"{profile}: ai-layer ignores nothing on the Agent", not agent_ignores(ai_layer), str(agent_ignores(ai_layer)))

    stale = live_agent(workshop_tools=STALE_ELEVEN)
    healed = self_heal(AGENT, stale, ignores, respect)
    check(f"{profile}: git's twelve show as drift on a stale Agent (OutOfSync), so selfHeal syncs it",
          out_of_sync(AGENT, stale, ignores))
    check(f"{profile}: and the sync lands git's workshop-mcp list, read_support_ticket included, with no converge",
          server(healed, "workshop-mcp")["toolNames"] == GIT_TOOLS, str(server(healed, "workshop-mcp")["toolNames"]))
    check(f"{profile}: and git's whole tools array, headersFrom included",
          healed["spec"]["declarative"]["tools"] == AGENT["spec"]["declarative"]["tools"])
    check(f"{profile}: after it the Agent is Synced", not out_of_sync(AGENT, healed, ignores))
    renamed = with_git(workshop_tools=[t if t != "list_services" else "list_workloads" for t in GIT_TOOLS])
    check(f"{profile}: a later git change to a workshop-mcp tool lands the same way",
          server(self_heal(renamed, healed, ignores, respect), "workshop-mcp")["toolNames"]
          == server(renamed, "workshop-mcp")["toolNames"])
    check(f"{profile}: a fresh cluster (no live Agent) gets git's Agent as committed",
          self_heal(AGENT, None, ignores, respect) == AGENT)

    narrowed = live_agent(evil_tools=NARROWED)
    tiered = live_agent(model_config=TIER)
    check(f"{profile}: a live modelConfig tier patch with no git change leaves the Agent Synced, so selfHeal keeps it",
          self_heal(AGENT, tiered, ignores, respect) == tiered)
    if control == "toolnames":
        check(f"{profile}: the Agent's ignores are evil-mcp's toolNames and modelConfig",
              ignores == [EVIL, ".spec.declarative.modelConfig"], str(ignores))
        check(f"{profile}: a student's guard-mcp-on (evil-mcp narrowed to get_weather) leaves the Agent Synced",
              not out_of_sync(AGENT, narrowed, ignores))
        check(f"{profile}: so it survives a selfHeal with no git change",
              server(self_heal(AGENT, narrowed, ignores, respect), "evil-mcp")["toolNames"] == NARROWED)
        print(f"   the costs #707 accepted, on {profile}")
        evil_change = with_git(evil_tools=GIT_EVIL[:-1])
        check(f"{profile}: a git change to evil-mcp's committed toolNames alone is ignored by the diff, so a running "
              "cluster's Agent keeps the old list", not out_of_sync(evil_change, live_agent(), ignores)
              and server(self_heal(evil_change, live_agent(), ignores, respect), "evil-mcp")["toolNames"] == GIT_EVIL)
        check(f"{profile}: and it reaches new clusters only, the cost #515 accepted for agentgateway-c7-config",
              server(self_heal(evil_change, None, ignores, respect), "evil-mcp")["toolNames"] == GIT_EVIL[:-1])
        both = live_agent(workshop_tools=STALE_ELEVEN, evil_tools=NARROWED, model_config=TIER)
        reset = self_heal(AGENT, both, ignores, respect)
        check(f"{profile}: a sync for any other Agent change resets the student's guard-mcp-on to git's evil-mcp list",
              server(reset, "evil-mcp")["toolNames"] == GIT_EVIL)
        check(f"{profile}: and a live modelConfig tier patch along with it (#598: no script applies a tier yet)",
              reset["spec"]["declarative"]["modelConfig"] == GIT_MODEL)
    else:
        check(f"{profile}: the Agent's only ignore is modelConfig, outside the tools array",
              ignores == [".spec.declarative.modelConfig"], str(ignores))
        evil_change = with_git(evil_tools=GIT_EVIL[:-1])
        check(f"{profile}: a git change to evil-mcp's toolNames lands too, nothing ignoring it",
              server(self_heal(evil_change, live_agent(), ignores, respect), "evil-mcp")["toolNames"] == GIT_EVIL[:-1])
        check(f"{profile}: nothing on admin writes evil-mcp's list but the committed one, so selfHeal restoring it is right",
              server(self_heal(AGENT, narrowed, ignores, respect), "evil-mcp")["toolNames"] == GIT_EVIL)

print("== converge's repair is no longer the only route ==")
fleet = (REPO / "infra/terraform/fleet/fleet.sh").read_text(encoding="utf-8")
check("fleet.sh repair_one still runs repair_agent_tools, for a cluster Argo has not reconciled", re.search(
    r"^repair_one\(\) \{\n(?:.*\n){0,8}?    repair_step repair_agent_tools \"\$\{name\}\" \"\$\{kcfg\}\"", fleet, re.M)
      is not None)
check("and its comment says it is no longer the only route for the toolnames profiles (#707)",
      "This repair is no longer the only route on the toolnames profiles (attendee, burn, full) (#707)" in fleet)
check("and it reads the committed list from the workshop-agent bundle",
      'python3 - "${REPO_ROOT}/gitops/workshop-agent/agent.yaml"' in fleet)
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
                check(f"{profile} {n}: {i.get('kind')} ignores reach into no array {bad}", not bad)

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All agent tools sync checks passed.")
