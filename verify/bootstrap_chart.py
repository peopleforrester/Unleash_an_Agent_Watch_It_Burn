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
# The front door's certificate (#638): ai-layer.yaml alone holds a block between these two guards, rendered only when
# a root passes frontDoor.certificateArn, which patches the ARN onto the console Service's load balancer.
FRONT_DOOR_IF = "{{- if .Values.frontDoor.certificateArn }}"
FRONT_DOOR_ARN = "{{ .Values.frontDoor.certificateArn }}"
FRONT_DOOR_END = "{{- end }}"


def without_front_door(raw: str) -> str:
    """An app file as the chart renders it with no frontDoor.certificateArn: each guarded block left out."""
    return re.sub(r" \{\{- if \.Values\.frontDoor\.certificateArn \}\}.*? \{\{- end \}\}", "", raw, flags=re.S)


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
