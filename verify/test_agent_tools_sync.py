# ABOUTME: Reproduces #679 offline with Argo CD v3.5.2's RespectIgnoreDifferences sync, ported: a CRD array with an ignore
# ABOUTME: inside freezes whole, a built-in list with an ignored element freezes in its live order. Holds the fix to both.
#
# Why (#679). Git gave workshop-mcp twelve tools, read_support_ticket among them (#640), and both KubeCon clusters
# kept the older eleven. ai-layer showed Agent/workshop-agent OutOfSync, every auto-sync said serverside-applied,
# and the live list never changed. Then guard-proxy stuck the same way on both clusters after CONSOLE_ORIGIN was
# added to its env live, and its selfHeal syncs held back every later commit while each reported Succeeded.
#
# Both come from controller/sync.go at v3.5.2, normalizeTargetResources. With RespectIgnoreDifferences=true it copies
# each ignored field from live into the target it applies, as the patch from the normalized live object to the live
# one, then restoreNonIgnoredFields, which walks maps only, repairs the collateral.
#   - A CRD (the Agent) is not in Argo CD's scheme, so the patch is an RFC 7386 JSON merge patch, which cannot name one
#     element of an array: an ignore on evil-mcp's toolNames carries the WHOLE live tools array, and that is applied.
#   - A built-in kind (a Deployment) takes a strategic merge patch, with merge keys, so a new env entry from git lands
#     in git's place and a live toggle survives. But the patch also carries `$setElementOrder/env` from live, so the
#     list is applied in the LIVE order. Once that differs from git's (`kubectl set env` appends a new entry), no sync
#     corrects it, while the diff predicts git's order: OutOfSync forever, and selfHeal syncs that one Deployment.
#
# This ports that function for both kinds (the jq deletion is the real jq, as Argo CD's gojq del(<expression>); the
# merge patches are evanphx/json-patch's and apimachinery's strategicpatch, for maps and merge-key lists of maps) and
# runs it on the committed manifests and each profile's rendered ignores. The port was checked against the real code:
# docs/research/2026-10-30-argo-sync-replay/ runs Argo CD v3.5.2's normalizeTargetResources and its diff against a
# real kube-apiserver with server-side apply, and its results are the ones held here (decisions.md, #679). The port is
# held to VERSIONS.lock's Argo CD version: a version bump fails here until the port is read against the new sync.go.
#
# The fix it holds. The Agent is its own Application, ai-layer-agent, which does not respect its ignores on sync, so
# git's tools land on every profile while a student's guard-mcp-on is still left alone by selfHeal. No Application
# that respects ignores on sync may ignore a field inside a CRD's array. Every ignored element of a built-in list in
# such an Application is a list fleet.sh converge's repair_env_order puts back in git's order.
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
RESPECT = "RespectIgnoreDifferences=true"
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


def in_scheme(obj: dict) -> bool:
    """scheme.Scheme.New(gvk) succeeds: the built-in groups (core, apps, the *.k8s.io ones); a CRD's does not."""
    group = obj.get("apiVersion", "").rpartition("/")[0]
    return group == "" or "." not in group or group.endswith(".k8s.io")


def synced_target(target: dict, live: dict | None, expressions: list[str], respect: bool = True) -> dict:
    """What a sync applies for one resource: the target as committed, or with RespectIgnoreDifferences the
    normalizeTargetResources result."""
    if not respect or live is None:
        return target
    normalized_target = normalize(target, expressions)
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


# ---- the inputs: the committed manifests, and each profile's rendered Applications --------------------------------
print(f"== the port is of the Argo CD the clusters run ({PORTED_FROM}) ==")
lock = (REPO / "VERSIONS.lock").read_text(encoding="utf-8")
argocd = re.search(r"^argocd\s+chart \S+ / app (v\S+)", lock, re.M)
check(f"VERSIONS.lock's argocd app is {PORTED_FROM}, the sync.go this ports (a bump: re-read normalizeTargetResources)",
      argocd is not None and argocd.group(1) == PORTED_FROM, argocd.group(1) if argocd else "no argocd line")
REPLAY = REPO / "docs/research/2026-10-30-argo-sync-replay"
check("the real-code replay this port is checked against is committed beside it",
      all((REPLAY / f).is_file() for f in ("README.md", "main.go", "go.mod", "go.sum", "replay.sh")))
check("and it is of the same Argo CD", PORTED_FROM in (REPLAY / "README.md").read_text(encoding="utf-8")
      if (REPLAY / "README.md").is_file() else False)


def committed(rel: str, kind: str, name: str) -> dict:
    return next(d for d in yaml.safe_load_all((REPO / rel).read_text(encoding="utf-8"))
                if d and d.get("kind") == kind and d["metadata"]["name"] == name)


AGENT_FILE = "gitops/ai-layer-agent/workshop-agent.yaml"
AGENT = committed(AGENT_FILE, "Agent", "workshop-agent")
check("the Agent is not in the ai-layer bundle any more (#679)",
      not [d for d in yaml.safe_load_all((REPO / "gitops/ai-layer/resources.yaml").read_text(encoding="utf-8"))
           if d and d.get("kind") == "Agent"])
check("ai-layer-agent's bundle is the Agent alone, in namespace agent",
      yaml.safe_load((REPO / "gitops/ai-layer-agent/kustomization.yaml").read_text(encoding="utf-8"))
      == {"apiVersion": "kustomize.config.k8s.io/v1beta1", "kind": "Kustomization", "namespace": "agent",
          "resources": ["workshop-agent.yaml"]})


def server(agent: dict, name: str) -> dict:
    return next(t["mcpServer"] for t in agent["spec"]["declarative"]["tools"] if t["mcpServer"]["name"] == name)


GIT_TOOLS = server(AGENT, "workshop-mcp")["toolNames"]
check("git's workshop-mcp list is the stale eleven plus read_support_ticket (#640)",
      [t for t in GIT_TOOLS if t != "read_support_ticket"] == STALE_ELEVEN and "read_support_ticket" in GIT_TOOLS)


def rendered(app_file: str, profile: str) -> dict:
    raw = without_front_door(for_c7_control((APPS / app_file).read_text(encoding="utf-8"), c7_control(profile)))
    return yaml.safe_load(raw.replace(REVISION, "0" * 40).replace(IMAGE_REGISTRY, LAB_PLATFORM_GHCR))


def respects(app: dict) -> bool:
    return RESPECT in (((app.get("spec") or {}).get("syncPolicy") or {}).get("syncOptions") or [])


def ignores(app: dict, group: str, kind: str, name: str) -> list[str]:
    return [e for i in app["spec"].get("ignoreDifferences") or []
            if i.get("group", "") == group and i.get("kind") == kind and i.get("name") in (None, name)
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
check("and ai-layer-agent beside it", all("ai-layer-agent" in app_names(p) for p in ai_profiles))
check("only admin puts C7 on agentgateway's rule (c7Control gateway), the profile the web terminal's _c7gw names",
      [p for p in ai_profiles if c7_control(p) == "gateway"] == ["admin"])

print("== the layout before #679 reproduces it: the Agent in ai-layer, which respects its ignores ==")
# The old ai-layer Agent ignores on a toolnames profile, as 69ba6cf rendered them.
OLD = [EVIL, ".spec.declarative.modelConfig"]
stale = live_agent(workshop_tools=STALE_ELEVEN)
applied = synced_target(AGENT, stale, OLD, respect=True)
check("the Agent is a CRD, outside Argo CD's scheme, so the copy is a JSON merge patch", not in_scheme(AGENT))
check("git's twelve show as drift on the stale Agent (OutOfSync)", out_of_sync(AGENT, stale, OLD))
check("the sync applies the LIVE tools array, so read_support_ticket never lands",
      server(applied, "workshop-mcp")["toolNames"] == STALE_ELEVEN, str(server(applied, "workshop-mcp")["toolNames"]))
check("so the applied Agent is still OutOfSync, every auto-sync after it the same",
      out_of_sync(AGENT, synced_target(AGENT, applied, OLD), OLD))

for profile in ai_profiles:
    control = c7_control(profile)
    agent_app, ai = rendered("ai-layer-agent.yaml", profile), rendered("ai-layer.yaml", profile)
    agent_ignores = ignores(agent_app, "kagent.dev", "Agent", "workshop-agent")
    print(f"== {profile} (c7Control {control}): ai-layer-agent syncs the Agent's tools from git ==")
    check(f"{profile}: ai-layer has no Agent ignore", ignores(ai, "kagent.dev", "Agent", "workshop-agent") == [])
    check(f"{profile}: ai-layer-agent does not respect its ignores on sync", not respects(agent_app))
    want = ([EVIL] if control == "toolnames" else []) + [".spec.declarative.modelConfig"]
    check(f"{profile}: ai-layer-agent's Agent ignores are {want}", agent_ignores == want, str(agent_ignores))
    got = synced_target(AGENT, stale, agent_ignores, respect=respects(agent_app))
    check(f"{profile}: the stale eleven: the sync applies git's workshop-mcp list, read_support_ticket included",
          server(got, "workshop-mcp")["toolNames"] == GIT_TOOLS, str(server(got, "workshop-mcp")["toolNames"]))
    check(f"{profile}: and git's whole tools array, headersFrom included",
          got["spec"]["declarative"]["tools"] == AGENT["spec"]["declarative"]["tools"])
    check(f"{profile}: after it the Agent is Synced", not out_of_sync(AGENT, got, agent_ignores))
    narrowed = live_agent(evil_tools=["get_weather"])
    if control == "toolnames":
        check(f"{profile}: a student's guard-mcp-on (evil-mcp narrowed to get_weather) reads Synced, so selfHeal "
              "never syncs it away", not out_of_sync(AGENT, narrowed, agent_ignores))
        both = live_agent(workshop_tools=STALE_ELEVEN, evil_tools=["get_weather"])
        check(f"{profile}: the cost, held on purpose: a sync the Agent's own commit starts resets that fix to git's list",
              server(synced_target(AGENT, both, agent_ignores, respect=False), "evil-mcp")["toolNames"]
              == server(AGENT, "evil-mcp")["toolNames"])
    else:
        check(f"{profile}: nothing on admin writes evil-mcp's list but the committed one, so selfHeal restoring it is "
              "right", out_of_sync(AGENT, narrowed, agent_ignores))
    tiered = live_agent(model_config="bedrock-claude")
    check(f"{profile}: a per-cluster modelConfig reads Synced (a field of a map, ignored in the diff)",
          not out_of_sync(AGENT, tiered, agent_ignores))
    check(f"{profile}: a fresh cluster (no live Agent) gets git's Agent as committed",
          synced_target(AGENT, None, agent_ignores, respect=respects(agent_app)) == AGENT)

print("== guard-proxy's env, a built-in list with ignored elements, under ai-layer's RespectIgnoreDifferences ==")
PROXY = committed("gitops/ai-layer/resources.yaml", "Deployment", "guard-proxy")
GIT_ENV = [e["name"] for e in PROXY["spec"]["template"]["spec"]["containers"][0]["env"]]
ai = rendered("ai-layer.yaml", "burn")
proxy_ignores = ignores(ai, "apps", "Deployment", "guard-proxy")
check("ai-layer respects its ignores on sync, the option the strategic half of the port is", respects(ai))
check("guard-proxy's ignores name env entries of the proxy container", len(proxy_ignores) == 1
      and '.env[] | select(.name | test(' in proxy_ignores[0] and 'select(.name=="proxy")' in proxy_ignores[0])
check("a Deployment is in Argo CD's scheme, so the copy is a strategic merge patch", in_scheme(PROXY))
check("git puts CONSOLE_ORIGIN before OTEL_SERVICE_NAME", GIT_ENV.index("CONSOLE_ORIGIN") < GIT_ENV.index("OTEL_SERVICE_NAME"))


def live_proxy(drop: str | None = None, append: str | None = None, tier: str | None = None) -> dict:
    live = copy.deepcopy(PROXY)
    live["metadata"].update({"namespace": "agent", "uid": "5e1f", "resourceVersion": "777", "generation": 3})
    live["status"] = {"replicas": 1, "readyReplicas": 1}
    env = live["spec"]["template"]["spec"]["containers"][0]["env"]
    if drop:
        env[:] = [e for e in env if e["name"] != drop]
    if append:
        env[:] = [e for e in env if e["name"] != append] + [e for e in env if e["name"] == append]
    for e in env:
        if tier and e["name"] == "MODEL_TIER":
            e["value"] = tier
    return live


def env_of(obj: dict) -> list[tuple[str, str]]:
    return [(e["name"], e.get("value", "")) for e in obj["spec"]["template"]["spec"]["containers"][0]["env"]]


before = live_proxy(drop="CONSOLE_ORIGIN", tier="sonnet")
got = synced_target(PROXY, before, proxy_ignores)
check("a6af457, through Argo: git's new CONSOLE_ORIGIN lands, in git's place",
      [n for n, _ in env_of(got)] == GIT_ENV, str([n for n, _ in env_of(got)]))
check("with the live MODEL_TIER=sonnet toggle kept", dict(env_of(got))["MODEL_TIER"] == "sonnet")
check("and the Deployment reads Synced after it", not out_of_sync(PROXY, got, proxy_ignores))
appended = live_proxy(append="CONSOLE_ORIGIN", tier="sonnet")
check("the same entry added live with `kubectl set env`, which appends: OutOfSync on order alone",
      out_of_sync(PROXY, appended, proxy_ignores)
      and sorted(env_of(appended)) == sorted(env_of(live_proxy(tier="sonnet"))))
got = synced_target(PROXY, appended, proxy_ignores)
check("#679: the sync applies the LIVE order, CONSOLE_ORIGIN still last",
      [n for n, _ in env_of(got)][-1] == "CONSOLE_ORIGIN", str([n for n, _ in env_of(got)][-3:]))
check("so it is OutOfSync after every sync, and selfHeal syncs it alone for good",
      out_of_sync(PROXY, got, proxy_ignores) and out_of_sync(PROXY, synced_target(PROXY, got, proxy_ignores), proxy_ignores))
# repair_env_order's rewrite: the live entries in git's order, values kept (verify/test_fleet_converge_repairs.sh runs it).
reordered = copy.deepcopy(appended)
env = reordered["spec"]["template"]["spec"]["containers"][0]["env"]
env[:] = [e for n in GIT_ENV for e in env if e["name"] == n] + [e for e in env if e["name"] not in GIT_ENV]
got = synced_target(PROXY, reordered, proxy_ignores)
check("after repair_env_order puts the live list in git's order, the sync keeps it and the Deployment reads Synced",
      [n for n, _ in env_of(got)] == GIT_ENV and not out_of_sync(PROXY, got, proxy_ignores))
check("with the toggle still kept", dict(env_of(got))["MODEL_TIER"] == "sonnet")

print("== no Application freezes a list on sync that converge cannot put right ==")
# A JSON merge patch replaces an array whole, so on a resource outside Argo CD's scheme (a CRD: a dotted group not
# under k8s.io) an ignore that reaches INTO an array element freezes the whole array, and nothing can repair that but
# deleting the object. That is never allowed under RespectIgnoreDifferences, on any profile. On a built-in kind an
# ignore that selects an ELEMENT of a merge-key list freezes that list's order, which repair_env_order puts right, so
# each must be one of its rows. An ignore of a whole field (`.rules`, a ConfigMap's data key) freezes that field on
# purpose and is not a list element.
BUILTIN = re.compile(r"^$|^[a-z0-9]+$|\.k8s\.io$")
fleet = (REPO / "infra/terraform/fleet/fleet.sh").read_text(encoding="utf-8")
rows = re.search(r"^ENV_ORDER_LISTS=\(\n(.*?)\n\)", fleet, re.M | re.S)
order_rows = {tuple(r.strip().strip('"').split()) for r in rows.group(1).splitlines()} if rows else set()
check("fleet.sh repair_one runs repair_env_order", re.search(
    r"^repair_one\(\) \{\n(?:.*\n){0,10}?    repair_step repair_env_order \"\$\{name\}\" \"\$\{kcfg\}\"", fleet, re.M)
      is not None)
check(f"repair_env_order covers guard-proxy and agentgateway ({sorted(order_rows)})",
      order_rows == {("guard-proxy", "proxy", "gitops/ai-layer/resources.yaml"),
                     ("agentgateway", "agentgateway", "gitops/ai-layer/agentgateway.yaml")})
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
            if not respects(app):
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
