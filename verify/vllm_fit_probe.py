# ABOUTME: Live probe for #704: does the local-inference vLLM fit on a running cluster's node, and when it does, how
# ABOUTME: long its cold start takes. Runs the manifest's own pod spec in a scratch namespace and deletes it after.
"""Needs kubectl and CONTEXT. Not a test_*.py: it schedules a 4-CPU pod, so it is run by hand, never by a suite.

Why it exists. #704 asks for the local-inference profile's cold build to be timed until every Application is
Healthy, and for vLLM's cost to go into platform-baseline.yaml. That build needs a fresh t3.2xlarge cluster. A run
whose AWS session cannot call IAM cannot build one (the cluster module creates IAM roles and a user), and the
question underneath the timing, in values-local-inference.yaml's header, is whether vLLM fits beside the platform
on one t3.2xlarge at all. This answers that question on a cluster that is already up, without changing its profile:

1. It reads the node's allocatable CPU and memory and the requests of every pod running on it, and prints what is
   free against the Deployment's requests.
2. It creates the Deployment from gitops/manifests/vllm-qwen3/vllm-qwen3.yaml, unchanged but for its namespace,
   in a namespace of its own (`vllm-fit-probe`), and waits for the scheduler's verdict. A pod the scheduler cannot
   place is reported with the scheduler's own message.
3. When CPU_REQUEST is set, the pod's CPU request is that instead (limits unchanged), so vLLM's own cold start can
   be measured on a node where the manifest's request does not fit. The output says so on every line it affects.
4. When the pod is placed it waits for Ready (the manifest's startup probe allows 30 minutes), then prints the
   time from creation to scheduled, the image pull as the kubelet reports it, the time to Ready, the container's
   cgroup memory.peak, and one 5-token chat completion straight to the pod's :8000 over a port-forward.

The namespace is deleted at the end whatever happened, and the probe refuses to start when it already exists, so
it never reuses or removes something it did not create. The image stays in the node's containerd cache: say so
when a later measurement on the same node reads its pull as warm.

Usage: CONTEXT=<kube-context> [CPU_REQUEST=3500m] [READY_TIMEOUT=1800] python3 verify/vllm_fit_probe.py
"""
from __future__ import annotations

import copy
import datetime
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

import yaml

REPO = pathlib.Path(__file__).resolve().parent.parent
MANIFEST = REPO / "gitops/manifests/vllm-qwen3/vllm-qwen3.yaml"
PROBE_NS = "vllm-fit-probe"
PROBE_LABEL = "watch-it-burn/probe"
# The kubelet's event for a pull: 'Successfully pulled image "x" in 1m2.345s (1m2.345s including waiting). ...'
PULLED = re.compile(r'Successfully pulled image "[^"]+" in ([0-9hms.]+)')


def manifest_deployment(text: str) -> dict:
    """The one Deployment in the vllm-qwen3 manifest."""
    docs = [d for d in yaml.safe_load_all(text) if d]
    deps = [d for d in docs if d.get("kind") == "Deployment"]
    if len(deps) != 1:
        raise ValueError(f"{MANIFEST.name}: expected one Deployment, found {len(deps)}")
    return deps[0]


def probe_deployment(dep: dict, namespace: str, cpu_request: str | None) -> dict:
    """The manifest's Deployment moved to the probe namespace, its CPU request replaced only when asked."""
    out = copy.deepcopy(dep)
    out["metadata"]["namespace"] = namespace
    out["metadata"].setdefault("labels", {})[PROBE_LABEL] = "vllm-fit"
    if cpu_request:
        out["spec"]["template"]["spec"]["containers"][0]["resources"]["requests"]["cpu"] = cpu_request
    return out


def cpu_milli(v: str | None) -> int:
    if not v:
        return 0
    return int(v[:-1]) if v.endswith("m") else int(round(float(v) * 1000))


def mem_mi(v: str | None) -> int:
    if not v:
        return 0
    for suffix, factor in (("Ki", 1 / 1024), ("Mi", 1), ("Gi", 1024), ("Ti", 1024 * 1024),
                           ("k", 1000 / 1048576), ("M", 1e6 / 1048576), ("G", 1e9 / 1048576)):
        if v.endswith(suffix):
            return int(float(v[: -len(suffix)]) * factor)
    return int(float(v) / 1048576)


def pod_requests(pod: dict) -> tuple[int, int]:
    """A pod's effective requests as the scheduler counts them: the sum of its containers, or its largest init
    container when that is bigger, in millicores and MiB."""
    spec = pod.get("spec") or {}

    def total(containers: list[dict]) -> tuple[int, int]:
        c = m = 0
        for ct in containers:
            r = (ct.get("resources") or {}).get("requests") or {}
            c += cpu_milli(r.get("cpu"))
            m += mem_mi(r.get("memory"))
        return c, m

    c, m = total(spec.get("containers") or [])
    for ic in spec.get("initContainers") or []:
        ic_c, ic_m = total([ic])
        c, m = max(c, ic_c), max(m, ic_m)
    return c, m


def free_on_node(node: dict, pods: list[dict]) -> tuple[int, int, int, int]:
    """(allocatable CPU m, requested CPU m, allocatable MiB, requested MiB) for one node, counting the pods bound
    to it that have not finished."""
    name = node["metadata"]["name"]
    alloc = node["status"]["allocatable"]
    req_c = req_m = 0
    for p in pods:
        if (p.get("spec") or {}).get("nodeName") != name:
            continue
        if (p.get("status") or {}).get("phase") in ("Succeeded", "Failed"):
            continue
        c, m = pod_requests(p)
        req_c += c
        req_m += m
    return cpu_milli(alloc.get("cpu")), req_c, mem_mi(alloc.get("memory")), req_m


def go_seconds(d: str) -> float:
    """A Go duration as the kubelet prints it (1h2m3.5s, 45.2s, 812ms) in seconds."""
    if d.endswith("ms") and re.fullmatch(r"[0-9.]+ms", d):
        return float(d[:-2]) / 1000
    total = 0.0
    for num, unit in re.findall(r"([0-9.]+)([hms])", d):
        total += float(num) * {"h": 3600, "m": 60, "s": 1}[unit]
    return total


def pull_seconds(messages: list[str]) -> float | None:
    for msg in messages:
        m = PULLED.search(msg)
        if m:
            return go_seconds(m.group(1))
    return None


def when(stamp: str) -> datetime.datetime:
    return datetime.datetime.fromisoformat(stamp.replace("Z", "+00:00"))


# ------------------------------------------------------------------------------------------------- live part

CONTEXT = os.environ.get("CONTEXT", "")
KUBECTL = shutil.which("kubectl")


def kubectl(*args: str, timeout: int = 60, stdin: str | None = None) -> subprocess.CompletedProcess:
    # --context on every call: the current-context belongs to whoever else is on this box (CLAUDE.md).
    return subprocess.run([KUBECTL, "--context", CONTEXT, *args], capture_output=True, text=True,
                          timeout=timeout, input=stdin)


def kjson(*args: str) -> dict:
    r = kubectl(*args, "-o", "json")
    if r.returncode != 0:
        raise RuntimeError(f"kubectl {' '.join(args)}: {r.stderr.strip()}")
    return json.loads(r.stdout)


def chat_direct(pod: str, timeout: int = 180) -> tuple[str, str]:
    """One 5-token completion to the pod's :8000 over a port-forward. Returns (status, body or error)."""
    pf = subprocess.Popen([KUBECTL, "--context", CONTEXT, "-n", PROBE_NS, "port-forward", "--address", "127.0.0.1",
                           f"pod/{pod}", ":8000"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        found: list[str] = []

        def read() -> None:
            for line in pf.stdout:
                m = re.search(r"Forwarding from 127\.0\.0\.1:(\d+) -> 8000", line)
                if m:
                    found.append(m.group(1))
                    return

        t = threading.Thread(target=read, daemon=True)
        t.start()
        t.join(timeout=30)
        if not found:
            return "", "the port-forward to :8000 did not come up"
        body = json.dumps({"model": "qwen3-1.7b", "max_tokens": 5,
                           "messages": [{"role": "user", "content": "Reply with the single word OK."}]}).encode()
        req = urllib.request.Request(f"http://127.0.0.1:{found[0]}/v1/chat/completions", data=body,
                                     headers={"content-type": "application/json"})
        start = time.monotonic()
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return str(r.status), f"{time.monotonic() - start:.1f}s: {r.read().decode()}"
        except urllib.error.HTTPError as e:
            return str(e.code), e.read().decode()
        except OSError as e:
            return "", f"the request failed: {e}"
    finally:
        if pf.poll() is None:
            pf.terminate()
        try:
            pf.wait(timeout=15)
        except subprocess.TimeoutExpired:
            pf.kill()


def main() -> int:
    if not KUBECTL or not CONTEXT:
        print("FAIL: needs kubectl on PATH and CONTEXT naming the cluster")
        return 1
    cpu_override = os.environ.get("CPU_REQUEST") or None
    ready_timeout = int(os.environ.get("READY_TIMEOUT", "1800"))
    dep = manifest_deployment(MANIFEST.read_text())
    want = dep["spec"]["template"]["spec"]["containers"][0]["resources"]
    image = dep["spec"]["template"]["spec"]["containers"][0]["image"]
    probe = probe_deployment(dep, PROBE_NS, cpu_override)
    asked_cpu = probe["spec"]["template"]["spec"]["containers"][0]["resources"]["requests"]["cpu"]

    print(f"== {CONTEXT}: free capacity against vLLM's requests ==")
    nodes = kjson("get", "nodes")["items"]
    pods = kjson("get", "pods", "-A")["items"]
    digest = image.split("@", 1)[1] if "@" in image else image
    for n in nodes:
        a_c, r_c, a_m, r_m = free_on_node(n, pods)
        cached = any(digest in name for img in n["status"].get("images") or [] for name in img.get("names") or [])
        print(f"  node {n['metadata']['name']} ({n['metadata'].get('labels', {}).get('node.kubernetes.io/instance-type')}):"
              f" CPU {r_c}m of {a_c}m requested, {a_c - r_c}m free; memory {r_m}Mi of {a_m}Mi requested,"
              f" {a_m - r_m}Mi free; vLLM image already on the node: {'yes' if cached else 'no'}")
        print(f"    the manifest's requests ({want['requests']['cpu']} CPU, {want['requests']['memory']}):"
              f" CPU {'fits' if cpu_milli(want['requests']['cpu']) <= a_c - r_c else 'does NOT fit'},"
              f" memory {'fits' if mem_mi(want['requests']['memory']) <= a_m - r_m else 'does NOT fit'}")
    if cpu_override:
        print(f"  CPU_REQUEST={cpu_override}: this probe asks for {cpu_override} CPU instead of the manifest's"
              f" {want['requests']['cpu']}; memory and limits are the manifest's")

    if kubectl("get", "namespace", PROBE_NS).returncode == 0:
        print(f"FAIL: namespace {PROBE_NS} already exists; the probe only deletes what it created")
        return 1
    rc = 1
    try:
        r = kubectl("create", "namespace", PROBE_NS)
        if r.returncode != 0:
            print(f"FAIL: could not create {PROBE_NS}: {r.stderr.strip()}")
            return 1
        r = kubectl("apply", "-f", "-", stdin=json.dumps(probe))
        if r.returncode != 0:
            print(f"FAIL: the Deployment was refused: {r.stderr.strip()}")
            return 1
        print(f"== the scheduler's verdict on {asked_cpu} CPU / {want['requests']['memory']} ==")
        sel = "app.kubernetes.io/name=vllm-qwen3"
        pod = None
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            items = kjson("-n", PROBE_NS, "get", "pods", "-l", sel)["items"]
            if items:
                pod = items[0]
                cond = {c["type"]: c for c in pod["status"].get("conditions") or []}
                sched = cond.get("PodScheduled")
                if sched and sched.get("status") == "True":
                    break
                if sched and sched.get("reason") == "Unschedulable":
                    print(f"  UNSCHEDULABLE: {sched.get('message')}")
                    return 1
            time.sleep(5)
        else:
            print("  FAIL: no scheduler verdict within 120 s")
            return 1
        name = pod["metadata"]["name"]
        created = when(pod["metadata"]["creationTimestamp"])
        print(f"  scheduled: {name} on {pod['spec'].get('nodeName')}")

        print(f"== waiting up to {ready_timeout} s for Ready ==")
        deadline = time.monotonic() + ready_timeout
        ready_at = None
        while time.monotonic() < deadline:
            pod = kjson("-n", PROBE_NS, "get", "pod", name)
            cond = {c["type"]: c for c in pod["status"].get("conditions") or []}
            restarts = sum(c.get("restartCount", 0) for c in pod["status"].get("containerStatuses") or [])
            if restarts:
                print(f"  FAIL: the container restarted ({restarts}); last state:"
                      f" {pod['status']['containerStatuses'][0].get('lastState')}")
                return 1
            if cond.get("Ready", {}).get("status") == "True":
                ready_at = when(cond["Ready"]["lastTransitionTime"])
                break
            time.sleep(15)
        if ready_at is None:
            print(f"  FAIL: not Ready within {ready_timeout} s")
            return 1
        cond = {c["type"]: c for c in pod["status"].get("conditions") or []}
        sched_at = when(cond["PodScheduled"]["lastTransitionTime"])
        started = (pod["status"]["containerStatuses"][0].get("state") or {}).get("running", {}).get("startedAt")
        events = kjson("-n", PROBE_NS, "get", "events", "--field-selector", f"involvedObject.name={name}")["items"]
        pulled = pull_seconds([e.get("message", "") for e in events])
        print(f"  created {created.isoformat()}, scheduled {sched_at.isoformat()}, container started {started},"
              f" Ready {ready_at.isoformat()}")
        print(f"  creation to scheduled: {int((sched_at - created).total_seconds())} s")
        print(f"  image pull (kubelet): {pulled if pulled is not None else 'no pull event (image was cached)'} s")
        if started:
            print(f"  container start to Ready (model load): {int((ready_at - when(started)).total_seconds())} s")
        print(f"  creation to Ready: {int((ready_at - created).total_seconds())} s"
              + (f" (CPU request {asked_cpu}, not the manifest's {want['requests']['cpu']})" if cpu_override else ""))
        peak = kubectl("-n", PROBE_NS, "exec", name, "-c", "vllm", "--", "cat", "/sys/fs/cgroup/memory.peak")
        cur = kubectl("-n", PROBE_NS, "exec", name, "-c", "vllm", "--", "cat", "/sys/fs/cgroup/memory.current")
        for label, res in (("memory.peak", peak), ("memory.current", cur)):
            val = res.stdout.strip()
            print(f"  cgroup {label}: " + (f"{int(val) / 2**30:.2f} GiB" if val.isdigit() else res.stderr.strip()))
        cpu = kubectl("-n", PROBE_NS, "exec", name, "-c", "vllm", "--", "cat", "/sys/fs/cgroup/cpu.stat")
        usage = re.search(r"usage_usec (\d+)", cpu.stdout)
        if usage and started:
            secs = (datetime.datetime.now(datetime.timezone.utc) - when(started)).total_seconds()
            print(f"  CPU used since start: {int(usage.group(1)) / 1e6:.0f} CPU-seconds over {secs:.0f} s"
                  f" (mean {int(usage.group(1)) / 1e6 / secs:.2f} cores)")
        code, reply = chat_direct(name)
        print(f"== one chat completion to the pod's :8000 ==\n  HTTP {code or 'none'}: {reply[:600]}")
        try:
            body = json.loads(reply.split(": ", 1)[1]) if code == "200" else {}
        except (IndexError, json.JSONDecodeError):
            body = {}
        if code == "200" and body.get("choices") and body.get("model") == "qwen3-1.7b":
            print("PASS: vLLM came up from a cold start and answered as qwen3-1.7b")
            rc = 0
        else:
            print("FAIL: the completion did not come back from qwen3-1.7b")
        return rc
    finally:
        print(f"== cleanup: deleting namespace {PROBE_NS} ==")
        d = kubectl("delete", "namespace", PROBE_NS, "--wait=true", timeout=600)
        print(f"  {(d.stdout or d.stderr).strip()}")
        print(f"  namespace gone: {kubectl('get', 'namespace', PROBE_NS).returncode != 0}")


if __name__ == "__main__":
    sys.exit(main())
