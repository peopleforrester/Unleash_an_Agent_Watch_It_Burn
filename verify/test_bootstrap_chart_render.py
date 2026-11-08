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
from bootstrap_chart import (APPS, ARM_END, ARM_PARAMETER, ARM_VALUE, ARMED_IF, CHART, FRONT_DOOR_ARN,  # noqa: E402
                             FRONT_DOOR_END, FRONT_DOOR_IF, IMAGE_REGISTRY, REPO, LAB_PLATFORM_GHCR, REPO_URL, REVISION,
                             UNARMED_IF, all_profiles, app_names, c7_control, for_c7_control, for_guardrails,
                             for_kubecon_brief, kubecon_brief, profiles, values_path, kustomize_images,
                             without_front_door, DESK_REMOTE_COMPONENT, desk_remote_reports, for_desk_remote_reports,
                             PUBLIC_DESK_COMPONENT, for_public_desk, use_public_desk)

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


for profile in all_profiles():
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
    # in and, with no frontDoor.certificateArn, the front door's guarded block left out, on a gateway profile
    # the c7Control guarded block too (#679), at guardrails.validationAction Audit the armed block (#638), and on a
    # profile that serves /kubecon the block that withholds it (#909): tpl changes nothing else.
    want = []
    for n in app_names(profile):
        raw = for_c7_control((APPS / f"{n}.yaml").read_text(encoding="utf-8"), c7_control(profile))
        raw = for_public_desk(for_desk_remote_reports(raw, desk_remote_reports(profile)), use_public_desk(profile))
        raw = for_kubecon_brief(raw, kubecon_brief(profile))
        raw = without_front_door(for_guardrails(raw, "Audit")).replace(REVISION, COMMIT) \
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
    # The Agent's ignore (#679): evil-mcp's toolNames inside the tools array only where C7 is that list. Since #707
    # it is the workshop-agent Application's, which syncs without RespectIgnoreDifferences; ai-layer has none.
    def agent_ignores(name):
        app = next((a for a in apps if a["metadata"]["name"] == name), {})
        return app, [p for i in (app.get("spec") or {}).get("ignoreDifferences") or [] if i.get("kind") == "Agent"
                     for p in i.get("jqPathExpressions") or []]
    wa, agent = agent_ignores("workshop-agent")
    evil = '.spec.declarative.tools[] | select(.mcpServer.name == "evil-mcp") | .mcpServer.toolNames'
    want_agent = ([evil] if c7_control(profile) == "toolnames" else []) + [".spec.declarative.modelConfig"]
    check(f"{profile}: workshop-agent's Agent ignore is {want_agent} (c7Control {c7_control(profile)})",
          agent == want_agent, str(agent))
    check(f"{profile}: workshop-agent syncs without RespectIgnoreDifferences (#707)",
          bool(wa) and "RespectIgnoreDifferences=true" not in ((wa["spec"].get("syncPolicy") or {}).get("syncOptions") or []))
    check(f"{profile}: ai-layer ignores nothing on the Agent (#707)", not agent_ignores("ai-layer")[1])
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

print("== the KubeCon presenter page, withheld from the community cluster (#909) ==")


def ai_layer_for(profile: str) -> dict:
    r = render("-f", str(values_path(profile)), "--set", f"revision={COMMIT}")
    return next((d for d in yaml.safe_load_all(r.stdout) if d and d["metadata"]["name"] == "ai-layer"), {}) \
        if r.returncode == 0 else {}


def ai_layer_built(components: list[str]) -> tuple[list[dict], str]:
    """gitops/ai-layer as Argo CD builds it with these kustomize.components: it adds them to the app's own
    kustomization (`kustomize edit add component`). The objects, and kustomize's error when it fails."""
    (REPO / "tmp").mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir=REPO / "tmp") as d:
        app = pathlib.Path(d) / "ai-layer"
        shutil.copytree(REPO / "gitops/ai-layer", app, symlinks=True)
        if components:
            kust = yaml.safe_load((app / "kustomization.yaml").read_text(encoding="utf-8"))
            kust["components"] = list(kust.get("components") or []) + components
            (app / "kustomization.yaml").write_text(yaml.safe_dump(kust, sort_keys=False), encoding="utf-8")
        k = subprocess.run([KUBECTL, "kustomize", str(app)], capture_output=True, text=True)
    if k.returncode != 0:
        return [], k.stderr.strip()[:300]
    return [x for x in yaml.safe_load_all(k.stdout) if x], ""


def console_src_built(components: list[str]) -> tuple[dict, str, str]:
    """The console-src ConfigMap and the name the console Deployment mounts, built with these kustomize.components."""
    docs, err = ai_layer_built(components)
    if err:
        return {}, "", err
    cm = next((x for x in docs if x.get("kind") == "ConfigMap" and x["metadata"]["name"].startswith("console-src-")), {})
    dep = next((x for x in docs if x.get("kind") == "Deployment" and x["metadata"]["name"] == "console"), {})
    mounted = [v["configMap"]["name"] for v in (dep.get("spec") or {}).get("template", {}).get("spec", {}).get("volumes", [])
               if (v.get("configMap") or {}).get("name", "").startswith("console-src")]
    return cm, (mounted or [""])[0], ""


built = {}
for profile, served in (("kubecon-community", False), ("kubecon-private", True), ("burn", False), ("admin", True)):
    comps = ((ai_layer_for(profile).get("spec") or {}).get("source") or {}).get("kustomize", {}).get("components") or []
    want = ([PUBLIC_DESK_COMPONENT] if profile == "kubecon-private" else []) if served \
        else ["components/no-kubecon-brief"] + ([DESK_REMOTE_COMPONENT] if profile == "kubecon-community" else [])
    check(f"{profile}: ai-layer renders the components {want}", comps == want, str(comps))
    if not KUBECTL:
        continue
    cm, mounted, err = console_src_built(comps)
    built[profile] = cm
    data = cm.get("data") or {}
    check(f"{profile}: kustomize builds gitops/ai-layer with them, and console-src "
          f"{'keeps' if served else 'has no'} kubecon.html", bool(cm) and ("kubecon.html" in data) == served, err)
    check(f"{profile}: the console Deployment mounts that ConfigMap by its hashed name ({mounted})",
          bool(cm) and mounted == cm["metadata"]["name"])
    if served and cm:
        check(f"{profile}: the kubecon.html it serves is the repo's page",
              data.get("kubecon.html") == (REPO / "gitops/ai-layer/web/kubecon.html").read_text(encoding="utf-8"))
if len(built) == 4 and all(built.values()):
    community, private = built["kubecon-community"], built["kubecon-private"]
    check("the community console-src is the private one less kubecon.html, so the console rolls onto a new name",
          set(private["data"]) - set(community["data"]) == {"kubecon.html"}
          and all(community["data"][k] == private["data"][k] for k in community["data"])
          and community["metadata"]["name"] != private["metadata"]["name"])
r = render("-f", str(values_path("kubecon-private")), "--set", f"revision={COMMIT}", "--set", "console.kubeconBrief=no")
check("a console.kubeconBrief that is not a bool: the render fails, naming it (#909)", r.returncode != 0
      and "console.kubeconBrief is whether this cluster's console serves /kubecon" in r.stderr, r.stderr.strip()[:200])
for guard in ("console.kubeconBrief", "desk.remoteReports", "{{"):
    check(f"no rendered kubecon-community ai-layer keeps {guard!r}",
          guard not in yaml.safe_dump(ai_layer_for("kubecon-community")))

print("== the public desk's remote reports, kubecon-community alone (#1157) ==")
r = render("-f", str(values_path("kubecon-community")), "--set", f"revision={COMMIT}", "--set", "desk.remoteReports=yes")
check("a desk.remoteReports that is not a bool: the render fails, naming it", r.returncode != 0
      and "desk.remoteReports is whether this cluster's desk takes" in r.stderr, r.stderr.strip()[:200])
r = render("-f", str(values_path("kubecon-private")), "--set", f"revision={COMMIT}", "--set", "desk.remoteReports=true")
check("desk.remoteReports on a profile that serves /kubecon (the private cluster): the render fails, naming it",
      r.returncode != 0 and "desk.remoteReports is for the public desk" in r.stderr, r.stderr.strip()[:200])
LOCATIONS_FILE = REPO / "gitops/ai-layer/components/desk-remote-reports/desk-remote-report.locations"
for profile in ("kubecon-community", "burn", "attendee", "kubecon-private"):
    comps = ((ai_layer_for(profile).get("spec") or {}).get("source") or {}).get("kustomize", {}).get("components") or []
    on = profile == "kubecon-community"
    if not KUBECTL:
        continue
    docs, err = ai_layer_built(comps)
    conf = next((x for x in docs if x.get("kind") == "ConfigMap" and x["metadata"]["name"].startswith("console-conf-")), {})
    console = next((x for x in docs if x.get("kind") == "Deployment" and x["metadata"]["name"] == "console"), {})
    site = next((x for x in docs if x.get("kind") == "Deployment" and x["metadata"]["name"] == "fake-ticket"), {})
    mounts = [v["configMap"]["name"] for v in (console.get("spec") or {}).get("template", {}).get("spec", {})
              .get("volumes", []) if (v.get("configMap") or {}).get("name", "").startswith("console-conf")]
    env = {e["name"]: e for c in (site.get("spec") or {}).get("template", {}).get("spec", {}).get("containers", [])
           for e in c.get("env") or []}
    check(f"{profile}: kustomize builds it, and console-conf is "
          f"{'default.conf and desk-remote-report.locations' if on else 'default.conf alone'}",
          bool(conf) and sorted(conf["data"]) == (["default.conf", "desk-remote-report.locations"] if on
                                                  else ["default.conf"]), err or str(sorted((conf or {}).get("data", {}))))
    check(f"{profile}: the console mounts that console-conf by its hashed name", bool(conf) and mounts == [conf["metadata"]["name"]],
          str(mounts))
    if on and conf:
        check(f"{profile}: the locations file is the component's", conf["data"]["desk-remote-report.locations"]
              == LOCATIONS_FILE.read_text(encoding="utf-8"))
    want_env = {"DESK_CLUSTER", "DESK_REMOTE_CLUSTER", "DESK_REPORT_TOKEN"} if on else set()
    check(f"{profile}: fake-ticket's env is {sorted(want_env) or 'empty'}", set(env) == want_env, str(sorted(env)))
    if on:
        ref = (env.get("DESK_REPORT_TOKEN", {}).get("valueFrom") or {}).get("secretKeyRef") or {}
        check(f"{profile}: the token is the desk-report-token Secret's token key, optional",
              ref == {"name": "desk-report-token", "key": "token", "optional": True}, str(ref))

print("== the admin bot on the public desk, kubecon-private alone (#1158) ==")
r = render("-f", str(values_path("kubecon-private")), "--set", f"revision={COMMIT}", "--set", "desk.usePublicDesk=yes")
check("a desk.usePublicDesk that is not a bool: the render fails, naming it", r.returncode != 0
      and "desk.usePublicDesk is whether this cluster's bot uses the public desk" in r.stderr, r.stderr.strip()[:200])
r = render("-f", str(values_path("kubecon-community")), "--set", f"revision={COMMIT}", "--set", "desk.usePublicDesk=true")
check("desk.usePublicDesk on a community profile (the public desk's own cluster): the render fails, naming it",
      r.returncode != 0 and "desk.usePublicDesk is for the private cluster's bot" in r.stderr, r.stderr.strip()[:200])
IN_CLUSTER_DESK = "http://fake-ticket.agent.svc.cluster.local:8080"
RELAY = "http://desk-relay.agent.svc.cluster.local:8080"
for profile in ("attendee", "kubecon-private", "kubecon-community", "admin"):
    comps = ((ai_layer_for(profile).get("spec") or {}).get("source") or {}).get("kustomize", {}).get("components") or []
    on = profile == "kubecon-private"
    check(f"{profile}: the ai-layer {'adds' if on else 'does not add'} the public-desk component {comps}",
          (PUBLIC_DESK_COMPONENT in comps) is on)
    if not KUBECTL:
        continue
    docs, err = ai_layer_built(comps)
    mcp = next((x for x in docs if x.get("kind") == "Deployment" and x["metadata"]["name"] == "workshop-mcp"), {})
    env = {e["name"]: e.get("value") for c in (mcp.get("spec") or {}).get("template", {}).get("spec", {})
           .get("containers", []) for e in c.get("env") or []}
    check(f"{profile}: kustomize builds it, and workshop-mcp's TICKET_SITE_URL is {RELAY if on else IN_CLUSTER_DESK}",
          env.get("TICKET_SITE_URL") == (RELAY if on else IN_CLUSTER_DESK), err or str(env.get("TICKET_SITE_URL")))
    relay = [(x["kind"], x["metadata"]["name"]) for x in docs if "desk-relay" in x["metadata"]["name"]]
    check(f"{profile}: {'the relay, its Service, its NetworkPolicy and its source' if on else 'no desk-relay object'} "
          f"{relay}", sorted(k for k, _ in relay) == (["ConfigMap", "Deployment", "NetworkPolicy", "Service"] if on
                                                      else []))
    if on:
        dep = next((x for x in docs if x.get("kind") == "Deployment" and x["metadata"]["name"] == "desk-relay"), {})
        src = next((x for x in docs if x.get("kind") == "ConfigMap" and x["metadata"]["name"].startswith("desk-relay-src-")),
                   {})
        vols = (dep.get("spec") or {}).get("template", {}).get("spec", {}).get("volumes", [])
        check(f"{profile}: the relay mounts its source by the hashed name, and the token Secret optional",
              {"name": src.get("metadata", {}).get("name")} in [v.get("configMap") for v in vols]
              and {"secretName": "desk-report-token", "optional": True} in [v.get("secret") for v in vols], str(vols))
        check(f"{profile}: the relay source is the component's desk_relay.py", (src.get("data") or {}).get("desk_relay.py")
              == (REPO / "gitops/ai-layer/components/public-desk/desk_relay.py").read_text(encoding="utf-8"))

print("== the guardrails, armed by lab-platform's arm parameter (#638, lab-platform#310) ==")
ARMING = ("--set", f"{ARM_PARAMETER}={ARM_VALUE}")
LIVE_TOGGLE = ("require-resource-limits", "restrict-image-registries")


def kyverno_policies(profile: str, *args: str) -> dict:
    r = render("-f", str(values_path(profile)), "--set", f"revision={COMMIT}", *args)
    return next((d for d in yaml.safe_load_all(r.stdout) if d and d["metadata"]["name"] == "kyverno-policies"), {}) \
        if r.returncode == 0 else {}


def policy_actions(text: str) -> dict[str, list]:
    """Each ValidatingPolicy's spec.validationActions in a kustomize build of policies/kyverno, by name."""
    return {d["metadata"]["name"]: d["spec"].get("validationActions") for d in yaml.safe_load_all(text)
            if d and d.get("kind") == "ValidatingPolicy"}


as_written = {}
for f in sorted((REPO / "policies/kyverno").glob("*.yaml")):
    as_written.update(policy_actions(f.read_text(encoding="utf-8")))
built = subprocess.run([KUBECTL, "kustomize", str(REPO / "policies/kyverno")], capture_output=True, text=True) \
    if KUBECTL else None
check("policies/kyverno builds with kustomize to every policy as written, as Argo CD now builds it",
      built is not None and built.returncode == 0 and policy_actions(built.stdout) == as_written
      and len([d for d in yaml.safe_load_all(built.stdout) if d])
      == sum(1 for f in (REPO / "policies/kyverno").glob("*.yaml")
             for d in yaml.safe_load_all(f.read_text(encoding="utf-8")) if d),
      built.stderr.strip()[:300] if built else "no kubectl")
for profile in ("attendee", "admin", "full"):
    plain = kyverno_policies(profile)
    ign = sorted(i.get("name") for i in (plain.get("spec") or {}).get("ignoreDifferences") or [])
    check(f"{profile}, unarmed: no kustomize patches, and the live toggle's ignore on both policies",
          bool(plain) and "kustomize" not in plain["spec"]["source"] and ign == sorted(LIVE_TOGGLE), str(ign))
armed = kyverno_policies("admin", *ARMING)
patches = ((armed.get("spec") or {}).get("source") or {}).get("kustomize", {}).get("patches") or []
check("admin, armed: one patch on each live-toggle policy, replacing /spec/validationActions with [Deny]",
      sorted(p["target"].get("name") for p in patches) == sorted(LIVE_TOGGLE)
      and all(p["target"].get("kind") == "ValidatingPolicy" and p["target"].get("group") == "policies.kyverno.io"
              and yaml.safe_load(p["patch"]) == [{"op": "replace", "path": "/spec/validationActions",
                                                  "value": ["Deny"]}] for p in patches), str(patches))
check("admin, armed: no ignore on /spec/validationActions, so selfHeal holds Deny from git",
      bool(armed) and "ignoreDifferences" not in armed["spec"]
      and "RespectIgnoreDifferences=true" in armed["spec"]["syncPolicy"]["syncOptions"])
plain = kyverno_policies("admin")
if armed and plain:
    a, b = dict(armed["spec"]), dict(plain["spec"])
    a["source"] = {k: v for k, v in a["source"].items() if k != "kustomize"}
    b.pop("ignoreDifferences", None)
    check("admin, armed: nothing else in kyverno-policies changes", a == b and armed["metadata"] == plain["metadata"])
r_plain = render("-f", str(values_path("admin")), "--set", f"revision={COMMIT}")
r_armed = render("-f", str(values_path("admin")), "--set", f"revision={COMMIT}", *ARMING)
others = lambda r: [d for d in yaml.safe_load_all(r.stdout) if d and d["metadata"]["name"] != "kyverno-policies"]  # noqa: E731
check("admin, armed: no other Application changes", r_armed.returncode == 0 and others(r_armed) == others(r_plain))
for guard in (ARMED_IF, UNARMED_IF, ARM_END, ".Values.guardrails"):
    check(f"no rendered Application keeps {guard}", guard not in r_armed.stdout and guard not in r_plain.stdout)
# The patches as Argo CD applies them: kustomize over policies/kyverno, from a scratch overlay in the repo's tmp/.
if KUBECTL and patches:
    (REPO / "tmp").mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir=REPO / "tmp") as d:
        (pathlib.Path(d) / "kustomization.yaml").write_text(yaml.safe_dump({
            "apiVersion": "kustomize.config.k8s.io/v1beta1", "kind": "Kustomization",
            "resources": [os.path.relpath(REPO / "policies/kyverno", d)], "patches": patches}), encoding="utf-8")
        k = subprocess.run([KUBECTL, "kustomize", d], capture_output=True, text=True)
    got = policy_actions(k.stdout) if k.returncode == 0 else {}
    check("kustomize applies them: both live-toggle policies at [Deny], every other policy as written",
          bool(got) and got == {n: (["Deny"] if n in LIVE_TOGGLE else v) for n, v in as_written.items()},
          k.stderr.strip()[:300] or str(got))
check("both live-toggle policies ship at [Audit] in git", all(as_written.get(n) == ["Audit"] for n in LIVE_TOGGLE))
r = render("-f", str(values_path("admin")), "--set", f"revision={COMMIT}", "--set", f"{ARM_PARAMETER}=Enforce")
check("a guardrails.validationAction that is neither Audit nor Deny: the render fails, naming it", r.returncode != 0
      and "guardrails.validationAction is the action of the two guardrails" in r.stderr, r.stderr.strip()[:200])

print("== LLM Guard's image, set through kustomize.images at the root's registry (#652, #895) ==")
# resources.yaml names the container by the kustomize image name llm-guard; ai-layer.yaml's kustomize.images sets it.
# Argo CD runs `kustomize edit set image` with each entry, which writes the entries kustomize_images() returns
# (measured with kustomize v5.8.1, Argo CD v3.4.4's), so the scratch overlay below is what Argo CD builds.
# Since #895 the entry is lab-platform#341's rebuild of llm-guard:v1 at the root's imageRegistry, as before question
# 1041 (#719) moved it to cpu.5 for a while.
LLM_GUARD = "llm-guard:v1@sha256:46b3d20203147d36d2e023c01bfd889f27f1c3900246777abe48cb16d0f3881a"
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

print("== the demo apps' web image, set the same way (#715) ==")
# Each demo-app directory is a kustomize bundle whose Deployment names the kustomize image web; its app file's
# kustomize.images sets lab-platform's web by digest at the root's registry, and the bundle generates web.yaml's ConfigMap.
WEB = "web@sha256:73cd15652cb8b8eb706bd43f8877541db7f7c9e5f810ef0739636a27fc34fbd9"
DEMO = [n for n in app_names("burn") if n.startswith("demo-app-")]
check(f"burn deploys the five demo apps {DEMO}", len(DEMO) == 5)
for label, registry, args in (("unset", LAB_PLATFORM_GHCR, ()), ("at the cache path", CACHE,
                                                                ("--set", f"imageRegistry={CACHE}"))):
    r = render("-f", str(values_path("burn")), "--set", f"revision={COMMIT}", *args)
    rendered = {d["metadata"]["name"]: d for d in yaml.safe_load_all(r.stdout) if d} if r.returncode == 0 else {}
    for n in DEMO:
        entries = kustomize_images(rendered.get(n, {}))
        check(f"{label}: {n} sets one image, web, to {registry}/{WEB}",
              entries == [{"name": "web", "newName": f"{registry}/web", "digest": WEB.split("@", 1)[1]}], str(entries))
        if not (KUBECTL and entries):
            continue
        mdir = REPO / f"gitops/manifests/{n}"
        own = subprocess.run([KUBECTL, "kustomize", str(mdir)], capture_output=True, text=True)
        with tempfile.TemporaryDirectory(dir=REPO / "tmp") as d:
            (pathlib.Path(d) / "kustomization.yaml").write_text(yaml.safe_dump({
                "apiVersion": "kustomize.config.k8s.io/v1beta1", "kind": "Kustomization",
                "resources": [os.path.relpath(mdir, d)], "images": entries}), encoding="utf-8")
            k = subprocess.run([KUBECTL, "kustomize", d], capture_output=True, text=True)
        check(f"{label}: {n} builds with kustomize, as written and with the image set",
              own.returncode == 0 and k.returncode == 0, (own.stderr + k.stderr).strip()[:300])
        if k.returncode != 0:
            continue
        built = [x for x in yaml.safe_load_all(k.stdout) if x]
        check(f"{label}: the {n} Deployment runs {registry}/{WEB}",
              workload_images(k.stdout) == {f"Deployment/{n}/{n}": f"{registry}/{WEB}"}, str(workload_images(k.stdout)))
        check(f"{label}: and as written names it by the kustomize image name alone",
              own.returncode == 0 and workload_images(own.stdout) == {f"Deployment/{n}/{n}": "web"})
        check(f"{label}: restrict-image-registries allows it", allowed(f"{registry}/{WEB}"))
        gen = [x for x in built if x.get("kind") == "ConfigMap" and x["metadata"]["name"].startswith(f"{n}-web-")]
        dep = next((x for x in built if x.get("kind") == "Deployment"), {})
        vols = {v["name"]: (v.get("configMap") or {}).get("name")
                for v in (dep.get("spec") or {}).get("template", {}).get("spec", {}).get("volumes") or []}
        check(f"{label}: the web volume is the generated {n}-web-<hash>, in apps, holding web.yaml as written",
              len(gen) == 1 and vols.get("web") == gen[0]["metadata"]["name"]
              and gen[0]["metadata"].get("namespace") == "apps"
              and gen[0]["data"] == {"web.yaml": (mdir / "web.yaml").read_text(encoding="utf-8")}, str(vols))

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
