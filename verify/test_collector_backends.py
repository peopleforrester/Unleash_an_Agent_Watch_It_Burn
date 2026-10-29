# ABOUTME: Every exporter a profile's collector names has its backend in that profile's app list (#476),
# ABOUTME: with and without datadog-secret, and the burn overlay is values.yaml minus Tempo and Prometheus.
"""Why this exists (#476).

The burn profile installed otel-collector.yaml, values.yaml alone, whose metrics and traces pipelines export to
prometheusremotewrite and otlp_grpc/tempo. The burn profile lists neither prometheus.yaml nor tempo.yaml, so on
attackme every batch went to two endpoints with nothing behind them and was retried; only Datadog's copy
landed. Nothing caught it because every collector check read the instructor or attendee render, and no check
asked whether a sink the config names is installed on the profile that runs it.

This one does, for every profile of gitops/bootstrap (its values-<profile>.yaml app list, #609):

  - the profile lists exactly one collector Application, and collector_render.py knows how to render it;
  - every exporter in every pipeline of the collector the profile lists, with datadog-secret and without, is
    either an in-cluster sink whose Application the profile lists (and whose namespace the endpoint names) or
    a sink that needs nothing in the cluster. An exporter in neither table fails, so a new sink is placed;
  - the burn overlay changes the exporters lists and nothing else, and they are values.yaml's lists with the
    two absent sinks removed, in the same order, so a later change to values.yaml cannot leave burn behind.

Offline: reads the profile values files and the collector value files, nothing else.
"""
from __future__ import annotations

import pathlib
import sys

import yaml

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from bootstrap_chart import app_files, profiles as chart_profiles  # noqa: E402
from collector_render import APPS, PROFILE_APP, REPO, collector_config, datadog_overlay, helm_values  # noqa: E402

failures: list[str] = []


def check(name: str, cond: bool) -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        failures.append(name)


# Exporters whose backend runs in the cluster: the gitops/bootstrap/apps Application that installs it.
IN_CLUSTER = {"prometheusremotewrite": "prometheus.yaml", "otlp_grpc/tempo": "tempo.yaml"}
# Exporters that need nothing installed: Datadog is SaaS, debug writes to the collector's own log.
NO_BACKEND = {"datadog", "datadog/admin", "debug"}


def selected(profile: str) -> set[str]:
    """The gitops/bootstrap/apps files the profile's values file lists."""
    return app_files(profile)


def applications(f: str) -> list[dict]:
    """The Applications in a gitops/bootstrap/apps file; some files hold more than one document."""
    return [d for d in yaml.safe_load_all((APPS / f).read_text(encoding="utf-8"))
            if d and d.get("kind") == "Application"]


def is_collector_app(f: str) -> bool:
    return any(s.get("chart") == "opentelemetry-collector"
               for a in applications(f) for s in ([a["spec"]["source"]] if "source" in a["spec"] else [])
               + (a["spec"].get("sources") or []))


def app_namespace(f: str) -> str:
    (app,) = applications(f)
    return app["spec"]["destination"]["namespace"]


def pipeline_exporters(cfg: dict) -> set[str]:
    connectors = set((cfg.get("connectors") or {}).keys())
    return {e for p in ((cfg.get("service") or {}).get("pipelines") or {}).values()
            for e in p.get("exporters") or []} - connectors


RENDERS = {path.name: key for key, path in PROFILE_APP.items()}
profiles = chart_profiles()
check(f"there are profiles to check {profiles}", "burn" in profiles and len(profiles) > 1)

for profile in profiles:
    sel = selected(profile)
    print(f"== {profile}: the collector it installs and the sinks that collector names ==")
    apps = sorted(f for f in sel if is_collector_app(f))
    check(f"{profile} selects exactly one collector Application {apps}", len(apps) == 1)
    check(f"{profile}'s collector {apps} is one collector_render.py renders", len(apps) == 1 and apps[0] in RENDERS)
    if len(apps) != 1 or apps[0] not in RENDERS:
        continue
    collector = RENDERS[apps[0]]
    for secret in (False, True):
        cfg = collector_config(collector, datadog_secret=secret)
        label = "with datadog-secret" if secret else "without datadog-secret"
        for exp in sorted(pipeline_exporters(cfg)):
            if exp in NO_BACKEND:
                check(f"{profile} {label}: {exp} needs no in-cluster backend", True)
                continue
            app = IN_CLUSTER.get(exp)
            check(f"{profile} {label}: {exp} is a known sink (add it to IN_CLUSTER or NO_BACKEND)", app is not None)
            if app is None:
                continue
            check(f"{profile} {label}: {exp} has its backend {app} in the {profile} profile's list", app in sel)
            endpoint = (cfg["exporters"].get(exp) or {}).get("endpoint", "")
            check(f"{profile} {label}: {exp} points into {app}'s namespace ({endpoint})",
                  f".{app_namespace(app)}.svc.cluster.local:" in endpoint)

print("== burn: Datadog is the only sink, and the overlay is values.yaml minus the two it lacks ==")
burn_sel = selected("burn")
absent = {e for e, app in IN_CLUSTER.items() if app not in burn_sel}
check(f"burn installs neither Prometheus nor Tempo, the case this test exists for {sorted(absent)}",
      absent == {"prometheusremotewrite", "otlp_grpc/tempo"})
base, burn = helm_values("instructor"), helm_values("burn")
burn_file = yaml.safe_load((REPO / "gitops/otel-collector/values-burn.yaml").read_text(encoding="utf-8"))
check("values-burn.yaml overrides only config and the Datadog ConfigMap", set(burn_file) == {"config", "extraManifests"})
# Besides the exporters, burn adds one thing: the PII scrub at the end of the traces processors (#647), which
# verify/test_collector_pii_scrub.py holds in full.
SCRUB = "transform/scrub_pii"
burn_pipes = burn_file["config"]["service"]["pipelines"]
check("values-burn.yaml's config touches only the exporters lists, the traces processors and the PII scrub",
      burn_file["config"] == {"processors": {SCRUB: burn_file["config"]["processors"].get(SCRUB)},
                              "service": {"pipelines": {
          sig: {k: burn_pipes[sig][k] for k in (["exporters", "processors"] if sig == "traces" else ["exporters"])}
          for sig in burn_pipes}}})
bp, bbp = base["config"]["service"]["pipelines"], burn["config"]["service"]["pipelines"]
check("relay.yaml traces.processors on burn is values.yaml's with the PII scrub last, same order",
      bbp["traces"]["processors"] == bp["traces"]["processors"] + [SCRUB])
check("relay.yaml on burn has the same pipelines as values.yaml", set(bp) == set(bbp))
for sig in sorted(bp):
    check(f"relay.yaml {sig}.exporters on burn is values.yaml's without Tempo and Prometheus, same order",
          bbp[sig]["exporters"] == [e for e in bp[sig]["exporters"] if e not in absent])
ov, bov = datadog_overlay(base), datadog_overlay(burn)
check("the burn overlay's Datadog exporter and connector are the single-org overlay's",
      bov.get("exporters") == ov.get("exporters") and bov.get("connectors") == ov.get("connectors"))
ovp, bovp = ov["service"]["pipelines"], bov["service"]["pipelines"]
check("the burn overlay changes the same pipelines and lists as the single-org one",
      {s: set(p) for s, p in ovp.items()} == {s: set(p) for s, p in bovp.items()})
for sig in sorted(ovp):
    for kind in sorted(ovp[sig]):
        check(f"overlay {sig}.{kind} on burn is the single-org list without Tempo and Prometheus, same order",
              bovp[sig][kind] == [c for c in ovp[sig][kind] if c not in absent])
with_dd = collector_config("burn", datadog_secret=True)["service"]["pipelines"]
check("burn with datadog-secret still ships traces and metrics to Datadog",
      with_dd["traces"]["exporters"][0] == "datadog" and with_dd["metrics"]["exporters"][0] == "datadog")
check("everything else in the collector's values is the instructor collector's",
      {k: v for k, v in burn.items() if k not in burn_file} == {k: v for k, v in base.items() if k not in burn_file})

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All collector backend checks passed.")
