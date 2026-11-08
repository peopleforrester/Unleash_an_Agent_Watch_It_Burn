# ABOUTME: Serves every Terraform provider a committed lock pins from the host artifact cache (#1119): a filesystem mirror
# ABOUTME: filled through artifact_cache.get() by each zip's zh: SHA-256, a CLI config that installs only from it, a plugin cache.
"""Where the terraform inits under verify/ and .github/workflows/ take their providers from.

#1114 moved the plugin cache out of the checkout; #1119 takes the downloads away from terraform altogether. Everything
lives in the host artifact cache (artifact_cache.resolve_root: HECATON_TOOLS_CACHE, WIB_ARTIFACT_CACHE, else
${XDG_CACHE_HOME:-$HOME/.cache}/wib-artifacts), which is outside every git worktree or refused:

  <root>/sha256/<hex>                                   each provider zip, once per host, by its SHA-256
  <root>/terraform-providers/index/<host>/<ns>/<type>/<zip>.json   which SHA-256 and URL that zip has
  <root>/terraform-providers/mirror/<host>/<ns>/<type>/<zip>       a symlink to <root>/sha256/<hex>
  <root>/terraform-providers/terraformrc                the CLI config (TF_CLI_CONFIG_FILE)
  <root>/terraform-plugin-cache                         Terraform's unpacked copies (TF_PLUGIN_CACHE_DIR)

fill() reads each `.terraform.lock.hcl` and, for every provider it pins, finds this platform's zip: from the index, or
on a first sight from the registry's download API, whose answer is used only when its SHA-256 is one of the zh: hashes
the lock records. The lock is the root of trust, as it is for terraform: a package the lock does not vouch for is
never fetched. The zip then comes through artifact_cache.get(), which re-hashes a hit, fetches a miss once under a
per-sum lock and logs it, and fails on any mismatch without downloading again.

The CLI config installs registry.terraform.io providers from the mirror only: no `direct` source covers them, so a
provider the mirror lacks fails init by name and is never downloaded. Other hosts are left to `direct`; the one in use
is registry.opentofu.org, where OpenTofu (which reads the same TF_CLI_CONFIG_FILE) resolves hashicorp/aws in
plan-policy.yml. terraform init still checks each zip from the mirror against the lock (zh: for the zip's bytes, h1:
for its contents), and a cached provider in the plugin cache only when its h1: is one the lock records:
test_terraform_mirror_lock.py holds that a mirror zip the lock does not match fails init.

terraform_env(env) is what a test gives its terraform: the mirror filled and the config written, or, when the caller
already set TF_CLI_CONFIG_FILE, a check that it is a config this module wrote, for a mirror outside every worktree.
TF_PLUGIN_CACHE_MAY_BREAK_DEPENDENCY_LOCK_FILE, the one switch that loosens the lock's check on the plugin cache, is
dropped from what it returns; iam_plan_render.py sets it again for its lock-less renders and says why.

Command line:
  tf_plugin_cache.py           create the plugin cache and print its path (run-e2e-tools.sh locks it, #1005)
  tf_plugin_cache.py prepare   fill the mirror for every committed lock and print TF_CLI_CONFIG_FILE= and
                               TF_PLUGIN_CACHE_DIR= lines, for "$GITHUB_ENV" or `env`
Any failure prints one line starting TERRAFORM PROVIDER CACHE UNUSABLE to stderr and exits 1.
"""
from __future__ import annotations

import dataclasses
import json
import os
import pathlib
import platform as _platform
import re
import sys
import tempfile
import urllib.request
from collections.abc import Callable, Iterable, Mapping

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "verify"))
import artifact_cache  # noqa: E402

PLUGIN_SUBDIR = "terraform-plugin-cache"
PROVIDERS_SUBDIR = "terraform-providers"
MIRRORED_HOST = "registry.terraform.io"
APP = "unleash-watch-it-burn"
MARKER = "# Written by verify/tf_plugin_cache.py (#1119)."
TIMEOUT = 60

# A fetcher of the registry's download answer for one package: url -> parsed JSON.
MetaFetcher = Callable[[str], dict]


class CacheError(Exception):
    pass


@dataclasses.dataclass(frozen=True)
class Locked:
    """One provider block of a lock file."""
    address: str
    version: str
    zh: frozenset[str]
    lock: str

    @property
    def parts(self) -> tuple[str, str, str]:
        host, ns, typ = self.address.split("/")
        return host, ns, typ

    def zip_name(self, plat: str) -> str:
        return f"terraform-provider-{self.parts[2]}_{self.version}_{plat}.zip"


BLOCK = re.compile(r'^provider "([^"]+)" \{\n(.*?)^\}', re.M | re.S)
ADDRESS = re.compile(r"[a-z0-9.-]+/[a-z0-9_-]+/[a-z0-9_-]+")


def parse_lock(text: str, name: str = "lock") -> list[Locked]:
    """Every provider block in a `.terraform.lock.hcl`, with its version and its zh: hashes."""
    out = []
    for m in BLOCK.finditer(text):
        address, body = m.group(1), m.group(2)
        if not ADDRESS.fullmatch(address):
            raise CacheError(f"{name}: provider address {address!r} is not <host>/<namespace>/<type>")
        v = re.search(r'^\s*version\s*=\s*"([^"]+)"', body, re.M)
        if not v:
            raise CacheError(f"{name}: provider {address} has no version")
        zh = frozenset(re.findall(r'"zh:([0-9a-f]{64})"', body))
        out.append(Locked(address, v.group(1), zh, name))
    if not out:
        raise CacheError(f"{name}: no provider block found")
    return out


def committed_locks(repo: pathlib.Path = REPO) -> list[pathlib.Path]:
    """Every `.terraform.lock.hcl` under infra/, none from a .terraform/ directory an init left behind."""
    return sorted(p for p in (repo / "infra").glob("**/.terraform.lock.hcl") if ".terraform" not in p.parent.parts)


def read_locks(locks: Iterable[pathlib.Path | Locked]) -> list[Locked]:
    out: list[Locked] = []
    for item in locks:
        if isinstance(item, Locked):
            out.append(item)
            continue
        p = pathlib.Path(item)
        try:
            name = str(p.resolve().relative_to(REPO))
        except ValueError:
            name = str(p)
        out.extend(parse_lock(p.read_text(encoding="utf-8"), name))
    return out


def this_platform() -> str:
    """Terraform's name for this host's platform, as its provider zips are named."""
    os_name = {"Linux": "linux", "Darwin": "darwin"}.get(_platform.system())
    arch = {"x86_64": "amd64", "amd64": "amd64", "aarch64": "arm64", "arm64": "arm64"}.get(_platform.machine())
    if not os_name or not arch:
        raise CacheError(f"no Terraform platform name for {_platform.system()} {_platform.machine()}")
    return f"{os_name}_{arch}"


def user_cache_root(env: Mapping[str, str]) -> pathlib.Path:
    """$XDG_CACHE_HOME, else $HOME/.cache."""
    if env.get("XDG_CACHE_HOME"):
        return pathlib.Path(env["XDG_CACHE_HOME"])
    if env.get("HOME"):
        return pathlib.Path(env["HOME"]) / ".cache"
    raise CacheError("neither XDG_CACHE_HOME nor HOME is set")


def scratch(prefix: str) -> tempfile.TemporaryDirectory:
    """A temp directory outside the working tree, for a test that needs a cache of its own. Not TMPDIR: a hecaton run's
    TMPDIR is <worktree>/tmp/hecaton, inside the checkout, where artifact_cache refuses a root. It sits under the user's
    cache directory and is removed when the test is done with it."""
    root = user_cache_root(os.environ) / APP
    root.mkdir(parents=True, exist_ok=True)
    return tempfile.TemporaryDirectory(prefix=prefix, dir=root)


def root_of(env: Mapping[str, str]) -> pathlib.Path:
    try:
        return artifact_cache.resolve_root(env)
    except artifact_cache.ArtifactCacheError as e:
        raise CacheError(str(e)) from e


def outside_worktrees(path: pathlib.Path, what: str) -> pathlib.Path:
    if not path.is_absolute():
        raise CacheError(f"the {what} {str(path)!r} is a relative path; it must be absolute")
    path = path.resolve()
    tree = artifact_cache.worktree_of(path)
    if tree is not None:
        raise CacheError(f"the {what} {path} is inside the git worktree {tree}; it must sit in the host artifact "
                         "cache, outside every worktree (#1119)")
    return path


def plugin_cache(root: pathlib.Path) -> pathlib.Path:
    return root / PLUGIN_SUBDIR


def mirror_dir(root: pathlib.Path) -> pathlib.Path:
    return root / PROVIDERS_SUBDIR / "mirror"


def config_path(root: pathlib.Path) -> pathlib.Path:
    return root / PROVIDERS_SUBDIR / "terraformrc"


def writable_dir(path: pathlib.Path, what: str) -> pathlib.Path:
    path = outside_worktrees(path, what)
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise CacheError(f"the {what} {path} cannot be created: {e}") from e
    if not os.access(path, os.W_OK | os.X_OK):
        raise CacheError(f"the {what} {path} is not writable; terraform init installs into it")
    return path


def ensure(env: Mapping[str, str]) -> pathlib.Path:
    """The plugin cache in env's artifact root, created and checked writable."""
    return writable_dir(plugin_cache(root_of(env)), "Terraform plugin cache")


def registry_url(p: Locked, plat: str) -> str:
    host, ns, typ = p.parts
    if host != MIRRORED_HOST:
        raise CacheError(f"{p.lock}: {p.address} is on {host}; only {MIRRORED_HOST} providers are mirrored")
    os_name, arch = plat.split("_", 1)
    return f"https://{host}/v1/providers/{ns}/{typ}/{p.version}/download/{os_name}/{arch}"


def registry_meta(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "wib-tf-plugin-cache"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return json.load(r)
    except Exception as e:
        raise CacheError(f"the registry lookup {url} failed: {e}") from e


def _write_atomic(path: pathlib.Path, data: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".part", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(data)
        os.chmod(tmp, 0o644)
        os.replace(tmp, path)
    finally:
        pathlib.Path(tmp).unlink(missing_ok=True)


def _link(link: pathlib.Path, target: pathlib.Path) -> None:
    """link -> target, made with one rename so a reader never sees it missing or half-made."""
    rel = os.path.relpath(target, link.parent)
    if link.is_symlink() and os.readlink(link) == rel:
        return
    link.parent.mkdir(parents=True, exist_ok=True)
    tmp = link.parent / f".{link.name}.{os.getpid()}.link"
    tmp.unlink(missing_ok=True)
    os.symlink(rel, tmp)
    os.replace(tmp, link)


@dataclasses.dataclass(frozen=True)
class Filled:
    provider: Locked
    sha256: str
    zip: pathlib.Path
    looked_up: bool


def fill_one(p: Locked, root: pathlib.Path, plat: str, *, fetch_meta: MetaFetcher = registry_meta,
             fetch: artifact_cache.Fetcher = artifact_cache.url_fetch,
             env: Mapping[str, str] | None = None) -> Filled:
    """This platform's zip of p in the mirror, verified by the artifact cache against a zh: hash p's lock records."""
    name = p.zip_name(plat)
    host, ns, typ = p.parts
    index = root / PROVIDERS_SUBDIR / "index" / host / ns / typ / f"{name}.json"
    looked_up = False
    if index.is_file():
        try:
            rec = json.loads(index.read_text(encoding="utf-8"))
            sha, url = rec["sha256"], rec["url"]
        except (ValueError, KeyError, TypeError) as e:
            raise CacheError(f"the index entry {index} is not a JSON object with sha256 and url: {e}") from e
        if sha not in p.zh:
            raise CacheError(f"the index entry {index} names SHA-256 {sha} for {p.address} {p.version} {plat}, which "
                             f"is not one of the zh: hashes {p.lock} records; nothing is served from it")
    else:
        if not p.zh:
            raise CacheError(f"{p.lock} records no zh: hashes for {p.address} {p.version}, so no zip can be checked "
                             "against it; regenerate it with `terraform providers lock -platform=linux_amd64 ...`")
        meta = fetch_meta(registry_url(p, plat))
        sha, url, got_name = meta.get("shasum"), meta.get("download_url"), meta.get("filename")
        if got_name != name or not isinstance(url, str) or not url.startswith("https://"):
            raise CacheError(f"the registry's answer for {p.address} {p.version} {plat} names {got_name!r} at "
                             f"{url!r}; want {name} over https")
        if sha not in p.zh:
            raise CacheError(f"the registry's {plat} package for {p.address} {p.version} has SHA-256 {sha}, which is "
                             f"not one of the {len(p.zh)} zh: hashes {p.lock} records; the lock does not vouch for it, "
                             "so it is not fetched")
        _write_atomic(index, json.dumps({"sha256": sha, "url": url}, indent=1) + "\n")
        looked_up = True
    try:
        path = artifact_cache.get(sha, url, root=root, fetch=fetch, env=env)
    except artifact_cache.ArtifactCacheError as e:
        raise CacheError(f"{p.address} {p.version} {plat} ({p.lock}): {e}") from e
    _link(mirror_dir(root) / host / ns / typ / name, path)
    return Filled(p, sha, path, looked_up)


def fill(locks: Iterable[pathlib.Path | Locked], root: pathlib.Path, *, plat: str | None = None,
         fetch_meta: MetaFetcher = registry_meta, fetch: artifact_cache.Fetcher = artifact_cache.url_fetch,
         env: Mapping[str, str] | None = None) -> list[Filled]:
    """Every provider the locks pin, in the mirror under root. The same version locked twice is filled once."""
    plat = plat or this_platform()
    seen: dict[tuple[str, str], Locked] = {}
    for p in read_locks(locks):
        key = (p.address, p.version)
        if key in seen:
            # Two locks of one version may record different platforms; a zip either vouches for passes both.
            p = Locked(p.address, p.version, seen[key].zh | p.zh, f"{seen[key].lock} and {p.lock}")
        seen[key] = p
    return [fill_one(p, root, plat, fetch_meta=fetch_meta, fetch=fetch, env=env) for p in seen.values()]


def render_config(mirror: pathlib.Path) -> str:
    q = json.dumps(str(mirror))
    pattern = json.dumps(f"{MIRRORED_HOST}/*/*")
    return (f"{MARKER}\n"
            "# Every registry.terraform.io provider comes from the mirror below, which holds only zips the host artifact\n"
            "# cache checked against a committed lock's zh: hash; none is ever downloaded. Other hosts install directly.\n"
            f"# mirror: {mirror}\n"
            "provider_installation {\n"
            "  filesystem_mirror {\n"
            f"    path    = {q}\n"
            f"    include = [{pattern}]\n"
            "  }\n"
            "  direct {\n"
            f"    exclude = [{pattern}]\n"
            "  }\n"
            "}\n")


def write_config(root: pathlib.Path) -> pathlib.Path:
    path = config_path(root)
    text = render_config(mirror_dir(root))
    if not path.is_file() or path.read_text(encoding="utf-8") != text:
        _write_atomic(path, text)
    return path


def check_prepared(env: Mapping[str, str]) -> None:
    """The caller's TF_CLI_CONFIG_FILE is one this module wrote, for a mirror outside every worktree, and its
    TF_PLUGIN_CACHE_DIR is usable and outside every worktree too."""
    cfg = outside_worktrees(pathlib.Path(env["TF_CLI_CONFIG_FILE"]), "TF_CLI_CONFIG_FILE")
    try:
        text = cfg.read_text(encoding="utf-8")
    except OSError as e:
        raise CacheError(f"TF_CLI_CONFIG_FILE names {cfg}, which cannot be read: {e}") from e
    m = re.search(r"^# mirror: (.+)$", text, re.M)
    if not text.startswith(MARKER) or not m or text != render_config(pathlib.Path(m.group(1))):
        raise CacheError(f"TF_CLI_CONFIG_FILE names {cfg}, which is not a config verify/tf_plugin_cache.py wrote; "
                         "unset it, or set it from `python3 verify/tf_plugin_cache.py prepare`")
    outside_worktrees(pathlib.Path(m.group(1)), "provider mirror")
    if not env.get("TF_PLUGIN_CACHE_DIR"):
        raise CacheError(f"TF_CLI_CONFIG_FILE is set ({cfg}) but TF_PLUGIN_CACHE_DIR is not; `prepare` prints both")
    writable_dir(pathlib.Path(env["TF_PLUGIN_CACHE_DIR"]), "TF_PLUGIN_CACHE_DIR")


def terraform_env(env: Mapping[str, str], locks: Iterable[pathlib.Path | Locked] | None = None, *,
                  root: pathlib.Path | None = None, fetch_meta: MetaFetcher = registry_meta,
                  fetch: artifact_cache.Fetcher = artifact_cache.url_fetch, plat: str | None = None) -> dict[str, str]:
    """env for a terraform that reads providers only from the host artifact cache. With no TF_CLI_CONFIG_FILE set, the
    mirror is filled for locks (every committed lock when None) and the config written; with one set, it is checked."""
    out = dict(env)
    out.pop("TF_PLUGIN_CACHE_MAY_BREAK_DEPENDENCY_LOCK_FILE", None)
    if env.get("TF_CLI_CONFIG_FILE"):
        check_prepared(env)
        return out
    root = outside_worktrees(root, "artifact cache root") if root is not None else root_of(env)
    fill(committed_locks() if locks is None else locks, root, plat=plat, fetch_meta=fetch_meta, fetch=fetch, env=env)
    out["TF_CLI_CONFIG_FILE"] = str(write_config(root))
    out["TF_PLUGIN_CACHE_DIR"] = str(writable_dir(plugin_cache(root), "Terraform plugin cache"))
    return out


def main(argv: list[str]) -> int:
    try:
        if not argv:
            print(ensure(os.environ))
            return 0
        if argv == ["prepare"]:
            env = {k: v for k, v in os.environ.items() if k != "TF_CLI_CONFIG_FILE"}
            root = root_of(env)
            for f in fill(committed_locks(), root, env=env):
                state = "looked up and verified" if f.looked_up else "verified"
                print(f"{f.provider.address} {f.provider.version}: {f.zip} ({state})", file=sys.stderr)
            print(f"TF_CLI_CONFIG_FILE={write_config(root)}")
            print(f"TF_PLUGIN_CACHE_DIR={writable_dir(plugin_cache(root), 'Terraform plugin cache')}")
            return 0
        raise CacheError("usage: tf_plugin_cache.py [prepare]")
    except CacheError as e:
        print(f"TERRAFORM PROVIDER CACHE UNUSABLE: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
