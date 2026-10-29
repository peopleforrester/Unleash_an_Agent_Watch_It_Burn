# ABOUTME: Render gate for #519: every cluster object the pinned proxy.py reads for the /controls C7 badge, and every
# ABOUTME: other object it reads, is granted get by name to guard-proxy-reader, configmaps/agentgateway-c7-config too.
"""Why this exists (#519).

The C7 badge in guard-proxy-agenticburn#5 lights when agentgateway's rule for evil-mcp is narrowed or the agent's
toolNames drop the rogue tools. proxy.py reads both objects with _k8s_get as guard-proxy-reader, and a read the
Role does not grant comes back None, which the badge shows unlit: on stage, after guard-mcp-on, C7 would read
unarmed with nothing failing. verify/test_c7_gateway_reader.py holds the ConfigMap grant's shape (#564); this
holds the other side, that the paths the pinned proxy.py actually reads are the ones granted, so a re-pin that
reads a new object, or a renamed one, fails here and not in the room.

The paths are read from proxy.py's own _k8s_get calls, each a string literal, and resolved to an API group,
resource, namespace and name. A namespaced read in `agent` may be granted by the Role guard-proxy-reader; any read
may be granted by the ClusterRole. Each binding has to bind its role to ServiceAccount agent/guard-proxy-reader.
"""
from __future__ import annotations

import ast
import pathlib
import sys

import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
PROXY = REPO / "gitops/ai-layer/guard-proxy/proxy.py"
RESOURCES = list(yaml.safe_load_all((REPO / "gitops/ai-layer/resources.yaml").read_text()))
READER = "guard-proxy-reader"
SUBJECT = {"kind": "ServiceAccount", "name": READER, "namespace": "agent"}
# The two objects guard-proxy-agenticburn#5's C7 badge reads, which this check must find among the C7 reads.
C7_MUST_READ = {("", "configmaps", "agent", "agentgateway-c7-config"),
                ("kagent.dev", "agents", "agent", "workshop-agent")}

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}{('  -> ' + detail) if (detail and not cond) else ''}")
    if not cond:
        failures.append(name)


def one(kind: str, name: str) -> dict:
    found = [d for d in RESOURCES if d and d.get("kind") == kind and d.get("metadata", {}).get("name") == name]
    check(f"{kind}/{name} is declared exactly once", len(found) == 1)
    return found[0] if found else {}


def resolve(path: str) -> tuple[str, str, str | None, str] | None:
    """An API path for one object as (group, resource, namespace, name); namespace None when cluster-scoped."""
    parts = path.strip("/").split("/")
    if parts[:2] == ["api", "v1"]:
        group, rest = "", parts[2:]
    elif parts[:1] == ["apis"] and len(parts) >= 3:
        group, rest = parts[1], parts[3:]
    else:
        return None
    if len(rest) == 4 and rest[0] == "namespaces":
        return group, rest[2], rest[1], rest[3]
    if len(rest) == 2:
        return group, rest[0], None, rest[1]
    return None


def grants(rule: dict, group: str, resource: str, name: str) -> bool:
    """get on this one object by name; a rule without resourceNames grants every name, which is not by name."""
    return (group in rule.get("apiGroups", []) and resource in rule.get("resources", [])
            and name in (rule.get("resourceNames") or []) and "get" in rule.get("verbs", []))


# --- the reads, from the pinned proxy.py ------------------------------------------------------------------
print(f"what the pinned proxy.py reads ({PROXY.relative_to(REPO)})")
check("the guard-proxy submodule is checked out", PROXY.is_file(), "run: git submodule update --init")
tree = ast.parse(PROXY.read_text(encoding="utf-8")) if PROXY.is_file() else ast.Module(body=[], type_ignores=[])
funcs = {n.name: n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}


def k8s_reads(fn: ast.FunctionDef) -> list[ast.Call]:
    return [c for c in ast.walk(fn) if isinstance(c, ast.Call) and getattr(c.func, "id", None) == "_k8s_get"]


calls = [(name, c) for name, fn in funcs.items() for c in k8s_reads(fn)]
check("proxy.py reads the cluster through _k8s_get", bool(calls))
literal = [(name, c.args[0].value) for name, c in calls
           if len(c.args) == 1 and isinstance(c.args[0], ast.Constant) and isinstance(c.args[0].value, str)]
check("every _k8s_get call takes one string-literal path, so this check sees every object read",
      len(literal) == len(calls), f"{[ast.unparse(c) for _, c in calls]}")
reads = {(name, path): resolve(path) for name, path in literal}
check("every path names one object", all(reads.values()), f"{[p for (_, p), r in reads.items() if not r]}")

# The C7 reads: read_controls sets out["tool_allowlist"] under `if` tests on local names, each bound to a call
# of a reader function; the _k8s_get calls inside those functions are what the badge reads.
rc = funcs.get("read_controls")
check("proxy.py has read_controls", rc is not None)
rc_nodes = list(ast.walk(rc)) if rc else []


def sets_c7(node: ast.AST) -> bool:
    return any(isinstance(s, ast.Assign) and any(isinstance(t, ast.Subscript) and isinstance(t.slice, ast.Constant)
                                                 and t.slice.value == "tool_allowlist" for t in s.targets)
               for s in ast.walk(node))


bound = {t.id: getattr(n.value.func, "id", None) for n in rc_nodes
         if isinstance(n, ast.Assign) and isinstance(n.value, ast.Call) for t in n.targets if isinstance(t, ast.Name)}
c7_vars = {x.id for n in rc_nodes if isinstance(n, ast.If) and sets_c7(n)
           for x in ast.walk(n.test) if isinstance(x, ast.Name)}
c7_funcs = {bound[v] for v in c7_vars if v in bound}
check("read_controls decides tool_allowlist on names bound to reader-function calls",
      bool(c7_vars) and c7_vars <= set(bound) and c7_funcs <= set(funcs),
      f"tests {sorted(c7_vars)}, bound {sorted((v, bound.get(v)) for v in c7_vars)}")
c7_reads = {r for (name, _), r in reads.items() if name in c7_funcs and r}
for r in sorted(C7_MUST_READ):
    check(f"the C7 badge reads {r[1]}/{r[3]} in {r[2]} (via {sorted(c7_funcs)})", r in c7_reads, f"{sorted(c7_reads)}")

# --- the grants, from resources.yaml ----------------------------------------------------------------------
print(f"\nwhat {READER} is granted (gitops/ai-layer/resources.yaml)")
role, cluster_role = one("Role", READER), one("ClusterRole", READER)
check(f"Role {READER} is in namespace agent", role.get("metadata", {}).get("namespace") == "agent")
rb, crb = one("RoleBinding", READER), one("ClusterRoleBinding", READER)
check(f"RoleBinding {READER} binds Role {READER} to agent/{READER}",
      rb.get("roleRef", {}).get("kind") == "Role" and rb.get("roleRef", {}).get("name") == READER
      and SUBJECT in (rb.get("subjects") or []), f"{rb.get('roleRef')} {rb.get('subjects')}")
check(f"ClusterRoleBinding {READER} binds ClusterRole {READER} to agent/{READER}",
      crb.get("roleRef", {}).get("kind") == "ClusterRole" and crb.get("roleRef", {}).get("name") == READER
      and SUBJECT in (crb.get("subjects") or []), f"{crb.get('roleRef')} {crb.get('subjects')}")
proxy_pod = one("Deployment", "guard-proxy").get("spec", {}).get("template", {}).get("spec", {})
check(f"guard-proxy runs as {READER}", proxy_pod.get("serviceAccountName") == READER,
      f"{proxy_pod.get('serviceAccountName')!r}")

print("\nevery read is granted by name")
for (fn, path), r in sorted(reads.items(), key=lambda kv: kv[0][1]):
    if not r:
        continue
    group, resource, ns, name = r
    by_role = ns == "agent" and any(grants(x, group, resource, name) for x in role.get("rules", []))
    by_cluster_role = any(grants(x, group, resource, name) for x in cluster_role.get("rules", []))
    tag = " (C7)" if fn in c7_funcs else ""
    check(f"{fn}{tag} reads {path}: get on {resource or '?'}/{name} granted to {READER} by name",
          by_role or by_cluster_role)

if failures:
    print(f"\nFAIL: {len(failures)} check(s) failed: {failures}")
    sys.exit(1)
print(f"\nPASS: every object the pinned proxy.py reads, the C7 badge's ConfigMap and Agent among them, is granted "
      f"get by name to {READER}")
