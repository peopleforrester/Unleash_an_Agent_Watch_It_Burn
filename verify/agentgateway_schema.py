# ABOUTME: The JSON Schema subset that checks agentgateway configs against the vendored upstream schema.
# ABOUTME: Shared by test_agentgateway_config.py (the committed config) and test_tool_pin.py (the #480 spike bind).
"""A small subset of JSON Schema: refs, properties, required, additionalProperties, unevaluatedProperties,
oneOf/anyOf and types. That is everything agentgateway's schema uses for the shapes we write, and it keeps
the offline suite dependency-free (verify/ runs on stdlib plus PyYAML). Why it exists: #394, in
test_agentgateway_config.py's docstring.
"""
from __future__ import annotations

import json
import pathlib

REPO = pathlib.Path(__file__).resolve().parents[1]
SCHEMA_VERSION = "v1.7.0"
SCHEMA = REPO / f"verify/schemas/agentgateway-{SCHEMA_VERSION}-config.json"


def load_schema() -> dict:
    return json.loads(SCHEMA.read_text(encoding="utf-8"))


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
