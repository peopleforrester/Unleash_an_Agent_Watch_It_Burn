# ABOUTME: Fails when the guard-proxy pod template's checksum/proxy-py annotation does not match
# ABOUTME: sha256(proxy.py). Without it a proxy.py change syncs green and never restarts the process.
import hashlib
import pathlib
import sys

import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
SRC = REPO / "gitops" / "ai-layer" / "proxy.py"
RES = REPO / "gitops" / "ai-layer" / "resources.yaml"

failures = []


def check(name, cond):
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        failures.append(name)


docs = [d for d in yaml.safe_load_all(RES.read_text()) if d]
deploys = [d for d in docs if d.get("kind") == "Deployment" and d["metadata"]["name"] == "guard-proxy"]
check("guard-proxy Deployment is present", len(deploys) == 1)

if deploys:
    ann = deploys[0]["spec"]["template"]["metadata"].get("annotations", {})
    want = hashlib.sha256(SRC.read_bytes()).hexdigest()[:12]
    got = ann.get("checksum/proxy-py")
    check("pod template carries a checksum/proxy-py annotation", got is not None)
    # The annotation is what makes the Deployment spec change, which is what makes Argo restart the
    # pod. proxy.py is read by Python once at startup, so without a restart a content change is a
    # silent no-op: synced, healthy, and running the old code.
    check(f"checksum/proxy-py matches sha256(proxy.py) (want {want}, got {got})", got == want)
    if got != want:
        print(f"\n  Bump it: set checksum/proxy-py to {want} in gitops/ai-layer/resources.yaml")

print(f"\n{'FAILED: ' + ', '.join(failures) if failures else 'Proxy checksum annotation is current.'}")
sys.exit(1 if failures else 0)
