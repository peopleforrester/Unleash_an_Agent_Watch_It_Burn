# ABOUTME: Offline render of the OTel Collector config the way a cluster builds it: the Application's Helm
# ABOUTME: value files layered in order, then the datadog-gate's second --config (the Datadog overlay, or none).
"""The collector's config is two files at run time, and every check that reads it has to see both.

relay.yaml is the chart's render of `config` from the value files an Application lists. Since #500 that is the
Datadog-free collector. The datadog-gate init container then writes a second file the collector loads after
it: the otel-collector-datadog ConfigMap's datadog.yaml when datadog-secret exists, an empty config when it
does not. On the attendee profile the ConfigMap also has datadog-dual.yaml, which the gate loads instead when
datadog-admin-secret exists too, the instructor org being a second org (#587). Both Helm and the collector merge the same way, maps recursively and every other value (lists
included) replaced, so one deep_merge models both steps.

Since #1332 there is a third file. transform/coc_mask, the code-of-conduct mask, is too big for relay.yaml's
ConfigMap (helm writes its aliased statements out four times), so it is the otel-collector-coc-mask ConfigMap in
gitops/otel-collector/coc-mask/, which each collector Application deploys as a directory source of its own and
values.yaml mounts and loads with a further --config. collector_config() reads every --config in command.extraArgs in
order and finds each file the way the pod does: the mount its directory is, that mount's volume, the volume's
ConfigMap among the Application's manifests, and the file's key in it.

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
APPS = REPO / "gitops/bootstrap/apps"
# The Application that installs the collector on each profile. admin and full take the instructor one; their
# values files list neither the attendee nor the burn one (test_bootstrap_chart.py holds the lists, and
# test_collector_backends.py checks each profile lists exactly one of these).
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


def datadog_overlay(vals: dict, admin_secret: bool = True) -> dict:
    """The file the gate copies when datadog-secret exists: datadog-dual.yaml where the ConfigMap has one and
    datadog-admin-secret exists, datadog.yaml otherwise."""
    data = overlay_configmap(vals)["data"]
    return yaml.safe_load(data["datadog-dual.yaml" if admin_secret and "datadog-dual.yaml" in data else "datadog.yaml"]) or {}


def feature_gate_args(profile: str) -> list[str]:
    """The --feature-gates arguments the profile's chart passes the collector (command.extraArgs). A test that runs
    the traces processors passes them too: without ottl.functions.enableLambda the collector refuses the config."""
    return [a for a in helm_values(profile).get("command", {}).get("extraArgs", []) if a.startswith("--feature-gates=")]


def directory_manifests(app_path: pathlib.Path) -> list[dict]:
    """The manifests of the Application's in-repo directory sources, as Argo CD applies them: each *.yaml at the top of
    the path (no source here recurses), every document in it."""
    app = yaml.safe_load(app_path.read_text(encoding="utf-8"))
    out: list[dict] = []
    for src in app["spec"].get("sources") or [app["spec"]["source"]]:
        if "path" not in src or "chart" in src:
            continue
        for f in sorted((REPO / src["path"]).glob("*.yaml")):
            out += [d for d in yaml.safe_load_all(f.read_text(encoding="utf-8")) if d]
    return out


def config_paths(vals: dict) -> list[str]:
    """Each --config the chart's command.extraArgs adds after relay.yaml, in the order the collector loads them."""
    return [a.split("=", 1)[1] for a in vals.get("command", {}).get("extraArgs", []) if a.startswith("--config=")]


GATE_VOLUME = "datadog-gate"  # the emptyDir the datadog-gate init container writes, not a ConfigMap


def mounted_file(profile: str, vals: dict, path: str) -> tuple[dict, str]:
    """The volume a --config path is read from and, for a ConfigMap volume, the file's text: the mount whose
    mountPath is the path's directory, its volume, the volume's ConfigMap among the chart's extraManifests and the
    Application's directory sources, and the key the file is named by. Each missing link is named."""
    where = f"{profile}: --config={path}"
    directory, _, name = path.rpartition("/")
    mount = next((m for m in vals.get("extraVolumeMounts", []) if m["mountPath"].rstrip("/") == directory), None)
    if mount is None:
        raise SystemExit(f"{where}: no extraVolumeMounts entry mounts {directory}")
    volume = next((v for v in vals.get("extraVolumes", []) if v["name"] == mount["name"]), None)
    if volume is None:
        raise SystemExit(f"{where}: no extraVolumes entry is named {mount['name']}")
    if "configMap" not in volume:
        return volume, ""
    cm_name = volume["configMap"]["name"]
    found = [m for m in vals.get("extraManifests", []) + directory_manifests(PROFILE_APP[profile])
             if m.get("kind") == "ConfigMap" and m["metadata"]["name"] == cm_name]
    if len(found) != 1:
        raise SystemExit(f"{where}: {len(found)} ConfigMaps named {cm_name} among the chart's extraManifests and "
                         f"{PROFILE_APP[profile].name}'s directory sources, where one is expected")
    if name not in (found[0].get("data") or {}):
        raise SystemExit(f"{where}: the ConfigMap {cm_name} has no {name}")
    return volume, found[0]["data"][name]


def coc_mask_configmap() -> dict:
    """The otel-collector-coc-mask ConfigMap (#1332), as its directory source holds it."""
    return yaml.safe_load(COC_MASK_MANIFEST.read_text(encoding="utf-8"))


COC_MASK_MANIFEST = REPO / "gitops/otel-collector/coc-mask/configmap.yaml"
COC_MASK_KEY = "coc-mask.yaml"


def collector_config(profile: str, datadog_secret: bool, admin_secret: bool = True) -> dict:
    """The config the collector runs: relay.yaml, then each --config after it in turn, the gate's file among them.
    admin_secret matters on the attendee profile only: True is a pool of per-student orgs (dual shipping), False one
    org for the cluster and the instructor."""
    vals = helm_values(profile)
    config = vals["config"]
    for path in config_paths(vals):
        volume, text = mounted_file(profile, vals, path)
        if volume["name"] == GATE_VOLUME:
            layer = datadog_overlay(vals, admin_secret) if datadog_secret else {}
        else:
            layer = yaml.safe_load(text) or {}
        config = deep_merge(config, layer)
    return config
