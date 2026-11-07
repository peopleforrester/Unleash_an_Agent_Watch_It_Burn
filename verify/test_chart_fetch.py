# ABOUTME: Holds verify/chart_fetch.py: a network error is retried and then named, any other fails at once, and a
# ABOUTME: chart's tarball fetched once is read from the cache, against a stub helm the test writes (#1028).
"""In run 17993 charts.external-secrets.io answered one index read with EOF and test_datadog_log_services_render.py
failed on it; run alone right after, it passed (#1028). The tier's chart fetches now go through chart_fetch.pull(),
and this holds what it does, offline: the stub helm below fails as told (a count of failures, then a pull that untars
a chart) and logs each call, and the waits between attempts are recorded, never slept."""
from __future__ import annotations

import os
import pathlib
import subprocess
import sys
import tempfile
import threading

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import chart_fetch  # noqa: E402

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        failures.append(name)
        if detail:
            print(f"        {detail}")


# The stub: each call is a line in $STUB_DIR/calls. It fails while $STUB_DIR/fail holds a count above zero, printing
# $STUB_DIR/error, and otherwise writes, into --destination, the tarball of a one-file chart named by its pull reference,
# as `helm pull` names it: <chart>-<version>.tgz.
STUB = """#!/usr/bin/env bash
echo "$*" >>"$STUB_DIR/calls"
n=$(cat "$STUB_DIR/fail" 2>/dev/null || echo 0)
if [ "$n" -gt 0 ]; then
    echo $((n - 1)) >"$STUB_DIR/fail"
    cat "$STUB_DIR/error" >&2
    exit 1
fi
ref="$2"; dir=""
while [ $# -gt 0 ]; do [ "$1" = --destination ] && dir="$2"; shift; done
name="${ref##*/}"
src=$(mktemp -d "$STUB_DIR/src.XXXXXX")
mkdir -p "$src/$name"
printf 'apiVersion: v2\\nname: %s\\nversion: 1.0.0\\n' "$name" >"$src/$name/Chart.yaml"
tar -czf "$dir/$name-1.0.0.tgz" -C "$src" "$name"
rm -rf "$src"
"""

EOF_ERROR = ('Error: looks like "https://charts.external-secrets.io" is not a valid chart repository or cannot be '
             'reached: Get "https://charts.external-secrets.io/index.yaml": EOF\n')
NOT_FOUND = 'Error: chart "external-secrets" version "9.9.9" not found in https://charts.external-secrets.io repository\n'
REPO, CHART, VERSION = "https://charts.external-secrets.io", "external-secrets", "0.19.2"


class Stub:
    def __init__(self, root: pathlib.Path):
        self.dir = root / "stub"
        self.dir.mkdir()
        self.helm = self.dir / "helm"
        self.helm.write_text(STUB)
        self.helm.chmod(0o755)
        os.environ["STUB_DIR"] = str(self.dir)

    def fail(self, times: int, error: str) -> None:
        (self.dir / "fail").write_text(str(times))
        (self.dir / "error").write_text(error)

    def calls(self) -> list[str]:
        f = self.dir / "calls"
        return f.read_text().splitlines() if f.exists() else []

    def reset(self) -> None:
        for name in ("calls", "fail", "error"):
            (self.dir / name).unlink(missing_ok=True)


def pull(stub: Stub, cache: pathlib.Path, waits: list[float], repo: str = REPO, chart: str = CHART,
         version: str = VERSION):
    try:
        return chart_fetch.pull(str(stub.helm), repo, chart, version, cache=cache, sleep=waits.append), None
    except chart_fetch.ChartFetchError as e:
        return None, str(e)


print("== Helm's network errors are told from the rest ==")
for err in (EOF_ERROR, "Get \"https://x/index.yaml\": unexpected EOF", "read tcp 10.0.0.1:443: connection reset by peer",
            "dial tcp: lookup charts.jetstack.io: no such host", "net/http: TLS handshake timeout",
            "Get \"https://x\": context deadline exceeded (Client.Timeout exceeded while awaiting headers)",
            "failed to fetch https://x/index.yaml : 503 Service Unavailable",
            "unexpected status from GET request to https://ghcr.io/v2/x: 429 Too Many Requests", "dial tcp: i/o timeout"):
    check(f"a network error: {err.strip()[:90]}", chart_fetch.is_network_error(err))
for err in (NOT_FOUND, "failed to fetch https://x/index.yaml : 404 Not Found",
            "Error: unauthorized: authentication required", "Error: invalid_reference: invalid tag"):
    check(f"not a network error: {err.strip()[:90]}", not chart_fetch.is_network_error(err))

print("== the reference Helm is given: an HTTP repository, or an OCI registry with or without its scheme ==")
check("an HTTP repository is --repo", chart_fetch.chart_ref(REPO, CHART) == [CHART, "--repo", REPO])
check("ghcr.io/kagent-dev/kagent/helm is an OCI reference",
      chart_fetch.chart_ref("ghcr.io/kagent-dev/kagent/helm", "kagent") == ["oci://ghcr.io/kagent-dev/kagent/helm/kagent"])
check("oci://ghcr.io/x/ keeps one scheme and no doubled slash",
      chart_fetch.chart_ref("oci://ghcr.io/x/", "c") == ["oci://ghcr.io/x/c"])

with tempfile.TemporaryDirectory() as t:
    root = pathlib.Path(t)
    stub = Stub(root)

    print("== an EOF is retried, and the chart comes back on the next attempt ==")
    cache, waits = root / "cache1", []
    stub.fail(1, EOF_ERROR)
    got, err = pull(stub, cache, waits)
    check(f"the chart is fetched as a tarball holding its Chart.yaml ({err})",
          got is not None and chart_fetch.holds_chart(got, CHART))
    check("it lives in the cache, named by chart and version",
          got is not None and got.parent == cache and got.name.startswith(f"{CHART}-{VERSION}-")
          and got.suffix == ".tgz", str(got))
    check(f"Helm was asked twice ({len(stub.calls())})", len(stub.calls()) == 2, str(stub.calls()))
    check(f"one wait came between them, the first backoff ({waits})", waits == [chart_fetch.BACKOFF[0]])
    check("the pull asks for the pinned version, into a directory of its own",
          all(f"pull {CHART} --repo {REPO} --version {VERSION} --destination " in c for c in stub.calls()),
          str(stub.calls()))
    # Tarballs alone: an untarred chart's files would be read by the offline tests that scan the tree for text, as
    # test_mesh_enrollment.py read three cached charts' istio.io/dataplane-mode when they were untarred.
    check("the cache holds the tarball and nothing else, no staging directory and no untarred chart",
          sorted(p.name for p in cache.iterdir()) == [got.name] if got else False, str(list(cache.iterdir())))

    print("== a chart in the cache is read from there: Helm is not asked again ==")
    stub.reset()
    waits = []
    again, err = pull(stub, cache, waits)
    check(f"the same path comes back ({err})", again == got, f"{again} != {got}")
    check(f"Helm was not called ({stub.calls()})", stub.calls() == [])
    other, _ = pull(stub, cache, waits, version="0.19.3")
    check("another version is a fetch of its own, in a directory of its own",
          other is not None and other != got and len(stub.calls()) == 1, f"{other} {stub.calls()}")

    print("== an error that is not a network one fails at once, in Helm's words ==")
    stub.reset()
    cache, waits = root / "cache2", []
    stub.fail(5, NOT_FOUND)
    got, err = pull(stub, cache, waits, version="9.9.9")
    check("no chart comes back", got is None)
    check(f"the error names the chart, version and repository and is Helm's line ({err})",
          err is not None and err.startswith(f"helm pull {CHART} 9.9.9 from {REPO}: ") and err.endswith(NOT_FOUND.strip()))
    check(f"Helm was asked once ({len(stub.calls())}), with no wait ({waits})", len(stub.calls()) == 1 and waits == [])
    check("the cache holds nothing", not any(cache.iterdir()), str(list(cache.iterdir())))

    print("== a network error on every attempt fails after the last, naming it ==")
    stub.reset()
    cache, waits = root / "cache3", []
    stub.fail(chart_fetch.ATTEMPTS, EOF_ERROR)
    got, err = pull(stub, cache, waits)
    check("no chart comes back", got is None)
    check(f"the error is Helm's EOF and says each attempt failed ({err})",
          err is not None and err.startswith(f"helm pull {CHART} {VERSION} from {REPO}: ")
          and "index.yaml\": EOF" in err and f"on each of {chart_fetch.ATTEMPTS} attempts" in err)
    check(f"Helm was asked {chart_fetch.ATTEMPTS} times ({len(stub.calls())})", len(stub.calls()) == chart_fetch.ATTEMPTS)
    check(f"each backoff was waited in turn ({waits})", waits == list(chart_fetch.BACKOFF))
    check("the cache holds nothing", not any(cache.iterdir()), str(list(cache.iterdir())))

    print("== the retry is printed, so a tier log shows the blip it rode out ==")
    stub.reset()
    stub.fail(1, EOF_ERROR)
    probe = (f"import sys; sys.path.insert(0, {str(chart_fetch.VERIFY)!r}); import chart_fetch\n"
             f"chart_fetch.pull({str(stub.helm)!r}, {REPO!r}, {CHART!r}, {VERSION!r}, backoff=(0,))\n")
    r = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True,
                       env={**os.environ, "CHART_CACHE": str(root / "cache4")})
    check(f"the probe fetched the chart (exit {r.returncode})", r.returncode == 0, r.stderr)
    check("CHART_CACHE moved the cache", any((root / "cache4").glob(f"{CHART}-{VERSION}-*.tgz")))
    check("one RETRY line names the chart and the attempt",
          [ln.strip() for ln in r.stdout.splitlines() if "RETRY" in ln][:1]
          == [f"RETRY helm pull {CHART} {VERSION} from {REPO}: {EOF_ERROR.strip()} (attempt 1 of 2; again in 0s)"],
          r.stdout)

    print("== two fetches of one chart at once both get the chart, and one copy stays ==")
    stub.reset()
    cache = root / "cache5"
    results: list = []
    threads = [threading.Thread(target=lambda: results.append(pull(stub, cache, []))) for _ in range(4)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    paths = {r[0] for r in results}
    check(f"each fetch got the one cached chart ({results})",
          len(results) == 4 and len(paths) == 1 and None not in paths and all(chart_fetch.holds_chart(p, CHART) for p in paths))
    check("the cache holds that tarball alone, no staging directory",
          [p.name for p in cache.iterdir()] == [next(iter(paths)).name] if paths and None not in paths else False,
          str(list(cache.iterdir())))

print("== the tier tests that fetch upstream charts go through chart_fetch ==")
VERIFY = chart_fetch.VERIFY
for name in ("test_datadog_log_services_render.py", "app_render.py", "test_image_registry_render.py",
             "test_enforce_floor.py", "test_kubearmor_config_render.py"):
    text = (VERIFY / name).read_text()
    check(f"{name} fetches with chart_fetch.pull and never asks a repository from helm template or helm pull itself",
          "chart_fetch.pull(" in text and "\"--repo\"" not in text and "\"pull\"" not in text)

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    sys.exit(1)
print("Chart fetches retry a network error, fail at once on any other, and read a fetched chart from the cache.")
