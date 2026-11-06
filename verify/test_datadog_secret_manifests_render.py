# ABOUTME: Renders fleet.sh's datadog_secret_manifest with the real kubectl: each value read from the env file on a file
# ABOUTME: descriptor decodes to exactly what was passed, a JSON blob included, and the manifest carries no annotation (#977).
# SUITE: e2e (needs kubectl: reading --from-env-file is kubectl's)
# E2E TIER: tools (no cluster, no AWS: run-e2e-tools.sh runs it with the pinned tools, #572)
"""#977 moved the Datadog keys from --from-literal arguments to an env file on a file descriptor, and the writes from
apply to replace. test_fleet_converge_repairs.sh and test_datadog_secrets_off_argv.py hold the calls against fakes, the
second including the exact env-file lines deploy-full-idp.sh and datadog-cluster-identity.sh write. Whether kubectl
reads each line back as the exact value is kubectl's behaviour, so this renders fleet.sh's own helper with the pinned
kubectl and KUBECONFIG=/dev/null, which reaches no cluster. The identity script puts the dual-shipping JSON blobs on
such lines, so the second case passes one as a value: its quotes, colons, brackets and an "=" must all survive.
"""
from __future__ import annotations

import base64
import json
import os
import pathlib
import shutil
import subprocess
import sys

import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
FLEET_DIR = REPO / "infra/terraform/fleet"
API, APP = "SENTINEL-API-5d1", "SENTINEL-APP-9b2"
# The identity script's logs blob, as jq -c prints it, with an "=" in a value besides.
BLOB = json.dumps([{"api_key": API, "Host": "agent-http-intake.logs.datadoghq.com", "Port": 443, "is_reliable": True,
                    "note": "a=b"}], separators=(",", ":"))
failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"\n        {detail}" if detail and not ok else ""))
    if not ok:
        failures.append(name)


if not shutil.which("kubectl"):
    print("FAIL: kubectl is not on PATH (run through verify/run-e2e-tools.sh, which puts the pinned one first)",
          file=sys.stderr)
    sys.exit(1)


def render(ns: str, api: str, app: str) -> tuple[list[dict], str]:
    env = {**os.environ, "KUBECONFIG": "/dev/null", "WANT_NS": ns, "WANT_API": api, "WANT_APP": app}
    script = ('source ./fleet.sh >/dev/null 2>&1\n'
              'declare -F datadog_secret_manifest >/dev/null || { echo "fleet.sh defines no datadog_secret_manifest" >&2; exit 3; }\n'
              'datadog_secret_manifest "$WANT_NS" "$WANT_API" "$WANT_APP"\n')
    p = subprocess.run(["bash", "-c", script],
                       cwd=FLEET_DIR, env=env, capture_output=True, text=True, timeout=120)
    docs = [d for d in yaml.safe_load_all(p.stdout) if d] if p.returncode == 0 else []
    return docs, (p.stdout + p.stderr)[-400:]


def decoded(doc: dict) -> dict[str, str]:
    return {k: base64.b64decode(v).decode() for k, v in (doc.get("data") or {}).items()}


print("== the cluster's two keys, as repair_datadog writes them ==")
docs, out = render("monitoring", API, APP)
check("it prints one Secret, datadog-secret in monitoring", len(docs) == 1 and docs[0].get("kind") == "Secret"
      and docs[0]["metadata"].get("name") == "datadog-secret" and docs[0]["metadata"].get("namespace") == "monitoring", out)
check("its data decodes to exactly the two keys", bool(docs) and decoded(docs[0]) == {"api-key": API, "app-key": APP})
check("and it carries no annotation", bool(docs) and not docs[0]["metadata"].get("annotations"))

print("== a JSON blob on an env-file line, as the identity script writes the dual-shipping endpoints ==")
docs, out = render("datadog", API, BLOB)
got = decoded(docs[0]) if docs else {}
check("the blob decodes byte for byte, quotes, colons and the \"=\" kept", got.get("app-key") == BLOB, json.dumps(got) or out)
check("and parses as the JSON that went in", bool(got) and json.loads(got.get("app-key", "null")) == json.loads(BLOB))

if failures:
    print(f"\n{len(failures)} check(s) failed", file=sys.stderr)
    sys.exit(1)
print("\ndatadog_secret_manifest renders with the real kubectl: every value exact, no annotation")
