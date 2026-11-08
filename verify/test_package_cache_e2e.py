# ABOUTME: Real uv and the Backstage app's own yarn 4, on loopback (#1121): a warm artifact cache installs with no
# ABOUTME: fetch, and a cached Python wheel or yarn zip whose bytes do not match the pin fails the install, unfetched.
# SUITE: e2e
# E2E TIER: tools (no cluster, no AWS, no network: uv, node and the committed yarn release, on fixtures served locally)
"""The end-to-end half of verify/test_package_cache.py, which holds the same paths on stubs.

Python, with a fixture wheel built here and handed to verify/package_cache.py by a counting fetcher:
  - cold: environment() fetches the wheel once into the artifact cache and uv installs it, offline, hash-checked;
  - warm: with the environment removed, it is built again from the cache with no fetch, and uv's cache is the one in
    the artifact root;
  - a cached wheel whose bytes changed fails the call, naming both sums, with no fetch and the file left in place;
  - uv's own check: a wheelhouse whose wheel is other bytes under the pinned name fails `uv pip install
    --require-hashes` with a hash mismatch, and nothing is installed.

Node, with a one-package npm registry on 127.0.0.1 that counts its requests and the yarn release the Backstage app
commits (images/watch-it-burn-backstage/.yarn/releases), with package_cache.node_env()'s caches:
  - cold: `yarn install --no-immutable` fetches the package and writes its checksum into yarn.lock;
  - warm: a fresh project with that yarn.lock installs with `--immutable` and makes no request;
  - a cached zip whose bytes changed fails `yarn install --immutable` with YN0018, makes no request, leaves the zip
    as it was and installs nothing.

Needs uv and node. A missing tool is a failure, not a skip.
"""
from __future__ import annotations

import base64
import hashlib
import http.server
import io
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tarfile
import threading
import zipfile

VERIFY = pathlib.Path(__file__).resolve().parent
REPO = VERIFY.parent
sys.path.insert(0, str(VERIFY))
import artifact_cache  # noqa: E402
import package_cache as pc  # noqa: E402

BACKSTAGE = REPO / "images/watch-it-burn-backstage"
failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"\n        {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def finish() -> None:
    shutil.rmtree(SCRATCH, ignore_errors=True)
    if failures:
        print(f"\nFAILED: {len(failures)} check(s)")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    print("\nAll package cache end-to-end checks passed.")
    sys.exit(0)


print("== prerequisites ==")
missing = [t for t in ("uv", "node") if shutil.which(t) is None]
check(f"uv and node are on PATH (missing: {missing})", missing == [])
yarn_release = sorted((BACKSTAGE / ".yarn/releases").glob("yarn-4.*.cjs"))
check(f"the Backstage app commits a yarn 4 release ({[p.name for p in yarn_release]})", len(yarn_release) == 1)
SCRATCH = artifact_cache.scratch_dir("wib-package-cache-e2e-")
if failures:
    finish()
YARN = yarn_release[0]


# --------------------------------------------------------------------------------------------------- Python

def wheel(value: int) -> bytes:
    """A pure-Python wheel of the package wibfixture 1.0.0 whose VALUE is value, with a correct RECORD."""
    files = {
        "wibfixture/__init__.py": f"VALUE = {value}\n".encode(),
        "wibfixture-1.0.0.dist-info/METADATA": b"Metadata-Version: 2.1\nName: wibfixture\nVersion: 1.0.0\n",
        "wibfixture-1.0.0.dist-info/WHEEL": b"Wheel-Version: 1.0\nGenerator: wib\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
    }
    record = "".join(f"{n},sha256={base64.urlsafe_b64encode(hashlib.sha256(d).digest()).rstrip(b'=').decode()},{len(d)}\n"
                     for n, d in files.items()) + "wibfixture-1.0.0.dist-info/RECORD,,\n"
    files["wibfixture-1.0.0.dist-info/RECORD"] = record.encode()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for n, d in files.items():
            info = zipfile.ZipInfo(n, date_time=(2020, 1, 1, 0, 0, 0))
            z.writestr(info, d)
    return buf.getvalue()


WHEEL = wheel(42)
SUM = hashlib.sha256(WHEEL).hexdigest()
NAME = "wibfixture-1.0.0-py3-none-any.whl"
PY = f"{sys.version_info[0]}.{sys.version_info[1]}"
LOCK = pc.parse_lock(f"fx  {PY}  wibfixture  1.0.0  {SUM}  https://fixture.invalid/{NAME}\n")
FETCHES: list[str] = []


def fetch(url: str, out) -> None:
    FETCHES.append(url)
    out.write(WHEEL)


def import_value(venv: pathlib.Path) -> str:
    r = subprocess.run([str(venv / "bin" / "python"), "-I", "-c", "import wibfixture; print(wibfixture.VALUE)"],
                       capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else f"exit {r.returncode}: {r.stderr.strip()[-300:]}"


def refusal(fn) -> str:
    try:
        fn()
    except (pc.PackageCacheError, artifact_cache.ArtifactCacheError) as e:
        return str(e)
    return ""


root = SCRATCH / "artifacts"
print("== Python: cold, the wheel fetched once and installed offline, hash-checked ==")
try:
    venv = pc.environment("fx", root=root, lock=LOCK, fetch=fetch)
except pc.PackageCacheError as e:
    check("the cold build succeeds", False, str(e))
    finish()
check(f"one fetch, of the locked URL ({FETCHES})", FETCHES == [f"https://fixture.invalid/{NAME}"])
check(f"the environment imports the wheel ({import_value(venv)})", import_value(venv) == "42")
check("uv's cache is the one in the artifact root", (root / "packages" / "uv-cache").is_dir())

print("== Python: warm, built again from the cache with no fetch ==")
FETCHES.clear()
shutil.rmtree(root / "packages" / "envs")
venv = pc.environment("fx", root=root, lock=LOCK, fetch=fetch)
check(f"no fetch ({FETCHES})", FETCHES == [])
check(f"and the rebuilt environment imports it ({import_value(venv)})", import_value(venv) == "42")

print("== Python: a cached wheel whose bytes changed fails, unfetched ==")
entry = artifact_cache.path_for(SUM, root)
changed = wheel(43)
entry.write_bytes(changed)
err = refusal(lambda: pc.environment("fx", root=root, lock=LOCK, fetch=fetch))
check("the call fails, naming the wheel and both sums",
      "wibfixture 1.0.0" in err and SUM in err and hashlib.sha256(changed).hexdigest() in err, err)
check(f"no fetch ({FETCHES})", FETCHES == [])
check("the cache file is left as it was found", entry.read_bytes() == changed)

print("== Python: uv's own hash check refuses other bytes under the pinned name ==")
house = SCRATCH / "house"
house.mkdir()
(house / NAME).write_bytes(changed)
(house / "requirements.txt").write_text(pc.requirements(LOCK["fx"]))
fresh = SCRATCH / "fresh-venv"
ienv = pc.installer_env(root)
subprocess.run(["uv", "venv", "--no-config", "--quiet", "--python", sys.executable, str(fresh)], check=True, env=ienv)
r = subprocess.run(pc.uv_install_cmd(str(fresh / "bin" / "python"), house), capture_output=True, text=True, env=ienv)
check(f"`uv pip install --require-hashes` fails (exit {r.returncode}) on a hash mismatch",
      r.returncode != 0 and "Hash mismatch" in r.stderr, r.stderr[-600:])
check("and installs nothing", import_value(fresh).startswith("exit "), import_value(fresh))


# ----------------------------------------------------------------------------------------------------- Node

def tgz() -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as t:
        for n, d in (("package/package.json", b'{"name":"wib-fixture","version":"1.0.0","main":"index.js"}'),
                     ("package/index.js", b"module.exports = 42;\n")):
            info = tarfile.TarInfo(n)
            info.size, info.mtime = len(d), 0
            t.addfile(info, io.BytesIO(d))
    return buf.getvalue()


TGZ = tgz()
REQUESTS: list[str] = []


class Registry(http.server.BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        REQUESTS.append(self.path)
        port = self.server.server_address[1]
        if self.path == "/wib-fixture/-/wib-fixture-1.0.0.tgz":
            body, kind = TGZ, "application/octet-stream"
        elif self.path == "/wib-fixture":
            stamp = "2020-01-01T00:00:00.000Z"
            body = json.dumps({"name": "wib-fixture", "dist-tags": {"latest": "1.0.0"},
                               "time": {"created": stamp, "modified": stamp, "1.0.0": stamp},
                               "versions": {"1.0.0": {"name": "wib-fixture", "version": "1.0.0", "dist": {
                                   "tarball": f"http://127.0.0.1:{port}/wib-fixture/-/wib-fixture-1.0.0.tgz",
                                   "shasum": hashlib.sha1(TGZ).hexdigest(),
                                   "integrity": "sha512-" + base64.b64encode(hashlib.sha512(TGZ).digest()).decode()}}}}
                              ).encode()
            kind = "application/json"
        else:
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args) -> None:
        pass


server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Registry)
threading.Thread(target=server.serve_forever, daemon=True).start()
port = server.server_address[1]
yenv = {**os.environ, **pc.node_env(root)}
for k in [k for k in yenv if k.startswith("npm_config_")]:
    del yenv[k]


def project(name: str, lockfile: str | None) -> pathlib.Path:
    d = SCRATCH / name
    d.mkdir()
    (d / "package.json").write_text('{"name":"wib-fixture-user","private":true,"dependencies":{"wib-fixture":"1.0.0"}}')
    (d / ".yarnrc.yml").write_text(f'nodeLinker: node-modules\nnpmRegistryServer: "http://127.0.0.1:{port}"\n'
                                   'unsafeHttpWhitelist:\n  - "127.0.0.1"\nenableTelemetry: false\n')
    (d / "yarn.lock").write_text(lockfile or "")
    return d


def yarn(d: pathlib.Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["node", str(YARN), "install", *args], cwd=d, capture_output=True, text=True, env=yenv,
                          timeout=300)


def installed(d: pathlib.Path) -> str:
    f = d / "node_modules" / "wib-fixture" / "index.js"
    return f.read_text() if f.is_file() else ""


try:
    print(f"== Node: cold, yarn {YARN.stem.split('-', 1)[1]} fetches the package and records its checksum ==")
    cold = project("node-cold", None)
    # yarn 4 turns enableImmutableInstalls on whenever CI is set, as on the GitHub runner, and an immutable install
    # refuses to write yarn.lock (YN0028). This is the step that writes it, so it says so instead of taking the
    # default from the environment (#1186).
    r = yarn(cold, "--no-immutable")
    lockfile = (cold / "yarn.lock").read_text()
    check(f"`yarn install --no-immutable` succeeds (exit {r.returncode})", r.returncode == 0, (r.stdout + r.stderr)[-800:])
    check(f"it asked the registry for the package and its tarball ({REQUESTS})",
          sorted(REQUESTS) == ["/wib-fixture", "/wib-fixture/-/wib-fixture-1.0.0.tgz"])
    check("yarn.lock records the package's checksum",
          '"wib-fixture@npm:1.0.0":' in lockfile and "\n  checksum: 10c0/" in lockfile, lockfile)
    cache = root / "packages" / "yarn" / "cache"
    zips = sorted(cache.glob("wib-fixture-npm-1.0.0-*.zip"))
    check(f"the package's zip is in the artifact root's yarn cache ({[z.name for z in zips]})", len(zips) == 1)
    if failures:
        finish()

    print("== Node: warm, a fresh project installs --immutable with no request ==")
    REQUESTS.clear()
    warm = project("node-warm", lockfile)
    r = yarn(warm, "--immutable")
    check(f"`yarn install --immutable` succeeds (exit {r.returncode})", r.returncode == 0, (r.stdout + r.stderr)[-800:])
    check(f"no request to the registry ({REQUESTS})", REQUESTS == [])
    check("the package is installed", installed(warm) == "module.exports = 42;\n", installed(warm))

    print("== Node: a cached zip whose bytes changed fails the install, unfetched ==")
    z = zips[0]
    with zipfile.ZipFile(z) as src:
        items = [(i, src.read(i.filename)) for i in src.infolist()]
    with zipfile.ZipFile(z, "w") as out:
        for i, d in items:
            out.writestr(i, d.replace(b"42", b"43"))
    tampered = z.read_bytes()
    REQUESTS.clear()
    bad = project("node-tampered", lockfile)
    r = yarn(bad, "--immutable")
    out = r.stdout + r.stderr
    check(f"`yarn install --immutable` fails (exit {r.returncode}) with YN0018, the checksum mismatch",
          r.returncode != 0 and "YN0018" in out and "doesn't match the expected checksum" in out, out[-800:])
    check(f"no request to the registry ({REQUESTS})", REQUESTS == [])
    check("the cached zip is left as it was found, not fetched again", z.read_bytes() == tampered)
    check("and nothing is installed", installed(bad) == "", installed(bad))
finally:
    server.shutdown()
finish()
