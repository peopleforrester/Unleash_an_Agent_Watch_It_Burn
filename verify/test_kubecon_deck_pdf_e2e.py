# ABOUTME: Runs scripts/kubecon-deck-pdf.py in Playwright's Chromium against throwaway reveal.js decks: a 16:9
# ABOUTME: deck exports and checks clean, and a stale, non-16:9, cut-naming or untitled deck is refused (#449).
# SUITE: e2e
"""The rendered half of verify/test_kubecon_deck_pdf.py.

Each case is a small git repo shaped like a rounds-agenticburn checkout (origin set to that repo,
attendee.html loading reveal.js 6.0.2 from the CDN as the real deck does, one local image). The real deck
is not used: its export waits for the KubeCon cut to be final, and this has to prove the tool before then.

- a 1600 by 900 deck exports: one PDF page per page reveal.js laid out (a fragment step is a page), every
  page 1248 by 702 pt, the recorded slide text without the speaker notes (which name C8), and `check`
  passes; after a committed change to attendee.html, `check` fails;
- the reveal.js default size, a slide naming C8, a first slide without the talk title, and an image that
  fails to load are each refused, and no PDF is written.

Needs uv, network for playwright 1.64.1 and the reveal.js CDN, and Chromium (fetched by `playwright install
chromium` if not cached). A missing tool or a failed launch is a failure.
"""
from __future__ import annotations

import base64
import json
import pathlib
import shutil
import subprocess
import sys
import tempfile

REPO = pathlib.Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts/kubecon-deck-pdf.py"
PLAYWRIGHT = "playwright==1.64.1"
UV = ["uv", "run", "--no-project", "--with", PLAYWRIGHT]
TITLE = "BurritoBot Said Let’s Dance, the Platform Said No"
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8DwHwAFBQIAX8jx0gAAAABJRU5ErkJggg==")

failures: list[str] = []


def check(name: str, cond: bool, why: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  ({why})" if why and not cond else ""))
    if not cond:
        failures.append(name)


def deck(size: str = "width: 1600, height: 900,", title: str = TITLE, extra: str = "",
         image: str = "slide.png") -> str:
    return f"""<!doctype html>
<html><head><meta charset="utf-8">
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/reveal.js@6.0.2/dist/reveal.css">
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/reveal.js@6.0.2/dist/theme/black.css">
</head><body><div class="reveal"><div class="slides">
<section><h1>{title}</h1><p>KubeCon NA 2026</p></section>
<section><h2>Wide open</h2><p class="fragment">the room attacks it</p>
  <aside class="notes">Hand-off. C8 is cut from this session.</aside></section>
<section><h2>The platform</h2><img src="{image}" width="64" height="64">{extra}</section>
</div></div>
<script src="https://cdn.jsdelivr.net/npm/reveal.js@6.0.2/dist/reveal.js"></script>
<script src="https://cdn.jsdelivr.net/npm/reveal.js@6.0.2/dist/plugin/notes.js"></script>
<script>Reveal.initialize({{ {size} plugins: [ RevealNotes ], hash: true, transition: 'none' }});</script>
</body></html>
"""


def git(co: pathlib.Path, *args: str) -> None:
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false", *args],
                   cwd=co, check=True, capture_output=True)


def checkout(root: pathlib.Path, name: str, html: str) -> pathlib.Path:
    co = root / name
    co.mkdir()
    (co / "attendee.html").write_text(html, encoding="utf-8")
    (co / "slide.png").write_bytes(PNG)
    git(co, "init", "-q")
    git(co, "remote", "add", "origin", "https://github.com/peopleforrester/rounds-agenticburn.git")
    git(co, "add", ".")
    git(co, "commit", "-q", "-m", "deck")
    return co


def export(co: pathlib.Path, out: pathlib.Path) -> subprocess.CompletedProcess:
    return subprocess.run([*UV, "python", "-I", str(SCRIPT), "export", str(co), "--out", str(out)],
                          capture_output=True, text=True)


def check_cmd(co: pathlib.Path, out: pathlib.Path) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SCRIPT), "check", str(co), "--out", str(out)],
                          capture_output=True, text=True)


if shutil.which("uv") is None:
    print("FAILED: uv is not on PATH; this E2E check cannot run, which is a failure, not a skip")
    sys.exit(1)
install = subprocess.run([*UV, "playwright", "install", "chromium"], capture_output=True, text=True)
if install.returncode != 0:
    print(f"FAILED: `playwright install chromium` exited {install.returncode}:\n{install.stdout}{install.stderr}")
    sys.exit(1)

with tempfile.TemporaryDirectory() as tmp:
    root = pathlib.Path(tmp)

    print("== a 16:9 deck exports, and the check holds it to its source ==")
    co, out = checkout(root, "good", deck()), root / "out-good"
    r = export(co, out)
    check("the export succeeds", r.returncode == 0, (r.stdout + r.stderr).strip()[-800:])
    if r.returncode == 0:
        rec = json.loads((out / "export.json").read_text(encoding="utf-8"))
        pdf = (out / "kubecon-na-2026-deck.pdf").read_bytes()
        boxes = [b for b in pdf.split(b"/MediaBox")[1:]]
        check("four pages: title, the fragment slide twice, the image slide", rec["pdf"]["pages"] == 4
              and len(boxes) == 4, f"{rec['pdf']['pages']} pages, {len(boxes)} MediaBox")
        check("every page is 1248 by 702 pt", rec["pdf"]["page_size_pt"] == [1248, 702]
              and all(b.split(b"]")[0].split()[-2:] == [b"1248", b"702"] for b in boxes), str(rec["pdf"]))
        check("one slide-text entry per slide", len(rec["slide_text"]) == 3, str(rec["slide_text"]))
        check("speaker notes are not recorded as slide text", not any("C8" in t or "Hand-off" in t
                                                                      for t in rec["slide_text"]))
        check("the record names the source commit and the image's hash",
              len(rec["source"]["commit"]) == 40 and list(rec["source"]["assets"]) == ["slide.png"])
        c = check_cmd(co, out)
        check("check passes on the unchanged source", c.returncode == 0, (c.stdout + c.stderr).strip())
        (co / "attendee.html").write_text(deck(extra="<p>one more line</p>"), encoding="utf-8")
        git(co, "commit", "-q", "-am", "edit")
        c = check_cmd(co, out)
        check("check fails once attendee.html changes", c.returncode == 1 and "STALE" in c.stderr
              and "attendee.html changed" in c.stderr, (c.stdout + c.stderr).strip())

    print("== a deck the export must refuse ==")
    cases = [
        ("reveal.js's default size", deck(size=""), "not 16:9 = 1.7778"),
        ("a slide naming C8", deck(extra="<p>Then C8 takes the token</p>"), "names challenge C8"),
        ("a first slide without the talk title", deck(title="Watch It Burn"), "does not carry the talk's title"),
        ("an image that does not load", deck(image="https://deck-image.invalid/slide.png"), "request failed"),
    ]
    for i, (name, html, why) in enumerate(cases):
        co, out = checkout(root, f"bad{i}", html), root / f"out-bad{i}"
        r = export(co, out)
        check(f"{name} is refused", r.returncode == 1 and why in r.stderr, (r.stdout + r.stderr).strip()[-800:])
        check(f"{name}: no PDF is written", not (out / "kubecon-na-2026-deck.pdf").exists())

if failures:
    print(f"\nFAILED: {len(failures)} check(s)")
    sys.exit(1)
print("\nall KubeCon deck export E2E checks passed")
