#!/usr/bin/env python3
# ABOUTME: The fetch call-site scan of #1116: every line under verify/, .github/workflows/ and scripts/ that names a
# ABOUTME: fetch, held against verify/fetch-inventory.yaml, where each one is a pinned artifact, a live check or no fetch.
"""Scan for fetch call sites and hold them against the inventory.

    python3 verify/fetch_inventory.py check [INVENTORY]  exit 1, naming file:line, on a site the inventory misses or leaves
                                                 unclassified, or on an inventory entry that matches no site
    python3 verify/fetch_inventory.py sites     every site the scan finds, as file:line:tool:text
    python3 verify/fetch_inventory.py counts    sites per class and kind, the table decisions.md's #1115 entry gives

The scan is `git grep` over the tracked files under SCOPE: a line is a site when one of PATTERNS matches it and it is
not a comment line (its first non-blank characters are `#` or `//`). PATTERNS is the issue's list: curl, wget, urlopen
and http.client, the helm verbs that reach a repository (pull, repo add or update, dependency) and chart_fetch.pull,
terraform init, pip and uv installs (`uv run --with`, `uv pip install`, `uv sync`, uvx), npm installs and npx,
playwright install, docker and podman pull, crane, git clone and submodule update, and a workflow's `uses:` action.

The inventory (verify/fetch-inventory.yaml) maps each file to entries; an entry's `match` is a regular expression
searched in the site's line, and a site is covered when an entry of its own file matches it. Each entry has a class:

  pinned   an artifact with a version, digest or checksum: `kind` (one of KINDS) and `pin`, the tracked file that
           holds the pin (the same file when the pin is on the line, such as a `==` version)
  unpinned an artifact fetched at a moving reference (a major tag such as `@v4`, `latest`, no version at all): `kind`
           and `why`; #1115 pins each one before it can be cached
  live     a call whose job is to reach our own service, a cluster, or an account's API: `service` names it
  none     the line names a fetch tool but fetches nothing (a test's stub or fake, an assertion on a command's
           text, a usage line in a docstring, a PATH check): `why` says which

A site matched by no entry, an entry with no class or a missing field, and an entry that matches no site all fail
`check`, each naming the file and line (or the entry). Run by verify/test_fetch_inventory.py in the offline suite.
"""
from __future__ import annotations

import collections
import pathlib
import re
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
INVENTORY = REPO / "verify" / "fetch-inventory.yaml"
SCOPE = ("verify", ".github/workflows", "scripts")
# The inventory names every pattern below in its own entries, so it is not scanned itself.
EXEMPT = {"verify/fetch-inventory.yaml"}

PATTERNS: dict[str, str] = {
    "curl": r"\bcurl\b",
    "wget": r"\bwget\b",
    "urlopen": r"\burlopen\b|\bHTTPS?Connection\(",
    "helm": r"\bhelm\b.*\b(pull|repo (add|update)|dependency (build|update)|dep (build|up))\b|\bchart_fetch\.pull\(",
    "terraform-init": r"\bterraform\b.*\binit\b|\brun\(\s*\"init\"|\"init\",\s*\"-(input|backend|upgrade|no-color|lockfile|plugin)",
    "pip-uv": r"\bpip3? install\b|\buv pip install\b|\buv sync\b|\buvx\b|\buv tool install\b|--with\b",
    "npm": r"\bnpm\b[\"', ]+(install|ci|i)\b|\bnpx\b",
    "playwright-install": r"\bplaywright\b.*\binstall\b",
    "image-pull": r"\b(docker|podman)\b.*\bpull\b",
    "crane": r"\bcrane\b",
    "git-clone": r"\bgit\b.*\bclone\b|\bsubmodule update\b",
    "action": r"^\s*-?\s*uses:\s",
}
COMPILED = {tool: re.compile(p) for tool, p in PATTERNS.items()}
COMMENT = re.compile(r"^\s*(#|//)")

CLASSES = ("pinned", "unpinned", "live", "none")
KINDS = (
    "tool-binary",         # a release binary, pinned by SHA-256 in verify/e2e-tools.lock or a script's own checksum
    "terraform-provider",  # a provider, pinned by a .terraform.lock.hcl
    "helm-chart",          # a chart at the version its Application or values file names
    "browser",             # Playwright's Chromium, at the revision the pinned playwright version names
    "os-package",          # a Debian package, pinned by version and checksum
    "python-package",      # a PyPI package at a `==` version
    "node-package",        # an npm package at the version a lock file or the line names
    "container-image",     # an image by digest, images.lock's or the line's
    "git-commit",          # a clone or submodule at a fixed commit
    "github-action",       # a workflow action at a commit SHA
    "release-asset",       # a file a release publishes, at a fixed tag, checked against a vendored copy or a SHA-256
)
REQUIRED = {"pinned": ("kind", "pin"), "unpinned": ("kind", "why"), "live": ("service",), "none": ("why",)}


class Site(collections.namedtuple("Site", "path line tools text")):
    def where(self) -> str:
        return f"{self.path}:{self.line}"


def sites(repo: pathlib.Path = REPO) -> list[Site]:
    """Every fetch call site under SCOPE in the tracked files of repo."""
    union = "|".join(f"(?:{p})" for p in PATTERNS.values())
    r = subprocess.run(["git", "-C", str(repo), "grep", "-nIP", "--no-color", union, "--", *SCOPE],
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if r.returncode not in (0, 1):
        raise RuntimeError(f"git grep failed ({r.returncode}): {r.stderr.strip()}")
    found = []
    for raw in r.stdout.splitlines():
        path, line, text = raw.split(":", 2)
        if path in EXEMPT or COMMENT.match(text):
            continue
        tools = tuple(t for t, rx in COMPILED.items() if rx.search(text))
        if tools:
            found.append(Site(path, int(line), tools, text))
    return found


def load(path: pathlib.Path = INVENTORY) -> dict:
    import yaml
    data = yaml.safe_load(path.read_text())
    if not isinstance(data, dict) or not isinstance(data.get("files"), dict):
        raise ValueError(f"{path.name} has no top-level `files:` mapping")
    return data["files"]


def entry_problems(path: str, i: int, e: object, repo: pathlib.Path) -> list[str]:
    name = f"{INVENTORY.name}: {path} entry {i + 1}"
    if not isinstance(e, dict):
        return [f"{name} is not a mapping"]
    out = []
    if not isinstance(e.get("match"), str) or not e["match"]:
        out.append(f"{name} has no `match`")
    else:
        try:
            re.compile(e["match"])
        except re.error as err:
            out.append(f"{name} `match` {e['match']!r} is not a regular expression: {err}")
    cls = e.get("class")
    if cls not in CLASSES:
        out.append(f"{name} ({e.get('match')!r}) has no classification: class is {cls!r}, not one of {', '.join(CLASSES)}")
        return out
    for field in REQUIRED[cls]:
        if not isinstance(e.get(field), str) or not e[field].strip():
            out.append(f"{name} ({e.get('match')!r}) is {cls} but has no `{field}`")
    if cls in ("pinned", "unpinned"):
        if e.get("kind") not in KINDS:
            out.append(f"{name} ({e.get('match')!r}) kind {e.get('kind')!r} is not one of {', '.join(KINDS)}")
        pin = e.get("pin")
        if cls == "pinned" and isinstance(pin, str) and pin and not (repo / pin).is_file():
            out.append(f"{name} ({e.get('match')!r}) pin {pin!r} is not a file in the repo")
    return out


def check(found: list[Site], files: dict, repo: pathlib.Path = REPO) -> list[str]:
    """Every problem, each naming the file and line or the entry: an empty list is a pass."""
    problems = []
    for path, entries in files.items():
        if not isinstance(entries, list) or not entries:
            problems.append(f"{INVENTORY.name}: {path} lists no entries")
            continue
        for i, e in enumerate(entries):
            problems.extend(entry_problems(path, i, e, repo))
    used: set[tuple[str, int]] = set()
    for s in found:
        entries = files.get(s.path)
        if not isinstance(entries, list):
            problems.append(f"{s.where()}: {'/'.join(s.tools)} site is missing from {INVENTORY.name}: {s.text.strip()}")
            continue
        hit = [i for i, e in enumerate(entries)
               if isinstance(e, dict) and isinstance(e.get("match"), str) and _search(e["match"], s.text)]
        if not hit:
            problems.append(f"{s.where()}: {'/'.join(s.tools)} site matches no entry for {s.path} in "
                            f"{INVENTORY.name}: {s.text.strip()}")
        used.update((s.path, i) for i in hit)
    for path, entries in files.items():
        for i, e in enumerate(entries if isinstance(entries, list) else []):
            if (path, i) not in used and isinstance(e, dict):
                problems.append(f"{INVENTORY.name}: {path} entry {i + 1} ({e.get('match')!r}) matches no fetch site "
                                f"there; remove it or fix its match")
    return problems


def _search(rx: str, text: str) -> bool:
    try:
        return re.search(rx, text) is not None
    except re.error:
        return False


def classify(found: list[Site], files: dict) -> list[tuple[Site, dict]]:
    """Each site with the first entry of its file that matches it."""
    out = []
    for s in found:
        for e in files.get(s.path) or []:
            if isinstance(e, dict) and _search(e.get("match", ""), s.text):
                out.append((s, e))
                break
    return out


def counts(found: list[Site], files: dict) -> collections.Counter:
    c: collections.Counter = collections.Counter()
    for s, e in classify(found, files):
        c[(e["class"], e.get("kind") or s.tools[0])] += 1
    return c


def main(argv: list[str]) -> int:
    verb = argv[1] if len(argv) in (2, 3) else ""
    inventory = pathlib.Path(argv[2]) if len(argv) == 3 else INVENTORY
    if verb == "sites":
        for s in sites():
            print(f"{s.where()}:{'/'.join(s.tools)}:{s.text.strip()}")
        return 0
    if verb == "check":
        found = sites()
        problems = check(found, load(inventory))
        for p in problems:
            print(f"FAIL  {p}")
        print(f"{len(found)} fetch call sites, {len(problems)} problems")
        return 1 if problems else 0
    if verb == "counts":
        found = sites()
        c = counts(found, load(inventory))
        for (cls, kind), n in sorted(c.items()):
            print(f"{cls:7s} {kind:20s} {n:4d}")
        print(f"{'all':28s} {sum(c.values()):4d} of {len(found)} sites")
        return 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
