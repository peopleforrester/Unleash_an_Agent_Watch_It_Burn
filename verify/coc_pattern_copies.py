#!/usr/bin/env python3
# ABOUTME: Every copy of the code-of-conduct pattern under gitops/ (#1289): where each sits, how it is written there, and
# ABOUTME: one command that checks them all against floor.py's RE2 forms or regenerates them all from them.
"""One source for the copies of the code-of-conduct pattern.

docs/research/2026-11-09-coc-floor/floor.py's portable_patterns() and name_pattern(), over terms-proposed.rot13, are
the term floor in the RE2 forms the collector (portable_patterns, portable_pattern() cut into short patterns, #1328) and
the cluster's admission on names (name_pattern, the same matcher for text that can only hold what a name or a label
holds, #1316) run. Neither can import Python, so the pattern is written out in full in each place that runs it. Each
place is a Site below: its file, the text around the copy, which form it holds, and how the copy is escaped there.

    python3 verify/coc_pattern_copies.py          check: name each copy and exit 1 on a stale or unknown one
    python3 verify/coc_pattern_copies.py write    regenerate every copy from its floor function, then check

A copy found anywhere else under gitops/ is a problem too: scan() looks for the pattern's own pieces (floor's
separator class and its leetspeak classes, in any escaping) in every file there, and each one has to sit
inside a copy a Site knows or a Port's block. A Port is a file that carries floor.py's own Python and builds the
pattern from it (#1269 put one in workshop-mcp-server.py and ticket_site.py); test_deploy_coc.py holds those to the
floor. A new copy therefore fails verify/test_coc_pattern_copies.py until it gets a Site or a Port here, and from then
on the tests it names hold it to the floor. On 2026-11-09 #1278 copied the pattern into the admission policy
and #1277 changed it 17 minutes later; each run passed on its own branch and staging went red (#1289).
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
    source: Callable[..., str] = floor.portable_pattern  # the floor function the copy is, called with a term list or none

    @property
    def form(self) -> str:
        return f"{self.source.__module__}.{self.source.__name__}()"


def _cel_raw(regex: str) -> str:
    """CEL raw string r'...' in a YAML block scalar: neither layer escapes, so the copy is the pattern itself."""
    if "'" in regex or "\n" in regex:
        raise SystemExit("the term pattern holds a quote or a newline; a CEL raw string in a block scalar cannot hold it")
    return regex


_OTTL = (f'replace_all_patterns({coc_mask_cases.CACHE}, "value", "', f'", "{coc_mask_cases.REPLACEMENT}")')
_OTTL_INDENT = " " * 12  # the statements' indentation in values.yaml
_OTTL_FIRST = "'" + _OTTL[0]


def _ottl_block(patterns: str) -> str:
    """The collector's patterns (coc_mask_cases.collector_patterns(), one a line) as values.yaml writes them in
    transform/coc_mask's span statements: each pattern's replace_all_patterns statement, then the same with
    coc_mask_cases.SECOND_PASS, so the collector applies each twice before the next; the span-event context aliases
    the whole list."""
    lines = []
    for regex in patterns.split("\n"):
        statement = coc_mask_cases.replace_statement(regex)
        lines += [f"'{statement}'", f"'{statement}{coc_mask_cases.SECOND_PASS}'"]
    return f"\n{_OTTL_INDENT}- ".join(lines)


_OTTL_STATEMENT = re.compile("^'" + re.escape(_OTTL[0]) + r'([^"\n]*)' + re.escape(_OTTL[1]) + "'$")


def _ottl_patterns(written: str) -> str:
    """What RE2 compiles from each first-pass statement of the block, one a line."""
    lines = [line.strip().removeprefix("- ") for line in written.split("\n")]
    return "\n".join(coc_mask_cases.decode(m.group(1)) for m in map(_OTTL_STATEMENT.match, lines) if m)


SITES = (
    Site("gitops/namespaces/code-of-conduct-names.yaml",
         "variables.floor of the code-of-conduct-names ValidatingAdmissionPolicy, a CEL raw string",
         "- name: floor",
         re.compile(r"^(?P<i> +)- name: floor\n(?P=i)  expression: \|-\n(?P=i)    r'(?P<w>[^'\n]+)'$", re.M),
         _cel_raw, lambda written: written, ("test_coc_admission",), floor.name_pattern),
    Site("gitops/otel-collector/values.yaml",
         "transform/coc_mask's replace_all_patterns statements, OTTL strings in collector config ($$ for $, \\\\ for "
         "\\), two a pattern",
         "- " + _OTTL_FIRST,
         re.compile(r"^(?P<i> +)- (?P<w>" + re.escape(_OTTL_FIRST) + r"[^\n]*'(?:\n(?P=i)- " + re.escape(_OTTL_FIRST)
                    + r"[^\n]*')*)$", re.M),
         _ottl_block, _ottl_patterns, ("test_collector_coc_mask",),
         coc_mask_cases.collector_patterns),
)
# What the floor is built from: a change to any of these changes the pattern, so it has to select every test that
# holds a copy (verify/scope-map.yaml), and it then fails on its own branch rather than on staging.
FLOOR_SOURCES = ("docs/research/2026-11-09-coc-floor/floor.py", "docs/research/2026-11-09-coc-floor/corpus.py",
                 "docs/research/2026-11-09-coc-floor/terms-proposed.rot13")


@dataclasses.dataclass(frozen=True)
class Port:
    """A file that carries floor.py's own Python rather than a copy of portable_pattern(): its separator class, its
    leetspeak table and its term list, from which the file builds the pattern itself as it starts. It sits between two
    marker lines, and `tests` hold it to floor.proposed_pattern(). The scan reads the floor's pieces between the
    markers as the port's, so only a piece outside them is a copy no Site or Port knows."""
    path: str
    start: str
    end: str
    tests: tuple[str, ...]  # by stem, as Site.tests


# #1269 put the floor into the deploy path as one block, the same text in both files; test_deploy_coc.py holds it
# equal in both and its compiled pattern to floor.proposed_pattern(), on the spike's abuse set and hard negatives.
_PORT_START = "# --- the code-of-conduct floor (#1269, part of #1267) "
_PORT_END = "# --- end of the code-of-conduct floor "
PORTS = (
    Port("gitops/ai-layer/workshop-mcp-server.py", _PORT_START, _PORT_END, ("test_deploy_coc",)),
    Port("gitops/ai-layer/ticket_site.py", _PORT_START, _PORT_END, ("test_deploy_coc",)),
)
# By stem: a test named in full here would read to verify/scope_tests.py as a helper this one runs.
HOLDERS = ("test_coc_pattern_copies",) + tuple(dict.fromkeys(t for s in SITES + PORTS for t in s.tests))


def pattern() -> str:
    """floor.portable_pattern(), the single RE2 form the collector's patterns are cut from; each Site's own is
    site.source()."""
    return floor.portable_pattern()


def _any_escaping(piece: str) -> str:
    """A regex for the piece however a layer has escaped it: each backslash or $ may be doubled, or more."""
    return "".join(r"\\+" if c == "\\" else r"\$+" if c == "$" else re.escape(c) for c in piece)


# The pattern's own pieces, which no other text under gitops/ holds: the separator spelt-out terms use, and the class
# of each letter that has leetspeak stand-ins, which portable_pattern() holds; and name_pattern()'s opening, its plain
# edge then its terms, since its classes keep only what a name holds and read like any other regex's. Read from
# floor.py, so they follow it.
NAME_OPENING = r"(?i)(^|[^a-z0-9])((?:"
# (The i class is left out: portable_pattern() writes the dotless i inside it, so it reads differently there.)
PIECES = ((floor._SEP,) + tuple(floor._letter(ch) for ch in sorted(floor._LEET) if ch not in floor._RE2_UNFOLDED)
          + (NAME_OPENING,))
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

    @property
    def regexes(self) -> list[str]:
        """Each pattern the copy holds: the collector's holds one a line (coc_mask_cases.collector_patterns())."""
        return self.decoded.split("\n")


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


def port_spans(files: dict[str, str], ports: tuple[Port, ...] = PORTS) -> tuple[dict[str, list[tuple[int, int]]],
                                                                                  list[str]]:
    """Where each port's block sits in its file, from the start marker to the end of the end marker's line, and each
    problem: the file missing, or a marker missing or written more than once."""
    spans: dict[str, list[tuple[int, int]]] = {}
    problems: list[str] = []
    for port in ports:
        text = files.get(port.path)
        if text is None:
            problems.append(f"{port.path}: missing, and it carries a port of floor.py")
            continue
        counts = {m: text.count(m) for m in (port.start, port.end)}
        if any(n != 1 for n in counts.values()):
            problems.append(f"{port.path}: the port's markers {counts} each have to be there once, and the floor's "
                            "pieces are read as the port's only between them")
            continue
        s = text.index(port.start)
        e = text.find("\n", text.index(port.end))
        spans.setdefault(port.path, []).append((s, len(text) if e < 0 else e))
    return spans, problems


def scan(files: dict[str, str], sites: tuple[Site, ...] = SITES,
         ports: tuple[Port, ...] = PORTS) -> tuple[list[Copy], list[str]]:
    """Each copy the sites find, and each problem: a site's file or anchor or copy missing, a site holding more than
    one copy, a port's markers missing, and a piece of the pattern outside every copy and port (a copy no Site or Port
    knows)."""
    copies: list[Copy] = []
    known, problems = port_spans(files, ports)
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
        spans = sorted([(c.start, c.end) for c in copies if c.site.path == path] + known.get(path, []))
        for m in FINGERPRINT.finditer(text):
            if not any(s <= m.start() and m.end() <= e for s, e in spans):
                line = text.count("\n", 0, m.start()) + 1
                problems.append(f"{path}:{line}: a piece of the code-of-conduct pattern ({m.group(0)}) outside every "
                                f"copy and port verify/coc_pattern_copies.py knows; add a Site or a Port for it there")
                break
    return copies, problems


def stale(copies: list[Copy]) -> list[str]:
    """Each copy that does not decode to its Site's floor function."""
    bad = []
    forms = {}
    for c in copies:
        regex = forms.setdefault(c.site.source, c.site.source())
        got = c.decoded
        if got != regex:
            at = next((i for i, (a, b) in enumerate(zip(got, regex)) if a != b), min(len(got), len(regex)))
            bad.append(f"{c.site.path}: {c.site.what} is not {c.site.form} ({len(got)} vs {len(regex)} "
                       f"characters, first difference at {at})")
    return bad


def regenerate(files: dict[str, str], sites: tuple[Site, ...] = SITES) -> dict[str, str]:
    """The files with every copy rewritten from its Site's floor function; only those that change."""
    out = {}
    for site in sites:
        text = files.get(site.path)
        if text is None:
            continue
        regex = site.source()
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
        print(f"{c.site.path}: {c.site.what}, {c.site.form}, {len(c.decoded)} characters")
    for p in problems:
        print(f"PROBLEM {p}")
    if problems:
        print("rerun as `python3 verify/coc_pattern_copies.py write` to regenerate every copy from floor.py")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
