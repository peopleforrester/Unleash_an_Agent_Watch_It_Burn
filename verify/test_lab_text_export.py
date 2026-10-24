# ABOUTME: challenges/LAB-TEXT.md is the instructor copy of the student lab page; this fails when lab.html
# ABOUTME: has changed since the copy was made, and checks the export script stamps and refuses as it says.
"""Keeps the handout copy of the lab text from going stale without saying so (#419).

An instructor hands out challenges/LAB-TEXT.md instead of a 120 KB HTML file. A copy that is behind the
page is worse than no copy: it is the text someone reads to a room. So the copy carries the git blob id of
the lab.html it came from, and this compares that with lab.html as it is now. The commit is stamped too,
for a reader, but it is not what this checks: a squash or rebase rewrites the commit while the content,
and so the blob, stays the same.

Fix a failure here with `bash verify/export-lab-text.sh`, after committing lab.html.
"""
from __future__ import annotations

import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import lab_text  # noqa: E402

REPO = lab_text.REPO
LAB_BYTES = lab_text.LAB.read_bytes()
LAB = LAB_BYTES.decode("utf-8")
DOC = lab_text.OUT.read_text(encoding="utf-8")
SCRIPT = REPO / "verify/export-lab-text.sh"

failures: list[str] = []


def check(name: str, cond: bool) -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        failures.append(name)


def outside_code(md: str) -> str:
    """The Markdown with every fenced block removed, quote markers included."""
    out, fenced = [], False
    for line in md.splitlines():
        if re.match(r"^(> ?)*```", line):
            fenced = not fenced
            continue
        if not fenced:
            out.append(line)
    return "\n".join(out)


print("== the copy is not behind the page ==")
blob = lab_text.blob_id(LAB_BYTES)
check("the copy names the blob of lab.html as it is now (else: bash verify/export-lab-text.sh)",
      lab_text.stamp(DOC, "Source blob") == blob)
body = lab_text.body_of(DOC)
check("the copy's text is exactly what the exporter renders from lab.html today", body == lab_text.render(LAB))

print("== the header says when, from where, and which copy ==")
check("it is dated", re.fullmatch(r"20\d\d-[01]\d-[0-3]\d", lab_text.stamp(DOC, "Copied out")) is not None)
check("it names a full commit", re.fullmatch(r"[0-9a-f]{40}", lab_text.stamp(DOC, "Source commit")) is not None)
check("it says it is the student copy", "This is the **student** copy" in DOC)
check("it names the presenter copy", "gitops/ai-layer/web/brief.html" in DOC
      and (REPO / "gitops/ai-layer/web/brief.html").is_file())
check("it says it is generated, and by what", "do not edit by hand" in DOC and "verify/export-lab-text.sh" in DOC)

print("== the copy carries the lab, all of it ==")
headings = re.findall(r"^## (.+)$", body, re.M)
challenges = [h for h in headings if re.match(r"Challenge [1-8]:", h)]
check(f"the eight challenges, in order ({len(challenges)})",
      [int(h.split()[1].rstrip(":")) for h in challenges] == list(range(1, 9)))
page_titles = [re.sub(r"\s+", " ", m).strip() for m in re.findall(r'<div class="t">([^<]+)</div>', LAB)]
check(f"every step on the page has a heading ({len(page_titles)})",
      len(page_titles) == 11 and all(any(h.endswith(t) for h in headings) for t in page_titles))

tree = lab_text.parse(LAB)
guide = tree.find("section", "guide")


def walk(n):
    for c in n.children:
        if isinstance(c, lab_text.Node):
            yield c
            yield from walk(c)


nodes = list(walk(guide))
details = [n for n in nodes if n.tag == "details"]
check(f"every caret on the page is opened in the copy ({len(details)})",
      len(details) > 20 and body.count("**▸ ") == len(details))
# The attack prompts are the reason the copy exists. Each one is checked line by line, whitespace and all,
# so a prompt that was cut short or re-wrapped fails here.
prompts = [lab_text.raw_text(n).strip("\n").rstrip() for n in nodes
           if n.tag == "div" and "noterm" in n.classes and lab_text.raw_text(n).strip()]
quoted = re.sub(r"^(> ?)+", "", body, flags=re.M)
missing = [p[:50] for p in prompts if p not in quoted]
check(f"every prompt and pasted text is in the copy verbatim ({len(prompts)}; missing: {missing or 'none'})",
      len(prompts) >= 10 and not missing)
check("Challenge 4's measured prompt made it", "origin story for every single protein" in body)
check("both variants are there, each marked",
      lab_text.ONLY_COMMUNITY in body and lab_text.NOT_COMMUNITY in body
      and body.count("⤵") == len(re.findall(r"ends\]\*$", body, re.M)))

print("== nothing of the page's machinery leaks into the text ==")
prose = outside_code(body)
check("no HTML tag outside code", not re.search(r"(?<!\\)</?(?:p|div|details|summary|b|span|a|code)\b", prose))
# Each command box ends in a copy button; its label must not end up as the last word of the command.
check("no copy-button label", not re.search(r"copy\n(> ?)*```", body))
check("no script or style text", "function(" not in body and "{display" not in body)
check("no unfilled login box", "Your Datadog login" not in body)

print("== the export script stamps, and refuses an uncommitted page ==")
with tempfile.TemporaryDirectory() as tmp:
    t = pathlib.Path(tmp)
    for rel in ("verify/export-lab-text.sh", "verify/lab_text.py", "gitops/ai-layer/web/lab.html"):
        (t / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(REPO / rel, t / rel)
    (t / "challenges").mkdir()

    def git(*args: str) -> str:
        return subprocess.run(["git", "-C", tmp, "-c", "user.name=t", "-c", "user.email=t@t", *args],
                              capture_output=True, text=True, check=True).stdout.strip()

    def export(*args: str) -> subprocess.CompletedProcess:
        return subprocess.run(["bash", str(t / "verify/export-lab-text.sh"), *args],
                              capture_output=True, text=True)

    git("init", "-q")
    git("add", "-A")
    git("commit", "-qm", "lab")
    commit = git("log", "-1", "--format=%H", "--", "gitops/ai-layer/web/lab.html")
    r = export()
    out = t / "challenges/LAB-TEXT.md"
    made = out.read_text(encoding="utf-8") if out.exists() else ""
    wrote = r.returncode == 0 and lab_text.BODY_MARKER in made
    check(f"it writes challenges/LAB-TEXT.md (exit {r.returncode}) {r.stderr.strip()}", wrote)
    if not wrote:
        # Every check below reads the file it should have written; without one they can only crash.
        print(f"FAILED: the export script did not run\n{r.stdout}{r.stderr}")
        sys.exit(1)
    check("it stamps the commit that last changed lab.html", lab_text.stamp(made, "Source commit") == commit)
    check("it stamps the blob of the page it read", lab_text.stamp(made, "Source blob") == blob)
    check("what it writes matches the committed copy", lab_text.body_of(made) == body)

    stamped = made.replace(lab_text.stamp(made, "Copied out"), "2000-01-01", 1)
    out.write_text(stamped, encoding="utf-8")
    r = export()
    check("a second run on an unchanged page leaves the file and its date alone",
          r.returncode == 0 and "already current" in r.stdout and out.read_text(encoding="utf-8") == stamped)

    lab = t / "gitops/ai-layer/web/lab.html"
    lab.write_text(LAB.replace("Run up the bill", "Run up the tab"), encoding="utf-8")
    r = export()
    check("it refuses while lab.html has uncommitted changes",
          r.returncode != 0 and "uncommitted" in r.stderr and out.read_text(encoding="utf-8") == stamped)

    git("commit", "-qam", "edit")
    r = export()
    fresh = out.read_text(encoding="utf-8")
    check("once committed, it re-exports the changed page with a new stamp",
          r.returncode == 0 and "Challenge 4: Run up the tab" in fresh
          and lab_text.stamp(fresh, "Source commit") == git("rev-parse", "HEAD")
          and lab_text.stamp(fresh, "Copied out") != "2000-01-01")

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("The lab text copy is current.")
