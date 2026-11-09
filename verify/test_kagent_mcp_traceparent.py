# ABOUTME: Holds #1222's fix in place: the kagent controller starts golang-adk v0.10.1 rebuilt with its MCP client sending
# ABOUTME: the active span's trace context, at the digest images.lock pins, built by images/kagent-mcp-traceparent.
"""Why (#1222, found by #877). Stock golang-adk v0.10.1 builds its MCP client on a plain http.Transport, so a tool call
carries no trace context of the execute_tool span that makes it. In Tempo on watch-it-burn-private every evil-mcp call
was a gateway trace of its own, and every workshop-mcp call hung under the gateway's A2A hop through the traceparent
agent.yaml forwards (#885), not under its tool span. Upstream's fix (kagent-dev/kagent#2809) is only in the 1.0 line,
which renames the CRD group, so question 1138 chose a patched 0.10.1 runtime.

images/kagent-mcp-traceparent/build.sh applies mcp-traceparent.patch to the v0.10.1 tag, runs the patch's Go tests, and
lays the rebuilt /app over upstream's own image, reproducibly, so images.lock pins the digest before
.github/workflows/build-kagent-mcp-traceparent.yml copies it to ghcr.io; kagent.yaml points the controller's
goAgentImage at it.

This holds the pieces together, so none can move alone: the patch injects the active span's context under the header
layer and records no span, the build starts from the release the chart runs and the base digest images.lock pins, the
controller's goAgentImage names the build's tag at the pinned digest, and the workflow builds and copies it. Reverting
the controller to the stock image, or bumping kagent without carrying the fix, goes red here.
"""
import hashlib
import pathlib
import re
import sys

import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
FIX = REPO / "images/kagent-mcp-traceparent"
BUILD = FIX / "build.sh"
PATCH = FIX / "mcp-traceparent.patch"
APP = REPO / "gitops/bootstrap/apps/kagent.yaml"
LOCK = REPO / "images.lock"
TOOLS = REPO / "verify/e2e-tools.lock"
WORKFLOW = REPO / ".github/workflows/build-kagent-mcp-traceparent.yml"
GHCR = "ghcr.io/peopleforrester/watch-it-burn"
SOURCE = "repo:peopleforrester/Unleash_an_Agent_Watch_It_Burn/images/kagent-mcp-traceparent"
failures = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"\n        {detail}" if detail and not ok else ""))
    if not ok:
        failures.append(name)


for p in (BUILD, PATCH, APP, LOCK, TOOLS, WORKFLOW):
    if not p.is_file():
        print(f"FAIL: {p.relative_to(REPO)} is missing", file=sys.stderr)
        sys.exit(1)

build = BUILD.read_text(encoding="utf-8")
code = "\n".join(l for l in build.splitlines() if not l.lstrip().startswith("#"))


def pin(name):
    m = re.search(rf'^{name}="([^"]+)"$', build, re.M)
    return m.group(1) if m else None


print("== the patch injects the active span's trace context and records no span ==")
patch = PATCH.read_bytes()
text = patch.decode("utf-8")
check("build.sh pins the patch's sha256", pin("PATCH_SHA256") == hashlib.sha256(patch).hexdigest(),
      f"build.sh {pin('PATCH_SHA256')}, file {hashlib.sha256(patch).hexdigest()}")
touched = set(re.findall(r"^diff --git a/(\S+) b/", text, re.M))
check("the patch changes the MCP registry and adds its own tests",
      touched == {"go/adk/pkg/mcp/registry.go", "go/adk/pkg/mcp/trace_context_test.go"}, f"{sorted(touched)}")
added = "\n".join(l[1:] for l in text.splitlines() if l.startswith("+") and not l.startswith("+++"))
removed = "\n".join(l[1:] for l in text.splitlines() if l.startswith("-") and not l.startswith("---"))
check("a round tripper injects the global propagator's fields for the request's active span",
      "func (rt *traceContextRoundTripper) RoundTrip(" in added
      and "otel.GetTextMapPropagator().Inject(req.Context(), propagation.HeaderCarrier(req.Header))" in added)
check("it clones the request before it writes a header, and leaves a request with no active span as it came",
      "req = req.Clone(req.Context())" in added
      and "if !trace.SpanContextFromContext(req.Context()).IsValid() {\n\t\treturn rt.base.RoundTrip(req)" in added)
check("it is the innermost layer, under headerRoundTripper, so the active span outranks a forwarded traceparent",
      "var httpTransport http.RoundTripper = &traceContextRoundTripper{base: baseTransport}" in added
      and "\t\t\tbase:           httpTransport," in added and "\t\t\tbase:           baseTransport," in removed)
files = dict(re.findall(r"^diff --git a/(\S+) b/\S+\n(.*?)(?=^diff --git |\Z)", text, re.M | re.S))
registry_added = "\n".join(l[1:] for l in files.get("go/adk/pkg/mcp/registry.go", "").splitlines()
                           if l.startswith("+") and not l.startswith("+++") and not l[1:].lstrip().startswith("//"))
check("it records no client span: registry.go gains no otelhttp layer and starts no tracer",
      "otelhttp" not in registry_added and ".Tracer(" not in registry_added and ".Start(" not in registry_added,
      registry_added)
tests = set(re.findall(r"^func (Test\w+)\(t \*testing\.T\)", added, re.M))
want_tests = {"TestCreateTransport_InjectsActiveSpan", "TestCreateTransport_ActiveSpanOutranksForwardedTraceparent",
              "TestCreateTransport_NoSpanKeepsForwardedTraceparent", "TestCreateTransport_RecordsNoSpan",
              "TestCallTool_CarriesExecuteToolSpan"}
check("the patch's tests cover the active span, a forwarded traceparent, no span, no client span, and a real tools/call",
      want_tests <= tests, f"missing {sorted(want_tests - tests)}")

print("== the build starts from the release the chart runs ==")
app = yaml.safe_load(APP.read_text(encoding="utf-8"))
chart = str(app["spec"]["source"]["targetRevision"])
check(f"build.sh builds kagent v{chart}, the chart kagent.yaml deploys; a kagent bump rebuilds the patch, or drops it "
      "for a release that carries kagent-dev/kagent#2809", pin("KAGENT_TAG") == f"v{chart}", f"got {pin('KAGENT_TAG')!r}")
check("build.sh holds the tag to its commit, the one upstream's binary names",
      pin("KAGENT_COMMIT") == "a3d26eaf2eda002d9c9104d2a8f6f27a2ff23ec3", f"got {pin('KAGENT_COMMIT')!r}")
check("build.sh fixes the Go toolchain and GOAMD64 to upstream's binary's",
      pin("GO_TOOLCHAIN") == "go1.27.1" and pin("GO_AMD64") == "v2", f"{pin('GO_TOOLCHAIN')} {pin('GO_AMD64')}")
tools = re.search(r"^crane\s+v(\S+)\s", TOOLS.read_text(encoding="utf-8"), re.M)
check("build.sh insists on the crane verify/e2e-tools.lock pins",
      tools is not None and f'== "{tools.group(1)}" ]]' in build, f"e2e-tools.lock crane {tools and tools.group(1)}")
lock_rows = {}
for line in LOCK.read_text(encoding="utf-8").splitlines():
    parts = line.split()
    if len(parts) >= 3 and not line.startswith("#"):
        lock_rows[parts[0]] = parts
base = pin("BASE") or ""
name, _, digest = base.partition("@")
row = lock_rows.get(name)
check(f"the base is upstream's golang-adk:{chart} at the index digest images.lock pins",
      name == f"ghcr.io/kagent-dev/kagent/golang-adk:{chart}" and row is not None and row[1] == digest,
      f"base {base!r}, row {row}")
tag = pin("TAG")
check("the tag names the release and the patch", tag == f"golang-adk-{chart}-mcptrace", f"got {tag!r}")
test_at = code.find("go test -count=1 ./adk/pkg/mcp/")
build_at = code.find("go build -trimpath")
check("the patch's Go tests run before the binary is built", 0 <= test_at < build_at, f"test at {test_at}, build at {build_at}")
check("the runtime binary is built as kagent's Makefile builds it, and goes in as /app",
      '-o "${tmp}/layer/app" ./adk/cmd/main.go' in code and '-cf "${tmp}/app.tar" app' in code)

print("== the controller starts the build, at the pinned digest ==")
image = (app["spec"]["source"]["helm"]["valuesObject"].get("controller") or {}).get("goAgentImage") or {}
# The controller's resolveRuntimeImage: registry "/" repository ":" tag, as GO_IMAGE_* in its ConfigMap name them.
ref = f"{image.get('registry')}/{image.get('repository')}:{image.get('tag')}"
want = f"{GHCR}:{tag}@sha256:"
check(f"controller.goAgentImage is {tag} at a digest", ref.startswith(want)
      and re.fullmatch(r"[0-9a-f]{64}", ref[len(want):]) is not None, f"renders {ref}")
row = lock_rows.get(ref)
check("images.lock has a row for it, with the same digest and this build as its source",
      row is not None and f"{ref.split('@', 1)[0]}@{row[1]}" == ref and row[2] == SOURCE, f"row {row}")

print("== the workflow builds it and copies only the pinned digest ==")
wf = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
on = wf.get(True) or wf.get("on") or {}
paths = (on.get("push") or {}).get("paths") or []
check("the workflow runs on a change to images/kagent-mcp-traceparent or images.lock",
      "images/kagent-mcp-traceparent/**" in paths and "images.lock" in paths, f"{paths}")
check("it runs on staging and main", set((on.get("push") or {}).get("branches") or []) >= {"staging", "main"})
check("it runs again when image_cache.py or git_mirror.py changes",
      {"verify/image_cache.py", "verify/git_mirror.py"} <= set(paths), f"{paths}")
runs = "\n".join(s.get("run", "") for j in wf["jobs"].values() for s in j["steps"])
check("it builds with build.sh into a loopback registry", "bash images/kagent-mcp-traceparent/build.sh 127.0.0.1:" in runs)
loop = re.search(r"for tag in ([^;]+); do", runs)
check("it copies the build's tag", loop is not None and loop.group(1).split() == [tag], f"{loop and loop.group(1)}")
check("the copy goes through ghcr_version_tag.py's crane: row with images.lock as the pin file",
      'python3 scripts/ghcr_version_tag.py "crane:127.0.0.1:5000/peopleforrester/watch-it-burn:${tag}" '
      f'"{GHCR}:${{tag}}" images.lock' in runs)

print("== the build reads its base and its source from the host artifact cache (#1216) ==")
check("build.sh names the kagent repository once, as KAGENT_URL",
      pin("KAGENT_URL") == "https://github.com/kagent-dev/kagent.git" and code.count("github.com/kagent-dev/kagent.git") == 1)
check("the source comes from git_mirror.py's bare mirror at KAGENT_COMMIT, not a clone of GitHub",
      'git_mirror.py" ensure "${KAGENT_URL}" "${KAGENT_COMMIT}")"' in code
      and re.search(r"git (-c \S+ )*clone[^\n]*https?://", code) is None and "--branch" not in code)
check("the mirror's tag and the checkout's HEAD must both be KAGENT_COMMIT, or the build stops naming both hashes",
      "is ${tagged} in the mirror ${mirror}, not ${KAGENT_COMMIT}" in code and "is at ${head}, not ${KAGENT_COMMIT}" in code)
check("the base comes from image_cache.py's layout of its pinned digest, as its amd64 image, pushed to loopback",
      'image_cache.py" platform-layout "${BASE}" "${tmp}/base" linux/amd64)"' in code
      and '[[ "${pushed}" == "${LOCAL_BASE}" ]]' in code)
appends = re.findall(r"append --platform linux/amd64 -b \"([^\"]+)\"", code)
check("crane append builds on the loopback copy, and on nothing else", appends == ["${LOCAL_BASE}"], f"{appends}")
remote = sorted(set(re.findall(r"(?:ghcr\.io|docker\.io|github\.com)[^\s\"]*", code)) - {base, "github.com/kagent-dev/kagent.git"})
check("no other remote reference is in build.sh's code", remote == [], f"{remote}")

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    sys.exit(1)
print("The kagent controller starts golang-adk v0.10.1 with its MCP client sending the active span's trace context.")
