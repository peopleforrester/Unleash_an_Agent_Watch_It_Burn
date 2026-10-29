# ABOUTME: Renders every chart and manifest a cluster runs and holds every container's logs to a burritobot- service
# ABOUTME: and the sandbox env: from pod labels, DD_SERVICE/DD_ENV env, or the Datadog Agent's log config by image (#662).
# SUITE: e2e (needs helm and kubectl: the labels are judged on the rendered manifests)
# E2E TIER: tools (no cluster, no AWS: run-e2e-tools.sh runs it with the pinned tools, #572)
#
# Why. Issue 629 asks that every log from the KubeCon clusters carry a burritobot-* service in Whitney's sandbox org,
# and #662 found most of the platform still logging under image short names. The Datadog Agent names a container's
# logs, in this order, from a file-based Autodiscovery log config that matches its short image name, else from the
# standard tags: the pod's tags.datadoghq.com/* labels (never its annotations: comp/core/tagger/collectors/
# workloadmeta_extract.go reads those keys from pod.Labels only, read 2026-10-29) or the container's DD_SERVICE and
# DD_ENV, which the containerd collector reads off the container spec, envFrom included. Whether a chart's values
# reach the pod is the chart's behaviour, so this asks Helm, at each pinned version, the way Argo CD will render it.
#
# Covered: every Application under gitops/bootstrap/apps (all profiles, so both KubeCon clusters), the pods the
# operators build from rendered CRs (Prometheus, KubeArmorConfig, DatadogAgent), Argo CD and the AWS Load Balancer
# Controller that infra/deploy-full-idp.sh installs, and kube-system's EKS add-ons from Terraform, which are not
# charts here and are named by the Agent's log config. Not covered: pods the agent or the room creates during a run.
from __future__ import annotations

import pathlib
import re
import subprocess
import sys
import tempfile

import yaml

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from bootstrap_chart import APPS, IMAGE_REGISTRY, LAB_PLATFORM_GHCR, REPO, kustomize_images, set_image  # noqa: E402

DD_ENV = "burritobot-kubecon-na-26"
SVC, ENV = "tags.datadoghq.com/service", "tags.datadoghq.com/env"
WORKLOADS = ("Deployment", "DaemonSet", "StatefulSet", "Job", "CronJob")
# guard-proxy's service is the root span's, burritobot, which Datadog takes as the LLM Obs ml_app (question 868).
ROOT_SERVICE_POD = "guard-proxy"
# kube-system's images, per add-on in infra/terraform/aws/cluster/main.tf, by short image name (EKS's ECR repositories
# eks/coredns, eks/kube-proxy, amazon-k8s-cni, amazon/aws-network-policy-agent, eks/aws-ebs-csi-driver and its
# eks/csi-* sidecars, eks/eks-pod-identity-agent).
EKS_ADDON_IMAGES = {
    "vpc-cni": {"amazon-k8s-cni", "amazon-k8s-cni-init", "aws-network-policy-agent"},
    "kube-proxy": {"kube-proxy"},
    "coredns": {"coredns"},
    "eks-pod-identity-agent": {"eks-pod-identity-agent"},
    "aws-ebs-csi-driver": {"aws-ebs-csi-driver", "csi-provisioner", "csi-attacher", "csi-snapshotter", "csi-resizer",
                           "livenessprobe", "csi-node-driver-registrar"},
}

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        failures.append(name)
        if detail:
            print(f"        {detail}")


def load_all(text: str) -> list:
    """Tolerant loader: charts emit tags the safe loader rejects; only the shape matters here."""
    return [d for d in yaml.load_all(text, Loader=yaml.BaseLoader) if isinstance(d, dict)]


def short_image(ref: str) -> str:
    """The short image name the Agent matches ad_identifiers against: no registry, path, tag or digest."""
    return ref.split("@", 1)[0].rsplit("/", 1)[-1].split(":", 1)[0]


def helm(release: str, chart: str, repo: str, version: str, namespace: str, value_files: list[pathlib.Path],
         extra: tuple[str, ...] = ()) -> list:
    if repo.startswith("oci://") or "ghcr.io" in repo:
        oci = repo if repo.startswith("oci://") else f"oci://{repo}"
        ref = ["helm", "template", release, f"{oci.rstrip('/')}/{chart}"]
    else:
        ref = ["helm", "template", release, chart, "--repo", repo]
    cmd = ref + ["--version", version, "-n", namespace] + [a for f in value_files for a in ("-f", str(f))] + list(extra)
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"{' '.join(cmd[:4])}: {(r.stderr.strip().splitlines() or ['helm failed'])[-1][:200]}")
    return load_all(r.stdout)


def render_app(app: dict) -> list:
    """The manifests Argo CD applies for one Application: each chart source through Helm, each path source as-is."""
    docs = []
    ns = app["spec"]["destination"].get("namespace", "default")
    for src in app["spec"].get("sources") or [app["spec"]["source"]]:
        if "chart" in src:
            h = src.get("helm") or {}
            with tempfile.TemporaryDirectory() as tmp:
                vals = pathlib.Path(tmp) / "values.yaml"
                vals.write_text(yaml.safe_dump(h.get("valuesObject") or {}))
                files = [vals] + [REPO / vf.replace("$values/", "") for vf in h.get("valueFiles", [])]
                docs += helm(h.get("releaseName") or app["metadata"]["name"], src["chart"], src["repoURL"],
                             str(src["targetRevision"]), ns, files)
        elif "path" in src:
            path = REPO / src["path"]
            if (path / "kustomization.yaml").exists():
                r = subprocess.run(["kubectl", "kustomize", str(path)], capture_output=True, text=True)
                if r.returncode != 0:
                    raise RuntimeError(f"kubectl kustomize {src['path']}: {r.stderr.strip()[:200]}")
                docs += load_all(r.stdout)
            else:
                files = sorted(path.rglob("*.yaml")) if (src.get("directory") or {}).get("recurse") else sorted(path.glob("*.yaml"))
                for f in files:
                    docs += load_all(f.read_text())
    return docs


def pod_template(d: dict) -> dict:
    spec = d.get("spec") or {}
    return (((spec.get("jobTemplate") or {}).get("spec") or {}).get("template") if d["kind"] == "CronJob"
            else spec.get("template")) or {}


def container_env(c: dict, configmaps: dict) -> dict:
    """DD_SERVICE and DD_ENV as the container will have them: its env values and its envFrom config maps."""
    out = {}
    for ref in c.get("envFrom") or []:
        name = (ref.get("configMapRef") or {}).get("name")
        out.update({k: v for k, v in (configmaps.get(name) or {}).items() if k in ("DD_SERVICE", "DD_ENV")})
    out.update({e["name"]: e.get("value") for e in c.get("env") or [] if e.get("name") in ("DD_SERVICE", "DD_ENV")})
    return out


def judge(where: str, pod: str, labels: dict, containers: list[dict], configmaps: dict, ad: dict,
          images: list[dict]) -> None:
    """Every container of one pod logs under a burritobot- service with the env, and none is shadowed by a log config."""
    for c in containers:
        img = short_image(set_image(c.get("image", ""), images))
        env = container_env(c, configmaps)
        if img in ad:
            # A log config's service wins over a pod's labels, so a log config may only name a pod that has none.
            named = labels.get(SVC) or env.get("DD_SERVICE")
            check(f"{where} {pod}/{c['name']}: {img} is named by the Agent's log config ({ad[img]}), and the pod names "
                  f"no service of its own", not named, f"the pod names {named}, which the log config would override")
            continue
        svc = env.get("DD_SERVICE") or labels.get(SVC) or ""
        denv = env.get("DD_ENV") or labels.get(ENV) or ""
        ok_svc = svc == "burritobot" if pod == ROOT_SERVICE_POD else svc.startswith("burritobot-")
        check(f"{where} {pod}/{c['name']} logs as service={svc or f'<{img}>'} env={denv or '<none>'}",
              ok_svc and denv == DD_ENV)


def judge_docs(where: str, docs: list, ad: dict, images: list[dict]) -> int:
    configmaps = {d["metadata"]["name"]: d.get("data") or {} for d in docs if d.get("kind") == "ConfigMap"}
    n = 0
    for d in docs:
        if d.get("kind") not in WORKLOADS:
            continue
        tpl = pod_template(d)
        labels = (tpl.get("metadata") or {}).get("labels") or {}
        spec = tpl.get("spec") or {}
        judge(where, d["metadata"]["name"], labels, (spec.get("initContainers") or []) + (spec.get("containers") or []),
              configmaps, ad, images)
        n += 1
    return n


print("== the Datadog Agent's log configs: one per image, a burritobot- service and the env ==")
agent = yaml.safe_load((REPO / "gitops/manifests/datadog/datadog-agent.yaml").read_text())
confd = ((agent["spec"]["override"]["nodeAgent"].get("extraConfd") or {}).get("configDataMap")) or {}
ad: dict[str, str] = {}
for fname, body in sorted(confd.items()):
    doc = yaml.safe_load(body) or {}
    ids, logs = doc.get("ad_identifiers") or [], doc.get("logs") or []
    img = ids[0] if len(ids) == 1 else ""
    entry = logs[0] if len(logs) == 1 else {}
    check(f"{fname}: one image, one log config, source {img}, service {entry.get('service')}, env tag",
          fname == f"burritobot-logs-{img}.yaml" and entry.get("source") == img
          and str(entry.get("service", "")).startswith("burritobot-") and entry.get("tags") == [f"env:{DD_ENV}"]
          and set(doc) == {"ad_identifiers", "logs"}, str(doc))
    ad[img] = entry.get("service", "")

print("== kube-system: every EKS add-on's images are named by the log configs ==")
tf = (REPO / "infra/terraform/aws/cluster/main.tf").read_text()
block = re.search(r"\n  addons = \{\n(.*?)\n  \}\n", tf, re.S)
addons = set(re.findall(r"^    ([a-z0-9-]+)\s+= \{", block.group(1) if block else "", re.M))
check(f"main.tf's add-ons are the ones listed here ({sorted(addons)})", addons == set(EKS_ADDON_IMAGES),
      f"a new add-on needs its images in EKS_ADDON_IMAGES and the DatadogAgent's log configs; listed {sorted(EKS_ADDON_IMAGES)}")
for name, imgs in sorted(EKS_ADDON_IMAGES.items()):
    missing = sorted(imgs - set(ad))
    check(f"{name}: {', '.join(sorted(imgs))} have a log config", not missing, f"missing {missing}")

print("== every Application's pods ==")
for f in sorted(APPS.glob("*.yaml")):
    for app in yaml.safe_load_all(f.read_text().replace(IMAGE_REGISTRY, LAB_PLATFORM_GHCR)):
        if not (isinstance(app, dict) and app.get("kind") == "Application"):
            continue
        where = f"{f.name}[{app['metadata']['name']}]"
        try:
            docs = render_app(app)
        except RuntimeError as e:
            check(f"{where} renders", False, str(e))
            continue
        judge_docs(where, docs, ad, kustomize_images(app))
        for d in docs:
            kind = d.get("kind")
            if kind == "Prometheus":
                pl = ((d.get("spec") or {}).get("podMetadata") or {}).get("labels") or {}
                check(f"{where} Prometheus/{d['metadata']['name']}: the operator's pod gets service={pl.get(SVC)} "
                      f"env={pl.get(ENV)}", str(pl.get(SVC, "")).startswith("burritobot-") and pl.get(ENV) == DD_ENV)
            elif kind == "KubeArmorConfig":
                # The operator sets each component's env on its first container (and the init image's on the
                # DaemonSet's init container); the rest of its pods' containers are in the log configs.
                for comp in ("kubearmorImage", "kubearmorInitImage", "kubearmorRelayImage", "kubearmorControllerImage"):
                    env = {e["name"]: e.get("value") for e in ((d["spec"].get(comp) or {}).get("env") or [])}
                    check(f"{where} KubeArmorConfig {comp}: DD_SERVICE={env.get('DD_SERVICE')} DD_ENV={env.get('DD_ENV')}",
                          str(env.get("DD_SERVICE", "")).startswith("burritobot-") and env.get("DD_ENV") == DD_ENV)
                for img in ("kube-rbac-proxy", "kubearmor-snitch"):
                    check(f"{where} KubeArmor's {img}, which takes no env from the config, has a log config", img in ad)
            elif kind == "DatadogAgent":
                for comp in ("nodeAgent", "clusterAgent"):
                    lab = (d["spec"]["override"].get(comp) or {}).get("labels") or {}
                    check(f"{where} DatadogAgent {comp} pods: service={lab.get(SVC)} env={lab.get(ENV)}",
                          str(lab.get(SVC, "")).startswith("burritobot-") and lab.get(ENV) == DD_ENV)

print("== what infra/deploy-full-idp.sh installs with Helm ==")
deploy = (REPO / "infra/deploy-full-idp.sh").read_text()
for release, chart, repo, values in (
        ("argocd", "argo-cd", "https://argoproj.github.io/argo-helm", "argocd-values.yaml"),
        ("aws-load-balancer-controller", "aws-load-balancer-controller", "https://aws.github.io/eks-charts",
         "aws-load-balancer-controller-values.yaml")):
    m = re.search(rf"helm upgrade --install {release} \S+/{chart} --version (\S+)((?:.*\\\n)*.*)", deploy)
    check(f"deploy-full-idp.sh installs {chart} with {values}", bool(m) and f'"${{SCRIPT_DIR}}/{values}"' in m.group(2))
    if not m:
        continue
    ns = re.search(r"-n (\S+)", m.group(2)).group(1)
    extra = ("--set", "clusterName=watch-it-burn-x", "--set", "region=us-west-2", "--set", "vpcId=vpc-0") \
        if release == "aws-load-balancer-controller" else ()
    try:
        docs = helm(release, chart, repo, m.group(1), ns, [REPO / "infra" / values], extra)
    except RuntimeError as e:
        check(f"{chart} {m.group(1)} renders", False, str(e))
        continue
    check(f"{chart} {m.group(1)} renders workloads", judge_docs(f"deploy-full-idp.sh[{release}]", docs, ad, []) > 0)

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    sys.exit(1)
print("Every container's logs carry a burritobot- service and the sandbox env.")
