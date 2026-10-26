# ABOUTME: Static gate for #609: one root chart, gitops/bootstrap, taking the pinned commit as `revision`, four
# ABOUTME: explicit profile lists, no self-source and no repository credential, as lab-platform.yaml presents it.
#
# Why. lab-platform (peopleforrester/lab-platform#190) builds an event's clusters from this repo at one pinned
# commit: it reads lab-platform.yaml there, creates one root Application per cluster, lab-bootstrap, sourcing
# gitops/bootstrap with values-<profile>.yaml and revision=<commit>, then fails a cluster on any Application whose
# Unleashed source is at another revision. Before #609 there were four roots, each following staging, each listing
# its own directory as a second source (#253) and selecting apps by brace globs that matched files nobody chose;
# deploy-full-idp.sh wrote the operator's `gh auth token` onto every cluster as the witb-repo Secret.
#
# This holds the shape offline. test_bootstrap_chart_render.py renders it with the pinned Helm.
import pathlib
import re
import sys

import yaml

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from bootstrap_chart import (APPS, CHART, CONFIG, REPO, REPO_URL, REVISION, TEMPLATES, app_names,  # noqa: E402
                             deploy_root, deploys, profiles, values_path)

failures = []


def check(n, c):
    print(f"  {'PASS' if c else 'FAIL'}  {n}")
    if not c:
        failures.append(n)


def sources(app: dict) -> list[dict]:
    sp = app.get("spec") or {}
    return ([sp["source"]] if "source" in sp else []) + list(sp.get("sources") or [])


print("== lab-platform.yaml presents the chart (lab-platform docs/talk-config.md section 3) ==")
text = CONFIG.read_text(encoding="utf-8")
cfg = yaml.safe_load(text)
check("lab-platform.yaml is at the repo root", CONFIG.parent == REPO)
check("it holds exactly format, labs, branch and bootstrap (the parser refuses any other field)",
      list(cfg) == ["format", "labs", "branch", "bootstrap"])
check("format is lab-platform/v1", cfg.get("format") == "lab-platform/v1")
check("it is the content of the burn lab", cfg.get("labs") == ["burn"])
check("pinned commits must be on staging", cfg.get("branch") == "staging")
boot = cfg.get("bootstrap") or {}
check("bootstrap holds revision_parameter and profiles only", list(boot) == ["revision_parameter", "profiles"])
check("the revision parameter is `revision`", boot.get("revision_parameter") == "revision")
check("the profiles are attendee, burn, admin and full", profiles() == ["attendee", "burn", "admin", "full"])
for p in boot.get("profiles") or []:
    check(f"profile {p.get('name')}: root gitops/bootstrap, values values-{p.get('name')}.yaml",
          p == {"name": p.get("name"), "root": "gitops/bootstrap", "values": f"values-{p.get('name')}.yaml"})
# The strict subset: block style only and every value text, so a flow collection or a non-string scalar fails.
body = [ln.split("#", 1)[0] for ln in text.splitlines()]
check("block style only: no flow collection", not any(re.search(r"[\[\]{}]", ln) for ln in body))


def scalars(node):
    if isinstance(node, dict):
        for k, v in node.items():
            yield k
            yield from scalars(v)
    elif isinstance(node, list):
        for v in node:
            yield from scalars(v)
    else:
        yield node


check("every value is text", all(isinstance(s, str) for s in scalars(cfg)))

print("== gitops/bootstrap is the one root chart ==")
chart = yaml.safe_load((CHART / "Chart.yaml").read_text(encoding="utf-8"))
check("gitops/bootstrap/Chart.yaml is a Helm v2 application chart",
      chart.get("apiVersion") == "v2" and chart.get("type") == "application" and bool(chart.get("version")))
check("values.yaml shares only an empty revision, so a render without the parameter fails",
      yaml.safe_load((CHART / "values.yaml").read_text(encoding="utf-8")) == {"revision": ""})
check("the chart holds apps/, templates/ and no other directory (the four old root directories are gone)",
      sorted(d.name for d in CHART.iterdir() if d.is_dir()) == ["apps", "templates"])
check("gitops/apps is gone: its files are the chart's apps/", not (REPO / "gitops/apps").exists())
check("the templates are apps.yaml and ghcr-kagent-oci.yaml",
      sorted(p.name for p in TEMPLATES.iterdir()) == ["apps.yaml", "ghcr-kagent-oci.yaml"])
tpl = (TEMPLATES / "apps.yaml").read_text(encoding="utf-8")
check("apps.yaml requires revision by name", 'required "revision is the commit the root is pinned at" .Values.revision' in tpl)
check("apps.yaml fails on an app name with no file", "fail (printf \"the values name app %s, and the chart has no %s\"" in tpl)
check("apps.yaml renders each listed file through tpl", "{{ tpl $body $ }}" in tpl and '$.Files.Get $file' in tpl)

print("== each profile is an explicit list of files that exist ==")
app_files = sorted(p.name for p in APPS.glob("*.yaml"))
listed = set()
for profile in profiles():
    vp = values_path(profile)
    check(f"{vp.name} exists", vp.is_file())
    if not vp.is_file():
        continue
    doc = yaml.safe_load(vp.read_text(encoding="utf-8")) or {}
    names = app_names(profile)
    check(f"{profile}: the values file holds only its apps list", list(doc) == ["apps"])
    check(f"{profile}: it lists apps, each once", bool(names) and len(names) == len(set(names)))
    missing = [n for n in names if f"{n}.yaml" not in app_files]
    check(f"{profile}: every listed app has its file in apps/ {missing}", not missing)
    listed |= set(names)
unlisted = [f for f in app_files if f[:-5] not in listed]
check(f"every apps/ file is in at least one profile {unlisted}", not unlisted)
check("the act 2 OTTL overlay left apps/ (it is not an Application)",
      not (APPS / "otel-collector-act2-overlay.yaml").exists()
      and (REPO / "gitops/otel-collector/otel-collector-act2-overlay.yaml").is_file())

# The selections the four globs made at b1fcb0e, less the overlay the excludes matched without meaning to.
WANT = {
    "attendee": 29, "burn": 19, "admin": 33, "full": 31,
}
for profile, n in WANT.items():
    check(f"{profile} lists {n} apps, the old root's selection", len(app_names(profile)) == n)

print("== every Unleashed source takes the revision; no source is the chart itself ==")
SEMVER = re.compile(r"v?\d+\.\d+\.\d+")
for f in app_files:
    raw = (APPS / f).read_text(encoding="utf-8")
    # tpl renders the whole file, so the only template text is the revision and Prometheus' own, escaped.
    stray = [m for m in re.findall(r"\{\{.*?\}\}", re.sub(r"\{\{`\{\{.*?\}\}`\}\}", "", raw)) if m != REVISION]
    check(f"{f}: no template text but the revision (Prometheus' {{{{ }}}} escaped) {stray}", not stray)
    docs = [d for d in yaml.safe_load_all(raw) if d]
    check(f"{f}: every document is an Application", bool(docs) and all(d.get("kind") == "Application" for d in docs))
    for d in docs:
        name = d.get("metadata", {}).get("name")
        for s in sources(d):
            url, rev = s.get("repoURL", ""), str(s.get("targetRevision", ""))
            if url.rstrip("/").removesuffix(".git").lower() == REPO_URL.removesuffix(".git").lower():
                check(f"{f} {name}: the Unleashed source is at {REVISION}", rev == REVISION)
                check(f"{f} {name}: it does not source gitops/bootstrap (no second root)",
                      not str(s.get("path", "")).startswith("gitops/bootstrap"))
            elif s.get("chart"):
                check(f"{f} {name}: chart {s['chart']} is at one exact version ({rev})", SEMVER.fullmatch(rev) is not None)
            else:
                check(f"{f} {name}: another git repo ({url}) is at a 40-digit commit", re.fullmatch(r"[0-9a-f]{40}", rev) is not None)

print("== no root, and no repository credential, outside the chart ==")
for p in sorted((REPO / "gitops").rglob("*.yaml")):
    if TEMPLATES in p.parents or "apps-disabled" in p.parts:
        continue
    for d in yaml.safe_load_all(p.read_text(encoding="utf-8")):
        if isinstance(d, dict) and d.get("kind") == "Application":
            check(f"{p.relative_to(REPO)}: {d['metadata'].get('name')} is not an app-of-apps root",
                  not str(d["metadata"].get("name", "")).startswith("app-of-apps")
                  and d["metadata"].get("name") != "lab-bootstrap")
secret = yaml.safe_load((TEMPLATES / "ghcr-kagent-oci.yaml").read_text(encoding="utf-8").split("*/ -}}", 1)[1])
check("ghcr-kagent-oci is an Argo CD repository Secret in argocd",
      secret.get("kind") == "Secret" and secret["metadata"].get("namespace") == "argocd"
      and secret["metadata"].get("labels", {}).get("argocd.argoproj.io/secret-type") == "repository")
check("it registers the kagent chart registry as OCI Helm",
      secret.get("stringData") == {"type": "helm", "name": "kagent-oci", "url": "ghcr.io/kagent-dev/kagent/helm",
                                   "enableOCI": "true"})
crds = yaml.safe_load((APPS / "kagent-crds.yaml").read_text(encoding="utf-8"))
wave = lambda d: int(d["metadata"]["annotations"]["argocd.argoproj.io/sync-wave"])  # noqa: E731
check("it syncs in a wave below kagent-crds, the first app that pulls from it", wave(secret) < wave(crds))

print("== deploy-full-idp.sh applies lab-bootstrap and writes no token ==")
deploy = (REPO / "infra/deploy-full-idp.sh").read_text(encoding="utf-8")
code = "\n".join(ln for ln in deploy.splitlines() if not ln.lstrip().startswith("#"))
check("it never reads `gh auth token`", "gh auth" not in code)
check("it writes no repository Secret (no password, no secret-type label)",
      "password:" not in code and "secret-type" not in code)
check("it removes a witb-repo Secret an earlier build wrote", "kubectl -n argocd delete secret witb-repo --ignore-not-found" in code)
for profile in profiles():
    check(f"`{profile}` picks values-{profile}.yaml", re.search(rf'{profile}\)\s+VALUES="values-{profile}\.yaml"', code) is not None)
root = deploy_root("admin")
check("step [4] applies one heredoc root", bool(root))
check("the root is lab-bootstrap in argocd, labelled with its profile",
      root.get("kind") == "Application" and root.get("metadata") == {
          "name": "lab-bootstrap", "namespace": "argocd", "labels": {"lab-platform/profile": "admin"}})
spec = root.get("spec") or {}
check("it has one source: gitops/bootstrap at staging, the profile's values, revision=staging",
      "sources" not in spec and spec.get("source") == {
          "repoURL": REPO_URL, "targetRevision": "staging", "path": "gitops/bootstrap",
          "helm": {"valueFiles": ["values-admin.yaml"], "parameters": [{"name": "revision", "value": "staging"}]}})
check("it ignores the finalizers charts add to its child Applications (#265)",
      spec.get("ignoreDifferences") == [{"group": "argoproj.io", "kind": "Application",
                                         "jsonPointers": ["/metadata/finalizers"]}]
      and "RespectIgnoreDifferences=true" in spec.get("syncPolicy", {}).get("syncOptions", []))
check("selfHeal and prune stay on", spec.get("syncPolicy", {}).get("automated") == {"prune": True, "selfHeal": True})
step4 = code[code.index('log "[4]'):]
check("an old root is stripped of its finalizer, then deleted, before lab-bootstrap is applied",
      "for old in app-of-apps app-of-apps-attendee app-of-apps-burn app-of-apps-admin; do" in step4
      and step4.index('"metadata":{"finalizers":null}') < step4.index('delete application "${old}"')
      < step4.index("kubectl apply -f - <<EOF"))

print("== tempo and falco-talon: admin and full only (#475) ==")
for app_file in ("tempo.yaml", "falco-talon.yaml"):
    check(f"{app_file} exists in apps/", (APPS / app_file).exists())
    check(f"attendee does not deploy {app_file}", not deploys("attendee", app_file))
    for profile in ("admin", "full"):
        check(f"{profile} deploys {app_file}", deploys(profile, app_file))
# The rest of the attendee observability path still deploys; only the Tempo store and Talon leave.
for app_file in ("prometheus.yaml", "otel-collector-attendee.yaml", "falco.yaml", "falcosidekick.yaml"):
    check(f"attendee still deploys {app_file}", deploys("attendee", app_file))

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All bootstrap chart checks passed.")
