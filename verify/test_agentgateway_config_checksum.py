# ABOUTME: Fails when the agentgateway pod template's checksum/agentgateway-config annotation does not match
# ABOUTME: sha256 of agentgateway-config's config.yaml. Without it a static-section change syncs green and never rolls the pod.
"""Why this exists (#878).

agentgateway-config is a plain ConfigMap with a stable name, so a committed change to its config.yaml changes
nothing in the Deployment's pod template and nothing rolls the pod. v1.7.0 hot-reloads the binds, but not the
static `config:` section, and it refuses some migrations outright: on watch-it-burn-community on 2026-11-05 it
logged `Failed to reload config: cannot use deprecated config.tracing together with frontendPolicies.tracing`
on #864's ConfigMap and went on serving the config it had started with, with Argo CD reporting Synced and
Healthy. The annotation is what makes the pod template change with the content, so Argo CD rolls the pod and the
new one reads the file at startup. It is bumped by hand, as guard-proxy's checksum/proxy-py is
(verify/test_proxy_checksum.py), and this test is what makes forgetting it a red test instead of a stale gateway.

agentgateway-c7-config is kept out of the checksum on purpose: its rule line is flipped live on an admin cluster,
its container reloads it without a restart, and ai-layer ignores drift on it. A C7 rule flip must not roll the pod.
"""
from __future__ import annotations

import hashlib
import pathlib
import sys

import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
GATEWAY = REPO / "gitops" / "ai-layer" / "agentgateway.yaml"
APP = REPO / "gitops" / "bootstrap" / "apps" / "ai-layer.yaml"
ANNOTATION = "checksum/agentgateway-config"
CONFIG = "agentgateway-config"
C7_CONFIG = "agentgateway-c7-config"

# The literals the mutated cases below are built on. Each must occur exactly once in the committed file, so a
# reworded anchor reads as that and not as a broken check further on (CLAUDE.md, Tests own their inputs).
STATIC_ANCHOR = "      session:\n        key: disabled\n    # Tracing is a frontend policy (#864)."
C7_RULE_ANCHOR = "              - 'true' # c7-rule"

failures: list[str] = []


def check(name: str, cond: bool) -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        failures.append(name)


def load(text: str) -> list[dict]:
    return [d for d in yaml.safe_load_all(text) if d]


def one(docs: list[dict], kind: str, name: str) -> dict:
    found = [d for d in docs if d.get("kind") == kind and d["metadata"]["name"] == name]
    if len(found) != 1:
        print(f"FAIL  expected exactly one {kind} {name} in {GATEWAY.relative_to(REPO)}, found {len(found)}")
        sys.exit(1)
    return found[0]


def expected(docs: list[dict]) -> str:
    """The value the annotation must carry: sha256 of the ConfigMap's config.yaml string, first 12 hex digits."""
    return hashlib.sha256(one(docs, "ConfigMap", CONFIG)["data"]["config.yaml"].encode("utf-8")).hexdigest()[:12]


def carried(docs: list[dict]) -> str | None:
    template = one(docs, "Deployment", "agentgateway")["spec"]["template"]
    return ((template.get("metadata") or {}).get("annotations") or {}).get(ANNOTATION)


def current(docs: list[dict]) -> bool:
    return carried(docs) is not None and carried(docs) == expected(docs)


text = GATEWAY.read_text(encoding="utf-8")
for label, anchor in (("the static-section anchor", STATIC_ANCHOR), ("the C7 rule anchor", C7_RULE_ANCHOR)):
    if text.count(anchor) != 1:
        print(f"FAIL  {label} {anchor!r} occurs {text.count(anchor)} times in {GATEWAY.relative_to(REPO)}, not once; "
              "the cases below edit the file on it, so change it here in the same commit")
        sys.exit(1)

docs = load(text)
deploy = one(docs, "Deployment", "agentgateway")
want = expected(docs)
got = carried(docs)

print("== the pod template carries the checksum of agentgateway-config ==")
check(f"the pod template carries a {ANNOTATION} annotation", got is not None)
check(f"{ANNOTATION} matches sha256(config.yaml)[:12] (want {want}, got {got})", got == want)
if got != want:
    print(f"\n  Bump it: set {ANNOTATION} to {want} in {GATEWAY.relative_to(REPO)}")
check("the value is 12 lowercase hex digits", isinstance(got, str) and len(got) == 12
      and all(c in "0123456789abcdef" for c in got))
check("it is on the pod template, not on the Deployment's own metadata (which rolls nothing)",
      ANNOTATION not in (deploy["metadata"].get("annotations") or {}))

print("== a change to the static section changes the pod template ==")
# The case: one key added to the static `config:` section, the part v1.7.0 does not hot-reload. The committed
# annotation must then read as stale, which is this test going red on the commit that forgot to bump it.
edited = load(text.replace(STATIC_ANCHOR, STATIC_ANCHOR.replace("key: disabled\n", 'key: disabled\n      adminAddr: "off"\n'), 1))
check("the edited config has the new key", one(edited, "ConfigMap", CONFIG)["data"]["config.yaml"].count('adminAddr: "off"') == 1)
check("its expected checksum differs from the committed one", expected(edited) != want)
check("the committed annotation reads as stale on it (the test would fail that commit)", not current(edited))
check("the committed file reads as current", current(docs))

print("== a C7 rule flip does not roll the pod ==")
# The case: the C7 rule turned on, the edit guard-mcp-on makes live and the one a commit to the C7 ConfigMap makes.
flipped = load(text.replace(C7_RULE_ANCHOR, "              - 'mcp.tool.name == \"get_weather\"' # c7-rule", 1))
check("the flipped C7 config carries the rule",
      'mcp.tool.name == "get_weather"' in one(flipped, "ConfigMap", C7_CONFIG)["data"]["config.yaml"])
check("agentgateway-config's checksum is unchanged by it", expected(flipped) == want)
check("the annotation still reads as current on it", current(flipped))
template_annotations = (deploy["spec"]["template"].get("metadata") or {}).get("annotations") or {}
check("no pod template annotation names agentgateway-c7-config",
      not any(C7_CONFIG in k or C7_CONFIG in str(v) for k, v in template_annotations.items()))
c7_hash = hashlib.sha256(one(docs, "ConfigMap", C7_CONFIG)["data"]["config.yaml"].encode("utf-8")).hexdigest()
check("no pod template annotation carries the C7 config's hash",
      not any(str(v) and str(v) in c7_hash for v in template_annotations.values()))

print("== Argo CD syncs the annotation (ai-layer ignores no part of the pod template) ==")
app = yaml.safe_load(APP.read_text(encoding="utf-8"))
gateway_ignores = [e for i in app["spec"].get("ignoreDifferences", [])
                   if i.get("kind") == "Deployment" and i.get("name") == "agentgateway" for e in i.get("jqPathExpressions", [])]
check("the agentgateway Deployment ignore names env entries only", gateway_ignores
      and all(".env[]" in e and "annotations" not in e and "metadata" not in e for e in gateway_ignores))

print(f"\n{'FAILED: ' + ', '.join(failures) if failures else 'agentgateway-config checksum annotation is current.'}")
sys.exit(1 if failures else 0)
