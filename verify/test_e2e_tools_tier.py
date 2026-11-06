# ABOUTME: The cluster-free E2E tier (#572): its pins are VERSIONS.lock's, its tools land in a gitignored directory,
# ABOUTME: no tier test needs CONTEXT or IAM_PIPELINE_*, and a failed or tampered fetch fails loudly, never skips.
"""Holds what verify/run-e2e-tools.sh, the gate's E2E command, relies on. Offline: no download is made.

#543 took run-e2e.sh off the gate because the gate host has no cluster, no AWS and none of the cluster tools.
#572 declared the part of the E2E suite that host can run: tests marked `# E2E TIER: tools`, run with the
binaries in verify/e2e-tools.lock, which verify/fetch-e2e-tools.sh downloads into verify/.tools and checks
against the lock's SHA-256 before use.

The fetch is run here for real, in a scratch copy of the scripts, with `curl` stubbed to serve fixture
archives and log each call, and `uname`, `sha256sum` and `unzip` stubbed so the run does not depend on the
host. A good lock installs every binary, a second run downloads nothing, and a missing artifact or a
checksum mismatch exits 1 naming each failure and leaves no binary behind. run-e2e-tools.sh stops on a
failed fetch or a missing prerequisite before any test runs, and that includes Playwright browsers that are missing
from a directory `playwright install` cannot write (#658), with `uv` stubbed to list them.

run-e2e.sh, the by-hand live suite, runs the same fetch in its prerequisite check (#585), so a cluster build runs
the gate's binaries, otelcol-contrib included since #654 and ttyd since #770. Its scratch copy is run with a fixture lock of the seven tools: the fetched kubectl, not one
already on PATH, is what checks the cluster, and a failed fetch is listed as missing with no kubectl run at all.
Some prerequisite is always left missing there, so the run stops before any check or cluster call.
"""
from __future__ import annotations

import hashlib
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
import zipfile

REPO = pathlib.Path(__file__).resolve().parent.parent
VERIFY = REPO / "verify"
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
for path in ("verify/.tools/bin/kyverno", "verify/.tools/dl/terraform_1.15.6_linux_amd64.zip"):
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
check("run-e2e-tools.sh stubs aws and eksctl, and only those two, with no-cloud.sh (#865)",
      '. "${SCRIPT_DIR}/no-cloud.sh"' in code and 'no_cloud_setup "${NO_CLOUD_DIR}" aws eksctl\n' in code)
check("run-e2e-tools.sh runs each tier test through no_cloud_run",
      code.count('no_cloud_run "${tier_env[@]}"') == 2 and code.count('"${tier_env[@]}"') == 2)

print("== a fetch is checked against the lock, and fails loudly ==")

STUB_CURL = f"""#!{PY}
import os, shutil, sys
args = sys.argv[1:]
with open(os.environ["CURL_LOG"], "a") as f:
    f.write(" ".join(args) + "\\n")
out, url = args[args.index("-o") + 1], args[-1]
src = os.path.join(os.environ["FIXTURES"], url.rsplit("/", 1)[-1])
if not url.startswith("https://fixture.invalid/") or not os.path.isfile(src):
    sys.stderr.write("curl: (22) The requested URL returned error: 404\\n")
    sys.exit(22)
shutil.copyfile(src, out)
"""
STUB_SHA = f"""#!{PY}
import hashlib, sys
print(hashlib.sha256(open(sys.argv[1], "rb").read()).hexdigest() + "  " + sys.argv[1])
"""
STUB_UNZIP = f"""#!{PY}
import sys, zipfile
assert sys.argv[1] == "-p"
sys.stdout.buffer.write(zipfile.ZipFile(sys.argv[2]).read(sys.argv[3]))
"""
STUB_UNAME = '#!/bin/sh\ncase "$1" in -s) echo Linux ;; -m) echo x86_64 ;; esac\n'


def make_stubs(bindir: pathlib.Path, extra: dict[str, str] | None = None) -> None:
    bindir.mkdir(parents=True, exist_ok=True)
    stubs = {"curl": STUB_CURL, "sha256sum": STUB_SHA, "unzip": STUB_UNZIP, "uname": STUB_UNAME, **(extra or {})}
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
# run-e2e.sh's seven tools. The fetched kubectl logs each call and fails, as an unreachable cluster would.
SEVEN = ("kyverno", "conftest", "terraform", "kubectl", "helm", "otelcol-contrib", "ttyd")
for _tool in SEVEN:
    FIXTURES[f"{_tool}-linux-amd64"] = (
        b'#!/bin/sh\necho "fetched $*" >>"$KUBECTL_LOG"\nexit 1\n' if _tool == "kubectl" else b"#!/bin/sh\nexit 0\n")
SEVEN_LOCK = "".join(f"{t} v9 {sha(FIXTURES[f'{t}-linux-amd64'])} https://fixture.invalid/{t}-linux-amd64 -\n"
                     for t in SEVEN)
GOOD_LOCK = (
    "# fixture lock\n"
    f"alpha v1 {sha(FIXTURES['alpha-linux_x86_64.tar.gz'])} https://fixture.invalid/alpha-linux_x86_64.tar.gz pkg/alpha\n"
    f"beta  v2 {sha(FIXTURES['beta_linux_amd64.zip'])} https://fixture.invalid/beta_linux_amd64.zip beta\n"
    f"gamma v3 {sha(FIXTURES['gamma-linux-amd64'])} https://fixture.invalid/gamma-linux-amd64 -\n"
    f"epsilon v5 {sha(FIXTURES['epsilon-x86_64-unknown-linux-gnu.tar.xz'])} "
    "https://fixture.invalid/epsilon-x86_64-unknown-linux-gnu.tar.xz epsilon-x86_64-unknown-linux-gnu/epsilon\n"
)
BAD_LOCK = (
    f"alpha v1 {'0' * 64} https://fixture.invalid/alpha-linux_x86_64.tar.gz pkg/alpha\n"
    f"delta v4 {'1' * 64} https://fixture.invalid/delta-linux-amd64 -\n"
)


def scratch(tmp: pathlib.Path, lock: str, scripts: tuple[pathlib.Path, ...]) -> pathlib.Path:
    """A scratch verify/ holding copies of the scripts and the given lock, with fixtures and a curl log."""
    vdir = tmp / "verify"
    vdir.mkdir(parents=True, exist_ok=True)
    for s in scripts:
        shutil.copy2(s, vdir / s.name)
    (vdir / "e2e-tools.lock").write_text(lock)
    fx = tmp / "fixtures"
    fx.mkdir(exist_ok=True)
    for name, data in FIXTURES.items():
        (fx / name).write_bytes(data)
    return vdir


def run(script: pathlib.Path, tmp: pathlib.Path, bindir: pathlib.Path) -> subprocess.CompletedProcess:
    # TMPDIR is the fixture's own (#909): run-tests.sh and no-cloud.sh mktemp, and on 2026-11-05 run 17593's host /tmp
    # was an unlinked directory (stat Links: 0), so a mktemp falling back to /tmp failed and this test with it.
    env = {"PATH": f"{bindir}:{os.environ['PATH']}", "HOME": str(tmp), "TMPDIR": str(tmp),
           "CURL_LOG": str(tmp / "curl.log"), "FIXTURES": str(tmp / "fixtures")}
    return subprocess.run([BASH, str(script)], capture_output=True, text=True, timeout=120, env=env)


def curl_calls(tmp: pathlib.Path) -> list[str]:
    log = tmp / "curl.log"
    return log.read_text().splitlines() if log.exists() else []


with tempfile.TemporaryDirectory() as t:
    tmp = pathlib.Path(t)
    vdir = scratch(tmp, GOOD_LOCK, (FETCH,))
    make_stubs(tmp / "bin")
    r = run(vdir / FETCH.name, tmp, tmp / "bin")
    check(f"a lock whose artifacts match installs every tool (exit {r.returncode})", r.returncode == 0,
          r.stdout + r.stderr)
    for name, body in (("alpha", b"echo alpha"), ("beta", b"echo beta"), ("gamma", b"echo gamma"),
                       ("epsilon", b"echo epsilon")):
        b = vdir / ".tools" / "bin" / name
        check(f"{name} is in .tools/bin, executable, holding the archive's member",
              b.is_file() and os.access(b, os.X_OK) and body in b.read_bytes())
    check("each artifact was downloaded once", len(curl_calls(tmp)) == 4, str(curl_calls(tmp)))
    first = len(curl_calls(tmp))
    r = run(vdir / FETCH.name, tmp, tmp / "bin")
    check(f"a second run reuses the verified downloads and fetches nothing (exit {r.returncode})",
          r.returncode == 0 and len(curl_calls(tmp)) == first, str(curl_calls(tmp)[first:]))
    (vdir / ".tools" / "dl" / "gamma-linux-amd64").write_bytes(b"tampered")
    r = run(vdir / FETCH.name, tmp, tmp / "bin")
    check("a cached download that no longer matches is fetched again",
          r.returncode == 0 and curl_calls(tmp)[first:] and "gamma-linux-amd64" in curl_calls(tmp)[-1]
          and b"echo gamma" in (vdir / ".tools" / "bin" / "gamma").read_bytes(), r.stdout + r.stderr)

with tempfile.TemporaryDirectory() as t:
    tmp = pathlib.Path(t)
    vdir = scratch(tmp, BAD_LOCK, (FETCH,))
    make_stubs(tmp / "bin")
    r = run(vdir / FETCH.name, tmp, tmp / "bin")
    check(f"a mismatched checksum and a missing artifact exit 1 (exit {r.returncode})", r.returncode == 1)
    check("it says the fetch failed, as a failure and not a skip",
          "E2E TOOLS FETCH FAILED; this is a failure, not a skip" in r.stderr, r.stderr)
    check("it names the mismatch with the expected and the downloaded SHA-256",
          f"alpha v1: SHA-256 mismatch for https://fixture.invalid/alpha-linux_x86_64.tar.gz: expected {'0' * 64}, "
          f"got {sha(FIXTURES['alpha-linux_x86_64.tar.gz'])}" in r.stderr, r.stderr)
    check("it names the artifact it could not download",
          "delta v4: download failed: https://fixture.invalid/delta-linux-amd64" in r.stderr, r.stderr)
    check("no binary is installed from a failed fetch",
          not (vdir / ".tools" / "bin" / "alpha").exists() and not (vdir / ".tools" / "bin" / "delta").exists())
    check("no unverified download is kept", not any((vdir / ".tools" / "dl").iterdir()))

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
    check("the fetch's own reasons are shown", "delta v4: download failed" in r.stderr, r.stderr)
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
TIER_LOCK = f"kubectl v9 {sha(FIXTURES['kubectl-linux-amd64'])} https://fixture.invalid/kubectl-linux-amd64 -\n"
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
    env = {"PATH": f"{tmp / 'bin'}:{os.environ['PATH']}", "HOME": str(tmp), "TMPDIR": str(tmp), "AWS_PROFILE": "accen-dev",
           "CURL_LOG": str(tmp / "curl.log"), "FIXTURES": str(tmp / "fixtures"),
           "KUBECTL_LOG": str(tmp / "kubectl.log"), "HOST_LOG": str(tmp / "host.log")}
    r = subprocess.run([BASH, str(vdir / RUNNER.name)], capture_output=True, text=True, timeout=120, env=env)
    out = r.stdout + r.stderr
    check(f"the runner reached its tier and ran all four fixture tests (exit {r.returncode})",
          "5 checks ran (the offline suite and 4 tier tests)" in out, out)
    check("it fails, naming the three tests that called a cloud tool and not the kubectl one",
          r.returncode == 1 and all(f"  {n} (exit 1)" in r.stderr for n in
                                    ("test_calls_aws.sh", "test_calls_eksctl.sh", "test_calls_aws_env.py"))
          and "test_calls_kubectl.sh (exit" not in r.stderr, r.stderr)
    check("a test that swallows aws's failure and exits 0 still fails, and the call is named",
          "    aws sts get-caller-identity" in r.stderr, r.stderr)
    check("the eksctl call is named", "    eksctl utils write-kubeconfig --cluster watch-it-burn-private" in r.stderr,
          r.stderr)
    check("a python subprocess with env= of PATH alone still reaches the stub", "    aws eks list-clusters" in r.stderr,
          r.stderr)
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
    env = {"PATH": f"{tmp / 'bin'}:{os.environ['PATH']}", "HOME": str(tmp), "TMPDIR": str(tmp),
           "CURL_LOG": str(tmp / "curl.log"), "FIXTURES": str(tmp / "fixtures"), "HELM_LOG": str(tmp / "helm.json"),
           "HELM_CONFIG_HOME": str(host_helm)}
    r = subprocess.run([BASH, str(vdir / RUNNER.name)], capture_output=True, text=True, timeout=120, env=env)
    out = r.stdout + r.stderr
    check(f"the runner ran the fixture tier test and passed (exit {r.returncode})",
          r.returncode == 0 and "2 checks ran (the offline suite and 1 tier tests)" in out, out)
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
    env = {"PATH": f"{tmp / 'bin'}:{os.environ['PATH']}", "HOME": str(tmp), "TMPDIR": str(tmp),
           "KUBECONFIG": "/dev/null", "CONTEXT": "wib-fixture", "CURL_LOG": str(tmp / "curl.log"), "FIXTURES": str(tmp / "fixtures"),
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
    check("the fetch's own reasons are shown", "delta v4: download failed" in r.stderr, r.stderr)
    check("no kubectl runs, not even the host's", kubectl_calls(tmp) == [], str(kubectl_calls(tmp)))

if failures:
    print(f"\nFAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("\nAll E2E tools tier checks passed.")
