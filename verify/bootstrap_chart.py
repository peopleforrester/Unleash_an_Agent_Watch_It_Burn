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


# Where Challenge 7's control sits (#679): values.yaml's c7Control, toolnames unless a profile's values file says
# gateway. workshop-agent.yaml renders the Agent's evil-mcp toolNames ignore between these two guards, on toolnames only (#707).
C7_TOOLNAMES_IF = '{{- if ne .Values.c7Control "gateway" }}'
C7_TOOLNAMES_END = "{{- end }}"


def c7_control(profile: str) -> str:
    """Where a profile's Challenge 7 control sits: its values file's c7Control, else values.yaml's."""
    shared = yaml.safe_load((CHART / "values.yaml").read_text(encoding="utf-8")) or {}
    return values(profile).get("c7Control", shared.get("c7Control"))


def for_c7_control(raw: str, control: str) -> str:
    """An app file as the chart renders it for this c7Control: the toolnames-only block left out on gateway."""
    if control == "toolnames":
        return raw
    return re.sub(r" \{\{- if ne \.Values\.c7Control \"gateway\" \}\}.*? \{\{- end \}\}", "", raw, flags=re.S)


def without_front_door(raw: str) -> str:
    """An app file as the chart renders it with no frontDoor.certificateArn: each guarded block left out."""
    return re.sub(r" \{\{- if \.Values\.frontDoor\.certificateArn \}\}.*? \{\{- end \}\}", "", raw, flags=re.S)


# The KubeCon presenter page (#909): values.yaml's console.kubeconBrief, true unless a profile's values file says false.
# ai-layer.yaml alone holds a block between these two guards, rendered on false, which adds the no-kubecon-brief
# component that takes kubecon.html out of the console-src ConfigMap.
KUBECON_WITHHELD_IF = "{{- if not .Values.console.kubeconBrief }}"
KUBECON_WITHHELD_END = "{{- end }}"
NO_KUBECON_COMPONENT = "components/no-kubecon-brief"


def kubecon_brief(profile: str) -> bool:
    """Whether a profile's console serves /kubecon: its values file's console.kubeconBrief, else values.yaml's."""
    shared = yaml.safe_load((CHART / "values.yaml").read_text(encoding="utf-8")) or {}
    return (values(profile).get("console") or {}).get("kubeconBrief", shared["console"]["kubeconBrief"])


def for_kubecon_brief(raw: str, serve: bool) -> str:
    """An app file as the chart renders it at this console.kubeconBrief: the withholding block left out on true."""
    if not serve:
        return raw
    return re.sub(" " + re.escape(KUBECON_WITHHELD_IF) + r".*? \{\{- end \}\}", "", raw, flags=re.S)


# The guardrails' action (#638, lab-platform#310): values.yaml's guardrails.validationAction, Audit unless lab-platform's
# arm step sets Deny. kyverno-policies.yaml alone holds a block between each pair: the Deny patches when armed, the
# /spec/validationActions ignore when not.
ARMED_IF = '{{- if eq .Values.guardrails.validationAction "Deny" }}'
UNARMED_IF = '{{- if ne .Values.guardrails.validationAction "Deny" }}'
ARM_END = "{{- end }}"
# lab-platform.yaml's arm section: the Helm parameter lab-platform sets on an arming role's root, and its value.
ARM_PARAMETER = "guardrails.validationAction"
ARM_VALUE = "Deny"


def for_guardrails(raw: str, action: str) -> str:
    """An app file as the chart renders it at this guardrails.validationAction: the other action's block left out."""
    drop = UNARMED_IF if action == "Deny" else ARMED_IF
    return re.sub(" " + re.escape(drop) + r".*? \{\{- end \}\}", "", raw, flags=re.S)


def profiles() -> list[str]:
    """The profile names lab-platform.yaml declares, in its order."""
    doc = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    return [p["name"] for p in doc["bootstrap"]["profiles"]]


# Profiles infra/deploy-full-idp.sh builds that lab-platform.yaml does not present (#394): local-inference is full
# plus a CPU vLLM for one instructor or demo cluster (question 657), never a roster or attendee cluster, so labctl
# is not handed it. kubecon-community and kubecon-private are the breakout's two roster clusters with the four
# Kubernetes guardrails off until guardrails-on (#774); fleet.sh builds the KubeCon roster, so labctl is not handed
# them either.
DEPLOY_ONLY_PROFILES = ("local-inference", "kubecon-community", "kubecon-private")
# The KubeCon breakout's profiles (#774), and the workshop profile each one stands in for on its role.
KUBECON_PROFILES = {"kubecon-community": "burn", "kubecon-private": "admin"}


def all_profiles() -> list[str]:
    """Every profile the chart has a values file for: lab-platform.yaml's, then the deploy-only ones."""
    return profiles() + list(DEPLOY_ONLY_PROFILES)


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


# The app that puts behind each service host fleet.sh publishes (WIB_SERVICE_HOSTS) the Service console.conf maps it
# to (#887): Grafana is kube-prometheus-stack's, in the prometheus app. None is Argo CD, which the root itself runs on,
# so every profile has it. A host whose app a profile leaves out answers the console's not-installed page there.
SERVICE_HOST_APPS = {"grafana": "prometheus", "argocd": None, "backstage": "backstage"}


def serves(profile: str, label: str) -> bool:
    """Whether a profile installs what the service host <label>-<cluster> fronts. KeyError on a host not mapped."""
    app = SERVICE_HOST_APPS[label]
    return app is None or deploys(profile, app)


def is_template(path: pathlib.Path) -> bool:
    """A Helm template of the chart: Go template text, not YAML, so YAML-reading sweeps leave it out."""
    return TEMPLATES in path.resolve().parents


def deploy_root(profile: str) -> dict:
    """The lab-bootstrap Application infra/deploy-full-idp.sh step [4] applies for a profile, from its heredoc."""
    deploy = (REPO / "infra/deploy-full-idp.sh").read_text(encoding="utf-8")
    m = re.search(r'kubectl --context "\$\{CONTEXT\}" apply -f - <<EOF\n(.*?)\nEOF', deploy[deploy.index('log "[4]'):], re.S)
    if not m:
        return {}
    return yaml.safe_load(m.group(1).replace("${REPO_URL}", REPO_URL).replace("${PROFILE}", profile)
                          .replace("${VALUES}", f"values-{profile}.yaml")) or {}


def kustomize_images(app: dict) -> list[dict]:
    """An Application's kustomize.images (#652), each as the entry `kustomize edit set image` writes for it.

    Argo CD hands each string to that command, which reads name=newName:newTag@digest and writes name, newName,
    newTag and digest into the kustomization (measured with kustomize v5.8.1, the one Argo CD v3.4.4 bundles)."""
    src = (app.get("spec") or {}).get("source") or {}
    out = []
    for arg in (src.get("kustomize") or {}).get("images") or []:
        name, _, new = arg.partition("=")
        new, _, digest = new.partition("@")
        new_name, tag = (new.rsplit(":", 1) if ":" in new.rsplit("/", 1)[-1] else (new, ""))
        entry = {"name": name, "newName": new_name}
        if tag:
            entry["newTag"] = tag
        if digest:
            entry["digest"] = digest
        out.append(entry)
    return out


def image_name(ref: str) -> str:
    """A reference less its tag and digest: the name a kustomize images entry matches."""
    ref = ref.split("@", 1)[0]
    head, _, last = ref.rpartition("/")
    return f"{head}/{last.split(':', 1)[0]}" if head else last.split(":", 1)[0]


def set_image(ref: str, entries: list[dict]) -> str:
    """The reference kustomize writes for ref under these images entries; ref itself when none names it."""
    for e in entries:
        if image_name(ref) == e["name"]:
            if "newTag" not in e and "digest" not in e:
                return e["newName"] + ref[len(e["name"]):]
            return e["newName"] + (f":{e['newTag']}" if "newTag" in e else "") + (f"@{e['digest']}" if "digest" in e else "")
    return ref
