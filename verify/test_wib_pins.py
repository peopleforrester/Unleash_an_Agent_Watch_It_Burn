# ABOUTME: Offline half of #1282: holds verify/wib_pins.py's reading of images.lock rows and manifests, and its
# ABOUTME: verdict on each digest's sha256-<digest>.sig tag, to fixtures and a stub ghcr.io, with no network.
"""verify/test_wib_digests_signed.py asks ghcr.io for real; this checks, on text and answers it owns, that the reading
finds every form a digest of ours is pinned in and that a 404 on the .sig tag, or on the image, fails the digest."""
from __future__ import annotations

import io
import json
import pathlib
import sys
import types
import urllib.error

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "verify"))
import ghcr_pull  # noqa: E402
from wib_pins import lock_pins, manifest_pins, merge, sig_tag, unsigned  # noqa: E402

ghcr_pull._sleep = lambda s: None  # a stub busy answer is retried without waiting

A = "sha256:" + "a" * 64
B = "sha256:" + "b" * 64
C = "sha256:" + "c" * 64
D = "sha256:" + "d" * 64
E = "sha256:" + "e" * 64
WIB = "peopleforrester/watch-it-burn"

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail and not ok else ""))
    if not ok:
        failures.append(name)


print("== images.lock rows ==")
LOCK = "\n".join((
    "# ghcr.io/peopleforrester/watch-it-burn:commented@" + E + " " + E + " none -",
    f"ghcr.io/{WIB}:web-terminal-ttyd-1.7.7@{A} {A} repo:x 2026-11-04",
    f"ghcr.io/{WIB}:llm-guard-0.3.16-cpu.5 {B} repo:y 2026-11-06",
    f"ghcr.io/{WIB}:tool-pin-grpcio-1.84.1 - build:x -",
    f"ghcr.io/peopleforrester/lab-platform/web:v1@{C} {C} repo:z -",
    "",
))
got = lock_pins(LOCK)
check("a row with name@digest and a row with a bare tag both pin their digest column",
      got == {(WIB, A): ["images.lock:2"], (WIB, B): ["images.lock:3"]}, str(got))
check("a - digest, another package and a comment pin nothing",
      all(d not in {k[1] for k in got} for d in (C, E)), str(got))

print("== manifests ==")
DEPLOY = "\n".join((
    "spec:",
    f"  containers:",
    f"    - image: ghcr.io/{WIB}:workshop-mcp-mcp-1.29.1@{A} # built here",
    f"    # image: ghcr.io/{WIB}:old@{E}",
    f"    - image: ghcr.io/peopleforrester/lab-platform/mirror/library/node:24@{C}",
    "",
))
got = manifest_pins(DEPLOY, "d.yaml")
check("an image: key with a trailing comment pins its digest; a commented-out one and another package do not",
      got == {(WIB, A): ["d.yaml:3"]}, str(got))

HELM = "\n".join((
    "        admissionController:",
    "          container:",
    "            image:",
    "              registry: ghcr.io",
    f"              repository: {WIB}",
    f'              tag: "kyverno-v1.19.1-pr17085@{B}"',
    "            resources: {}",
    "        reportsController:",
    "          image:",
    f"            repository: {WIB}",
    "            pullPolicy: IfNotPresent",
    f"            tag: kyverno-reports-controller@{D}",
    "",
))
got = manifest_pins(HELM, "kyverno.yaml")
check("a Helm values block that splits repository and tag pins the tag's digest, with a key between them",
      got == {(WIB, B): ["kyverno.yaml:6"], (WIB, D): ["kyverno.yaml:12"]}, str(got))

KUSTOMIZE = "\n".join((
    "images:",
    f"  - name: ghcr.io/{WIB}",
    f"    digest: {C}",
    "",
))
got = manifest_pins(KUSTOMIZE, "kustomization.yaml")
check("a kustomize images: entry pins its digest", got == {(WIB, C): ["kustomization.yaml:3"]}, str(got))

SHELL = f'readonly IMAGE="ghcr.io/{WIB}:nginx-1.27-alpine@{E}"\nFROM ghcr.io/{WIB}-next@{D}\n'
got = manifest_pins(SHELL, "s.sh")
check("a shell variable pins its digest, and a package the policy's watch-it-burn* glob also takes is its own",
      got == {(WIB, E): ["s.sh:1"], (WIB + "-next", D): ["s.sh:2"]}, str(got))

merged = merge(lock_pins(LOCK), manifest_pins(DEPLOY, "d.yaml"))
check("a digest images.lock and a manifest both pin is one pin naming both places",
      merged[(WIB, A)] == ["images.lock:2", "d.yaml:3"], str(merged))

print("== the verdict, against a stub ghcr.io ==")
check("the .sig tag is cosign v2's", sig_tag(A) == "sha256-" + "a" * 64 + ".sig")


class Resp(io.BytesIO):
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


def registry(present: set[str], token_ok: bool = True):
    """A stub opener (an object with open(), as ghcr_pull.open_url takes): a token for the pull scope, and 200 for each manifest ref in present, 404 for the rest."""
    asked: list[str] = []

    def opener(req, timeout=None):
        url = req if isinstance(req, str) else req.full_url
        asked.append(url)
        if "/token?" in url:
            if not token_ok:
                raise urllib.error.HTTPError(url, 401, "Unauthorized", {}, None)
            return Resp(json.dumps({"token": "t"}).encode())
        check(f"a manifest is asked with HEAD and the anonymous token ({url[-30:]})",
              req.get_method() == "HEAD" and req.get_header("Authorization") == "Bearer t")
        if url.rsplit("/manifests/", 1)[1] in present:
            return Resp(b"")
        raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)
    return types.SimpleNamespace(open=opener), asked


pins = {(WIB, A): ["images.lock:2"], (WIB, B): ["images.lock:3", "kyverno.yaml:6"]}
opener, asked = registry({A, sig_tag(A), B, sig_tag(B)})
check("every digest served with its .sig tag passes", unsigned(pins, opener) == [])
check("both the image and its .sig tag are asked for each digest, with one token",
      sum("/token?" in u for u in asked) == 1
      and {u.rsplit("/", 1)[1] for u in asked if "/manifests/" in u} == {A, sig_tag(A), B, sig_tag(B)}, str(asked))

opener, _ = registry({A, sig_tag(A), B})
got = unsigned(pins, opener)
check("a digest with no .sig tag fails, naming the digest, where it is pinned and the 404",
      len(got) == 1 and got[0].startswith(f"ghcr.io/{WIB}@{B} (images.lock:3, kyverno.yaml:6): no {sig_tag(B)} tag")
      and "HTTP 404" in got[0], str(got))

opener, _ = registry({sig_tag(A), B, sig_tag(B)})
got = unsigned(pins, opener)
check("a digest ghcr.io does not serve fails as not served, before its signature is asked",
      len(got) == 1 and f"@{A} " in got[0] and "the image itself is not served (HTTP 404" in got[0], str(got))

opener, _ = registry({A, sig_tag(A)}, token_ok=False)
got = unsigned({(WIB, A): ["images.lock:2"]}, opener)
check("a package with no anonymous token fails", len(got) == 1 and "no anonymous token" in got[0], str(got))

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for name in failures:
        print(f"  - {name}")
    sys.exit(1)
print("verify/wib_pins.py reads every pin form and fails each unsigned or unserved digest.")
