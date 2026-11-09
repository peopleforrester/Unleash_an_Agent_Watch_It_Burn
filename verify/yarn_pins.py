# ABOUTME: The Backstage app's two Yarn pins Yarn 4 leaves unchecked (#1167): the lock of its platform-conditional packages'
# ABOUTME: cache checksums, which its install plugin holds each fetch to, and the corepack yarn packageManager's hash names.
"""Two parts of the Backstage `corepack yarn install --immutable` in run-e2e.sh were checked against nothing (#1167,
from #1121).

Platform-conditional packages. images/watch-it-burn-backstage/yarn.lock records a checksum for every registry package
except those with a `conditions:` line, the optional native binaries such as @esbuild/linux-x64. Yarn 4.13.0 treats
those as unstable: their cache zip is never hashed, and no checksum is written for them whatever supportedArchitectures
or checksumBehavior say (run 18530). The app's yarn-plugins/conditional-checksums.cjs closes that: after the fetch step
and before the link step it hashes each enabled conditional package's cache zip, in the cache's own
`<cacheKey>/<sha512>` form, against yarn-plugins/conditional-checksums.lock, and fails the install with YN0018 on a
mismatch or a package with no line. YARN_PLUGINS names it to each install (run-e2e.sh, the Dockerfile, the README's
build step).

`write` records that lock, one line per conditional locator in yarn.lock, every platform's included:
  1. each package's version document is read from registry.npmjs.org and its tarball downloaded and checked against
     the document's dist.integrity (sha512); a mismatch fails, naming the package and both values;
  2. a registry on 127.0.0.1 serves those tarballs alone to a scratch project that depends on each package as a
     plain dependency, so the app's own yarn release fetches and zips them as stable packages and writes their
     checksums into the scratch yarn.lock (`yarn install --mode=update-lockfile`, nothing linked, nothing run);
  3. each locator's checksum is read from there, a patch locator (fsevents' builtin compat patch) included, and the
     line keeps the npm integrity it was made from.
The zip a conditional install makes is the same bytes as that stable one, so the plugin's check reads the same value.

corepack. package.json's packageManager is `yarn@<version>+sha512.<hex>`, the SHA-512 of the yarn.js corepack
downloads from repo.yarnpkg.com, which is the committed .yarn/releases/yarn-<version>.cjs byte for byte. corepack checks
a download against it ("Mismatch hashes") but reuses an install folder already in COREPACK_HOME without hashing it
again, and the artifact cache keeps that folder between runs. `corepack-check` hashes it: the folder's yarn.js must
match the pin and its .corepack must name the yarn bins and that hash, or it fails, naming the file and both values.
An absent folder passes, since corepack's own download check covers the first fetch.

Command line:
  yarn_pins.py write [<app dir>]          rewrite <app>/yarn-plugins/conditional-checksums.lock (needs the network)
  yarn_pins.py corepack-check [<app dir>] check COREPACK_HOME's yarn for the app's packageManager pin
Any failure prints one line starting YARN PINS FAILED to stderr and exits 1."""
from __future__ import annotations

import base64
import hashlib
import http.server
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterable, Mapping

VERIFY = pathlib.Path(__file__).resolve().parent
REPO = VERIFY.parent
sys.path.insert(0, str(VERIFY))
import artifact_cache  # noqa: E402

BACKSTAGE = REPO / "images/watch-it-burn-backstage"
PLUGIN_REL = "yarn-plugins/conditional-checksums.cjs"
LOCK_REL = "yarn-plugins/conditional-checksums.lock"
NPM_REGISTRY = "https://registry.npmjs.org"
# The plugin's own line rule (conditional-checksums.cjs, LINE).
LOCK_LINE = re.compile(r"^(\S+) ([0-9a-z]+/[0-9a-f]{128}) (sha512-[A-Za-z0-9+/]+=*)$")
PACKAGE_MANAGER = re.compile(r"yarn@(\d+\.\d+\.\d+)\+sha512\.([0-9a-f]{128})")
FETCH_TIMEOUT = 300


DROPPED = ("dependencies", "optionalDependencies", "peerDependencies", "peerDependenciesMeta", "scripts", "gypfile")


class YarnPinsError(RuntimeError):
    """A pin is missing, malformed or does not match; the message names which and where."""


# ------------------------------------------------------------------------------------------------ yarn.lock

def lock_entries(text: str) -> list[dict[str, str]]:
    """Each package entry of a Yarn 4 lockfile as {resolution, conditions, checksum}, '' where a field is absent."""
    out = []
    for block in re.split(r"\n\n+", text):
        res = re.search(r'^  resolution: "(.*)"$', block, re.M)
        if not res:
            continue
        cond = re.search(r"^  conditions: (.*)$", block, re.M)
        csum = re.search(r"^  checksum: (\S+)$", block, re.M)
        out.append({"resolution": res.group(1), "conditions": cond.group(1) if cond else "",
                    "checksum": csum.group(1) if csum else ""})
    return out


def cache_key(text: str) -> str:
    m = re.search(r"^__metadata:\n(?:  .*\n)*?  cacheKey: (\S+)$", text, re.M)
    if not m:
        raise YarnPinsError("yarn.lock has no __metadata cacheKey")
    return m.group(1)


def conditional(text: str) -> list[str]:
    """The resolution of every entry with a `conditions:` line, in lockfile order."""
    return [e["resolution"] for e in lock_entries(text) if e["conditions"]]


def npm_base(locator: str) -> tuple[str, str]:
    """(name, version) of the registry package a locator is made from: itself for `<name>@npm:<version>`, the patched
    package for a `<name>@patch:<name>@npm%3A<version>#...` locator."""
    if "@patch:" in locator:
        inner = urllib.parse.unquote(locator.split("@patch:", 1)[1].split("#", 1)[0])
        return npm_base(inner)
    name, sep, version = locator.rpartition("@npm:")
    if not sep or not name or not re.fullmatch(r"\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?", version):
        raise YarnPinsError(f"{locator} is not a registry locator (<name>@npm:<version>) or a patch of one")
    return name, version


# --------------------------------------------------------------------------------------------- the lock file

def parse_lock(text: str) -> dict[str, tuple[str, str]]:
    """{locator: (checksum, npm integrity)}, refusing a line the plugin would refuse."""
    out: dict[str, tuple[str, str]] = {}
    for i, raw in enumerate(text.split("\n"), 1):
        if raw == "" or raw.startswith("#"):
            continue
        m = LOCK_LINE.fullmatch(raw)
        if not m:
            raise YarnPinsError(f"{LOCK_REL} line {i} is not '<locator> <cacheKey>/<sha512> sha512-<integrity>': {raw}")
        if m.group(1) in out:
            raise YarnPinsError(f"{LOCK_REL} line {i} records {m.group(1)} a second time")
        out[m.group(1)] = (m.group(2), m.group(3))
    return out


def render_lock(rows: Mapping[str, tuple[str, str]], release: str) -> str:
    head = [
        "# The cache checksum of each platform-conditional package in yarn.lock, which Yarn 4 does not record (#1167).",
        "# yarn-plugins/conditional-checksums.cjs fails an install whose cache zip for one of them differs.",
        f"# Written by `python3 verify/yarn_pins.py write` with {release}: each tarball checked against npm's",
        "# dist.integrity (the third field; a patch's is its base package's), then zipped by that yarn.",
        "# <locator> <cacheKey>/<sha512 of the cache zip> <npm dist.integrity>",
    ]
    return "\n".join(head + [f"{loc} {c} {i}" for loc, (c, i) in sorted(rows.items())]) + "\n"


# ----------------------------------------------------------------------------------------------- the registry

def integrity_of(data: bytes) -> str:
    return "sha512-" + base64.b64encode(hashlib.sha512(data).digest()).decode()


def ident_path(name: str) -> str:
    """The path Yarn asks a registry for a package's document at: /<name>, a scope's slash encoded."""
    return "/" + name.replace("/", "%2f")


class Registry:
    """An npm registry on 127.0.0.1 serving given packages, one version each, from bytes held in memory, and counting
    the requests it gets. Each version document is the one given, with its tarball URL pointed here and what would
    pull in another package dropped: its dependencies, and the scripts and gypfile for which yarn adds node-gyp. A
    scratch project needs the packages' own bytes only, and yarn zips the tarball whatever the document says."""

    def __init__(self, packages: Mapping[tuple[str, str], tuple[Mapping, bytes]]):
        self.requests: list[str] = []
        self.docs: dict[str, dict] = {}
        self.tarballs: dict[str, bytes] = {}
        handler = self._handler()
        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        stamp = "2020-01-01T00:00:00.000Z"
        for (name, version), (doc, tgz) in packages.items():
            tar_path = f"{ident_path(name)}/-/{name.split('/')[-1]}-{version}.tgz"
            self.tarballs[tar_path] = tgz
            v = {k: val for k, val in doc.items() if k not in DROPPED}
            v.update(name=name, version=version, dist={"tarball": self.url + tar_path,
                                                       "integrity": integrity_of(tgz),
                                                       "shasum": hashlib.sha1(tgz).hexdigest()})
            d = self.docs.setdefault(ident_path(name), {"name": name, "dist-tags": {}, "versions": {},
                                                        "time": {"created": stamp, "modified": stamp}})
            d["versions"][version] = v
            d["time"][version] = stamp
            d["dist-tags"]["latest"] = version
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def _handler(self):
        reg = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                reg.requests.append(self.path)
                path = self.path.split("?", 1)[0].replace("%2F", "%2f")
                if path in reg.tarballs:
                    body, kind = reg.tarballs[path], "application/octet-stream"
                elif path in reg.docs:
                    body, kind = json.dumps(reg.docs[path]).encode(), "application/json"
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

        return Handler

    def __enter__(self) -> "Registry":
        self.thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self.server.shutdown()
        self.server.server_close()


def yarnrc(registry_url: str) -> str:
    return (f'nodeLinker: node-modules\nnpmRegistryServer: "{registry_url}"\n'
            'unsafeHttpWhitelist:\n  - "127.0.0.1"\nenableTelemetry: false\nenableScripts: false\n')


def yarn_env(global_folder: pathlib.Path, base: Mapping[str, str] | None = None) -> dict[str, str]:
    """The environment a scratch yarn runs in: its own global cache, checksums thrown, nothing from npm_config_* or
    a YARN_* setting of the caller's, and immutable installs off (yarn turns them on under CI)."""
    env = {k: v for k, v in (os.environ if base is None else base).items()
           if not k.startswith(("npm_config_", "YARN_"))}
    env.update(YARN_ENABLE_GLOBAL_CACHE="true", YARN_GLOBAL_FOLDER=str(global_folder),
               YARN_CHECKSUM_BEHAVIOR="throw", YARN_ENABLE_IMMUTABLE_INSTALLS="false")
    return env


def record(locators: Iterable[str], registry_url: str, release: pathlib.Path, work: pathlib.Path,
           env: Mapping[str, str] | None = None) -> dict[str, str]:
    """{locator: checksum} for each locator, as the given yarn release zips it, from a scratch project in work that
    depends plainly on each locator's registry package. A name pinned at several versions gets one workspace per
    version past the first. A locator the scratch lockfile has no checksum for fails, naming it."""
    locators = list(locators)
    versions: dict[str, list[str]] = {}
    for loc in locators:
        name, version = npm_base(loc)
        if version not in versions.setdefault(name, []):
            versions[name].append(version)
    proj = work / "project"
    proj.mkdir(parents=True)
    layers = max((len(v) for v in versions.values()), default=1)
    workspaces = [f"w{i}" for i in range(1, layers)]
    deps = {name: vs[0] for name, vs in sorted(versions.items())}
    (proj / "package.json").write_text(json.dumps({"name": "wib-conditional-record", "private": True,
                                                   "workspaces": workspaces, "dependencies": deps}, indent=1))
    for i, ws in enumerate(workspaces, 1):
        (proj / ws).mkdir()
        wdeps = {name: vs[i] for name, vs in sorted(versions.items()) if len(vs) > i}
        (proj / ws / "package.json").write_text(json.dumps({"name": f"wib-conditional-record-{ws}", "private": True,
                                                            "dependencies": wdeps}, indent=1))
    (proj / ".yarnrc.yml").write_text(yarnrc(registry_url))
    (proj / "yarn.lock").write_text("")
    r = subprocess.run(["node", str(release), "install", "--mode=update-lockfile"], cwd=proj, capture_output=True,
                       text=True, env=yarn_env(work / "yarn-global", env), timeout=3600)
    if r.returncode != 0:
        raise YarnPinsError(f"the scratch install failed (exit {r.returncode}): {(r.stdout + r.stderr)[-1500:]}")
    got = {e["resolution"]: e["checksum"] for e in lock_entries((proj / "yarn.lock").read_text(encoding="utf-8"))}
    missing = [loc for loc in locators if not got.get(loc)]
    if missing:
        raise YarnPinsError(f"the scratch yarn.lock records no checksum for {', '.join(missing)}")
    return {loc: got[loc] for loc in locators}


def fetch_npm(name: str, version: str, get: Callable[[str], bytes]) -> tuple[dict, bytes]:
    """The version document and the tarball of name@version from registry.npmjs.org, the tarball checked against
    the document's dist.integrity."""
    doc = json.loads(get(f"{NPM_REGISTRY}{ident_path(name)}/{version}"))
    want = doc.get("dist", {}).get("integrity", "")
    if not want.startswith("sha512-"):
        raise YarnPinsError(f"{name}@{version}: the registry document has no sha512 dist.integrity ({want!r})")
    tgz = get(doc["dist"]["tarball"])
    got = integrity_of(tgz)
    if got != want:
        raise YarnPinsError(f"{name}@{version}: the tarball is {got}, but the registry's dist.integrity is {want}")
    return doc, tgz


def url_get(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=FETCH_TIMEOUT) as r:
        return r.read()


def release_of(app: pathlib.Path) -> pathlib.Path:
    m = re.search(r"^yarnPath:\s*(\S+)\s*$", (app / ".yarnrc.yml").read_text(encoding="utf-8"), re.M)
    if not m:
        raise YarnPinsError(f"{app / '.yarnrc.yml'} names no yarnPath")
    return app / m.group(1)


def write(app: pathlib.Path = BACKSTAGE, get: Callable[[str], bytes] = url_get) -> int:
    text = (app / "yarn.lock").read_text(encoding="utf-8")
    key = cache_key(text)
    locators = conditional(text)
    if not locators:
        raise YarnPinsError(f"{app / 'yarn.lock'} has no platform-conditional entry")
    release = release_of(app)
    bases = sorted({npm_base(loc) for loc in locators})
    packages = {}
    for name, version in bases:
        packages[(name, version)] = fetch_npm(name, version, get)
    work = artifact_cache.scratch_dir("wib-yarn-pins-")
    try:
        with Registry(packages) as reg:
            sums = record(locators, reg.url, release, work)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    wrong = [f"{loc} {s}" for loc, s in sums.items() if not s.startswith(f"{key}/")]
    if wrong:
        raise YarnPinsError(f"yarn.lock's cacheKey is {key}, but the scratch install wrote {', '.join(wrong)}")
    rows = {loc: (sums[loc], integrity_of(packages[npm_base(loc)][1])) for loc in locators}
    (app / LOCK_REL).write_text(render_lock(rows, release.name), encoding="utf-8")
    return len(rows)


# --------------------------------------------------------------------------------------------------- corepack

def package_manager(app: pathlib.Path) -> tuple[str, str]:
    """(version, sha512 hex) of the app's packageManager pin, which must carry its hash."""
    pm = json.loads((app / "package.json").read_text(encoding="utf-8")).get("packageManager", "")
    m = PACKAGE_MANAGER.fullmatch(pm)
    if not m:
        raise YarnPinsError(f"{app / 'package.json'} packageManager is {pm!r}, not yarn@<version>+sha512.<hex>")
    return m.group(1), m.group(2)


def corepack_check(app: pathlib.Path, corepack_home: pathlib.Path) -> str:
    """Checks COREPACK_HOME's install folder for the app's pinned yarn, when there is one, and says what it found."""
    version, want = package_manager(app)
    folder = corepack_home / "v1" / "yarn" / version
    if not folder.exists():
        return f"no yarn {version} in {corepack_home} yet; corepack checks its download against the pin"
    meta_file, js = folder / ".corepack", folder / "yarn.js"
    try:
        meta = json.loads(meta_file.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise YarnPinsError(f"{meta_file} cannot be read as corepack's record ({e})") from None
    if meta.get("bin") != ["yarn", "yarnpkg"] or meta.get("hash") != f"sha512.{want}":
        raise YarnPinsError(f"{meta_file} records bin {meta.get('bin')!r} and hash {meta.get('hash')!r}, not "
                            f"['yarn', 'yarnpkg'] and sha512.{want}")
    if not js.is_file():
        raise YarnPinsError(f"{js} is missing from corepack's yarn {version} folder")
    got = hashlib.sha512(js.read_bytes()).hexdigest()
    if got != want:
        raise YarnPinsError(f"{js} is sha512 {got}, but package.json's packageManager pins {want}")
    return f"{js} matches the packageManager pin"


# ----------------------------------------------------------------------------------------------- command line

USAGE = "usage: yarn_pins.py write [<app dir>] | corepack-check [<app dir>]"


def main(argv: list[str]) -> int:
    try:
        if argv[:1] in (["write"], ["corepack-check"]) and len(argv) <= 2:
            app = pathlib.Path(argv[1]).resolve() if len(argv) == 2 else BACKSTAGE
            if argv[0] == "write":
                print(f"{write(app)} platform-conditional packages recorded in {app / LOCK_REL}")
                return 0
            home = os.environ.get("COREPACK_HOME", "")
            if not home:
                raise YarnPinsError("COREPACK_HOME is not set; run-e2e.sh exports it before this check")
            print(corepack_check(app, pathlib.Path(home)))
            return 0
        raise YarnPinsError(USAGE)
    except (YarnPinsError, artifact_cache.ArtifactCacheError, OSError, urllib.error.URLError) as e:
        print(f"YARN PINS FAILED: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
