# ABOUTME: Tools-tier half of #959: the vendored Gateway API bundle is still the v1.5.1 release asset, and v1.5.1 is
# ABOUTME: still the sigs.k8s.io/gateway-api version in istio/istio's go.mod at the pinned Istio tag. Reads github.com.
# SUITE: e2e (needs the network: github.com and raw.githubusercontent.com)
# E2E TIER: tools
#
# The offline half (test_gateway_api_crds.py) holds the vendored file to a recorded digest and the Istio pin to a
# recorded Gateway API version. This reads both from the source: it downloads the release asset and hashes it, and it
# reads go.mod at the Istio tag istio.yaml pins. Nothing here skips: no network, or an HTTP error, is a failure with
# the reason printed. A read the network broke (a stall, a reset, an HTTP 408, 429 or 5xx, as artifact_cache.transient
# reads them) is asked again after each wait in artifact_cache.BACKOFF first, each retry printed: on 2026-11-08 the
# release asset answered a 503 after a minute's stall and then came back whole a second later, and the one read this
# made before failed the heavy gate on staging 5985b8dc (#1186). A 404 or any other error fails on the first read.
from __future__ import annotations

import hashlib
import pathlib
import re
import sys
import time
import urllib.error
import urllib.request

import yaml

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import artifact_cache  # noqa: E402
from bootstrap_chart import APPS, REPO  # noqa: E402

BUNDLE = REPO / "gitops/gateway-api/standard-install.yaml"
VERSION = "v1.5.1"
ASSET = f"https://github.com/kubernetes-sigs/gateway-api/releases/download/{VERSION}/standard-install.yaml"

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"\n        {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def fetch(url: str) -> bytes | None:
    attempts = len(artifact_cache.BACKOFF) + 1
    for attempt in range(1, attempts + 1):
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                return r.read()
        except Exception as e:  # noqa: BLE001 - every error is either retried or reported as a failed check
            if attempt == attempts or not artifact_cache.transient(e):
                check(f"{url} is fetched", False, f"{e} (attempt {attempt} of {attempts})")
                return None
            wait = artifact_cache.BACKOFF[attempt - 1]
            print(f"  RETRY {url}: {e} (attempt {attempt} of {attempts}; again in {wait:g}s)", flush=True)
            time.sleep(wait)
    raise AssertionError("unreachable")


print("== the vendored bundle is the release asset ==")
asset = fetch(ASSET)
if asset is not None:
    want, got = hashlib.sha256(asset).hexdigest(), hashlib.sha256(BUNDLE.read_bytes()).hexdigest()
    check(f"{BUNDLE.relative_to(REPO)} is byte for byte {ASSET}", want == got, f"release {want}, vendored {got}")

print("== v1.5.1 is the Gateway API the pinned Istio builds against ==")
istio = [d for d in yaml.safe_load_all((APPS / "istio.yaml").read_text(encoding="utf-8")) if d]
pins = sorted({str(d["spec"]["source"]["targetRevision"]) for d in istio if d["spec"]["source"].get("chart")})
check(f"Istio is on one pin {pins}", len(pins) == 1)
if len(pins) == 1:
    gomod = fetch(f"https://raw.githubusercontent.com/istio/istio/{pins[0]}/go.mod")
    if gomod is not None:
        m = re.search(r"(?m)^\s*sigs\.k8s\.io/gateway-api (v\S+)$", gomod.decode("utf-8"))
        check(f"istio/istio {pins[0]} go.mod requires sigs.k8s.io/gateway-api {VERSION}",
              bool(m) and m.group(1) == VERSION, f"found {m.group(1) if m else None}")

if failures:
    print(f"\nFAIL: {len(failures)} check(s) failed: {failures}")
    sys.exit(1)
print(f"\nPASS: the vendored Gateway API is the {VERSION} release, the version the pinned Istio builds against")
