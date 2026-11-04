# ABOUTME: Ports Argo CD v3.5.2's RespectIgnoreDifferences sync (#679): a CRD array with an ignore inside freezes whole
# ABOUTME: (the Agent's tools, fixed by #707's own Application), a built-in list with an ignored element freezes in order.
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
# The second instance (#679, reopened). guard-proxy's new CONSOLE_ORIGIN env entry stuck on both KubeCon clusters, and
# guard-proxy's endless selfHeal syncs held back every later commit while each reported Succeeded. guard-proxy is a
# Deployment, a built-in kind, so the copy is a strategic merge patch with merge keys: a new env entry from git lands
# in git's place and a live toggle survives. But the patch also carries `$setElementOrder/env` from live, so the list
# is applied in the LIVE order. Once that differs from git's (`kubectl set env` appends a new entry, and a commit that
# only reorders entries does the same), no sync corrects it while the diff predicts git's order: OutOfSync for good.
# fleet.sh converge's repair_env_order puts the live list back in git's order, values kept.
#
# This ports normalizeTargetResources for both kinds (the jq deletion is the real jq, as Argo CD's gojq
# del(<expression>); the merge patches are evanphx/json-patch's and apimachinery's strategicpatch, for maps and
# merge-key lists of maps), shows it still reproduces #679 under ai-layer's old options, and then runs selfHeal on the
# committed Agent with each profile's rendered workshop-agent ignores: git's tools land on attendee, burn, full and
# admin with no fleet.sh converge, a student's guard-mcp-on survives a selfHeal with no git change, and the two costs
# #707 accepted hold as recorded. It then runs guard-proxy's env through ai-layer's ignores, and holds every ignored
# list element under RespectIgnoreDifferences to a row of repair_env_order. The port was checked against the real code:
# docs/research/2026-10-30-argo-sync-replay/ runs Argo CD v3.5.2's normalizeTargetResources and its diff against a
# real kube-apiserver with server-side apply, and its results are the ones held here. The port is held to
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
# The merge keys apimachinery's strategicpatch reads from the apps/v1 Deployment's Go types, for the lists a
# Deployment's pod template carries.
MERGE_KEYS = {"containers": "name", "initContainers": "name", "env": "name", "volumes": "name",
              "volumeMounts": "mountPath", "ports": "containerPort", "imagePullSecrets": "name"}
ORDER = "$setElementOrder/"


# ---- the port: Argo CD v3.5.2 controller/sync.go normalizeTargetResources ---------------------------------------
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


def merge_list(key: str, cur, mod) -> bool:
    return key in MERGE_KEYS and isinstance(cur, list) and isinstance(mod, list) \
        and all(isinstance(x, dict) for x in cur + mod)


def create_strategic_patch(cur: dict, mod: dict) -> dict:
    """strategicpatch.CreateThreeWayMergePatch(live, live, normalizedLive): the additions and changes from current to
    modified (original is modified, so there are no deletions), each changed merge-key list with its
    `$setElementOrder` directive, which lists the MODIFIED (live) order of every element."""
    out: dict = {}
    for k, mv in mod.items():
        if k not in cur:
            out[k] = copy.deepcopy(mv)
            continue
        cv = cur[k]
        if isinstance(mv, dict) and isinstance(cv, dict):
            d = create_strategic_patch(cv, mv)
            if d:
                out[k] = d
        elif merge_list(k, cv, mv):
            mk, items = MERGE_KEYS[k], []
            for m in mv:
                c = next((c for c in cv if c.get(mk) == m.get(mk)), None)
                if c is None:
                    items.append(copy.deepcopy(m))
                else:
                    d = create_strategic_patch(c, m)
                    if d:
                        items.append({mk: m[mk], **d})
            if items:
                out[ORDER + k] = [{mk: m[mk]} for m in mv]
                out[k] = items
        elif mv != cv:
            out[k] = copy.deepcopy(mv)
    return out


def _sorted_by(items: list, order: list, mk: str) -> list:
    """normalizeSliceOrder: a stable sort by each item's index in order."""
    pos = {o: i for i, o in enumerate(order)}
    return sorted(items, key=lambda x: pos.get(x[mk], len(pos)))


def _merge_sorted(left: list, right: list, server_order: list, mk: str) -> list:
    """mergeSortedSlice: left is the server-only items, right the patch items; left first only when both are in the
    server order and left comes first there."""
    pos = {o: i for i, o in enumerate(server_order)}
    out, i, j = [], 0, 0
    while i < len(left) or j < len(right):
        if i >= len(left):
            out.append(right[j]); j += 1
        elif j >= len(right):
            out.append(left[i]); i += 1
        elif left[i][mk] in pos and right[j][mk] in pos and pos[left[i][mk]] < pos[right[j][mk]]:
            out.append(left[i]); i += 1
        else:
            out.append(right[j]); j += 1
    return out


def apply_strategic_patch(orig: dict, patch: dict) -> dict:
    """strategicpatch.StrategicMergePatch for maps and merge-key lists of maps: mergePatchIntoOriginal merges each
    list with an order directive, splits it into the items the directive names (sorted by the directive) and the
    original's other items (sorted by the original), and merges the two."""
    out = copy.deepcopy(orig)
    orders = {k[len(ORDER):]: v for k, v in patch.items() if k.startswith(ORDER)}
    for k, v in patch.items():
        if k.startswith(ORDER):
            continue
        if k in MERGE_KEYS and isinstance(v, list):
            mk, original = MERGE_KEYS[k], out.get(k)
            merged = copy.deepcopy(original) if isinstance(original, list) else []
            for item in v:
                at = next((n for n, m in enumerate(merged) if m.get(mk) == item.get(mk)), None)
                if at is None:
                    merged.append(apply_strategic_patch({}, item))
                else:
                    merged[at] = apply_strategic_patch(merged[at], item)
            if k in orders and isinstance(original, list):
                order = [o[mk] for o in orders[k]]
                server_order = [o[mk] for o in original]
                patch_items = _sorted_by([m for m in merged if m[mk] in order], order, mk)
                server_only = _sorted_by([m for m in merged if m[mk] not in order], server_order, mk)
                merged = _merge_sorted(server_only, patch_items, server_order, mk)
            out[k] = merged
        elif isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = apply_strategic_patch(out[k], v)
        elif v is None:
            out.pop(k, None)
        else:
            out[k] = copy.deepcopy(v)
    return out


def in_scheme(obj: dict) -> bool:
    """scheme.Scheme.New(gvk) succeeds: the built-in groups (core, apps, the *.k8s.io ones); a CRD's does not."""
    group = obj.get("apiVersion", "").rpartition("/")[0]
    return group == "" or "." not in group or group.endswith(".k8s.io")


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
    if in_scheme(target):
        patched = apply_strategic_patch(normalized_target,
                                        create_strategic_patch(normalized_live_for_patch, live_for_patch))
    else:
        patched = apply_merge_patch(normalized_target, create_merge_patch(normalized_live_for_patch, live_for_patch))
    restore_non_ignored_fields(patched, target, normalized_target, normalized_live)
    return patched


def out_of_sync(target: dict, live: dict, expressions: list[str]) -> bool:
    """The diff Argo CD shows: the two objects with the ignored fields deleted, spec compared, list order included
    (the structured-merge diff predicts the committed order, which a server-side dry run confirms)."""
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
REPLAY = REPO / "docs/research/2026-10-30-argo-sync-replay"
check("the real-code replay this port is checked against is committed beside it",
      all((REPLAY / f).is_file() for f in ("README.md", "main.go", "go.mod", "go.sum", "replay.sh")))
check("and it is of the same Argo CD", (REPLAY / "README.md").is_file()
      and PORTED_FROM in (REPLAY / "README.md").read_text(encoding="utf-8"))

AGENT_BUNDLE = REPO / "gitops/workshop-agent"
AGENT = next(d for d in yaml.safe_load_all((AGENT_BUNDLE / "agent.yaml").read_text(encoding="utf-8"))
             if d and d.get("kind") == "Agent" and d["metadata"]["name"] == "workshop-agent")


def server(agent: dict, name: str) -> dict:
    return next(t["mcpServer"] for t in agent["spec"]["declarative"]["tools"] if t["mcpServer"]["name"] == name)


GIT_TOOLS = server(AGENT, "workshop-mcp")["toolNames"]
GIT_EVIL = server(AGENT, "evil-mcp")["toolNames"]
GIT_MODEL = AGENT["spec"]["declarative"]["modelConfig"]
# #733's live check swapped check_inventory and reorder_supply in git, so the up clusters had a workshop-mcp change
# that only a sync lands: fleet.sh's repair_agent_tools compares the lists sorted.
GIT_ORDER = ["lookup_customer_records", "reorder_supply", "check_inventory", "get_order_history",
             "get_marketing_intel", "search_web", "read_support_ticket", "post_marketing", "get_vault_entry",
             "list_services", "deploy_app", "run_shell"]
check("git's workshop-mcp list is the stale eleven plus read_support_ticket (#640)",
      sorted(t for t in GIT_TOOLS if t != "read_support_ticket") == sorted(STALE_ELEVEN)
      and "read_support_ticket" in GIT_TOOLS)
check("in #733's order, which differs from the stale eleven's in more than the added tool",
      GIT_TOOLS == GIT_ORDER and [t for t in GIT_TOOLS if t != "read_support_ticket"] != STALE_ELEVEN, str(GIT_TOOLS))


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
check("the Agent is a CRD, outside Argo CD's scheme, so the copy is a JSON merge patch", not in_scheme(AGENT))
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

print("== guard-proxy's env, a built-in list with ignored elements, under ai-layer's RespectIgnoreDifferences ==")
# The second instance of #679. The replay (docs/research/2026-10-30-argo-sync-replay) ran each case below through Argo
# CD's own code against a real apiserver; this holds the same results offline.
PROXY = next(d for d in yaml.safe_load_all((REPO / "gitops/ai-layer/resources.yaml").read_text(encoding="utf-8"))
             if d and d.get("kind") == "Deployment" and d["metadata"]["name"] == "guard-proxy")


def proxy_env(obj: dict) -> list[dict]:
    return next(c for c in obj["spec"]["template"]["spec"]["containers"] if c["name"] == "proxy")["env"]


def ignores(app: dict, group: str, kind: str, name: str) -> list[str]:
    return [e for i in app["spec"].get("ignoreDifferences") or []
            if i.get("group", "") == group and i.get("kind") == kind and i.get("name") in (None, name)
            for e in i.get("jqPathExpressions") or []]


GIT_ENV = [e["name"] for e in proxy_env(PROXY)]
ai = rendered("ai-layer.yaml", "burn")
proxy_ignores = ignores(ai, "apps", "Deployment", "guard-proxy")
check("ai-layer respects its ignores on sync, the option the strategic half of the port is",
      "RespectIgnoreDifferences=true" in sync_options(ai))
check("guard-proxy's ignores name env entries of the proxy container", len(proxy_ignores) == 1
      and ".env[] | select(.name | test(" in proxy_ignores[0] and 'select(.name=="proxy")' in proxy_ignores[0])
check("a Deployment is in Argo CD's scheme, so the copy is a strategic merge patch", in_scheme(PROXY))
check("git puts CONSOLE_ORIGIN before OTEL_SERVICE_NAME",
      GIT_ENV.index("CONSOLE_ORIGIN") < GIT_ENV.index("OTEL_SERVICE_NAME"))


def live_proxy(drop: str | None = None, append: str | None = None, tier: str | None = None) -> dict:
    live = copy.deepcopy(PROXY)
    live["metadata"].update({"namespace": "agent", "uid": "5e1f", "resourceVersion": "777", "generation": 3})
    live["status"] = {"replicas": 1, "readyReplicas": 1}
    env = proxy_env(live)
    if drop:
        env[:] = [e for e in env if e["name"] != drop]
    if append:
        env[:] = [e for e in env if e["name"] != append] + [e for e in env if e["name"] == append]
    for e in env:
        if tier and e["name"] == "MODEL_TIER":
            e["value"] = tier
    return live


def names(obj: dict) -> list[str]:
    return [e["name"] for e in proxy_env(obj)]


def values(obj: dict) -> dict:
    return {e["name"]: e.get("value", "") for e in proxy_env(obj)}


def reorder(live: dict, order: list[str]) -> dict:
    """repair_env_order's rewrite: the live entries in git's order, values kept, entries git lacks last."""
    out = copy.deepcopy(live)
    env = proxy_env(out)
    env[:] = [e for n in order for e in env if e["name"] == n] + [e for e in env if e["name"] not in order]
    return out


before = live_proxy(drop="CONSOLE_ORIGIN", tier="sonnet")
got = synced_target(PROXY, before, proxy_ignores)
check("a6af457, through Argo: git's new CONSOLE_ORIGIN lands, in git's place", names(got) == GIT_ENV, str(names(got)))
check("with the live MODEL_TIER=sonnet toggle kept", values(got)["MODEL_TIER"] == "sonnet")
check("and the Deployment reads Synced after it", not out_of_sync(PROXY, got, proxy_ignores))
appended = live_proxy(append="CONSOLE_ORIGIN", tier="sonnet")
check("the same entry added live with `kubectl set env`, which appends: OutOfSync on order alone",
      out_of_sync(PROXY, appended, proxy_ignores) and values(appended) == values(live_proxy(tier="sonnet")))
got = synced_target(PROXY, appended, proxy_ignores)
check("#679: the sync applies the LIVE order, CONSOLE_ORIGIN still last", names(got)[-1] == "CONSOLE_ORIGIN",
      str(names(got)[-3:]))
check("so it is OutOfSync after every sync, and selfHeal syncs it alone for good",
      out_of_sync(PROXY, got, proxy_ignores)
      and out_of_sync(PROXY, synced_target(PROXY, got, proxy_ignores), proxy_ignores))
fixed = synced_target(PROXY, reorder(appended, GIT_ENV), proxy_ignores)
check("after repair_env_order puts the live list in git's order, the sync keeps it and the Deployment reads Synced",
      names(fixed) == GIT_ENV and not out_of_sync(PROXY, fixed, proxy_ignores))
check("with the toggle still kept", values(fixed)["MODEL_TIER"] == "sonnet")
# A commit that only moves entries is the same freeze from git's side: the live list holds every entry, so the patch's
# order directive names all of them in the live order.
moved = copy.deepcopy(PROXY)
env = proxy_env(moved)
env[:] = [e for e in env if e["name"] == "CONSOLE_ORIGIN"] + [e for e in env if e["name"] != "CONSOLE_ORIGIN"]
MOVED_ENV = names(moved)
on_cluster = live_proxy(tier="sonnet")
got = synced_target(moved, on_cluster, proxy_ignores)
check("a commit that only reorders guard-proxy's env: the sync keeps the live order, so it reads OutOfSync for good",
      names(got) == GIT_ENV and out_of_sync(moved, got, proxy_ignores))
fixed = synced_target(moved, reorder(got, MOVED_ENV), proxy_ignores)
check("and repair_env_order puts that right too", names(fixed) == MOVED_ENV and not out_of_sync(moved, fixed, proxy_ignores))

print("== agentgateway's Bedrock pin through a sync, and the operation a script asks for (#583) ==")
# Run 15801 (2026-11-02) found agentgateway's BEDROCK_NOVA_MODEL back at git's system id on watch-it-burn-community,
# where the 2026-10-31 run had read the cluster's application profile ARN. ai-layer ignores that entry and syncs with
# RespectIgnoreDifferences, so its own syncs keep the ARN. But Argo CD v3.5.2 reads the option from the sync OPERATION
# (controller/sync.go SyncAppState: syncOp.SyncOptions.HasOption("RespectIgnoreDifferences=true")). Auto-sync and the
# API server copy .spec.syncPolicy.syncOptions into it; an operation patched straight onto the Application has only
# what the patch gives it. The by-hand sync of 2026-11-01 16:36Z wrote one without the option (agentgateway's
# ReplicaSets date the change to it on both clusters), and fleet.sh repair_failed_syncs and roll-console.sh patched
# bare ones too. Both scripts and `fleet.sh sync` now write sync_operation_of's operation, the app's own options.
GW = next(d for d in yaml.safe_load_all((REPO / "gitops/ai-layer/agentgateway.yaml").read_text(encoding="utf-8"))
          if d and d.get("kind") == "Deployment" and d["metadata"]["name"] == "agentgateway")
ARN = "arn:aws:bedrock:us-west-2:515966504359:application-inference-profile/5l72jg8rnz71"


def gw_model(obj: dict) -> str | None:
    c = next(c for c in obj["spec"]["template"]["spec"]["containers"] if c["name"] == "agentgateway")
    return next((e.get("value") for e in c.get("env") or [] if e["name"] == "BEDROCK_NOVA_MODEL"), None)


pinned = copy.deepcopy(GW)
pinned["metadata"].update({"namespace": "agent", "uid": "a9e7", "resourceVersion": "912", "generation": 4})
next(e for c in pinned["spec"]["template"]["spec"]["containers"] if c["name"] == "agentgateway"
     for e in c["env"] if e["name"] == "BEDROCK_NOVA_MODEL")["value"] = ARN
check("git commits agentgateway's BEDROCK_NOVA_MODEL as the system id, the value run 15801 read live",
      gw_model(GW) == "us.amazon.nova-pro-v1:0", str(gw_model(GW)))
FLEET = REPO / "infra/terraform/fleet/fleet.sh"
for profile in profiles():
    if "ai-layer" not in app_names(profile):
        continue
    ai_p = rendered("ai-layer.yaml", profile)
    gw_ignores = ignores(ai_p, "apps", "Deployment", "agentgateway")
    check(f"{profile}: the pinned gateway reads Synced, so selfHeal alone never touches it",
          not out_of_sync(GW, pinned, gw_ignores))
    check(f"{profile}: #583: a sync run WITHOUT RespectIgnoreDifferences applies git's system id over the ARN",
          gw_model(sync_applies(GW, pinned, gw_ignores, False)) == gw_model(GW))
    run = subprocess.run(["bash", "-c", 'source "$1" >/dev/null 2>&1; sync_operation_of "$2"', "_", str(FLEET),
                          json.dumps(ai_p)], cwd=FLEET.parent, capture_output=True, text=True, timeout=60)
    try:
        op = json.loads(run.stdout)["operation"]["sync"]
    except (ValueError, KeyError, TypeError):
        op = None
    check(f"{profile}: fleet.sh's re-sync of ai-layer (sync_operation_of) carries ai-layer's own sync options",
          op is not None and op.get("syncOptions") == sync_options(ai_p), run.stdout + run.stderr)
    respect = op is not None and "RespectIgnoreDifferences=true" in (op.get("syncOptions") or [])
    check(f"{profile}: so that sync keeps the cluster's ARN on agentgateway",
          gw_model(sync_applies(GW, pinned, gw_ignores, respect)) == ARN)

print("== no Application freezes a list on sync that converge cannot put right ==")
# A JSON merge patch replaces an array whole, so on a resource outside Argo CD's scheme (a CRD: a dotted group not
# under k8s.io) an ignore that reaches INTO an array element freezes the whole array, and nothing but deleting the
# object repairs that. It is never allowed under RespectIgnoreDifferences, on any profile. On a built-in kind an
# ignore that selects an ELEMENT of a merge-key list freezes that list's order, which repair_env_order puts right, so
# each must be one of its rows. An ignore of a whole field (`.rules`, a ConfigMap's data key) freezes that field on
# purpose and is not a list element.
BUILTIN = re.compile(r"^$|^[a-z0-9]+$|\.k8s\.io$")
rows = re.search(r"^ENV_ORDER_LISTS=\(\n(.*?)\n\)", fleet, re.M | re.S)
order_rows = {tuple(r.strip().strip('"').split()) for r in rows.group(1).splitlines()} if rows else set()
check("fleet.sh repair_one runs repair_env_order", re.search(
    r"^repair_one\(\) \{\n(?:.*\n){0,10}?    repair_step repair_env_order \"\$\{name\}\" \"\$\{kcfg\}\"", fleet, re.M)
      is not None)
check(f"repair_env_order covers guard-proxy and agentgateway ({sorted(order_rows)})",
      order_rows == {("guard-proxy", "proxy", "gitops/ai-layer/resources.yaml"),
                     ("agentgateway", "agentgateway", "gitops/ai-layer/agentgateway.yaml")})
for dep, ctr, rel in sorted(order_rows):
    deps = [d for d in yaml.safe_load_all((REPO / rel).read_text(encoding="utf-8"))
            if d and d.get("kind") == "Deployment" and d["metadata"]["name"] == dep]
    check(f"repair_env_order's {dep}/{ctr} row names a Deployment and container {rel} commits",
          len(deps) == 1 and any(c["name"] == ctr for c in deps[0]["spec"]["template"]["spec"]["containers"]))
ELEMENT = re.compile(r'containers\[\] \| select\(\.name *== *"([^"]+)"\) \| \.env\[\] \| select\(')


def into_array(i: dict) -> list[str]:
    """The paths that reach into an array: jq's `[]` or `[<n>]` (`["key"]` is a map key), a pointer's /<n>/."""
    return [e for e in i.get("jqPathExpressions") or [] if re.search(r"\[\d*\]", e)] + \
        [p for p in i.get("jsonPointers") or [] if re.search(r"/\d+(/|$)", p)]


seen_elements: set[tuple[str, str]] = set()
for profile in profiles():
    for n in app_names(profile):
        raw = for_c7_control((APPS / f"{n}.yaml").read_text(encoding="utf-8"), c7_control(profile))
        for app in (d for d in yaml.safe_load_all(without_front_door(raw)) if d):
            if "RespectIgnoreDifferences=true" not in (((app.get("spec") or {}).get("syncPolicy") or {})
                                                       .get("syncOptions") or []):
                continue
            for i in app["spec"].get("ignoreDifferences") or []:
                reach = into_array(i)
                if not BUILTIN.search(i.get("group", "")):
                    check(f"{profile} {n}: {i.get('kind')} (a CRD) has no ignore inside an array {reach}", not reach)
                    continue
                for e in reach:
                    m = ELEMENT.search(e)
                    covered = bool(m) and i.get("kind") == "Deployment" and any(
                        r[0] == i.get("name") and r[1] == m.group(1) for r in order_rows)
                    if m:
                        seen_elements.add((i.get("name"), m.group(1)))
                    check(f"{profile} {n}: {i.get('kind')}/{i.get('name')}'s ignored list element is a list "
                          f"repair_env_order orders ({e[:60]}...)", covered)
check("and every row of repair_env_order is a list some profile does ignore an element of",
      {(r[0], r[1]) for r in order_rows} == seen_elements, str(sorted(seen_elements)))

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All agent tools sync checks passed.")
