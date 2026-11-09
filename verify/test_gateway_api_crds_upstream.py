# ABOUTME: Tools-tier half of #959: the vendored Gateway API bundle is still the v1.5.1 release asset, and v1.5.1 is
# ABOUTME: still the sigs.k8s.io/gateway-api version in istio/istio's go.mod at the pinned Istio tag. Reads github.com.
# SUITE: e2e (needs the network: github.com and raw.githubusercontent.com)
# E2E TIER: tools
#
# The offline half (test_gateway_api_crds.py) holds the vendored file to a recorded digest and the Istio pin to a
# recorded Gateway API version. This reads both from the source: it downloads the release asset and hashes it, and it
# reads go.mod at the Istio tag istio.yaml pins. Nothing here skips: no network, or an HTTP error, is a failure with
# the reason printed.
#
# A fetch the network broke (an HTTP 408, 429 or 5xx, a timeout, a reset or refused connection, a failed name lookup,
# a body cut short; artifact_cache.transient() is the rule) is asked again after each wait in artifact_cache.BACKOFF,
# each retry printed. Staging b344e331's heavy gate failed this test with the same inputs that passed before and after
# it, on the gate host and in CI (#1248); the old fetch caught only URLError and TimeoutError, once. A 404 and every
# other error fail on the first attempt, naming the error's type, and the last attempt's error is the failure.
# test_gateway_api_crds_upstream_fetch.py holds fetch() offline.
from __future__ import annotations

import hashlib
import pathlib
import re
import sys
import time
import urllib.request
from collections.abc import Callable

import yaml

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import artifact_cache  # noqa: E402
from bootstrap_chart import APPS, REPO  # noqa: E402

BUNDLE = REPO / "gitops/gateway-api/standard-install.yaml"
VERSION = "v1.5.1"
ASSET = f"https://github.com/kubernetes-sigs/gateway-api/releases/download/{VERSION}/standard-install.yaml"
TIMEOUT = 60

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"\n        {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def read_url(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "wib-verify"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return r.read()


def fetch(url: str, *, read: Callable[[str], bytes] = read_url, sleep: Callable[[float], None] = time.sleep,
          backoff: tuple[float, ...] = artifact_cache.BACKOFF) -> bytes | None:
    """The bytes at url, or None with a FAIL check naming the last error. A transient error is retried."""
    attempts = len(backoff) + 1
    for attempt in range(1, attempts + 1):
        try:
            return read(url)
        except Exception as e:  # every error is a failure with its reason; only a transient one is asked again
            if attempt < attempts and artifact_cache.transient(e):
                wait = backoff[attempt - 1]
                print(f"  RETRY {url}: {type(e).__name__}: {e} (attempt {attempt} of {attempts}; again in {wait:g}s)",
                      flush=True)
                sleep(wait)
                continue
            check(f"{url} is fetched", False, f"{type(e).__name__}: {e} (attempt {attempt} of {attempts})")
            return None
    raise AssertionError("unreachable")


def main() -> int:
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
        return 1
    print(f"\nPASS: the vendored Gateway API is the {VERSION} release, the version the pinned Istio builds against")
    return 0


if __name__ == "__main__":
    sys.exit(main())
