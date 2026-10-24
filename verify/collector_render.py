# ABOUTME: Offline render of the OTel Collector config the way a cluster builds it: the Application's Helm
# ABOUTME: value files layered in order, then the datadog-gate's second --config (the Datadog overlay, or none).
"""The collector's config is two files at run time, and every check that reads it has to see both.

relay.yaml is the chart's render of `config` from the value files an Application lists. Since #500 that is the
Datadog-free collector. The datadog-gate init container then writes a second file the collector loads after
it: the otel-collector-datadog ConfigMap's datadog.yaml when datadog-secret exists, an empty config when it
does not. Both Helm and the collector merge the same way, maps recursively and every other value (lists
included) replaced, so one deep_merge models both steps.

Two things the chart does to relay.yaml are left out on purpose. It prepends k8s_attributes to each pipeline's
processors (the kubernetesAttributes preset), which the overlay never touches. And it renames `otlp` exporters
to `otlp_grpc`, which the overlay does NOT get; test_collector_no_datadog.py asserts no exporter here carries
an old name, so that rename has nothing to do.
"""
from __future__ import annotations

import copy
import pathlib

import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
APPS = REPO / "gitops/apps"
# The Application that installs the collector on each profile. admin and full take the instructor one; their
# roots exclude the attendee and burn ones (test_root_self_managed.py holds the excludes, and
# test_collector_backends.py checks each root selects exactly one of these).
PROFILE_APP = {"instructor": APPS / "otel-collector.yaml", "attendee": APPS / "otel-collector-attendee.yaml",
               "burn": APPS / "otel-collector-burn.yaml"}


def deep_merge(base, over):
    """Maps merged recursively; anything else in `over` replaces `base`. Helm's rule and the collector's."""
    if not (isinstance(base, dict) and isinstance(over, dict)):
        return copy.deepcopy(over)
    out = copy.deepcopy(base)
    for k, v in over.items():
        out[k] = deep_merge(out[k], v) if k in out else copy.deepcopy(v)
    return out


def value_files(app_path: pathlib.Path) -> list[pathlib.Path]:
    app = yaml.safe_load(app_path.read_text(encoding="utf-8"))
    chart = next(s for s in app["spec"]["sources"] if s.get("chart") == "opentelemetry-collector")
    return [REPO / f.replace("$values/", "") for f in chart["helm"]["valueFiles"]]


def helm_values(profile: str) -> dict:
    vals: dict = {}
    for f in value_files(PROFILE_APP[profile]):
        vals = deep_merge(vals, yaml.safe_load(f.read_text(encoding="utf-8")) or {})
    return vals


def overlay_configmap(vals: dict) -> dict:
    """The extraManifests ConfigMap the datadog-overlay volume mounts."""
    vol = next(v for v in vals.get("extraVolumes", []) if v["name"] == "datadog-overlay")
    name = vol["configMap"]["name"]
    return next(m for m in vals.get("extraManifests", [])
                if m.get("kind") == "ConfigMap" and m["metadata"]["name"] == name)


def datadog_overlay(vals: dict) -> dict:
    return yaml.safe_load(overlay_configmap(vals)["data"]["datadog.yaml"]) or {}


def collector_config(profile: str, datadog_secret: bool) -> dict:
    """The config the collector runs: relay.yaml, then what the gate wrote."""
    vals = helm_values(profile)
    return deep_merge(vals["config"], datadog_overlay(vals) if datadog_secret else {})
