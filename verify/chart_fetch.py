# ABOUTME: Fetches a pinned upstream Helm chart's tarball once into verify/.tools/charts, retrying a network error (#1028).
# ABOUTME: Shared by the tools-tier tests that render upstream charts, so one upstream blip does not fail the tier.
"""Each tier test that renders an upstream chart used to ask the chart's repository for it on every render: `helm
template --repo` or `helm pull` read the repository's index.yaml live. In run 17993 charts.external-secrets.io answered
one of those reads with EOF, test_datadog_log_services_render.py failed on it, and the same test passed when run alone
right after (#1028).

pull() asks Helm for the chart at its pinned version and keeps its tarball under verify/.tools/charts, which is
gitignored with the rest of the pinned tools; `helm template` renders a tarball as it renders a directory. A chart
already there is read from there, so the tier's tests that render the same chart fetch it once between them. The
cache holds tarballs and nothing else: an untarred chart's README.md, values.yaml and templates would be read by the
offline tests that scan the tree for text (test_mesh_enrollment.py found istio.io/dataplane-mode in three cached
charts when they were untarred). Each fetch writes into a directory of its own and its tarball is renamed into place,
so checks running side by side never read a half-written chart: when two fetch the same chart at once, both
tarballs hold the same pinned chart and the later rename replaces the earlier.

A fetch that fails on a network error (an EOF, a reset or refused connection, a timeout, a failed name lookup, a 429 or
a 5xx) is tried again, up to ATTEMPTS times in all, and each retry is printed. Any other error, a chart or version not
in the repository included, fails at once with Helm's own words, and so does the last network error."""
from __future__ import annotations

import hashlib
import os
import pathlib
import re
import shutil
import subprocess
import tarfile
import tempfile
import time
from collections.abc import Callable, Sequence

VERIFY = pathlib.Path(__file__).resolve().parent
# CHART_CACHE moves the cache, for test_chart_fetch.py, which must not write the real one.
CACHE = pathlib.Path(os.environ.get("CHART_CACHE") or VERIFY / ".tools" / "charts")
# Seconds before each retry; one more attempt than there are waits.
BACKOFF = (2, 5, 10)
ATTEMPTS = len(BACKOFF) + 1

# Helm's words for a fetch the network broke, as Go's net/http, crypto/tls and net packages and an HTTP status put them.
NETWORK_ERROR = re.compile(
    r"\bEOF\b|connection reset|connection refused|broken pipe|i/o timeout|TLS handshake timeout"
    r"|Client\.Timeout|context deadline exceeded|timeout awaiting|no such host|server misbehaving"
    r"|temporary failure in name resolution|network is unreachable|http2: "
    r"|\b(?:429|50[0234])\b(?: [A-Z]|$)|Too Many Requests|Bad Gateway|Service Unavailable|Gateway Timeout",
    re.I | re.M)


class ChartFetchError(RuntimeError):
    """A chart could not be fetched; the message is Helm's last line of error, with the chart named."""


def is_network_error(stderr: str) -> bool:
    return bool(NETWORK_ERROR.search(stderr))


def chart_ref(repo: str, chart: str) -> list[str]:
    """Helm's arguments for a chart: an OCI reference for a registry (Argo CD's repoURL names ghcr.io without a scheme),
    else the chart and its HTTP repository."""
    if repo.startswith(("http://", "https://")):
        return [chart, "--repo", repo]
    return [f"oci://{repo.removeprefix('oci://').rstrip('/')}/{chart}"]


def cache_path(repo: str, chart: str, version: str, cache: pathlib.Path | None = None) -> pathlib.Path:
    """Where the chart's tarball lives: one file per repository, chart and version."""
    key = hashlib.sha256(f"{repo}\n{chart}\n{version}".encode()).hexdigest()[:12]
    return (cache or CACHE) / f"{chart}-{version}-{key}.tgz"


def last_line(stderr: str) -> str:
    lines = [ln for ln in stderr.strip().splitlines() if ln.strip()]
    return (lines[-1] if lines else "helm failed with no error output")[:300]


def holds_chart(tgz: pathlib.Path, chart: str) -> bool:
    try:
        with tarfile.open(tgz, "r:gz") as t:
            return f"{chart}/Chart.yaml" in t.getnames()
    except (tarfile.TarError, OSError, EOFError):
        return False


def pull(helm: str, repo: str, chart: str, version: str, *, cache: pathlib.Path | None = None,
         backoff: Sequence[float] = BACKOFF, sleep: Callable[[float], None] = time.sleep) -> pathlib.Path:
    """The chart's tarball at its pinned version, fetched once; ChartFetchError when Helm cannot fetch it."""
    final = cache_path(repo, chart, version, cache)
    if final.is_file():
        return final
    where = f"helm pull {chart} {version} from {repo}"
    attempts = len(backoff) + 1
    final.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(1, attempts + 1):
        stage = pathlib.Path(tempfile.mkdtemp(prefix=f".{chart}-", dir=final.parent))
        try:
            r = subprocess.run([helm, "pull", *chart_ref(repo, chart), "--version", version, "--destination",
                                str(stage)], capture_output=True, text=True)
            if r.returncode == 0:
                got = sorted(stage.glob("*.tgz"))
                if len(got) != 1 or not holds_chart(got[0], chart):
                    raise ChartFetchError(f"{where}: Helm exited 0 but left {[g.name for g in got]}, "
                                          f"not one tarball holding {chart}/Chart.yaml")
                os.replace(got[0], final)
                return final
        finally:
            shutil.rmtree(stage, ignore_errors=True)
        err = last_line(r.stderr)
        if not is_network_error(r.stderr):
            raise ChartFetchError(f"{where}: {err}")
        if attempt == attempts:
            raise ChartFetchError(f"{where}: {err} (a network error on each of {attempts} attempts)")
        wait = backoff[attempt - 1]
        print(f"  RETRY {where}: {err} (attempt {attempt} of {attempts}; again in {wait:g}s)", flush=True)
        sleep(wait)
    raise AssertionError("unreachable")
