# ABOUTME: Renders the Datadog Secrets fleet.sh, deploy-full-idp.sh and the identity script write with the real kubectl:
# ABOUTME: each value read from the env file decodes to what was meant, and no manifest carries an annotation (#977).
# SUITE: e2e (needs kubectl: reading --from-env-file is kubectl's)
# E2E TIER: tools (no cluster, no AWS: run-e2e-tools.sh runs it with the pinned tools, #572)
"""#977 moved the Datadog keys from --from-literal arguments to an env file on a file descriptor, and the writes from
apply to replace. test_datadog_secrets_off_argv.py and test_fleet_converge_repairs.sh hold the calls against fakes.
Whether kubectl reads each env-file line back as the exact value, the dual-shipping JSON blobs with their quotes,
colons and "=" included, is kubectl's behaviour, so this renders the manifests with the pinned kubectl and
KUBECONFIG=/dev/null. A wrapper hands every client-side create to the real kubectl, its --context dropped since
/dev/null has none, and keeps what replace reads on stdin. No cluster is reached.
"""
from __future__ import annotations

import base64
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
FLEET_DIR = REPO / "infra/terraform/fleet"
DEPLOY = REPO / "infra/deploy-full-idp.sh"
IDENT = REPO / "infra/datadog-cluster-identity.sh"
CTX = "arn:aws:eks:us-west-2:111122223333:cluster/watch-it-burn-attendee-001"
OWN_API, OWN_APP, ADMIN_API = "OWN-API-SENTINEL-5d1", "OWN-APP-SENTINEL-9b2", "ADMIN-API-SENTINEL-c47"
failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"\n        {detail}" if detail and not ok else ""))
    if not ok:
        failures.append(name)


KUBECTL = shutil.which("kubectl")
if not KUBECTL:
    print("FAIL: kubectl is not on PATH (run through verify/run-e2e-tools.sh, which puts the pinned one first)",
          file=sys.stderr)
    sys.exit(1)

WRAPPER = """#!/usr/bin/env bash
args=(); skip=0
for a in "$@"; do
    if [[ "${skip}" -eq 1 ]]; then skip=0; continue; fi
    [[ "${a}" == "--context" ]] && { skip=1; continue; }
    args+=("${a}")
done
n="${#args[@]}"
if [[ "${n}" -ge 3 && "${args[n-2]}" == "-f" && "${args[n-1]}" == "-" ]]; then
    { cat; echo "---"; } >>"${OUT}/${args[n-3]}"; exit 0
fi
[[ " ${args[*]} " == *" create "*" --dry-run=client "* ]] && exec "${REAL_KUBECTL}" "${args[@]}"
exit 0
"""
STUB = """#!/usr/bin/env bash
[[ "$(basename "$0")" == aws && " $* " == *" describe-cluster "* ]] && { echo vpc-0abc; exit 0; }
[[ "$(basename "$0")" == aws ]] && exit 1
exit 0
"""


def secrets(text: str) -> list[dict]:
    return [d for d in yaml.safe_load_all(text) if d and d.get("kind") == "Secret"]


def decoded(doc: dict) -> dict[str, str]:
    return {k: base64.b64decode(v).decode() for k, v in (doc.get("data") or {}).items()}


with tempfile.TemporaryDirectory() as tmp:
    t = pathlib.Path(tmp)
    (t / "bin").mkdir()
    (t / "bin" / "kubectl").write_text(WRAPPER)
    for tool in ("helm", "aws"):
        (t / "bin" / tool).write_text(STUB)
    for f in (t / "bin").iterdir():
        f.chmod(0o755)
    base = {k: v for k, v in os.environ.items() if k not in ("CONTEXT", "CLUSTER_NAME", "DD_SITE")}
    base.update({"KUBECONFIG": "/dev/null", "REAL_KUBECTL": KUBECTL})

    print("== fleet.sh datadog_secret_manifest, as repair_datadog writes it ==")
    env = {**base, "OWN_API": OWN_API, "OWN_APP": OWN_APP}
    p = subprocess.run(["bash", "-c", 'source ./fleet.sh >/dev/null 2>&1; datadog_secret_manifest monitoring "$OWN_API" "$OWN_APP"'],
                       cwd=FLEET_DIR, env=env, capture_output=True, text=True, timeout=60)
    docs = secrets(p.stdout)
    check("it prints one Secret, datadog-secret in monitoring", len(docs) == 1
          and docs[0]["metadata"].get("name") == "datadog-secret" and docs[0]["metadata"].get("namespace") == "monitoring",
          (p.stdout + p.stderr)[-400:])
    check("its data decodes to exactly the two keys", bool(docs) and decoded(docs[0]) == {"api-key": OWN_API, "app-key": OWN_APP})
    check("and it carries no annotation", bool(docs) and not docs[0]["metadata"].get("annotations"))

    print("== deploy-full-idp.sh and the identity script it runs ==")
    out = t / "out"
    out.mkdir()
    env = {**base, "PATH": f"{t / 'bin'}:{os.environ['PATH']}", "HOME": str(t), "OUT": str(out), "CONTEXT": CTX,
           "AWS_PROFILE": "fake", "WITB_DD_API_KEY": OWN_API, "WITB_DD_APP_KEY": OWN_APP, "WITB_DD_ADMIN_API_KEY": ADMIN_API}
    p = subprocess.run(["bash", str(DEPLOY), "attendee"], env=env, capture_output=True, text=True, timeout=300)
    check("deploy-full-idp.sh completes", p.returncode == 0, (p.stdout + p.stderr)[-400:])
    replaced = secrets((out / "replace").read_text() if (out / "replace").exists() else "")
    own = [d for d in replaced if d["metadata"]["name"] == "datadog-secret"]
    adm = [d for d in replaced if d["metadata"]["name"] == "datadog-admin-secret"]
    check("datadog-secret is replaced in datadog, monitoring and security",
          sorted(d["metadata"].get("namespace", "") for d in own) == ["datadog", "monitoring", "security"])
    check("each decodes to exactly the cluster's two keys",
          bool(own) and all(decoded(d) == {"api-key": OWN_API, "app-key": OWN_APP} for d in own))
    check("datadog-admin-secret is replaced in datadog, monitoring and agent",
          sorted(d["metadata"].get("namespace", "") for d in adm) == ["agent", "datadog", "monitoring"])
    site = "datadoghq.com"
    want = {"api-key": ADMIN_API,
            "additional-endpoints": {f"https://app.{site}": [ADMIN_API]},
            "process-additional-endpoints": {f"https://process.{site}": [ADMIN_API]},
            "orchestrator-additional-endpoints": {f"https://orchestrator.{site}": [ADMIN_API]},
            "logs-additional-endpoints": [{"api_key": ADMIN_API, "Host": f"agent-http-intake.logs.{site}", "Port": 443,
                                           "is_reliable": True}]}

    def admin_ok(d: dict) -> bool:
        got = decoded(d)
        try:
            return set(got) == set(want) and got["api-key"] == ADMIN_API and all(
                json.loads(got[k]) == v for k, v in want.items() if k != "api-key")
        except ValueError:
            return False
    check("each decodes to the admin key and the four endpoint blobs, each the exact JSON the Agent reads",
          bool(adm) and all(admin_ok(d) for d in adm), json.dumps(decoded(adm[0]) if adm else {}))
    check("no Secret written carries an annotation", bool(replaced) and not any(d["metadata"].get("annotations") for d in replaced))
    applied = (out / "apply").read_text() if (out / "apply").exists() else ""
    check("no Secret is applied", bool(applied) and not secrets(applied))

if failures:
    print(f"\n{len(failures)} check(s) failed", file=sys.stderr)
    sys.exit(1)
print("\nthe Datadog Secrets render with the real kubectl: every value exact, no annotation")
