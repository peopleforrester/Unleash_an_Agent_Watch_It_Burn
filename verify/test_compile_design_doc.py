# ABOUTME: Tests for scripts/compile-design-doc.py (#257): section order, source annotations, heading demotion, the
# ABOUTME: sha header, and --publish stopping on the American English check before the Doc is touched (#745). Offline.
import importlib.util
import pathlib
import sys
import tempfile
import traceback

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


def published_globs():
    lines = (REPO / ".american-english").read_text().splitlines()
    return [g for g in (line.split("#", 1)[0].strip() for line in lines) if g]


def test_opt_in_lists_exactly_what_the_doc_compiles():
    # The check reads the opt-in, the Doc reads SECTIONS: a section missing from the opt-in would publish unchecked.
    compiled = [path for _, path in cdd.SECTIONS] + [str(cdd.GLANCE.relative_to(REPO))]
    assert published_globs() == compiled, (published_globs(), compiled)
    for glob in published_globs():
        # A literal path to a Markdown file, so the checker reads every one and no glob matches nothing.
        assert not any(ch in glob for ch in "*?[") and glob.endswith(".md"), glob
        assert (REPO / glob).is_file(), glob


def fake_publish_tools(tmp_path, check_rc):
    """A checker that records its cwd and argv and exits check_rc, and a gdoc-update that records its call."""
    log = tmp_path / "calls.log"
    checker = tmp_path / "check_american_english.py"
    checker.write_text(
        "import os, sys\n"
        f"open({str(log)!r}, 'a').write('check ' + os.getcwd() + ' ' + ' '.join(sys.argv[1:]) + '\\n')\n"
        f"sys.exit({check_rc})\n")
    gdoc = tmp_path / "gdoc-update.py"
    gdoc.write_text(
        "import sys\n"
        f"open({str(log)!r}, 'a').write('gdoc ' + ' '.join(sys.argv[1:]) + '\\n')\n")
    return checker, gdoc, log


def run_main(tmp_path, checker, gdoc, *argv):
    saved = cdd.CHECKER, cdd.GDOC_UPDATE
    cdd.CHECKER, cdd.GDOC_UPDATE = checker, gdoc
    try:
        return cdd.main(["--out", str(tmp_path / "doc.md"), *argv])
    finally:
        cdd.CHECKER, cdd.GDOC_UPDATE = saved


def test_publish_stops_on_a_failed_check_before_the_doc(tmp_path):
    for check_rc in (1, 2):
        run_dir = tmp_path / f"rc{check_rc}"
        run_dir.mkdir()
        checker, gdoc, log = fake_publish_tools(run_dir, check_rc)
        assert run_main(run_dir, checker, gdoc, "--publish") == check_rc
        # Run once, from the repo root, with --published; gdoc-update never ran and nothing was compiled.
        assert log.read_text() == f"check {REPO} --published\n", log.read_text()
        assert not (run_dir / "doc.md").exists()


def test_publish_runs_the_check_first_then_updates_the_doc(tmp_path):
    checker, gdoc, log = fake_publish_tools(tmp_path, 0)
    assert run_main(tmp_path, checker, gdoc, "--publish") == 0
    assert log.read_text() == f"check {REPO} --published\ngdoc {cdd.DOC_ID}={tmp_path / 'doc.md'}\n", log.read_text()


def test_publish_without_the_checker_fails(tmp_path):
    _, gdoc, log = fake_publish_tools(tmp_path, 0)
    assert run_main(tmp_path, tmp_path / "absent.py", gdoc, "--publish") == 1
    assert not log.exists() and not (tmp_path / "doc.md").exists()


def test_compile_alone_does_not_run_the_check(tmp_path):
    checker, gdoc, log = fake_publish_tools(tmp_path, 1)
    assert run_main(tmp_path, checker, gdoc) == 0
    assert not log.exists() and (tmp_path / "doc.md").exists()


if __name__ == "__main__":
    # run-tests.sh runs each file with plain python3, so the tests run here; each gets its own tmp_path.
    failures = []
    tests = [(name, fn) for name, fn in list(globals().items()) if name.startswith("test_") and callable(fn)]
    for name, fn in tests:
        try:
            if "tmp_path" in fn.__code__.co_varnames[:fn.__code__.co_argcount]:
                with tempfile.TemporaryDirectory() as tmp:
                    fn(pathlib.Path(tmp))
            else:
                fn()
            print(f"  ok    {name}")
        except Exception:
            failures.append(name)
            print(f"  FAIL  {name}")
            traceback.print_exc()
    if failures:
        print(f"FAILED: {len(failures)} of {len(tests)} check(s): {', '.join(failures)}")
        sys.exit(1)
    print(f"All {len(tests)} compile-design-doc checks passed.")
