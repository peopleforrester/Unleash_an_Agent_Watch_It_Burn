# ABOUTME: Holds scripts/kubecon-deck-pdf.py's rules without a browser: the cut tables it reads, the words it
# ABOUTME: refuses, the 16:9 page check, and the sha256 hold that makes a stale Sessionize PDF fail (#449).
"""The offline half of the KubeCon deck export (#449). The Chromium half is test_kubecon_deck_pdf_e2e.py.

The deck is rounds-agenticburn's attendee.html; this repo holds the export and the hold. Checked here:

- the run-of-show's title and both cut tables parse, so the export reads them rather than a copy;
- every one of the nine abstract points has words to refuse, so cutting any point is enforced;
- a cut point or challenge named on a slide is caught, on word boundaries, and an uncut one is not;
- the page check takes reveal.js's floored 16:9 page and refuses the default 960 by 700;
- the hold: against a throwaway git repo, an unchanged source passes and a changed attendee.html, a
  changed image, a swapped PDF, or a point cut after the export each make it stale;
- the export refuses a checkout of another repo or one with uncommitted changes to the deck.
"""
from __future__ import annotations

import importlib.util
import pathlib
import subprocess
import sys
import tempfile

REPO = pathlib.Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("kubecon_deck_pdf", REPO / "scripts/kubecon-deck-pdf.py")
k = importlib.util.module_from_spec(spec)
spec.loader.exec_module(k)
ROS = k.RUN_OF_SHOW.read_text(encoding="utf-8")

failures: list[str] = []


def check(name: str, cond: bool, why: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  ({why})" if why and not cond else ""))
    if not cond:
        failures.append(name)


def fake_pdf(pages: int, w: float, h: float) -> bytes:
    """Enough of a PDF for pdf_pages(): one uncompressed page dictionary per page, as Chromium writes them."""
    body = b"".join(b"%d 0 obj\n<</Type /Page\n/MediaBox [0 0 %g %g]>>\nendobj\n" % (i + 3, w, h)
                    for i in range(pages))
    return b"%PDF-1.4\n1 0 obj\n<</Type /Pages /Count " + str(pages).encode() + b">>\nendobj\n" + body


def sh(cwd: pathlib.Path, *args: str) -> None:
    subprocess.run(args, cwd=cwd, check=True, capture_output=True)


print("== the run-of-show is what the export reads ==")
check("the talk title is read from the run-of-show",
      k.talk_title(ROS) == "BurritoBot Said Let's Dance, the Platform Said No", k.talk_title(ROS))
points = k.table(k.section(ROS, "Abstract points to segments"))
check("the abstract table has the nine points", [r["#"] for r in points] == [str(n) for n in range(1, 10)])
check("every row of it has a 'Delivered by the cut?' cell", all("Delivered by the cut?" in r for r in points))
challenges = k.table(k.section(ROS, "Challenges shown live, and challenges cut"))
check("the challenge table has C1 to C8", [r["Challenge"].split()[0] for r in challenges] ==
      [f"C{n}" for n in range(1, 9)])
cuts = k.cut_items(ROS)
c8 = [c for c in cuts if c["label"].startswith("challenge C8")]
check("C8 is cut, and its number and name are refused",
      len(c8) == 1 and c8[0]["terms"] == ["C8", "service-account token theft"], str(cuts))
check("C4, narrated only, is not treated as cut", not any("C4" in c["label"] for c in cuts))
check("every abstract point has words to refuse", sorted(k.ABSTRACT_TERMS) == list(range(1, 10))
      and all(k.ABSTRACT_TERMS[n] for n in range(1, 10)))

marked = ROS.replace("| **At risk.**", "| **Cut** with Whitney's agreement. Was at risk.", 1)
point8 = [c for c in k.cut_items(marked) if c["label"].startswith("abstract point 8")]
check("a point the run-of-show marks Cut is picked up with its words",
      len(point8) == 1 and "sell burritos" in point8[0]["terms"], str(point8))

print("== naming a cut item on a slide ==")
slides = ["BurritoBot Said Let's Dance", "Next: C8 steals the token", "C80 is not a challenge",
          "We Sell Burritos. Nothing more."]
check("C8 on a slide is caught", k.named_cuts(slides, cuts) == ["slide 2 names challenge C8 service-account "
                                                                "token theft (scoped Role) ('C8')"],
      str(k.named_cuts(slides, cuts)))
check("a cut point's words are caught across case and spacing",
      any(h.startswith("slide 4 names abstract point 8") for h in k.named_cuts(slides, point8)))
check("an uncut point names nothing", k.named_cuts(slides, []) == [])
check("curly apostrophes match the title", k.term_in(k.normalize(k.talk_title(ROS)),
                                                      k.normalize("BurritoBot Said Let’s Dance, the Platform Said No")))

print("== the page is 16:9 ==")
check("1600 by 900 (1664 by 936 px printed, 1248 by 702 pt) is 16:9", k.is_16_9(1248, 702))
check("1280 by 720, floored to 1331 by 748 px, is within the tolerance", k.is_16_9(1331 * 0.75, 748 * 0.75))
check("reveal.js's default 960 by 700 (998 by 728 px) is refused", not k.is_16_9(749.04, 546))
check("4:3 is refused", not k.is_16_9(1024, 768))
check("pdf_pages reads each page's MediaBox", k.pdf_pages(fake_pdf(3, 1248, 702)) == [(1248, 702)] * 3)
try:
    k.pdf_pages(b"<html>")
    check("a file that is not a PDF is refused", False)
except k.ExportError:
    check("a file that is not a PDF is refused", True)

print("== local assets ==")
html_text = ('<link rel="icon" href="burrito-icon.png"><link href="https://cdn.example/reveal.css">'
             '<img src="diagram.png?v=2"><img src="data:image/png;base64,AA"><a href="#/3">x</a>'
             '<section data-background-image="bg.png"></section><a href="mailto:x@y">m</a>')
check("only the page's own files are hashed", k.local_assets(html_text) == ["bg.png", "burrito-icon.png",
                                                                            "diagram.png"],
      str(k.local_assets(html_text)))

print("== the hold: a stale source or PDF fails the check ==")
with tempfile.TemporaryDirectory() as tmp:
    co = pathlib.Path(tmp) / "rounds-agenticburn"
    co.mkdir()
    (co / "attendee.html").write_text('<section><h1>Title</h1><img src="slide.png"></section>', encoding="utf-8")
    (co / "slide.png").write_bytes(b"png-one")
    sh(co, "git", "init", "-q")
    sh(co, "git", "remote", "add", "origin", "git@github.com:peopleforrester/rounds-agenticburn.git")
    sh(co, "git", "add", ".")
    sh(co, "git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false", "commit", "-q", "-m", "deck")

    digest = k.source_digest(co)
    commit = k.checkout_state(co, ["attendee.html", *digest["assets"]])
    check("the checkout's commit is recorded", len(commit) == 40)
    pdf = fake_pdf(2, 1248, 702)
    record = {"source": {"repo": k.DECK_REPO, "commit": commit, **digest},
              "pdf": {"file": k.PDF_NAME, "sha256": k.sha256(pdf), "pages": 2, "page_size_pt": [1248, 702]},
              "slide_text": ["BurritoBot Said Let's Dance, the Platform Said No", "C5 leaks the sauce"]}
    check("an unchanged source and PDF pass", k.stale(record, co, pdf, ROS) == [], str(k.stale(record, co, pdf, ROS)))
    check("a different PDF fails", any("sha256 differs" in p for p in k.stale(record, co, fake_pdf(2, 1248, 701), ROS)))
    check("a PDF that is not 16:9 fails", any("not 16:9" in p for p in
                                               k.stale({**record, "pdf": {**record["pdf"],
                                                        "sha256": k.sha256(fake_pdf(2, 749, 546))}},
                                                       co, fake_pdf(2, 749, 546), ROS)))
    check("a point cut after the export fails", any("abstract point 8" in p for p in
                                                    k.stale({**record, "slide_text": ["Sell burritos"]}, co, pdf, marked)))

    (co / "slide.png").write_bytes(b"png-two")
    check("a changed image fails", any("slide.png changed" in p for p in k.stale(record, co, pdf, ROS)))
    try:
        k.checkout_state(co, ["attendee.html", "slide.png"])
        check("the export refuses uncommitted changes to the deck", False)
    except k.ExportError as e:
        check("the export refuses uncommitted changes to the deck", "uncommitted" in str(e))
    sh(co, "git", "checkout", "-q", "--", "slide.png")

    (co / "attendee.html").write_text('<section><h1>Title v2</h1><img src="slide.png"></section>', encoding="utf-8")
    check("a changed attendee.html fails", any("attendee.html changed" in p for p in k.stale(record, co, pdf, ROS)))
    sh(co, "git", "checkout", "-q", "--", "attendee.html")

    sh(co, "git", "remote", "set-url", "origin", "https://github.com/someone/rounds-agenticburn-fork.git")
    try:
        k.checkout_state(co, ["attendee.html"])
        check("the export refuses a checkout of another repo", False)
    except k.ExportError as e:
        check("the export refuses a checkout of another repo", "not peopleforrester/rounds-agenticburn" in str(e))

print("== the docs point at the export ==")
readme = (REPO / "facilitation/kubecon-na-2026-deck/README.md").read_text(encoding="utf-8")
check("the deck directory's README names the script and the check", "scripts/kubecon-deck-pdf.py" in readme
      and " check " in readme)
item = ROS[ROS.index("**The deck (#449"):]
check("the run-of-show's deck item names the export", "scripts/kubecon-deck-pdf.py" in item[:2000])

if failures:
    print(f"\nFAILED: {len(failures)} check(s)")
    sys.exit(1)
print("\nall KubeCon deck export checks passed")
