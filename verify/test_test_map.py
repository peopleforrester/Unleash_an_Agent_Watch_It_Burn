#!/usr/bin/env python3
# ABOUTME: Holds verify/test-map.yaml, the Test map hecaton's tests gate reads (#1319), to what scope_tests.py writes
# ABOUTME: from the scope map, and for every tracked path to a superset of the offline tests select() would run.
"""Offline. Hecaton's tests gate picks the offline suite's files itself (hecaton#623, #1319) and passes them to
run-tests.sh in HECATON_TEST_FILES. It finds a test for a changed path when the test's code spells the path, plus the
rules of the `Test map:` file AGENTS.md declares. A test that globs a directory or walks the tree spells nothing, so
the map carries what verify/scope-map.yaml knows of each test, written by `python3 verify/scope_tests.py write`.

1. AGENTS.md declares `Test map: `verify/test-map.yaml``, read the way the gate reads it, and the file is exactly what
   scope_tests.test_map() writes from the committed scope map: a map behind the scope map fails here, naming the
   command that brings it current.
2. The rules match the way the gate matches them (PurePosixPath.full_match on each rule's paths, the tests of every
   rule a path matches, the whole suite when a matched rule is `full`). For every tracked path, and a new file of each
   common kind under each path the map covers, the rules give at least the offline tests scope_tests.select() runs for
   a change to that path alone, and the whole suite wherever select() runs it for the map's full list.
3. Only offline tests are named, as run-tests.sh sets a `# SUITE: e2e` file aside.
4. A new file gives the same map before and after its `git add` (#1396): test_map() counts the untracked files git
   would add as files, so `write` run before the add does not write the file as a directory too.
"""
from __future__ import annotations

import difflib
import glob
import os
import pathlib
import re
import subprocess
import sys
import tempfile

import yaml

REPO = pathlib.Path(__file__).resolve().parent.parent
VERIFY = REPO / "verify"
sys.path.insert(0, str(VERIFY))
import scope_tests as st  # noqa: E402

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"\n        {detail[-3000:]}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def declared(text: str, label: str) -> str | None:
    """The value of a `<label>: `value`` line, as hecaton's gate reads it (validate.command_line); the first wins."""
    m = re.search(rf"^[ \t]*(?:[-*+][ \t]+)?(?:\*\*)?{re.escape(label)}:(?:\*\*)?[ \t]*`([^`\n]+)`", text, re.M | re.I)
    return (m.group(1).strip() or None) if m else None


print("== AGENTS.md declares the Test map, and it is current with the scope map ==")
agents = (REPO / "AGENTS.md").read_text(encoding="utf-8")
check(f"AGENTS.md declares `Test map: `{st.TEST_MAP_REL}`` (got {declared(agents, 'Test map')!r})",
      declared(agents, "Test map") == st.TEST_MAP_REL)
doc, tree, tests = st.load_map(), st.Tree(), st.discover()
rules = st.test_map(doc, tree, tests)
want = st.render_test_map(rules)
have = st.TEST_MAP.read_text(encoding="utf-8") if st.TEST_MAP.exists() else ""
check(f"{st.TEST_MAP_REL} is what scope_tests.test_map() writes from {st.MAP_REL}; "
      "`python3 verify/scope_tests.py write` brings it current", have == want,
      next((f"first difference at line {i + 1}: have {a!r}, want {b!r}"
            for i, (a, b) in enumerate(zip(have.splitlines(), want.splitlines())) if a != b),
           f"have {len(have.splitlines())} lines, want {len(want.splitlines())}"))
loaded = (yaml.safe_load(have) or {}).get("rules", []) if have else []
check("the file reads back as the rules it was written from", loaded == [
    {k: v for k, v in r.items()} for r in rules], f"{len(loaded)} rules read, {len(rules)} written")

print("== only offline tests are named ==")
named = {t for r in rules for t in r.get("tests", [])}
offline = {f"verify/{n}" for n, s in tests.items() if s == "offline"}
check("every test a rule names is an offline test of the suite", named <= offline, str(sorted(named - offline)[:10]))
check("every rule is named, has paths, and either runs everything or names tests",
      all(r["name"] and r["paths"] and (r.get("full") is True) != bool(r.get("tests")) for r in rules),
      str([r["name"] for r in rules if not r["paths"] or (r.get("full") is True) == bool(r.get("tests"))][:10]))

print("== for each path, the rules give at least what select() runs ==")


def translate(g: str) -> str:
    """g as the regex PurePosixPath.full_match compiles it to (Python 3.13's glob.translate, recursive, hidden files
    matched, / the separator); one regex per rule keeps ~2,000 paths against ~9,000 globs to seconds."""
    return glob.translate(g, recursive=True, include_hidden=True, seps="/")


matchers = [(r, re.compile("|".join(f"(?:{translate(g)})" for g in r["paths"]))) for r in rules]


def gate(path: str) -> tuple[bool, set[str]]:
    """(runs everything, the tests the rules add) for a change to path alone, as hecaton's testscope reads the rules."""
    hit = [r for r, rx in matchers if rx.match(path)]
    return any(r.get("full") for r in hit), {t for r in hit for t in r.get("tests", [])}


roots = [r for r in st.covered_roots(doc, tests) if not st.WILD.search(r) and r not in tree.files]
probes = sorted(set(tree.all) | {f"{r}/{d}{name}" for r in roots for d in ("", "zz-new/deeper/")
                                 for name in ("zz.yaml", "zz.md", "zz.sh", "zz.json", "Dockerfile", "zz.txt")})
# The regexes are full_match itself: every glob of the map against one probe in fifty, and against paths built from
# the glob itself (each ** as none, one and two directories, each * as a name), which it matches.
globs = sorted({g for r in rules for g in r["paths"]})
sample = probes[::50]


def built(g: str) -> list[str]:
    return [re.sub(r"\*", "x", g.replace("/**/", d).replace("/**", d.rstrip("/") + "/y").replace("**", "z"))
            for d in ("/", "/a/", "/a/b/")]


pairs = [(path, g) for g in globs for path in sample + built(g)]
differ = [(path, g) for path, g in pairs if bool(re.match(translate(g), path)) != pathlib.PurePosixPath(path).full_match(g)]
check(f"the compiled globs match as PurePosixPath.full_match does ({len(pairs)} pairs of path and glob)",
      not differ, str(differ[:5]))
missed: list[str] = []
not_full: list[str] = []
selected_paths = 0
for path in probes:
    mode, why = st.select(doc, "offline", [path], tests, None, tree.submodules, doc)
    runs_all, got = gate(path)
    if path.startswith("verify/test_") and path.removeprefix("verify/") in tests:
        got.add(path)  # the gate runs a changed test file itself
    if mode == "full":
        if any("full list" in w for ws in why.values() for w in ws) and not runs_all:
            not_full.append(path)
        continue
    selected_paths += 1
    lack = {f"verify/{n}" for n in why} - got
    if lack and not runs_all:
        missed.append(f"{path}: {', '.join(sorted(lack)[:4])}" + (f" and {len(lack) - 4} more" if len(lack) > 4 else ""))
check(f"select() scopes a change to most of the {len(probes)} paths probed ({selected_paths})",
      selected_paths > len(probes) // 2)
check(f"for each of them the rules add every offline test select() runs ({len(missed)} short)", not missed,
      "\n        ".join(missed[:15]))
check(f"a path in the map's full list runs everything ({len(not_full)} do not)", not not_full, str(not_full[:10]))

print()
print("== a new file gives the same map before and after its git add (#1396) ==")
# Run 20624 (#1391) ran `write` before `git add` of a new tool, and widen() wrote it as a directory too
# (`verify/deck_renumber.py/**`), which this file then failed on once the tool was tracked. A scratch repo, under the
# run's own TMPDIR, holds a tracked test, a new tool, a new directory and an ignored file; the map is written with the
# tool untracked and again with it added, and the two must be equal.
with tempfile.TemporaryDirectory() as t:
    root = pathlib.Path(t)

    def git(*args: str) -> None:
        subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, text=True,
                       env={**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull})

    git("init", "-q")
    (root / "verify" / "newdir").mkdir(parents=True)
    (root / "verify" / "test_tool.py").write_text("# reads the tool\n", encoding="utf-8")
    (root / ".gitignore").write_text("verify/ignored.py\n", encoding="utf-8")
    git("add", "-A")
    (root / "verify" / "tool.py").write_text("# a new tool\n", encoding="utf-8")
    (root / "verify" / "newdir" / "a.py").write_text("# a new directory's file\n", encoding="utf-8")
    (root / "verify" / "ignored.py").write_text("# ignored\n", encoding="utf-8")
    scratch = {"full": [], "always": {}, "unread": [],
               "reads": {"test_tool.py": ["verify/tool.py", "verify/newdir", "verify/ignored.py"]}}
    one = {"test_tool.py": "offline"}
    before_tree = st.Tree(root)
    check("the scratch repo's tool is untracked and on disk, and its ignored file is not untracked",
          "verify/tool.py" not in before_tree.files and "verify/tool.py" in before_tree.untracked()
          and "verify/ignored.py" not in before_tree.untracked(), str(sorted(before_tree.untracked())))
    before = st.render_test_map(st.test_map(scratch, before_tree, one))
    git("add", "verify/tool.py", "verify/newdir/a.py")
    after = st.render_test_map(st.test_map(scratch, st.Tree(root), one))
    check("the map written before `git add` of a new file is the map written after it", before == after,
          "".join(difflib.unified_diff(before.splitlines(True), after.splitlines(True), "before", "after")))
    check("the new file is written as a file, with no /** glob under it",
          "verify/tool.py/**" not in after and "      - verify/tool.py\n" in after, after)
    check("a new directory and an ignored file still take everything under them",
          "verify/newdir/**" in before and "verify/ignored.py/**" in before, before)

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("verify/test-map.yaml holds the scope map for hecaton's tests gate.")
