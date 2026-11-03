# ABOUTME: Render gate for #782: the go-otel Component swaps guard-proxy's inject-python for inject-sdk on the
# ABOUTME: http/protobuf 4318 Instrumentation, changes nothing else, and must be on once guard-proxy runs Go (#738).
# SUITE: e2e (needs kubectl: every check reads the `kubectl kustomize` render of gitops/ai-layer)
# E2E TIER: tools (no cluster, no AWS: run-e2e-tools.sh runs it with the pinned tools, #572)
#
# Why. The Go guard-proxy exports OTLP over http/protobuf from the standard OTEL_* variables and is off without an
# endpoint; OTEL_EXPORTER_OTLP_PROTOCOL=grpc stops it at startup (guard-proxy-agenticburn#36). The OTel Operator's
# inject-sdk annotation supplies them from the Instrumentation CR; inject-python, which proxy.py needs, mounts a
# Python agent a Go binary cannot use. KubeCon runs proxy.py, so the Component is off and the cutover turns it on.
# The last check is what stops the cutover forgetting to.
import pathlib, shutil, subprocess, sys, tempfile
from urllib.parse import urlsplit

import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
AI_LAYER = REPO / "gitops/ai-layer"
COMPONENT = "go-otel"
INJECT = "instrumentation.opentelemetry.io/inject-"
SDK = INJECT + "sdk"
PYTHON = INJECT + "python"
CAPTURE_MODES = {"SPAN_ONLY", "EVENT_ONLY", "SPAN_AND_EVENT"}
failures = []


def check(n, c, detail=""):
    print(f"  {'PASS' if c else 'FAIL'}  {n}" + (f"  ({detail})" if detail and not c else ""))
    if not c:
        failures.append(n)


def render(path):
    out = subprocess.run(["kubectl", "kustomize", str(path)], capture_output=True, text=True, check=True).stdout
    return [d for d in yaml.safe_load_all(out) if d]


def key(d):
    return (d["kind"], d["metadata"]["name"])


def guard_proxy(docs):
    return next(d for d in docs if key(d) == ("Deployment", "guard-proxy"))


def annotations(docs):
    return guard_proxy(docs)["spec"]["template"].get("metadata", {}).get("annotations", {})


def runs_proxy_py(docs):
    c = guard_proxy(docs)["spec"]["template"]["spec"]["containers"][0]
    return c.get("command") == ["python", "/app/proxy.py"]


ai_ns = yaml.safe_load((AI_LAYER / "kustomization.yaml").read_text())["namespace"]
instrumentations = {d["metadata"]["name"]: d for d in yaml.safe_load_all(
    (REPO / "gitops/ai-layer-otel/instrumentation.yaml").read_text()) if d and d.get("kind") == "Instrumentation"}


def otel_checks(docs, label):
    """The Go build's OTEL_* contract on one render. Returns whether every check passed."""
    before = len(failures)
    ann = annotations(docs)
    injects = {k: v for k, v in ann.items() if k.startswith(INJECT)}
    check(f"{label}: the pod's one injection annotation is {SDK} (the Operator injects neither of two, #782)",
          list(injects) == [SDK], str(injects))
    inst = instrumentations.get(ann.get(SDK))
    check(f"{label}: it names an Instrumentation gitops/ai-layer-otel ships in the pod's namespace ({ann.get(SDK)})",
          inst is not None and inst["metadata"].get("namespace") == ai_ns)
    spec = (inst or {}).get("spec", {})
    endpoint = urlsplit((spec.get("exporter") or {}).get("endpoint", ""))
    check(f"{label}: the exporter endpoint is the collector's OTLP/HTTP port, http://...:4318 ({endpoint.geturl()})",
          endpoint.scheme == "http" and endpoint.port == 4318 and bool(endpoint.hostname))
    cr_env = {e["name"]: e.get("value") for e in spec.get("env", [])}
    check(f"{label}: the Instrumentation sets OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf; grpc stops the Go proxy",
          cr_env.get("OTEL_EXPORTER_OTLP_PROTOCOL") == "http/protobuf", str(cr_env.get("OTEL_EXPORTER_OTLP_PROTOCOL")))
    check(f"{label}: no OTLP setting in the Instrumentation says grpc or port 4317",
          not any(n.startswith("OTEL_EXPORTER_OTLP") and ("grpc" in str(v) or ":4317" in str(v))
                  for n, v in cr_env.items()), str(cr_env))

    proxy = guard_proxy(docs)["spec"]["template"]["spec"]["containers"][0]
    check(f"{label}: container 0 is proxy, the container inject-sdk falls back to", proxy["name"] == "proxy")
    env = {e["name"]: e for e in proxy.get("env", [])}
    # The Operator adds no variable a container already sets, so a pod-level OTLP setting would override the CR.
    pinned = sorted(n for n in env if n.startswith("OTEL_EXPORTER_OTLP"))
    check(f"{label}: the proxy sets no OTEL_EXPORTER_OTLP_* itself, so the Instrumentation's 4318 and http/protobuf "
          f"apply ({pinned})", not pinned)
    check(f"{label}: OTEL_SERVICE_NAME is burritobot, or the Operator names the service after the Deployment (#265)",
          env.get("OTEL_SERVICE_NAME", {}).get("value") == "burritobot")
    check(f"{label}: OTEL_RESOURCE_ATTRIBUTES names the service burritobot",
          "service.name=burritobot" in env.get("OTEL_RESOURCE_ATTRIBUTES", {}).get("value", "").split(","))
    capture = env.get("OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT", {}).get("value")
    check(f"{label}: content capture is still OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT, a capture mode "
          f"({capture})", capture in CAPTURE_MODES)
    return len(failures) == before


committed = render(AI_LAYER)
wired = COMPONENT in (yaml.safe_load((AI_LAYER / "kustomization.yaml").read_text()).get("components") or [])

print(f"== the {COMPONENT} Component, rendered into the bundle ==")
with tempfile.TemporaryDirectory(dir=REPO) as tmp:
    copy = pathlib.Path(tmp) / "ai-layer"
    shutil.copytree(AI_LAYER, copy, ignore=shutil.ignore_patterns(".git"))
    kfile = copy / "kustomization.yaml"
    k = yaml.safe_load(kfile.read_text())
    if not wired:
        k["components"] = (k.get("components") or []) + [COMPONENT]
        kfile.write_text(yaml.safe_dump(k, sort_keys=False))
    with_otel = render(copy)
    k["components"] = [c for c in k.get("components") or [] if c != COMPONENT] or None
    if k["components"] is None:
        del k["components"]
    kfile.write_text(yaml.safe_dump(k, sort_keys=False))
    without_otel = render(copy)

otel_checks(with_otel, "with the Component")

print("== the Component changes guard-proxy's injection annotation and nothing else ==")
check("it adds and removes no object", {key(d) for d in with_otel} == {key(d) for d in without_otel})
others = {key(d): d for d in without_otel if key(d) != ("Deployment", "guard-proxy")}
check("every other object renders identically", all(others[key(d)] == d for d in with_otel if key(d) in others))
before, after = annotations(without_otel), annotations(with_otel)
check(f"without it, guard-proxy carries {PYTHON}, which proxy.py's spans need", PYTHON in before and SDK not in before)
check(f"it removes {PYTHON} and adds {SDK} with the same Instrumentation",
      {k: v for k, v in before.items() if k != PYTHON} == {k: v for k, v in after.items() if k != SDK}
      and after.get(SDK) == before.get(PYTHON), str((before.get(PYTHON), after.get(SDK))))


def strip_ann(d):
    d = yaml.safe_load(yaml.safe_dump(d))
    d["spec"]["template"]["metadata"].pop("annotations", None)
    return d


check("the rest of the guard-proxy Deployment is untouched (the cutover changes the image and command, not this)",
      strip_ann(guard_proxy(with_otel)) == strip_ann(guard_proxy(without_otel)))

print("== the PreSync gate waits for the Instrumentation inject-sdk names ==")
gate = (AI_LAYER / "otel-ordering-gate.yaml").read_text()
check(f"otel-ordering-gate.yaml waits on instrumentations/{after.get(SDK)} in namespace {ai_ns}",
      f"/namespaces/{ai_ns}/instrumentations/{after.get(SDK)}" in gate)

print("== the committed bundle: a guard-proxy that does not run proxy.py carries the Go OTEL_* env ==")
py = runs_proxy_py(committed)
print(f"  committed guard-proxy runs proxy.py: {py}; {COMPONENT} listed in components: {wired}")
if py:
    # proxy.py needs the Python SDK inject-python mounts; inject-sdk alone would leave it with no tracer and no spans.
    check(f"while proxy.py runs, the committed bundle renders as the bundle without {COMPONENT}",
          committed == without_otel)
else:
    check(f"the Go build runs, so the committed bundle carries its OTEL_* env ({COMPONENT} in components)",
          otel_checks(committed, "committed bundle"))

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All guard-proxy Go OTEL_* environment checks passed.")
