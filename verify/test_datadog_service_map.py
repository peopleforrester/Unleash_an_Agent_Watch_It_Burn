# ABOUTME: Live Datadog acceptance for PRD #27 — asserts AI-layer Service Map edges and both
# ABOUTME: log<->trace pivot directions via the Datadog API (terminal step, NOT a static CI gate).
#
# Unlike verify/test_observability.py (which statically validates the YAML manifests), this script
# talks to the LIVE Datadog API and therefore requires DD_API_KEY + DD_APP_KEY in the environment and
# a real trace_id harvested from a recent guard-proxy request on a running cluster. Run it as the final
# acceptance step after the AI-layer stack is deployed and a test workload has driven traffic through
# guard-proxy -> agentgateway -> kagent. Stdlib only (urllib), matching the rest of verify/.
#
# Usage:
#   DD_API_KEY=... DD_APP_KEY=... python3 verify/test_datadog_service_map.py [<trace_id>]
#   - With no trace_id: runs the Service Map edge assertion only.
#   - With a trace_id:  also runs both log<->trace pivot assertions.
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

DD_API_KEY = os.environ["DD_API_KEY"]
DD_APP_KEY = os.environ["DD_APP_KEY"]
DD_SITE = os.environ.get("DD_SITE", "datadoghq.com")
DD_ENV = os.environ.get("DD_ENV", "production")  # locked UST SDLC env (PRD #27 M1)
HEADERS = {"DD-API-KEY": DD_API_KEY, "DD-APPLICATION-KEY": DD_APP_KEY}

# Internal Service Map edges the AI layer is expected to render. guard-proxy sets peer.service in code
# (M2); agentgateway->kagent is the OTTL fallback (M3). kagent->Bedrock is intentionally NOT asserted:
# Datadog auto-infers the AWS dependency, and the PRD permits 3 internal edges when Bedrock is
# external-only (PRD #27 M3/M5 Decision Log). Add ("kagent", "bedrock") here only if verify-at-build
# shows Bedrock is NOT auto-inferred AND the M3 transform was extended to stamp it.
EXPECTED_EDGES = [
    ("guard-proxy", "agentgateway"),
    ("agentgateway", "kagent"),
]

failures = []


def check(name, cond):
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        failures.append(name)


def _request(method, url, params=None, body=None):
    """Issue a Datadog API call and return the parsed JSON. Raises on HTTP error with the body."""
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    headers = dict(HEADERS)
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:400]
        raise SystemExit(f"Datadog API {method} {url} failed: {exc.code} {detail}")


def _downstreams(deps, service):
    """Extract the downstream-service list for `service` from a /service_dependencies payload.

    The endpoint's value shape has varied by Datadog version: either a bare list of downstream
    names, or a dict with a "calls" key. Handle both so the assertion is not brittle to the shape.
    """
    val = deps.get(service)
    if val is None:
        return []
    if isinstance(val, dict):
        return val.get("calls", [])
    return val


def test_service_map_edges():
    """Assert every expected service-dependency edge is present (GET /api/v1/service_dependencies)."""
    now = int(time.time())
    deps = _request(
        "GET",
        f"https://api.{DD_SITE}/api/v1/service_dependencies",
        params={"env": DD_ENV, "start": now - 1800, "end": now},  # last 30 minutes
    )
    for caller, callee in EXPECTED_EDGES:
        check(f"Service Map edge {caller} -> {callee}", callee in _downstreams(deps, caller))


def test_log_trace_forward_pivot(trace_id):
    """Forward pivot: querying logs by trace_id returns >=1 record (POST /api/v2/logs/events/search)."""
    resp = _request(
        "POST",
        f"https://api.{DD_SITE}/api/v2/logs/events/search",
        body={"filter": {"query": f"trace_id:{trace_id}"}, "page": {"limit": 5}},
    )
    count = len(resp.get("data", []))
    check(f"Forward pivot: >=1 log record for trace_id {trace_id} (found {count})", count >= 1)


def test_log_trace_reverse_pivot(trace_id):
    """Reverse pivot: the APM trace for trace_id contains a guard-proxy span (GET /api/v1/trace/<id>)."""
    resp = _request("GET", f"https://api.{DD_SITE}/api/v1/trace/{trace_id}")
    trace = resp.get("trace", resp)
    spans = trace.get("spans", []) if isinstance(trace, dict) else []
    has_guard = any(s.get("service") == "guard-proxy" for s in spans)
    check(f"Reverse pivot: guard-proxy span present in trace {trace_id}", has_guard)


if __name__ == "__main__":
    test_service_map_edges()
    if len(sys.argv) > 1:
        tid = sys.argv[1]
        test_log_trace_forward_pivot(tid)
        test_log_trace_reverse_pivot(tid)
    else:
        print("  SKIP  log<->trace pivots (no trace_id argument; pass one from a recent live run)")

    if failures:
        print(f"\nFAILED: {len(failures)} check(s)")
        sys.exit(1)
    print("\nAll Datadog Service Map + correlation checks passed.")
