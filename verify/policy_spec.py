# ABOUTME: Compares a live Kyverno policy's CEL expressions with the repo file's, ignoring whitespace only, because
# ABOUTME: kustomize, which builds policies/kyverno for Argo CD since #638, adds a line break to some `>-` blocks.
"""Why (#608). Escalation 755 ran verify/test_llm_bypass_live.py against watch-it-burn-private with Argo CD's
kyverno-policies Application synced to the same staging revision as the checkout, and it stopped at the
prerequisite "live restrict-agent-spawned-workloads validation expressions are the repo's". The two #607
expressions differed from the repo's only by one empty line after their first line:

    live: "!object.spec.?volumes.orValue([]).exists(v,\\n\\n  (has(v.secret) && ..."
    repo: "!object.spec.?volumes.orValue([]).exists(v,\\n  (has(v.secret) && ..."

Both are folded scalars (`>-`) whose second line is more indented than their first. Since #638 (ea699ed),
policies/kyverno has a Kustomization, so Argo CD builds it with kustomize, and kustomize (v5.8.1 in kubectl v1.36.2)
writes such a block back out with one more empty line. The test reads the file itself with PyYAML, which has no such
line. CEL treats any run of whitespace outside a string literal as one separator, so the policy the cluster runs is
the repo's. Collapsing every whitespace run to one space before comparing makes the check say that, and a changed
name, operator or literal still differs. verify/test_policy_spec.py holds it to the live diff, and
verify/test_policy_spec_kustomize.py to the pinned kustomize's own render.
"""
from __future__ import annotations


def cel(expr: object) -> object:
    """An expression with every whitespace run collapsed to one space; anything else unchanged."""
    return " ".join(expr.split()) if isinstance(expr, str) else expr


def normalized(items: list | None) -> list:
    """A copy of a policy list field (matchConditions, variables, validations) with each `expression` put
    through cel(); every other key is kept as it is, so a changed name or message still differs."""
    return [{k: cel(v) if k == "expression" else v for k, v in item.items()} if isinstance(item, dict) else item
            for item in items or []]


def expressions(items: list | None) -> list:
    """The `expression` of each entry, through cel(), in order."""
    return [cel(item.get("expression")) for item in items or []]


def first_difference(have: list, want: list) -> str:
    """Where two expression lists part, for a FAIL line: the cluster's entry and the repo's, by index."""
    if len(have) != len(want):
        return f"cluster has {len(have)} expressions, the repo {len(want)}"
    for i, (h, w) in enumerate(zip(have, want)):
        if h != w:
            return f"expression {i}: cluster {h!r}, repo {w!r}"
    return ""
