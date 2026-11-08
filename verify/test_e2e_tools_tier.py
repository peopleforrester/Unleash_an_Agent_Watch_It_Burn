# ABOUTME: The cluster-free E2E tier (#572): its pins are VERSIONS.lock's, its tools land in a gitignored directory,
# ABOUTME: no tier test needs CONTEXT or IAM_PIPELINE_*, and a failed or tampered fetch fails loudly, never skips.
"""Holds what verify/run-e2e-tools.sh, the gate's E2E command, relies on. Offline: no download is made.

#543 took run-e2e.sh off the gate because the gate host has no cluster, no AWS and none of the cluster tools.
#572 declared the part of the E2E suite that host can run: tests marked `# E2E TIER: tools`, run with the
binaries in verify/e2e-tools.lock, which verify/fetch-e2e-tools.sh downloads into verify/.tools and checks
against the lock's SHA-256 before use.

The fetch is run here for real, in a scratch copy of the scripts, against a file server on 127.0.0.1 that serves
fixture archives and counts each request, with `uname` stubbed so the run does not depend on the host. Since #1118 the
fetch takes every download from the host artifact cache (artifact-cache.sh) by its SHA-256, so each run here names a
cache root of its own, outside every worktree, and the cache's fetch log is read back. Zip members are read with
python3's zipfile since #1047, and `unzip` is a stub that logs any call and fails, so a fetch that reaches for it again
is caught on a host that has one; `curl` is a stub that logs any call and fails, so a fetch that bypasses the cache is
caught too. A good lock installs every binary, a second run downloads nothing, and so does a run from a fresh worktree
on the same cache (#1004); a cached file that no longer matches fails by name and is not fetched again, and a missing
artifact or a checksum mismatch exits 1 naming each failure and leaves no binary behind. run-e2e-tools.sh stops on a
failed fetch or a missing prerequisite before any test runs, and that includes Playwright browsers that are missing
from a directory `playwright install` cannot write (#658), with `uv` stubbed to list them.

run-e2e.sh, the by-hand live suite, runs the same fetch in its prerequisite check (#585), so a cluster build runs
the gate's binaries, otelcol-contrib included since #654 and ttyd since #770. Its scratch copy is run with a fixture lock of the seven tools: the fetched kubectl, not one
already on PATH, is what checks the cluster, and a failed fetch is listed as missing with no kubectl run at all.
Some prerequisite is always left missing there, so the run stops before any check or cluster call.
"""
from __future__ import annotations

import contextlib
import fcntl
import hashlib
import http.server
import io
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import threading
import zipfile

REPO = pathlib.Path(__file__).resolve().parent.parent
VERIFY = REPO / "verify"
sys.path.insert(0, str(VERIFY))
import artifact_cache  # noqa: E402

LOCK = VERIFY / "e2e-tools.lock"
FETCH = VERIFY / "fetch-e2e-tools.sh"
RUNNER = VERIFY / "run-e2e-tools.sh"
BROWSERS = VERIFY / "playwright_browsers.py"
BASH = shutil.which("bash")
PY = sys.executable

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"\n        {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def lock_rows(text: str) -> list[list[str]]:
    return [line.split() for line in text.splitlines() if line.strip() and not line.lstrip().startswith("#")]


print("== the lock pins what VERSIONS.lock and the tests pin ==")
rows = lock_rows(LOCK.read_text())
tools = {r[0]: r for r in rows}
check(f"e2e-tools.lock pins kyverno, conftest, terraform, kubectl, helm, otelcol-contrib, ttyd, crane, weaver, agentgateway "
      f"and caddy ({sorted(tools)})",
      set(tools) == {"kyverno", "conftest", "terraform", "kubectl", "helm", "otelcol-contrib", "ttyd", "crane",
                     "weaver", "agentgateway", "caddy"})
for name, row in tools.items():
    check(f"{name}: five fields (name, version, sha256, url, member)", len(row) == 5, str(row))
    if len(row) != 5:
        continue
    _, version, sha, url, _member = row
    check(f"{name}: a 64-hex SHA-256", re.fullmatch(r"[0-9a-f]{64}", sha) is not None, sha)
    check(f"{name}: an https URL naming {version}", url.startswith("https://") and version.lstrip("v") in url, url)
    # ttyd's release names its Linux builds by architecture alone (ttyd.x86_64), weaver's by Rust target triple.
    check(f"{name}: a linux x86_64 artifact",
          re.search(r"linux[_/-](amd64|x86_64)|/ttyd\.x86_64$|x86_64-unknown-linux-gnu", url, re.I) is not None, url)

# otelcol-contrib runs the PII scrub test (#647) on the collector the clusters run, so its pin is the image tag
# every gitops/bootstrap/apps/otel-collector*.yaml file names (lab-platform's mirror tag is <version>-<digest>).
collector_tags = {re.search(r'^\s+tag: "([0-9.]+)-', f.read_text(), re.M).group(1)
                  for f in sorted((REPO / "gitops/bootstrap/apps").glob("otel-collector*.yaml"))}
check(f"otelcol-contrib is the collector image's version {sorted(collector_tags)}",
      len(collector_tags) == 1 and "otelcol-contrib" in tools
      and tools["otelcol-contrib"][1] == f"v{next(iter(collector_tags))}")
want = re.search(r'^OTELCOL_VERSION = "([^"]+)"', (VERIFY / "test_lab_pipeline_collector.py").read_text(), re.M)
check("otelcol-contrib is the version test_lab_pipeline_collector.py demands",
      bool(want) and "otelcol-contrib" in tools and tools["otelcol-contrib"][1] == f"v{want.group(1)}")
# Its validate of a config with a Datadog exporter takes about 25 s off-cloud, and 60 s timed out on a loaded gate
# host (#800). The limit stays well above that, and a hang is caught and recorded as a FAIL naming the config.
lab_text = (VERIFY / "test_lab_pipeline_collector.py").read_text()
want = re.search(r"^VALIDATE_TIMEOUT = (\d+)$", lab_text, re.M)
check(f"test_lab_pipeline_collector.py gives each validate at least 180 s ({want.group(1) if want else None})",
      bool(want) and int(want.group(1)) >= 180 and "timeout=VALIDATE_TIMEOUT" in lab_text)
check("test_lab_pipeline_collector.py fails a validate that hangs instead of raising",
      re.search(r"except subprocess\.TimeoutExpired:\n\s+check\(f\"\{label\} validates within", lab_text) is not None)

# ttyd runs test_ttyd_ws_auth.py (#770) on the terminal the clusters run, so its pin is the one the web-terminal
# image downloads.
want = re.search(r"tsl0922/ttyd/releases/download/([0-9.]+)/ttyd\.",
                 (REPO / "images/web-terminal/Dockerfile").read_text())
check(f"ttyd is the web-terminal image's version ({want.group(1) if want else None})",
      bool(want) and "ttyd" in tools and tools["ttyd"][1] == want.group(1))

# crane rebuilds the Jokers in test_joker_build_digest.py (#775), and gzip output can change between releases, so its
# pin is the crane images/villains/build.sh says the pushed digests come from.
want = re.search(r"crane ([0-9.]+) \(verify/e2e-tools\.lock\)", (REPO / "images/villains/build.sh").read_text())
check(f"crane is the version images/villains/build.sh pushes with ({want.group(1) if want else None})",
      bool(want) and "crane" in tools and tools["crane"][1] == f"v{want.group(1)}")

# weaver checks weaver/registry in the tier (#782) as .github/workflows/weaver-registry-check.yml does on GitHub, so
# both run the same weaver: the workflow's version and SHA-256 are the lock's.
workflow = (REPO / ".github/workflows/weaver-registry-check.yml").read_text()
wf_version = re.search(r"^\s+WEAVER_VERSION: (\S+)", workflow, re.M)
wf_sha = re.search(r"^\s+WEAVER_SHA256: ([0-9a-f]{64})", workflow, re.M)
check("weaver is the version and SHA-256 weaver-registry-check.yml pins",
      bool(wf_version and wf_sha) and "weaver" in tools
      and tools["weaver"][1:3] == [wf_version.group(1), wf_sha.group(1)], str(tools.get("weaver")))

# agentgateway runs both gateway ConfigMaps in test_agentgateway_tracing_e2e.py (#864), so its pin is the version of
# the image gitops/ai-layer/agentgateway.yaml runs (the tag before the digest).
want = re.search(r"image: cr\.agentgateway\.dev/agentgateway:(v[0-9.]+)@sha256:",
                 (REPO / "gitops/ai-layer/agentgateway.yaml").read_text())
check(f"agentgateway is the deployed gateway image's version ({want.group(1) if want else None})",
      bool(want) and "agentgateway" in tools and tools["agentgateway"][1] == want.group(1))
check("the agentgateway artifact is that version's release binary",
      "agentgateway" in tools and bool(want) and tools["agentgateway"][3]
      == f"https://github.com/agentgateway/agentgateway/releases/download/{want.group(1)}/agentgateway-linux-amd64")

# caddy runs the apex router's cluster leg in verify/failover_drill.py (#986). The router image lives in
# apex-agenticburn, so the lock's comment names its version and this holds the artifact to that version's release.
check("caddy is v2.11.4, the Caddy the apex router image runs, as the lock's comment says",
      "caddy" in tools and tools["caddy"][1] == "v2.11.4" and "Caddy v2.11.4" in LOCK.read_text())
check("the caddy artifact is that version's release tarball, its binary the member",
      "caddy" in tools and tools["caddy"][3:] == [
          "https://github.com/caddyserver/caddy/releases/download/v2.11.4/caddy_2.11.4_linux_amd64.tar.gz", "caddy"])

versions_lock = (REPO / "VERSIONS.lock").read_text()
for name in ("terraform", "conftest", "kubectl", "helm"):
    m = re.search(rf"^{name}\s+(v\S+)", versions_lock, re.M)
    pinned = m.group(1) if m else None
    check(f"{name} is VERSIONS.lock's {pinned}", name in tools and tools[name][1] == pinned)
m = re.search(r"^kyverno\s+app (v\S+)", versions_lock, re.M)
check(f"kyverno is the deployed engine VERSIONS.lock pins ({m.group(1) if m else None})",
      bool(m) and "kyverno" in tools and tools["kyverno"][1] == m.group(1))
want = re.search(r'^WANT_VERSION = "([^"]+)"', (VERIFY / "test_kyverno_cel_policies.py").read_text(), re.M)
check("kyverno is the version test_kyverno_cel_policies.py demands",
      bool(want) and "kyverno" in tools and tools["kyverno"][1] == f"v{want.group(1)}")
want = re.search(r'^WANT_CONFTEST = "([^"]+)"', (VERIFY / "test_iam_policy_structural.py").read_text(), re.M)
check("conftest is the version test_iam_policy_structural.py demands",
      bool(want) and "conftest" in tools and tools["conftest"][1] == f"v{want.group(1)}")

print("== the tools land in a directory git ignores ==")
fetch_text = FETCH.read_text()
check("fetch-e2e-tools.sh installs into verify/.tools", 'TOOLS_DIR="${SCRIPT_DIR}/.tools"' in fetch_text)
fetch_code = "\n".join(ln for ln in fetch_text.splitlines() if not ln.lstrip().startswith("#"))
check("fetch-e2e-tools.sh takes each download from the artifact cache by its sum, and downloads nothing itself (#1118)",
      'bash "${CACHE}" get "${want}" "${url}"' in fetch_code
      and not re.search(r"\b(curl|wget|urlopen)\b", fetch_code), fetch_code)
for path in ("verify/.tools/bin/kyverno", "verify/.tools/.fetch-err.abc123"):
    ignored = subprocess.run(["git", "-C", str(REPO), "check-ignore", "-q", path], capture_output=True)
    check(f"git ignores {path}", ignored.returncode == 0)
tracked = subprocess.run(["git", "-C", str(REPO), "ls-files", "verify/.tools"], capture_output=True, text=True).stdout
check("nothing under verify/.tools is committed", tracked.strip() == "", tracked)

print("== the tier is the tool-only E2E checks and nothing that needs a cluster or AWS ==")
tests = sorted(list(VERIFY.glob("test_*.py")) + list(VERIFY.glob("test_*.sh")))
tier = [t for t in tests if re.search(r"^# E2E TIER: tools", t.read_text(), re.M)]
names = {t.name for t in tier}
for need in ("test_kyverno_cel_policies.py", "test_iam_policy_structural.py", "test_service_naming_render.py",
             "test_terraform_lock_init.py", "test_party_refresh_rate.py", "test_lab_pipeline_collector.py",
             "test_collector_pii_scrub_e2e.py", "test_trace_shape_e2e.py", "test_ttyd_ws_auth.py",
             "test_joker_build_digest.py", "test_weaver_registry_check.py", "test_guard_proxy_go_otel.py",
             "test_agentgateway_tracing_e2e.py"):
    check(f"{need} is in the tier", need in names)
for t in tier:
    text = t.read_text()
    check(f"{t.name} is also `# SUITE: e2e`, so run-tests.sh leaves it out", re.search(r"^# SUITE: e2e", text, re.M)
          is not None)
    # A literal stand-in handed to a subprocess ("DD_API_KEY": "x", which the collector's validator needs to see set)
    # is not a read of the real value, so it is taken out before looking.
    read = re.sub(r'"(?:DD_API_KEY|DD_APP_KEY|DD_ADMIN_API_KEY)":\s*"[^"$]{0,8}"', "", text)
    used = sorted(set(re.findall(r"\b(CONTEXT|IAM_PIPELINE_[A-Z]+|DD_API_KEY|DD_APP_KEY)\b", read)))
    check(f"{t.name} reads no CONTEXT, IAM_PIPELINE_* or Datadog key ({used})", not used)
    check(f"{t.name} calls no kubectl against a cluster", "--context" not in text)
    # The runner runs checks at once (#1005), and a test that runs terraform shares the provider cache, which
    # Terraform does not promise is safe for two writers: every such test takes its turn.
    if re.search(r"\bTERRAFORM\b|iam_plan_render", text):
        check(f"{t.name} runs terraform, so it carries `# E2E SERIAL: terraform`",
              re.search(r"^# E2E SERIAL: terraform", text, re.M) is not None)
serial_tests = sorted(t.name for t in tier if re.search(r"^# E2E SERIAL: terraform", t.read_text(), re.M))
check(f"the five terraform tests are the serial ones ({serial_tests})",
      serial_tests == ["test_control_plane_app_ports_module.py", "test_iam_policy_structural.py",
                       "test_lab_platform_operator_entry.py", "test_terraform_lock_init.py",
                       "test_terraform_plugin_cache_lock.py"])

runner = RUNNER.read_text()
code = "\n".join(line for line in runner.splitlines() if not line.lstrip().startswith("#"))
check("run-e2e-tools.sh never runs run-e2e.sh", "run-e2e.sh" not in code)
check("run-e2e-tools.sh runs the offline suite, which the gate no longer runs on its own",
      'bash "${SCRIPT_DIR}/run-tests.sh"' in code)
for var in ("CONTEXT", "IAM_PIPELINE_PROFILE", "IAM_PIPELINE_REGION", "AWS_PROFILE"):
    check(f"run-e2e-tools.sh runs each tier test with {var} unset", f"-u {var}" in code)
check("run-e2e-tools.sh runs each tier test with KUBECONFIG=/dev/null", "KUBECONFIG=/dev/null" in code)
for var, tool in (("KYVERNO_CLI", "kyverno"), ("CONFTEST", "conftest"), ("TERRAFORM", "terraform"),
                  ("OTELCOL_CONTRIB", "otelcol-contrib"), ("TTYD", "ttyd"), ("CRANE", "crane"),
                  ("AGENTGATEWAY", "agentgateway")):
    check(f"run-e2e-tools.sh points {var} at the fetched {tool}", f'{var}="${{TOOLS_BIN}}/{tool}"' in code)
check("run-e2e-tools.sh puts the fetched tools first on PATH, behind only the aws and eksctl stubs (#865)",
      'PATH="${NO_CLOUD_BIN}:${TOOLS_BIN}:${PATH}"' in code)
check("run-e2e-tools.sh stubs aws and eksctl, and only those two, with no-cloud.sh, in each check's own directory "
      "(#865, #1005)",
      '. "${SCRIPT_DIR}/no-cloud.sh"' in code and 'no_cloud_setup "${dir}/no-cloud" aws eksctl\n' in code)
check("run-e2e-tools.sh runs each tier test through no_cloud_run",
      code.count('no_cloud_run "${tier_env[@]}"') == 2 and code.count('"${tier_env[@]}"') == 2)

print("== a fetch is checked against the lock, and fails loudly ==")

# A tripwire: since #1118 every download goes through the artifact cache, so the fetch must never call curl itself.
STUB_CURL = f"""#!{PY}
import os, sys
with open(os.path.join(os.environ["HOME"], "curl.log"), "a") as f:
    f.write(" ".join(sys.argv[1:]) + "\\n")
sys.stderr.write("curl: the fetch reached for curl and not the artifact cache (#1118)\\n")
sys.exit(22)
"""
# A tripwire, not a stand-in: Tanjiro's CI runner has no unzip (#1047), so the fetch must never call one.
STUB_UNZIP = f"""#!{PY}
import os, sys
with open(os.path.join(os.environ["HOME"], "unzip.log"), "a") as f:
    f.write(" ".join(sys.argv[1:]) + "\\n")
sys.stderr.write("unzip: not on Tanjiro's runner (#1047)\\n")
sys.exit(127)
"""
STUB_UNAME = '#!/bin/sh\ncase "$1" in -s) echo Linux ;; -m) echo x86_64 ;; esac\n'


def make_stubs(bindir: pathlib.Path, extra: dict[str, str] | None = None) -> None:
    bindir.mkdir(parents=True, exist_ok=True)
    stubs = {"curl": STUB_CURL, "unzip": STUB_UNZIP, "uname": STUB_UNAME, **(extra or {})}
    for name, body in stubs.items():
        p = bindir / name
        p.write_text(body)
        p.chmod(0o755)


def tgz(member: str, data: bytes) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        info = tarfile.TarInfo(member)
        info.size = len(data)
        tf.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def txz(member: str, data: bytes) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:xz") as tf:
        info = tarfile.TarInfo(member)
        info.size = len(data)
        tf.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def zipped(member: str, data: bytes) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(member, data)
    return buf.getvalue()


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


FIXTURES = {
    "alpha-linux_x86_64.tar.gz": tgz("pkg/alpha", b"#!/bin/sh\necho alpha\n"),
    "beta_linux_amd64.zip": zipped("beta", b"#!/bin/sh\necho beta\n"),
    "gamma-linux-amd64": b"#!/bin/sh\necho gamma\n",
    "epsilon-x86_64-unknown-linux-gnu.tar.xz": txz("epsilon-x86_64-unknown-linux-gnu/epsilon",
                                                   b"#!/bin/sh\necho epsilon\n"),
}


class FixtureServer:
    """Serves FIXTURES at /<name> on 127.0.0.1 and logs each request's path; anything else is a 404."""

    def __init__(self):
        self.paths: list[str] = []
        self.lock = threading.Lock()
        srv = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                with srv.lock:
                    srv.paths.append(self.path)
                body = FIXTURES.get(self.path.lstrip("/"))
                if body is None:
                    self.send_error(404)
                    return
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_):
                pass

        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.httpd.daemon_threads = True
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"

    def requests(self) -> int:
        with self.lock:
            return len(self.paths)


SERVER = FixtureServer()
URL = SERVER.base
# run-e2e.sh's seven tools. The fetched kubectl logs each call and fails, as an unreachable cluster would.
SEVEN = ("kyverno", "conftest", "terraform", "kubectl", "helm", "otelcol-contrib", "ttyd")
for _tool in SEVEN:
    FIXTURES[f"{_tool}-linux-amd64"] = (
        b'#!/bin/sh\necho "fetched $*" >>"$KUBECTL_LOG"\nexit 1\n' if _tool == "kubectl" else b"#!/bin/sh\nexit 0\n")
SEVEN_LOCK = "".join(f"{t} v9 {sha(FIXTURES[f'{t}-linux-amd64'])} {URL}/{t}-linux-amd64 -\n"
                     for t in SEVEN)
GOOD_LOCK = (
    "# fixture lock\n"
    f"alpha v1 {sha(FIXTURES['alpha-linux_x86_64.tar.gz'])} {URL}/alpha-linux_x86_64.tar.gz pkg/alpha\n"
    f"beta  v2 {sha(FIXTURES['beta_linux_amd64.zip'])} {URL}/beta_linux_amd64.zip beta\n"
    f"gamma v3 {sha(FIXTURES['gamma-linux-amd64'])} {URL}/gamma-linux-amd64 -\n"
    f"epsilon v5 {sha(FIXTURES['epsilon-x86_64-unknown-linux-gnu.tar.xz'])} "
    f"{URL}/epsilon-x86_64-unknown-linux-gnu.tar.xz epsilon-x86_64-unknown-linux-gnu/epsilon\n"
)
BAD_LOCK = (
    f"alpha v1 {'0' * 64} {URL}/alpha-linux_x86_64.tar.gz pkg/alpha\n"
    f"delta v4 {'1' * 64} {URL}/delta-linux-amd64 -\n"
)


# The runner keeps the Terraform provider cache outside the checkout and fails on one inside it (#1114). A scratch
# checkout here is the fixture's whole temp directory, HOME included, so each run names a cache of its own outside it,
# in a directory removed when this test exits.
TF_CACHE_HOME = tempfile.TemporaryDirectory(prefix="tier-tf-cache-")
TF_CACHE_ENV = {"TF_PLUGIN_CACHE_DIR": str(pathlib.Path(TF_CACHE_HOME.name) / "terraform-plugin-cache")}
# The fetch takes its downloads from the host artifact cache (#1118), which refuses a root inside a git worktree, and
# hecaton points TMPDIR inside the run's. Each scratch checkout gets a cache root of its own under one directory outside
# every worktree, removed when this test ends, and the cache's fetch log in the checkout.
CACHE_BASE = artifact_cache.scratch_dir("tier-artifact-cache-")


def fetch_env(tmp: pathlib.Path, cache: pathlib.Path | None = None) -> dict[str, str]:
    return {"WIB_ARTIFACT_CACHE": str(cache or CACHE_BASE / tmp.name), "ARTIFACT_FETCH_LOG": str(tmp / "fetch.log")}


def scratch(tmp: pathlib.Path, lock: str, scripts: tuple[pathlib.Path, ...]) -> pathlib.Path:
    """A scratch verify/ holding copies of the scripts and the given lock. The runner names its provider cache through
    tf_plugin_cache.py, and the fetch takes its downloads through artifact-cache.sh, so those come with them."""
    vdir = tmp / "verify"
    vdir.mkdir(parents=True, exist_ok=True)
    helpers = ((VERIFY / "tf_plugin_cache.py",) if RUNNER in scripts else ()) + \
        ((VERIFY / "artifact-cache.sh", VERIFY / "artifact_cache.py") if FETCH in scripts else ())
    for s in scripts + helpers:
        shutil.copy2(s, vdir / s.name)
    (vdir / "e2e-tools.lock").write_text(lock)
    return vdir


def run(script: pathlib.Path, tmp: pathlib.Path, bindir: pathlib.Path,
        cache: pathlib.Path | None = None) -> subprocess.CompletedProcess:
    # TMPDIR is the fixture's own (#909): run-tests.sh and no-cloud.sh mktemp, and on 2026-11-05 run 17593's host /tmp
    # was an unlinked directory (stat Links: 0), so a mktemp falling back to /tmp failed and this test with it.
    env = {"PATH": f"{bindir}:{os.environ['PATH']}", "HOME": str(tmp), "TMPDIR": str(tmp), **TF_CACHE_ENV,
           **fetch_env(tmp, cache)}
    return subprocess.run([BASH, str(script)], capture_output=True, text=True, timeout=120, env=env)


def block(out: str, label: str) -> str:
    """What the runner printed for one check: the lines between its `== label ==` heading and its `-- label took`."""
    head, tail = f"\n== {label} ==\n", f"-- {label} took "
    if head not in out or tail not in out.split(head, 1)[1]:
        return f"<no whole block for {label}>"
    return out.split(head, 1)[1].split(tail, 1)[0]


def curl_calls(tmp: pathlib.Path) -> list[str]:
    """Every network fetch the scratch checkout's runs made: the artifact cache's fetch-log lines, then any call to the
    curl tripwire, which a fetch that bypassed the cache would make."""
    out = []
    for name in ("fetch.log", "curl.log"):
        log = tmp / name
        out += log.read_text().splitlines() if log.exists() else []
    return out


def cached(tmp: pathlib.Path) -> list[str]:
    """The files in the scratch checkout's cache root, but the per-sum lock files: no temp or unverified file."""
    d = CACHE_BASE / tmp.name / "sha256"
    return sorted(p.name for p in d.iterdir() if not p.name.endswith(".lock")) if d.is_dir() else []


GOOD_FILES = ("alpha-linux_x86_64.tar.gz", "beta_linux_amd64.zip", "gamma-linux-amd64",
              "epsilon-x86_64-unknown-linux-gnu.tar.xz")
with tempfile.TemporaryDirectory() as t, tempfile.TemporaryDirectory() as t2:
    tmp = pathlib.Path(t)
    vdir = scratch(tmp, GOOD_LOCK, (FETCH,))
    make_stubs(tmp / "bin")
    # A worktree that ran the fetch before #1118 holds its own copy of every download here; the fetch removes it.
    (vdir / ".tools" / "dl").mkdir(parents=True)
    (vdir / ".tools" / "dl" / "terraform_1.15.6_linux_amd64.zip").write_bytes(b"an old per-worktree copy")
    served = SERVER.requests()
    r = run(vdir / FETCH.name, tmp, tmp / "bin")
    check(f"a lock whose artifacts match installs every tool (exit {r.returncode})", r.returncode == 0,
          r.stdout + r.stderr)
    for name, body in (("alpha", b"echo alpha"), ("beta", b"echo beta"), ("gamma", b"echo gamma"),
                       ("epsilon", b"echo epsilon")):
        b = vdir / ".tools" / "bin" / name
        check(f"{name} is in .tools/bin, executable, holding the archive's member",
              b.is_file() and os.access(b, os.X_OK) and body in b.read_bytes())
    check("each artifact was downloaded once, through the cache", len(curl_calls(tmp)) == 4
          and SERVER.requests() - served == 4 and all(ln.endswith("\tok") for ln in curl_calls(tmp)),
          str(curl_calls(tmp)))
    check("the cache holds each download once, under its sum, and nothing unverified",
          cached(tmp) == sorted(sha(FIXTURES[f]) for f in GOOD_FILES), str(cached(tmp)))
    check("the worktree keeps no copy of any download: the old .tools/dl is gone (#1004)",
          not (vdir / ".tools" / "dl").exists() and sorted(p.name for p in (vdir / ".tools").iterdir()) == ["bin"],
          str(list((vdir / ".tools").iterdir())))
    check("the zip artifact was read without unzip, which Tanjiro's runner lacks (#1047)",
          not (tmp / "unzip.log").exists(), (tmp / "unzip.log").read_text() if (tmp / "unzip.log").exists() else "")
    first, served = len(curl_calls(tmp)), SERVER.requests()
    r = run(vdir / FETCH.name, tmp, tmp / "bin")
    check(f"a second run takes every download from the cache and fetches nothing (exit {r.returncode})",
          r.returncode == 0 and len(curl_calls(tmp)) == first and SERVER.requests() == served,
          str(curl_calls(tmp)[first:]))

    # A fresh worktree on the same host: a scratch checkout of its own, with no .tools, on the same cache root.
    tmp2 = pathlib.Path(t2)
    vdir2 = scratch(tmp2, GOOD_LOCK, (FETCH,))
    make_stubs(tmp2 / "bin")
    r = run(vdir2 / FETCH.name, tmp2, tmp2 / "bin", cache=CACHE_BASE / tmp.name)
    check(f"a run from a fresh worktree on the same cache installs every tool (exit {r.returncode})",
          r.returncode == 0 and all(os.access(vdir2 / ".tools" / "bin" / n, os.X_OK)
                                    for n in ("alpha", "beta", "gamma", "epsilon")), r.stdout + r.stderr)
    check("and makes no network fetch for any lock entry (#1004, #1118)",
          SERVER.requests() == served and curl_calls(tmp2) == [], str(curl_calls(tmp2)))

    gamma = artifact_cache.path_for(sha(FIXTURES["gamma-linux-amd64"]), CACHE_BASE / tmp.name)
    gamma.write_bytes(b"tampered")
    r = run(vdir / FETCH.name, tmp, tmp / "bin")
    check(f"a cached download that no longer matches fails the fetch (exit {r.returncode})",
          r.returncode == 1 and "E2E TOOLS FETCH FAILED; this is a failure, not a skip" in r.stderr, r.stderr)
    check("naming the tool, the cached file and both sums",
          f"gamma v3: cache hit {gamma} does not match its pin: expected SHA-256 {sha(FIXTURES['gamma-linux-amd64'])}, "
          f"got {sha(b'tampered')}" in r.stderr, r.stderr)
    check("and it is never used, nor fetched again over: no request, and the file is left for a person to look at",
          SERVER.requests() == served and len(curl_calls(tmp)) == first and gamma.read_bytes() == b"tampered",
          str(curl_calls(tmp)[first:]))
    check("the tool's old binary is removed, and the others are still installed",
          not (vdir / ".tools" / "bin" / "gamma").exists()
          and all((vdir / ".tools" / "bin" / n).is_file() for n in ("alpha", "beta", "epsilon")))

with tempfile.TemporaryDirectory() as t:
    tmp = pathlib.Path(t)
    vdir = scratch(tmp, BAD_LOCK, (FETCH,))
    make_stubs(tmp / "bin")
    r = run(vdir / FETCH.name, tmp, tmp / "bin")
    check(f"a mismatched checksum and a missing artifact exit 1 (exit {r.returncode})", r.returncode == 1)
    check("it says the fetch failed, as a failure and not a skip",
          "E2E TOOLS FETCH FAILED; this is a failure, not a skip" in r.stderr, r.stderr)
    check("it names the mismatch with the expected and the downloaded SHA-256",
          f"alpha v1: download of {URL}/alpha-linux_x86_64.tar.gz does not match its pin: expected SHA-256 {'0' * 64}, "
          f"got {sha(FIXTURES['alpha-linux_x86_64.tar.gz'])}" in r.stderr, r.stderr)
    check("it names the artifact it could not download",
          f"delta v4: fetch of {URL}/delta-linux-amd64 for SHA-256 {'1' * 64} failed: HTTP Error 404" in r.stderr,
          r.stderr)
    check("a 404 is asked once, not retried", sum(ln.count("\terror ") for ln in curl_calls(tmp)) == 1,
          str(curl_calls(tmp)))
    check("no binary is installed from a failed fetch",
          not (vdir / ".tools" / "bin" / "alpha").exists() and not (vdir / ".tools" / "bin" / "delta").exists())
    check("no unverified download is kept, in the cache or the worktree",
          cached(tmp) == [] and not (vdir / ".tools" / "dl").exists(), str(cached(tmp)))

with tempfile.TemporaryDirectory() as t:
    tmp = pathlib.Path(t)
    vdir = scratch(tmp, GOOD_LOCK, (FETCH,))
    make_stubs(tmp / "bin")
    inside = tmp / "repo" / "cache"
    (tmp / "repo" / ".git").mkdir(parents=True)
    r = run(vdir / FETCH.name, tmp, tmp / "bin", cache=inside)
    check(f"a cache root inside a git worktree fails the fetch before any download, naming it (exit {r.returncode})",
          r.returncode == 1 and "E2E TOOLS FETCH FAILED: no usable artifact cache: " in r.stderr
          and f"{inside} (from WIB_ARTIFACT_CACHE) is inside the git worktree {tmp / 'repo'}" in r.stderr
          and not curl_calls(tmp), r.stderr)

with tempfile.TemporaryDirectory() as t:
    tmp = pathlib.Path(t)
    vdir = scratch(tmp, GOOD_LOCK, (FETCH,))
    make_stubs(tmp / "bin", {"uname": '#!/bin/sh\ncase "$1" in -s) echo Darwin ;; -m) echo arm64 ;; esac\n'})
    r = run(vdir / FETCH.name, tmp, tmp / "bin")
    check(f"on a host the lock has no binaries for, it exits 1 and says why (exit {r.returncode})",
          r.returncode == 1 and "pins Linux x86_64 binaries; this host is Darwin arm64" in r.stderr
          and not curl_calls(tmp), r.stderr)

print("== run-e2e-tools.sh stops before any test when it cannot have its tools ==")
NODE24 = '#!/bin/sh\ncase "$1" in -p) echo 24 ;; --version) echo v24.22.0 ;; esac\n'
NODE22 = '#!/bin/sh\ncase "$1" in -p) echo 22 ;; --version) echo v22.11.0 ;; esac\n'
PREREQS = {"jq": "#!/bin/sh\nexit 0\n", "openssl": "#!/bin/sh\nexit 0\n", "xz": "#!/bin/sh\nexit 0\n"}


def uv_listing(browsers: pathlib.Path, installed: bool) -> str:
    """A uv whose `playwright install --dry-run chromium` lists two browsers under browsers, installed or not."""
    browsers.mkdir(parents=True, exist_ok=True)
    listing = ""
    for name, d in (("Chrome for Testing 1 (playwright chromium v9)", "chromium-9"),
                    ("FFmpeg (playwright ffmpeg v9)", "ffmpeg-9")):
        if installed:
            (browsers / d).mkdir(exist_ok=True)
            (browsers / d / "INSTALLATION_COMPLETE").touch()
        listing += f"{name}\n  Install location:    {browsers / d}\n  Download url:        https://fixture.invalid/{d}\n\n"
    return f"#!/bin/sh\ncat <<'EOF'\n{listing}EOF\n"


with tempfile.TemporaryDirectory() as t:
    tmp = pathlib.Path(t)
    vdir = scratch(tmp, BAD_LOCK, (FETCH, RUNNER, BROWSERS))
    make_stubs(tmp / "bin", {**PREREQS, "uv": uv_listing(tmp / "ms-playwright", True), "node": NODE24})
    r = run(vdir / RUNNER.name, tmp, tmp / "bin")
    check(f"a failed fetch fails the tier (exit {r.returncode})", r.returncode == 1)
    check("it says the tier cannot run, as a failure and not a skip",
          "E2E TOOLS TIER CANNOT RUN; this is a failure, not a skip: the pinned tools could not be fetched"
          in r.stderr, r.stderr)
    check("the fetch's own reasons are shown", "delta v4: fetch of " in r.stderr, r.stderr)
    check("no test ran", "== " not in r.stdout, r.stdout)

with tempfile.TemporaryDirectory() as t:
    tmp = pathlib.Path(t)
    vdir = scratch(tmp, GOOD_LOCK, (FETCH, RUNNER, BROWSERS))
    make_stubs(tmp / "bin", {**PREREQS, "uv": uv_listing(tmp / "ms-playwright", True), "node": NODE22})
    r = run(vdir / RUNNER.name, tmp, tmp / "bin")
    check(f"a Node other than 24 fails the tier before any fetch (exit {r.returncode})",
          r.returncode == 1 and "node v22.11.0 is on PATH; the node harnesses run on Node 24" in r.stderr
          and not curl_calls(tmp), r.stderr)
    check("no test ran", "== " not in r.stdout, r.stdout)

with tempfile.TemporaryDirectory() as t:
    tmp = pathlib.Path(t)
    vdir = scratch(tmp, GOOD_LOCK, (FETCH, RUNNER, BROWSERS))
    browsers = tmp / "ms-playwright"
    make_stubs(tmp / "bin", {**PREREQS, "uv": uv_listing(browsers, False), "node": NODE24})
    browsers.chmod(0o555)
    try:
        r = run(vdir / RUNNER.name, tmp, tmp / "bin")
    finally:
        browsers.chmod(0o755)
    check(f"Playwright browsers missing from a directory it cannot write fail the tier before any fetch "
          f"(exit {r.returncode})",
          r.returncode == 1 and "E2E TOOLS TIER CANNOT RUN; this is a failure, not a skip" in r.stderr
          and not curl_calls(tmp), r.stderr)
    check("it names the directory and each missing browser at its install location",
          f"Playwright's browsers directory {browsers} is not writable" in r.stderr
          and f"FFmpeg (playwright ffmpeg v9) at {browsers / 'ffmpeg-9'}" in r.stderr
          and f"Chrome for Testing 1 (playwright chromium v9) at {browsers / 'chromium-9'}" in r.stderr, r.stderr)
    check("no test ran", "== " not in r.stdout, r.stdout)

print("== a tier test that calls aws or eksctl fails, and the pinned tools still answer (#865) ==")
# The whole runner, in a scratch verify/ whose tier is four fixture tests. The host's aws and eksctl here log as
# "host" and stand in for hecaton's wrapper, which carries the run's live session: if one is ever reached, the
# runner's stub was not first on PATH. AWS_PROFILE is set as a dispatched run has it.
TIER_LOCK = f"kubectl v9 {sha(FIXTURES['kubectl-linux-amd64'])} {URL}/kubectl-linux-amd64 -\n"
TIER_TESTS = {
    "test_calls_aws.sh": "aws sts get-caller-identity >/dev/null 2>&1 || true\nexit 0\n",
    "test_calls_eksctl.sh": "eksctl utils write-kubeconfig --cluster watch-it-burn-private\n",
    "test_calls_aws_env.py": ("import os, subprocess, sys\n"
                              "subprocess.run(['aws', 'eks', 'list-clusters'], env={'PATH': os.environ['PATH']},"
                              " capture_output=True)\nsys.exit(0)\n"),
    "test_calls_kubectl.sh": "kubectl version --client || true\nexit 0\n",
}
HOST_CLOUD = '#!/bin/sh\necho "host $(basename "$0") $*" >>"$HOST_LOG"\nexit 0\n'
with tempfile.TemporaryDirectory() as t:
    tmp = pathlib.Path(t)
    vdir = scratch(tmp, TIER_LOCK, (FETCH, RUNNER, BROWSERS, VERIFY / "no-cloud.sh", VERIFY / "ensure-submodules.sh"))
    (vdir / "run-tests.sh").write_text("#!/usr/bin/env bash\nexit 0\n")
    for name, body in TIER_TESTS.items():
        (vdir / name).write_text(f"# SUITE: e2e\n# E2E TIER: tools\n{body}")
    make_stubs(tmp / "bin", {**PREREQS, "uv": uv_listing(tmp / "ms-playwright", True), "node": NODE24,
                             "aws": HOST_CLOUD, "eksctl": HOST_CLOUD})
    env = {"PATH": f"{tmp / 'bin'}:{os.environ['PATH']}", "HOME": str(tmp), "TMPDIR": str(tmp), **TF_CACHE_ENV, "AWS_PROFILE": "accen-dev",
           **fetch_env(tmp),
           "KUBECTL_LOG": str(tmp / "kubectl.log"), "HOST_LOG": str(tmp / "host.log")}
    r = subprocess.run([BASH, str(vdir / RUNNER.name)], capture_output=True, text=True, timeout=120, env=env)
    out = r.stdout + r.stderr
    check(f"the runner reached its tier and ran all four fixture tests (exit {r.returncode})",
          re.search(r"5 checks ran \(the offline suite and 4 tier tests\) in \d+m\d\ds, 4 at a time", out), out)
    check("it fails, naming the three tests that called a cloud tool and not the kubectl one",
          r.returncode == 1 and all(f"  {n} (exit 1)" in r.stderr for n in
                                    ("test_calls_aws.sh", "test_calls_eksctl.sh", "test_calls_aws_env.py"))
          and "test_calls_kubectl.sh (exit" not in r.stderr, r.stderr)
    # The four run at once (#1005), so each call must be named in the block of the test that made it, not another's.
    check("a test that swallows aws's failure and exits 0 still fails, and the call is named in its own block",
          "    aws sts get-caller-identity" in block(r.stdout, "test_calls_aws.sh"), r.stdout)
    check("the eksctl call is named in its test's block",
          "    eksctl utils write-kubeconfig --cluster watch-it-burn-private" in block(r.stdout, "test_calls_eksctl.sh"),
          r.stdout)
    check("a python subprocess with env= of PATH alone still reaches the stub, named in its test's block",
          "    aws eks list-clusters" in block(r.stdout, "test_calls_aws_env.py"), r.stdout)
    check("the kubectl test's block names no cloud call", "TEST CALLED A CLOUD TOOL" not in
          block(r.stdout, "test_calls_kubectl.sh"), block(r.stdout, "test_calls_kubectl.sh"))
    host = (tmp / "host.log").read_text() if (tmp / "host.log").exists() else ""
    check("nothing reached the host's aws or eksctl", host == "", host)
    kube = (tmp / "kubectl.log").read_text().splitlines() if (tmp / "kubectl.log").exists() else []
    check("the fetched kubectl is what the kubectl test ran, unstubbed", kube == ["fetched version --client"], str(kube))

print("== a tier test gets an empty Helm home of its own, never the host's (#921's run) ==")
# Run 17641's tier failed six tests on the host's Helm home, which listed a `cilium` repository with no cached
# index, so every `helm pull --repo` failed. Here HOME carries that same repositories.yaml, and the one fixture
# tier test reports where Helm would look and what it would find there.
HELM_VARS = ("HELM_CONFIG_HOME", "HELM_CACHE_HOME", "HELM_DATA_HOME")
HELM_PROBE = ("import json, os, pathlib, sys\n"
              f"names = {HELM_VARS!r}\n"
              "seen = {n: os.environ.get(n, '') for n in names}\n"
              "listed = {n: sorted(p.name for p in pathlib.Path(v).iterdir()) if v and pathlib.Path(v).is_dir()"
              " else None for n, v in seen.items()}\n"
              "pathlib.Path(os.environ['HELM_LOG']).write_text(json.dumps({'seen': seen, 'listed': listed}))\n"
              "sys.exit(0)\n")
with tempfile.TemporaryDirectory() as t:
    tmp = pathlib.Path(t)
    vdir = scratch(tmp, TIER_LOCK, (FETCH, RUNNER, BROWSERS, VERIFY / "no-cloud.sh", VERIFY / "ensure-submodules.sh"))
    (vdir / "run-tests.sh").write_text("#!/usr/bin/env bash\nexit 0\n")
    (vdir / "test_helm_home.py").write_text(f"# SUITE: e2e\n# E2E TIER: tools\n{HELM_PROBE}")
    host_helm = tmp / ".config" / "helm"
    host_helm.mkdir(parents=True)
    (host_helm / "repositories.yaml").write_text("repositories:\n- name: cilium\n  url: https://helm.cilium.io\n")
    make_stubs(tmp / "bin", {**PREREQS, "uv": uv_listing(tmp / "ms-playwright", True), "node": NODE24})
    env = {"PATH": f"{tmp / 'bin'}:{os.environ['PATH']}", "HOME": str(tmp), "TMPDIR": str(tmp), **TF_CACHE_ENV,
           **fetch_env(tmp), "HELM_LOG": str(tmp / "helm.json"),
           "HELM_CONFIG_HOME": str(host_helm)}
    r = subprocess.run([BASH, str(vdir / RUNNER.name)], capture_output=True, text=True, timeout=120, env=env)
    out = r.stdout + r.stderr
    check(f"the runner ran the fixture tier test and passed (exit {r.returncode})",
          r.returncode == 0 and re.search(r"2 checks ran \(the offline suite and 1 tier tests\) in \d+m\d\ds, 4 at a time", out), out)
    got = json.loads((tmp / "helm.json").read_text()) if (tmp / "helm.json").exists() else {}
    seen, listed = got.get("seen", {}), got.get("listed", {})
    for var in HELM_VARS:
        value = seen.get(var, "")
        check(f"{var} is set for the tier test, outside HOME and away from the caller's own setting",
              bool(value) and not pathlib.Path(value).is_relative_to(tmp / ".config")
              and not pathlib.Path(value).is_relative_to(tmp / ".cache") and value != str(host_helm), str(seen))
        check(f"{var} is an empty directory when the test starts", listed.get(var) == [], str(listed))
    check("the three are separate directories", len({seen.get(v) for v in HELM_VARS}) == 3, str(seen))
    check("the Helm home is gone once the runner exits",
          all(seen.get(v) and not pathlib.Path(seen[v]).exists() for v in HELM_VARS), str(seen))

print("== the tier runs its checks at once, each printed whole, and the terraform tests one at a time (#1005) ==")
# Run one after another, the offline suite and the tier took more than the gate's hour on staging 629c53ea. The runner
# now runs E2E_TOOLS_JOBS checks at once. Two fixture tests here meet: each says it has started, waits for the
# other's mark and prints a second line, so they pass only when both run at the same time, and each one's two lines
# must come out together. Two more carry `# E2E SERIAL: terraform`: each fails if the other's busy mark is there when
# it starts, so they pass only when they take turns, and one of them meets a plain test, so taking turns holds no other
# check back.
MEET = ("echo \"$1 started\"\ntouch \"$PAIR_DIR/$1\"\nn=0\n"
        "while [ ! -e \"$PAIR_DIR/$2\" ] && [ \"$n\" -lt \"$PAIR_POLLS\" ]; do sleep 0.1; n=$((n + 1)); done\n"
        "[ -e \"$PAIR_DIR/$2\" ] || { echo \"$1 never saw $2 start\"; exit 1; }\necho \"$1 saw $2\"\n")
TURN = ("[ ! -e \"$PAIR_DIR/busy\" ] || { echo \"$1 started while another terraform test ran\"; exit 1; }\n"
        "touch \"$PAIR_DIR/busy\"\necho \"start $1\" >>\"$PAIR_DIR/turns\"\n")
TURN_END = "sleep 1\necho \"end $1\" >>\"$PAIR_DIR/turns\"\nrm \"$PAIR_DIR/busy\"\n"
POOL_TESTS = {
    "test_pair_a.sh": ("", f"set -- pair_a pair_b\n{MEET}"),
    "test_pair_b.sh": ("", f"set -- pair_b pair_a\n{MEET}"),
    "test_tf_one.sh": ("# E2E SERIAL: terraform\n",
                       f"set -- tf_one\n{TURN}set -- tf_one plain\n{MEET}set -- tf_one\n{TURN_END}"),
    "test_tf_two.sh": ("# E2E SERIAL: terraform\n", f"set -- tf_two\n{TURN}{TURN_END}"),
    "test_plain.sh": ("", f"set -- plain tf_one\n{MEET}"),
}


def pool_run(tmp: pathlib.Path, extra: dict[str, str]) -> subprocess.CompletedProcess:
    pair = tmp / "pair"
    shutil.rmtree(pair, ignore_errors=True)
    pair.mkdir()
    env = {"PATH": f"{tmp / 'bin'}:{os.environ['PATH']}", "HOME": str(tmp), "TMPDIR": str(tmp), **TF_CACHE_ENV,
           **fetch_env(tmp), "PAIR_DIR": str(pair), **extra}
    return subprocess.run([BASH, str(tmp / "verify" / RUNNER.name)], capture_output=True, text=True, timeout=240,
                          env=env)


with tempfile.TemporaryDirectory() as t:
    tmp = pathlib.Path(t)
    vdir = scratch(tmp, TIER_LOCK, (FETCH, RUNNER, BROWSERS, VERIFY / "no-cloud.sh", VERIFY / "ensure-submodules.sh"))
    (vdir / "run-tests.sh").write_text("#!/usr/bin/env bash\necho offline suite ran\nexit 0\n")
    for name, (mark, body) in POOL_TESTS.items():
        (vdir / name).write_text(f"# SUITE: e2e\n# E2E TIER: tools\n{mark}{body}")
    make_stubs(tmp / "bin", {**PREREQS, "uv": uv_listing(tmp / "ms-playwright", True), "node": NODE24})
    # 600 polls of 0.1 s: a minute for the partner to start, which only a broken runner needs.
    r = pool_run(tmp, {"PAIR_POLLS": "600"})
    out = r.stdout + r.stderr
    check(f"the five fixture checks pass, four at a time by default (exit {r.returncode})",
          r.returncode == 0 and re.search(r"6 checks ran \(the offline suite and 5 tier tests\) in \d+m\d\ds, 4 at a time", out), out)
    check("the offline suite runs and is printed as a check of its own",
          block(r.stdout, "run-tests.sh (the offline suite)") == "offline suite ran\n", r.stdout)
    for me, other in (("pair_a", "pair_b"), ("pair_b", "pair_a"), ("plain", "tf_one")):
        name = "test_tf_one.sh" if me == "tf_one" else f"test_{me}.sh"
        check(f"{name} ran while {other} did, and its two lines are printed together under its heading",
              block(r.stdout, name) == f"{me} started\n{me} saw {other}\n", block(r.stdout, name))
    check("a terraform test runs beside a plain one", "tf_one saw plain\n" in block(r.stdout, "test_tf_one.sh"),
          block(r.stdout, "test_tf_one.sh"))
    turns = (tmp / "pair" / "turns").read_text().splitlines() if (tmp / "pair" / "turns").exists() else []
    check("the two terraform tests took turns: one ended before the other started",
          turns in (["start tf_one", "end tf_one", "start tf_two", "end tf_two"],
                    ["start tf_two", "end tf_two", "start tf_one", "end tf_one"]), str(turns))
    check("every check's seconds are printed, and the slowest listed at the end",
          all(f"-- {n} took " in r.stdout for n in POOL_TESTS) and "\nThe slowest checks:\n" in r.stdout, r.stdout)

    # One at a time, the two that must meet cannot: each gives up after 2 s and fails, naming the other.
    r = pool_run(tmp, {"PAIR_POLLS": "20", "E2E_TOOLS_JOBS": "1"})
    out = r.stdout + r.stderr
    check(f"E2E_TOOLS_JOBS=1 runs one check at a time, so the pair that must meet fails (exit {r.returncode})",
          r.returncode == 1 and re.search(r"6 checks ran \(the offline suite and 5 tier tests\) in \d+m\d\ds, 1 at a time", out)
          and "pair_a never saw pair_b start" in block(r.stdout, "test_pair_a.sh")
          and "  test_pair_a.sh (exit 1)" in r.stderr, out)

    for bad in ("0", "two", "-3"):
        r = pool_run(tmp, {"PAIR_POLLS": "1", "E2E_TOOLS_JOBS": bad})
        check(f"E2E_TOOLS_JOBS={bad} fails before any fetch or test, as a failure and not a skip (exit {r.returncode})",
              r.returncode == 1 and "E2E TOOLS TIER CANNOT RUN; this is a failure, not a skip" in r.stderr
              and f"E2E_TOOLS_JOBS is '{bad}', not a whole number of 1 or more" in r.stderr
              and "== " not in r.stdout, r.stdout + r.stderr)

print("== a terraform test waits for the shared provider cache's lock, and fails naming it when never free (#1114) ==")
# The cache now outlives the checkout, so a run in another checkout can share it. Each terraform test holds
# <cache>.lock while it runs. Here the lock is held from outside, as another run would hold it: with a wait of 1 s the
# terraform test fails without starting, naming the lock, and a plain test beside it still passes. Released, the same
# run passes.
with tempfile.TemporaryDirectory() as t:
    tmp = pathlib.Path(t)
    vdir = scratch(tmp, TIER_LOCK, (FETCH, RUNNER, BROWSERS, VERIFY / "no-cloud.sh", VERIFY / "ensure-submodules.sh"))
    (vdir / "run-tests.sh").write_text("#!/usr/bin/env bash\nexit 0\n")
    (vdir / "test_tf_locked.sh").write_text("# SUITE: e2e\n# E2E TIER: tools\n# E2E SERIAL: terraform\n"
                                            "echo terraform test ran\n")
    (vdir / "test_plain_beside.sh").write_text("# SUITE: e2e\n# E2E TIER: tools\necho plain test ran\n")
    make_stubs(tmp / "bin", {**PREREQS, "uv": uv_listing(tmp / "ms-playwright", True), "node": NODE24})
    lock_path = pathlib.Path(TF_CACHE_ENV["TF_PLUGIN_CACHE_DIR"] + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    # Held by this process, as flock(1) in the runner takes it, and released when the file closes.
    with lock_path.open("a") as held:
        fcntl.flock(held, fcntl.LOCK_EX)
        r = pool_run(tmp, {"TF_CACHE_LOCK_WAIT": "1", "PAIR_POLLS": "1"})
    locked = block(r.stdout, "test_tf_locked.sh")
    check(f"with the lock held elsewhere the terraform test fails (exit {r.returncode})",
          r.returncode == 1 and "  test_tf_locked.sh (exit 1)" in r.stderr, r.stdout + r.stderr)
    check("it names the lock and the wait, and never starts",
          f"FAIL: {lock_path} was held by another run for 1s" in locked and "terraform test ran" not in locked, locked)
    check("the plain test beside it still passes", block(r.stdout, "test_plain_beside.sh") == "plain test ran\n",
          r.stdout)
    r = pool_run(tmp, {"TF_CACHE_LOCK_WAIT": "1", "PAIR_POLLS": "1"})
    check(f"released, the same run passes and the terraform test runs (exit {r.returncode})",
          r.returncode == 0 and block(r.stdout, "test_tf_locked.sh") == "terraform test ran\n", r.stdout + r.stderr)
    check("the runner names the cache it used", f"Terraform provider cache: {TF_CACHE_ENV['TF_PLUGIN_CACHE_DIR']}\n"
          in r.stdout, r.stdout)

print("== stopped by a signal, the runner names what still ran and stops it (#1005) ==")
# The gate's timeout interrupts the command, then terminates it. The signal here goes to the runner alone, so what
# the fixture started is stopped by the runner and not by a signal to its whole group.
SLEEPER = ("echo \"sleeper started\"\nsleep 300 &\necho $! >\"$PAIR_DIR/sleep.pid\"\necho \"sleeping now\"\n"
           "touch \"$PAIR_DIR/ready\"\nwait\n")
with tempfile.TemporaryDirectory() as t:
    tmp = pathlib.Path(t)
    vdir = scratch(tmp, TIER_LOCK, (FETCH, RUNNER, BROWSERS, VERIFY / "no-cloud.sh", VERIFY / "ensure-submodules.sh"))
    (vdir / "run-tests.sh").write_text("#!/usr/bin/env bash\nexit 0\n")
    (vdir / "test_ends.sh").write_text("# SUITE: e2e\n# E2E TIER: tools\necho ended\n")
    (vdir / "test_sleeper.sh").write_text(f"# SUITE: e2e\n# E2E TIER: tools\n{SLEEPER}")
    make_stubs(tmp / "bin", {**PREREQS, "uv": uv_listing(tmp / "ms-playwright", True), "node": NODE24})
    pair = tmp / "pair"
    pair.mkdir()
    env = {"PATH": f"{tmp / 'bin'}:{os.environ['PATH']}", "HOME": str(tmp), "TMPDIR": str(tmp), **TF_CACHE_ENV,
           **fetch_env(tmp), "PAIR_DIR": str(pair)}
    proc = subprocess.Popen([BASH, str(vdir / RUNNER.name)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                            env=env, start_new_session=True)
    # The signal waits for the runner to have printed test_ends.sh as ended, not only for the sleeper: on a loaded
    # host the runner had not yet reaped test_ends.sh when the sleeper was ready, and listed it as still running
    # (run 18118, #998). The runner's output is read as it comes, so its `-- test_ends.sh took` line can be seen.
    out_lines: list[str] = []
    err_lines: list[str] = []
    readers = [threading.Thread(target=lambda s=s, d=d: d.extend(s), daemon=True)
               for s, d in ((proc.stdout, out_lines), (proc.stderr, err_lines))]
    for r in readers:
        r.start()
    polls = 0
    while (not (pair / "ready").exists() or not any(line.startswith("-- test_ends.sh took") for line in out_lines)) \
            and proc.poll() is None and polls < 1200:
        subprocess.run(["sleep", "0.1"])
        polls += 1
    ready = (pair / "ready").exists()
    proc.terminate()
    try:
        proc.wait(timeout=60)
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, 9)
        proc.wait()
    for r in readers:
        r.join(timeout=30)
    stdout, stderr = "".join(out_lines), "".join(err_lines)
    check("the sleeper reached its sleep before the signal", ready, stdout + stderr)
    check(f"the stopped runner exits 1 (exit {proc.returncode})", proc.returncode == 1, stdout + stderr)
    check("it says it was stopped and names the check still running, with its seconds and last lines",
          "STOPPED by a signal after " in stdout and "  test_sleeper.sh, for " in stdout
          and "      sleeping now" in stdout, stdout)
    check("the check that had ended is printed whole before the stop", block(stdout, "test_ends.sh") == "ended\n",
          stdout)
    sleep_pid = int((pair / "sleep.pid").read_text()) if (pair / "sleep.pid").exists() else 0
    gone, polls = False, 0
    while sleep_pid and not gone and polls < 100:
        try:
            os.kill(sleep_pid, 0)
            gone = pathlib.Path(f"/proc/{sleep_pid}/stat").read_text().split(") ", 1)[1].startswith("Z")
        except (ProcessLookupError, FileNotFoundError):
            gone = True
        if not gone:
            subprocess.run(["sleep", "0.1"])
            polls += 1
    check("what the check started is stopped with it", sleep_pid > 0 and gone, f"sleep pid {sleep_pid}")
    if sleep_pid and not gone:
        os.kill(sleep_pid, 9)
    with contextlib.suppress(ProcessLookupError):
        os.killpg(proc.pid, 9)

print("== run-e2e.sh fetches the same tools and runs them first on PATH (#585) ==")
RUN_E2E = VERIFY / "run-e2e.sh"
live = "\n".join(line for line in RUN_E2E.read_text().splitlines() if not line.lstrip().startswith("#"))
check("run-e2e.sh runs fetch-e2e-tools.sh", 'bash "${SCRIPT_DIR}/fetch-e2e-tools.sh"' in live)
check("run-e2e.sh fetches into the directory the tier runs from", 'TOOLS_BIN="${SCRIPT_DIR}/.tools/bin"' in live)
check("run-e2e.sh puts the fetched tools first on PATH", 'export PATH="${TOOLS_BIN}:${PATH}"' in live)
for var, tool in (("KYVERNO_CLI", "kyverno"), ("CONFTEST", "conftest"), ("TERRAFORM", "terraform"),
                  ("OTELCOL_CONTRIB", "otelcol-contrib"), ("TTYD", "ttyd"), ("CRANE", "crane"),
                  ("AGENTGATEWAY", "agentgateway")):
    check(f"run-e2e.sh points {var} at the fetched {tool}", f'{var}="${{TOOLS_BIN}}/{tool}"' in live)
check("run-e2e.sh never looks for otelcol-contrib on PATH (#654)",
      "command -v" not in "\n".join(line for line in live.splitlines() if "otelcol" in line.lower()))
# The host's kubectl logs as "host": if it is ever what runs, the fetched one was not first on PATH.
HOST_KUBECTL = '#!/bin/sh\necho "host $*" >>"$KUBECTL_LOG"\nexit 1\n'


def run_live(tmp: pathlib.Path, vdir: pathlib.Path) -> subprocess.CompletedProcess:
    env = {"PATH": f"{tmp / 'bin'}:{os.environ['PATH']}", "HOME": str(tmp), "TMPDIR": str(tmp), **TF_CACHE_ENV,
           "KUBECONFIG": "/dev/null", "CONTEXT": "wib-fixture", **fetch_env(tmp),
           "KUBECTL_LOG": str(tmp / "kubectl.log")}
    return subprocess.run([BASH, str(vdir / RUN_E2E.name)], capture_output=True, text=True, timeout=120, env=env)


def kubectl_calls(tmp: pathlib.Path) -> list[str]:
    log = tmp / "kubectl.log"
    return log.read_text().splitlines() if log.exists() else []


LIVE_CANNOT_RUN = "E2E SUITE CANNOT RUN; this is a failure, not a skip"
with tempfile.TemporaryDirectory() as t:
    tmp = pathlib.Path(t)
    vdir = scratch(tmp, SEVEN_LOCK, (FETCH, RUN_E2E))
    make_stubs(tmp / "bin", {"kubectl": HOST_KUBECTL})
    r = run_live(tmp, vdir)
    check(f"run-e2e.sh stops in its prerequisite check (exit {r.returncode})",
          r.returncode == 1 and LIVE_CANNOT_RUN in r.stderr and "E2E checks ran" not in r.stdout + r.stderr,
          r.stdout + r.stderr)
    check("it fetched all seven tools into its .tools/bin",
          all(os.access(vdir / ".tools" / "bin" / tool, os.X_OK) for tool in SEVEN), r.stdout + r.stderr)
    check("otelcol-contrib is not listed as missing", "otelcol" not in r.stderr, r.stderr)
    check("a good fetch is not listed as missing", "could not be fetched" not in r.stderr
          and "were not fetched" not in r.stderr, r.stderr)
    check("the fetched kubectl checks the cluster, with the explicit context",
          kubectl_calls(tmp) == ["fetched --context wib-fixture --request-timeout=15s get --raw /readyz"],
          str(kubectl_calls(tmp)))
    check("the unreachable cluster is listed as missing",
          "cluster for context 'wib-fixture' is not reachable" in r.stderr, r.stderr)

with tempfile.TemporaryDirectory() as t:
    tmp = pathlib.Path(t)
    vdir = scratch(tmp, BAD_LOCK, (FETCH, RUN_E2E))
    make_stubs(tmp / "bin", {"kubectl": HOST_KUBECTL})
    r = run_live(tmp, vdir)
    check(f"a failed fetch fails run-e2e.sh in its prerequisite check (exit {r.returncode})",
          r.returncode == 1 and LIVE_CANNOT_RUN in r.stderr and "E2E checks ran" not in r.stdout + r.stderr,
          r.stdout + r.stderr)
    check("it lists the failed fetch as missing",
          "  - the pinned kyverno, conftest, terraform, kubectl, helm, otelcol-contrib, ttyd, crane, weaver and agentgateway could not "
          "be fetched" in r.stderr,
          r.stderr)
    check("the fetch's own reasons are shown", "delta v4: fetch of " in r.stderr, r.stderr)
    check("no kubectl runs, not even the host's", kubectl_calls(tmp) == [], str(kubectl_calls(tmp)))

if failures:
    shutil.rmtree(CACHE_BASE, ignore_errors=True)
    print(f"\nFAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
shutil.rmtree(CACHE_BASE, ignore_errors=True)
print("\nAll E2E tools tier checks passed.")
