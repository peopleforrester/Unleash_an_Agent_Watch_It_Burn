# ABOUTME: Reads require-resource-limits' required limit keys out of the policy itself, so render gates judge a
# ABOUTME: manifest the way the policy does without each test re-deriving it from the YAML.
"""The policy is a Kyverno CEL ValidatingPolicy (#206). Its `limitsSet` variable says every entry of
`object.spec.containers` carries each named key ('cpu', 'memory') under resources.limits. Kyverno autogen
applies the same check to a Deployment's pod template. The real evaluation of that expression is covered by
verify/test_kyverno_cel_policies.py."""
from __future__ import annotations

import pathlib
import re

import yaml

POLICY = pathlib.Path(__file__).resolve().parents[1] / "policies/kyverno/require-resource-limits.yaml"


def _limits_set() -> str:
    pol = next(d for d in yaml.safe_load_all(POLICY.read_text(encoding="utf-8")) if d)
    return next(v["expression"] for v in pol["spec"]["variables"] if v["name"] == "limitsSet")


def required() -> set[str]:
    expr = _limits_set()
    if not expr.strip().startswith("object.spec.containers.all("):
        raise ValueError(f"limitsSet no longer judges object.spec.containers: {expr!r}")
    keys = set(re.findall(r"'(\w+)' in c\.\?resources\.\?limits", expr))
    if not keys:
        raise ValueError(f"limitsSet names no limit keys: {expr!r}")
    return keys


def pod_spec(obj: dict) -> dict:
    """A Pod's spec, or the pod template's spec of a workload (what autogen judges)."""
    return obj["spec"] if obj.get("kind") == "Pod" else obj["spec"]["template"]["spec"]


def missing(obj: dict) -> list[str]:
    """The containers the policy would deny, each as 'name: missing keys'. Empty means it passes."""
    keys = required()
    out = []
    for c in pod_spec(obj).get("containers") or []:
        lack = sorted(keys - set(((c.get("resources") or {}).get("limits") or {})))
        if lack:
            out.append(f"{c.get('name')}: no {', '.join(lack)} limit")
    return out
