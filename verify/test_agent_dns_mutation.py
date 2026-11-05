# ABOUTME: Runs the agent-dns-resolver MutatingPolicy (#861) through the Kyverno CLI on the platform's own pod templates:
# ABOUTME: every agent pod gets nameserver 172.20.0.53, agent-dns and egress-proxy keep ClusterFirst, other namespaces too.
# SUITE: e2e (needs the kyverno CLI v1.19.1 on PATH)
# E2E TIER: tools (no cluster, no AWS: run-e2e-tools.sh runs it with the pinned tools, #572)
#
# Why the CLI. The DNS lock narrows agent-allow-dns to the resolver, so a pod the mutation misses loses every lookup,
# and a pod it wrongly catches (the resolver itself) would loop. verify/test_egress_lock.py reads the policy's text;
# the CLI is the engine the admission controller runs, and says what the patch does to a real pod spec. The first
# draft of this policy was an ApplyConfiguration, which the CLI refused ("may not mutate atomic arrays"), which is
# why the policy is a JSON patch.
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
POLICY = REPO / "gitops/agent-dns/agent-dns-resolver.yaml"
RES = [d for d in yaml.safe_load_all((REPO / "gitops/ai-layer/resources.yaml").read_text()) if isinstance(d, dict)]
DNS = [d for d in yaml.safe_load_all((REPO / "gitops/agent-dns/resolver.yaml").read_text()) if d]
WANT_VERSION = "1.19.1"
WANT_DNS = {"nameservers": ["172.20.0.53"], "searches": ["agent.svc.cluster.local", "svc.cluster.local", "cluster.local"],
            "options": [{"name": "ndots", "value": "5"}]}
failures = []


def check(n, c, detail=""):
    print(f"  {'PASS' if c else 'FAIL'}  {n}" + (f"  ({detail})" if detail and not c else ""))
    if not c:
        failures.append(n)


cli = os.environ.get("KYVERNO_CLI") or shutil.which("kyverno")
if not cli:
    print("FAIL: the kyverno CLI is not on PATH (set KYVERNO_CLI to its path). Install v1.19.1 from "
          "https://github.com/kyverno/kyverno/releases/tag/v1.19.1 (kyverno-cli_v1.19.1_<os>_<arch>.tar.gz).",
          file=sys.stderr)
    sys.exit(1)
ver = subprocess.run([cli, "version"], capture_output=True, text=True).stdout
if WANT_VERSION not in ver:
    print(f"FAIL: kyverno CLI is not v{WANT_VERSION} (the deployed engine); got: {ver.strip()!r}", file=sys.stderr)
    sys.exit(1)


def pod_from(dep: dict, ns: str) -> dict:
    t = dep["spec"]["template"]
    return {"apiVersion": "v1", "kind": "Pod",
            "metadata": {"name": dep["metadata"]["name"], "namespace": ns, "labels": t["metadata"].get("labels", {})},
            "spec": t["spec"]}


deployments = {d["metadata"]["name"]: d for d in RES + DNS if d.get("kind") == "Deployment"}
for want in ("workshop-mcp", "weather-feed", "guard-proxy", "egress-proxy", "agent-dns"):
    check(f"the {want} Deployment is in the manifests", want in deployments)
pods = [pod_from(deployments[n], "agent") for n in ("workshop-mcp", "weather-feed", "guard-proxy", "egress-proxy",
                                                    "agent-dns") if n in deployments]
# A pod the agent deploys through deploy_app, and a pod in another namespace with the same shape.
pods.append({"apiVersion": "v1", "kind": "Pod", "metadata": {"name": "agent-made", "namespace": "agent",
             "labels": {"burritobot.co/workload": "maintenance-shell"}},
             "spec": {"containers": [{"name": "c", "image": "registry.burritobot.co/x:1"}]}})
pods.append({"apiVersion": "v1", "kind": "Pod", "metadata": {"name": "elsewhere", "namespace": "apps"},
             "spec": {"containers": [{"name": "c", "image": "ghcr.io/x:1"}]}})
namespaces = [{"apiVersion": "v1", "kind": "Namespace",
               "metadata": {"name": n, "labels": {"kubernetes.io/metadata.name": n}}} for n in ("agent", "apps")]

with tempfile.TemporaryDirectory() as tmp:
    res = pathlib.Path(tmp) / "pods.yaml"
    res.write_text(yaml.safe_dump_all(pods + namespaces))
    out = pathlib.Path(tmp) / "out.yaml"
    run = subprocess.run([cli, "apply", str(POLICY), "--resource", str(res), "-o", str(out)],
                         capture_output=True, text=True)
    check("the CLI applies the policy without an error", run.returncode == 0 and "error: 0" in run.stdout,
          (run.stdout + run.stderr)[-600:])
    got = {}
    if out.exists():
        for d in yaml.safe_load_all(out.read_text()):
            if d and d.get("kind") == "Pod":
                got[(d["metadata"].get("namespace"), d["metadata"]["name"])] = d["spec"]
    # A skipped resource is not written to the output, so a pod missing from it kept its spec as submitted.
    def spec_of(ns, name):
        return got.get((ns, name)) or next(p["spec"] for p in pods if p["metadata"]["name"] == name)

    print("== agent pods resolve through agent-dns ==")
    for name in ("workshop-mcp", "weather-feed", "guard-proxy", "agent-made"):
        s = spec_of("agent", name)
        check(f"{name}: dnsPolicy None", s.get("dnsPolicy") == "None", repr(s.get("dnsPolicy")))
        check(f"{name}: nameserver 172.20.0.53 alone, the cluster search path, ndots 5", s.get("dnsConfig") == WANT_DNS,
              repr(s.get("dnsConfig")))

    print("== the resolver, the proxy and other namespaces keep the cluster DNS ==")
    for ns, name in (("agent", "agent-dns"), ("agent", "egress-proxy"), ("apps", "elsewhere")):
        s = spec_of(ns, name)
        check(f"{ns}/{name}: no dnsConfig is set", "dnsConfig" not in s, repr(s.get("dnsConfig")))
        check(f"{ns}/{name}: its dnsPolicy is what it asked for", s.get("dnsPolicy") in (None, "ClusterFirst"),
              repr(s.get("dnsPolicy")))

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    sys.exit(1)
print("All agent-dns mutation checks passed.")
