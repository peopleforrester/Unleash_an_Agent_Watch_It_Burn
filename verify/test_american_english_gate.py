# ABOUTME: The repo opts in to the American English check for its published design doc, and the publish step
# ABOUTME: (compile-design-doc.py --publish) runs that check first and refuses to publish on a British form (#745).
"""Pins #745 (and its duplicates #780/#781).

scripts/compile-design-doc.py --publish compiles the SECTIONS docs and pushes them to a Google Doc, which
leaves the building. Per claude-config/rules/american-english.md a repo that publishes writing opts in with
a root .american-english listing the published paths, and its publish step runs
scripts/check_american_english.py --published from the repo root, stopping on a non-zero exit.

This half needs nothing but the tree. The run of the shared checker over the tree reads
~/repos/workflow/llm-coding-workflow, so it is test_american_english_tree.py in the E2E suite.
"""
from __future__ import annotations

import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
OPT_IN = REPO / ".american-english"
PUBLISH = (REPO / "scripts/compile-design-doc.py").read_text(encoding="utf-8")

failures: list[str] = []


def check(name: str, cond: bool, why: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  ({why})" if why and not cond else ""))
    if not cond:
        failures.append(name)


print("== the repo opts in, listing the published design-doc paths ==")
check("a root .american-english exists", OPT_IN.exists())
globs = [ln.strip() for ln in OPT_IN.read_text(encoding="utf-8").splitlines() if ln.strip()] if OPT_IN.exists() else []
check("it is not empty", len(globs) > 0)
check("every listed path exists in the tree", all((REPO / g).exists() for g in globs),
      ", ".join(g for g in globs if not (REPO / g).exists()))
# The published set is the compile script's SECTIONS content files, minus the internal decisions.md log.
import importlib.util  # noqa: E402
spec = importlib.util.spec_from_file_location("cdd", REPO / "scripts/compile-design-doc.py")
cdd = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cdd)
readable = {".md", ".mdx", ".txt", ".adoc", ".rst", ".html", ".htm"}
published = [p for _, p in cdd.SECTIONS if pathlib.Path(p).suffix in readable and p != "decisions.md"]
check("it covers the published SECTIONS docs (decisions.md stays internal)", set(globs) == set(published),
      f"opt-in {sorted(globs)} vs published {sorted(published)}")

print("== the publish step runs the check first, and stops on a non-zero exit ==")
checker_at = PUBLISH.find("check_american_english.py")      # the checker path, resolved into a `checker` var
gdoc_run_at = PUBLISH.find("str(GDOC_UPDATE)")               # the gdoc-update invocation that replaces the Doc
abort_at = PUBLISH.find("if rc != 0:")
check("--publish invokes check_american_english.py", checker_at != -1)
check("it passes --published", "--published" in PUBLISH)
check("the check runs BEFORE the Doc is replaced (gdoc-update)", 0 <= checker_at < gdoc_run_at)
check("a non-zero exit stops the publish before the Doc is replaced (returns the checker's code)",
      0 <= abort_at < gdoc_run_at and re.search(r"if rc != 0:\s*\n[^\n]*\n\s*return rc", PUBLISH) is not None)

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    sys.exit(1)
print("American English publish gate is wired and green.")
