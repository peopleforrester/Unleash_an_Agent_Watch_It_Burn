# ABOUTME: Every place that names the deployed Argo CD, cert-manager and Istio agrees: the chart deploy-full-idp.sh and
# ABOUTME: the Applications pin, the VERSIONS.lock lines, the Datadog version labels, and the working docs.
#
# Why (#674). #389 moved argo-cd to chart 10.8.4 (Argo CD v3.5.2), cert-manager to v1.21.2 and Istio to 1.30.4, and
# VERSIONS.lock went on saying 9.6.0 / v3.4.4 and v1.20.2, with no Istio line at all. The recreation spec, the build
# spec and the stack walkthrough said the same old versions, and #661 set the Datadog version labels from them, so
# #662 had to put the labels right by hand. This holds those three the way test_kyverno_version_pins.py holds Kyverno.
#
# VERSIONS.lock is the record of which app version a chart installs; this test does not look it up. It holds the lock
# to the chart that is deployed, and every other copy to the lock's app version. cert-manager and Istio publish
# their charts at the app's own version, so for them chart and app are one value.
import pathlib, re, sys

import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
APPS = REPO / "gitops/bootstrap/apps"
failures = []


def check(n, c, detail=""):
    print(f"  {'PASS' if c else 'FAIL'}  {n}" + (f"\n        {detail}" if (detail and not c) else ""))
    if not c:
        failures.append(n)


def lock_pins(name):
    """(chart, app) of each VERSIONS.lock line for one component, in either layout the lock uses."""
    lines = [l for l in (REPO / "VERSIONS.lock").read_text(encoding="utf-8").splitlines()
             if re.match(rf"^{name}\s", l)]
    pins = []
    for line in lines:
        c = re.search(r"\bchart (\S+)", line)
        a = re.search(r"\bapp (\S+)", line)
        pins.append((c.group(1) if c else None, a.group(1) if a else None))
    return pins


def lock_app(label, pins, count, chart):
    """Check the lock lines pin the deployed chart and one app version, and return that app version."""
    check(f"VERSIONS.lock lists {label} {count} time(s)", len(pins) == count, f"{pins}")
    check(f"every VERSIONS.lock {label} line pins chart {chart}, the chart that is deployed",
          bool(pins) and all(c == chart for c, _ in pins), f"{pins}")
    apps = {a for _, a in pins}
    check(f"the VERSIONS.lock {label} lines name one app version", len(apps) == 1 and None not in apps, f"{pins}")
    return next(iter(apps)) if len(apps) == 1 else None


print("== Argo CD: deploy-full-idp.sh, VERSIONS.lock, argocd-values.yaml ==")
deploy = (REPO / "infra/deploy-full-idp.sh").read_text(encoding="utf-8")
m = re.search(r"helm upgrade --install argocd argo/argo-cd --version (\S+)", deploy)
check("deploy-full-idp.sh installs argo/argo-cd at a pinned --version", m is not None)
argo_chart = m.group(1) if m else None
# Two lines: "argocd                 chart X / app Y" (component versions) and "argo-cd  chart X  app Y" (IDP foundation).
argo_app = lock_app("argocd/argo-cd", lock_pins("argocd") + lock_pins("argo-cd"), 2, argo_chart)
logged = re.search(r'log "\[2\] ArgoCD \(chart (\S+) / app (\S+)\)"', deploy)
check(f"deploy-full-idp.sh's install step logs chart {argo_chart} / app {argo_app}",
      logged is not None and logged.groups() == (argo_chart, argo_app),
      f"got {logged.groups() if logged else None!r}")
argo_values_text = (REPO / "infra/argocd-values.yaml").read_text(encoding="utf-8")
argo_values = yaml.safe_load(argo_values_text)
argo_dd = argo_values["server"]["podLabels"]["tags.datadoghq.com/version"]
check(f"argocd-server's tags.datadoghq.com/version is {argo_app}", argo_dd == argo_app, f"got {argo_dd!r}")
named = re.search(r"The version is argo-cd (\S+)'s", argo_values_text)
check(f"argocd-values.yaml's note names argo-cd {argo_chart} as the chart the label's version comes from",
      named is not None and named.group(1) == argo_chart, f"got {named.group(1) if named else None!r}")

print("== cert-manager: the Application, VERSIONS.lock ==")
cm_app = yaml.safe_load((APPS / "cert-manager.yaml").read_text(encoding="utf-8"))
cm_chart = str(cm_app["spec"]["source"]["targetRevision"])
cm = lock_app("cert-manager", lock_pins("cert-manager"), 1, cm_chart)
check(f"cert-manager's VERSIONS.lock app is its chart {cm_chart} (jetstack charts are versioned with the app)",
      cm == cm_chart, f"got {cm!r}")
cm_dd = cm_app["spec"]["source"]["helm"]["valuesObject"]["podLabels"]["tags.datadoghq.com/version"]
check(f"the controller's tags.datadoghq.com/version is {cm}", cm_dd == cm, f"got {cm_dd!r}")

print("== Istio: the four chart Applications, VERSIONS.lock, test_mesh.py ==")
istio_text = (APPS / "istio.yaml").read_text(encoding="utf-8")
istio_docs = {d["metadata"]["name"]: d for d in yaml.safe_load_all(istio_text) if d}
revs = {n: str(d["spec"]["source"]["targetRevision"]) for n, d in istio_docs.items() if d["spec"]["source"].get("chart")}
check("istio.yaml pins base, cni, istiod and ztunnel", sorted(revs) == ["istio-base", "istio-cni", "istiod", "ztunnel"],
      f"{sorted(revs)}")
check("the four Istio charts are one version", len(set(revs.values())) == 1, f"{revs}")
istio_chart = next(iter(set(revs.values()))) if len(set(revs.values())) == 1 else None
istio = lock_app("istio", lock_pins("istio"), 1, istio_chart)
check(f"Istio's VERSIONS.lock app is its chart {istio_chart} (istio-release charts are versioned with the app)",
      istio == istio_chart, f"got {istio!r}")
pilot = istio_docs["istiod"]["spec"]["source"]["helm"]["valuesObject"]["pilot"]["podLabels"]
ztunnel = istio_docs["ztunnel"]["spec"]["source"]["helm"]["valuesObject"]["podLabels"]
for who, labels in (("istiod", pilot), ("ztunnel", ztunnel)):
    check(f"{who}'s tags.datadoghq.com/version is {istio}", labels.get("tags.datadoghq.com/version") == istio,
          f"got {labels.get('tags.datadoghq.com/version')!r}")
header = re.search(r"^# ABOUTME: .*Pinned (\d+\.\d+\.\d+)\.", istio_text, re.M)
check(f"istio.yaml's header says it is pinned to {istio}", header is not None and header.group(1) == istio,
      f"got {header.group(1) if header else None!r}")
mesh = re.search(r'^ISTIO_VERSION = "([^"]+)"', (REPO / "verify/test_mesh.py").read_text(encoding="utf-8"), re.M)
check(f"test_mesh.py's ISTIO_VERSION is {istio}", mesh is not None and mesh.group(1) == istio,
      f"got {mesh.group(1) if mesh else None!r}")

print("== the working docs name the Argo CD, cert-manager and Istio we deploy ==")
# Each of these states the deployed versions. decisions.md, the PRDs, PROJECT_STATE.md, UPGRADE-INVENTORY.md (a
# superseded dated inventory) and the research notes are records and are not checked.
# Not inside a longer dotted number: the recreation spec's "argocd-managed-app ... `CONNECT 10.0.16.75`" is an IP.
VERSION = re.compile(r"(\bfrom\s+`?)?(?<![\w.])v?(\d+\.\d+\.\d+)(?!\d|\.\d)")


def strip(v):
    return v.lstrip("v") if v else v


# (component, the words a doc names it by, where its phrase ends, the versions it may name, what each doc must name).
# A phrase runs from the name to the next table cell or list separator, which keeps the next component's version
# out ("istio 1.30.4 / kyverno chart 3.9.1" is two components, so Istio's phrase also ends at a slash; Argo CD's
# does not, because "Argo CD `v3.5.2` / chart `10.8.4`" is one).
COMPONENTS = (
    ("Argo CD", r"argo[ -]?cd", r"[|;,]", {strip(argo_app), argo_chart}, {
        "docs/BUILD-SPEC.md": {strip(argo_app), argo_chart},
        "docs/MASTER-RECREATION-SPEC.md": {strip(argo_app), argo_chart},
        "docs/STACK-WALKTHROUGH.md": {strip(argo_app)},
    }),
    ("cert-manager", r"cert-manager", r"[|;,]", {strip(cm)}, {
        "docs/BUILD-SPEC.md": {strip(cm)},
        "docs/MASTER-RECREATION-SPEC.md": {strip(cm)},
        "docs/STACK-WALKTHROUGH.md": set(),
    }),
    ("Istio", r"istio|ztunnel", r"[|;,/]", {istio}, {
        "docs/BUILD-SPEC.md": {istio},
        "docs/MASTER-RECREATION-SPEC.md": {istio},
        "docs/STACK-WALKTHROUGH.md": {istio},
    }),
)


def phrases(text, name, cut):
    """Each mention of a component up to where its phrase ends, with the line it is on."""
    for i, line in enumerate(text.splitlines(), 1):
        for m in re.finditer(name, line, re.I):
            yield i, re.split(cut, line[m.end():], maxsplit=1)[0]


for label, name, cut, allowed, docs in COMPONENTS:
    for rel, want in docs.items():
        named = [(i, VERSION.findall(p)) for i, p in phrases((REPO / rel).read_text(encoding="utf-8"), name, cut)]
        if want:
            check(f"{rel} names {label} {' and '.join(sorted(map(str, want)))}",
                  any(want <= {v for _, v in vs} for _, vs in named))
        # A version after "from" is history; any other version in the component's phrase claims to be current.
        wrong = [(i, v) for i, vs in named for h, v in vs if not h and v not in allowed]
        check(f"{rel} names no other {label} version as current (found {wrong})", not wrong)

if failures:
    print(f"\nFAILED: {len(failures)} check(s)")
    sys.exit(1)
print("\nAll Argo CD, cert-manager and Istio version pin checks passed.")
