# ABOUTME: Every place that names the deployed Kyverno agrees: the chart gitops/apps/kyverno.yaml pins, both
# ABOUTME: VERSIONS.lock lines, the Datadog version tag, the CLI version the policy test and run-e2e.sh demand,
# ABOUTME: and the working docs that state the deployed chart and app.
#
# Why (#491). The chart went to 3.9.1 (Kyverno v1.19.1) in #389 and nothing else moved: VERSIONS.lock still
# said v1.18.1 / chart 3.8.1 twice, the admission controller's tags.datadoghq.com/version said v1.18.1, and the
# CLI test demanded v1.19.0 as "the deployed engine". The CLI pin only means something if it is the version
# the cluster runs, so a bump that leaves one copy behind fails here, before any cluster is built.
#
# The working docs drifted the same way (#579): six weeks after 3.9.1 the build spec and the recreation spec still
# said chart 3.8.1 / app v1.18.1 and the stack walkthrough said 3.9.0 / v1.19.0. They are held here as kagent's
# are in test_kagent_version_pins.py.
#
# VERSIONS.lock is the record of which app version a chart installs; this test does not look it up. It holds
# the lock to the chart the Application pins, and every other copy to the lock's app version.
import pathlib, re, sys

import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
failures = []


def check(n, c, detail=""):
    print(f"  {'PASS' if c else 'FAIL'}  {n}" + (f"\n        {detail}" if (detail and not c) else ""))
    if not c:
        failures.append(n)


app = yaml.safe_load((REPO / "gitops/apps/kyverno.yaml").read_text())
chart = str(app["spec"]["source"]["targetRevision"])
values = app["spec"]["source"]["helm"]["valuesObject"]
dd_version = str(values["admissionController"]["podAnnotations"]["tags.datadoghq.com/version"])

# Two lines, two layouts: "app v1.19.1 / chart 3.9.1" and "chart 3.9.1   app v1.19.1".
lock_lines = [l for l in (REPO / "VERSIONS.lock").read_text().splitlines() if re.match(r"^kyverno\s", l)]
lock = []
for line in lock_lines:
    c = re.search(r"\bchart (\S+)", line)
    a = re.search(r"\bapp (v\S+)", line)
    lock.append((c.group(1) if c else None, a.group(1) if a else None))
check("VERSIONS.lock lists kyverno twice (component versions and IDP foundation)", len(lock) == 2, f"{lock_lines}")
check(f"every VERSIONS.lock kyverno line pins chart {chart}, the chart gitops/apps/kyverno.yaml deploys",
      lock and all(c == chart for c, _ in lock), f"{lock}")
apps = {a for _, a in lock}
check("the VERSIONS.lock kyverno lines name one app version", len(apps) == 1 and None not in apps, f"{lock}")
deployed = next(iter(apps)) if len(apps) == 1 else None

check(f"the admission controller's tags.datadoghq.com/version is {deployed}", dd_version == deployed,
      f"got {dd_version!r}")

cli_test = (REPO / "verify/test_kyverno_cel_policies.py").read_text()
want = re.search(r'^WANT_VERSION = "([^"]+)"', cli_test, re.M)
check(f"test_kyverno_cel_policies.py pins the CLI to {deployed}",
      want is not None and f"v{want.group(1)}" == deployed, f"got {want.group(1) if want else None!r}")


def other_versions(text):
    """Kyverno versions a text names other than the deployed one."""
    return sorted({v for v in re.findall(r"\b(v1\.\d+\.\d+)\b", text) if v != deployed})


def cli_lines(text):
    """The lines that tell a reader which kyverno CLI to install (the file's other versions are fixtures)."""
    return "\n".join(l for l in text.splitlines() if re.search(r"kyverno CLI|kyverno-cli|kyverno/releases", l))


install = cli_lines(cli_test)
check(f"test_kyverno_cel_policies.py's install instructions name only {deployed}",
      "releases/tag" in install and not other_versions(install), install)
e2e = cli_lines((REPO / "verify/run-e2e.sh").read_text())
check(f"run-e2e.sh's kyverno CLI message names only {deployed}",
      "releases/tag" in e2e and not other_versions(e2e), e2e)
readme = (REPO / "policies/README.md").read_text()
cli_ref = re.search(r"Kyverno (v\d+\.\d+\.\d+) CLI", readme)
check(f"policies/README.md names the {deployed} CLI", cli_ref is not None and cli_ref.group(1) == deployed,
      f"got {cli_ref.group(1) if cli_ref else None!r}")

print("== the working docs name the Kyverno we deploy ==")
# Each of these states the deployed Kyverno. decisions.md, the PRDs, UPGRADE-INVENTORY.md (a superseded dated
# inventory) and the research notes are records and are not checked.
CURRENT_DOCS = (
    "docs/BUILD-SPEC.md",
    "docs/MASTER-RECREATION-SPEC.md",
    "docs/STACK-WALKTHROUGH.md",
)
VERSION = re.compile(r"(\bfrom\s+`?)?\bv?(\d+\.\d+\.\d+)\b")


def kyverno_phrases(text):
    """Each mention of Kyverno up to the next table cell, list separator or comma, with the line it is on.

    The phrase is where a doc pins a version ("Kyverno app `v1.19.1` / chart `3.9.1`", "kyverno v1.19.1, falco
    ...", "kyverno chart 3.9.1 (app v1.19.1) |"); cutting at the separator keeps the next component's version out.
    """
    for i, line in enumerate(text.splitlines(), 1):
        for m in re.finditer(r"kyverno", line, re.I):
            yield i, re.split(r"[|;,]", line[m.end():], maxsplit=1)[0]


for rel in CURRENT_DOCS:
    phrases = list(kyverno_phrases((REPO / rel).read_text(encoding="utf-8")))
    named = [(i, [(h, v) for h, v in VERSION.findall(p)]) for i, p in phrases]
    check(f"{rel} names Kyverno app {deployed} and chart {chart} together",
          any({deployed.lstrip("v"), chart} <= {v for _, v in vs} for _, vs in named))
    # Kyverno's app is on the 1.x line and its chart on the 3.x line. A version after "from" is history.
    wrong = [(i, v) for i, vs in named for h, v in vs if not h and (
        (v.startswith("1.") and v != deployed.lstrip("v")) or (v.startswith("3.") and v != chart))]
    check(f"{rel} names no other Kyverno app or chart as current (found {wrong})", not wrong)

if failures:
    print(f"\nFAILED: {len(failures)} check(s)")
    sys.exit(1)
print("\nAll Kyverno version pin checks passed.")
