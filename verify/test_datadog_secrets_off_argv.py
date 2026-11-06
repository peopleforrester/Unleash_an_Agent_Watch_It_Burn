# ABOUTME: infra/deploy-full-idp.sh and infra/datadog-cluster-identity.sh hand the Datadog keys to kubectl on a file
# ABOUTME: descriptor, never on a command line, and write the Secrets by replace or create, never by apply (#977).
"""#977, after #944 did the same for the terminal login. A key on a kubectl command line is in the process list, where
any user on the host reads it while kubectl runs, and a Secret written by a client-side apply keeps a second copy of
every value in its kubectl.kubernetes.io/last-applied-configuration annotation. fleet.sh's repair has its own checks in
test_fleet_converge_repairs.sh; this runs the two scripts the build runs.

kubectl, helm and aws are fakes on PATH that record every call, and jq is a wrapper that records its argv and runs the
real jq. kubectl's fake logs what a --from-env-file holds apart from the argv, answers a client-side create of a Secret
with a manifest carrying that content, and keeps what each of apply, replace and create read on stdin. Its replace
fails while FAKE_NO_SECRET is set, as it does on a cluster without the Secret. That the real kubectl reads an env-file
line back as the exact value, a JSON blob included, is checked in the tools tier by
test_datadog_secret_manifests_render.py; a tier test may not name a context, and both scripts require one.
"""
from __future__ import annotations

import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

REPO = pathlib.Path(__file__).resolve().parent.parent
DEPLOY = REPO / "infra/deploy-full-idp.sh"
IDENT = REPO / "infra/datadog-cluster-identity.sh"
CTX = "arn:aws:eks:us-west-2:111122223333:cluster/watch-it-burn-attendee-001"
OWN_API, OWN_APP, ADMIN_API = "OWN-API-SENTINEL-5d1", "OWN-APP-SENTINEL-9b2", "ADMIN-API-SENTINEL-c47"
SENTINELS = (OWN_API, OWN_APP, ADMIN_API)
failures: list[str] = []

FAKE = r"""#!/usr/bin/env python3
import json, os, sys
tool, args = os.path.basename(sys.argv[0]), sys.argv[1:]
t = os.environ["FAKE_DIR"]
def log(rec):
    with open(os.path.join(t, "calls"), "a") as f:
        f.write(json.dumps(rec) + "\n")
log([tool, *args])
if tool == "aws":
    if "describe-cluster" in args:
        print("vpc-0abc"); sys.exit(0)
    sys.exit(1)
if tool == "helm":
    sys.exit(0)
env = ""
for a in args:
    if a.startswith("--from-env-file="):
        env = open(a[len("--from-env-file="):]).read()
        log(["env-file", env])
if args[-2:] == ["-f", "-"]:
    verb = args[-3]
    with open(os.path.join(t, verb), "a") as f:
        f.write(sys.stdin.read() + "\n---\n")
    if verb == "replace" and os.environ.get("FAKE_NO_SECRET"):
        sys.exit(1)
    sys.exit(0)
if "--dry-run=client" in args:
    print("kind: Secret" if "secret" in args else "kind: Namespace")
    if env:
        print(env, end="")
sys.exit(0)
"""
JQ = """#!/usr/bin/env bash
printf '%s\\n' "$(python3 -c 'import json,sys; print(json.dumps(["jq", *sys.argv[1:]]))' "$@")" >>"${FAKE_DIR}/calls"
exec REAL_JQ "$@"
"""


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"\n        {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


real_jq = shutil.which("jq")
if not real_jq:
    print("FAIL: jq is not on PATH; both scripts need it", file=sys.stderr)
    sys.exit(1)

with tempfile.TemporaryDirectory() as tmp:
    tmp = pathlib.Path(tmp)
    fakebin = tmp / "bin"
    fakebin.mkdir()
    for tool in ("kubectl", "helm", "aws"):
        (fakebin / tool).write_text(FAKE)
        (fakebin / tool).chmod(0o755)
    (fakebin / "jq").write_text(JQ.replace("REAL_JQ", real_jq))
    (fakebin / "jq").chmod(0o755)
    runs = 0

    def run(cmd: list[str], **extra: str) -> tuple[int, str, pathlib.Path]:
        global runs
        runs += 1
        d = tmp / f"run-{runs}"
        d.mkdir()
        (d / "calls").write_text("")
        env = {k: v for k, v in os.environ.items() if k not in ("CONTEXT", "KUBECONFIG", "CLUSTER_NAME", "DD_SITE")}
        env.update({"PATH": f"{fakebin}:{os.environ['PATH']}", "HOME": str(tmp), "FAKE_DIR": str(d),
                    "CONTEXT": CTX, "AWS_PROFILE": "fake", "WITB_DD_API_KEY": OWN_API, "WITB_DD_APP_KEY": OWN_APP,
                    "WITB_DD_ADMIN_API_KEY": ADMIN_API, **extra})
        r = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=120)
        return r.returncode, r.stdout + r.stderr, d

    def calls(d: pathlib.Path) -> list[list[str]]:
        return [json.loads(line) for line in (d / "calls").read_text().splitlines()]

    def read(d: pathlib.Path, verb: str) -> str:
        f = d / verb
        return f.read_text() if f.exists() else ""

    def argv_clean(d: pathlib.Path) -> list[list[str]]:
        """Every recorded command line that carries a key."""
        return [c for c in calls(d) if c[0] != "env-file" and any(s in a for a in c for s in SENTINELS)]

    def writes(d: pathlib.Path, secret: str) -> list[list[str]]:
        return [c for c in calls(d) if c[0] == "kubectl" and "create" in c and "secret" in c and secret in c]

    print("== deploy-full-idp.sh: datadog-secret, and the identity script it runs ==")
    rc, out, d = run(["bash", str(DEPLOY), "attendee"])
    check("deploy-full-idp.sh completes", rc == 0, out[-400:])
    dd = writes(d, "datadog-secret")
    check("datadog-secret is built in datadog, monitoring and security from an env file",
          sorted(c[c.index("-n") + 1] for c in dd) == ["datadog", "monitoring", "security"]
          and all(any(a.startswith("--from-env-file=/dev/fd/") for a in c) for c in dd), json.dumps(dd))
    envs = [c[1] for c in calls(d) if c[0] == "env-file"]
    check("the env file holds both keys, a line each",
          envs.count(f"api-key={OWN_API}\napp-key={OWN_APP}\n") == 3, json.dumps(envs[:2]))
    adm = writes(d, "datadog-admin-secret")
    check("the identity script builds datadog-admin-secret in datadog, monitoring and agent from an env file",
          sorted(c[c.index("-n") + 1] for c in adm) == ["agent", "datadog", "monitoring"]
          and all(any(a.startswith("--from-env-file=/dev/fd/") for a in c) for c in adm), json.dumps(adm))
    check("no key is on any kubectl, helm, aws or jq command line", not argv_clean(d), json.dumps(argv_clean(d)[:2]))
    check("no --from-literal carries a key", not any(a.startswith("--from-literal=") and ("key=" in a or "endpoints=" in a)
                                                    for c in calls(d) for a in c))
    check("no key reaches an apply, so no last-applied annotation holds one",
          not any(s in read(d, "apply") for s in SENTINELS) and "kind: Secret" not in read(d, "apply"))
    rep = read(d, "replace")
    check("six Secrets are written by replace, both of the cluster's keys and the admin key among them",
          rep.count("kind: Secret") == 6 and rep.count(f"api-key={OWN_API}") == 3 and rep.count(f"app-key={OWN_APP}") == 3
          and rep.count(f"api-key={ADMIN_API}") == 3)
    check("and none is created over what replace wrote", read(d, "create") == "")
    check("every replace names the namespace and the context",
          all(c[1:3] == ["--context", CTX] and "-n" in c for c in calls(d) if c[0] == "kubectl" and "replace" in c))

    print("== a cluster without the Secrets: they are created ==")
    rc, out, d = run(["bash", str(DEPLOY), "attendee"], FAKE_NO_SECRET="1")
    made = read(d, "create")
    check("deploy-full-idp.sh completes", rc == 0, out[-400:])
    check("each of the six is created from a manifest holding its key, and none applied",
          made.count("kind: Secret") == 6 and made.count(f"api-key={OWN_API}") == 3 and made.count(f"api-key={ADMIN_API}") == 3
          and not any(s in read(d, "apply") for s in SENTINELS))

    print("== datadog-cluster-identity.sh alone: the dual-shipping blobs ==")
    rc, out, d = run(["bash", str(IDENT)])
    check("it completes", rc == 0, out[-400:])
    env = next((c[1] for c in calls(d) if c[0] == "env-file"), "")
    lines = dict(line.split("=", 1) for line in env.splitlines() if "=" in line)
    want = {"api-key", "additional-endpoints", "process-additional-endpoints", "orchestrator-additional-endpoints",
            "logs-additional-endpoints"}
    check("the env file holds the api key and the four endpoint blobs, one line each", set(lines) == want
          and len(env.splitlines()) == 5, env)
    blobs_ok = True
    try:
        blobs_ok = (json.loads(lines["additional-endpoints"]) == {"https://app.datadoghq.com": [ADMIN_API]}
                    and json.loads(lines["logs-additional-endpoints"])[0]["api_key"] == ADMIN_API
                    and lines["api-key"] == ADMIN_API)
    except (KeyError, ValueError, IndexError):
        blobs_ok = False
    check("each blob is the JSON the Agent reads, the admin key in it", blobs_ok, env)
    jq = [c for c in calls(d) if c[0] == "jq"]
    check("jq builds the blobs from its environment, the key on none of its command lines",
          len(jq) >= 4 and not any(ADMIN_API in a for c in jq for a in c), json.dumps(jq[:1]))
    check("no key is on any command line", not argv_clean(d), json.dumps(argv_clean(d)[:2]))

if failures:
    print(f"\n{len(failures)} check(s) failed", file=sys.stderr)
    sys.exit(1)
print("\nthe Datadog keys are off every command line and every apply")
