# ABOUTME: Holds verify/chart_fetch.py: a chart is served from the host artifact cache by its charts.lock sum (#1118), an
# ABOUTME: unlocked chart or a mismatch fails by name, and a miss retries a network error (#1028), against a stub helm.
"""In run 17993 charts.external-secrets.io answered one index read with EOF and test_datadog_log_services_render.py
failed on it; run alone right after, it passed (#1028). The tier's chart fetches go through chart_fetch.pull(), which
since #1118 serves each chart from the host artifact cache by the SHA-256 verify/charts.lock records, and asks Helm only
on a miss. This holds what it does, offline: the stub helm below fails as told (a count of failures, then a pull that
copies a fixture tarball the test built, so its sum is known) and logs each call, the waits between attempts are
recorded, never slept, and the cache root and the lock are the test's own, in a directory outside every worktree.

It also holds that charts.lock names every chart the repo pins and nothing else, so a version bump without a new lock
line fails here, offline, and not in a render in the tools tier."""
from __future__ import annotations

import contextlib
import gzip
import hashlib
import io
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tarfile
import threading

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import artifact_cache  # noqa: E402
import chart_fetch  # noqa: E402
import charts_lock  # noqa: E402

failures: list[str] = []

# The cache root and fetch log are the test's own: a root or log the host's environment names is not this test's input.
for var in (*artifact_cache.ROOT_VARS, "ARTIFACT_FETCH_LOG"):
    os.environ.pop(var, None)


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        failures.append(name)
        if detail:
            print(f"        {detail}")


# The stub: each call is a line in $STUB_DIR/calls. It fails while $STUB_DIR/fail holds a count above zero, printing
# $STUB_DIR/error.<that count> when there is one, else $STUB_DIR/error, and otherwise copies $STUB_DIR/serve/<chart>-<version>.tgz into --destination, named as `helm pull`
# names it; with no such fixture it fails as Helm does on a version the repository does not list.
STUB = """#!/usr/bin/env bash
echo "$*" >>"$STUB_DIR/calls"
n=$(cat "$STUB_DIR/fail" 2>/dev/null || echo 0)
if [ "$n" -gt 0 ]; then
    echo $((n - 1)) >"$STUB_DIR/fail"
    if [ -f "$STUB_DIR/error.$n" ]; then cat "$STUB_DIR/error.$n" >&2; else cat "$STUB_DIR/error" >&2; fi
    exit 1
fi
ref="$2"; dir=""; ver=""
while [ $# -gt 0 ]; do
    case "$1" in --destination) dir="$2" ;; --version) ver="$2" ;; esac
    shift
done
name="${ref##*/}"
src="$STUB_DIR/serve/$name-$ver.tgz"
[ -f "$src" ] || { echo "Error: chart \\"$name\\" version \\"$ver\\" not found" >&2; exit 1; }
cp "$src" "$dir/$name-$ver.tgz"
"""

EOF_ERROR = ('Error: looks like "https://charts.external-secrets.io" is not a valid chart repository or cannot be '
             'reached: Get "https://charts.external-secrets.io/index.yaml": EOF\n')
# Run 17888's error as its log kept it (#938, #989): Helm's wrapper for a GET of index.yaml that failed, its cause cut off.
UNREACHABLE_17888 = ('Error: looks like "https://charts.external-secrets.io" is not a valid chart repository or cannot be '
                     'reached: Get "https://charts.external-secrets.io/index.yaml"\n')
NOT_FOUND = 'Error: chart "external-secrets" version "9.9.9" not found in https://charts.external-secrets.io repository\n'
REPO, CHART, VERSION = "https://charts.external-secrets.io", "external-secrets", "0.19.2"


def chart_tgz(name: str, version: str) -> bytes:
    """A one-file chart's tarball, byte for byte the same on every build (gzip and tar mtimes are 0), so its sum is known."""
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb", mtime=0) as gz, tarfile.open(fileobj=gz, mode="w") as tf:
        data = f"apiVersion: v2\nname: {name}\nversion: {version}\n".encode()
        info = tarfile.TarInfo(f"{name}/Chart.yaml")
        info.size = len(data)
        tf.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


SERVED = {v: chart_tgz(CHART, v) for v in (VERSION, "0.19.3")}
SUMS = {**{v: sha(b) for v, b in SERVED.items()}, "9.9.9": "9" * 64}


class Stub:
    def __init__(self, root: pathlib.Path):
        self.dir = root / "stub"
        (self.dir / "serve").mkdir(parents=True)
        self.helm = self.dir / "helm"
        self.helm.write_text(STUB)
        self.helm.chmod(0o755)
        for v, b in SERVED.items():
            (self.dir / "serve" / f"{CHART}-{v}.tgz").write_bytes(b)
        os.environ["STUB_DIR"] = str(self.dir)

    def fail(self, times: int, error: str) -> None:
        (self.dir / "fail").write_text(str(times))
        (self.dir / "error").write_text(error)

    def fail_each(self, errors: list[str]) -> None:
        """Fail once per error, in order: the stub reads error.<count left>, so the first error is error.<len>."""
        self.fail(len(errors), "")
        for left, error in zip(range(len(errors), 0, -1), errors):
            (self.dir / f"error.{left}").write_text(error)

    def calls(self) -> list[str]:
        f = self.dir / "calls"
        return f.read_text().splitlines() if f.exists() else []

    def reset(self) -> None:
        for name in ("calls", "fail", "error"):
            (self.dir / name).unlink(missing_ok=True)
        for f in self.dir.glob("error.*"):
            f.unlink()


def write_lock(path: pathlib.Path) -> pathlib.Path:
    path.write_text("# a fixture lock\n" + "".join(f"{CHART}  {v}  {s}  {REPO}\n" for v, s in SUMS.items()))
    return path


def pull(stub: Stub, cache: pathlib.Path, lock: pathlib.Path, waits: list[float], repo: str = REPO, chart: str = CHART,
         version: str = VERSION):
    try:
        return chart_fetch.pull(str(stub.helm), repo, chart, version, cache=cache, lock=lock, sleep=waits.append), None
    except chart_fetch.ChartFetchError as e:
        return None, str(e)


def entries(cache: pathlib.Path) -> list[str]:
    """What the cache's sha256/ directory holds, but the per-sum lock files the helper leaves: no staging directory,
    temp file or untarred chart may be among them."""
    d = cache / "sha256"
    return sorted(p.name for p in d.iterdir() if not p.name.endswith(".lock")) if d.is_dir() else []


def fetch_log(cache: pathlib.Path) -> list[list[str]]:
    f = cache / "fetch.log"
    return [ln.split("\t") for ln in f.read_text().splitlines()] if f.exists() else []


print("== Helm's network errors are told from the rest ==")
for err in (EOF_ERROR, UNREACHABLE_17888,
            'Error: looks like "https://x" is not a valid chart repository or cannot be reached: Get "https://x/index.yaml":'
            ' net/http: request canceled', "Get \"https://x/index.yaml\": unexpected EOF", "read tcp 10.0.0.1:443: connection reset by peer",
            "dial tcp: lookup charts.jetstack.io: no such host", "net/http: TLS handshake timeout",
            "Get \"https://x\": context deadline exceeded (Client.Timeout exceeded while awaiting headers)",
            "failed to fetch https://x/index.yaml : 503 Service Unavailable",
            "unexpected status from GET request to https://ghcr.io/v2/x: 429 Too Many Requests", "dial tcp: i/o timeout"):
    check(f"a network error: {err.strip()[:90]}", chart_fetch.is_network_error(err))
for err in (NOT_FOUND, "failed to fetch https://x/index.yaml : 404 Not Found",
            'Error: looks like "https://x" is not a valid chart repository or cannot be reached: failed to fetch'
            ' https://x/index.yaml : 404 Not Found',
            "Error: unauthorized: authentication required", "Error: invalid_reference: invalid tag"):
    check(f"not a network error: {err.strip()[:90]}", not chart_fetch.is_network_error(err))

print("== the reference Helm is given: an HTTP repository, or an OCI registry with or without its scheme ==")
check("an HTTP repository is --repo", chart_fetch.chart_ref(REPO, CHART) == [CHART, "--repo", REPO])
check("ghcr.io/kagent-dev/kagent/helm is an OCI reference",
      chart_fetch.chart_ref("ghcr.io/kagent-dev/kagent/helm", "kagent") == ["oci://ghcr.io/kagent-dev/kagent/helm/kagent"])
check("oci://ghcr.io/x/ keeps one scheme and no doubled slash",
      chart_fetch.chart_ref("oci://ghcr.io/x/", "c") == ["oci://ghcr.io/x/c"])

base = artifact_cache.scratch_dir("chart-fetch-test-")
try:
    root = base
    stub = Stub(root)
    lock = write_lock(root / "charts.lock")
    want = artifact_cache.path_for(SUMS[VERSION], root / "cache1")

    print("== a miss: an EOF is retried, and the chart comes back on the next attempt, under its sum ==")
    cache, waits = root / "cache1", []
    stub.fail(1, EOF_ERROR)
    got, err = pull(stub, cache, lock, waits)
    check(f"the chart is the cache's file for the lock's sum, <root>/sha256/<hex> ({err})", got == want, str(got))
    check("holding the bytes Helm pulled, a tarball with its Chart.yaml",
          got is not None and got.read_bytes() == SERVED[VERSION] and chart_fetch.holds_chart(got, CHART))
    check(f"Helm was asked twice ({len(stub.calls())})", len(stub.calls()) == 2, str(stub.calls()))
    check(f"one wait came between them, the first backoff ({waits})", waits == [chart_fetch.BACKOFF[0]])
    check("the pull asks for the pinned version, into a directory of its own",
          all(f"pull {CHART} --repo {REPO} --version {VERSION} --destination " in c for c in stub.calls()),
          str(stub.calls()))
    # Tarballs alone: an untarred chart's files would be read by the offline tests that scan the tree for text, as
    # test_mesh_enrollment.py read three cached charts' istio.io/dataplane-mode when they were untarred.
    check("the cache holds the tarball and nothing else, no staging directory and no untarred chart",
          entries(cache) == [SUMS[VERSION]], str(entries(cache)))
    log = fetch_log(cache)
    check("the miss is one line in the cache's fetch log, naming the chart, the sum and the bytes",
          len(log) == 1 and log[0][1:] == [chart_fetch.source(REPO, CHART, VERSION), SUMS[VERSION],
                                           str(len(SERVED[VERSION])), "ok"], str(log))

    print("== a hit is served from the cache: Helm is not asked again, and nothing is fetched ==")
    stub.reset()
    stub.fail(99, EOF_ERROR)  # a Helm that cannot reach anything: a hit must not need it
    waits = []
    again, err = pull(stub, cache, lock, waits)
    check(f"the same path comes back ({err})", again == got, f"{again} != {got}")
    check(f"Helm was not called ({stub.calls()})", stub.calls() == [])
    check("the fetch log is unchanged", len(fetch_log(cache)) == 1, str(fetch_log(cache)))
    stub.reset()
    other, _ = pull(stub, cache, lock, waits, version="0.19.3")
    check("another version is a fetch of its own, under its own sum",
          other == artifact_cache.path_for(SUMS["0.19.3"], cache) and len(stub.calls()) == 1, f"{other} {stub.calls()}")

    print("== a chart the lock does not pin fails by name, and is never fetched ==")
    stub.reset()
    got, err = pull(stub, cache, lock, [], version="0.20.0")
    check(f"it fails, naming the chart, the version, the repository and the lock ({err})",
          got is None and err is not None and f"chart {CHART} 0.20.0 from {REPO} is not in {lock}" in err
          and "never fetched unpinned" in err)
    check("and the versions the lock does pin", err is not None and "it pins 0.19.2, 0.19.3, 9.9.9" in err, str(err))
    check(f"Helm was not called ({stub.calls()})", stub.calls() == [])
    got, err = pull(stub, cache, lock, [], chart="cert-manager")
    check(f"a chart the lock has no line for at all fails the same way ({err})",
          got is None and err is not None and f"chart cert-manager {VERSION} from {REPO} is not in {lock}" in err
          and stub.calls() == [])
    bad = root / "bad.lock"
    bad.write_text(f"{CHART} {VERSION} {SUMS[VERSION]}\n")
    got, err = pull(stub, cache, bad, [])
    check(f"a malformed lock line fails, naming the file and the line ({err})",
          got is None and err is not None and f"{bad}:1 is malformed" in err and stub.calls() == [])

    print("== a cached file that does not match its sum is never used, and never fetched over (#1004) ==")
    stub.reset()
    cache = root / "cache-tampered"
    tampered = artifact_cache.path_for(SUMS[VERSION], cache)
    tampered.parent.mkdir(parents=True)
    tampered.write_bytes(b"not the pinned chart")
    got, err = pull(stub, cache, lock, [])
    check(f"it fails, naming the path and both sums ({err})",
          got is None and err is not None and str(tampered) in err and SUMS[VERSION] in err
          and sha(b"not the pinned chart") in err)
    check(f"Helm was not called ({stub.calls()})", stub.calls() == [])
    check("the file is left as it was, for a person to look at", tampered.read_bytes() == b"not the pinned chart")

    print("== a repository that serves other bytes under the pinned version fails by name ==")
    stub.reset()
    cache = root / "cache-other"
    (stub.dir / "serve" / f"{CHART}-{VERSION}.tgz").write_bytes(chart_tgz(CHART, "rebuilt"))
    got, err = pull(stub, cache, lock, [])
    (stub.dir / "serve" / f"{CHART}-{VERSION}.tgz").write_bytes(SERVED[VERSION])
    check(f"it fails, naming the chart, the pinned sum and the one pulled ({err})",
          got is None and err is not None and err.startswith(f"chart {CHART} {VERSION} from {REPO}: ")
          and SUMS[VERSION] in err and sha(chart_tgz(CHART, "rebuilt")) in err)
    check("and nothing is put in the cache", entries(cache) == [], str(entries(cache)))

    print("== an error that is not a network one fails at once, in Helm's words ==")
    stub.reset()
    cache, waits = root / "cache2", []
    stub.fail(5, NOT_FOUND)
    got, err = pull(stub, cache, lock, waits, version="9.9.9")
    check("no chart comes back", got is None)
    check(f"the error names the chart, version and repository and is Helm's line ({err})",
          err is not None and err.startswith(f"helm pull {CHART} 9.9.9 from {REPO}: ") and err.endswith(NOT_FOUND.strip()))
    check(f"Helm was asked once ({len(stub.calls())}), with no wait ({waits})", len(stub.calls()) == 1 and waits == [])
    check("the cache holds nothing", entries(cache) == [], str(entries(cache)))

    print("== a network error on every attempt fails after the last, naming it ==")
    stub.reset()
    cache, waits = root / "cache3", []
    stub.fail(chart_fetch.ATTEMPTS, EOF_ERROR)
    got, err = pull(stub, cache, lock, waits)
    check("no chart comes back", got is None)
    check(f"the error is Helm's EOF and says each attempt failed ({err})",
          err is not None and err.startswith(f"helm pull {CHART} {VERSION} from {REPO}: ")
          and "index.yaml\": EOF" in err and f"on each of {chart_fetch.ATTEMPTS} attempts" in err)
    check(f"Helm was asked {chart_fetch.ATTEMPTS} times ({len(stub.calls())})", len(stub.calls()) == chart_fetch.ATTEMPTS)
    check(f"each backoff was waited in turn ({waits})", waits == list(chart_fetch.BACKOFF))
    check("the cache holds nothing", entries(cache) == [], str(entries(cache)))

    print("== run 17888's line, a repository that cannot be reached, is fetched again and the next answer used (#989) ==")
    stub.reset()
    cache, waits = root / "cache17888", []
    stub.fail(1, UNREACHABLE_17888)
    got, err = pull(stub, cache, lock, waits)
    check(f"the chart comes back from the second attempt ({err})",
          err is None and got is not None and got.read_bytes() == SERVED[VERSION])
    check(f"Helm was asked twice ({len(stub.calls())})", len(stub.calls()) == 2, str(stub.calls()))

    print("== a repository that stays unreachable fails, and every attempt's error is printed or returned (#989) ==")
    stub.reset()
    cache, waits = root / "cache-outage", []
    causes = [f'Error: looks like "{REPO}" is not a valid chart repository or cannot be reached: Get "{REPO}/index.yaml": '
              f"cause {i}\n" for i in range(1, chart_fetch.ATTEMPTS + 1)]
    stub.fail_each(causes)
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        got, err = pull(stub, cache, lock, waits)
    printed = out.getvalue()
    check("no chart comes back, so the render fails", got is None)
    check(f"Helm was asked {chart_fetch.ATTEMPTS} times, not once more ({len(stub.calls())})",
          len(stub.calls()) == chart_fetch.ATTEMPTS, str(stub.calls()))
    for i in range(1, chart_fetch.ATTEMPTS):
        check(f"attempt {i}'s error is printed on its RETRY line",
              f"cause {i} (attempt {i} of {chart_fetch.ATTEMPTS};" in printed, printed)
    check(f"the last attempt's error is the one returned ({err})",
          err is not None and f"cause {chart_fetch.ATTEMPTS} (a network error on each of" in err)
    check("the cache holds nothing", entries(cache) == [], str(entries(cache)))

    print("== the retry is printed, so a tier log shows the blip it rode out; the root comes from the environment ==")
    stub.reset()
    stub.fail(1, EOF_ERROR)
    probe = (f"import sys; sys.path.insert(0, {str(chart_fetch.VERIFY)!r}); import chart_fetch\n"
             f"chart_fetch.pull({str(stub.helm)!r}, {REPO!r}, {CHART!r}, {VERSION!r}, lock=chart_fetch.pathlib.Path("
             f"{str(lock)!r}), backoff=(0,))\n")
    r = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True,
                       env={**os.environ, "WIB_ARTIFACT_CACHE": str(root / "cache4")})
    check(f"the probe fetched the chart (exit {r.returncode})", r.returncode == 0, r.stderr)
    check("WIB_ARTIFACT_CACHE named the cache root",
          artifact_cache.path_for(SUMS[VERSION], root / "cache4").read_bytes() == SERVED[VERSION])
    check("one RETRY line names the chart and the attempt",
          [ln.strip() for ln in r.stdout.splitlines() if "RETRY" in ln][:1]
          == [f"RETRY helm pull {CHART} {VERSION} from {REPO}: {EOF_ERROR.strip()} (attempt 1 of 2; again in 0s)"],
          r.stdout)

    print("== four fetches of one chart at once all get it, from one pull between them ==")
    stub.reset()
    cache = root / "cache5"
    results: list = []
    threads = [threading.Thread(target=lambda: results.append(pull(stub, cache, lock, []))) for _ in range(4)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    paths = {r[0] for r in results}
    check(f"each fetch got the one cached chart ({results})",
          len(results) == 4 and paths == {artifact_cache.path_for(SUMS[VERSION], cache)})
    check(f"Helm was asked once ({stub.calls()})", len(stub.calls()) == 1)
    check("the cache holds that tarball alone, no staging directory", entries(cache) == [SUMS[VERSION]],
          str(entries(cache)))
finally:
    shutil.rmtree(base, ignore_errors=True)

print("== charts.lock pins every chart the repo deploys, and nothing else ==")
locked = chart_fetch.load_lock()
pinned = charts_lock.pins()
check(f"the repo pins charts to check ({len(pinned)})", len(pinned) >= 20)
for repo, chart, version in sorted(pinned - set(locked)):
    check(f"{chart} {version} from {repo} is in charts.lock (run python3 verify/charts_lock.py write)", False)
for repo, chart, version in sorted(set(locked) - pinned):
    check(f"charts.lock's {chart} {version} from {repo} is pinned somewhere (a stale line)", False)
check("charts.lock is exactly the pinned charts", set(locked) == pinned)
check("infra/deploy-full-idp.sh's argo-cd and aws-load-balancer-controller are among them",
      {c for (_, c, _) in charts_lock.deploy_pins()} == {"argo-cd", "aws-load-balancer-controller"})
check("charts.lock is as charts_lock.py writes it, sorted and aligned",
      chart_fetch.LOCK.read_text() == charts_lock.render(locked))

print("== the tier tests that fetch upstream charts go through chart_fetch ==")
VERIFY = chart_fetch.VERIFY
CALLERS = ("test_datadog_log_services_render.py", "app_render.py", "test_image_registry_render.py",
           "test_enforce_floor.py", "test_kubearmor_config_render.py")
for name in CALLERS:
    text = (VERIFY / name).read_text()
    check(f"{name} fetches with chart_fetch.pull and never asks a repository from helm template or helm pull itself",
          "chart_fetch.pull(" in text and "\"--repo\"" not in text and "\"pull\"" not in text)
# A new caller may pull a chart pinned somewhere charts_lock.pins() does not read; it is named here so it is looked at.
callers = sorted(p.name for p in VERIFY.glob("*.py") if p.name not in ("chart_fetch.py", "charts_lock.py",
                                                                       "test_chart_fetch.py")
                 and re.search(r"\bchart_fetch\.pull\(", p.read_text()))
check(f"those are all the callers of chart_fetch.pull ({callers})", callers == sorted(CALLERS))

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    sys.exit(1)
print("Charts are served from the host cache by their locked sum, an unlocked chart or a mismatch fails by name, and a"
      " miss retries a network error.")
