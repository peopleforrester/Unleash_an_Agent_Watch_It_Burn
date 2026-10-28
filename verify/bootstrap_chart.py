# ABOUTME: The gitops/bootstrap root chart as the offline tests read it (#609): the profiles lab-platform.yaml
# ABOUTME: names, each profile's app list from its values file, and the app files the chart renders, without Helm.
"""One place for every test that asks what a profile installs.

Before #609 each profile had its own root Application, and tests answered "does this profile deploy X" by
expanding the root's directory brace glob. The roots are now one chart, gitops/bootstrap, and a profile is
the explicit list in values-<profile>.yaml, so the answer is a set lookup. test_bootstrap_chart.py holds
the chart's shape; test_bootstrap_chart_render.py renders it with the pinned Helm.
"""
from __future__ import annotations

import pathlib
import re

import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
CHART = REPO / "gitops/bootstrap"
APPS = CHART / "apps"
TEMPLATES = CHART / "templates"
CONFIG = REPO / "lab-platform.yaml"
REPO_URL = "https://github.com/peopleforrester/Unleash_an_Agent_Watch_It_Burn.git"
# What every Unleashed source in an app file says instead of a branch: the revision the root passes down.
REVISION = "{{ .Values.revision }}"
# What an app file says instead of ghcr.io/peopleforrester/lab-platform: the registry the root passes down (#622).
IMAGE_REGISTRY = "{{ .Values.imageRegistry }}"
# The chart's default for it, which infra/deploy-full-idp.sh and an account with no pull-through cache get.
LAB_PLATFORM_GHCR = "ghcr.io/peopleforrester/lab-platform"

# lab-platform's deploy/mirror/copies.tsv as lab-platform#183 closed it (2026-10-28): each copy is under
# <imageRegistry>/mirror/, named by its upstream tag with the first twelve characters of its linux/amd64 digest
# appended. A row: what the chart pulled from upstream, the copy, the app files naming it, and where in the chart
# source's valuesObject the reference is, each {dotted.key} filled from it. Every copy a chart pulls is here.
_IMAGE = "{image.registry}/{image.repository}:{image.tag}"
_KUBEARMOR = "{kubearmor.repo}/{kubearmor.images.%s.image}:{kubearmor.images.%s.tag}"
_POSTGRES = "{database.postgres.bundled.image.%s}"
MIRROR_COPIES = (
    ("falco.docker.scarf.sh/falcosecurity/falco-talon:0.3.0", "falcosecurity/falco-talon:0.3.0-0a06b6a5e9f0",
     ("falco-talon",), _IMAGE),
    ("docker.io/falcosecurity/falcosidekick:2.32.0", "falcosecurity/falcosidekick:2.32.0-399d95934a67",
     ("falcosidekick",), _IMAGE),
    ("docker.io/library/postgres:18.6-alpine3.23", "library/postgres:18.6-alpine3.23-dd504ba15d33", ("kagent",),
     "/".join(_POSTGRES % k for k in ("registry", "repository", "name")) + ":" + _POSTGRES % "tag"),
    ("mcp/grafana:latest", "mcp/grafana:latest-208f8ea16064", ("kagent",),
     "{grafana-mcp.image.registry}/{grafana-mcp.image.repository}:{grafana-mcp.image.tag}"),
    ("docker.io/kubearmor/kubearmor-operator:v1.7.4", "kubearmor/kubearmor-operator:v1.7.4-84626528c4d6",
     ("kubearmor",), _KUBEARMOR % ("kubearmorOperator", "kubearmorOperator")),
    ("docker.io/kubearmor/kubearmor:stable", "kubearmor/kubearmor:stable-bf867783eb30",
     ("kubearmor",), _KUBEARMOR % ("kubearmor", "kubearmor")),
    ("docker.io/kubearmor/kubearmor-init:stable", "kubearmor/kubearmor-init:stable-cdc3763f302d",
     ("kubearmor",), _KUBEARMOR % ("kubearmorInit", "kubearmorInit")),
    ("docker.io/kubearmor/kubearmor-relay-server:latest", "kubearmor/kubearmor-relay-server:latest-e4fd875cc1e4",
     ("kubearmor",), _KUBEARMOR % ("kubearmorRelay", "kubearmorRelay")),
    ("docker.io/kubearmor/kubearmor-controller:latest", "kubearmor/kubearmor-controller:latest-89f52a3e9fc0",
     ("kubearmor",), _KUBEARMOR % ("kubearmorController", "kubearmorController")),
    ("docker.io/kubearmor/kubearmor-snitch:latest", "kubearmor/kubearmor-snitch:latest-ec11d33057b1",
     ("kubearmor",), _KUBEARMOR % ("kubearmorSnitch", "kubearmorSnitch")),
    ("otel/opentelemetry-collector-contrib:0.160.0",
     "otel/opentelemetry-collector-contrib:0.160.0-5b66b0dc6921",
     ("otel-collector", "otel-collector-attendee", "otel-collector-burn"), "{image.repository}:{image.tag}"),
    ("otel/opentelemetry-collector-k8s:0.158.0", "otel/opentelemetry-collector-k8s:0.158.0-158b837a5e98",
     ("otel-operator",), "{manager.collectorImage.repository}:{manager.collectorImage.tag}"),
    ("docker.io/grafana/grafana:13.2.2-distroless", "grafana/grafana:13.2.2-distroless-ada1141b386c",
     ("prometheus",), "{grafana.image.registry}/{grafana.image.repository}:{grafana.image.tag}"),
    ("docker.io/grafana/tempo:3.0.3", "grafana/tempo:3.0.3-05321ebf1f19",
     ("tempo",), "{tempo.registry}/{tempo.repository}:{tempo.tag}"),
)
# The two rows no chart pulls. Falco was bumped to chart 9.2.1 for kernel 6.18 (#626) after the copies were taken,
# and pulls falco 0.45.1 and falcoctl 0.14.2, so taking these would undo that fix. They wait for new copies.
MIRROR_COPIES_NOT_PULLED = (
    ("docker.io/falcosecurity/falco:0.44.1", "falcosecurity/falco:0.44.1-9f02feb5544a"),
    ("docker.io/falcosecurity/falcoctl:0.13.0", "falcosecurity/falcoctl:0.13.0-ffe71491ff79"),
)


def chart_helm(app: dict) -> dict:
    """The valuesObject of an Application's chart source (a multi-source app's other sources hold no chart)."""
    sp = app.get("spec") or {}
    for s in ([sp["source"]] if "source" in sp else []) + list(sp.get("sources") or []):
        if "chart" in s:
            return (s.get("helm") or {}).get("valuesObject") or {}
    return {}


def mirror_reference(values_object: dict, where: str) -> str:
    """The image a MIRROR_COPIES row's {dotted.key} template composes from a valuesObject; a missing key is ''."""
    def lookup(m: re.Match) -> str:
        node = values_object
        for k in m.group(1).split("."):
            node = node.get(k) if isinstance(node, dict) else None
        return node if isinstance(node, str) else ""
    return re.sub(r"\{([^{}]+)\}", lookup, where)


def profiles() -> list[str]:
    """The profile names lab-platform.yaml declares, in its order."""
    doc = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    return [p["name"] for p in doc["bootstrap"]["profiles"]]


def values_path(profile: str) -> pathlib.Path:
    return CHART / f"values-{profile}.yaml"


def values(profile: str) -> dict:
    return yaml.safe_load(values_path(profile).read_text(encoding="utf-8")) or {}


def app_names(profile: str) -> list[str]:
    """The apps a profile's values file lists, as written: each is apps/<name>.yaml."""
    return list(values(profile).get("apps") or [])


def app_files(profile: str) -> set[str]:
    """The apps/ file names a profile renders."""
    return {f"{n}.yaml" for n in app_names(profile)}


def deploys(profile: str, app_file: str) -> bool:
    """Whether a profile installs this apps/ file (given as 'name.yaml' or 'name')."""
    name = app_file[:-5] if app_file.endswith(".yaml") else app_file
    return name in app_names(profile)


def is_template(path: pathlib.Path) -> bool:
    """A Helm template of the chart: Go template text, not YAML, so YAML-reading sweeps leave it out."""
    return TEMPLATES in path.resolve().parents


def deploy_root(profile: str) -> dict:
    """The lab-bootstrap Application infra/deploy-full-idp.sh step [4] applies for a profile, from its heredoc."""
    deploy = (REPO / "infra/deploy-full-idp.sh").read_text(encoding="utf-8")
    m = re.search(r"kubectl apply -f - <<EOF\n(.*?)\nEOF", deploy[deploy.index('log "[4]'):], re.S)
    if not m:
        return {}
    return yaml.safe_load(m.group(1).replace("${REPO_URL}", REPO_URL).replace("${PROFILE}", profile)
                          .replace("${VALUES}", f"values-{profile}.yaml")) or {}
