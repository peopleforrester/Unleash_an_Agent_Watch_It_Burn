# ABOUTME: Holds #1018's scoping: verify/scope-map.yaml's rules and bounds hold, a test it lacks still runs when it should,
# ABOUTME: and both runners, driven in a fixture repo, run only what a change touches, or everything.
"""Offline. scope_tests.py and the map it reads decide which tests a hecaton validation runs (#1018).

1. The map's rules hold (scope_tests.structural()), and the map is current with the tests' sources
   (scope_tests.drift_items(): no test without an entry, no entry missing a path scope_tests.extract() finds). select()
   still reads every test's source and runs from the union, so a test the map is behind runs when it should; drift
   fails here because the gate's scoped selection is only as good as the map (#1190), and it had fallen 112 tests
   behind (#1189's 2800e073). `python3 verify/scope_tests.py write` brings it current. It fails on the drift a change
   made under that rule (scope_tests.owed()): a test or helper last changed in a commit whose scope_tests.py carries
   the rule, or edited and not yet committed. Drift from a commit made before the rule is named, not failed on: run
   18656's gate failed when a run cut before the rule landed a new read on staging between its validation and its
   rebase. A fixture repo holds owed()'s split.
2. The two bounds hold: every file bootstrap_chart.source_files() reads for an Application source in
   gitops/bootstrap/apps, and every values file collector_render.value_files() names, is inside the paths the map
   bounds that helper by. The render tests' bounds (#1078) hold too: every Application source path and $values/ file
   is inside the bound of each file that builds paths from them, and the installed_by scripts, the kubearmor chart
   source, the burn demo apps' manifests and the release value files each sit inside theirs. Each bounded file's
   count of run-time paths and git reads is pinned, so a new one fails until its bound is reread.
3. select() on the real map: a change to decisions.md alone runs its offline readers and the always tests and leaves
   the rest, and no tier test (#1190); a change to display.js runs its tier tests, not the whole tier;
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
import re
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


print("== the map's rules hold, and the map is current with the tests' sources ==")
tree = st.Tree()
doc = st.load_map()
bad = st.structural(doc, tree)
check("the map's rules (full, unread, bounds, always) name what the repo has, and no test is in two lists", not bad,
      "\n".join(bad))
behind, before_rule = st.owed(st.drift_items(doc, tree))
check("the map is current with every test's source a change under #1190's rule touched (run `python3 "
      "verify/scope_tests.py write`, review what it adds and commit it with the change); "
      f"{len(behind)} places behind", not behind, "\n".join(behind[:40]))
if before_rule:
    print(f"  NOTE  {len(before_rule)} places behind, each last changed in a commit made before #1190's rule; the next "
          "change to that test fails until `write` brings its entry current"
          + "".join(f"\n        {b}" for b in before_rule[:20]))

with tempfile.TemporaryDirectory() as t:
    fx = pathlib.Path(t)
    (fx / "verify").mkdir()
    def fx_git(*args: str) -> None:
        subprocess.run(["git", "-C", str(fx), *args], capture_output=True, text=True, check=True)
    fx_git("init", "-q")
    fx_git("config", "user.email", "fixture@example.invalid")
    fx_git("config", "user.name", "fixture")
    (fx / "verify" / "test_premap.py").write_text("print('before the map')\n")
    fx_git("add", "-A")
    fx_git("commit", "-q", "-m", "before scope_tests.py existed")
    (fx / "verify" / "scope_tests.py").write_text("# before the rule\n")
    (fx / "verify" / "test_old.py").write_text("print('old')\n")
    (fx / "verify" / "test_touched.py").write_text("print('touched')\n")
    (fx / "verify" / "test_dirty.py").write_text("print('dirty')\n")
    fx_git("add", "-A")
    fx_git("commit", "-q", "-m", "before the rule")
    (fx / "verify" / "scope_tests.py").write_text(f"# the rule\n{st.DRIFT_RULE}\n")
    (fx / "verify" / "test_touched.py").write_text("print('touched again')\n")
    fx_git("add", "-A")
    fx_git("commit", "-q", "-m", "under the rule")
    (fx / "verify" / "test_dirty.py").write_text("print('dirty, not committed')\n")
    items = [(f"verify/{n}", n) for n in ("test_premap.py", "test_old.py", "test_touched.py", "test_dirty.py", "test_gone.py")]
    fails, named = st.owed(items, root=fx)
    check("owed(): drift on a test last committed before the rule, or before scope_tests.py existed, is named, not "
          "failed on", named == ["test_premap.py", "test_old.py"],
          f"fails={fails} named={named}")
    check("owed(): drift on a test committed under the rule, edited and not committed, or git cannot place, fails",
          fails == ["test_touched.py", "test_dirty.py", "test_gone.py"], f"fails={fails} named={named}")
check("this scope_tests.py carries the rule owed() reads in each commit's copy",
      st.DRIFT_RULE in (VERIFY / "scope_tests.py").read_text())
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
# git_mirror.py (#1122) runs git cat-file on a mirror and ls-files for the gitlinks; its bound names what it reads of
# this tree, so a test that runs ensure-submodules.sh is not sent to always by those calls, and reads the bound instead.
bound = doc["bounds"]["verify/git_mirror.py"]["paths"]
check("git_mirror.py's bound is .gitmodules and every submodule path", sorted(bound)
      == sorted([".gitmodules", *tree.submodules]), f"{bound} against {sorted(tree.submodules)}")
unbounded = st.extract("verify/test_ensure_submodules.sh", tree, {})
bounded = st.extract("verify/test_ensure_submodules.sh", tree, doc["bounds"])
check("without the bound, git_mirror.py's git reads send a test that follows it to always",
      any(w.startswith("verify/git_mirror.py: it runs git") for w in unbounded.why_always), str(unbounded.why_always))
check("with it, they do not, and the test reads .gitmodules and both submodules", not bounded.why_always
      and set(bound) <= bounded.paths, f"{bounded.why_always} {sorted(bounded.paths)}")

# #1078: the render tests that build paths from what they read at run time, and the helpers they follow, are bounded
# here, so they move from always to reads. Each bound is held against the repo data the file builds its paths from.
# The render tests read every Application source in gitops/bootstrap/apps that names a path, whatever its repoURL,
# and each $values/ file a helm block names: every one of those must sit inside each such file's bound.
APP_SOURCE_BOUNDED = ("verify/app_render.py", "verify/test_datadog_log_services_render.py",
                      "verify/test_enforce_floor.py", "verify/test_image_registry_render.py")
app_paths: list[tuple[str, str]] = []
for app_file in sorted(bc.APPS.glob("*.yaml")):
    for app in yaml.safe_load_all(app_file.read_text(encoding="utf-8")):
        if not app or app.get("kind") != "Application":
            continue
        spec = app["spec"]
        for source in ([spec["source"]] if spec.get("source") else spec.get("sources") or []):
            if "path" in source:
                app_paths.append((app_file.name, source["path"]))
            for vf in (source.get("helm") or {}).get("valueFiles") or []:
                app_paths.append((app_file.name, vf.removeprefix("$values/")))
check("the Application sources name more than 20 paths and the otel-collector value files",
      len(app_paths) > 20 and any(p.startswith("gitops/otel-collector/") for _, p in app_paths), str(len(app_paths)))
for f in APP_SOURCE_BOUNDED:
    bound = doc["bounds"][f]["paths"]
    outside = [f"{a}: {p}" for a, p in app_paths if not any(st.covers(e, st._norm(p) or "..") for e in bound)]
    check(f"every Application source path and $values/ file is inside {f}'s bound", not outside, "\n".join(outside))
# test_enforce_floor.py renders the two releases deploy-full-idp.sh installs with REPO / "infra" / <values>, the
# value files its own release table names.
ef_values = sorted(set(re.findall(r'"([\w.-]+-values\.yaml)"', (VERIFY / "test_enforce_floor.py").read_text())))
bound = doc["bounds"]["verify/test_enforce_floor.py"]["paths"]
check("every infra values file test_enforce_floor.py's release table names is inside its bound",
      len(ef_values) >= 2 and all(any(st.covers(e, f"infra/{v}") for e in bound) for v in ef_values), str(ef_values))
# test_kubearmor_config_render.py renders the kubearmor app's source whose path is gitops/kubearmor-config.
kubearmor = [s.get("path") for d in yaml.safe_load_all((bc.APPS / "kubearmor.yaml").read_text(encoding="utf-8"))
             if d and d.get("kind") == "Application" for s in d["spec"].get("sources") or [] if "path" in s]
check("the kubearmor Application's path source is test_kubearmor_config_render.py's bound",
      kubearmor == doc["bounds"]["verify/test_kubearmor_config_render.py"]["paths"] == ["gitops/kubearmor-config"],
      str(kubearmor))
# test_bootstrap_chart_render.py builds REPO / f"gitops/manifests/{n}" for each demo app the burn profile lists.
demo = [n for n in bc.app_names("burn") if n.startswith("demo-app-")]
check("each burn demo app is a plain name with a directory in gitops/manifests, test_bootstrap_chart_render.py's bound",
      len(demo) == 5 and doc["bounds"]["verify/test_bootstrap_chart_render.py"]["paths"] == ["gitops/manifests"]
      and all("/" not in n and ".." not in n and f"gitops/manifests/{n}" in tree.dirs for n in demo), str(demo))
# test_platform_baseline.py reads REPO / c["installed_by"] for each component of platform-baseline.yaml.
baseline = yaml.safe_load((REPO / "platform-baseline.yaml").read_text(encoding="utf-8"))
installed = sorted({c["installed_by"] for c in baseline.get("components") or []
                    if isinstance(c, dict) and c.get("installed_by")})
bound = doc["bounds"]["verify/test_platform_baseline.py"]["paths"]
check("every installed_by script platform-baseline.yaml names is inside test_platform_baseline.py's bound",
      bool(installed) and all(any(st.covers(e, s) for e in bound) for s in installed), str(installed))
# sister_tree.py's git calls are a clone of the sister repo and ls-tree inside that clone (-C), none on this tree.
git_calls = re.findall(r'\["git",[^\]]*', (VERIFY / "sister_tree.py").read_text())
check("sister_tree.py runs git only to clone another repo and to read that clone, so its bound names no path",
      len(git_calls) == 2 and all('"clone"' in c or '"-C"' in c for c in git_calls)
      and doc["bounds"]["verify/sister_tree.py"]["paths"] == [], str(git_calls))
# A bound stands in for every run-time path and git read of its file, so one added later would hide behind it. Each
# bounded file's own count of those is pinned: a new one fails here until its bound is reread against it.
BOUNDED_READS = {"verify/app_render.py": 2, "verify/bootstrap_chart.py": 1, "verify/collector_render.py": 1,
                 "verify/git_mirror.py": 1, "verify/sister_tree.py": 1, "verify/test_bootstrap_chart_render.py": 1,
                 "verify/test_datadog_log_services_render.py": 4, "verify/test_enforce_floor.py": 3,
                 "verify/test_image_registry_render.py": 3, "verify/test_kubearmor_config_render.py": 1,
                 "verify/test_platform_baseline.py": 1}
check("every bound has its file's count of run-time paths and git reads pinned here",
      sorted(BOUNDED_READS) == sorted(doc["bounds"]), f"{sorted(BOUNDED_READS)} against {sorted(doc['bounds'])}")
for f, n in BOUNDED_READS.items():
    own = st._own(f, tree, {})[0].unbounded()
    check(f"{f} has the {n} run-time path(s) or git read(s) its bound was checked against", len(own) == n,
          f"{len(own)}: {own}; reread the bound in verify/scope-map.yaml and its check above, then pin the new count")
MOVED = ("test_bootstrap_chart_render.py", "test_chart_fetch.py", "test_datadog_log_services_render.py",
         "test_enforce_floor.py", "test_image_registry_render.py", "test_images_lock_render.py",
         "test_kubearmor_config_render.py", "test_no_docker_hub_render.py", "test_platform_baseline.py",
         "test_platform_baseline_sister.py", "test_sister_tree.py", "test_verify_harness.py")
check("with the bounds, the tests that were in always only for those reads are in reads",
      all(t in doc["reads"] and t not in doc["always"]
          and not st.extract(f"verify/{t}", tree, doc["bounds"]).unbounded() for t in MOVED),
      str([t for t in MOVED if t not in doc["reads"]]))
for suite in ("offline", "tools"):
    mode, why = st.select(doc, suite, ["scripts/compile-design-doc.py"], tests)
    check(f"a change to a script none of them reads runs none of them in the {suite} suite", mode == "scoped"
          and not set(MOVED) & set(why), str(sorted(set(MOVED) & set(why))))
mode, why = st.select(doc, "tools", ["gitops/bootstrap/apps/kubearmor.yaml"], tests)
check("a change to an app file runs the tier render tests that read it", mode == "scoped" and {
    "test_enforce_floor.py", "test_image_registry_render.py", "test_kubearmor_config_render.py",
    "test_datadog_log_services_render.py", "test_images_lock_render.py", "test_no_docker_hub_render.py"} <= set(why),
      str(sorted(why)))

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
check("a decisions.md change runs no tier test: the tier sets prose aside (#1190)", mode == "scoped" and not why,
      str(sorted(why)))
mode, why = st.select(doc, "tools", ["gitops/ai-layer/web/display.js"], tests)
check("the tier is scoped by the same map: a display.js change runs its render tests, not the whole tier",
      mode == "scoped" and "test_display_throttle_e2e.py" in why
      and len(why) < sum(1 for s in tests.values() if s == "tools") // 2, str(sorted(why)))

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
