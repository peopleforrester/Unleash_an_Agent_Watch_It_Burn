# ABOUTME: Holds #1015's fix in place: Kyverno's admission, reports and background controllers run v1.19.1 with upstream's
# ABOUTME: breaker fix (kyverno#17085), at the digests images.lock pins, built by images/kyverno-counter-fix from the patch.
"""Why (#1015). The Kyverno controllers that write reports (admission, reports and background) pass each one through a
breaker that is open while its report counter's watch is down. In v1.19.1 the counter starts one RetryWatcher and
never replaces it, and the watcher stops for good when the apiserver answers 410 (too old resource version). From then
on every report is dropped until the pod restarts: on 2026-11-08 the reports controller on watch-it-burn-community had
dropped 26085 of 26403 background-scan reports and its admission controller 1297 of 1300, and no Pod created in agent
after the first minutes of their start had a PolicyReport, so the lab's Challenge 2 report line printed nothing.

Upstream fixed it on main in 7c7042fb (kyverno#17085); no 1.19 release carries it. images/kyverno-counter-fix/build.sh
applies that commit to v1.19.1 and lays the three rebuilt binaries over upstream's own images, reproducibly, so
images.lock pins the digests before .github/workflows/build-kyverno-counter-fix.yml copies them to ghcr.io.

This holds the pieces together, so none can move alone: the patch is the upstream commit and carries the recovery,
the build starts from the release and the base digests the rest of the chart runs, the three controllers that gate
reports on the breaker (admission, reports and background) point at the build's tags at the digests images.lock pins,
and the workflow builds and copies all three. Reverting one to the stock image, or bumping Kyverno without carrying the
fix, goes red here.
"""
import hashlib
import pathlib
import re
import sys

import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
FIX = REPO / "images/kyverno-counter-fix"
BUILD = FIX / "build.sh"
PATCH = FIX / "pr17085.patch"
APP = REPO / "gitops/bootstrap/apps/kyverno.yaml"
LOCK = REPO / "images.lock"
TOOLS = REPO / "verify/e2e-tools.lock"
WORKFLOW = REPO / ".github/workflows/build-kyverno-counter-fix.yml"
UPSTREAM_COMMIT = "7c7042fb5fd9f6855ed1c5287d1233867a160b5f"
GHCR = "ghcr.io/peopleforrester/watch-it-burn"
SOURCE = "repo:peopleforrester/Unleash_an_Agent_Watch_It_Burn/images/kyverno-counter-fix"
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


def pin(name):
    m = re.search(rf'^{name}="([^"]+)"$', build, re.M)
    return m.group(1) if m else None


def assoc(name):
    """The [key]="value" pairs of a bash associative array build.sh declares."""
    m = re.search(rf"^declare -A {name}=\((.*?)^\)", build, re.M | re.S)
    return dict(re.findall(r'\[([\w-]+)\]="([^"]+)"', m.group(1))) if m else {}


print("== the patch is upstream's fix ==")
patch = PATCH.read_bytes()
text = patch.decode("utf-8")
check("build.sh pins the patch's sha256", pin("PATCH_SHA256") == hashlib.sha256(patch).hexdigest(),
      f"build.sh {pin('PATCH_SHA256')}, file {hashlib.sha256(patch).hexdigest()}")
check(f"the patch is kyverno commit {UPSTREAM_COMMIT[:10]} (kyverno#17085)",
      text.startswith(f"From {UPSTREAM_COMMIT} ") and "(#17085)" in text.splitlines()[3] + text.splitlines()[4])
touched = set(re.findall(r"^diff --git a/(\S+) b/", text, re.M))
check("the patch changes the breaker's counter and the RetryWatcher",
      {"pkg/breaker/resource_counter.go", "cmd/kyverno/watch/watcher.go"} <= touched, f"{sorted(touched)}")
added = "\n".join(l[1:] for l in text.splitlines() if l.startswith("+") and not l.startswith("+++"))
check("the counter lists again and starts a new watcher when its watcher stops",
      "func (c *counter) resync(" in added and "restarted, err := c.resync(ctx, client, gvr, tweakListOptions)" in added)
check("the watcher stops, instead of retrying a dead resource version, when the watch request answers 410",
      "apierrors.IsResourceExpired(err) || apierrors.IsGone(err)" in added)
check("the watcher's running flag is atomic", "isRunning           atomic.Bool" in added)

print("== the build starts from the release the chart runs ==")
app = yaml.safe_load(APP.read_text(encoding="utf-8"))
values = app["spec"]["source"]["helm"]["valuesObject"]
deployed = str(values["admissionController"]["podLabels"]["tags.datadoghq.com/version"])
check(f"build.sh builds Kyverno {deployed}, the version the chart and VERSIONS.lock name (test_kyverno_version_pins)",
      pin("KYVERNO_TAG") == deployed, f"got {pin('KYVERNO_TAG')!r}")
check("build.sh holds the tag to its commit, the one the running controllers log",
      pin("KYVERNO_COMMIT") == "40ec788d48bb28d83dbf85538e962a59db9d45c6", f"got {pin('KYVERNO_COMMIT')!r}")
check("build.sh fixes the Go toolchain", bool(re.fullmatch(r"go1\.\d+\.\d+", pin("GO_TOOLCHAIN") or "")))
check("the build names itself, so a controller's version= line tells it from the stock image",
      pin("BUILD_VERSION") == f"{deployed}-pr17085", f"got {pin('BUILD_VERSION')!r}")
tools = re.search(r"^crane\s+v(\S+)\s", TOOLS.read_text(encoding="utf-8"), re.M)
check("build.sh insists on the crane verify/e2e-tools.lock pins",
      tools is not None and f'== "{tools.group(1)}" ]]' in build, f"e2e-tools.lock crane {tools and tools.group(1)}")

lock_rows = {}
for line in LOCK.read_text(encoding="utf-8").splitlines():
    parts = line.split()
    if len(parts) >= 3 and not line.startswith("#"):
        lock_rows[parts[0]] = parts
bases = assoc("BASE")
tags = assoc("TAG")
bins = {"kyverno": ("admissionController", "container"), "reports-controller": ("reportsController",),
        "background-controller": ("backgroundController",)}
check("build.sh builds exactly the three controllers that gate reports on the breaker the patch fixes",
      set(bases) == set(bins) == set(tags), f"BASE {sorted(bases)}, TAG {sorted(tags)}")
for b in bins:
    base = bases.get(b, "")
    name, _, digest = base.partition("@")
    row = lock_rows.get(name)
    check(f"{b}'s base is upstream's {deployed} image at the index digest images.lock pins",
          name == f"reg.kyverno.io/kyverno/{b}:{deployed}" and row is not None and row[1] == digest,
          f"base {base!r}, row {row}")
    check(f"{b}'s tag names the release and the patch", tags.get(b) == f"{'kyverno' if b == 'kyverno' else 'kyverno-' + b}"
          f"-{deployed}-pr17085", f"got {tags.get(b)!r}")

print("== the three controllers run the build, at the pinned digests ==")
for b, path in bins.items():
    node = values
    for key in path:
        node = node.get(key, {})
    image = node.get("image") or {}
    # The chart's kyverno.image helper: registry "/" repository ":" tag.
    ref = f"{image.get('registry')}/{image.get('repository')}:{image.get('tag')}"
    want = f"{GHCR}:{tags.get(b)}@sha256:"
    check(f"{'.'.join(path)}.image is {tags.get(b)} at a digest", ref.startswith(want) and
          re.fullmatch(r"sha256:[0-9a-f]{64}", ref[len(want) - len("sha256:"):]) is not None, f"renders {ref}")
    row = lock_rows.get(ref)
    check(f"images.lock has a row for it, with the same digest and this build as its source",
          row is not None and f"{ref.split('@', 1)[0]}@{row[1]}" == ref and row[2] == SOURCE, f"row {row}")

print("== the workflow builds all three and copies only the pinned digests ==")
wf = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
on = wf.get(True) or wf.get("on") or {}
paths = (on.get("push") or {}).get("paths") or []
check("the workflow runs on a change to images/kyverno-counter-fix or images.lock",
      "images/kyverno-counter-fix/**" in paths and "images.lock" in paths, f"{paths}")
check("it runs on staging and main", set((on.get("push") or {}).get("branches") or []) >= {"staging", "main"})
runs = "\n".join(s.get("run", "") for j in wf["jobs"].values() for s in j["steps"])
check("it builds with build.sh into a loopback registry", "bash images/kyverno-counter-fix/build.sh 127.0.0.1:" in runs)
loop = re.search(r"for tag in ([^;]+); do", runs)
check("it copies all three tags", loop is not None and set(loop.group(1).split()) == set(tags.values()),
      f"{loop and loop.group(1)}")
check("each copy goes through ghcr_version_tag.py's crane: row with images.lock as the pin file",
      'python3 scripts/ghcr_version_tag.py "crane:127.0.0.1:5000/peopleforrester/watch-it-burn:${tag}" '
      f'"{GHCR}:${{tag}}" images.lock' in runs)

print("== the build reads its bases and its source from the host artifact cache (#1216) ==")
code = "\n".join(l for l in build.splitlines() if not l.lstrip().startswith("#"))
check("build.sh names the kyverno repository once, as KYVERNO_URL",
      pin("KYVERNO_URL") == "https://github.com/kyverno/kyverno.git" and code.count("github.com/kyverno/kyverno.git") == 1)
check("the source comes from git_mirror.py's bare mirror at KYVERNO_COMMIT, not a clone of GitHub",
      'git_mirror.py" ensure "${KYVERNO_URL}" "${KYVERNO_COMMIT}")"' in code
      and re.search(r"git (-c \S+ )*clone[^\n]*https?://", code) is None and "--branch" not in code,
      "want python3 ${VERIFY}/git_mirror.py ensure ${KYVERNO_URL} ${KYVERNO_COMMIT}, and no network clone")
check("the clone reads the mirror and checks out the pinned commit, detached",
      'clone --quiet --shared --no-checkout "${mirror}" "${tmp}/src"' in code
      and 'checkout --quiet --detach "${KYVERNO_COMMIT}"' in code)
check("the mirror's tag must name KYVERNO_COMMIT, or the build stops naming both hashes",
      'rev-parse --verify --quiet "refs/tags/${KYVERNO_TAG}^{commit}"' in code
      and "is ${tagged} in the mirror ${mirror}, not ${KYVERNO_COMMIT}" in code)
check("the checkout's HEAD must be KYVERNO_COMMIT, or the build stops naming both hashes",
      "is at ${head}, not ${KYVERNO_COMMIT}" in code)
check("each base comes from image_cache.py's layout of its pinned digest, as its amd64 image",
      'image_cache.py" platform-layout "${BASE[${bin}]}" "${tmp}/base-${bin}" linux/amd64)"' in code)
check("crane pushes it to the loopback registry, where it must land on that image's digest",
      'LOCAL_BASE[${bin}]="${addr}/kyverno-base/${bin}@${digest}"' in code
      and 'pushed="$("${crane}" --insecure push "${tmp}/base-${bin}" "${addr}/kyverno-base/${bin}")"' in code
      and '[[ "${pushed}" == "${LOCAL_BASE[${bin}]}" ]]' in code)
appends = re.findall(r"append --platform linux/amd64 -b \"([^\"]+)\"", code)
check("crane append builds on the loopback copy, and on nothing else", appends == ["${LOCAL_BASE[${bin}]}"], f"{appends}")
check("crane append is not asked for base annotations, so where the base was read from is not in the digest",
      "--set-base-image-annotations" not in code)
remote = sorted(set(re.findall(r"(?:reg\.kyverno\.io|ghcr\.io|docker\.io|github\.com)[^\s\"]*", code))
                - {b for b in bases.values()} - {"github.com/kyverno/kyverno.git", "github.com/kyverno/kyverno/pkg/version.BuildVersion=${BUILD_VERSION}"})
check("no other remote reference is in build.sh's code: the bases are pins, the URL is the mirror's key",
      remote == [], f"{remote}")
check("the workflow runs again when image_cache.py or git_mirror.py changes",
      {"verify/image_cache.py", "verify/git_mirror.py"} <= set(paths), f"{paths}")

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    sys.exit(1)
print("Kyverno's admission, reports and background controllers run v1.19.1 with the breaker fix, at the pinned digests.")
