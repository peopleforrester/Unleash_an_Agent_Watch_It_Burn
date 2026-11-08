# ABOUTME: Holds #1018's scoping: verify/scope-map.yaml's rules and bounds hold, a test it lacks still runs when it should,
# ABOUTME: and both runners, driven in a fixture repo, run only what a change touches, or everything.
"""Offline. scope_tests.py and the map it reads decide which tests a hecaton validation runs (#1018).

1. The map's rules hold (scope_tests.structural()). Its drift from the tests' sources (a test with no entry, an entry
   missing a path scope_tests.extract() finds) is printed, not failed on: select() reads every test's source and runs
   from the union, and a test without an entry, or with an empty one, still runs when what it reads changes. A run cut
   before a test landed on staging and rebased after sees that test without an entry through no edit of its own.
2. The two bounds hold: every file bootstrap_chart.source_files() reads for an Application source in
   gitops/bootstrap/apps, and every values file collector_render.value_files() names, is inside the paths the map
   bounds that helper by.
3. select() on the real map: a change to decisions.md alone runs its readers and the always tests and leaves the rest;
   a change to a runner, the map, a shared helper, or a path no entry covers runs everything; a changed test runs.
   A change to the map's rules runs everything, and one to a test's entry runs that test.
4. Both runners, copied into a fixture repo with four fixture tests (an offline and a tier test reading alpha/, the same
   two reading beta/): with HECATON_BASE_SHA on a base where only alpha/ changed, only alpha's tests run, and the tier's
   tools are fetched; where only an unread path changed, no tier test runs and nothing is fetched; where run-tests.sh
   or a path the map does not cover changed, everything runs; an edit to one test's map entry runs that test and one to
   the map's rules runs everything; a test added without an entry runs when its area changes; without
   HECATON_BASE_SHA everything runs; a base git does not have fails loudly.
"""
from __future__ import annotations

import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

REPO = pathlib.Path(__file__).resolve().parent.parent
VERIFY = REPO / "verify"
sys.path.insert(0, str(VERIFY))
import tf_plugin_cache  # noqa: E402

# The fixture runners' artifact root, outside the checkout and removed when this test exits.
ARTIFACTS = tf_plugin_cache.scratch("scope-tests-artifacts-")
sys.path.insert(0, str(VERIFY))
import scope_tests as st  # noqa: E402

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"\n        {detail[-3000:]}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


print("== the map's rules hold, and its drift from the tests' sources is shown, not failed on ==")
tree = st.Tree()
doc = st.load_map()
bad = st.structural(doc, tree)
check("the map's rules (full, unread, bounds, always) name what the repo has, and no test is in two lists", not bad,
      "\n".join(bad))
behind = st.drift(doc, tree)
print(f"  NOTE  the map is behind the tests' sources in {len(behind)} places; select reads those from source"
      + "".join(f"\n        {b}" for b in behind[:20]))
tests = st.discover()
check("the map has an entry for nearly every offline and tier test", len(tests) > 300
      and sum(1 for t in tests if t in doc["always"] or t in doc["reads"]) > len(tests) * 0.9, str(len(tests)))
check("test_scope_tests.py is in always, so every change runs it",
      "test_scope_tests.py" in doc["always"])
for f in ("verify/run-tests.sh", "verify/run-e2e-tools.sh", "verify/scope_tests.py", "verify/no-cloud.sh", "verify/no_cloud.py", "verify/ensure-submodules.sh", "verify/bootstrap_chart.py"):
    check(f"{f} is in full, so a change to it runs everything", any(st.covers(e, f) for e in doc["full"]))

print("== each bound holds for the repo data its helper builds paths from ==")
import bootstrap_chart as bc  # noqa: E402
import collector_render as cr  # noqa: E402
import yaml  # noqa: E402

bound = doc["bounds"]["verify/bootstrap_chart.py"]["paths"]
outside, sources = [], 0
for app_file in sorted(bc.APPS.glob("*.yaml")):
    for app in yaml.safe_load_all(app_file.read_text(encoding="utf-8")):
        if not app or app.get("kind") != "Application":
            continue
        spec = app["spec"]
        for source in ([spec["source"]] if spec.get("source") else spec.get("sources") or []):
            if source.get("repoURL") != bc.REPO_URL or "path" not in source:
                continue
            sources += 1
            for f in [bc.REPO / source["path"], *bc.source_files(source)]:
                rel = os.path.relpath(f, REPO)
                if not any(st.covers(e, rel) for e in bound):
                    outside.append(f"{app_file.name}: {rel}")
check(f"every file the {sources} Application sources of this repo hand Argo CD is inside bootstrap_chart.py's bound",
      sources > 20 and not outside, "\n".join(outside))
bound = doc["bounds"]["verify/collector_render.py"]["paths"]
named = [os.path.relpath(f, REPO) for app in cr.PROFILE_APP.values() for f in cr.value_files(app)]
check("every values file the collector Applications name is inside collector_render.py's bound",
      named and all(any(st.covers(e, f) for e in bound) for f in named), str(named))

print("== select() on the real map ==")
mode, why = st.select(doc, "offline", ["decisions.md"], tests)
readers = [t for t, ws in why.items() if any(w.startswith("reads decisions.md") for w in ws)]
check("a change to decisions.md alone is scoped", mode == "scoped", str(why)[:500])
check("it runs every test whose entry reads decisions.md, and every always test",
      set(readers) == {t for t, s in tests.items() if s == "offline" and t in doc["reads"]
                       and any(st.covers(e, "decisions.md") for e in doc["reads"][t])}
      and all(t in why for t, s in tests.items() if s == "offline" and t in doc["always"]), str(sorted(why)))
check("and leaves out a test that reads nothing it touched (test_stream.py)", "test_stream.py" not in why)
check("each test it runs says why", all(why.values()))
mode, why = st.select(doc, "offline", ["gitops/ai-layer/web/display.js"], tests)
check("a change to display.js runs test_stream.py, which reads it",
      mode == "scoped" and "test_stream.py" in why and why["test_stream.py"] == ["reads gitops/ai-layer/web/display.js"],
      str(why.get("test_stream.py")))
mode, why = st.select(doc, "offline", ["gitops/ai-layer/guard-proxy"], tests, None, tree.submodules)
check("a moved submodule pin runs test_stream.py, which reads guard-proxy, and test_docs_current.py, whose glob over "
      "the tree's Markdown reads the submodule's", mode == "scoped" and "test_stream.py" in why
      and "test_docs_current.py" in why, str(sorted(why))[:400])
mode, why = st.select(doc, "offline", ["verify/test_stream.py"], tests)
check("a changed test runs itself", mode == "scoped" and "the change edits it" in why.get("test_stream.py", []))
for path, reason in (("verify/run-tests.sh", "full list"), ("verify/run-e2e-tools.sh", "full list"),
                     ("verify/scope_tests.py", "full list"), ("verify/bootstrap_chart.py", "full list"),
                     ("a-path-nobody-has/notes.txt", "no entry in the map covers it")):
    for suite in ("offline", "tools"):
        mode, why = st.select(doc, suite, ["decisions.md", path], tests)
        check(f"a change to {path} runs every {suite} test ({reason})",
              mode == "full" and list(why) == [path] and reason in why[path][0], str(why))
import copy  # noqa: E402

for part, edit in (("full", lambda d: d["full"].append("README.md")), ("unread", lambda d: d["unread"].pop()),
                   ("bounds", lambda d: d["bounds"]["verify/collector_render.py"]["paths"].append("gitops"))):
    before = copy.deepcopy(doc)
    edit(before)
    mode, why = st.select(doc, "offline", ["decisions.md", st.MAP_REL], tests, before)
    check(f"a change to the map's {part} section runs everything",
          mode == "full" and why.get(st.MAP_REL) == [f"its {part} section changed"], str(why))
mode, why = st.select(doc, "offline", [], tests)
check("a change that touches no path runs everything, as there is nothing to scope it by",
      mode == "full" and "HECATON_BASE_SHA" in why, str(why))
mode, why = st.select(doc, "offline", [st.MAP_REL], tests, None)
check("a map the base did not have runs everything", mode == "full" and st.MAP_REL in why, str(why))
before = copy.deepcopy(doc)
before["reads"]["test_stream.py"] = before["reads"]["test_stream.py"] + ["decisions.md"]
mode, why = st.select(doc, "offline", ["decisions.md", st.MAP_REL], tests, before)
check("a change to one test's entry, even one dropping the very path the change edits, runs that test",
      mode == "scoped" and "the change edits its entry in the map" in why.get("test_stream.py", []), str(why)[:400])
check("and no test whose entry it left alone, beyond those the change selects anyway",
      not [t for t, ws in why.items() if "the change edits its entry in the map" in ws and t != "test_stream.py"])

print("== select() runs from the map and each test's source together ==")
stale = copy.deepcopy(doc)
del stale["reads"]["test_stream.py"]
stale["reads"]["test_two_domains.py"] = []
live, notes = st.effective(stale, tree, tests)
check("a test with no entry, and one whose entry misses its reads, are each noted",
      any(n.startswith("test_stream.py: no entry in the map") for n in notes)
      and any(n.startswith("test_two_domains.py: its entry misses") for n in notes), "\n".join(notes[:10]))
mode, why = st.select(stale, "offline", ["gitops/ai-layer/web/display.js"], tests, None, frozenset(), live)
check("a change to display.js still runs test_stream.py, though the map has no entry for it",
      mode == "scoped" and why.get("test_stream.py") == ["reads gitops/ai-layer/web/display.js"], str(why.get("test_stream.py")))
mode, why = st.select(stale, "offline", ["gitops/ai-layer/web-terminal/entrypoint.sh"], tests, None, frozenset(), live)
check("and a change to a path test_two_domains.py reads runs it, though its entry is empty",
      mode == "scoped" and "test_two_domains.py" in why, str(sorted(why))[:300])
live, notes = st.effective(doc, tree, tests)
check("on the committed map, the live map only adds to each entry",
      all(set(doc["reads"][t]) <= set(live["reads"].get(t, [])) or t in live["always"] for t in doc["reads"] if t in tests))

mode, why = st.select(doc, "tools", ["decisions.md"], tests)
check("the tier is scoped by the same map: a decisions.md change runs a few tier tests, not all of them",
      mode == "scoped" and 0 < len(why) < sum(1 for s in tests.values() if s == "tools") // 4, str(sorted(why)))

print("== both runners, in a fixture repo, run only what the change touches ==")
FIXTURE_TEST = ('import pathlib, sys\n'
                'REPO = pathlib.Path(__file__).resolve().parents[1]\n'
                'print("fixture read", (REPO / "{area}/data.txt").read_text().strip())\n')
TIER_HEAD = "# SUITE: e2e\n# E2E TIER: tools\n"
STUB = "#!/bin/sh\nexit 0\n"
NODE24 = '#!/bin/sh\ncase "$1" in -p) echo 24 ;; --version) echo v24.22.0 ;; esac\n'
FETCH_STUB = '#!/usr/bin/env bash\necho "fixture fetch ran" >>"$FETCH_LOG"\n'
FIXTURE_MAP = """full:
  - verify/run-tests.sh
  - verify/run-e2e-tools.sh
  - verify/scope_tests.py
  - verify/no-cloud.sh
  - verify/ensure-submodules.sh
  - verify/fetch-e2e-tools.sh
  - verify/playwright_browsers.py
unread:
  - notes.md
bounds: {}
always: {}
reads: {}
"""


def git(root: pathlib.Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, check=True).stdout.strip()


def fixture(tmp: pathlib.Path) -> tuple[pathlib.Path, str]:
    """A repo of two areas, four tests reading them, the real runners and scope_tests.py, and its map, committed."""
    root = tmp / "repo"
    v = root / "verify"
    v.mkdir(parents=True)
    for name in ("run-tests.sh", "run-e2e-tools.sh", "scope_tests.py", "no-cloud.sh", "ensure-submodules.sh",
                 "tf_plugin_cache.py", "artifact_cache.py"):
        shutil.copy2(VERIFY / name, v / name)
    (v / "fetch-e2e-tools.sh").write_text(FETCH_STUB)
    (v / "playwright_browsers.py").write_text("import sys\nsys.exit(0)\n")
    for area in ("alpha", "beta"):
        (root / area).mkdir()
        (root / area / "data.txt").write_text(f"{area} 1\n")
        (v / f"test_{area}.py").write_text(FIXTURE_TEST.format(area=area))
        (v / f"test_tier_{area}.py").write_text(TIER_HEAD + FIXTURE_TEST.format(area=area))
    (root / "notes.md").write_text("notes\n")
    (v / "scope-map.yaml").write_text(FIXTURE_MAP)
    git(tmp, "init", "-q", "-b", "main", str(root))
    git(root, "config", "user.email", "fixture@example.invalid")
    git(root, "config", "user.name", "fixture")
    git(root, "add", "-A")
    r = subprocess.run([sys.executable, str(v / "scope_tests.py"), "write"], capture_output=True, text=True)
    check(f"scope_tests.py write fills the fixture map (exit {r.returncode})", r.returncode == 0, r.stderr)
    r = subprocess.run([sys.executable, str(v / "scope_tests.py"), "check"], capture_output=True, text=True)
    check(f"and scope_tests.py check then finds it current (exit {r.returncode})", r.returncode == 0, r.stdout)
    written = (v / "scope-map.yaml").read_text()
    check("write gave each fixture test the area it reads",
          "  test_alpha.py:\n    - alpha/data.txt\n" in written and "  test_tier_beta.py:\n    - beta/data.txt\n" in written,
          written)
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "base")
    return root, git(root, "rev-parse", "HEAD")


def commit(root: pathlib.Path, rel: str, text: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(p.read_text() + text if p.exists() else text)
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", f"change {rel}")


def run(root: pathlib.Path, tmp: pathlib.Path, script: str, base: str | None) -> tuple[int, str]:
    bindir = tmp / "bin"
    bindir.mkdir(exist_ok=True)
    for name in ("curl", "tar", "unzip", "sha256sum", "xz", "uv", "jq", "openssl"):
        (bindir / name).write_text(STUB)
        (bindir / name).chmod(0o755)
    (bindir / "node").write_text(NODE24)
    (bindir / "node").chmod(0o755)
    log = tmp / "fetch.log"
    log.write_text("")
    # TMPDIR is the fixture's own (#909), and HOME too, so the runners' mktemp and Helm home stay inside it. The host
    # artifact cache, where run-e2e-tools.sh names the Terraform plugin cache, must sit outside every worktree, which
    # the fixture's temp directory may not (#1119): it gets a scratch root of its own outside the checkout. The
    # fixture has no .gitignore, so tf_plugin_cache.py's import of artifact_cache must leave no __pycache__ in it to
    # read as a change.
    env = {"PATH": f"{bindir}:{os.environ['PATH']}", "HOME": str(tmp), "TMPDIR": str(tmp), "FETCH_LOG": str(log),
           "WIB_ARTIFACT_CACHE": str(pathlib.Path(ARTIFACTS.name) / "artifacts"), "PYTHONDONTWRITEBYTECODE": "1"}
    if base is not None:
        env["HECATON_BASE_SHA"] = base
    r = subprocess.run(["bash", str(root / "verify" / script)], capture_output=True, text=True, env=env, timeout=300)
    return r.returncode, r.stdout + r.stderr + (f"\n[fetch log]\n{log.read_text()}" if log.read_text() else "")


def ran(out: str) -> set[str]:
    return {line[3:-3] for line in out.splitlines() if line.startswith("== ") and line.endswith(" ==")}


ALL_OFFLINE = {"test_alpha.py", "test_beta.py"}
ALL_TIER = {"test_tier_alpha.py", "test_tier_beta.py"}
ALL_E2E = ALL_TIER | {"run-tests.sh (the offline suite)"}

with tempfile.TemporaryDirectory() as t:
    tmp = pathlib.Path(t)
    root, base = fixture(tmp)

    rc, out = run(root, tmp, "run-tests.sh", None)
    check(f"without HECATON_BASE_SHA run-tests.sh runs every offline test (exit {rc})",
          rc == 0 and ran(out) == ALL_OFFLINE and "scope:" not in out, out)
    rc, out = run(root, tmp, "run-e2e-tools.sh", None)
    check(f"without HECATON_BASE_SHA run-e2e-tools.sh runs the offline suite and every tier test (exit {rc})",
          rc == 0 and ALL_E2E | ALL_OFFLINE <= ran(out) and "fixture fetch ran" in out
          and "3 checks ran (the offline suite and 2 tier tests)" in out, out)

    commit(root, "alpha/data.txt", "alpha 2\n")
    rc, out = run(root, tmp, "run-tests.sh", base)
    check(f"with only alpha/ changed, run-tests.sh runs test_alpha.py alone (exit {rc})",
          rc == 0 and ran(out) == {"test_alpha.py"}, out)
    check("it prints which it ran and why",
          "  test_alpha.py: reads alpha/data.txt" in out and "running 1 of 2 offline tests" in out
          and "1 of the 2 offline tests; the other 1 read nothing it touched" in out, out)
    rc, out = run(root, tmp, "run-e2e-tools.sh", base)
    check(f"run-e2e-tools.sh runs test_alpha.py and test_tier_alpha.py, and nothing of beta's (exit {rc})",
          rc == 0 and ran(out) == {"run-tests.sh (the offline suite)", "test_alpha.py", "test_tier_alpha.py"}, out)
    check("it fetched the tools, since a tier test runs, and says how many tier tests it left",
          "fixture fetch ran" in out and "1 of the 2 tier tests; the other 1 read nothing it touched" in out
          and "  test_tier_alpha.py: reads alpha/data.txt" in out, out)

    alpha_base = git(root, "rev-parse", "HEAD")
    commit(root, "notes.md", "more\n")
    rc, out = run(root, tmp, "run-e2e-tools.sh", alpha_base)
    check(f"with only an unread path changed, no test runs and the tools are not fetched (exit {rc})",
          rc == 0 and ran(out) == {"run-tests.sh (the offline suite)"} and "fixture fetch ran" not in out
          and "no tier test reads what the change touched" in out
          and "0 of the 2 tier tests" in out and "0 of the 2 offline tests" in out, out)

    notes_base = git(root, "rev-parse", "HEAD")
    commit(root, "verify/run-tests.sh", "# a comment\n")
    rc, out = run(root, tmp, "run-tests.sh", notes_base)
    check(f"with run-tests.sh changed, run-tests.sh runs every offline test (exit {rc})",
          rc == 0 and ran(out) == ALL_OFFLINE and "verify/run-tests.sh: it is in the map's full list" in out
          and "running every test" in out, out)
    rc, out = run(root, tmp, "run-e2e-tools.sh", notes_base)
    check(f"and run-e2e-tools.sh runs everything too (exit {rc})",
          rc == 0 and ALL_E2E | ALL_OFFLINE <= ran(out) and "fixture fetch ran" in out, out)

    runner_base = git(root, "rev-parse", "HEAD")
    commit(root, "gamma/new.txt", "new\n")
    rc, out = run(root, tmp, "run-e2e-tools.sh", runner_base)
    check(f"with a path the map does not cover changed, everything runs, naming the path (exit {rc})",
          rc == 0 and ALL_E2E | ALL_OFFLINE <= ran(out) and "gamma/new.txt: no entry in the map covers it" in out, out)

    commit(root, "verify/test_beta.py", "print('edited')\n")
    rc, out = run(root, tmp, "run-tests.sh", git(root, "rev-parse", "HEAD~1"))
    check(f"a changed test runs itself (exit {rc})",
          rc == 0 and ran(out) == {"test_beta.py"} and "  test_beta.py: the change edits it" in out, out)

    gamma_base = git(root, "rev-parse", "HEAD")
    commit(root, "verify/test_gamma.py", FIXTURE_TEST.format(area="alpha"))
    new_test_base = git(root, "rev-parse", "HEAD")
    commit(root, "alpha/data.txt", "alpha 3\n")
    rc, out = run(root, tmp, "run-tests.sh", new_test_base)
    check(f"a test added without a map entry still runs when what it reads changes (exit {rc})",
          rc == 0 and ran(out) == {"test_alpha.py", "test_gamma.py"}
          and "  test_gamma.py: no entry in the map; read from its source" in out
          and "  test_gamma.py: reads alpha/data.txt" in out, out)
    rc, out = run(root, tmp, "run-tests.sh", gamma_base)
    check(f"and runs itself in the change that adds it (exit {rc})",
          rc == 0 and "test_gamma.py" in ran(out) and "  test_gamma.py: the change edits it; reads alpha/data.txt" in out,
          out)

    fixture_map = root / "verify" / "scope-map.yaml"
    entry_base = git(root, "rev-parse", "HEAD")
    m = st.load_map(fixture_map)
    m["reads"]["test_beta.py"].append("notes.md")
    st.dump(m, fixture_map)
    commit(root, "verify/scope-map.yaml", "")
    rc, out = run(root, tmp, "run-tests.sh", entry_base)
    check(f"a change to one test's entry in the map runs that test alone (exit {rc})",
          rc == 0 and ran(out) == {"test_beta.py"} and "  test_beta.py: the change edits its entry in the map" in out,
          out)
    rules_base = git(root, "rev-parse", "HEAD")
    m["unread"].append("beta")
    st.dump(m, fixture_map)
    commit(root, "verify/scope-map.yaml", "")
    rc, out = run(root, tmp, "run-e2e-tools.sh", rules_base)
    check(f"a change to the map's rules runs everything, naming the section (exit {rc})",
          rc == 0 and ALL_E2E | ALL_OFFLINE <= ran(out) and "verify/scope-map.yaml: its unread section changed" in out,
          out)

    for script in ("run-tests.sh", "run-e2e-tools.sh"):
        rc, out = run(root, tmp, script, "0" * 40)
        check(f"{script} with a base git does not have fails, naming it (exit {rc})",
              rc == 1 and "SCOPE FAILED" in out and not ran(out) - {"run-tests.sh (the offline suite)"}, out)

print()
if failures:
    print(f"{len(failures)} FAILED")
    sys.exit(1)
print("ALL PASS")
