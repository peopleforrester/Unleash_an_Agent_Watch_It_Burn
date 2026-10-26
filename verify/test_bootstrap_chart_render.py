# ABOUTME: Renders gitops/bootstrap with the pinned Helm for every profile at a 40-digit revision, and checks what
# ABOUTME: lab-platform's pin check will: every Unleashed source at that commit, charts exact, no second root (#609).
# SUITE: e2e (needs helm: the chart is Helm's to render)
# E2E TIER: tools (no cluster, no AWS: run-e2e-tools.sh runs it with the pinned tools, #572)
#
# Why. test_bootstrap_chart.py reads the files. Whether tpl leaves every app as it was written, renders the escaped
# Prometheus alert text back to Prometheus' own, and refuses a render with no revision or an app with no file is
# Helm's behaviour, so this asks Helm v4.2.1. The pin check is lab-platform's (docs/talk-config.md section 5):
# after lab-bootstrap syncs, every Application in argocd must have its Unleashed sources at the pinned commit,
# other git repos at a 40-digit commit and charts at one exact version. Until labctl's own check is built, this is
# that check, on the rendered chart.
from __future__ import annotations

import pathlib
import re
import shutil
import subprocess
import sys

import yaml

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from bootstrap_chart import APPS, CHART, REPO_URL, REVISION, app_names, profiles, values_path  # noqa: E402

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail and not ok else ""))
    if not ok:
        failures.append(name)


HELM = shutil.which("helm")
if not HELM:
    print("FAIL: helm is not on PATH (run through verify/run-e2e-tools.sh, which puts the pinned one first)",
          file=sys.stderr)
    sys.exit(1)
version = subprocess.run([HELM, "version", "--short"], capture_output=True, text=True).stdout.strip()
check(f"helm is the pinned v4.2.1 ({version})", version.startswith("v4.2.1"))

COMMIT = "0123456789abcdef0123456789abcdef01234567"
SEMVER = re.compile(r"v?\d+\.\d+\.\d+")


def render(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([HELM, "template", "lab-bootstrap", str(CHART), *args], capture_output=True, text=True)


def sources(app: dict) -> list[dict]:
    sp = app.get("spec") or {}
    return ([sp["source"]] if "source" in sp else []) + list(sp.get("sources") or [])


def unleashed(url: str) -> bool:
    return url.rstrip("/").removesuffix(".git").lower() == REPO_URL.removesuffix(".git").lower()


for profile in profiles():
    print(f"== {profile}: rendered at revision={COMMIT[:12]}... ==")
    r = render("-f", str(values_path(profile)), "--set", f"revision={COMMIT}")
    check(f"{profile} renders", r.returncode == 0, r.stderr.strip()[:300])
    if r.returncode != 0:
        continue
    docs = [d for d in yaml.safe_load_all(r.stdout) if d]
    apps = [d for d in docs if d.get("kind") == "Application"]
    rest = [(d.get("kind"), d["metadata"]["name"]) for d in docs if d.get("kind") != "Application"]
    check(f"{profile}: besides the Applications it renders only the ghcr-kagent-oci Secret {rest}",
          rest == [("Secret", "ghcr-kagent-oci")])
    # Each listed file, rendered, is the file as written with the revision filled in: tpl changes nothing else.
    want = []
    for n in app_names(profile):
        raw = (APPS / f"{n}.yaml").read_text(encoding="utf-8").replace(REVISION, COMMIT)
        raw = re.sub(r"\{\{`(\{\{.*?\}\})`\}\}", r"\1", raw)
        want += [d for d in yaml.safe_load_all(raw) if d]
    check(f"{profile}: the Applications are exactly the {len(app_names(profile))} listed files, as written",
          sorted(apps, key=lambda d: d["metadata"]["name"]) == sorted(want, key=lambda d: d["metadata"]["name"]))
    names = [a["metadata"]["name"] for a in apps]
    check(f"{profile}: no Application name twice", len(names) == len(set(names)))
    for a in apps:
        n = a["metadata"]["name"]
        for s in sources(a):
            url, rev = s.get("repoURL", ""), str(s.get("targetRevision", ""))
            if unleashed(url):
                check(f"{profile} {n}: Unleashed at the pinned commit", rev == COMMIT, rev)
                check(f"{profile} {n}: not a second root over gitops/bootstrap",
                      not str(s.get("path", "")).startswith("gitops/bootstrap"))
            elif s.get("chart"):
                check(f"{profile} {n}: {s['chart']} at one exact version", SEMVER.fullmatch(rev) is not None, rev)
            else:
                check(f"{profile} {n}: {url} at a 40-digit commit", re.fullmatch(r"[0-9a-f]{40}", rev) is not None, rev)
    if profile == "admin":
        alerts = r.stdout
        check("admin: the Prometheus alert text renders as Prometheus' own template",
              '"Node {{ $labels.node }} is not ready"' in alerts and "{{`" not in alerts)

print("== the render refuses what it cannot pin ==")
r = render("-f", str(values_path("attendee")))
check("no revision: the render fails, naming it", r.returncode != 0
      and "revision is the commit the root is pinned at" in r.stderr, r.stderr.strip()[:200])
r = render("--set", f"revision={COMMIT}")
check("no profile values: the render fails, naming it", r.returncode != 0 and "the values name no apps" in r.stderr,
      r.stderr.strip()[:200])
r = render("--set", f"revision={COMMIT}", "--set", "apps={external-secrets,no-such-app}")
check("an app with no file: the render fails, naming the file", r.returncode != 0
      and "the values name app no-such-app, and the chart has no apps/no-such-app.yaml" in r.stderr,
      r.stderr.strip()[:200])
r = render("-f", str(values_path("burn")), "--set", "revision=staging")
check("revision=staging, deploy-full-idp.sh's root, renders the burn children at staging",
      r.returncode == 0 and all(str(s.get("targetRevision")) == "staging"
                                for d in yaml.safe_load_all(r.stdout) if d and d.get("kind") == "Application"
                                for s in sources(d) if unleashed(s.get("repoURL", ""))))

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All bootstrap chart render checks passed.")
