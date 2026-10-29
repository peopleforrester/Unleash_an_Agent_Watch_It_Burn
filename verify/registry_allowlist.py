# ABOUTME: Reads restrict-image-registries' allow-list out of the policy itself, so render gates judge an
# ABOUTME: image the way the policy does without each test re-deriving it from the YAML.
"""The policy is a Kyverno CEL ValidatingPolicy (#206). Its allow-list is two variables:
`allowedRegistries`, a CEL list of registry prefixes, and `ecr`, a host-anchored regex for any ECR registry.
A third, `refusedPaths`, lists paths refused on any registry: lab-platform's promo/, where the C2 villains live
(#653). An image is allowed when it starts with a prefix or matches the regex and contains no refused path,
exactly as the policy's expression says. The real evaluation of that expression is covered by
verify/test_kyverno_cel_policies.py."""
from __future__ import annotations

import pathlib
import re

import yaml

POLICY = pathlib.Path(__file__).resolve().parents[1] / "policies/kyverno/restrict-image-registries.yaml"


def _variables() -> dict[str, str]:
    pol = next(d for d in yaml.safe_load_all(POLICY.read_text(encoding="utf-8")) if d)
    return {v["name"]: v["expression"] for v in pol["spec"]["variables"]}


def prefixes() -> list[str]:
    return re.findall(r"'([^']+)'", _variables()["allowedRegistries"])


def ecr_regex() -> re.Pattern[str]:
    # The expression is a CEL raw string, r'...', so its body is the RE2 pattern verbatim.
    m = re.fullmatch(r"r'(.*)'", _variables()["ecr"].strip())
    if not m:
        raise ValueError(f"ecr variable is not a CEL raw string: {_variables()['ecr']!r}")
    return re.compile(m.group(1))


def refused_paths() -> list[str]:
    return re.findall(r"'([^']+)'", _variables()["refusedPaths"])


def allowed(image: str) -> bool:
    return ((any(image.startswith(p) for p in prefixes()) or ecr_regex().search(image) is not None)
            and not any(p in image for p in refused_paths()))
