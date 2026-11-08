# ABOUTME: Serves a pinned upstream Helm chart's tarball from the host artifact cache by the SHA-256 verify/charts.lock
# ABOUTME: records (#1118); on a miss Helm pulls it once, a network error retried (#1028). An unlocked chart fails by name.
"""Each tier test that renders an upstream chart used to ask the chart's repository for it on every render: `helm
template --repo` or `helm pull` read the repository's index.yaml live. In run 17993 charts.external-secrets.io answered
one of those reads with EOF, test_datadog_log_services_render.py failed on it, and the same test passed when run alone
right after (#1028). #1028 then kept each tarball in the worktree, under verify/.tools/charts, so every run fetched every
chart again.

pull() now looks the chart up in verify/charts.lock, which records each pinned chart's version and the SHA-256 of its
tarball (the digest the repository's index.yaml or the OCI manifest publishes; verify/charts_lock.py writes it), and
asks the host artifact cache (verify/artifact_cache.py, #1117) for that sum. A hit is hashed again and served with no
network access; `helm template` renders the tarball as it renders a directory. A chart the lock does not name, or names
at another version, fails at once, naming the chart, and is never fetched unpinned. A miss runs `helm pull` into a
staging directory of its own beside the cache, and the cache checks the tarball's sum before renaming it into place, so
a repository that serves other bytes under the pinned version fails by name and is never used. The cache holds
tarballs and nothing else: an untarred chart's README.md, values.yaml and templates would be read by the offline tests
that scan the tree for text (test_mesh_enrollment.py found istio.io/dataplane-mode in three cached charts when they were
untarred), and the cache sits outside every worktree in any case.

A pull that fails on a network error (an EOF, a reset or refused connection, a timeout, a failed name lookup, a 429 or
a 5xx) is tried again, up to ATTEMPTS times in all, and each retry is printed. Any other error, a chart or version not
in the repository included, fails at once with Helm's own words, and so does the last network error."""
from __future__ import annotations

import pathlib
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
from collections.abc import Callable, Sequence
from typing import BinaryIO

VERIFY = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(VERIFY))
import artifact_cache  # noqa: E402

LOCK = VERIFY / "charts.lock"
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
    """A chart could not be served; the message names the chart and says why, in Helm's words where Helm failed."""


def is_network_error(stderr: str) -> bool:
    return bool(NETWORK_ERROR.search(stderr))


def chart_ref(repo: str, chart: str) -> list[str]:
    """Helm's arguments for a chart: an OCI reference for a registry (Argo CD's repoURL names ghcr.io without a scheme),
    else the chart and its HTTP repository."""
    if repo.startswith(("http://", "https://")):
        return [chart, "--repo", repo]
    return [f"oci://{repo.removeprefix('oci://').rstrip('/')}/{chart}"]


def source(repo: str, chart: str, version: str) -> str:
    """What the fetch log names for a chart: the reference Helm pulls, at its version."""
    return f"{' '.join(chart_ref(repo, chart))} --version {version}"


def load_lock(path: pathlib.Path | None = None) -> dict[tuple[str, str, str], str]:
    """(repo, chart, version) -> tarball SHA-256, from charts.lock: one chart a line, `chart version sha256 repo`,
    with # comments. A malformed line raises ChartFetchError naming it."""
    path = path or LOCK
    try:
        text = path.read_text()
    except OSError as e:
        raise ChartFetchError(f"the chart lock {path} cannot be read: {e}") from e
    pins: dict[tuple[str, str, str], str] = {}
    for n, line in enumerate(text.splitlines(), 1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        f = line.split()
        if len(f) != 4 or not artifact_cache.SHA256.fullmatch(f[2]):
            raise ChartFetchError(f"{path}:{n} is malformed: want chart, version, sha256 and repo, got {line.strip()!r}")
        chart, version, sha, repo = f
        pins[(repo, chart, version)] = sha
    return pins


def pinned_sha(repo: str, chart: str, version: str, lock: pathlib.Path | None = None) -> str:
    """The lock's SHA-256 for the chart at this version; ChartFetchError, naming the chart, when the lock has none."""
    pins = load_lock(lock)
    sha = pins.get((repo, chart, version))
    if sha is None:
        held = sorted(v for (r, c, v) in pins if (r, c) == (repo, chart))
        also = f" (it pins {', '.join(held)})" if held else ""
        raise ChartFetchError(f"chart {chart} {version} from {repo} is not in {lock or LOCK}{also}; a chart is served only "
                              "by the SHA-256 the lock records, never fetched unpinned: run "
                              "python3 verify/charts_lock.py write")
    return sha


def last_line(stderr: str) -> str:
    lines = [ln for ln in stderr.strip().splitlines() if ln.strip()]
    return (lines[-1] if lines else "helm failed with no error output")[:300]


def holds_chart(tgz: pathlib.Path, chart: str) -> bool:
    try:
        with tarfile.open(tgz, "r:gz") as t:
            return f"{chart}/Chart.yaml" in t.getnames()
    except (tarfile.TarError, OSError, EOFError):
        return False


def helm_fetcher(helm: str, repo: str, chart: str, version: str, stage_in: pathlib.Path,
                 backoff: Sequence[float], sleep: Callable[[float], None]) -> Callable[[str, BinaryIO], None]:
    """The artifact cache's fetcher for a miss: `helm pull` into a directory of its own, a network error retried, and
    the one tarball it leaves copied to the cache's temp file, which the cache then checks against the pinned sum."""
    where = f"helm pull {chart} {version} from {repo}"
    attempts = len(backoff) + 1

    def fetch(_url: str, out: BinaryIO) -> None:
        for attempt in range(1, attempts + 1):
            stage = pathlib.Path(tempfile.mkdtemp(prefix=f".{chart}-", dir=stage_in))
            try:
                r = subprocess.run([helm, "pull", *chart_ref(repo, chart), "--version", version, "--destination",
                                    str(stage)], capture_output=True, text=True)
                if r.returncode == 0:
                    got = sorted(stage.glob("*.tgz"))
                    if len(got) != 1 or not holds_chart(got[0], chart):
                        raise ChartFetchError(f"{where}: Helm exited 0 but left {[g.name for g in got]}, "
                                              f"not one tarball holding {chart}/Chart.yaml")
                    with open(got[0], "rb") as f:
                        shutil.copyfileobj(f, out)
                    return
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

    return fetch


def pull(helm: str, repo: str, chart: str, version: str, *, cache: pathlib.Path | None = None,
         lock: pathlib.Path | None = None, backoff: Sequence[float] = BACKOFF,
         sleep: Callable[[float], None] = time.sleep) -> pathlib.Path:
    """The chart's tarball, <cache root>/sha256/<the lock's sum>, served from the host cache and pulled by Helm only on
    a miss; ChartFetchError when the lock does not pin it, Helm cannot pull it, or what Helm pulls is not those bytes.
    cache is the cache root (artifact_cache.resolve_root() when None) and lock the chart lock (charts.lock when None);
    test_chart_fetch.py passes both."""
    sha = pinned_sha(repo, chart, version, lock)
    try:
        root = artifact_cache.resolve_root() if cache is None else cache
        # get() makes this directory before it calls the fetcher on a miss; a hit needs only read access to it.
        stage_in = artifact_cache.path_for(sha, root).parent
        fetch = helm_fetcher(helm, repo, chart, version, stage_in, backoff, sleep)
        return artifact_cache.get(sha, source(repo, chart, version), root=root, fetch=fetch)
    except ChartFetchError:
        raise
    except artifact_cache.ArtifactCacheError as e:
        if isinstance(e.__cause__, ChartFetchError):
            raise e.__cause__ from None
        raise ChartFetchError(f"chart {chart} {version} from {repo}: {e}") from e
    except OSError as e:
        raise ChartFetchError(f"chart {chart} {version} from {repo}: the artifact cache cannot be written: {e}") from e
