#!/usr/bin/env python3
# ABOUTME: Every copy of the code-of-conduct pattern under gitops/ (#1289): where each sits, how it is written there, and
# ABOUTME: one command that checks them all against floor.portable_pattern() or regenerates them all from it.
"""One source for the copies of the code-of-conduct pattern.

docs/research/2026-11-09-coc-floor/floor.py's portable_pattern(), over terms-proposed.rot13, is the term floor in the
RE2 form both the cluster's admission and the collector run. Neither can import Python, so the pattern is written out
in full in each place that runs it. Each place is a Site below: its file, the text around the copy, and how the
copy is escaped there.

    python3 verify/coc_pattern_copies.py          check: name each copy and exit 1 on a stale or unknown one
    python3 verify/coc_pattern_copies.py write    regenerate every copy from floor.portable_pattern(), then check

A copy found anywhere else under gitops/ is a problem too: scan() looks for the pattern's own pieces (floor's
separator class and its leetspeak classes, in any escaping) in every file there, and each one has to sit
inside a copy a Site knows. A new copy therefore fails verify/test_coc_pattern_copies.py until it gets a Site here,
and from then on that test holds it to the floor. On 2026-11-09 #1278 copied the pattern into the admission policy
and #1277 changed it 17 minutes later; each run passed on its own branch and staging went red (#1289).

A Builder is the other kind of place: a Python file that builds the floor's pattern itself, from the same terms,
inside a block between two anchor comments (#1269's deploy_app refusal and the desk's mask). Its pieces inside that
block are known, `write` leaves it alone, and the test it names (test_deploy_coc) holds the compiled pattern to
floor.proposed_pattern(). #1269 added the block a minute before #1289's scan landed, each on its own branch, and the
scan called the block's separator an unknown copy (#1294's run 19718).
"""
from __future__ import annotations

import dataclasses
import pathlib
import re
import sys
from typing import Callable

REPO = pathlib.Path(__file__).resolve().parent.parent
SPIKE = REPO / "docs/research/2026-11-09-coc-floor"
GITOPS = REPO / "gitops"
sys.path.insert(0, str(SPIKE))
sys.path.insert(0, str(REPO / "verify"))

import coc_mask_cases  # noqa: E402
import floor  # noqa: E402


@dataclasses.dataclass(frozen=True)
class Site:
    """One place the pattern is written. `where` finds the copy in the file's text: its group w is the pattern as
    written. encode turns the pattern into that; decode undoes it. `anchor` is the literal `where` is built around, so
    a reworded file is named as that rather than as a missing copy."""
    path: str
    what: str
    anchor: str
    where: re.Pattern
    encode: Callable[[str], str]
    decode: Callable[[str], str]
    tests: tuple[str, ...]  # the offline tests besides this one's own that hold this copy to the floor, by stem


def _cel_raw(regex: str) -> str:
    """CEL raw string r'...' in a YAML block scalar: neither layer escapes, so the copy is the pattern itself."""
    if "'" in regex or "\n" in regex:
        raise SystemExit("the term pattern holds a quote or a newline; a CEL raw string in a block scalar cannot hold it")
    return regex


_OTTL = (f'&coc_mask \'replace_all_patterns({coc_mask_cases.CACHE}, "value", "',
         f'", "{coc_mask_cases.REPLACEMENT}")\'')

SITES = (
    Site("gitops/namespaces/code-of-conduct-names.yaml",
         "variables.floor of the code-of-conduct-names ValidatingAdmissionPolicy, a CEL raw string",
         "- name: floor",
         re.compile(r"^(?P<i> +)- name: floor\n(?P=i)  expression: \|-\n(?P=i)    r'(?P<w>[^'\n]+)'$", re.M),
         _cel_raw, lambda written: written, ("test_coc_admission",)),
    Site("gitops/otel-collector/values.yaml",
         "transform/coc_mask's replace_all_patterns, an OTTL string in collector config ($$ for $, \\\\ for \\)",
         _OTTL[0],
         re.compile(re.escape(_OTTL[0]) + r'(?P<w>[^"\n]+)' + re.escape(_OTTL[1]) + "$", re.M),
         coc_mask_cases.encode, coc_mask_cases.decode, ("test_collector_coc_mask",)),
)
@dataclasses.dataclass(frozen=True)
class Builder:
    """A Python file that builds the pattern from the floor's terms between `start` and `end`, two comment lines each
    there once. The block is not a copy to rewrite; `tests` holds what it compiles to the floor."""
    path: str
    what: str
    start: str
    end: str
    tests: tuple[str, ...]


_BLOCK = ("# --- the code-of-conduct floor (#1269, part of #1267) ", "# --- end of the code-of-conduct floor ")
BUILDERS = (
    Builder("gitops/ai-layer/workshop-mcp-server.py", "deploy_app's code-of-conduct refusal (#1269)", *_BLOCK,
            ("test_deploy_coc",)),
    Builder("gitops/ai-layer/ticket_site.py", "the desk's code-of-conduct mask on record_landing (#1269)", *_BLOCK,
            ("test_deploy_coc",)),
)
# What the floor is built from: a change to any of these changes the pattern, so it has to select every test that
# holds a copy (verify/scope-map.yaml), and it then fails on its own branch rather than on staging.
FLOOR_SOURCES = ("docs/research/2026-11-09-coc-floor/floor.py", "docs/research/2026-11-09-coc-floor/corpus.py",
                 "docs/research/2026-11-09-coc-floor/terms-proposed.rot13")
# By stem: a test named in full here would read to verify/scope_tests.py as a helper this one runs.
HOLDERS = ("test_coc_pattern_copies",) + tuple(dict.fromkeys(t for s in SITES + BUILDERS for t in s.tests))


def pattern() -> str:
    return floor.portable_pattern()


def _any_escaping(piece: str) -> str:
    """A regex for the piece however a layer has escaped it: each backslash or $ may be doubled, or more."""
    return "".join(r"\\+" if c == "\\" else r"\$+" if c == "$" else re.escape(c) for c in piece)


# The pattern's own pieces, which no other text under gitops/ holds: the separator spelt-out terms use, and the class
# of each letter that has leetspeak stand-ins. Read from floor.py, so they follow it.
PIECES = (floor._SEP,) + tuple(floor._letter(ch) for ch in sorted(floor._LEET))
FINGERPRINT = re.compile("|".join(_any_escaping(p) for p in PIECES))


@dataclasses.dataclass(frozen=True)
class Copy:
    site: Site
    start: int
    end: int
    written: str

    @property
    def decoded(self) -> str:
        return self.site.decode(self.written)


def gitops_paths() -> dict[str, pathlib.Path]:
    """Every file under gitops/ in the working tree, by its repo path, outside a submodule's checkout (guard-proxy is
    its own repo, built from its own tree) and Python's bytecode caches."""
    found = sorted(p for p in GITOPS.rglob("*") if p.is_file())
    submodules = [p.parent for p in found if p.name == ".git"]
    return {p.relative_to(REPO).as_posix(): p for p in found
            if not any(s in p.parents for s in submodules) and "__pycache__" not in p.parts}


def gitops_files() -> dict[str, str]:
    """Each of gitops_paths() as text."""
    return {rel: p.read_bytes().decode("utf-8", errors="replace") for rel, p in gitops_paths().items()}


def builder_spans(files: dict[str, str], builders: tuple[Builder, ...] = BUILDERS) -> tuple[dict[str, tuple[int, int]],
                                                                                          list[str]]:
    """Each builder's block as (start, end) in its file, by path, and each problem: the file missing, or an anchor
    there other than once or out of order."""
    spans: dict[str, tuple[int, int]] = {}
    problems: list[str] = []
    for b in builders:
        text = files.get(b.path)
        if text is None:
            problems.append(f"{b.path}: missing, and it is where {b.what} builds the pattern")
            continue
        counts = {a: text.count(a) for a in (b.start, b.end)}
        if any(n != 1 for n in counts.values()) or text.index(b.start) > text.index(b.end):
            problems.append(f"{b.path}: the block {b.what} sits in is found by {b.start!r} then {b.end!r}, once each; "
                            f"the file holds them {counts[b.start]} and {counts[b.end]} times")
            continue
        spans[b.path] = (text.index(b.start), text.index(b.end))
    return spans, problems


def scan(files: dict[str, str], sites: tuple[Site, ...] = SITES,
         builders: tuple[Builder, ...] = BUILDERS) -> tuple[list[Copy], list[str]]:
    """Each copy the sites find, and each problem: a site's file or anchor or copy missing, a site holding more than
    one copy, a builder's block not found, and a piece of the pattern outside every copy and every builder's block (a
    copy no Site knows)."""
    copies: list[Copy] = []
    blocks, problems = builder_spans(files, builders)
    for site in sites:
        text = files.get(site.path)
        if text is None:
            problems.append(f"{site.path}: missing, and it is where {site.what} sits")
            continue
        if site.anchor not in text:
            problems.append(f"{site.path} no longer holds {site.anchor!r}, which the copy is found by")
            continue
        found = [Copy(site, m.start("w"), m.end("w"), m.group("w")) for m in site.where.finditer(text)]
        if len(found) != 1:
            problems.append(f"{site.path}: {len(found)} copies where one is expected ({site.what}); "
                            f"the Site's pattern is {site.where.pattern[:80]!r}...")
        copies += found
    for path, text in sorted(files.items()):
        spans = sorted([(c.start, c.end) for c in copies if c.site.path == path]
                       + ([blocks[path]] if path in blocks else []))
        for m in FINGERPRINT.finditer(text):
            if not any(s <= m.start() and m.end() <= e for s, e in spans):
                line = text.count("\n", 0, m.start()) + 1
                problems.append(f"{path}:{line}: a piece of the code-of-conduct pattern ({m.group(0)}) outside every "
                                f"copy and builder verify/coc_pattern_copies.py knows; add a Site or a Builder for it "
                                f"there")
                break
    return copies, problems


def stale(copies: list[Copy], regex: str | None = None) -> list[str]:
    """Each copy that does not decode to floor.portable_pattern()."""
    regex = pattern() if regex is None else regex
    bad = []
    for c in copies:
        got = c.decoded
        if got != regex:
            at = next((i for i, (a, b) in enumerate(zip(got, regex)) if a != b), min(len(got), len(regex)))
            bad.append(f"{c.site.path}: {c.site.what} is not floor.portable_pattern() ({len(got)} vs {len(regex)} "
                       f"characters, first difference at {at})")
    return bad


def regenerate(files: dict[str, str], sites: tuple[Site, ...] = SITES) -> dict[str, str]:
    """The files with every copy rewritten from floor.portable_pattern(); only those that change."""
    regex = pattern()
    out = {}
    for site in sites:
        text = files.get(site.path)
        if text is None:
            continue
        new = site.where.sub(lambda m: m.group(0)[:m.start("w") - m.start()] + site.encode(regex)
                             + m.group(0)[m.end("w") - m.start():], text)
        if new != text:
            out[site.path] = new
    return out


def main(argv: list[str]) -> int:
    if argv not in ([], ["write"]):
        print(__doc__)
        return 2
    if argv == ["write"]:
        paths = gitops_paths()
        for path, text in regenerate(gitops_files()).items():
            paths[path].write_text(text, encoding="utf-8")
            print(f"rewrote the copy in {path}")
    copies, problems = scan(gitops_files())
    problems += stale(copies)
    for c in copies:
        print(f"{c.site.path}: {c.site.what}, {len(c.decoded)} characters")
    for b in BUILDERS:
        print(f"{b.path}: {b.what}, built in Python and held to the floor by {', '.join(b.tests)}")
    for p in problems:
        print(f"PROBLEM {p}")
    if problems:
        print("rerun as `python3 verify/coc_pattern_copies.py write` to regenerate every copy from floor.py")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
