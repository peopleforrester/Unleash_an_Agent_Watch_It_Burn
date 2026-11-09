# ABOUTME: Keeps the Terraform modules a render installed in the host artifact cache, keyed by the root's module calls, so
# ABOUTME: a later render seeds .terraform/modules from a copy whose digest is checked, and reaches no network (#1246).
"""Why. The renders in iam_plan_render.py took their providers from the artifact cache's mirror (#1119), but the cluster
root's six module calls (terraform-aws-modules/eks and five of eks-pod-identity, with the kms module eks calls) were
installed from the registry and GitHub on every render, four times a test. On staging cdeaedfd one of those GitHub
connections timed out after 300 s, and the CI tools tier went red on test_iam_policy_structural.py (#1246).

What. Terraform's module installer skips a module call that .terraform/modules/modules.json already records with the
same source and a version the call's constraint allows, and makes no network request for it. So this module keeps one
copy of an installed .terraform/modules per set of module calls, in the host artifact cache (artifact_cache.py, which
resolves the root and refuses one inside a worktree):

  <root>/terraform-modules/<key>/modules/   .terraform/modules as an install left it, each module's .git left out
  <root>/terraform-modules/<key>/DIGEST     the SHA-256 over every file's path and bytes under modules/

<key> is the SHA-256 of the root's module calls: each `module "<name>"` block's source and version, sorted by name. A
change to any of them is a new key and a fresh install; an edit that leaves them alone (break_rules in
test_iam_policy_structural.py rewrites resources only) reuses the copy.

  seed(work, main_tf)   on a hit, checks the copy's digest and copies it into work/.terraform/modules; True on a hit,
                        False on a miss or when the root calls no module. A copy whose digest does not match fails,
                        naming the path and both sums, and is left where it is, as the artifact cache leaves a file.
  store(work, main_tf)  after an install that started from a miss, copies work/.terraform/modules into the cache under a
                        lock on the key, through a temp directory renamed into place, so runs side by side store it once
                        and no reader sees half a copy. It appends one line to the artifact cache's fetch log (the
                        module sources, the key, the bytes kept), since the install it follows reached the network.

A version constraint (`~> 1.12.0`) admits later patch releases, which a fresh install would pick and a kept copy does
not: the copy holds what the first install resolved until main.tf's calls change. The renders read policy documents the
modules generate, and a kept copy makes them read the same documents on every run.

Command line:
  tf_module_cache.py key <main.tf>   print the key of that file's module calls
Any failure raises ModuleCacheError (an ArtifactCacheError), and the command line prints one line starting
TERRAFORM MODULE CACHE FAILED to stderr and exits 1."""
from __future__ import annotations

import fcntl
import hashlib
import os
import pathlib
import re
import shutil
import sys
import tempfile
from collections.abc import Mapping

VERIFY = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(VERIFY))
import artifact_cache as ac  # noqa: E402

SUBDIR = "terraform-modules"
FORMAT = "1"  # part of every key: a change to what a copy holds starts the cache over
MODULE_START = re.compile(r'^module "([^"]+)" \{\s*$', re.M)
ATTR = re.compile(r'^  (source|version)\s*=\s*"([^"]*)"\s*$', re.M)


class ModuleCacheError(ac.ArtifactCacheError):
    pass


class ModuleCopyMismatch(ModuleCacheError, ac.ArtifactMismatch):
    """A kept copy's files no longer hash to the digest it was stored with."""


def calls(main_tf: str) -> list[tuple[str, str, str]]:
    """(name, source, version) for each module block, sorted by name; version is "" for a call that gives none. A block
    with no top-level source line, or with no closing brace, is an error naming it."""
    out = []
    for m in MODULE_START.finditer(main_tf):
        end = main_tf.find("\n}", m.end())
        if end < 0:
            raise ModuleCacheError(f'module "{m.group(1)}" has no closing brace at the start of a line')
        attrs = dict(ATTR.findall(main_tf[m.end():end]))
        if "source" not in attrs:
            raise ModuleCacheError(f'module "{m.group(1)}" has no `  source = "..."` line; the key cannot name it')
        out.append((m.group(1), attrs["source"], attrs.get("version", "")))
    if len(out) != len(re.findall(r'^module\s', main_tf, re.M)):
        raise ModuleCacheError("a `module` block is not written `module \"<name>\" {` on one line; the key cannot read it")
    return sorted(out)


def key(main_tf: str) -> str | None:
    """The cache key of main_tf's module calls; None when it calls no module."""
    cs = calls(main_tf)
    if not cs:
        return None
    text = FORMAT + "\n" + "".join(f"{n}\t{s}\t{v}\n" for n, s, v in cs)
    return hashlib.sha256(text.encode()).hexdigest()


def _files(top: pathlib.Path) -> list[pathlib.Path]:
    """Every file and symlink under top, .git dirs left out and symlinked dirs not followed, sorted by relative path."""
    found = []
    for d, dirs, files in os.walk(top):
        here = pathlib.Path(d)
        found += [here / x for x in dirs if (here / x).is_symlink()]
        dirs[:] = [x for x in dirs if x != ".git" and not (here / x).is_symlink()]
        found += [here / f for f in files]
    return sorted(found, key=lambda p: p.relative_to(top).as_posix())


def digest(top: pathlib.Path) -> tuple[str, int]:
    """SHA-256 over each file's path relative to top and its bytes (a symlink's target text), .git dirs left out; and
    the bytes read."""
    h, size = hashlib.sha256(), 0
    for f in _files(top):
        rel = f.relative_to(top).as_posix()
        data = ("->" + os.readlink(f)).encode() if f.is_symlink() else f.read_bytes()
        size += len(data)
        h.update(f"{rel}\0{len(data)}\0".encode())
        h.update(data)
    return h.hexdigest(), size


def entry(k: str, root: pathlib.Path) -> pathlib.Path:
    return root / SUBDIR / k


def _copy(src: pathlib.Path, dst: pathlib.Path) -> None:
    shutil.copytree(src, dst, symlinks=True, ignore=shutil.ignore_patterns(".git"))


def seed(work: pathlib.Path, main_tf: str, *, env: Mapping[str, str] | None = None) -> bool:
    k = key(main_tf)
    if k is None:
        return False
    e = entry(k, ac.resolve_root(env))
    if not (e / "DIGEST").is_file():
        return False
    want = (e / "DIGEST").read_text(encoding="utf-8").strip()
    got, _ = digest(e / "modules")
    if got != want:
        raise ModuleCopyMismatch(f"kept modules {e / 'modules'} do not match their digest: expected SHA-256 {want}, got "
                                 f"{got}; the copy is left in place and not installed again")
    dst = work / ".terraform" / "modules"
    if dst.exists():
        raise ModuleCacheError(f"{dst} exists already; seed() fills a fresh working directory only")
    dst.parent.mkdir(parents=True, exist_ok=True)
    _copy(e / "modules", dst)
    return True


def store(work: pathlib.Path, main_tf: str, *, env: Mapping[str, str] | None = None) -> pathlib.Path | None:
    """Keep work/.terraform/modules for main_tf's key; the entry's path, or None when main_tf calls no module."""
    k = key(main_tf)
    if k is None:
        return None
    src = work / ".terraform" / "modules"
    if not (src / "modules.json").is_file():
        raise ModuleCacheError(f"{src} has no modules.json; store() keeps a finished install only")
    root = ac.resolve_root(env)
    e = entry(k, root)
    e.parent.mkdir(parents=True, exist_ok=True)
    with open(e.parent / f"{k}.lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if (e / "DIGEST").is_file():
            return e  # another run kept it while this one installed
        tmp = pathlib.Path(tempfile.mkdtemp(prefix=f".{k[:12]}-", dir=e.parent))
        try:
            _copy(src, tmp / "modules")
            d, size = digest(tmp / "modules")
            (tmp / "DIGEST").write_text(d + "\n", encoding="utf-8")
            if e.exists():
                raise ModuleCacheError(f"{e} exists with no DIGEST, which no store() leaves; it is left for a person "
                                       "to look at")
            os.rename(tmp, e)
        except BaseException:
            shutil.rmtree(tmp, ignore_errors=True)
            raise
    sources = ",".join(sorted({s for _, s, _ in calls(main_tf)}))
    ac.log_fetch(ac.fetch_log_path(root, env), f"terraform-modules:{sources}", k, size, "ok (kept)")
    return e


def main(argv: list[str]) -> int:
    try:
        if len(argv) == 3 and argv[1] == "key":
            print(key(pathlib.Path(argv[2]).read_text(encoding="utf-8")) or "")
            return 0
        print(__doc__.split("Command line:")[1].split("Any failure")[0].rstrip(), file=sys.stderr)
        return 2
    except (ac.ArtifactCacheError, OSError) as e:
        print(f"TERRAFORM MODULE CACHE FAILED: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
