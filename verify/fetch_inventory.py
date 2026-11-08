#!/usr/bin/env python3
# ABOUTME: The fetch call-site scan of verify/, .github/workflows/ and scripts/ (#1116, part of #1115), and the check of
# ABOUTME: what it finds against verify/fetch-inventory.yaml, where each site is classed pinned artifact or live check.
"""Every line under verify/, .github/workflows/ and scripts/ that names a fetch, and what each one is.

    python3 verify/fetch_inventory.py check     exit 1 naming each file:line the inventory does not account for
    python3 verify/fetch_inventory.py summary   the counts by class and kind, as decisions.md's #1115 entry gives them
    python3 verify/fetch_inventory.py draft     a YAML stub for each line no entry claims, to classify by hand

The scan reads every file `git ls-files --cached --others --exclude-standard` lists under the three directories, so a
new file is seen before it is committed, and searches each line with the PATTERNS below: curl, wget, urlopen, the Helm
verbs that read a repository, a Terraform init, the Python installs of pip and uv, the Node fetches of npm, yarn and
corepack, a Playwright browser install, a Docker or Podman pull, crane, a git clone or submodule update, the setup
actions a workflow downloads a runtime with, and a get from the host artifact cache (#1117), a chart pull, an image
layout or a git mirror through it (#1122), which fetch on a miss. It is a line scan, as #1115's `git grep` was: a command built across lines is found on the
line that names it, and a line that only names a command (a comment, a message, a regex, a stub) is found too.

The inventory, verify/fetch-inventory.yaml, lists by file the entries that claim those lines. An entry's `match` is a
regular expression searched in the line, and a line belongs to the first entry of its file that matches it; `lines`
is how many lines that entry claims, so a new fetch on a line an existing entry would match still changes a count and
fails. Each entry has a `class`:

    pinned    a fetch of an artifact with a version, digest or checksum; `kind` names the artifact kind, `pin` the
              file holding its pin, and `cached` whether it goes through the host artifact cache (#1117) today
    live      a fetch whose job is the network: our own service, a cluster, or a registry or index read as it stands
              now; `kind` names what it reaches and `target` the service or cluster
    loopback  a fetch from a server on 127.0.0.1, or a clone of a repository on this host, that the test itself made;
              `why` says which
    none      a line that names a fetch command and runs none: a comment, a message, a regex, a stub; `why` says which

Drift on a file (a call site no entry claims, a count that is off, an entry for a file with no call site) fails when
the file was last changed under the rule: an edit not yet committed, or a commit whose own copy of this module carries
DRIFT_RULE. Drift on a file last changed before the inventory existed is named, not failed on, until a change touches
that file again, as scope_tests.owed() does for the scope map (#1190): a run cut before the inventory that lands a call
site on staging mid-gate cannot fail another run's change. A malformed entry always fails.

The inventory, this file and its test are left out of the scan: they are the scan's own definition, and each names
every command it looks for. None of them fetches anything.
"""
from __future__ import annotations

import collections
import pathlib
import re
import subprocess
import sys

import yaml

REPO = pathlib.Path(__file__).resolve().parent.parent
INVENTORY_REL = "verify/fetch-inventory.yaml"
ROOTS = ("verify", ".github/workflows", "scripts")
SELF = (INVENTORY_REL, "verify/fetch_inventory.py", "verify/test_fetch_inventory.py")

# Each command family the scan looks for. The words around each are written as \W{1,4} or \s+ so that a list form,
# ["helm", "pull", ...], is found as well as a shell one.
PATTERNS = {
    "curl": r"(?<![\w./-])curl(?![\w./-])",
    "wget": r"(?<![\w./-])wget(?![\w./-])",
    "urlopen": r"\burlopen\b",
    "helm": r"\bhelm\b\W{1,4}(?:pull|fetch|push|install|upgrade|repo\W{1,4}(?:add|update)"
            r"|dep(?:endency)?\W{1,4}(?:update|build))\b|\bhelm\b.*\s--repo\b",
    "terraform-init": r"\bterraform\b\W{1,4}(?:-chdir=\S+\s+)?init\b"
                      r"""|["']init["'],\s*["']-(?:input|lockfile|backend|no-color|upgrade|plugin-dir)""",
    "pip-uv": r"\bpip3?\W{1,4}install\b|\buv\W{1,4}(?:pip\W{1,4}(?:install|sync|compile)|sync|run|venv"
              r"|tool\W{1,4}install)\b|\buvx\b|\bpipx\b",
    "node": r"\bnpm\W{1,4}(?:ci|install|i|exec)\b|\bnpx\b|\byarn\W{1,4}(?:install|add|dlx)\b"
            r"|\bcorepack\W{1,4}(?:prepare|install|enable)\b",
    "playwright-install": r"\bplaywright\W{1,4}install\b",
    "image-pull": r"\b(?:docker|podman)\W{1,4}pull\b",
    "crane": r"(?<![\w./$-])crane(?![\w./-])",
    "git-clone": r"\bgit\b.*\bclone\b|\bgit\b.*\bsubmodule\W{1,4}update\b",
    "setup-action": r"uses:\s*(?:actions/setup-\w+|astral-sh/setup-uv)",
    "artifact-cache": r"artifact-cache\.sh\W{1,4}get\b|\$\{CACHE\}\W{1,4}get\b|\bartifact_cache\.get(?:_retrying)?\("
                      r"|\bchart_fetch\.pull\(|\bimage_cache\.layout\(|image_cache\.py\W{1,4}layout\b"
                      r"|\bgit_mirror\.(?:ensure|submodules)\(|git_mirror\.py\W{1,4}(?:ensure|submodules)\b",
}
SCAN = re.compile("|".join(f"(?:{p})" for p in PATTERNS.values()))
FAMILY = {name: re.compile(p) for name, p in PATTERNS.items()}

CLASSES = {
    "pinned": ("kind", "pin", "cached"),
    "live": ("kind", "target"),
    "loopback": ("why",),
    "none": ("why",),
}
PINNED_KINDS = ("tool", "terraform-provider", "helm-chart", "browser", "python-package", "node-package",
                "container-image", "git-commit", "release-file", "cache-fill")
LIVE_KINDS = ("cluster", "lab-endpoint", "registry", "saas-api", "upstream-index", "github", "public-web")

# Drift on a file fails once the file was last changed under this rule; owed() reads it in each commit's copy of this
# module. Run 18664's gate failed on drift it had not made: 45 commits landed on staging between its base and its gate,
# from runs cut before the inventory existed, and added call sites to files it had listed (#1116).
DRIFT_RULE = "DRIFT_FAILS_SINCE = \"#1116\""
DRIFT_FAILS_SINCE = "#1116"
FIX_HINT = "run `python3 verify/fetch_inventory.py draft`, class each line and commit the inventory with the change"


def tracked(root: pathlib.Path | None = None) -> list[str]:
    """Every file under ROOTS that git tracks or would track, the scan's own three files aside."""
    root = root or REPO
    r = subprocess.run(["git", "-C", str(root), "ls-files", "-z", "--cached", "--others", "--exclude-standard", "--",
                        *ROOTS], capture_output=True)
    if r.returncode != 0:
        raise SystemExit(f"fetch_inventory: git ls-files failed in {root}: {r.stderr.decode(errors='replace').strip()}")
    files = sorted(set(f for f in r.stdout.decode().split("\0") if f))
    return [f for f in files if f not in SELF and (root / f).is_file() and not (root / f).is_symlink()]


def scan(root: pathlib.Path | None = None, files: list[str] | None = None) -> list[tuple[str, int, str]]:
    """(file, line number, line) for each line that names a fetch."""
    root = root or REPO
    hits = []
    for rel in tracked(root) if files is None else files:
        try:
            text = (root / rel).read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue  # a binary file holds no call site
        for n, line in enumerate(text.splitlines(), 1):
            if SCAN.search(line):
                hits.append((rel, n, line))
    return hits


def families(line: str) -> list[str]:
    return [name for name, rx in FAMILY.items() if rx.search(line)]


def load(path: pathlib.Path) -> dict:
    doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    sites = doc.get("sites")
    if not isinstance(sites, dict):
        raise SystemExit(f"fetch_inventory: {path} has no `sites` mapping of file to entries")
    return sites


def entry_problems(rel: str, i: int, e) -> list[str]:
    """What is wrong with one entry's own fields, each naming the file and the entry."""
    where = f"{rel}: entry {i + 1}"
    if not isinstance(e, dict):
        return [f"{where} is not a mapping"]
    where += f" (match {e.get('match')!r})"
    out = []
    if not isinstance(e.get("match"), str) or not e["match"]:
        out.append(f"{where} has no match")
    else:
        try:
            re.compile(e["match"])
        except re.error as err:
            out.append(f"{where} has a match that is not a regular expression: {err}")
    if not isinstance(e.get("lines"), int) or isinstance(e.get("lines"), bool) or e["lines"] < 1:
        out.append(f"{where} has no `lines` count of 1 or more")
    cls = e.get("class")
    if not isinstance(cls, str) or cls not in CLASSES:
        out.append(f"{where} has no classification: class is {cls!r}, not one of {', '.join(CLASSES)}")
        return out
    for field in CLASSES[cls]:
        v = e.get(field)
        if field == "cached":
            if not isinstance(v, bool):
                out.append(f"{where} is {cls} but `cached` is not true or false")
        elif not isinstance(v, str) or not v.strip():
            out.append(f"{where} is {cls} but has no {field}")
    kinds = PINNED_KINDS if cls == "pinned" else LIVE_KINDS if cls == "live" else None
    if kinds and e.get("kind") not in kinds:
        out.append(f"{where} has kind {e.get('kind')!r}, not one of {', '.join(kinds)}")
    return out


def assign(sites: dict, hits: list[tuple[str, int, str]]):
    """(problems, claimed). Each problem is (file, drift, message): drift is True when the file's lines changed under an
    entry that was right for them, False when the entry itself is malformed. claimed maps (file, entry index) to the
    hits that entry claims."""
    problems: list[tuple[str, bool, str]] = []
    claimed: dict[tuple[str, int], list[tuple[int, str]]] = collections.defaultdict(list)
    compiled: dict[str, list] = {}
    for rel, entries in sites.items():
        if not isinstance(entries, list) or not entries:
            problems.append((rel, False, f"{rel}: its entry in the inventory is not a list of entries"))
            compiled[rel] = []
            continue
        compiled[rel] = []
        for i, e in enumerate(entries):
            problems += [(rel, False, b) for b in entry_problems(rel, i, e)]
            ok = isinstance(e, dict) and isinstance(e.get("match"), str) and e["match"]
            try:
                rx = re.compile(e["match"]) if ok else None
            except re.error:
                rx = None
            compiled[rel].append(rx)
    for rel, n, line in hits:
        i = next((i for i, rx in enumerate(compiled.get(rel, [])) if rx is not None and rx.search(line)), None)
        if i is None:
            why = "no entry for this file" if rel not in sites else "no entry of this file matches it"
            problems.append((rel, True, f"{rel}:{n}: a fetch call site missing from the inventory ({why}): "
                                        f"{line.strip()[:160]}"))
        else:
            claimed[(rel, i)].append((n, line))
    seen = {rel for rel, _, _ in hits}
    for rel, entries in sites.items():
        if not isinstance(entries, list):
            continue
        if rel not in seen:
            problems.append((rel, True, f"{rel}: the inventory lists it, but the scan finds no fetch call site there"))
            continue
        for i, e in enumerate(entries):
            if not isinstance(e, dict):
                continue
            got = claimed.get((rel, i), [])
            want = e.get("lines")
            if isinstance(want, int) and len(got) != want:
                at = ", ".join(f"{rel}:{n}" for n, _ in got) or "none"
                problems.append((rel, True, f"{rel}: entry {i + 1} (match {e.get('match')!r}) claims {len(got)} "
                                            f"lines, the inventory says {want}; it claims {at}"))
            if not isinstance(e.get("class"), str) or e["class"] not in CLASSES:
                for n, _ in got:
                    problems.append((rel, False, f"{rel}:{n}: a fetch call site with no classification"))
    return problems, claimed


def _under_rule(rel: str, root: pathlib.Path, seen: dict[str, bool]) -> bool:
    """Whether the last change to rel was made under the drift rule: an edit not yet committed, or a commit whose own
    verify/fetch_inventory.py carries DRIFT_RULE. A commit with no fetch_inventory.py came before the inventory. A path
    git cannot place counts as under the rule, so nothing is let off by an unreadable history."""
    def git(*args: str) -> subprocess.CompletedProcess:
        return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)
    status = git("status", "--porcelain", "--", rel)
    if status.returncode != 0 or status.stdout.strip():
        return True
    last = git("log", "-1", "--format=%H", "--", rel)
    sha = last.stdout.strip()
    if last.returncode != 0 or not sha:
        return True
    if sha not in seen:
        own = git("show", f"{sha}:verify/fetch_inventory.py")
        seen[sha] = own.returncode == 0 and DRIFT_RULE in own.stdout
    return seen[sha]


def owed(problems: list[tuple[str, bool, str]], root: pathlib.Path | None = None) -> tuple[list[str], list[str]]:
    """(fails, named). A malformed entry always fails: the inventory is this change's own. Drift on a file fails when
    the file was last changed under the rule, so the change that adds a call site classes it in the same commit. Drift
    on a file last changed in a commit made before the inventory existed is named, not failed on, until a change
    touches that file again: another run's older commit landing on staging mid-gate cannot fail this one."""
    root = root or REPO
    seen: dict[str, bool] = {}
    under: dict[str, bool] = {}
    fails, named = [], []
    for rel, drift, msg in problems:
        if drift and rel not in under:
            under[rel] = _under_rule(rel, root, seen)
        (fails if not drift or under[rel] else named).append(msg)
    return fails, named


def check_split(root: pathlib.Path | None = None, inventory: pathlib.Path | None = None,
                files: list[str] | None = None) -> tuple[list[str], list[str]]:
    """(fails, named): check()'s problems split by owed()."""
    root = root or REPO
    sites = load(inventory or root / INVENTORY_REL)
    problems, _ = assign(sites, scan(root, files))
    return owed(problems, root)


def check(root: pathlib.Path | None = None, inventory: pathlib.Path | None = None,
          files: list[str] | None = None) -> list[str]:
    """Every problem, drift from before the rule included."""
    root = root or REPO
    sites = load(inventory or root / INVENTORY_REL)
    problems, _ = assign(sites, scan(root, files))
    return [msg for _, _, msg in problems]


def summary(root: pathlib.Path | None = None, inventory: pathlib.Path | None = None) -> dict:
    """Sites (lines) by class and kind, and by class and command family."""
    root = root or REPO
    sites = load(inventory or root / INVENTORY_REL)
    problems, claimed = assign(sites, scan(root))
    by_kind: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    by_family: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    cached: collections.Counter = collections.Counter()
    files: dict[str, set] = collections.defaultdict(set)
    for (rel, i), got in claimed.items():
        e = sites[rel][i]
        cls, kind = str(e.get("class")), str(e.get("kind", "-"))
        for _, line in got:
            by_kind[cls][kind] += 1
            for fam in families(line):
                by_family[cls][fam] += 1
            if cls == "pinned":
                cached[(kind, e.get("cached") is True)] += 1
            files[cls].add(rel)
    return {"problems": [msg for _, _, msg in problems], "by_kind": by_kind, "by_family": by_family, "cached": cached, "files": files,
            "total": sum(len(g) for g in claimed.values())}


def draft(root: pathlib.Path | None = None, inventory: pathlib.Path | None = None) -> str:
    root = root or REPO
    inventory = inventory or root / INVENTORY_REL
    sites = load(inventory) if inventory.exists() else {}
    problems, _ = assign(sites, scan(root))
    out = collections.defaultdict(list)
    for _, _, p in problems:
        m = re.match(r"(.+?):(\d+): a fetch call site missing", p)
        if m:
            out[m.group(1)].append(p.split("): ", 1)[1])
    lines = []
    for rel, ls in out.items():
        lines.append(f"  {rel}:")
        lines.append(f"    - match: '.'  # {len(ls)}: " + " | ".join(x[:60] for x in ls[:3]))
        lines.append(f"      lines: {len(ls)}")
        lines.append("      class: ")
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    if argv == ["check"]:
        fails, named = check_split()
        for p in fails:
            print(f"  FAIL  {p}")
        for p in named:
            print(f"  NOTE  {p} (last changed before the inventory's rule; named, not failed on)")
        print(f"fetch inventory: {len(fails)} problems; {FIX_HINT}" if fails
              else "fetch inventory: every call site classed")
        return 1 if fails else 0
    if argv == ["summary"]:
        s = summary()
        print(f"{s['total']} call sites in {len(set().union(*s['files'].values()))} files")
        for cls in CLASSES:
            n = sum(s["by_kind"][cls].values())
            print(f"{cls}: {n} sites in {len(s['files'][cls])} files")
            if cls in ("pinned", "live"):
                for k, v in sorted(s["by_kind"][cls].items(), key=lambda kv: -kv[1]):
                    extra = ""
                    if cls == "pinned":
                        extra = f" ({s['cached'][(k, True)]} through the artifact cache)"
                    print(f"  {k}: {v}{extra}")
            print("  by command: " + ", ".join(f"{k} {v}" for k, v in sorted(s["by_family"][cls].items(),
                                                                         key=lambda kv: -kv[1])))
        for p in s["problems"]:
            print(f"  FAIL  {p}")
        return 1 if s["problems"] else 0
    if argv == ["draft"]:
        print(draft())
        return 0
    print(__doc__.split("\n\n")[1], file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
