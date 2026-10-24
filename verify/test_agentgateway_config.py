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
label = deployment["metadata"]["labels"].get("app.kubernetes.io/version")
check(f"the Deployment's app.kubernetes.io/version label is {tag.lstrip('v')} (found {label})", label == tag.lstrip("v"))
lock = next((l for l in (REPO / "VERSIONS.lock").read_text(encoding="utf-8").splitlines() if l.startswith("agentgateway ")), "")
check(f"VERSIONS.lock records agentgateway {tag} (found {lock.split()[1:3]})", lock.split()[1:3] == ["OSS", tag])
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
