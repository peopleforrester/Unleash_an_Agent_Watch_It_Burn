# ABOUTME: Tests for scripts/compile-design-doc.py (#257): section order, source annotations, heading
# ABOUTME: demotion and the sha header on the generated markdown, entirely offline.
import importlib.util
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("cdd", REPO / "scripts/compile-design-doc.py")
cdd = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cdd)


def make_repo(tmp_path):
    for _, path in cdd.SECTIONS:
        f = tmp_path / path
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(f"# Title of {path}\n\nbody\n\n## Sub\n\ntext\n")
    (tmp_path / "docs/DESIGN-GLANCE.md").write_text("## The stack at a glance\n\nOne paragraph.\n")
    return tmp_path


def test_sections_in_order_with_source_lines_and_demoted_headings(tmp_path):
    md = cdd.compile_doc(make_repo(tmp_path), sha="abc1234", today="2026-09-06")
    heads = [line for line in md.splitlines() if line.startswith("# ")]
    assert heads[0] == "# " + cdd.TITLE
    assert heads[1:] == ["# " + t for t, _ in cdd.SECTIONS]
    for _, path in cdd.SECTIONS:
        assert f"_Source: `{path}`_" in md
        assert f"## Title of {path}" in md          # the file's own H1 became H2
        assert f"### Sub" in md                     # and its H2 became H3
        assert f"\n# Title of {path}" not in md      # no source H1 competes with the section headings


def test_header_carries_sha_date_and_contents(tmp_path):
    md = cdd.compile_doc(make_repo(tmp_path), sha="abc1234", today="2026-09-06")
    assert "_Compiled 2026-09-06 from the repository at staging abc1234" in md
    assert "## Contents" in md and "## The stack at a glance" in md
    for title, path in cdd.SECTIONS:
        assert f"- {title} (`{path}`)" in md


def test_real_repo_compiles_and_every_source_exists():
    for _, path in cdd.SECTIONS:
        assert (REPO / path).exists(), path
    md = cdd.compile_doc(REPO, sha="deadbee", today="2026-09-06")
    assert md.count("_Source: `") == len(cdd.SECTIONS)
    assert cdd.DOC_ID.startswith("18xDmj")
