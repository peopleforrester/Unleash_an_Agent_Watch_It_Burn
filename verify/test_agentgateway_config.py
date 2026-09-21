# ABOUTME: Render gate for the agentgateway config: validate it against the vendored upstream schema for
# ABOUTME: the exact image tag we run, so a bad key is caught here instead of by a crash-looping pod.
"""Why this exists (#394).

Building the inference bind cost four failed bootstraps, each one discovered the same way: apply the
config, watch the gateway crash-loop, read the rejection message, guess the next key. The binary was the
only validator we had. It rejected `llm:` for `ai:`, then `host` for `hostOverride`, then a missing
`region`, then an `auth` block that is not a field at this level at all.

agentgateway publishes a JSON schema per release. Checking the committed config against the one for the
tag we actually run turns every one of those four into a failure here, offline, in under a second.

The validator below is a small subset of JSON Schema: refs, properties, required, additionalProperties,
unevaluatedProperties, oneOf/anyOf and types. That is everything this schema uses for the shapes we
write, and it keeps the offline suite dependency-free (the rest of verify/ runs on stdlib plus PyYAML).
"""
from __future__ import annotations

import json
import pathlib
import sys

import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
GATEWAY = REPO / "gitops/ai-layer/agentgateway.yaml"
# Pinned to the image tag in the Deployment. The test asserts they agree, so a bump without a new
# schema fails here rather than silently checking against the wrong version.
SCHEMA_VERSION = "v1.5.0"
SCHEMA = REPO / f"verify/schemas/agentgateway-{SCHEMA_VERSION}-config.json"

failures: list[str] = []


def check(name: str, cond: bool) -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        failures.append(name)


# --- the validator ------------------------------------------------------------------------------
class Invalid(Exception):
    pass


def resolve(schema: dict, root: dict) -> dict:
    seen = 0
    while "$ref" in schema:
        ref = schema["$ref"]
        if not ref.startswith("#/$defs/"):
            raise Invalid(f"unsupported $ref {ref}")
        schema = root["$defs"][ref.split("/")[-1]]
        seen += 1
        if seen > 20:
            raise Invalid("ref loop")
    return schema


TYPES = {
    "object": dict, "array": list, "string": str, "boolean": bool,
    "integer": int, "number": (int, float), "null": type(None),
}


def merge(parent: dict, variant: dict) -> dict:
    """Parent constraints plus one variant's, with properties and required unioned."""
    out = {k: v for k, v in parent.items() if k not in ("oneOf", "anyOf")}
    out.update({k: v for k, v in variant.items() if k not in ("oneOf", "anyOf", "properties", "required")})
    out["properties"] = {**parent.get("properties", {}), **variant.get("properties", {})}
    required = list(parent.get("required", [])) + list(variant.get("required", []))
    if required:
        out["required"] = required
    for closing in ("additionalProperties", "unevaluatedProperties"):
        if parent.get(closing) is False or variant.get(closing) is False:
            out[closing] = False
    if "oneOf" in variant or "anyOf" in variant:
        out.update({k: v for k, v in variant.items() if k in ("oneOf", "anyOf")})
    return out


def validate(value, schema: dict, root: dict, path: str = "") -> None:
    schema = resolve(schema, root)

    types = schema.get("type")
    if types is not None:
        allowed = [types] if isinstance(types, str) else types
        if not any(isinstance(value, TYPES[t]) for t in allowed if t in TYPES):
            raise Invalid(f"{path or '<root>'}: expected {allowed}, got {type(value).__name__}")

    for key in ("oneOf", "anyOf"):
        if key in schema:
            # A variant is checked against the parent's constraints AS WELL, not instead of them:
            # LocalRouteBackend carries weight and policies at the top and the backend kind in the
            # variants, so replacing rather than merging rejects a perfectly good `weight`. First match
            # wins, which is anyOf semantics; oneOf's exactly-one rule would only ever reject configs
            # this schema's overlapping variants make ambiguous.
            errors = []
            for variant in schema[key]:
                merged = merge(schema, resolve(variant, root))
                try:
                    validate(value, merged, root, path)
                    break
                except Invalid as e:
                    errors.append(str(e))
            else:
                raise Invalid(f"{path or '<root>'}: matched no variant ({'; '.join(errors[:4])})")
            return

    if isinstance(value, dict):
        props = schema.get("properties", {})
        for req in schema.get("required", []):
            if req not in value:
                raise Invalid(f"{path}: missing required field '{req}'")
        closed = schema.get("additionalProperties") is False or schema.get("unevaluatedProperties") is False
        for k, v in value.items():
            if k in props:
                validate(v, props[k], root, f"{path}.{k}")
            elif closed:
                raise Invalid(f"{path}: unknown field '{k}' (valid: {sorted(props)})")
    elif isinstance(value, list) and "items" in schema:
        for i, item in enumerate(value):
            validate(item, schema["items"], root, f"{path}[{i}]")


# --- the checks ---------------------------------------------------------------------------------
docs = [d for d in yaml.safe_load_all(GATEWAY.read_text(encoding="utf-8")) if d]
deployment = next(d for d in docs if d["kind"] == "Deployment" and d["metadata"]["name"] == "agentgateway")
image = deployment["spec"]["template"]["spec"]["containers"][0]["image"]

print("== the schema on disk is the one for the image we run ==")
check(f"image is {SCHEMA_VERSION} (found {image.rsplit(':', 1)[-1]})", image.endswith(f":{SCHEMA_VERSION}"))
check("the vendored schema for that version exists", SCHEMA.exists())
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
