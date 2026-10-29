# ABOUTME: Renders gitops/bootstrap with the pinned Helm for every profile at a 40-digit revision, and checks what
# ABOUTME: lab-platform's pin check will: every Unleashed source at that commit, charts exact, no second root (#609).
# SUITE: e2e (needs helm: the chart is Helm's to render; and kubectl, to apply kustomize.images and the patch)
# E2E TIER: tools (no cluster, no AWS: run-e2e-tools.sh runs it with the pinned tools, #572)
#
# Why. test_bootstrap_chart.py reads the files. Whether tpl leaves every app as it was written, renders the escaped
# Prometheus alert text back to Prometheus' own, and refuses a render with no revision or an app with no file is
# Helm's behaviour, so this asks Helm v4.2.1. The pin check is lab-platform's (docs/talk-config.md section 5):
# after lab-bootstrap syncs, every Application in argocd must have its Unleashed sources at the pinned commit,
# other git repos at a 40-digit commit and charts at one exact version. Until labctl's own check is built, this is
# that check, on the rendered chart.
from __future__ import annotations

import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

import yaml

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from bootstrap_chart import (APPS, CHART, FRONT_DOOR_ARN, FRONT_DOOR_END, FRONT_DOOR_IF, IMAGE_REGISTRY, REPO,  # noqa: E402
                             LAB_PLATFORM_GHCR, REPO_URL, REVISION, app_names, c7_control, for_c7_control,
                             profiles, values_path, kustomize_images, without_front_door)

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
    # Each listed file, rendered, is the file as written with the revision and the default image registry filled
    # in and, with no frontDoor.certificateArn, the front door's guarded block left out, and on a gateway profile
    # the c7Control guarded block too (#679): tpl changes nothing else.
    want = []
    for n in app_names(profile):
        raw = for_c7_control((APPS / f"{n}.yaml").read_text(encoding="utf-8"), c7_control(profile))
        raw = without_front_door(raw).replace(REVISION, COMMIT) \
            .replace(IMAGE_REGISTRY, LAB_PLATFORM_GHCR)
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
    # The Agent's ignore (#679): evil-mcp's toolNames inside the tools array only where C7 is that list.
    ai = next((a for a in apps if a["metadata"]["name"] == "ai-layer"), {})
    agent = [p for i in (ai.get("spec") or {}).get("ignoreDifferences") or [] if i.get("kind") == "Agent"
             for p in i.get("jqPathExpressions") or []]
    evil = '.spec.declarative.tools[] | select(.mcpServer.name == "evil-mcp") | .mcpServer.toolNames'
    want_agent = ([evil] if c7_control(profile) == "toolnames" else []) + [".spec.declarative.modelConfig"]
    check(f"{profile}: ai-layer's Agent ignore is {want_agent} (c7Control {c7_control(profile)})", agent == want_agent,
          str(agent))
    check(f"{profile}: no rendered Application keeps the c7Control guard",
          '.Values.c7Control' not in r.stdout)
    if profile == "admin":
        alerts = r.stdout
        check("admin: the Prometheus alert text renders as Prometheus' own template",
              '"Node {{ $labels.node }} is not ready"' in alerts and "{{`" not in alerts)

print("== the front door's certificate (#638) ==")
CERT = "arn:aws:acm:us-west-2:111122223333:certificate/0f1e2d3c-4b5a-6978-8a9b-0c1d2e3f4a5b"


def ai_layer(*args: str) -> dict:
    r = render("-f", str(values_path("burn")), "--set", f"revision={COMMIT}", *args)
    return next((d for d in yaml.safe_load_all(r.stdout) if d and d["metadata"]["name"] == "ai-layer"), {}) \
        if r.returncode == 0 else {}


plain = ai_layer()
check("no certificateArn: ai-layer's kustomize block has no patches, so 443 stays nginx's self-signed pass-through",
      bool(plain) and "patches" not in plain["spec"]["source"].get("kustomize", {}))
fd = ai_layer("--set", f"frontDoor.certificateArn={CERT}")
patches = ((fd.get("spec") or {}).get("source") or {}).get("kustomize", {}).get("patches") or []
check("with one: one patch, on the console Service", len(patches) == 1
      and patches[0].get("target") == {"kind": "Service", "name": "console"})
ops = {o["path"].rsplit("/", 1)[-1].replace("~1", "/"): o["value"]
       for o in yaml.safe_load(patches[0]["patch"]) if o.get("op") == "add"} if patches else {}
check("it puts the certificate on the NLB's 443 as a TLS listener that re-encrypts to nginx",
      ops == {"service.beta.kubernetes.io/aws-load-balancer-ssl-cert": CERT,
              "service.beta.kubernetes.io/aws-load-balancer-ssl-ports": "443",
              "service.beta.kubernetes.io/aws-load-balancer-backend-protocol": "ssl",
              "service.beta.kubernetes.io/aws-load-balancer-ssl-negotiation-policy":
                  "ELBSecurityPolicy-TLS13-1-2-2021-06"}, str(ops))
# The patch as Argo CD applies it: kustomize over gitops/ai-layer, from a scratch overlay in the repo's tmp/.
KUBECTL = shutil.which("kubectl")
check("kubectl is on PATH, to apply the patch with kustomize", KUBECTL is not None)
if KUBECTL and patches:
    (REPO / "tmp").mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir=REPO / "tmp") as d:
        (pathlib.Path(d) / "kustomization.yaml").write_text(yaml.safe_dump({
            "apiVersion": "kustomize.config.k8s.io/v1beta1", "kind": "Kustomization",
            "resources": [os.path.relpath(REPO / "gitops/ai-layer", d)], "patches": patches}), encoding="utf-8")
        k = subprocess.run([KUBECTL, "kustomize", d], capture_output=True, text=True)
    svc = next((x for x in yaml.safe_load_all(k.stdout) if x and x.get("kind") == "Service"
                and x["metadata"]["name"] == "console"), {}) if k.returncode == 0 else {}
    ann = (svc.get("metadata") or {}).get("annotations") or {}
    check("kustomize applies it: the console Service carries the certificate and keeps its own annotations",
          all(ann.get(a) == v for a, v in ops.items()) and ann.get("service.beta.kubernetes.io/aws-load-balancer-type")
          == "external" and len(ann) == len(ops) + 4, k.stderr.strip()[:300] or str(ann))
fd["spec"]["source"].get("kustomize", {}).pop("patches", None) if fd else None
check("and changes nothing else in the Application", bool(fd) and fd == plain)
r = render("-f", str(values_path("burn")), "--set", f"revision={COMMIT}", "--set", "frontDoor.certificateArn=console-tls")
check("a certificateArn that is not an ACM ARN: the render fails, naming it", r.returncode != 0
      and "frontDoor.certificateArn is the ARN of the ACM certificate" in r.stderr, r.stderr.strip()[:200])
for guard in (FRONT_DOOR_IF, FRONT_DOOR_ARN, FRONT_DOOR_END):
    check(f"no rendered Application keeps {guard}", guard not in render(
        "-f", str(values_path("admin")), "--set", f"revision={COMMIT}", "--set", f"frontDoor.certificateArn={CERT}").stdout)

print("== LLM Guard's image, set through kustomize.images at the root's registry (#652) ==")
# resources.yaml names the container by the kustomize image name llm-guard; ai-layer.yaml's kustomize.images sets it.
# Argo CD runs `kustomize edit set image` with each entry, which writes the entries kustomize_images() returns
# (measured with kustomize v5.8.1, Argo CD v3.4.4's), so the scratch overlay below is what Argo CD builds.
LLM_GUARD = "llm-guard:v1@sha256:781a126bf7c7da6b8460d48b1fba1e0823673b85b186a165b36e0b23eb3f4d7b"
CACHE = "123456789012.dkr.ecr.us-west-2.amazonaws.com/lp-shared/peopleforrester/lab-platform"


def workload_images(text: str) -> dict[str, str]:
    """Each workload container's image in a kustomize build, keyed kind/name/container."""
    out = {}
    for d in yaml.safe_load_all(text):
        if not d or d.get("kind") not in ("Deployment", "StatefulSet", "DaemonSet", "Job"):
            continue
        spec = (d["spec"].get("template") or {}).get("spec") or {}
        for c in spec.get("containers", []) + spec.get("initContainers", []):
            out[f"{d['kind']}/{d['metadata']['name']}/{c['name']}"] = c["image"]
    return out


base = subprocess.run([KUBECTL, "kustomize", str(REPO / "gitops/ai-layer")], capture_output=True, text=True) \
    if KUBECTL else None
check("gitops/ai-layer builds with kustomize", base is not None and base.returncode == 0,
      base.stderr.strip()[:300] if base else "no kubectl")
from registry_allowlist import allowed  # noqa: E402

for label, registry, args in (("unset", LAB_PLATFORM_GHCR, ()), ("at the cache path", CACHE,
                                                                ("--set", f"imageRegistry={CACHE}"))):
    entries = kustomize_images(ai_layer(*args))
    check(f"{label}: ai-layer sets one image, llm-guard, to {registry}/{LLM_GUARD}",
          entries == [{"name": "llm-guard", "newName": f"{registry}/llm-guard", "newTag": "v1",
                       "digest": LLM_GUARD.split("@", 1)[1]}], str(entries))
    if not (KUBECTL and base and base.returncode == 0 and entries):
        continue
    (REPO / "tmp").mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir=REPO / "tmp") as d:
        (pathlib.Path(d) / "kustomization.yaml").write_text(yaml.safe_dump({
            "apiVersion": "kustomize.config.k8s.io/v1beta1", "kind": "Kustomization",
            "resources": [os.path.relpath(REPO / "gitops/ai-layer", d)], "images": entries}), encoding="utf-8")
        k = subprocess.run([KUBECTL, "kustomize", d], capture_output=True, text=True)
    got = workload_images(k.stdout) if k.returncode == 0 else {}
    want = workload_images(base.stdout)
    key = "Deployment/llm-guard/llm-guard-api"
    check(f"{label}: the llm-guard Deployment runs {registry}/{LLM_GUARD}", got.get(key) == f"{registry}/{LLM_GUARD}",
          k.stderr.strip()[:300] or str(got.get(key)))
    check(f"{label}: restrict-image-registries allows it", allowed(got.get(key, "")))
    check(f"{label}: no other container's image changes", {n: i for n, i in got.items() if n != key}
          == {n: i for n, i in want.items() if n != key} and set(got) == set(want))
check("the bundle as written names llm-guard by the kustomize image name alone",
      workload_images(base.stdout).get("Deployment/llm-guard/llm-guard-api") == "llm-guard" if base else False)

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
r = render("-f", str(values_path("admin")), "--set", f"revision={COMMIT}", "--set", "c7Control=toolNames")
check("a c7Control that is neither toolnames nor gateway: the render fails, naming it (#679)", r.returncode != 0
      and "c7Control is where Challenge 7's control sits" in r.stderr, r.stderr.strip()[:200])
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
