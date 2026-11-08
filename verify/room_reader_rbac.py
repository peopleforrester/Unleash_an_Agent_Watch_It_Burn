# ABOUTME: The RBAC evaluation #1050's two tests share: every Role workshop-mcp can be bound to, each with the reader's
# ABOUTME: own Role beside it, allows list on every kind the room reader reports.
"""Shared by verify/test_room_reader_rbac.py (offline, on resources.yaml as written) and
verify/test_room_reader_rbac_e2e.py (tools tier, on the pinned kubectl's kustomize render of gitops/ai-layer).

check_all(check, docs, read, applied_files) takes the manifests of the ai-layer bundle and evaluates, for each Role
the workshop-agent binding can hold (the shipped one and every workshop-agent Role in the challenge-fixes ConfigMap),
the rules the API server would grant workshop-mcp: that Role's plus those of every other Role bound to the account.
It returns how many checks failed, so a caller can also run it on a broken copy and expect failures.
"""
from __future__ import annotations

import re

import yaml

NS = "agent"
SA = "workshop-mcp"
READER = "workshop-mcp-room-reader"
SWAPPED = "workshop-agent"
# The challenge-fixes keys that replace the workshop-agent Role: the guardrails switch and guard-rbac-on/off
# (c5-scoped-role, c8-broad-role), guard-agency-on/off (c6-least-privilege-role, c5-scoped-role), and Challenge 8's
# fix and reset in the lab (c8-scoped-role, c8-broad-role).
EXPECTED_SWAPS = {"c5-scoped-role.yaml", "c6-least-privilege-role.yaml", "c8-broad-role.yaml", "c8-scoped-role.yaml"}


def read_kinds(room_read_kinds) -> list[tuple[str, str, str]]:
    """(Kind, API group, plural) for each kind the reader lists, from workshop-mcp-server.py's ROOM_READ_KINDS."""
    return [(k, base.split("/")[2] if base.startswith("/apis/") else "", plural) for k, base, plural in room_read_kinds]


def applied_role_files(*texts: str) -> set[str]:
    """Every challenges/*role*.yaml the terminal's commands or the lab text apply."""
    return {m for t in texts for m in re.findall(r"apply -f \S*challenges/([\w.-]*role[\w.-]*\.yaml)", t)}


def allows(rules: list[dict], verb: str, group: str, plural: str) -> bool:
    """Whether RBAC rules allow a verb on a whole resource (a rule naming resourceNames covers no list)."""
    return any((group in r.get("apiGroups", []) or "*" in r.get("apiGroups", []))
               and (plural in r.get("resources", []) or "*" in r.get("resources", []))
               and (verb in r.get("verbs", []) or "*" in r.get("verbs", []))
               and not r.get("resourceNames")
               for r in rules)


def _bound_to_sa(binding: dict) -> bool:
    return any(s.get("kind") == "ServiceAccount" and s.get("name") == SA
               and s.get("namespace", binding["metadata"].get("namespace")) == NS
               for s in binding.get("subjects") or [])


def check_all(check, docs: list[dict], read: list[tuple[str, str, str]], applied_files: set[str],
              say=print) -> int:
    failed = 0

    def c(name: str, cond: bool, detail: str = "") -> None:
        nonlocal failed
        check(name, cond, detail)
        failed += 0 if cond else 1

    def one(kind: str, name: str) -> dict:
        found = [d for d in docs if d.get("kind") == kind and d.get("metadata", {}).get("name") == name
                 and d["metadata"].get("namespace") == NS]
        return found[0] if len(found) == 1 else {}

    say("== the reader's own Role and binding ==")
    reader, reader_binding = one("Role", READER), one("RoleBinding", READER)
    c(f"Role {READER} is in agent", bool(reader))
    c(f"RoleBinding {READER} binds that Role to the {SA} ServiceAccount and to nothing else",
      reader_binding.get("roleRef") == {"apiGroup": "rbac.authorization.k8s.io", "kind": "Role", "name": READER}
      and reader_binding.get("subjects") in ([{"kind": "ServiceAccount", "name": SA}],
                                             [{"kind": "ServiceAccount", "name": SA, "namespace": NS}]),
      str(reader_binding))
    grants = {(g, res, v) for r in reader.get("rules", []) for g in r.get("apiGroups", [])
              for res in r.get("resources", []) for v in r.get("verbs", [])}
    c("it grants list on exactly the kinds the reader reads, and nothing else",
      grants == {(g, p, "list") for _k, g, p in read} and not any(r.get("resourceNames") for r in reader.get("rules", [])),
      f"grants {sorted(grants)}")

    say("== every Role a swap puts on the workshop-agent binding ==")
    swapped_binding = one("RoleBinding", SWAPPED)
    c(f"the {SWAPPED} RoleBinding binds the {SA} ServiceAccount, so each swap of that Role reaches the reader",
      _bound_to_sa(swapped_binding) and swapped_binding.get("roleRef", {}).get("name") == SWAPPED, str(swapped_binding))
    fixes = one("ConfigMap", "challenge-fixes").get("data") or {}
    variants = {"resources.yaml (the shipped Role)": one("Role", SWAPPED)}
    for key, text in sorted(fixes.items()):
        if not key.endswith(".yaml"):
            continue
        for doc in yaml.safe_load_all(text):
            if isinstance(doc, dict) and doc.get("kind") == "Role" and doc.get("metadata", {}).get("name") == SWAPPED:
                variants[f"challenge-fixes {key}"] = doc
    keys = {k.removeprefix("challenge-fixes ") for k in variants if k.startswith("challenge-fixes ")}
    c("challenge-fixes holds each Role the switch, the guard commands and Challenge 8 apply",
      EXPECTED_SWAPS <= keys, f"found {sorted(keys)}")
    c("every role file the terminal's commands and the lab text apply is one of those workshop-agent Roles",
      bool(applied_files) and applied_files <= keys, f"applied {sorted(applied_files)}, Roles {sorted(keys)}")
    for label, doc in variants.items():
        c(f"{label} is the workshop-agent Role in agent",
          doc.get("kind") == "Role" and doc.get("metadata", {}).get("namespace", NS) == NS, str(doc.get("metadata")))

    say("== under each one, workshop-mcp lists every kind the reader reports ==")
    others = [d for d in docs if d.get("kind") == "RoleBinding" and d["metadata"].get("name") != SWAPPED
              and d["metadata"].get("namespace") == NS and _bound_to_sa(d)
              and d.get("roleRef", {}).get("kind") == "Role"]
    other_rules = [r for b in others for r in one("Role", b["roleRef"]["name"]).get("rules", [])]
    for label, doc in variants.items():
        rules = (doc.get("rules") or []) + other_rules
        missing = [k for k, g, p in read if not allows(rules, "list", g, p)]
        c(f"under {label}: list on {', '.join(k for k, _g, _p in read)}", not missing, f"no list on {missing}")
    return failed
