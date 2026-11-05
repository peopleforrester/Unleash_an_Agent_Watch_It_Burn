# ABOUTME: Offline check of verify/vllm_fit_probe.py (#704): the probe runs the manifest's own vLLM pod spec, changes
# ABOUTME: only its namespace and, when asked, its CPU request, and counts free node capacity as the scheduler does.
"""Why this exists.

The probe's numbers go into platform-baseline.yaml's vllm entry and into decisions.md, so what it schedules has to
be the profile's vLLM and not a copy that has drifted from it. If the probe built its own pod spec, a change to the
manifest's limits, KV cache or /dev/shm would leave the probe measuring a different server. So the probe reads the
manifest, and this test holds it to changing nothing but the namespace, a label and, under CPU_REQUEST, the CPU
request. The capacity sums are checked on a node and pods built here, including the init-container rule and the
skipping of finished pods, because a wrong sum would print "fits" for a pod the scheduler then refuses.
"""
from __future__ import annotations

import copy
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import vllm_fit_probe as probe  # noqa: E402

failures: list[str] = []


def check(name: str, cond: bool) -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        failures.append(name)


print("== the probe schedules the manifest's own Deployment ==")
dep = probe.manifest_deployment(probe.MANIFEST.read_text(encoding="utf-8"))
check("the manifest has one Deployment, vllm-qwen3", dep["metadata"]["name"] == "vllm-qwen3")
same = probe.probe_deployment(dep, probe.PROBE_NS, None)
check("without CPU_REQUEST the pod template is the manifest's, unchanged", same["spec"] == dep["spec"])
check("it lands in the probe's own namespace", same["metadata"]["namespace"] == probe.PROBE_NS != "agent")
check("it carries the probe label", same["metadata"]["labels"].get(probe.PROBE_LABEL) == "vllm-fit")
check("the manifest's Deployment itself is not modified", dep["metadata"]["namespace"] == "agent"
      and probe.PROBE_LABEL not in dep["metadata"]["labels"])
low = probe.probe_deployment(dep, probe.PROBE_NS, "3500m")
want = copy.deepcopy(dep["spec"])
want["template"]["spec"]["containers"][0]["resources"]["requests"]["cpu"] = "3500m"
check("with CPU_REQUEST only the CPU request differs", low["spec"] == want)
check("limits and the memory request stay the manifest's",
      low["spec"]["template"]["spec"]["containers"][0]["resources"]["limits"]
      == dep["spec"]["template"]["spec"]["containers"][0]["resources"]["limits"])

print("== quantities ==")
for raw, milli in (("4", 4000), ("3500m", 3500), ("0.5", 500), ("7910m", 7910), (None, 0)):
    check(f"cpu {raw!r} is {milli}m", probe.cpu_milli(raw) == milli)
for raw, mib in (("10Gi", 10240), ("512Mi", 512), ("31466844Ki", 30729), ("1G", 953), (None, 0)):
    check(f"memory {raw!r} is {mib}Mi", probe.mem_mi(raw) == mib)
for raw, secs in (("1m2.5s", 62.5), ("45.25s", 45.25), ("812ms", 0.812), ("1h0m3s", 3603.0)):
    check(f"Go duration {raw} is {secs} s", abs(probe.go_seconds(raw) - secs) < 1e-9)
msg = ('Successfully pulled image "ghcr.io/peopleforrester/vllm-qwen3@sha256:ab" in 2m3.4s '
       '(2m3.4s including waiting). Image size: 4950000000 bytes.')
check("the kubelet's pull event gives the pull time", probe.pull_seconds(["Created container", msg]) == 123.4)
check("no pull event (a cached image) gives None", probe.pull_seconds(["Container image already present"]) is None)

print("== free capacity is counted the way the scheduler counts it ==")
node = {"metadata": {"name": "n1"}, "status": {"allocatable": {"cpu": "7910m", "memory": "31466844Ki"}}}


def pod(node_name: str, phase: str, containers: list[tuple[str, str]], inits: list[tuple[str, str]] = ()) -> dict:
    def ct(c: str, m: str) -> dict:
        return {"resources": {"requests": {"cpu": c, "memory": m}}}
    return {"spec": {"nodeName": node_name, "containers": [ct(*c) for c in containers],
                     "initContainers": [ct(*c) for c in inits]}, "status": {"phase": phase}}


pods = [
    pod("n1", "Running", [("250m", "1Gi"), ("100m", "128Mi")]),
    pod("n1", "Pending", [("100m", "64Mi")], inits=[("500m", "256Mi")]),   # the init container is the larger
    pod("n1", "Succeeded", [("2", "4Gi")]),                                  # finished: holds nothing
    pod("n2", "Running", [("4", "10Gi")]),                                   # another node
]
check("a pod's requests sum its containers", probe.pod_requests(pods[0]) == (350, 1152))
check("a larger init container sets the pod's requests", probe.pod_requests(pods[1]) == (500, 256))
check("only this node's unfinished pods count", probe.free_on_node(node, pods) == (7910, 850, 30729, 1408))

if failures:
    print(f"\nFAIL: {len(failures)} check(s) failed: {failures}")
    sys.exit(1)
print("\nPASS: the fit probe runs the manifest's vLLM and counts capacity as the scheduler does")
