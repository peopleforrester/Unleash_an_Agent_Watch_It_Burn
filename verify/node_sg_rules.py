# ABOUTME: Reads the cluster root's node_security_group_additional_rules out of module "eks" in main.tf, so the
# ABOUTME: offline and tools-tier checks of #869 and #906 parse it one way, and the cluster group's rules likewise.
"""The block is plain HCL the repo writes itself: a map of rule name to an object of `key = value` lines. This
reads it with brace matching and a line regex, which is enough for that shape; it is not an HCL parser. Each
anchor it cuts on is checked first, and a missing one raises AnchorMissing naming the literal and the file."""
from __future__ import annotations

import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parents[1]
CLUSTER_TF = REPO / "infra/terraform/aws/cluster/main.tf"
MODULE_ANCHOR = 'module "eks" {'
RULES_ANCHOR = "node_security_group_additional_rules = {"
# The cluster security group's own rules (#906). The newline and indent are part of the literal: without them it is
# also the tail of the node rules' anchor above.
CLUSTER_RULES_ANCHOR = "\n  security_group_additional_rules = {"

# The workshop apps lab-platform's attendee check reaches through the API server's Service proxy, by the pod
# port the control plane dials (issue #869, measured on watch-it-burn-private 2026-11-05).
APP_PORTS = {
    8080: "the five demo apps, argocd-server and kagent-ui",
    3000: "Grafana",
}


class AnchorMissing(Exception):
    pass


def _block(text: str, anchor: str, where: str) -> str:
    """The body between the `{` that ends `anchor` and its matching `}`."""
    start = text.find(anchor)
    if start < 0:
        raise AnchorMissing(f"the literal {anchor!r} is not in {where}")
    i = start + len(anchor)
    depth = 1
    while i < len(text) and depth:
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
        i += 1
    if depth:
        raise AnchorMissing(f"the block opened by {anchor!r} in {where} never closes")
    return text[start + len(anchor):i - 1]


def eks_module_body(text: str | None = None) -> str:
    text = CLUSTER_TF.read_text(encoding="utf-8") if text is None else text
    return _block(text, MODULE_ANCHOR, str(CLUSTER_TF.relative_to(REPO)))


def rules_body(text: str | None = None, anchor: str = RULES_ANCHOR) -> str:
    return _block(eks_module_body(text), anchor, f'module "eks" in {CLUSTER_TF.relative_to(REPO)}')


_VALUE = re.compile(r'^\s*([a-z_]+)\s*=\s*(.+?)\s*$')


def _value(raw: str):
    if raw.startswith('"') and raw.endswith('"'):
        return raw[1:-1]
    if re.fullmatch(r"-?\d+", raw):
        return int(raw)
    if raw in ("true", "false"):
        return raw == "true"
    return raw  # an expression, kept as written


def rules(text: str | None = None, anchor: str = RULES_ANCHOR) -> dict[str, dict]:
    """Rule name -> {attribute: value}. Strings are unquoted, numbers and bools converted, anything else raw.
    The node rules by default; CLUSTER_RULES_ANCHOR reads the cluster security group's."""
    body = rules_body(text, anchor)
    out: dict[str, dict] = {}
    for m in re.finditer(r'^\s*([A-Za-z0-9_]+)\s*=\s*\{(.*?)^\s*\}', body, re.MULTILINE | re.DOTALL):
        attrs = {}
        for line in m.group(2).splitlines():
            line = line.split("#", 1)[0]
            v = _VALUE.match(line)
            if v:
                attrs[v.group(1)] = _value(v.group(2))
        out[m.group(1)] = attrs
    return out


def rule_for_port(all_rules: dict[str, dict], port: int) -> list[str]:
    """Names of the rules that admit TCP `port` from the cluster security group, inbound."""
    return [name for name, r in all_rules.items()
            if r.get("type", "ingress") == "ingress"
            and r.get("protocol", "tcp") in ("tcp", "6")
            and r.get("source_cluster_security_group") is True
            and isinstance(r.get("from_port"), int) and isinstance(r.get("to_port"), int)
            and r["from_port"] <= port <= r["to_port"]]
