# ABOUTME: Render gate for the agentgateway config: validate it against the vendored upstream schema for
# ABOUTME: the exact image tag we run, so a bad key is caught here instead of by a crash-looping pod.
"""Why this exists (#394).

Building the inference bind cost four failed bootstraps, each one discovered the same way: apply the
config, watch the gateway crash-loop, read the rejection message, guess the next key. The binary was the
only validator we had. It rejected `llm:` for `ai:`, then `host` for `hostOverride`, then a missing
`region`, then an `auth` block that is not a field at this level at all.

agentgateway publishes a JSON schema per release. Checking the committed config against the one for the
tag we actually run turns every one of those four into a failure here, offline, in under a second.

The validator, in agentgateway_schema.py, is a small subset of JSON Schema: refs, properties, required, additionalProperties,
unevaluatedProperties, oneOf/anyOf and types. That is everything this schema uses for the shapes we
write, and it keeps the offline suite dependency-free (the rest of verify/ runs on stdlib plus PyYAML).
"""
from __future__ import annotations

import json
import pathlib
import sys

import yaml

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from agentgateway_schema import SCHEMA, SCHEMA_VERSION, Invalid, validate  # noqa: E402

REPO = pathlib.Path(__file__).resolve().parents[1]
GATEWAY = REPO / "gitops/ai-layer/agentgateway.yaml"
# Pinned to the image tag in the Deployment (SCHEMA_VERSION, in agentgateway_schema.py). The test asserts
# they agree, so a bump without a new schema fails here rather than silently checking against the wrong version.

failures: list[str] = []


def check(name: str, cond: bool) -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        failures.append(name)


# --- the checks ---------------------------------------------------------------------------------
docs = [d for d in yaml.safe_load_all(GATEWAY.read_text(encoding="utf-8")) if d]
deployment = next(d for d in docs if d["kind"] == "Deployment" and d["metadata"]["name"] == "agentgateway")
image = deployment["spec"]["template"]["spec"]["containers"][0]["image"]


def image_tag(ref: str) -> str:
    """The tag out of a reference that may also carry a digest.

    `repo:tag@sha256:...` is the pinned form (#415), and a naive rsplit on ':' returns the digest hex
    from it. Splitting the digest off first is what makes the version check survive pinning.
    """
    return ref.split("@", 1)[0].rsplit(":", 1)[-1]


print("== the schema on disk is the one for the image we run ==")
check(f"image is {SCHEMA_VERSION} (found {image_tag(image)})", image_tag(image) == SCHEMA_VERSION)
# Pinning is asserted separately so a future bump cannot quietly drop the digest (#415).
check("the gateway image is pinned by digest as well as tag", "@sha256:" in image)
check("the vendored schema for that version exists", SCHEMA.exists())

print("== every recorded version is the image we run ==")
# The image went to v1.5.0 on 2026-09-10 while the span version, the version label and VERSIONS.lock
# stayed at v1.3.0 for six weeks, so every gateway span reported the wrong version (#495).
tag = image_tag(image)
env = {e["name"]: e.get("value", "") for e in deployment["spec"]["template"]["spec"]["containers"][0].get("env", [])}
attrs = dict(kv.split("=", 1) for kv in env.get("OTEL_RESOURCE_ATTRIBUTES", "").split(",") if "=" in kv)
check(f"spans carry service.version={tag} (found {attrs.get('service.version')})", attrs.get("service.version") == tag)
# The C7 container (#514) is a second process in the same pod and emits its own spans. It must report the
# same version, and the first container's check above cannot see it.
for c in deployment["spec"]["template"]["spec"]["containers"]:
    cenv = {e["name"]: e.get("value", "") for e in c.get("env", [])}
    cattrs = dict(kv.split("=", 1) for kv in cenv.get("OTEL_RESOURCE_ATTRIBUTES", "").split(",") if "=" in kv)
    check(f"container {c['name']} spans carry service.version={tag} (found {cattrs.get('service.version')})",
          cattrs.get("service.version") == tag)
label = deployment["metadata"]["labels"].get("app.kubernetes.io/version")
check(f"the Deployment's app.kubernetes.io/version label is {tag.lstrip('v')} (found {label})", label == tag.lstrip("v"))
lock = next((l for l in (REPO / "VERSIONS.lock").read_text(encoding="utf-8").splitlines() if l.startswith("agentgateway ")), "")
check(f"VERSIONS.lock records agentgateway {tag} (found {lock.split()[1:3]})", lock.split()[1:3] == ["OSS", tag])

print("== the working docs name the image we run ==")
# #495 fixed gitops/ and VERSIONS.lock; the walkthrough, the specs and the gateway notes went on calling
# v1.3.0 the current version (#506). Each of these states the deployed version, and a line may name the
# old one only beside the new one, as history ("moved from v1.3.0"). DECISION-LOG and the dated research
# notes are records and are not checked.
CURRENT_DOCS = (
    "agent/GATEWAY-NOTES.md",
    "docs/STACK-WALKTHROUGH.md",
    "docs/MASTER-RECREATION-SPEC.md",
    "docs/BUILD-SPEC.md",
    "docs/TECH-STATUS.md",
    "docs/UPGRADE-INVENTORY.md",
)
for rel in CURRENT_DOCS:
    lines = (REPO / rel).read_text(encoding="utf-8").splitlines()
    check(f"{rel} names agentgateway {tag}", any("agentgateway" in l and tag in l for l in lines))
    stale = [i for i, l in enumerate(lines, 1) if "v1.3.0" in l and tag not in l]
    check(f"{rel} names v1.3.0 only beside {tag} (lines {stale})", not stale)
if not SCHEMA.exists():
    print(f"\nFAILED: {len(failures)} check(s)")
    sys.exit(1)

root = json.loads(SCHEMA.read_text(encoding="utf-8"))
cm = next(d for d in docs if d["kind"] == "ConfigMap" and d["metadata"]["name"] == "agentgateway-config")
config = yaml.safe_load(cm["data"]["config.yaml"])

print("== the committed config validates against it ==")
try:
    validate(config, root, root)
    check("the whole config validates", True)
except Invalid as e:
    check(f"the whole config validates ({e})", False)

print("== the validator is not vacuous ==")
# Negative controls, one per mistake that actually crash-looped a cluster.
for label, mutate in (
    ("an unknown backend key is rejected", lambda c: c["binds"][-1]["listeners"][0]["routes"][0]["backends"][0]["ai"].update({"host": "x"})),
    ("a bedrock provider without a region is rejected", lambda c: c["binds"][-1]["listeners"][0]["routes"][0]["backends"][0]["ai"]["provider"]["bedrock"].pop("region")),
    ("an auth block on a provider is rejected", lambda c: c["binds"][-1]["listeners"][0]["routes"][0]["backends"][0]["ai"].update({"auth": {"aws": {}}})),
):
    broken = yaml.safe_load(cm["data"]["config.yaml"])
    mutate(broken)
    try:
        validate(broken, root, root)
        check(label, False)
    except Invalid:
        check(label, True)

print("== C7's evil-mcp bind (#514) validates too, in both of its rule states ==")
# The second container runs the same binary, so it must run the same pinned image the schema is for.
images = {c["name"]: c["image"] for c in deployment["spec"]["template"]["spec"]["containers"]}
check(f"every agentgateway container runs the same pinned image ({sorted(images)})", set(images.values()) == {image})
c7_cm = next((d for d in docs if d["kind"] == "ConfigMap" and d["metadata"]["name"] == "agentgateway-c7-config"), None)
check("there is an agentgateway-c7-config ConfigMap", c7_cm is not None)
c7_text = c7_cm["data"]["config.yaml"] if c7_cm else ""
marked = [line for line in c7_text.splitlines() if line.rstrip().endswith("# c7-rule")]
check(f"exactly one line carries the # c7-rule marker, and it is - 'true' ({marked})",
      [line.strip() for line in marked] == ["- 'true' # c7-rule"])
# The C7 control's on state (guard-proxy-agenticburn#5 reads the same line): only get_weather is allowed.
ON_RULE = "'mcp.tool.name == \"get_weather\"'"
for label, text in (("as committed", c7_text),
                    ("with the rule set to get_weather", c7_text.replace("- 'true' # c7-rule", f"- {ON_RULE} # c7-rule"))):
    c7_config = yaml.safe_load(text) or {}
    try:
        validate(c7_config, root, root)
        check(f"the C7 config validates {label}", True)
    except Invalid as e:
        check(f"the C7 config validates {label} ({e})", False)
    routes = [r for b in c7_config.get("binds", []) for l in b["listeners"] for r in l["routes"]]
    found = [x for r in routes for x in r.get("policies", {}).get("mcpAuthorization", {}).get("rules", [])]
    want = "true" if label == "as committed" else 'mcp.tool.name == "get_weather"'
    check(f"its one mcpAuthorization rule is {want!r} {label}", found == [want])
broken = yaml.safe_load(c7_text) or {}
try:
    broken["binds"][0]["listeners"][0]["routes"][0]["policies"]["mcpAuthorization"]["deny"] = ["true"]
    validate(broken, root, root)
    rejected = False
except Invalid:
    rejected = True
except (KeyError, IndexError):
    rejected = False  # no rule block to put the key beside; the checks above already fail
check("an unknown key beside the C7 rules is rejected (the validator reaches this bind)", rejected)

# Both processes share the pod's network namespace. agentgateway's defaults are admin 15000, stats 15020 and
# readiness 15021; the first container keeps them, so the second must move or switch off every one.
c7_static = (yaml.safe_load(c7_text) or {}).get("config", {})
check("the C7 container's admin and stats listeners are off",
      c7_static.get("adminAddr") == "off" and c7_static.get("statsAddr") == "off")
ready_port = int(str(c7_static.get("readinessAddr", ":15021")).rsplit(":", 1)[-1])
main_ports = {p["containerPort"] for p in deployment["spec"]["template"]["spec"]["containers"][0]["ports"]}
check(f"its readiness listener ({ready_port}) takes no port the first container holds",
      ready_port not in main_ports | {15000, 15020, 15021})
c7_container = next((c for c in deployment["spec"]["template"]["spec"]["containers"] if c["name"] == "agentgateway-c7"), {})
c7_ports = {p["containerPort"] for p in c7_container.get("ports", [])}
c7_bind_ports = {b["port"] for b in (yaml.safe_load(c7_text) or {}).get("binds", [])}
check("the C7 container declares its bind and its readiness port, and nothing the first one holds",
      c7_ports == c7_bind_ports | {ready_port} and not (c7_ports & main_ports))

print("== the bedrock backend's model is pinned through the container env (#561) ==")
# agentgateway v1.5.0 runs the whole config file through shellexpand::full before parsing it
# (crates/agentgateway/src/config.rs, parse_config), so a $VAR or ${VAR} its container does not set fails the
# whole config at startup, comments included. That is what lets the model come from the env, and why every
# reference has to resolve.
import re  # noqa: E402

REF = re.compile(r"\$\{?([A-Za-z_][A-Za-z0-9_]*)")
containers = {c["name"]: c for c in deployment["spec"]["template"]["spec"]["containers"]}
for cm_name, container in (("agentgateway-config", "agentgateway"), ("agentgateway-c7-config", "agentgateway-c7")):
    text = next(d for d in docs if d["kind"] == "ConfigMap" and d["metadata"]["name"] == cm_name)["data"]["config.yaml"]
    cenv = {e["name"] for e in containers.get(container, {}).get("env", [])}
    refs = set(REF.findall(text))
    check(f"every variable {cm_name} reads is set on the {container} container ({sorted(refs - cenv)} unset)",
          refs <= cenv)
bedrock_backends = [be["ai"]["provider"]["bedrock"] for b in config["binds"] for l in b["listeners"] for r in l["routes"]
                    for be in r["backends"] if "bedrock" in (be.get("ai") or {}).get("provider", {})]
check(f"there is one bedrock backend ({len(bedrock_backends)})", len(bedrock_backends) == 1)
main_env = {e["name"]: e.get("value", "") for e in containers["agentgateway"].get("env", [])}
tiers = re.search(r"bedrock_tiers\s*=\s*\{(.*?)\}", (REPO / "infra/terraform/aws/cluster/main.tf").read_text(encoding="utf-8"), re.S)
tier_ids = set(re.findall(r'=\s*"([^"]+)"', tiers.group(1))) if tiers else set()
for bedrock in bedrock_backends:
    model = str(bedrock.get("model", ""))
    ref = re.fullmatch(r"\$\{(\w+)\}", model)
    # Inline, the model is a system profile, which cannot be tagged, and fleet.sh has nothing to set.
    check(f"its model is a ${{VAR}} reference, not an inline id (found {model!r})", ref is not None)
    committed = main_env.get(ref.group(1), "") if ref else ""
    check(f"the variable is committed to a system profile id the cluster root copies into a tagged profile "
          f"(found {committed!r})", committed in tier_ids)
    # Live the variable holds an application profile ARN. The provider puts it into the URL path and escapes
    # its '/' as %2F (crates/llm/src/bedrock.rs, get_path_for_route, read at tag v1.5.0); that is a property
    # of the binary, confirmed live by a call through gateway-bedrock-nova, not something this file can test.
    arn = "arn:aws:bedrock:us-west-2:111122223333:application-inference-profile/abcd1234efgh"
    expanded = yaml.safe_load(cm["data"]["config.yaml"].replace(model, arn))
    try:
        validate(expanded, root, root)
        check("the config validates with the ARN in place", True)
    except Invalid as e:
        check(f"the config validates with the ARN in place ({e})", False)

print("== the inference bind is what the toggle switches between ==")
bind = next((b for b in config["binds"] if b["port"] == 3002), None)
check("there is an inference bind on :3002", bind is not None)
if bind:
    backends = [r["backends"][0]["ai"] for l in bind["listeners"] for r in l["routes"]]
    by_name = {b["name"]: b for b in backends}
    check("a bedrock route", any("bedrock" in b.get("provider", {}) for b in backends))
    check("and a local route pointed at the in-cluster server, not api.openai.com",
          any("openAI" in b.get("provider", {}) and b.get("hostOverride", "").endswith(".svc.cluster.local:8000")
              for b in backends))
    # The credential is ambient (AIProvider::Bedrock supplies implicit AWS auth itself), so what has to
    # exist is the Pod Identity association, not a key in this file.
    tf = (REPO / "infra/terraform/aws/cluster/main.tf").read_text(encoding="utf-8")
    check("the gateway ServiceAccount is associated with the Bedrock role",
          'service_account = "agentgateway"' in tf)
    check("no static AWS credentials are committed anywhere in the gateway config",
          "accessKeyId" not in cm["data"]["config.yaml"] and "secretAccessKey" not in cm["data"]["config.yaml"])

if failures:
    print(f"\nFAILED: {len(failures)} check(s)")
    sys.exit(1)
print("\nAll agentgateway-config checks passed.")
