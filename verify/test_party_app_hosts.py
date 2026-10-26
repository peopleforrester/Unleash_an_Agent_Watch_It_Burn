# ABOUTME: The party apps have no ALB Ingress of their own and nothing deployed joins watch-it-burn-ingress:
# ABOUTME: they are reached at <app>-<cluster>.agenticburn.com through the console LB (#233, #554).
"""Why (#554). Each party app shipped an internet-facing ALB Ingress in group watch-it-burn-ingress for a fixed
host (hedgehog.agenticburn.com and so on), the same host on every cluster. Since #233 the party apps are reached
at <app>-<cluster>.agenticburn.com, which the apex router sends to the console LB and the console's nginx fans
out on Host. The Ingresses kept an ALB alive on every cluster that deployed a party app, the one #493 meant to
remove when it took Grafana out of the group. gitops/argocd/values.yaml carried a third claimant,
argocd.agenticburn.com, in a file nothing installed: deploy-full-idp.sh installs Argo CD from
infra/argocd-values.yaml.
"""
from __future__ import annotations

import pathlib
import re
import sys

import yaml

REPO = pathlib.Path(__file__).resolve().parent.parent
GITOPS = REPO / "gitops"
sys.path.insert(0, str(REPO / "verify"))
from bootstrap_chart import is_template  # noqa: E402
CONF = (GITOPS / "ai-layer/console.conf").read_text(encoding="utf-8")
DEPLOY = (REPO / "infra/deploy-full-idp.sh").read_text(encoding="utf-8")
PARTY = ["hedgehog", "wombat", "unicorn", "spider", "mantis-shrimp"]
GROUP_KEY = "alb.ingress.kubernetes.io/group.name"

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"\n        {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def walk(node):
    """Every dict in a parsed document, so Helm valuesObject blocks are searched as well as manifests."""
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from walk(v)
    elif isinstance(node, list):
        for v in node:
            yield from walk(v)


# gitops/apps-disabled holds Applications no root installs; everything else under gitops/ can reach a cluster.
# The root chart's templates are Go template text, not YAML (#609); none of them is an Ingress.
deployable = [p for p in sorted(GITOPS.rglob("*.yaml"))
              if "apps-disabled" not in p.relative_to(GITOPS).parts and not is_template(p)]
alb, grouped = [], []
for p in deployable:
    for doc in yaml.safe_load_all(p.read_text(encoding="utf-8")):
        for d in walk(doc):
            if d.get("ingressClassName") == "alb":
                alb.append(str(p.relative_to(REPO)))
            if GROUP_KEY in d:
                grouped.append(str(p.relative_to(REPO)))

print("== nothing deployable asks for an ALB ==")
check("no deployable manifest or Helm values names ingressClassName alb", not alb, f"{sorted(set(alb))}")
check("and nothing joins the ALB group watch-it-burn-ingress", not grouped, f"{sorted(set(grouped))}")

print("== each party app is served through the console, not its own Ingress ==")
for app in PARTY:
    mdir = GITOPS / f"manifests/demo-app-{app}"
    kinds = [d.get("kind") for p in sorted(mdir.glob("*.yaml"))
             for d in yaml.safe_load_all(p.read_text(encoding="utf-8")) if d]
    check(f"demo-app-{app} still ships its Service", "Service" in kinds, f"kinds={kinds}")
    check(f"demo-app-{app} ships no Ingress", "Ingress" not in kinds, f"kinds={kinds}")
    row = re.search(rf'"~\^{re.escape(app)}-\[a-z0-9-\]\+\\\.agenticburn\\\.com\$"\s+(\S+);', CONF)
    check(f"console.conf maps {app}-<cluster>.agenticburn.com to demo-app-{app}",
          bool(row) and row.group(1) == f"http://demo-app-{app}.apps.svc.cluster.local:80",
          f"row={row.group(1) if row else None!r}")
m = re.search(r"^\s*server_name\s+~\^\(([^)]+)\)-", CONF, re.M)
names = m.group(1).split("|") if m else []
check("the console's service server block answers every party host", all(a in names for a in PARTY), f"{names}")

print("== Argo CD is installed from infra/argocd-values.yaml, and the unused gitops copy is gone ==")
check("deploy-full-idp.sh installs Argo CD with infra/argocd-values.yaml",
      '--values "${SCRIPT_DIR}/argocd-values.yaml"' in DEPLOY)
check("gitops/argocd/values.yaml, which claimed argocd.agenticburn.com on the ALB, is gone",
      not (GITOPS / "argocd/values.yaml").exists())

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All party-app host checks passed.")
