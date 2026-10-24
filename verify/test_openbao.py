# ABOUTME: Render gate for OpenBao as the cluster's secret store (#394, question 656): the pieces agree on names,
# ABOUTME: every profile installs it, the deploy seeds it before the root, and openbao-secrets.sh behaves. Offline.
"""Why this exists.

OpenBao went in as five pieces in five places: the Application (gitops/apps/openbao.yaml), ESO's store
(security/eso/cluster-secret-store.yaml), the ExternalSecrets that write datadog-secret
(security/openbao/datadog-externalsecrets.yaml), the script that makes the token and seeds the store
(infra/openbao-secrets.sh), and the two callers (deploy-full-idp.sh and fleet.sh's repair). They meet only
at names: a Secret name, a namespace, a store name, a KV path. Get one wrong and nothing fails until a
cluster comes up without Datadog and the collector quietly ships to Tempo alone. So the names are checked
against each other here, and the script is run against a kubectl stand-in that records what it was asked.

The ordering matters as much as the names. datadog-secret used to be written before the root app-of-apps
so that its readers found it at start (32a30e2). Argo CD here runs no health check on child Applications,
so sync waves alone cannot keep that promise; the deploy script does, by seeding before it applies the
root. That order is asserted below, on the script's text.
"""
from __future__ import annotations

import base64
import fnmatch
import os
import pathlib
import re
import subprocess
import sys
import tempfile

import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
APP = yaml.safe_load((REPO / "gitops/apps/openbao.yaml").read_text(encoding="utf-8"))
STORE = yaml.safe_load((REPO / "security/eso/cluster-secret-store.yaml").read_text(encoding="utf-8"))
EXTERNAL = [d for d in yaml.safe_load_all((REPO / "security/openbao/datadog-externalsecrets.yaml").read_text(encoding="utf-8")) if d]
ESO_APP = yaml.safe_load((REPO / "gitops/apps/external-secrets.yaml").read_text(encoding="utf-8"))
SCRIPT = REPO / "infra/openbao-secrets.sh"
SCRIPT_TXT = SCRIPT.read_text(encoding="utf-8")
DEPLOY = (REPO / "infra/deploy-full-idp.sh").read_text(encoding="utf-8")
FLEET = (REPO / "infra/terraform/fleet/fleet.sh").read_text(encoding="utf-8")
NAMESPACES = [d for d in yaml.safe_load_all((REPO / "gitops/namespaces/namespaces.yaml").read_text(encoding="utf-8")) if d]
# The three namespaces whose readers take datadog-secret, as deploy-full-idp.sh wrote them before #394.
READERS = {"datadog", "monitoring", "security"}

failures: list[str] = []


def check(name: str, cond: bool) -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        failures.append(name)


print("== the Application is the sister's dev-mode shape, with a per-cluster token and a fence ==")
values = APP["spec"]["source"]["helm"]["valuesObject"]
server = values["server"]
check("chart openbao 0.29.4 from the openbao-helm repo",
      APP["spec"]["source"]["chart"] == "openbao" and APP["spec"]["source"]["targetRevision"] == "0.29.4")
check("dev mode on, injector and UI off",
      server["dev"]["enabled"] is True and values["injector"]["enabled"] is False and values["ui"]["enabled"] is False)
env = {e["envName"]: e for e in server.get("extraSecretEnvironmentVars", [])}
check("the root token comes from openbao-root-token through an env var the dev command expands",
      env.get("OPENBAO_ROOT_TOKEN", {}).get("secretName") == "openbao-root-token"
      and env["OPENBAO_ROOT_TOKEN"].get("secretKey") == "token"
      and "-dev-root-token-id=" in server.get("extraArgs", "") and "${OPENBAO_ROOT_TOKEN}" in server["extraArgs"])
check("the chart's fixed token is not the guessable default", server["dev"].get("devRootToken") != "root")
check("CPU and memory limits are set (require-resource-limits covers every pod)",
      {"cpu", "memory"} <= set(server["resources"]["limits"]))
ingress = server["networkPolicy"]["ingress"]
froms = [f for rule in ingress for f in rule.get("from", [])]
check("the NetworkPolicy is on and admits 8200 from the ESO namespace only",
      server["networkPolicy"]["enabled"] is True and len(ingress) == 1
      and froms == [{"namespaceSelector": {"matchLabels": {"kubernetes.io/metadata.name": ESO_APP["spec"]["destination"]["namespace"]}}}]
      and ingress[0]["ports"] == [{"port": 8200, "protocol": "TCP"}])
check("it installs into the openbao namespace, which namespaces.yaml declares",
      APP["spec"]["destination"]["namespace"] == "openbao"
      and any(d["kind"] == "Namespace" and d["metadata"]["name"] == "openbao" for d in NAMESPACES))

print("== ESO's store, the ExternalSecrets and the script name the same things ==")
vault = STORE["spec"]["provider"].get("vault", {})
tok = vault.get("auth", {}).get("tokenSecretRef", {})
check("the store reads OpenBao's Service in the openbao namespace, KV v2 at secret/",
      vault.get("server") == "http://openbao.openbao.svc.cluster.local:8200" and vault.get("path") == "secret"
      and vault.get("version") == "v2")
check("it authenticates with platform/openbao-token, in the namespace ESO runs in",
      tok == {"name": "openbao-token", "namespace": ESO_APP["spec"]["destination"]["namespace"], "key": "token"})
check("the script writes both token Secrets the Application and the store read",
      '"openbao/openbao-root-token" "platform/openbao-token"' in SCRIPT_TXT)
check("no store points at AWS Secrets Manager any more", "aws" not in STORE["spec"]["provider"])
check("one ExternalSecret per reader namespace", {d["metadata"]["namespace"] for d in EXTERNAL} == READERS and len(EXTERNAL) == 3)
for d in EXTERNAL:
    ns, spec = d["metadata"]["namespace"], d["spec"]
    check(f"{ns}: named datadog-secret (what reload-datadog-consumers.sh force-syncs), from the openbao store",
          d["metadata"]["name"] == "datadog-secret" and spec["secretStoreRef"] == {"kind": "ClusterSecretStore", "name": STORE["metadata"]["name"]})
    check(f"{ns}: writes datadog-secret, kept when a dev-mode restart empties the store",
          spec["target"] == {"name": "datadog-secret", "creationPolicy": "Owner", "deletionPolicy": "Retain"})
    check(f"{ns}: api-key and app-key from secret/datadog, the path the seed writes",
          sorted((x["secretKey"], x["remoteRef"]["key"], x["remoteRef"]["property"]) for x in spec["data"])
          == [("api-key", "datadog", "api-key"), ("app-key", "datadog", "app-key")])
check("the seed writes that path", "bao kv put -mount=secret datadog api-key=" in SCRIPT_TXT)
check("the script's reader namespaces are the ExternalSecrets' namespaces",
      re.search(r'SECRET_NAMESPACES="([^"]+)"', SCRIPT_TXT) is not None
      and set(re.search(r'SECRET_NAMESPACES="([^"]+)"', SCRIPT_TXT).group(1).split()) == READERS)
check("reload-datadog-consumers.sh still force-syncs externalsecret/datadog-secret",
      "externalsecret datadog-secret" in (REPO / "infra/reload-datadog-consumers.sh").read_text(encoding="utf-8"))

print("== every profile installs the three Applications the deploy script applies ahead of the root ==")
PREAPPLIED = ("external-secrets.yaml", "eso-resources.yaml", "openbao.yaml")


def expand(glob: str) -> list[str]:
    m = re.fullmatch(r"\{(.*)\}(.*)", glob)
    return [p + m.group(2) for p in m.group(1).split(",")] if m else [glob]


for root in sorted((REPO / "gitops/bootstrap").glob("*/*.yaml")):
    doc = yaml.safe_load(root.read_text(encoding="utf-8"))
    sel = next(s for s in doc["spec"]["sources"] if s.get("path") == "gitops/apps").get("directory", {})
    if "include" in sel:
        takes = lambda f: any(fnmatch.fnmatch(f, p) for p in expand(sel["include"]))  # noqa: E731
    else:
        takes = lambda f: not any(fnmatch.fnmatch(f, p) for p in expand(sel.get("exclude", "")) if p)  # noqa: E731
    missing = [f for f in PREAPPLIED if not takes(f)]
    # A root that left one out would never own it, so its prune would never clean it up and its selfHeal
    # would never repair it, while the deploy script went on installing it.
    check(f"{root.parent.name}: takes all three" + (f" (missing {missing})" if missing else ""), not missing)

print("== the deploy seeds OpenBao before it applies the root, and nothing writes datadog-secret around it ==")
pre = DEPLOY.find('gitops/apps/openbao.yaml"')
seed = DEPLOY.find('openbao-secrets.sh" seed')
token = DEPLOY.find('openbao-secrets.sh" token')
root_apply = DEPLOY.find('kubectl apply -f "${REPO}/${ROOT_APP}"')
check("token, then the three Applications, then the seed, then the root",
      -1 < token < pre < seed < root_apply)
check("the seed runs only when there are keys (no key leaves Datadog off, #500)",
      re.search(r'if \[\[ -n "\$\{DD_API_KEY\}" && -n "\$\{DD_APP_KEY\}" \]\]; then\s+CONTEXT=.*\n\s+bash "\$\{SCRIPT_DIR\}/openbao-secrets.sh" seed', DEPLOY) is not None)
for name, txt in (("deploy-full-idp.sh", DEPLOY), ("fleet.sh", FLEET)):
    check(f"{name} no longer creates datadog-secret directly", "create secret generic datadog-secret" not in txt)
check("fleet.sh's repair re-seeds OpenBao", "run_openbao_seed" in FLEET and "openbao-secrets.sh\" seed" in FLEET)

print("== openbao-secrets.sh, run against a kubectl that records what it is asked ==")
with tempfile.TemporaryDirectory(prefix="openbao-test.") as tmp:
    t = pathlib.Path(tmp)
    (t / "bin").mkdir()
    calls, stdin_log = t / "calls", t / "stdin"
    (t / "bin/kubectl").write_text(f"""#!/usr/bin/env bash
echo "kubectl $*" >>'{calls}'
case "$*" in
  *"get secret openbao-root-token -o jsonpath={{.data.token}}"*) [[ -f '{t}/token' ]] && base64 <'{t}/token' | tr -d '\\n' ;;
  *"get secret datadog-secret -o jsonpath={{.data.api-key}}"*) printf '%s' API_KEY_1234 | base64 ;;
  *"exec -i"*) cat >>'{stdin_log}' ;;
  *"--dry-run=client -o yaml"*) echo "kind: Placeholder" ;;
  *"apply -f -"*) cat >/dev/null ;;
esac
exit 0
""")
    (t / "bin/kubectl").chmod(0o755)
    base = {**os.environ, "PATH": f"{t / 'bin'}:{os.environ['PATH']}", "OPENBAO_WAIT_S": "5"}

    def run(*args: str, **env: str) -> subprocess.CompletedProcess:
        return subprocess.run(["bash", str(SCRIPT), *args], env={**base, **env}, capture_output=True, text=True)

    check("no CONTEXT is a failure, before any kubectl call",
          run("token").returncode != 0 and not calls.exists())
    r = run("token", CONTEXT="ctx-a")
    made = re.findall(r"create secret generic (\S+) --from-literal=token=(\S+)", calls.read_text())
    check("token: both Secrets get the same freshly generated 64-hex token",
          r.returncode == 0 and [n for n, _ in made] == ["openbao-root-token", "openbao-token"]
          and len({v for _, v in made}) == 1 and re.fullmatch(r"[0-9a-f]{64}", made[0][1]) is not None)
    check("every kubectl call names the context it was given",
          all("--context ctx-a" in line for line in calls.read_text().splitlines()))
    calls.unlink()
    (t / "token").write_text("EXISTING_TOKEN")
    run("token", CONTEXT="ctx-a")
    made = re.findall(r"create secret generic (\S+) --from-literal=token=(\S+)", calls.read_text())
    check("token: an existing token is reused, never rotated under a running server",
          {v for _, v in made} == {"EXISTING_TOKEN"})
    calls.unlink()
    check("seed: no keys is a failure", run("seed", CONTEXT="ctx-a").returncode != 0)
    r = run("seed", CONTEXT="ctx-a", WITB_DD_API_KEY="API_KEY_1234", WITB_DD_APP_KEY="APP_KEY_5678")
    log = calls.read_text()
    check("seed: succeeds once ESO has written the seeded key", r.returncode == 0)
    check("seed: the keys and token reach the pod on stdin", stdin_log.read_text().split() == ["EXISTING_TOKEN", "API_KEY_1234", "APP_KEY_5678"])
    check("seed: never on this host's command line", "API_KEY_1234" not in log and "APP_KEY_5678" not in log and "EXISTING_TOKEN" not in log)
    check("seed: applies the ExternalSecrets and force-syncs each reader namespace",
          "apply -f " + str(REPO / "security/openbao/datadog-externalsecrets.yaml") in log
          and all(f"-n {ns} annotate externalsecret datadog-secret" in log for ns in READERS))
    r = run("seed", CONTEXT="ctx-a", WITB_DD_API_KEY="A_DIFFERENT_KEY", WITB_DD_APP_KEY="APP_KEY_5678")
    check("seed: a datadog-secret still holding the old key is a failure, not a repair",
          r.returncode != 0 and "carrying the seeded key" in r.stderr)

if failures:
    print(f"\nFAILED: {len(failures)} check(s)")
    sys.exit(1)
print("\nAll OpenBao checks passed.")
