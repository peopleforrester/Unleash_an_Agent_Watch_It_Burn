# ABOUTME: Render gate for #500: with no datadog-secret, every collector and falcosidekick container env resolves
# ABOUTME: and the trace pipeline still exports to Tempo; with the secret, the same profile ships to Datadog again.
"""Why this exists (#500).

The admin profile has to come up before a Datadog org pool exists (#454), and it could not. The collector read
DD_API_KEY with a non-optional secretKeyRef and named the datadog exporter in both pipelines, so with no
datadog-secret the pod never started and Tempo and Prometheus, the fallback the run-of-show names for segment 6,
died with the primary. falcosidekick had the same reference, so Falco's CRITICAL events stopped reaching Talon.

The fix splits the collector config in two. relay.yaml (values.yaml `config`) is Datadog-free; the Datadog half
is the otel-collector-datadog ConfigMap, which the datadog-gate init container copies into a second --config
only when datadog-secret exists. This checks the pieces offline:

  - without the secret: no container reference can block a pod start, and the config the collector runs is
    valid and exports traces to Tempo and metrics to Prometheus, with no Datadog component in it;
  - the gate itself, run with sh in both branches, writes what the two configs below assume;
  - with the secret: the merged config is the Datadog config the collector ran before #500, and the overlay's
    lists cannot drift from relay.yaml's, because the collector replaces lists rather than merging them;
  - attendee clusters still dual-ship and still fail loudly without their secrets, and name no Tempo exporter,
    because the attendee profile installs no Tempo (#475).

The merged-config validity check is a reference check, not the collector's own validator. Both configs were also
run through `otelcol-contrib validate` 0.160.0 (this chart's appVersion) against the real chart render when this
was written: VALID without a key, VALID with one, VALID for attendee with both. That needs the binary and stays
out of the offline suite.
"""
from __future__ import annotations

import fnmatch
import os
import pathlib
import re
import subprocess
import sys
import tempfile

import yaml

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from collector_render import REPO, collector_config, datadog_overlay, deep_merge, helm_values  # noqa: E402

failures: list[str] = []


def check(name: str, cond: bool) -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        failures.append(name)


def reference_problems(cfg: dict) -> list[str]:
    """What the collector would refuse at start: a pipeline naming a component that is not defined, or a
    connector used on only one side."""
    out = []
    connectors = set((cfg.get("connectors") or {}).keys())
    defined = {"receivers": set((cfg.get("receivers") or {}).keys()) | connectors,
               "processors": set((cfg.get("processors") or {}).keys()),
               "exporters": set((cfg.get("exporters") or {}).keys()) | connectors}
    as_exporter, as_receiver = set(), set()
    for pname, p in ((cfg.get("service") or {}).get("pipelines") or {}).items():
        for kind in ("receivers", "processors", "exporters"):
            for c in p.get(kind) or []:
                if c not in defined[kind]:
                    out.append(f"{pname}.{kind} names undefined {c}")
        as_exporter |= set(p.get("exporters") or []) & connectors
        as_receiver |= set(p.get("receivers") or []) & connectors
    out += [f"connector {c} is used on one side only" for c in sorted(as_exporter ^ as_receiver)]
    return out


def env_refs(cfg: dict) -> set[str]:
    return set(re.findall(r"\$\{env:([A-Za-z_][A-Za-z0-9_]*)", yaml.safe_dump(cfg)))


def blocking_refs(envs: list[dict], absent: set[str]) -> list[str]:
    """Env entries that stop the container starting when a secret in `absent` does not exist."""
    out = []
    for e in envs or []:
        ref = (e.get("valueFrom") or {}).get("secretKeyRef")
        if ref and ref.get("name") in absent and ref.get("optional") is not True:
            out.append(f"{e['name']} <- secret {ref['name']}")
    return out


# What deploy-full-idp.sh does NOT write when it has no Datadog keys: datadog-secret is skipped, and
# datadog-cluster-identity.sh deletes datadog-admin-secret when there is no distinct admin key.
ABSENT = {"datadog-secret", "datadog-admin-secret"}
# Env the chart itself sets on the collector container (templates/_pod.tpl, chart 0.173.1).
CHART_ENV = {"MY_POD_IP", "OTEL_K8S_NODE_NAME", "OTEL_K8S_NODE_IP", "OTEL_K8S_NAMESPACE", "OTEL_K8S_POD_NAME",
             "OTEL_K8S_POD_IP", "K8S_NODE_NAME", "K8S_NODE_IP", "GOMEMLIMIT"}

vals = helm_values("instructor")
inits = {c["name"]: c for c in vals.get("initContainers") or []}
gate = inits.get("datadog-gate", {})

print("== the admin profile installs the instructor collector and keeps Datadog in the profile ==")
admin = yaml.safe_load((REPO / "gitops/bootstrap/admin/app-of-apps-admin.yaml").read_text(encoding="utf-8"))
excl = next(s for s in admin["spec"]["sources"] if s.get("path") == "gitops/apps")["directory"].get("exclude", "")
m = re.fullmatch(r"\{(.*)\}(.*)", excl)
patterns = [p + m.group(2) for p in m.group(1).split(",")] if m else [excl]
excluded = lambda f: any(fnmatch.fnmatch(f, p) for p in patterns if p)  # noqa: E731
check("admin takes otel-collector.yaml, not the attendee overlay",
      excluded("otel-collector-attendee.yaml") and not excluded("otel-collector.yaml"))
check("admin keeps falcosidekick and the Datadog apps (the secret switches Datadog, not the profile)",
      not any(excluded(f) for f in ("falcosidekick.yaml", "datadog-operator.yaml", "datadog-agent-cr.yaml")))

print("== without datadog-secret: no reference can stop the collector or falcosidekick starting ==")
check(f"collector container env: no blocking secret reference {blocking_refs(vals.get('extraEnvs'), ABSENT)}",
      not blocking_refs(vals.get("extraEnvs"), ABSENT))
for name, c in sorted(inits.items()):
    check(f"init container {name}: no blocking secret reference {blocking_refs(c.get('env'), ABSENT)}",
          not blocking_refs(c.get("env"), ABSENT))
check("no envFrom on the collector that could name a missing secret", not vals.get("extraEnvsFrom"))
check("no secret volume on the collector", not any("secret" in v for v in vals.get("extraVolumes") or []))
fsk_app = yaml.safe_load((REPO / "gitops/apps/falcosidekick.yaml").read_text(encoding="utf-8"))
fsk = fsk_app["spec"]["source"]["helm"]["valuesObject"]
check(f"falcosidekick env: no blocking secret reference {blocking_refs(fsk['config'].get('extraEnv'), ABSENT)}",
      not blocking_refs(fsk["config"].get("extraEnv"), ABSENT))
# The chart's own envFrom secret carries config.datadog.apikey, "" by default, and falcosidekick enables the
# Datadog output only on a non-empty key. A key set here would switch the output on with no secret at all.
check("falcosidekick sets no inline Datadog apikey, so a missing secret leaves the output off",
      "apikey" not in (fsk["config"].get("datadog") or {}))
check("falcosidekick still feeds Talon without Datadog", "talon.falco.svc" in fsk["config"]["talon"]["address"])

print("== without datadog-secret: the collector runs a valid config that ships to Tempo and Prometheus ==")
bare = collector_config("instructor", datadog_secret=False)
pipes = bare["service"]["pipelines"]
check(f"every pipeline names defined components {reference_problems(bare)}", not reference_problems(bare))
check("no Datadog exporter or connector is defined",
      not any(k.startswith("datadog") for k in {**(bare.get("exporters") or {}), **(bare.get("connectors") or {})}))
check("no Datadog component in any pipeline",
      not any(c.startswith("datadog") for p in pipes.values() for k in ("receivers", "exporters") for c in p.get(k) or []))
check("the trace pipeline exports to Tempo", "otlp_grpc/tempo" in pipes["traces"]["exporters"])
check("the Tempo exporter points at the Tempo service on OTLP gRPC",
      bare["exporters"]["otlp_grpc/tempo"]["endpoint"] == "tempo.monitoring.svc.cluster.local:4317")
check("the metrics pipeline exports to Prometheus", "prometheusremotewrite" in pipes["metrics"]["exporters"])
check("span_metrics still turns spans into metrics", "span_metrics" in pipes["traces"]["exporters"]
      and "span_metrics" in pipes["metrics"]["receivers"])
refs = env_refs(bare)
check(f"every env var the config reads is set on the container {sorted(refs)}",
      refs <= {e["name"] for e in vals.get("extraEnvs") or []} | CHART_ENV)
check("the config reads no Datadog env var", not any(r.startswith("DD_") for r in refs))
# The chart renames otlp/otlphttp exporters in relay.yaml and not in the overlay; an old name would make the
# two files disagree about what the Tempo exporter is called, which is how the first cut of this broke.
old = [k for k in (bare.get("exporters") or {}) if re.match(r"^(otlp|otlphttp)(/|$)", k)]
check(f"no exporter uses a name the chart rewrites {old}", not old)

print("== the gate, run with sh: what it writes in each branch ==")
args = gate.get("args") or []
check("datadog-gate runs one sh script", gate.get("command") == ["sh", "-c"] and len(args) == 1)
check("datadog-gate is a digest-pinned image", "@sha256:" in gate.get("image", ""))
mounts = {v["name"]: v["mountPath"] for v in gate.get("volumeMounts") or []}
main_mounts = {v["name"]: v["mountPath"] for v in vals.get("extraVolumeMounts") or []}
cfg_args = [a.split("=", 1)[1] for a in (vals.get("command") or {}).get("extraArgs") or [] if a.startswith("--config=")]
check("the collector loads a second config from the gate's volume",
      len(cfg_args) == 1 and "datadog-gate" in main_mounts and cfg_args[0].startswith(main_mounts["datadog-gate"] + "/"))
check("the gate writes to that same volume and reads the overlay ConfigMap",
      mounts.get("datadog-gate") == main_mounts.get("datadog-gate") and "datadog-overlay" in mounts)
written: dict[bool, dict] = {}
if len(args) == 1 and len(cfg_args) == 1 and {"datadog-gate", "datadog-overlay"} <= set(mounts):
    overlay_text = yaml.safe_dump(datadog_overlay(vals))
    for with_key in (False, True):
        with tempfile.TemporaryDirectory() as tmp:
            ov, out = pathlib.Path(tmp, "overlay"), pathlib.Path(tmp, "gate")
            ov.mkdir()
            out.mkdir()
            (ov / "datadog.yaml").write_text(overlay_text, encoding="utf-8")
            script = args[0].replace(mounts["datadog-overlay"], str(ov)).replace(mounts["datadog-gate"], str(out))
            env = {k: v for k, v in os.environ.items() if k != "DD_API_KEY"}
            if with_key:
                env["DD_API_KEY"] = "not-a-real-key"
            r = subprocess.run(["sh", "-c", script], env=env, capture_output=True, text=True)
            target = out / pathlib.Path(cfg_args[0]).name
            label = "with datadog-secret" if with_key else "without datadog-secret"
            check(f"{label}: the gate exits 0 and writes the file the collector loads", r.returncode == 0 and target.exists())
            written[with_key] = (yaml.safe_load(target.read_text(encoding="utf-8")) or {}) if target.exists() else {"missing": True}
            check(f"{label}: it says in its log which way it went",
                  ("ON" in r.stdout) if with_key else ("OFF" in r.stdout and "Tempo" in r.stdout))
    check("without the secret it writes an empty config", written.get(False) == {})
    check("with the secret it writes the Datadog overlay", written.get(True) == datadog_overlay(vals))
check("the gate reads DD_API_KEY from datadog-secret, optionally",
      any(((e.get("valueFrom") or {}).get("secretKeyRef") or {}).get("name") == "datadog-secret" for e in gate.get("env") or []))

print("== with datadog-secret: the same profile ships to Datadog as it did before #500 ==")
full = deep_merge(vals["config"], written.get(True, {}))
fp = full["service"]["pipelines"]
check(f"every pipeline names defined components {reference_problems(full)}", not reference_problems(full))
check("Datadog is the primary traces exporter and Tempo stays beside it",
      fp["traces"]["exporters"][:2] == ["datadog", "otlp_grpc/tempo"])
check("Datadog is the primary metrics exporter and Prometheus stays beside it",
      fp["metrics"]["exporters"][:2] == ["datadog", "prometheusremotewrite"])
check("the APM-stats connector is wired both ways",
      "datadog/connector" in fp["traces"]["exporters"] and "datadog/connector" in fp["metrics"]["receivers"])
check("the Datadog key is an env reference, never a literal", full["exporters"]["datadog"]["api"]["key"] == "${env:DD_API_KEY}")
check("DD_API_KEY and DD_SITE are set on the collector container",
      {"DD_API_KEY", "DD_SITE"} <= {e["name"] for e in vals.get("extraEnvs") or []})
ov = datadog_overlay(vals)
ovp = ov["service"]["pipelines"]
check("the overlay leaves every processors list to relay.yaml",
      not any("processors" in p for p in ovp.values()) and "processors" not in ov)
for sig, kind in (("metrics", "receivers"), ("metrics", "exporters"), ("traces", "exporters")):
    stripped = [c for c in ovp[sig][kind] if not c.startswith("datadog")]
    check(f"overlay {sig}.{kind} is relay.yaml's list plus Datadog, in the same order",
          stripped == vals["config"]["service"]["pipelines"][sig][kind])
check("the overlay changes no pipeline relay.yaml does not have", set(ovp) <= set(vals["config"]["service"]["pipelines"]))
check("an overlay change rolls the collector (checksum annotation over extraManifests)",
      "extraManifests" in str((vals.get("podAnnotations") or {}).get("checksum/datadog-overlay", ""))
      and "sha256sum" in str((vals.get("podAnnotations") or {}).get("checksum/datadog-overlay", "")))

print("== attendee clusters: still dual-ship, still fail loudly without their secrets ==")
att_vals = helm_values("attendee")
att_ov = datadog_overlay(att_vals)
att = collector_config("attendee", datadog_secret=True)
check(f"attendee config with both secrets names defined components {reference_problems(att)}", not reference_problems(att))
# The attendee profile installs no Tempo (#475), so no attendee trace list may name it: neither the merged
# config, nor relay.yaml's own list (what would run if the overlay were empty), nor the overlay's.
att_relay = att_vals["config"]["service"]["pipelines"]
check("attendee drops Tempo from the traces it runs with both secrets",
      "otlp_grpc/tempo" not in att["service"]["pipelines"]["traces"]["exporters"])
check("attendee drops Tempo from relay.yaml's traces list too", "otlp_grpc/tempo" not in att_relay["traces"]["exporters"])
check("attendee relay.yaml still turns spans into metrics", "span_metrics" in att_relay["traces"]["exporters"])
check("attendee still ships traces to both Datadog orgs",
      att["service"]["pipelines"]["traces"]["exporters"][:2] == ["datadog", "datadog/admin"])
check("the dual overlay's datadog exporter and connector are the single-org overlay's",
      att_ov["exporters"]["datadog"] == ov["exporters"]["datadog"] and att_ov["connectors"] == ov["connectors"])
for sig, kind in (("metrics", "receivers"), ("metrics", "exporters"), ("traces", "exporters")):
    want = []
    for c in ovp[sig][kind]:
        if c == "otlp_grpc/tempo":
            continue
        want += [c, "datadog/admin"] if c == "datadog" else [c]
    check(f"dual {sig}.{kind} is the single-org list without Tempo, with datadog/admin after the student's org",
          att_ov["service"]["pipelines"][sig][kind] == want)
    check(f"dual {sig}.{kind} is attendee relay.yaml's list plus both Datadog orgs, in the same order",
          [c for c in att_ov["service"]["pipelines"][sig][kind] if not c.startswith("datadog")] == att_relay[sig][kind])
att_env = {e["name"]: e for e in att_vals.get("extraEnvs") or []}
for key in ("DD_API_KEY", "DD_ADMIN_API_KEY"):
    ref = (att_env.get(key, {}).get("valueFrom") or {}).get("secretKeyRef") or {}
    check(f"attendee {key} stays non-optional (a pool cluster without it is a bootstrap bug)",
          bool(ref) and ref.get("optional") is not True)

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All no-Datadog collector checks passed.")
