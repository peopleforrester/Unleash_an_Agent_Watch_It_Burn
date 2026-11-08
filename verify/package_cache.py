# ABOUTME: Pinned Python and Node packages from the host artifact cache (#1121): each wheel python.lock pins comes in by
# ABOUTME: its SHA-256 and installs offline with --require-hashes; yarn's cache sits in the same root and throws on a bad zip.
"""Runs and CI jobs used to install their pinned Python packages on every job, often into a fresh environment: `uv run
--with mcp==1.29.1`, `uv pip install PyYAML==6.0.3`, `pip install PyYAML==6.0.3`, each a resolution against PyPI and
a download unless the installer's own cache happened to hold it, and none of them checked against a hash (#1121, from
#1115).

Python. verify/python.lock pins every package of each environment in ENVS, its dependencies included: the one wheel
this repo installs, by file name, SHA-256 and URL, for the environment's Python on linux x86_64. `write` makes it with
`uv pip compile --format pylock.toml` and picks, of the wheels uv lists for that platform, the one the interpreter
prefers (best_wheel()). Nothing else reads an index:

  - wheelhouse(env) asks the host artifact cache (artifact_cache.py, #1117) for each wheel by its SHA-256. A hit is
    hashed again and served with no network access; a miss is fetched once from the locked URL and checked before it
    is kept. A cached wheel that no longer matches its pin fails here, naming the file and both sums, and is not
    downloaded again. The wheelhouse is a directory of links named for the wheels, beside a requirements.txt that pins
    each one as `name==version --hash=sha256:<sum>`.
  - The install reads only that directory: `uv pip install --offline --no-index --no-build --require-hashes`, or
    pip's `--no-index --only-binary=:all: --require-hashes`. Both hash every wheel again before they unpack it, so a
    file that changed between the fill and the install fails too, and a package the lock leaves out fails the
    resolution instead of being fetched.
  - environment(env) is a virtual environment in the artifact root, one per environment, lock and interpreter, built
    the first time and reused after. Every call fills the wheelhouse first, so every call re-checks the cached wheels.
    `run <env> -- <program> ...` is the command line callers prefix: it does the same, then runs the program from the
    environment's bin.
  - uv's and pip's own caches (UV_CACHE_DIR, PIP_CACHE_DIR) are in the artifact root too, outside every worktree.

Node. The one Node install under verify/ and .github/workflows/ is the Backstage app's `corepack yarn install
--immutable` in run-e2e.sh. Its yarn.lock records a checksum for every package, and node_env() points yarn's global
cache (YARN_GLOBAL_FOLDER, with YARN_ENABLE_GLOBAL_CACHE) and corepack's (COREPACK_HOME) into the artifact root, with
YARN_CHECKSUM_BEHAVIOR=throw, so a cached zip that does not match the lock fails the install with YN0018 and is not
fetched again.

Command line:
  package_cache.py run <env> [--root <dir>] -- <program> [args...]
                                                       install the environment if needed, then exec bin/<program>
  package_cache.py python <env>                        print the environment's python
  package_cache.py install <env> --python <interpreter> [--pip]
                                                       install the environment's lock into that interpreter, with uv
                                                       (or with pip, for a job that has no uv)
  package_cache.py wheelhouse <env>                    print the filled wheelhouse directory
  package_cache.py node-env                            print the yarn and corepack cache variables, KEY=VALUE
  package_cache.py write [env...]                      rewrite python.lock from ENVS (needs uv and the network)
Any failure prints one line starting PACKAGE CACHE FAILED to stderr and exits 1."""
from __future__ import annotations

import dataclasses
import fcntl
import hashlib
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.parse
from collections.abc import Mapping, Sequence

VERIFY = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(VERIFY))
import artifact_cache  # noqa: E402

LOCK = VERIFY / "python.lock"
# The platform every environment is locked for: the hosts and runners are linux x86_64 with glibc 2.28 or newer.
PLATFORM = "x86_64-manylinux_2_28"
GLIBC_MAX = 28
MARKER = ".wib-package-cache"


@dataclasses.dataclass(frozen=True)
class Env:
    """One environment: the Python it runs on, what it asks for, and any index beside PyPI."""
    python: str
    requires: tuple[str, ...]
    indexes: tuple[str, ...] = ()
    why: str = ""


# Each pin is the one its caller ran before #1121. A caller holds its own pin against the lock (test_package_cache.py).
ENVS: dict[str, Env] = {
    "pyyaml": Env("3.13", ("PyYAML==6.0.3",),
                  why="the suites' one package beyond the standard library, for the CI jobs' Python 3.13"),
    "playwright": Env("3.13", ("playwright==1.64.1",), why="verify/playwright_browsers.py and the browser tests"),
    "segno": Env("3.13", ("segno==1.6.6",), why="scripts/audience-qr.py (#451)"),
    "mcp": Env("3.12", ("mcp==1.29.1", "PyYAML==6.0.2"),
               why="the workshop-mcp image's pins on its Python (images/workshop-mcp/Dockerfile)"),
    "llm-guard": Env("3.12", ("torch==2.14.0+cpu", "llm-guard[onnxruntime]==0.3.16"),
                     ("https://download.pytorch.org/whl/cpu",),
                     why="the llm-guard image's scanner, with the CPU torch build (images/llm-guard)"),
}


class PackageCacheError(RuntimeError):
    """An environment could not be served or installed; the message names it and says why."""


@dataclasses.dataclass(frozen=True)
class Wheel:
    env: str
    python: str
    name: str
    version: str
    sha256: str
    url: str

    @property
    def filename(self) -> str:
        return urllib.parse.unquote(self.url.rsplit("/", 1)[-1])


# ---------------------------------------------------------------------------------------------------------- the lock

def parse_lock(text: str, source: str = "python.lock") -> dict[str, list[Wheel]]:
    """{env: [wheels]} from the lock's text. A malformed line, a sum that is not a SHA-256, a URL that is not an https
    wheel, a package twice in one environment or an environment with two Pythons fails, naming the line."""
    envs: dict[str, list[Wheel]] = {}
    for n, raw in enumerate(text.splitlines(), 1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        f = line.split()
        where = f"{source} line {n}"
        if len(f) != 6:
            raise PackageCacheError(f"{where}: want `env python package version sha256 url`, got {raw!r}")
        w = Wheel(*f)
        if not artifact_cache.SHA256.fullmatch(w.sha256):
            raise PackageCacheError(f"{where}: {w.sha256!r} is not a SHA-256")
        if not (w.url.startswith("https://") and w.filename.endswith(".whl")):
            raise PackageCacheError(f"{where}: {w.url!r} is not an https URL of a wheel")
        have = envs.setdefault(w.env, [])
        if have and have[0].python != w.python:
            raise PackageCacheError(f"{where}: {w.env} is locked for Python {have[0].python} above, not {w.python}")
        if any(x.name == w.name for x in have):
            raise PackageCacheError(f"{where}: {w.name} is pinned twice in {w.env}")
        have.append(w)
    return envs


def read_lock(path: pathlib.Path | None = None) -> dict[str, list[Wheel]]:
    path = LOCK if path is None else path
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        raise PackageCacheError(f"cannot read {path}: {e}") from e
    return parse_lock(text, path.name)


def env_wheels(env: str, lock: Mapping[str, list[Wheel]] | None = None) -> list[Wheel]:
    lock = read_lock() if lock is None else lock
    if env not in lock:
        raise PackageCacheError(f"python.lock has no environment {env!r}; it locks {', '.join(sorted(lock))}. "
                                "Add it to ENVS in verify/package_cache.py and run `package_cache.py write`")
    return lock[env]


def normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def pinned(env: str, package: str, lock: Mapping[str, list[Wheel]] | None = None) -> str:
    """The version python.lock pins for package in env; fails naming both when it pins none."""
    for w in env_wheels(env, lock):
        if normalize(w.name) == normalize(package):
            return w.version
    raise PackageCacheError(f"python.lock pins no {package} in {env}")


def digest(wheels: Sequence[Wheel], *extra: str) -> str:
    """12 hex digits naming one environment's lock (and whatever else is given): its directories carry it, so a
    changed lock gets a new wheelhouse and environment, and two worktrees on different locks never share one."""
    h = hashlib.sha256()
    for part in [*extra, *sorted(f"{w.env} {w.python} {w.name} {w.version} {w.sha256}" for w in wheels)]:
        h.update(part.encode() + b"\n")
    return h.hexdigest()[:12]


def requirements(wheels: Sequence[Wheel]) -> str:
    return "".join(f"{w.name}=={w.version} --hash=sha256:{w.sha256}\n" for w in sorted(wheels, key=lambda w: w.name))


# ------------------------------------------------------------------------------------------------ wheel selection

def _platforms() -> list[str]:
    """linux x86_64 platform tags newest glibc first, each legacy alias right after its glibc, as pip orders them."""
    alias = {17: "manylinux2014_x86_64", 12: "manylinux2010_x86_64", 5: "manylinux1_x86_64"}
    out = []
    for minor in range(GLIBC_MAX, 4, -1):
        out.append(f"manylinux_2_{minor}_x86_64")
        if minor in alias:
            out.append(alias[minor])
    return out


def supported_tags(python: str) -> list[tuple[str, str, str]]:
    """The (python, abi, platform) tags CPython <python> accepts on manylinux x86_64, most preferred first: the order
    of packaging.tags' cpython_tags() then compatible_tags(), with linux_x86_64 left out."""
    major, minor = (int(x) for x in python.split(".")[:2])
    cp = f"cp{major}{minor}"
    plats = _platforms()
    tags = [(cp, cp, p) for p in plats] + [(cp, "abi3", p) for p in plats] + [(cp, "none", p) for p in plats]
    for m in range(minor - 1, 1, -1):
        tags += [(f"cp{major}{m}", "abi3", p) for p in plats]
    pys = [f"py{major}{minor}", f"py{major}"] + [f"py{major}{m}" for m in range(minor - 1, -1, -1)]
    tags += [(v, "none", p) for v in pys for p in plats]
    tags += [(cp, "none", "any")] + [(v, "none", "any") for v in pys]
    return tags


def wheel_tags(filename: str) -> set[tuple[str, str, str]]:
    """The tags a wheel file name declares, its compressed sets expanded."""
    parts = filename[:-len(".whl")].split("-")
    if len(parts) not in (5, 6):
        raise PackageCacheError(f"{filename!r} is not a wheel file name")
    py, abi, plat = parts[-3:]
    return {(a, b, c) for a in py.split(".") for b in abi.split(".") for c in plat.split(".")}


def best_wheel(filenames: Sequence[str], python: str) -> str | None:
    """Of the wheel file names, the one CPython <python> prefers on manylinux x86_64; None when it accepts none."""
    rank = {t: i for i, t in enumerate(supported_tags(python))}
    scored = []
    for f in filenames:
        hits = [rank[t] for t in wheel_tags(f) if t in rank]
        if hits:
            scored.append((min(hits), f))
    return min(scored)[1] if scored else None


# ------------------------------------------------------------------------------------------------------- the root

def root_dir(root: pathlib.Path | None = None, env: Mapping[str, str] | None = None) -> pathlib.Path:
    """<artifact root>/packages, where every directory this module keeps sits."""
    return (artifact_cache.resolve_root(env) if root is None else root) / "packages"


def installer_env(root: pathlib.Path | None = None, base: Mapping[str, str] | None = None) -> dict[str, str]:
    """The process environment, with base laid over it, and uv's and pip's caches in the artifact root (resolved from
    that environment when root is None)."""
    out = {**os.environ, **(base or {})}
    r = root_dir(root, out)
    out["UV_CACHE_DIR"] = str(r / "uv-cache")
    out["PIP_CACHE_DIR"] = str(r / "pip-cache")
    return out


def node_env(root: pathlib.Path | None = None, env: Mapping[str, str] | None = None) -> dict[str, str]:
    """The variables a yarn 4 install takes its caches from: yarn's global cache and corepack's home in the artifact
    root, and a checksum mismatch thrown, never updated or reset."""
    r = root_dir(root, env)
    return {
        "YARN_ENABLE_GLOBAL_CACHE": "true",
        "YARN_GLOBAL_FOLDER": str(r / "yarn"),
        "YARN_CHECKSUM_BEHAVIOR": "throw",
        "COREPACK_HOME": str(r / "corepack"),
    }


def _link(target: pathlib.Path, link: pathlib.Path) -> None:
    """link -> target, replaced in one rename, so a reader never sees it missing or half made."""
    if link.is_symlink() and os.readlink(link) == str(target):
        return
    tmp = link.with_name(f".{link.name}.{os.getpid()}.tmp")
    tmp.unlink(missing_ok=True)
    os.symlink(target, tmp)
    os.replace(tmp, link)


def _write(path: pathlib.Path, text: str) -> None:
    if path.is_file() and path.read_text(encoding="utf-8") == text:
        return
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    os.chmod(tmp, 0o644)
    os.replace(tmp, path)


def wheelhouse(env: str, *, root: pathlib.Path | None = None, lock: Mapping[str, list[Wheel]] | None = None,
               fetch: artifact_cache.Fetcher = artifact_cache.url_fetch,
               cache_env: Mapping[str, str] | None = None) -> pathlib.Path:
    """The filled wheelhouse of env: each locked wheel served by the artifact cache by its sum, linked under its file
    name, beside requirements.txt. A cached wheel that does not match its pin fails, and is not fetched again."""
    wheels = env_wheels(env, lock)
    aroot = artifact_cache.resolve_root(cache_env) if root is None else root
    house = root_dir(aroot) / "wheels" / f"{env}-{digest(wheels)}"
    try:
        house.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise PackageCacheError(f"{env}: cannot make the wheelhouse {house}: {e}") from e
    for w in wheels:
        try:
            path = artifact_cache.get_retrying(w.sha256, w.url, root=aroot, fetch=fetch, env=cache_env)
        except artifact_cache.ArtifactCacheError as e:
            raise PackageCacheError(f"{env}: {w.name} {w.version} ({w.filename}): {e}") from e
        _link(path, house / w.filename)
    _write(house / "requirements.txt", requirements(wheels))
    return house


# ---------------------------------------------------------------------------------------------------- the install

def _run(cmd: Sequence[str], what: str, env: Mapping[str, str]) -> None:
    try:
        r = subprocess.run(list(cmd), capture_output=True, text=True, env=dict(env))
    except OSError as e:
        raise PackageCacheError(f"{what}: cannot run {cmd[0]}: {e}") from e
    if r.returncode != 0:
        out = (r.stdout + r.stderr).strip()
        raise PackageCacheError(f"{what} exited {r.returncode}: {' '.join(cmd)}\n{out[-3000:]}")


def uv_install_cmd(python: str, house: pathlib.Path) -> list[str]:
    return ["uv", "pip", "install", "--no-config", "--python", python, "--offline", "--no-index", "--no-build",
            "--find-links", str(house), "--require-hashes", "-r", str(house / "requirements.txt")]


def pip_install_cmd(python: str, house: pathlib.Path) -> list[str]:
    return [python, "-m", "pip", "install", "--no-input", "--disable-pip-version-check", "--no-index",
            "--only-binary=:all:", "--find-links", str(house), "--require-hashes",
            "-r", str(house / "requirements.txt")]


def python_version(python: str) -> str:
    try:
        r = subprocess.run([python, "-c", "import sys; print('%d.%d' % sys.version_info[:2])"],
                           capture_output=True, text=True)
    except OSError as e:
        raise PackageCacheError(f"cannot run the interpreter {python}: {e}") from e
    if r.returncode != 0:
        raise PackageCacheError(f"the interpreter {python} exited {r.returncode}: {r.stderr.strip()}")
    return r.stdout.strip()


def install(env: str, python: str, *, pip: bool = False, root: pathlib.Path | None = None,
            lock: Mapping[str, list[Wheel]] | None = None, cache_env: Mapping[str, str] | None = None,
            fetch: artifact_cache.Fetcher = artifact_cache.url_fetch) -> None:
    """Installs env's lock into the interpreter python's environment, offline and hash-checked. The interpreter must be
    the Python the lock is for, since the lock holds that Python's wheels."""
    wheels = env_wheels(env, lock)
    have = python_version(python)
    if have != wheels[0].python:
        raise PackageCacheError(f"{env} is locked for Python {wheels[0].python}, and {python} is Python {have}")
    house = wheelhouse(env, root=root, lock=lock, fetch=fetch, cache_env=cache_env)
    cmd = pip_install_cmd(python, house) if pip else uv_install_cmd(python, house)
    _run(cmd, f"{env}: the hash-checked install into {python}", installer_env(root, cache_env))


def _find_python(version: str, ienv: Mapping[str, str]) -> str:
    try:
        r = subprocess.run(["uv", "python", "find", "--no-config", version], capture_output=True, text=True,
                           env=dict(ienv))
    except OSError as e:
        raise PackageCacheError(f"cannot run uv to find Python {version}: {e}") from e
    found = r.stdout.strip()
    if r.returncode != 0 or not found:
        raise PackageCacheError(f"uv finds no Python {version} (exit {r.returncode}): {(r.stdout + r.stderr).strip()}")
    return found


def environment(env: str, *, root: pathlib.Path | None = None, lock: Mapping[str, list[Wheel]] | None = None,
                cache_env: Mapping[str, str] | None = None,
                fetch: artifact_cache.Fetcher = artifact_cache.url_fetch) -> pathlib.Path:
    """The virtual environment of env, in the artifact root, built from its lock on first use. Every call fills the
    wheelhouse first, so a cached wheel that changed under its sum fails the call even when the environment exists."""
    wheels = env_wheels(env, lock)
    aroot = artifact_cache.resolve_root(cache_env) if root is None else root
    ienv = installer_env(aroot, cache_env)
    house = wheelhouse(env, root=aroot, lock=lock, fetch=fetch, cache_env=cache_env)
    interpreter = _find_python(wheels[0].python, ienv)
    key = digest(wheels, interpreter)
    envs = root_dir(aroot) / "envs"
    venv = envs / f"{env}-{key}"
    marker = venv / MARKER
    envs.mkdir(parents=True, exist_ok=True)
    fd = os.open(envs / f".{env}-{key}.lock", os.O_RDWR | os.O_CREAT, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        if marker.is_file() and marker.read_text(encoding="utf-8") == key:
            return venv
        print(f"package cache: building the {env} environment ({len(wheels)} packages, offline) in {venv}",
              file=sys.stderr, flush=True)
        _run(["uv", "venv", "--no-config", "--clear", "--quiet", "--python", interpreter, str(venv)],
             f"{env}: uv venv", ienv)
        if not (venv / "bin" / "python").is_file():
            raise PackageCacheError(f"{env}: uv venv exited 0 and made no {venv / 'bin' / 'python'}")
        _run(uv_install_cmd(str(venv / "bin" / "python"), house), f"{env}: the hash-checked install", ienv)
        _write(marker, key)
        return venv
    finally:
        os.close(fd)


def run_cmd(env: str, root: pathlib.Path | None = None) -> list[str]:
    """The prefix that runs a program from env's environment: [*run_cmd("mcp"), "python", "-I", "-c", ...]. It names
    the artifact root resolved here, so a caller that hands its child a stripped environment (PATH and HOME alone, as
    several tier tests do) still reaches the same root, WIB_ARTIFACT_CACHE on a CI runner included."""
    root = artifact_cache.resolve_root() if root is None else root
    return [sys.executable, str(VERIFY / "package_cache.py"), "run", env, "--root", str(root), "--"]


# ---------------------------------------------------------------------------------------------------- the writer

def compile_env(name: str, spec: Env, work: pathlib.Path, ienv: Mapping[str, str]) -> list[Wheel]:
    """The wheels of one environment, resolved by uv for its Python on PLATFORM, the preferred wheel of each."""
    import tomllib

    src = work / f"{name}.in"
    src.write_text("".join(f"{r}\n" for r in spec.requires), encoding="utf-8")
    out = work / f"pylock.{re.sub(r'[^a-z0-9]', '', name)}.toml"
    cmd = ["uv", "pip", "compile", "--no-config", "--quiet", "--no-header", "--python-version", spec.python,
           "--python-platform", PLATFORM, "--format", "pylock.toml", "-o", str(out)]
    for index in spec.indexes:
        cmd += ["--index", index, "--index-strategy", "unsafe-best-match"]
    _run([*cmd, str(src)], f"{name}: uv pip compile", ienv)
    wheels = []
    for p in tomllib.loads(out.read_text(encoding="utf-8")).get("packages", []):
        files = {urllib.parse.unquote(w["url"].rsplit("/", 1)[-1]): w for w in p.get("wheels", [])}
        pick = best_wheel(list(files), spec.python)
        if pick is None:
            raise PackageCacheError(f"{name}: {p['name']} {p['version']} has no wheel for Python {spec.python} on "
                                    f"{PLATFORM}; the install builds nothing from source")
        w = files[pick]
        wheels.append(Wheel(name, spec.python, p["name"], p["version"], w["hashes"]["sha256"], w["url"]))
    return wheels


def render(lock: Mapping[str, list[Wheel]], envs: Mapping[str, Env] = ENVS) -> str:
    head = [
        "# ABOUTME: Every Python package verify/, scripts/ and the CI jobs install, by environment: the one wheel each",
        "# ABOUTME: installs, by SHA-256 and URL. verify/package_cache.py serves them from the host artifact cache (#1121).",
        "#",
        "# Written by `python3 verify/package_cache.py write`, which resolves each environment in its ENVS with",
        f"# `uv pip compile --format pylock.toml` for its Python on {PLATFORM} and keeps the wheel that Python",
        "# prefers. Do not edit by hand: change ENVS and write it again.",
        "#",
        "# env  python  package  version  sha256  url",
    ]
    body = []
    for name in sorted(lock):
        spec = envs[name]
        body += ["", f"# {name}: {', '.join(spec.requires)} on Python {spec.python}"
                 + (f", with {', '.join(spec.indexes)}" if spec.indexes else "") + (f". {spec.why}" if spec.why else "")]
        body += [f"{w.env}  {w.python}  {w.name}  {w.version}  {w.sha256}  {w.url}"
                 for w in sorted(lock[name], key=lambda w: w.name)]
    return "\n".join(head + body) + "\n"


def write(names: Sequence[str] = ()) -> None:
    unknown = [n for n in names if n not in ENVS]
    if unknown:
        raise PackageCacheError(f"no environment {', '.join(unknown)} in ENVS ({', '.join(ENVS)})")
    old = read_lock() if LOCK.exists() else {}
    ienv = installer_env()
    new = {n: w for n, w in old.items() if n in ENVS}
    work = artifact_cache.scratch_dir("wib-pylock-")
    try:
        for name in names or list(ENVS):
            new[name] = compile_env(name, ENVS[name], work, ienv)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    LOCK.write_text(render(new), encoding="utf-8")


# ------------------------------------------------------------------------------------------------ command line

USAGE = ("usage: package_cache.py run <env> [--root <dir>] -- <program> [args...] | python <env> | wheelhouse <env> | "
         "install <env> --python <interpreter> [--pip] | node-env | write [env...]")


def main(argv: list[str]) -> int:
    try:
        if argv[:1] == ["run"] and "--" in argv:
            sep = argv.index("--")
            opts, program_argv = argv[1:sep], argv[sep + 1:]
            if len(opts) == 3 and opts[1] == "--root":
                root = pathlib.Path(opts[2])
                if artifact_cache.worktree_of(root) is not None:
                    raise PackageCacheError(f"--root {root} is inside the git worktree {artifact_cache.worktree_of(root)}")
            elif len(opts) == 1:
                root = None
            else:
                raise PackageCacheError(USAGE)
            if not program_argv:
                raise PackageCacheError(USAGE)
            venv = environment(opts[0], root=root)
            program = venv / "bin" / program_argv[0]
            if not program.is_file():
                raise PackageCacheError(f"{opts[0]}: the environment has no program {program_argv[0]} in {venv / 'bin'}")
            sys.stdout.flush()
            sys.stderr.flush()
            os.execv(program, [str(program), *program_argv[1:]])
        if len(argv) == 2 and argv[0] == "python":
            print(environment(argv[1]) / "bin" / "python")
            return 0
        if len(argv) == 2 and argv[0] == "wheelhouse":
            print(wheelhouse(argv[1]))
            return 0
        if len(argv) in (4, 5) and argv[0] == "install" and argv[2] == "--python" and argv[4:] in ([], ["--pip"]):
            install(argv[1], argv[3], pip=argv[4:] == ["--pip"])
            return 0
        if argv == ["node-env"]:
            for k, v in node_env().items():
                print(f"{k}={v}")
            return 0
        if argv[:1] == ["write"]:
            write(argv[1:])
            return 0
        raise PackageCacheError(USAGE)
    except (PackageCacheError, artifact_cache.ArtifactCacheError) as e:
        print(f"PACKAGE CACHE FAILED: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
