# ABOUTME: Offline tests for test_burritobot_cluster_live.py (#629): a fake cluster that ships with the burritobot key and
# ABOUTME: names every container's service and env passes, and each way of breaking that (a stray key, an untagged pod) fails.
"""Nothing here runs kubectl or reaches AWS. The cluster is a fake `get` answering the kubectl reads the live check
makes, built from the repo's own DatadogAgent manifest so its log configs are the ones a cluster runs. A live check
that passes whatever it is fed proves nothing on the day it finally runs, so each break below must turn it red.
"""
from __future__ import annotations

import base64
import copy
import importlib.util
import pathlib
import sys

import yaml

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parent
spec = importlib.util.spec_from_file_location("cluster_live", HERE / "test_burritobot_cluster_live.py")
live = importlib.util.module_from_spec(spec)
spec.loader.exec_module(live)

ENV = "burritobot-kubecon-na-26"
KEY = "0123456789abcdef0123456789ababcd"
AGENT = yaml.safe_load((REPO / "gitops/manifests/datadog/datadog-agent.yaml").read_text(encoding="utf-8"))
REF = {"valueFrom": {"secretKeyRef": {"name": "datadog-secret", "key": "api-key"}}}


def pod(ns: str, name: str, containers: list[dict], labels: dict | None = None, phase: str = "Running",
        annotations: dict | None = None) -> dict:
    return {"metadata": {"namespace": ns, "name": name, "labels": labels or {}, "annotations": annotations or {}},
            "spec": {"containers": containers}, "status": {"phase": phase}}


def labelled(service: str) -> dict:
    return {"tags.datadoghq.com/service": service, "tags.datadoghq.com/env": ENV}


GOOD = {
    "secrets": {ns: KEY for ns in live.SECRET_NAMESPACES},
    "admin": set(),
    "pods": [
        pod("argocd", "argocd-server-1", [{"name": "server", "image": "quay.io/argoproj/argocd:v3.5.2"}],
            labelled("burritobot-argocd")),
        pod("kube-system", "aws-load-balancer-controller-1",
            [{"name": "controller", "image": "public.ecr.aws/eks/aws-load-balancer-controller:v2.13.0"}],
            labelled("burritobot-aws-load-balancer-controller")),
        pod("kubearmor", "kubearmor-abc", [{"name": "kubearmor", "image": "ghcr.io/x/mirror/kubearmor/kubearmor:stable",
                                            "env": [{"name": "DD_SERVICE", "value": "burritobot-kubearmor"},
                                                    {"name": "DD_ENV", "value": ENV}]}]),
        pod("kube-system", "coredns-1", [{"name": "coredns",
                                          "image": "602401143452.dkr.ecr.us-west-2.amazonaws.com/eks/coredns:v1.11.4"}]),
        pod("agent", "guard-proxy-1", [{"name": "guard-proxy", "image": "ghcr.io/x/guard-proxy@sha256:abc"}],
            labelled("burritobot")),
        pod("datadog", "datadog-agent-x", [{"name": "agent", "image": "gcr.io/datadoghq/agent:7", "env": [
            {"name": "DD_API_KEY", **REF}, {"name": "DD_ENV", "value": ENV},
            {"name": "DD_ADDITIONAL_ENDPOINTS", "valueFrom": {"secretKeyRef": {
                "name": "datadog-admin-secret", "key": "additional-endpoints", "optional": True}}}]}],
            labelled("burritobot-datadog-agent")),
        pod("security", "falcosidekick-1", [{"name": "falcosidekick", "image": "falcosecurity/falcosidekick:2",
                                             "env": [{"name": "DATADOG_APIKEY", **REF}]}],
            labelled("burritobot-falcosidekick")),
        # Two containers, one named by its own label: tags.datadoghq.com/<container>.service.
        pod("agent", "two-1", [{"name": "main", "image": "x/main:1"}, {"name": "side", "image": "x/side:1"}],
            {**labelled("burritobot-two"), "tags.datadoghq.com/side.service": "burritobot-two-side"}),
        # Backstage: its JSON logs carry their own service field, so a log config on the pod names the service.
        pod("backstage", "backstage-1", [{"name": "backstage", "image": "ghcr.io/x/watch-it-burn:backstage-1"}],
            labelled("burritobot-backstage"),
            annotations={"ad.datadoghq.com/backstage.logs": '[{"source": "backstage", "service": "burritobot-backstage"}]'}),
        # A finished Job's pod sends nothing more, so it is not judged.
        pod("default", "done-1", [{"name": "c", "image": "busybox:1"}], phase="Succeeded"),
    ],
    "agent": AGENT,
    # Keyed (namespace, name): ConfigMaps and Secrets a container reads through envFrom (grafana-mcp's shape).
    "configmaps": {("kagent", "kagent-grafana-mcp"): {"DD_ENV": ENV, "DD_SERVICE": "burritobot-grafana-mcp",
                                                      "GRAFANA_URL": "grafana.kagent:3000/api"}},
    "secrets_refs": {("kagent", "kagent-grafana-mcp"): {}},
}
GRAFANA = {"name": "grafana-mcp", "image": "x/grafana-mcp:1",
           "envFrom": [{"configMapRef": {"name": "kagent-grafana-mcp"}}, {"secretRef": {"name": "kagent-grafana-mcp"}}]}
GOOD["pods"].append(pod("kagent", "kagent-grafana-mcp-1", [GRAFANA]))


def fake_get(data: dict):
    calls = []

    def get(*args: str) -> dict:
        calls.append(args)
        a = list(args)
        if a[:1] == ["-n"] and a[2:5] == ["get", "secret", "datadog-secret"]:
            if a[1] not in data["secrets"]:
                raise RuntimeError(f'secrets "datadog-secret" not found in {a[1]}')
            v = data["secrets"][a[1]]
            return {"data": {"api-key": base64.b64encode(v.encode()).decode()} if v else {}}
        if a[:1] == ["-n"] and a[2:4] == ["get", "secret"] and "metadata.name=datadog-admin-secret" in a:
            return {"items": [{"metadata": {"name": "datadog-admin-secret"}}] if a[1] in data["admin"] else []}
        if a[:1] == ["-n"] and a[2:4] == ["get", "configmap"]:
            if (a[1], a[4]) not in data["configmaps"]:
                raise RuntimeError(f'configmaps "{a[4]}" not found')
            return {"data": data["configmaps"][(a[1], a[4])]}
        if a[:1] == ["-n"] and a[2:4] == ["get", "secret"] and a[4] != "--field-selector":
            if (a[1], a[4]) not in data["secrets_refs"]:
                raise RuntimeError(f'secrets "{a[4]}" not found')
            return {"data": data["secrets_refs"][(a[1], a[4])]}
        if a == ["get", "pods", "-A"]:
            return {"items": data["pods"]}
        if a == ["-n", "datadog", "get", "datadogagent", "datadog"]:
            return data["agent"]
        raise AssertionError(f"unexpected kubectl read {a}")
    get.calls = calls
    return get


failures: list[str] = []


def check(name: str, cond: bool) -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        failures.append(name)


def judge(data: dict, key: str = KEY) -> tuple[list[str], list[str]]:
    out: list[str] = []
    return live.run("ctx", key, get=fake_get(data), say=out.append), out


print("== the pieces ==")
check("a short image drops the registry, the path, the tag and the digest",
      [live.short_image(i) for i in ("602401143452.dkr.ecr.us-west-2.amazonaws.com/eks/coredns:v1.11.4",
                                     "ghcr.io/x/guard-proxy@sha256:abc", "busybox")] == ["coredns", "guard-proxy", "busybox"])
confs = live.log_configs(AGENT)
check("the repo's DatadogAgent log configs are read, with their service and env",
      confs.get("coredns") == ("burritobot-coredns", ENV) and confs.get("kube-rbac-proxy", ("", ""))[1] == ENV)
check("the root service passes and a bare prefix does not",
      live.ours("burritobot") and live.ours("burritobot-argocd") and not live.ours("burritobot-")
      and not live.ours("argocd"))

print("== a cluster that meets every rule ==")
failed, out = judge(GOOD)
check("passes every check", failed == [])
check("reads the key, the second key and every container", sum(line.startswith("==") for line in out) == 3)
check("never prints the key", not any(KEY in line for line in out))


def broken(name: str, mutate, expect: str, key: str = KEY) -> list[str]:
    data = copy.deepcopy(GOOD)
    mutate(data)
    failed, out = judge(data, key)
    check(f"{name}: fails '{expect}'", any(expect in f for f in failed))
    return out


print("== each break turns it red ==")
out = broken("argocd before its helm upgrade (no labels)",
             lambda d: d["pods"][0]["metadata"].update({"labels": {}}), "every container's logs carry")
check("and names the pod and the image", any("argocd/argocd-server-1 server (argocd)" in line for line in out))
broken("the load balancer controller labelled with the old env",
       lambda d: d["pods"][1]["metadata"]["labels"].update({"tags.datadoghq.com/env": "production"}),
       "every container's logs carry")
broken("kubearmor with DD_SERVICE but no DD_ENV (the hook config never reached it)",
       lambda d: d["pods"][2]["spec"]["containers"][0].update({"env": [{"name": "DD_SERVICE", "value": "burritobot-kubearmor"}]}),
       "every container's logs carry")
broken("a second container with no name of its own and a pod label for the other",
       lambda d: d["pods"][7]["metadata"]["labels"].pop("tags.datadoghq.com/service"), "every container's logs carry")
broken("a pod log config naming a service outside BurritoBot",
       lambda d: d["pods"][8]["metadata"]["annotations"].update(
           {"ad.datadoghq.com/backstage.logs": '[{"source": "backstage", "service": "backstage"}]'}),
       "every container's logs carry")
out = broken("an unreadable pod log config",
             lambda d: d["pods"][8]["metadata"]["annotations"].update({"ad.datadoghq.com/backstage.logs": "[{"}),
             "every container's logs carry")
check("and says it is unreadable", any("unreadable ad.datadoghq.com/backstage.logs" in line for line in out))
broken("an EKS add-on image with no log config",
       lambda d: d["pods"].append(pod("kube-system", "metrics-server-1", [{"name": "m", "image": "x/metrics-server:1"}])),
       "every container's logs carry")
broken("a Joker deployed with its own service label",
       lambda d: d["pods"].append(pod("agent", "joker-1", [{"name": "j", "image": "x/joker:1"}],
                                      {"tags.datadoghq.com/service": "joker", "tags.datadoghq.com/env": ENV})),
       "every container's logs carry")
broken("monitoring's datadog-secret holds another key", lambda d: d["secrets"].update({"monitoring": "f" * 32}),
       "monitoring/datadog-secret's api-key is the burritobot key")
broken("security has no datadog-secret", lambda d: d["secrets"].pop("security"), "security/datadog-secret is readable")
broken("datadog's datadog-secret has no api-key", lambda d: d["secrets"].update({"datadog": ""}),
       "datadog/datadog-secret's api-key")
broken("watch-it-burn/datadog unread (no key to compare)", lambda d: None, "datadog/datadog-secret's api-key", key="")
broken("a datadog-admin-secret left on the cluster", lambda d: d["admin"].add("datadog"), "no datadog-admin-secret in datadog")
broken("a pod reading DD_API_KEY from another secret",
       lambda d: d["pods"][5]["spec"]["containers"][0]["env"].__setitem__(
           0, {"name": "DD_API_KEY", "valueFrom": {"secretKeyRef": {"name": "other-org", "key": "api-key"}}}),
       "every Datadog API key variable")
broken("a literal DD_API_KEY", lambda d: d["pods"][6]["spec"]["containers"][0]["env"].__setitem__(
    0, {"name": "DATADOG_APIKEY", "value": "f" * 32}), "every Datadog API key variable")
broken("a literal additional endpoint", lambda d: d["pods"][5]["spec"]["containers"][0]["env"].append(
    {"name": "DD_LOGS_CONFIG_ADDITIONAL_ENDPOINTS", "value": '[{"api_key":"x"}]'}), "every Datadog API key variable")
broken("no Running pods", lambda d: d.update({"pods": []}), "Running pods to read")
broken("a grafana-style container whose ConfigMap lacks the env",
       lambda d: d["configmaps"][("kagent", "kagent-grafana-mcp")].pop("DD_ENV"), "every container's logs carry")
out = broken("a container's own env overriding envFrom to another env",
             lambda d: d["pods"][-1]["spec"]["containers"][0].update({"env": [{"name": "DD_ENV", "value": "production"}]}),
             "every container's logs carry")
check("and names where its tags came from", any("env production" in line for line in out))
out = broken("an envFrom ConfigMap that cannot be read",
             lambda d: d["pods"][-1]["spec"]["containers"][0].update({"envFrom": [{"configMapRef": {"name": "missing"}}]}),
             "every container's logs carry")
check("and names the unreadable reference", any("envFrom configmap missing unreadable" in line for line in out))
broken("a grafana-style container whose ConfigMap lacks the service",
       lambda d: d["configmaps"][("kagent", "kagent-grafana-mcp")].pop("DD_SERVICE"), "every container's logs carry")
out = broken("an envFrom Secret that cannot be read, when it is the one carrying the tags",
             lambda d: (d["configmaps"].update({("kagent", "kagent-grafana-mcp"): {}}),
                        d["secrets_refs"].pop(("kagent", "kagent-grafana-mcp"))),
             "every container's logs carry")
check("and names the unreadable Secret", any("envFrom secret kagent-grafana-mcp unreadable" in line for line in out))
out = broken("an envFrom reference with no name",
             lambda d: d["pods"][-1]["spec"]["containers"][0].update({"envFrom": [{"configMapRef": {}}]}),
             "every container's logs carry")
check("and says the reference has no name", any("an envFrom configMapRef with no name" in line for line in out))
broken("an envFrom prefix that moves DD_SERVICE and DD_ENV to other names",
       lambda d: d["pods"][-1]["spec"]["containers"][0]["envFrom"][0].update({"prefix": "GRAFANA_"}),
       "every container's logs carry")
broken("a later envFrom Secret overriding the ConfigMap's env",
       lambda d: d["secrets_refs"].update({("kagent", "kagent-grafana-mcp"): {
           "DD_ENV": base64.b64encode(b"production").decode()}}), "every container's logs carry")
out = broken("an envFrom Secret whose DD_ENV is not base64 text",
             lambda d: (d["configmaps"][("kagent", "kagent-grafana-mcp")].pop("DD_ENV"),
                        d["secrets_refs"].update({("kagent", "kagent-grafana-mcp"): {"DD_ENV": "not base64!"}})),
             "every container's logs carry")
check("and names the undecodable value", any("DD_ENV is not base64 text" in line for line in out))


def passes(name: str, mutate) -> None:
    data = copy.deepcopy(GOOD)
    mutate(data)
    failed, _ = judge(data)
    check(f"{name}: passes", failed == [])


passes("a container fed only by an envFrom Secret",
       lambda d: (d["configmaps"].update({("kagent", "kagent-grafana-mcp"): {}}),
                  d["secrets_refs"].update({("kagent", "kagent-grafana-mcp"): {
                      "DD_ENV": base64.b64encode(ENV.encode()).decode(),
                      "DD_SERVICE": base64.b64encode(b"burritobot-grafana-mcp").decode()}})))
passes("an envFrom prefix of DD_ on SERVICE and ENV keys",
       lambda d: (d["configmaps"].update({("kagent", "kagent-grafana-mcp"): {
           "ENV": ENV, "SERVICE": "burritobot-grafana-mcp"}}),
                  d["pods"][-1]["spec"]["containers"][0]["envFrom"][0].update({"prefix": "DD_"})))
broken("a DatadogAgent with no log configs", lambda d: d["agent"]["spec"]["override"]["nodeAgent"].pop("extraConfd"),
       "file-based log configs")

print("== a failed kubectl read is a failure, not a pass ==")


def refusing(*args):
    raise RuntimeError("the server has asked for the client to provide credentials")


try:
    live.run("ctx", KEY, get=refusing, say=lambda _: None)
    check("an unreachable cluster raises past the first secret", False)
except RuntimeError as exc:
    check("an unreachable cluster raises past the first secret, naming kubectl's reason", "credentials" in str(exc))

print("== how it is run ==")
SRC = (HERE / "test_burritobot_cluster_live.py").read_text(encoding="utf-8")
check("it is in the E2E suite", "\n# SUITE: e2e" in SRC)
check("its one kubectl call names the context",
      SRC.count('"kubectl"') == 1 and '"kubectl", "--context", context, *args' in SRC)


def picked(argv: list[str], environ: dict):
    try:
        return live.contexts(argv, environ)
    except ValueError as exc:
        return f"ValueError: {exc}"


BOTH = {"COMMUNITY_CONTEXT": "watch-it-burn-community", "PRIVATE_CONTEXT": "watch-it-burn-private"}
check("each --context named is read, in order",
      picked(["--context", "a", "--context", "b"], BOTH) == ["a", "b"])
check("with no --context it reads COMMUNITY_CONTEXT and PRIVATE_CONTEXT",
      picked([], BOTH) == ["watch-it-burn-community", "watch-it-burn-private"])
check("with no --context and no PRIVATE_CONTEXT it fails naming it, never the current-context",
      "PRIVATE_CONTEXT" in str(picked([], {"COMMUNITY_CONTEXT": "c"})) and "ValueError" in str(picked([], {})))
check("an empty --context fails", "ValueError" in str(picked(["--context", ""], BOTH)))
check("CONTEXT alone is not read: no default cluster",
      "ValueError" in str(picked([], {"CONTEXT": "some-attendee-cluster"})))
check("an empty --context exits 1 before any read (its FAIL line above is expected)",
      live.main(["--context", ""]) == 1)
check("this file is not in the E2E suite",
      not any(line.startswith("# SUITE: e2e") for line in pathlib.Path(__file__).read_text().splitlines()))

print(f"\n  {'all passed' if not failures else f'{len(failures)} failed'}")
sys.exit(1 if failures else 0)
