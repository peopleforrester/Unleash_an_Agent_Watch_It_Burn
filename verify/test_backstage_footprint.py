# ABOUTME: Offline check of verify/backstage-footprint.sh (#484): its arithmetic on fixed kubelet, pod, node and
# ABOUTME: Kubernetes-tab responses, and that it refuses to run without an explicit CONTEXT.
import math
import os
import pathlib
import re
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import backstage_footprint as bf  # noqa: E402

SCRIPT = HERE / "backstage-footprint.sh"
MI = 2**20
failures = []


def check(n, c):
    print(f"  {'PASS' if c else 'FAIL'}  {n}")
    if not c:
        failures.append(n)


def raises(fn, *a):
    try:
        fn(*a)
    except ValueError:
        return True
    return False


def container(name, req_cpu, req_mem, lim_cpu=None, lim_mem=None, **extra):
    res = {"requests": {"cpu": req_cpu, "memory": req_mem}}
    if lim_cpu:
        res["limits"] = {"cpu": lim_cpu, "memory": lim_mem}
    return {"name": name, "resources": res, **extra}


def pod(name, ns, node, containers, init=None, phase="Running", ready=True, restarts=0):
    return {
        "metadata": {"name": name, "namespace": ns},
        "spec": {"nodeName": node, "containers": containers, "initContainers": init or []},
        "status": {"phase": phase,
                   "conditions": [{"type": "Ready", "status": "True" if ready else "False"}],
                   "containerStatuses": [{"name": c["name"], "restartCount": restarts,
                                          "imageID": f"ghcr.io/x@sha256:{c['name']}"} for c in containers]},
    }


print("== quantities ==")
check("250m is 0.25 cores", bf.quantity("250m") == 0.25)
check("1 is one core", bf.quantity("1") == 1.0)
check("512Mi is 512 MiB", bf.quantity("512Mi") == 512 * MI)
check("1Gi is 1024 MiB", bf.quantity("1Gi") == 1024 * MI)
check("a plain byte count", bf.quantity("128974848") == 128974848)
check("decimal suffix: 500M", bf.quantity("500M") == 500e6)
check("an exponent: 1e3", bf.quantity("1e3") == 1000)
check("absent is zero", bf.quantity(None) == 0.0)
check("garbage raises", raises(bf.quantity, "12 apples"))

print("== what the scheduler counts for a pod ==")
backstage = pod("backstage-7d9", "backstage", "n1", [container("backstage", "250m", "512Mi", "1", "1Gi")])
postgres = pod("postgres-0", "backstage", "n1", [container("postgres", "50m", "128Mi", "500m", "512Mi")])
check("Backstage requests 250m / 512Mi", bf.pod_requests(backstage) == (0.25, 512 * MI))
big_init = pod("p", "x", "n1", [container("app", "100m", "64Mi")], init=[container("migrate", "500m", "32Mi")])
check("a larger init container wins on CPU, the app on memory", bf.pod_requests(big_init) == (0.5, 64 * MI))
sidecar = pod("p", "x", "n1", [container("app", "100m", "64Mi")],
              init=[container("mesh", "50m", "16Mi", restartPolicy="Always")])
cpu, mem = bf.pod_requests(sidecar)
check("a sidecar init container adds to the app", math.isclose(cpu, 0.15) and mem == 80 * MI)
with_overhead = pod("p", "x", "n1", [container("app", "100m", "64Mi")])
with_overhead["spec"]["overhead"] = {"cpu": "10m", "memory": "8Mi"}
cpu, mem = bf.pod_requests(with_overhead)
check("pod overhead is added", math.isclose(cpu, 0.11) and mem == 72 * MI)

print("== node allocatable versus requests ==")
nodes = {"items": [{"metadata": {"name": "n1", "labels": {"node.kubernetes.io/instance-type": "t3.2xlarge"}},
                    "status": {"allocatable": {"cpu": "7910m", "memory": "31482092Ki"}}}]}
done = pod("job-1", "x", "n1", [container("j", "4", "8Gi")], phase="Succeeded")
pods = {"items": [backstage, postgres, done]}
table = bf.node_table(nodes, pods)
row = table[1]
check("the node row names the instance type", "t3.2xlarge" in row)
check("two live pods counted, the Succeeded job left out", re.search(r"t3\.2xlarge\s+2\s", row) is not None)
check("300m of 7910m CPU requested", "300/7910" in row)
check("640 Mi of 30744 Mi memory requested", "640/30744" in row)

print("== backstage pod status ==")
lines, ok = bf.pod_status(pods)
check("both backstage pods listed with the running digest", len(lines) == 2 and all("sha256:" in x for x in lines))
check("all Ready passes", ok)
_, ok = bf.pod_status({"items": [pod("backstage-1", "backstage", "n1", [container("b", "1", "1")], ready=False)]})
check("a pod not Ready fails", not ok)
lines, ok = bf.pod_status({"items": [done]})
check("no backstage pods fails and says so", not ok and "no pods" in lines[0])

print("== usage against requests ==")


def summary(ws_mi, rss_mi, cpu_m):
    return {"pods": [
        {"podRef": {"name": "backstage-7d9", "namespace": "backstage"},
         "containers": [{"name": "backstage", "cpu": {"usageNanoCores": cpu_m * 1e6},
                         "memory": {"workingSetBytes": ws_mi * MI, "rssBytes": rss_mi * MI}}]},
        {"podRef": {"name": "postgres-0", "namespace": "backstage"},
         "containers": [{"name": "postgres", "cpu": {"usageNanoCores": 3e6},
                         "memory": {"workingSetBytes": 40 * MI, "rssBytes": 20 * MI}}]},
        {"podRef": {"name": "other", "namespace": "apps"}, "containers": [{"name": "backstage"}]},
    ]}


lines, ok = bf.usage_table(pods, [summary(330, 313, 20), summary(560, 533, 400), summary(340, 320, 15)])
bs = next(x for x in lines if x.startswith("backstage-7d9/backstage"))
check("every container has a reading", ok)
check("Backstage working set: last 340, peak 560", "340/560" in bs)
check("Backstage RSS peak 533", re.search(r"\s533\s", bs) is not None)
check("Backstage CPU: last 15m, peak 400m", "15/400" in bs)
check("Backstage request and limit shown beside it", re.search(r"\s250\s+1000\s", bs) and re.search(r"\s512\s+1024\s", bs))
check("three samples counted", bs.rstrip().endswith(" 3"))
_, ok = bf.usage_table(pods, [{"pods": []}])
check("a container with no reading fails rather than reading as zero", not ok)

print("== guest sign-in and the Kubernetes tab ==")
check("the guest token is read", bf.guest_token({"backstageIdentity": {"token": "abc"}}) == "abc")
check("a refresh without a token raises", raises(bf.guest_token, {"profile": {}}))
resp = {"items": [{"cluster": {"name": "wib-01"}, "errors": [],
                   "resources": [{"type": "services", "resources": [{"metadata": {"name": "svc"}}]},
                                 {"type": "pods", "resources": [
                                     {"metadata": {"name": "demo-app-unicorn-abc", "namespace": "apps"},
                                      "status": {"phase": "Running"}}]}]}]}
tab, errs = bf.tab_pods(resp)
check("the tab's pod is listed, services are not", tab == ["wib-01: apps/demo-app-unicorn-abc Running"] and not errs)
denied = {"items": [{"cluster": {"name": "wib-01"}, "resources": [],
                     "errors": [{"errorType": "UNAUTHORIZED_ERROR", "resourcePath": "/api/v1/pods"}]}]}
tab, errs = bf.tab_pods(denied)
check("an RBAC error is reported", not tab and "UNAUTHORIZED_ERROR" in errs[0])

print("== the script ==")
env = {k: v for k, v in os.environ.items() if k != "CONTEXT"}
r = subprocess.run(["bash", str(SCRIPT)], capture_output=True, text=True, env=env)
check("no CONTEXT: exits non-zero and says CONTEXT is required",
      r.returncode != 0 and "CONTEXT is required" in r.stderr)
txt = SCRIPT.read_text()
calls = [line for line in txt.splitlines()
         if re.search(r"(^|[\s;&|(])kubectl\s", line) and not line.lstrip().startswith("#")]
check("every kubectl call carries --context \"${CONTEXT}\"",
      calls and all('kubectl --context "${CONTEXT}"' in line or "command -v" in line or "for tool in" in line
                    for line in calls))
check("never touches the current-context", "use-context" not in txt and "set-context" not in txt)

if failures:
    print(f"\nFAILED: {len(failures)}")
    sys.exit(1)
print("\nAll backstage-footprint checks passed.")
