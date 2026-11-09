#!/usr/bin/env python3
# ABOUTME: Every copy of the code-of-conduct pattern under gitops/ is floor.portable_pattern() (#1289), no copy sits
# ABOUTME: where coc_pattern_copies.py has no Site for it, and a change to the floor selects every test that holds one.
"""Offline: git ls-files, the files under gitops/, the spike's floor and verify/scope-map.yaml; standard library and
PyYAML. No cluster, no network.

1. Each Site in verify/coc_pattern_copies.py finds exactly one copy, each decodes to floor.portable_pattern(), and no
   piece of the pattern (floor's separator class or a leetspeak class, in any escaping) sits anywhere else under
   gitops/: a copy in a new file fails here until it gets a Site.
2. The scan finds the pattern however it is escaped, and the check catches what turned staging red on 2026-11-09: a
   copy written before #1277 gave the pattern its JSON-escape edges is stale, and `write` repairs it and touches
   nothing else in the file. A copy in a file no Site names is reported, and so is a Site whose anchor is reworded.
3. Through verify/scope-map.yaml as committed, a change to floor.py, corpus.py or terms-proposed.rot13 selects this
   test and every test a Site names, without running the whole suite, and a change to a copy's file selects them too.
"""
from __future__ import annotations

import fnmatch
import json
import pathlib
import sys

import yaml

VERIFY = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(VERIFY))

import coc_pattern_copies as cpc  # noqa: E402

failures: list[str] = []


def check(what: str, ok: bool) -> None:
    print(("  PASS  " if ok else "  FAIL  ") + what)
    if not ok:
        failures.append(what)


PATTERN = cpc.pattern()
# #1277 added the JSON-escape alternatives to the leading edge; the copy #1278 made before it had the plain edge.
EDGE_NOW = r"(?i)(^|[^a-z0-9]|\\[nrt]|\\u" + "[0-9a-f]" * 4 + ")"
EDGE_BEFORE_1277 = r"(?i)(^|[^a-z0-9])"
if not PATTERN.startswith(EDGE_NOW):
    print(f"  FAIL  floor.portable_pattern() no longer starts with {EDGE_NOW!r}, which case 2 builds the old copy from")
    sys.exit(1)

print("== 1. every copy under gitops/ is floor.portable_pattern(), and there is no other ==")
files = cpc.gitops_files()
copies, problems = cpc.scan(files)
for p in problems:
    print(f"        {p}")
check(f"each of the {len(cpc.SITES)} Sites finds one copy, and no piece of the pattern sits outside them among the "
      f"{len(files)} files under gitops/", not problems and len(copies) == len(cpc.SITES))
for c in copies:
    check(f"{c.site.path}: {c.site.what} decodes to floor.portable_pattern() ({len(c.decoded)} of {len(PATTERN)} "
          "characters)", c.decoded == PATTERN)
    check(f"{c.site.path}: it is written as that Site encodes it, so `write` leaves it as it is",
          c.written == c.site.encode(PATTERN))
check("`python3 verify/coc_pattern_copies.py write` would change no file", cpc.regenerate(files) == {})

print("== 2. the scan finds every escaping, and the check catches a stale or unknown copy ==")
for site in cpc.SITES:
    check(f"the scan finds the pattern as {site.path} writes it", bool(cpc.FINGERPRINT.search(site.encode(PATTERN))))
check("the scan finds the pattern JSON-encoded (every backslash doubled)",
      bool(cpc.FINGERPRINT.search(json.dumps(PATTERN))))
check("the scan finds the pattern with every backslash quadrupled",
      bool(cpc.FINGERPRINT.search(PATTERN.replace("\\", "\\\\\\\\"))))
check("every piece the scan looks for is in floor.portable_pattern() itself",
      all(p in PATTERN for p in cpc.PIECES))

old = EDGE_BEFORE_1277 + PATTERN[len(EDGE_NOW):]
for site in cpc.SITES:
    mine = next(c for c in copies if c.site is site)
    text = files[site.path]
    before = text[:mine.start] + site.encode(old) + text[mine.end:]
    staged = dict(files, **{site.path: before})
    got, probs = cpc.scan(staged)
    bad = cpc.stale(got)
    check(f"{site.path} with the copy from before #1277's JSON-escape edges: the check names it stale "
          f"({bad[:1]})", not probs and len(bad) == 1 and bad[0].startswith(site.path))
    fixed = cpc.regenerate(staged)
    check(f"{site.path}: `write` restores the file exactly as committed, every other line untouched",
          fixed == {site.path: text})

unknown = "/".join(("gitops", "a-file-no-site-names"))
_, probs = cpc.scan(dict(files, **{unknown: "pattern: " + json.dumps(old) + "\n"}))
check(f"a copy in {unknown}, which no Site names, is reported with its line ({probs[:1]})",
      len(probs) == 1 and probs[0].startswith(f"{unknown}:1: "))
site = cpc.SITES[0]
_, probs = cpc.scan(dict(files, **{site.path: files[site.path].replace(site.anchor, "- name: pattern")}))
check(f"a reworded anchor in {site.path} is named as that ({probs[:1]})",
      any(repr(site.anchor) in p and "no longer holds" in p for p in probs))

print("== 3. a change to the floor selects every test that holds a copy, through verify/scope-map.yaml ==")
# The map as committed, read the way verify/scope_tests.py's select() reads it: a test runs for a changed path when it
# is an always test or an entry of its reads covers the path. (Importing scope_tests would make this an always test,
# since its own git calls read the whole tree.)
doc = yaml.safe_load((VERIFY / "scope-map.yaml").read_text(encoding="utf-8"))


def covers(entry: str, path: str) -> bool:
    """scope_tests.covers(): a path covers itself and what is under it; * and ? glob, * across / as well."""
    if any(c in entry for c in "*?["):
        return fnmatch.fnmatchcase(path, entry) or fnmatch.fnmatchcase(path, entry.rstrip("/") + "/*")
    return path == entry or path.startswith(entry + "/") or entry == ""


def selects(stem: str, path: str) -> bool:
    test = f"{stem}.py"
    return test in (doc.get("always") or {}) or any(covers(e, path) for e in (doc.get("reads") or {}).get(test, []))


check(f"each holder ({', '.join(cpc.HOLDERS)}) has an entry in the map",
      all(f"{t}.py" in (doc.get("always") or {}) or f"{t}.py" in (doc.get("reads") or {}) for t in cpc.HOLDERS))
for src in cpc.FLOOR_SOURCES:
    missing = [t for t in cpc.HOLDERS if not selects(t, src)]
    check(f"a change to {src} selects {', '.join(cpc.HOLDERS)} (missing: {missing})", not missing)
    check(f"{src} is not in the map's full list, so a change to it alone is scoped, not the whole suite",
          not any(covers(e, src) for e in doc.get("full") or []))
for site in cpc.SITES:
    for t in site.tests:
        check(f"a change to {site.path} selects {t} and this test, which hold its copy to the floor",
              selects(t, site.path) and selects("test_coc_pattern_copies", site.path))

print()
if failures:
    print(f"FAIL: {len(failures)} checks failed")
    sys.exit(1)
print("PASS: every copy of the code-of-conduct pattern under gitops/ is the floor's, and a change to the floor runs "
      "every test that holds one")
