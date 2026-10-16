# ABOUTME: Every AI-layer Deployment that names its service in OTEL_RESOURCE_ATTRIBUTES also pins it in
# ABOUTME: OTEL_SERVICE_NAME, checked on the kustomize render. The source checks are in test_service_naming.py.
# SUITE: e2e (needs kubectl: the pin is checked on the `kubectl kustomize` render of gitops/ai-layer)
#
# Why. OTEL_SERVICE_NAME wins over service.name in OTEL_RESOURCE_ATTRIBUTES, and the OTel operator injects
# it from the Deployment name at admission. Without the pin the rename is applied, synced, running, and
# ignored.
import pathlib, subprocess, sys

import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
failures = []


def check(n, c):
    print(f"  {'PASS' if c else 'FAIL'}  {n}")
    if not c:
        failures.append(n)


print("== the service name is PINNED where the OTel operator would otherwise inject one ==")
rendered = subprocess.run(["kubectl", "kustomize", str(REPO / "gitops/ai-layer")], capture_output=True, text=True, check=True).stdout
pinned = 0
for doc in yaml.safe_load_all(rendered):
    if not doc or doc.get("kind") != "Deployment":
        continue
    env = {e["name"]: e.get("value") for e in doc["spec"]["template"]["spec"]["containers"][0].get("env", [])}
    ra = env.get("OTEL_RESOURCE_ATTRIBUTES", "")
    if "service.name=" not in ra:
        continue
    want = ra.split("service.name=", 1)[1].split(",")[0]
    pinned += 1
    check(f"{doc['metadata']['name']}: OTEL_SERVICE_NAME pins '{want}' (operator injection cannot win)",
          env.get("OTEL_SERVICE_NAME") == want)
# A render with no named Deployment would pass every check above by checking nothing.
check(f"the render has Deployments that name their service ({pinned})", pinned > 0)

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    sys.exit(1)
print("All service-naming render checks passed.")
