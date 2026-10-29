# ABOUTME: Every place that names the deployed OpenTelemetry Collector agrees: the chart and image the three
# ABOUTME: gitops/bootstrap/apps/otel-collector*.yaml files pin, both VERSIONS.lock lines, and the working docs.
#
# Why (#666). The collector Applications moved to chart 0.173.1 with the mirrored otelcol-contrib image
# 0.160.0-5b66b0dc6921 and VERSIONS.lock went on saying chart 0.158.2 / app 0.153.0 on both of its lines, as did
# the build spec and the recreation spec. #647 then had to hold the otelcol-contrib pin in e2e-tools.lock to the app
# files' image tag, because the lock that calls itself authoritative was wrong. This holds the lock to the app files
# the way test_kyverno_version_pins.py does for Kyverno.
#
# The app version is the image tag's version: lab-platform's mirror tags each copy <version>-<digest prefix>.
# test_e2e_tools_tier.py holds e2e-tools.lock's otelcol-contrib to that same tag; this holds the CHART and
# OTELCOL_VERSION constants test_lab_pipeline_collector.py runs the real collector against.
import pathlib, re, sys

import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
APPS = REPO / "gitops/bootstrap/apps"
failures = []


def check(n, c, detail=""):
    print(f"  {'PASS' if c else 'FAIL'}  {n}" + (f"\n        {detail}" if (detail and not c) else ""))
    if not c:
        failures.append(n)


def collector_source(path):
    """The opentelemetry-collector chart source of one Application (its other source is the git value files)."""
    sources = yaml.safe_load(path.read_text(encoding="utf-8"))["spec"]["sources"]
    return next(s for s in sources if s.get("chart") == "opentelemetry-collector")


print("== the three collector Applications run one chart and one image ==")
files = sorted(APPS.glob("otel-collector*.yaml"))
check("there are three collector Applications (instructor, attendee, burn)",
      [f.name for f in files] == ["otel-collector-attendee.yaml", "otel-collector-burn.yaml", "otel-collector.yaml"],
      f"{[f.name for f in files]}")
pins = {}
for f in files:
    src = collector_source(f)
    pins[f.name] = (str(src["targetRevision"]), str(src["helm"]["valuesObject"]["image"]["tag"]))
charts = {c for c, _ in pins.values()}
tags = {t for _, t in pins.values()}
check("every collector Application pins the same chart", len(charts) == 1, f"{pins}")
check("every collector Application runs the same image tag", len(tags) == 1, f"{pins}")
chart = next(iter(charts)) if len(charts) == 1 else None
tag = next(iter(tags)) if len(tags) == 1 else ""
m = re.fullmatch(r"(\d+\.\d+\.\d+)-[0-9a-f]{12}", tag)
check(f"the image tag is the mirror's <version>-<digest prefix> ({tag!r})", m is not None)
app = m.group(1) if m else None

print("== VERSIONS.lock records the collector we deploy ==")
# Two lines, one layout each: "otel-collector         chart X / app Y" and "opentelemetry-collector chart X    app Y".
lock_lines = [l for l in (REPO / "VERSIONS.lock").read_text(encoding="utf-8").splitlines()
              if re.match(r"^(otel-collector|opentelemetry-collector)\s", l)]
lock = []
for line in lock_lines:
    c = re.search(r"\bchart (\S+)", line)
    a = re.search(r"\bapp (\S+)", line)
    lock.append((c.group(1) if c else None, a.group(1) if a else None))
check("VERSIONS.lock lists the collector twice (component versions and IDP foundation)", len(lock) == 2,
      f"{lock_lines}")
check(f"every VERSIONS.lock collector line pins chart {chart}, the chart the Applications deploy",
      bool(lock) and all(c == chart for c, _ in lock), f"{lock}")
check(f"every VERSIONS.lock collector line pins app {app}, the image the Applications run",
      bool(lock) and all(a == app for _, a in lock), f"{lock}")

print("== the E2E collector test names the deployed chart ==")
lab = (REPO / "verify/test_lab_pipeline_collector.py").read_text(encoding="utf-8")
want_chart = re.search(r'^CHART = "([^"]+)"', lab, re.M)
want_app = re.search(r'^OTELCOL_VERSION = "([^"]+)"', lab, re.M)
check(f"test_lab_pipeline_collector.py's CHART is {chart}", bool(want_chart) and want_chart.group(1) == chart,
      f"got {want_chart.group(1) if want_chart else None!r}")
check(f"test_lab_pipeline_collector.py's OTELCOL_VERSION is {app}", bool(want_app) and want_app.group(1) == app,
      f"got {want_app.group(1) if want_app else None!r}")

print("== the working docs name the collector we deploy ==")
# Each of these states the deployed collector. decisions.md, the PRDs, UPGRADE-INVENTORY.md (a superseded dated
# inventory) and PROJECT_STATE.md are records and are not checked.
CURRENT_DOCS = (
    "docs/BUILD-SPEC.md",
    "docs/MASTER-RECREATION-SPEC.md",
)
VERSION = re.compile(r"(\bfrom\s+`?)?\bv?(\d+\.\d+\.\d+)\b")


def collector_phrases(text):
    """Each mention of the OTel Collector up to the next table cell, list separator or closing parenthesis.

    The phrase is where a doc pins a version ("OTel Collector chart `0.173.1` / app `0.160.0`;", "otel-collector
    chart 0.173.1 (app 0.160.0) |", "OTel Collector (Helm 0.173.1, contrib 0.160.0 daemonset, ..."); the separator
    keeps the next component's version out. "OTel Operator" is a different chart and is not matched.
    """
    for i, line in enumerate(text.splitlines(), 1):
        for m in re.finditer(r"otel[ -]collector|opentelemetry-collector", line, re.I):
            yield i, re.split(r"[|;]|\bns\b", line[m.end():], maxsplit=1)[0]


for rel in CURRENT_DOCS:
    named = [(i, VERSION.findall(p)) for i, p in collector_phrases((REPO / rel).read_text(encoding="utf-8"))]
    check(f"{rel} names the collector's chart {chart} and app {app} together",
          any({chart, app} <= {v for _, v in vs} for _, vs in named))
    # A version after "from" is history; any other version in a collector phrase claims to be the current one.
    wrong = [(i, v) for i, vs in named for h, v in vs if not h and v not in (chart, app)]
    check(f"{rel} names no other collector chart or app as current (found {wrong})", not wrong)

if failures:
    print(f"\nFAILED: {len(failures)} check(s)")
    sys.exit(1)
print("\nAll OpenTelemetry Collector version pin checks passed.")
