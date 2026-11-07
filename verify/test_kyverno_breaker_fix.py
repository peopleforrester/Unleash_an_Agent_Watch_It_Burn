# ABOUTME: Kyverno's two report-writing controllers run v1.19.1 with upstream's breaker fix (#1015): the Application's
# ABOUTME: image overrides, images.lock's rows, images/kyverno/build.sh, the patch and push-kyverno.yml agree. Offline.
"""Why (#1015). Challenge 2 has a student read the PolicyReport for the villain Deployment deploy_app just created. On
both KubeCon clusters no report came: Kyverno's admission controller and reports controller each guard their report
writes with a circuit breaker, and in v1.19.1 that breaker stays open for the rest of the pod's life once the watch
behind its EphemeralReport counter is answered 410 Gone. On 2026-11-07 the reports controller on
watch-it-burn-community had dropped 14386 of 14704 background-scan writes, every one after the first 318, and the
admission controller 717 of 720, with no EphemeralReport on the cluster to be over the limit. A pod restart clears it
until the next 410. Upstream fixed it in kyverno/kyverno#17085, which is in v1.20.0-rc.1 and in no 1.19 release.

So gitops/bootstrap/apps/kyverno.yaml runs both controllers from images/kyverno/build.sh's build: upstream's v1.19.1
image with its binary rebuilt from the v1.19.1 commit plus #17085's diff. This holds what has to stay together:

  - the two image overrides name the tags build.sh builds, at the digests images.lock pins (build:images/kyverno);
  - build.sh builds the Kyverno version the chart deploys (VERSIONS.lock), on upstream's own images at the digests
    images.lock pins for them, from the commit that tag names, with the patch, and runs the recovery tests first;
  - the patch is #17085's: it changes the counter and the watcher and adds upstream's recovery tests, and it carries
    the three changes that are the fix (the counter lists again and starts a new watcher, the List takes the label
    selector, and a 410 on the watch request stops the watcher);
  - push-kyverno.yml builds with build.sh on loopback and pushes each tag only through scripts/ghcr_version_tag.py;
  - the background and cleanup controllers, which write no reports through the breaker, stay upstream's.

When the chart moves off v1.19.1 this fails on the version, which is the reminder to drop both overrides at a release
that has #17085 rather than run a 1.19 binary under a newer chart. verify/test_kyverno_build_digest.py (tools tier)
rebuilds both images and holds their digests to the pins.
"""
from __future__ import annotations

import pathlib
import re
import sys

import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
APP = REPO / "gitops/bootstrap/apps/kyverno.yaml"
BUILD = REPO / "images/kyverno/build.sh"
PATCH = REPO / "images/kyverno/17085-breaker-recovery.patch"
WORKFLOW = REPO / ".github/workflows/push-kyverno.yml"
LOCK = REPO / "images.lock"
failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"\n        {detail}" if detail and not ok else ""))
    if not ok:
        failures.append(name)


def const(text: str, name: str) -> str | None:
    m = re.search(rf'^{name}="([^"]*)"$', text, re.M)
    return m.group(1) if m else None


def lock_rows() -> dict[str, tuple[str, str]]:
    rows = {}
    for line in LOCK.read_text(encoding="utf-8").splitlines():
        if line and not line.startswith("#"):
            parts = line.split()
            rows[parts[0]] = (parts[1], parts[2])
    return rows


build = BUILD.read_text(encoding="utf-8")
patch = PATCH.read_text(encoding="utf-8")
workflow = WORKFLOW.read_text(encoding="utf-8")
values = yaml.safe_load(APP.read_text(encoding="utf-8"))["spec"]["source"]["helm"]["valuesObject"]
rows = lock_rows()
lock_app = re.findall(r"^kyverno\s.*\bapp (v\S+)", (REPO / "VERSIONS.lock").read_text(encoding="utf-8"), re.M)

print("== build.sh builds the deployed Kyverno, on upstream's pinned images ==")
tag = const(build, "KYVERNO_TAG")
check("VERSIONS.lock names one Kyverno app version", len(set(lock_app)) == 1, str(lock_app))
check(f"build.sh's KYVERNO_TAG is the deployed {lock_app[0] if lock_app else '?'}",
      bool(lock_app) and tag == lock_app[0], f"KYVERNO_TAG={tag!r}")
commit = const(build, "KYVERNO_COMMIT")
check("build.sh checks the tag's commit (40 hex) before it builds", bool(commit and re.fullmatch(r"[0-9a-f]{40}", commit))
      and '[[ "${head}" == "${KYVERNO_COMMIT}" ]]' in build)
check("build.sh pins the Go toolchain with GOTOOLCHAIN and checks it", bool(re.fullmatch(r"go1\.\d+\.\d+", const(build, "GO_TOOLCHAIN") or ""))
      and 'export GOTOOLCHAIN="${GO_TOOLCHAIN}"' in build and '"${got_go}" == "${GO_TOOLCHAIN}"' in build)
check("build.sh builds with -trimpath and no VCS stamp, so the binaries reproduce",
      "-trimpath -buildvcs=false" in build and "CGO_ENABLED=0" in build)
check("build.sh applies the patch, then runs upstream's recovery tests, before it builds",
      0 < build.find('git -C "${src}" apply "${PATCH}"') < build.find("go test -count=1 ./pkg/breaker/ ./cmd/kyverno/watch/")
      < build.find("build_one cmd/kyverno "))
check("build.sh refuses any registry but loopback", r'^127\.0\.0\.1:[0-9]+$' in build)
for name, upstream in (("KYVERNO_BASE", "kyverno"), ("REPORTS_BASE", "reports-controller")):
    base = const(build, name) or ""
    ref, _, digest = base.partition("@")
    check(f"{name} is upstream's {upstream}:{tag} at the digest images.lock pins",
          ref == f"reg.kyverno.io/kyverno/{upstream}:{tag}" and rows.get(ref, ("",))[0] == digest, base)

print("== the Application runs build.sh's two images at images.lock's digests ==")
overrides = {
    "admission controller": (values.get("admissionController", {}).get("container", {}).get("image") or {}, "KYVERNO_REF"),
    "reports controller": (values.get("reportsController", {}).get("image") or {}, "REPORTS_REF"),
}
for who, (image, refname) in overrides.items():
    ref = const(build, refname) or ""
    registry, _, rest = ref.partition("/")
    repository, _, built_tag = rest.partition(":")
    t, _, digest = str(image.get("tag", "")).partition("@")
    check(f"the {who} pulls {registry}/{repository}", image.get("registry") == registry and image.get("repository") == repository,
          str(image))
    check(f"the {who}'s tag is build.sh's {built_tag}, pinned by digest", t == built_tag and bool(re.fullmatch(r"sha256:[0-9a-f]{64}", digest)),
          str(image.get("tag")))
    row = rows.get(f"{ref}@{digest}")
    check(f"images.lock has {ref}@{digest[:19]}... from build:images/kyverno", row == (digest, "build:images/kyverno"), str(row))
    check(f"push-kyverno.yml keeps {built_tag} on its pin",
          bool(re.search(rf"^\s+for tag in [^;\n]*\b{re.escape(built_tag)}\b", workflow, re.M)))
for who in ("backgroundController", "cleanupController"):
    check(f"{who} stays upstream's image (it writes no reports through the breaker)", "image" not in values.get(who, {}))

print("== the patch is kyverno/kyverno#17085 ==")
files = re.findall(r"^diff --git a/(\S+) b/", patch, re.M)
check("it changes the counter and the watcher and adds upstream's recovery tests",
      files == ["cmd/kyverno/watch/watcher.go", "pkg/breaker/resource_counter.go", "pkg/breaker/resource_counter_recovery_test.go"],
      str(files))
added = "\n".join(line[1:] for line in patch.splitlines() if line.startswith("+") and not line.startswith("+++"))
check("the counter lists again and starts a new watcher when the old one ends", "func (c *counter) resync(" in added)
check("the List takes the counter's label selector", "tweakListOptions(&listOptions)" in added)
check("a 410 on the watch request stops the watcher instead of retrying it forever",
      "apierrors.IsResourceExpired(err) || apierrors.IsGone(err)" in added)
check("isRunning is read and written atomically", "isRunning.Store(true)" in added)

print("== push-kyverno.yml ==")
check("it runs on images/kyverno/** and images.lock", "'images/kyverno/**'" in workflow and "'images.lock'" in workflow)
check("it builds with build.sh on loopback", "bash images/kyverno/build.sh 127.0.0.1:5000" in workflow)
check("it pushes only through scripts/ghcr_version_tag.py, as a crane: build checked against images.lock",
      'python3 scripts/ghcr_version_tag.py "crane:127.0.0.1:5000/peopleforrester/watch-it-burn:${tag}" '
      '"ghcr.io/peopleforrester/watch-it-burn:${tag}" images.lock' in workflow)

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("Both report-writing Kyverno controllers run v1.19.1 with kyverno/kyverno#17085, pinned and built from this repo.")
