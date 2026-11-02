# ABOUTME: Holds that KubeArmor's kubearmor-default KubeArmorConfig is a plain resource of the kubearmor Application,
# ABOUTME: from gitops/kubearmor-config at the root's revision, and not the operator chart's Helm hook (#629).
"""Offline: reads the app file and the local chart's files, renders nothing.

Why. The operator pushes a KubeArmorConfig's images and env into the DaemonSet, relay and controller it already runs
only when the config is updated in place (pkg/KubeArmorOperator/internal/controller/cluster.go at v1.7.4). With
autoDeploy on, kubearmor-operator 1.7.4 writes the config as a post-install,post-upgrade hook. Argo CD leaves a hook
out of the Application's sync status, so a change to it never starts an automated sync, and on a sync it deletes
the hook and creates it again (BeforeHookCreation), which the operator takes as a new config and pushes nowhere. So
#662's DD_SERVICE and DD_ENV never reached a running cluster's KubeArmor pods, whose logs reached Whitney's sandbox
org under service kubearmor (decisions.md, 2026-10-31, #711). verify/test_kubearmor_config_render.py renders both
charts and holds that the spec is the one the hook rendered.
"""
from __future__ import annotations

import pathlib
import sys

import yaml

REPO = pathlib.Path(__file__).resolve().parent.parent
APP = REPO / "gitops/bootstrap/apps/kubearmor.yaml"
CHART = REPO / "gitops/kubearmor-config"
REPO_URL = "https://github.com/peopleforrester/Unleash_an_Agent_Watch_It_Burn.git"
HOOKS = ("helm.sh/hook", "argocd.argoproj.io/hook")

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        failures.append(name)
        if detail:
            print(f"        {detail}")


print("== the kubearmor Application ==")
app = yaml.safe_load(APP.read_text(encoding="utf-8"))
sources = app["spec"].get("sources") or []
check("it has no single source, only sources", "source" not in app["spec"] and len(sources) == 2)
operator = [s for s in sources if s.get("chart") == "kubearmor-operator"]
config = [s for s in sources if s.get("path") == "gitops/kubearmor-config"]
check("one source is the kubearmor-operator chart", len(operator) == 1)
check("one source is gitops/kubearmor-config, from this repo at the root's revision",
      len(config) == 1 and config[0].get("repoURL") == REPO_URL
      and config[0].get("targetRevision") == "{{ .Values.revision }}")
op_values = ((operator[0].get("helm") or {}).get("valuesObject") or {}) if operator else {}
check("the operator chart's autoDeploy is off, so it renders no hook config", op_values.get("autoDeploy") is False)
check("the operator chart is given no kubearmorConfig, which only its hook would read",
      "kubearmorConfig" not in op_values)
cfg_values = ((config[0].get("helm") or {}).get("valuesObject") or {}) if config else {}
check("the config source carries the kubearmorConfig", isinstance(cfg_values.get("kubearmorConfig"), dict))
check("the Application applies server-side, so Argo CD's apply owns the fields it sets",
      "ServerSideApply=true" in (app["spec"].get("syncPolicy") or {}).get("syncOptions", []))

print("== gitops/kubearmor-config ==")
chart = yaml.safe_load((CHART / "Chart.yaml").read_text(encoding="utf-8"))
check("Chart.yaml is a v2 application chart", chart.get("apiVersion") == "v2" and chart.get("type") == "application")
templates = sorted((CHART / "templates").iterdir())
check("its templates are the config and the namespace's default limits",
      [p.name for p in templates] == ["kubearmorconfig.yaml", "limitrange.yaml"])
tpl = yaml.safe_load((CHART / "templates/kubearmorconfig.yaml").read_text(encoding="utf-8"))
meta = tpl.get("metadata") or {}
ann = meta.get("annotations") or {}
check("it is the KubeArmorConfig kubearmor-default, the name the hook used",
      tpl.get("kind") == "KubeArmorConfig" and tpl.get("apiVersion") == "operator.kubearmor.com/v1"
      and meta.get("name") == "kubearmor-default")
check(f"it carries no hook annotation ({[k for k in ann if k in HOOKS]})", not any(k in ann for k in HOOKS))
check("it syncs after the operator's own resources (a wave above 0)", int(ann.get("argocd.argoproj.io/sync-wave", "0")) > 0)
check("its dry run waits for the CRD the same sync applies",
      "SkipDryRunOnMissingResource=true" in ann.get("argocd.argoproj.io/sync-options", ""))
text = (CHART / "templates/kubearmorconfig.yaml").read_text(encoding="utf-8")
check("its spec is .Values.kubearmorConfig", "toYaml .Values.kubearmorConfig" in text)
# The operator sets no limits on what it builds, and KubeArmorConfig has no field for them, so with
# require-resource-limits armed (Deny on the admin profile) Kyverno refused its controller and snitch pods (#629).
lr = yaml.safe_load((CHART / "templates/limitrange.yaml").read_text(encoding="utf-8"))
lim = next((x for x in (lr.get("spec") or {}).get("limits") or [] if x.get("type") == "Container"), {})
check("a LimitRange gives every container in the namespace default cpu and memory limits and small requests",
      lr.get("kind") == "LimitRange" and {"cpu", "memory"} <= set(lim.get("default") or {})
      and {"cpu", "memory"} <= set(lim.get("defaultRequest") or {}))
check("it syncs before the operator's Deployment (a wave below 0)",
      int(((lr.get("metadata") or {}).get("annotations") or {}).get("argocd.argoproj.io/sync-wave", "0")) < 0)
ka = next((s.get("helm") or {}).get("valuesObject", {}).get("kubearmorConfig") or {} for s in config) if config else {}
check("the config sets DD_ENV on every component through globalEnv, the change that pushes env into running pods",
      {"name": "DD_ENV", "value": "burritobot-kubecon-na-26"} in (ka.get("globalEnv") or []))
defaults = (yaml.safe_load((CHART / "values.yaml").read_text(encoding="utf-8")) or {}).get("kubearmorConfig") or {}
check("values.yaml holds the operator chart's kubearmorConfig defaults, with stdout process logs off",
      defaults.get("enableStdOutLogs") is False and defaults.get("defaultFilePosture") == "audit")

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All KubeArmor config tracking checks passed.")
