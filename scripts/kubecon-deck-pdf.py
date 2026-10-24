# ABOUTME: Exports the KubeCon NA 2026 breakout deck (rounds-agenticburn's attendee.html) to the 16:9 PDF for
# ABOUTME: Sessionize, and holds that PDF to its source by sha256 so a stale PDF cannot be uploaded (#449).
"""Export the KubeCon deck to PDF, and check that an exported PDF still matches its source.

The deck is not built in this repo. It is the reveal.js page `attendee.html` in
peopleforrester/rounds-agenticburn (the run-of-show, "The deck (#449, rounds-agenticburn#38)"). This
script takes a checkout of that repo, prints the page in Playwright's Chromium through reveal.js's own
print mode (`?print-pdf`), and writes two files to facilitation/kubecon-na-2026-deck/:

- kubecon-na-2026-deck.pdf: the file the presenters upload to Sessionize;
- export.json: what it was exported from. The rounds-agenticburn commit, the sha256 of attendee.html and
  of every local file it references, the PDF's own sha256, page count and page size, and the text of
  each slide (speaker notes left out).

    uv run --no-project --with playwright==1.64.1 playwright install chromium
    uv run --no-project --with playwright==1.64.1 python -I scripts/kubecon-deck-pdf.py export <rounds-checkout>
    python3 scripts/kubecon-deck-pdf.py check <rounds-checkout>      # before uploading; exit 1 if stale

The export refuses, and writes nothing, when:

- the checkout is not peopleforrester/rounds-agenticburn, or attendee.html or anything it references has
  uncommitted changes (the recorded commit would not be what was printed);
- the first slide does not carry the talk's title from the run-of-show (that is the workshop deck);
- a slide names an abstract point or a challenge the run-of-show marks as cut;
- the page is not 16:9. reveal.js sizes the print page from the deck's own `width` and `height`
  (default 960 by 700), so the deck has to set a 16:9 size; this script does not override the deck's
  layout to get one. 1600 by 900 gives an exact 16:9 page after reveal's 4% margin;
- the page throws an error or a request fails (a slide printed without its image or its reveal.js).

`check` needs no browser. It recomputes the hashes against the checkout, re-reads the PDF, and scans the
recorded slide text against the cut tables as they stand now, so a point cut after the export also
makes the PDF stale.
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import html.parser
import json
import pathlib
import re
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
RUN_OF_SHOW = REPO / "facilitation/kubecon-na-2026-run-of-show.md"
OUT_DIR = REPO / "facilitation/kubecon-na-2026-deck"
PDF_NAME = "kubecon-na-2026-deck.pdf"
RECORD_NAME = "export.json"
DECK_REPO = "peopleforrester/rounds-agenticburn"
DECK_FILE = "attendee.html"
SESSIONIZE = "1249553"
PLAYWRIGHT = "1.64.1"

# reveal.js floors the print page to whole pixels after adding its margin, so a deck sized 1280 by 720
# prints 1331 by 748: 0.09% off 16:9. A deck that is not 16:9 at all (the default 960 by 700) is 23% off.
RATIO = 16 / 9
RATIO_TOLERANCE = 0.0025

# The words a slide would use to name each of the accepted abstract's nine points (the run-of-show,
# "Abstract points to segments"). Nothing here is checked until the run-of-show marks a point as cut.
ABSTRACT_TERMS = {
    1: ["burrito chain", "burrito-chain"],
    2: ["MCP"],
    3: ["IDP", "internal developer platform"],
    4: ["wide open", "wide-open", "hack it live", "hacks it live"],
    5: ["Kubernetes layers", "Kubernetes security layers"],
    6: ["pre-inference", "mid-inference", "prompt analysis"],
    7: ["observability"],
    8: ["selling burritos", "sell burritos", "nothing more", "on-topic"],
    9: ["weirdest off-topic", "off-topic question"],
}


class ExportError(Exception):
    """A reason the deck cannot be exported or the PDF is stale. The message says what to fix."""


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# --- the run-of-show: the talk title and the cut tables ---------------------------------------------------

def section(text: str, heading: str) -> str:
    """The body under a markdown heading, up to the next heading of the same or a higher level."""
    m = re.search(rf"^(#+) {re.escape(heading)}\s*$", text, re.M)
    if not m:
        raise ExportError(f"the run-of-show has no section '{heading}'")
    level = len(m.group(1))
    rest = text[m.end():]
    end = re.search(rf"^#{{1,{level}}} ", rest, re.M)
    return rest[: end.start()] if end else rest


def table(body: str) -> list[dict[str, str]]:
    """The first markdown table in body, as one dict per row keyed by the header cells."""
    lines = [ln.strip() for ln in body.splitlines() if ln.strip().startswith("|")]
    if len(lines) < 3:
        raise ExportError("expected a markdown table")
    cells = [[c.strip() for c in ln.strip("|").split("|")] for ln in lines]
    header, rows = cells[0], [r for r in cells[2:] if not all(re.fullmatch(r"-+", c) for c in r)]
    return [dict(zip(header, r)) for r in rows]


def is_cut(cell: str) -> bool:
    return re.match(r"\W*cut\b", cell, re.I) is not None


def talk_title(ros: str) -> str:
    """The quoted title under the run-of-show's H1, without its closing full stop."""
    m = re.search(r'^# .*\n+"([^"\n]+?)\.?"', ros, re.M)
    if not m:
        raise ExportError("the run-of-show does not quote the talk's title under its heading")
    return m.group(1)


def cut_items(ros: str) -> list[dict]:
    """Every abstract point and challenge the run-of-show marks as cut, with the words that would name it."""
    cuts = []
    for row in table(section(ros, "Abstract points to segments")):
        if is_cut(row.get("Delivered by the cut?", "")):
            n = int(row["#"])
            cuts.append({"label": f"abstract point {n} ({row['The abstract says']})", "terms": ABSTRACT_TERMS[n]})
    for row in table(section(ros, "Challenges shown live, and challenges cut")):
        if is_cut(row.get("In the cut?", "")):
            m = re.match(r"(C\d+)\s+(.*?)\s*(?:\(|$)", row["Challenge"])
            if not m:
                raise ExportError(f"cannot read the challenge cell '{row['Challenge']}'")
            cuts.append({"label": f"challenge {row['Challenge']}", "terms": [m.group(1), m.group(2)]})
    return cuts


def normalize(text: str) -> str:
    text = text.replace("’", "'").replace("‘", "'").replace("‑", "-").replace("‐", "-")
    return re.sub(r"\s+", " ", text).strip()


def term_in(term: str, text: str) -> bool:
    return re.search(rf"(?<![A-Za-z0-9]){re.escape(term)}(?![A-Za-z0-9])", text, re.I) is not None


def named_cuts(slide_text: list[str], cuts: list[dict]) -> list[str]:
    """One line per slide that names a cut item: 'slide 4 names challenge C8 ... ("C8")'."""
    found = []
    for i, text in enumerate(slide_text, 1):
        text = normalize(text)
        for cut in cuts:
            hits = [t for t in cut["terms"] if term_in(t, text)]
            if hits:
                found.append(f"slide {i} names {cut['label']} ({', '.join(repr(h) for h in hits)})")
    return found


# --- the source: attendee.html, what it references, and the checkout it came from -------------------------

class _Refs(html.parser.HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.refs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        for name, value in attrs:
            if name in ("src", "href", "poster", "data-src", "data-background-image") and value:
                self.refs.append(value)


def local_assets(html_text: str) -> list[str]:
    """The files the page loads from its own directory: not URLs, data: URIs or in-page anchors."""
    p = _Refs()
    p.feed(html_text)
    out = set()
    for ref in p.refs:
        if re.match(r"^([a-z][a-z0-9+.-]*:|//|#)", ref, re.I):
            continue
        out.add(ref.split("#")[0].split("?")[0])
    return sorted(out - {""})


def source_digest(checkout: pathlib.Path) -> dict:
    page = checkout / DECK_FILE
    if not page.is_file():
        raise ExportError(f"no {DECK_FILE} in {checkout}")
    data = page.read_bytes()
    assets = {}
    for rel in local_assets(data.decode("utf-8")):
        f = (checkout / rel).resolve()
        if checkout.resolve() not in f.parents or not f.is_file():
            raise ExportError(f"{DECK_FILE} references {rel}, which is not a file in the checkout")
        assets[rel] = sha256(f.read_bytes())
    return {"file": DECK_FILE, "sha256": sha256(data), "assets": assets}


def git(checkout: pathlib.Path, *args: str) -> str:
    r = subprocess.run(["git", "-C", str(checkout), *args], capture_output=True, text=True)
    if r.returncode != 0:
        raise ExportError(f"git {' '.join(args)} in {checkout} failed: {r.stderr.strip()}")
    return r.stdout.strip()


def checkout_state(checkout: pathlib.Path, files: list[str]) -> str:
    """The commit the source files are at. Refuses a checkout of another repo or with uncommitted changes."""
    origin = git(checkout, "remote", "get-url", "origin")
    if not re.search(rf"[:/]{re.escape(DECK_REPO)}(\.git)?/?$", origin):
        raise ExportError(f"{checkout} is a checkout of {origin}, not {DECK_REPO}")
    dirty = git(checkout, "status", "--porcelain", "--", *files)
    if dirty:
        raise ExportError(f"uncommitted changes in the deck's source, so no commit describes it:\n{dirty}")
    return git(checkout, "rev-parse", "HEAD")


# --- the PDF ----------------------------------------------------------------------------------------------

def pdf_pages(data: bytes) -> list[tuple[float, float]]:
    """Each page's MediaBox size in points. Chromium writes every page dictionary uncompressed."""
    if not data.startswith(b"%PDF-"):
        raise ExportError("not a PDF")
    pages = len(re.findall(rb"/Type\s*/Page(?![A-Za-z])", data))
    boxes = [tuple(float(v) for v in m.groups()) for m in
             re.finditer(rb"/MediaBox\s*\[\s*([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)\s*\]", data)]
    if pages == 0 or len(boxes) != pages:
        raise ExportError(f"cannot read the page sizes: {pages} pages, {len(boxes)} MediaBox entries")
    return [(x1 - x0, y1 - y0) for x0, y0, x1, y1 in boxes]


def is_16_9(width: float, height: float) -> bool:
    return height > 0 and abs(width / height - RATIO) / RATIO <= RATIO_TOLERANCE


def not_16_9(sizes: list[tuple[float, float]]) -> list[str]:
    return [f"page {i} is {w:g} x {h:g} pt ({w / h:.4f}, not 16:9 = {RATIO:.4f})"
            for i, (w, h) in enumerate(sizes, 1) if not is_16_9(w, h)]


# --- check: is the PDF still what the source says ---------------------------------------------------------

def stale(record: dict, checkout: pathlib.Path, pdf: bytes, ros: str) -> list[str]:
    """Every reason the exported PDF no longer matches its source or the run-of-show. Empty means upload it."""
    problems = []
    src, now = record["source"], source_digest(checkout)
    if now["sha256"] != src["sha256"]:
        problems.append(f"{DECK_FILE} changed since the export (now {now['sha256'][:12]}, "
                        f"exported {src['sha256'][:12]} at {src['commit'][:12]})")
    for rel in sorted(set(src["assets"]) | set(now["assets"])):
        if src["assets"].get(rel) != now["assets"].get(rel):
            problems.append(f"{rel} changed, was added or was removed since the export")
    if sha256(pdf) != record["pdf"]["sha256"]:
        problems.append(f"{record['pdf']['file']} is not the file that was exported (its sha256 differs)")
    sizes = pdf_pages(pdf)
    if len(sizes) != record["pdf"]["pages"]:
        problems.append(f"the PDF has {len(sizes)} pages, the record says {record['pdf']['pages']}")
    problems += not_16_9(sizes)
    problems += named_cuts(record["slide_text"], cut_items(ros))
    return problems


# --- export: render the deck in Chromium ------------------------------------------------------------------

READY = """() => window.Reveal && Reveal.isReady() && document.querySelectorAll('.pdf-page').length > 0
  && [...document.images].every(i => i.complete)"""

# One entry per printed page, as rendered: innerText keeps the line breaks between blocks and leaves out
# what is not displayed, which is the speaker notes. reveal.js prints a page per fragment step, so every
# fragment is shown while the text is read, the steps of one slide read the same, and consecutive repeats
# are dropped to give one entry per slide. It runs after the PDF is printed, so the PDF never sees it.
SHOW_FRAGMENTS = (".reveal .slides .fragment "
                  "{ visibility: visible !important; opacity: 1 !important; transition: none !important; }")
SLIDE_TEXT = """() => [...document.querySelectorAll('.pdf-page')].map(p =>
  [...p.children].filter(e => !e.matches('.speaker-notes, .slide-number, .slide-background'))
    .map(e => e.innerText).join('\\n').replace(/\\s+/g, ' ').trim())"""


def render(page_path: pathlib.Path) -> tuple[bytes, list[str], int, str]:
    from playwright.sync_api import sync_playwright  # imported here so `check` and the tests need no browser

    errors: list[str] = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.on("pageerror", lambda e: errors.append(f"page error: {e}"))
        page.on("requestfailed", lambda r: errors.append(f"request failed: {r.url} ({r.failure})"))
        page.goto(page_path.as_uri() + "?print-pdf", wait_until="networkidle")
        page.wait_for_function(READY, timeout=60_000)
        page.evaluate("document.fonts.ready.then(() => true)")
        printed = page.evaluate("document.querySelectorAll('.pdf-page').length")
        pdf = page.pdf(prefer_css_page_size=True, print_background=True)
        page.add_style_tag(content=SHOW_FRAGMENTS)
        texts = page.evaluate(SLIDE_TEXT)
        version = browser.version
        browser.close()
    if errors:
        raise ExportError("the deck did not render cleanly:\n  " + "\n  ".join(errors))
    slides = [t for i, t in enumerate(texts) if i == 0 or t != texts[i - 1]]
    return pdf, slides, printed, version


def export(checkout: pathlib.Path, out_dir: pathlib.Path, ros: str) -> dict:
    digest = source_digest(checkout)
    commit = checkout_state(checkout, [DECK_FILE, *digest["assets"]])
    title = talk_title(ros)
    cuts = cut_items(ros)

    pdf, slides, printed, chromium = render(checkout / DECK_FILE)
    if not slides or not term_in(normalize(title), normalize(slides[0])):
        raise ExportError(f"the first slide does not carry the talk's title \"{title}\"; "
                          f"is the checkout on the KubeCon cut (rounds-agenticburn#38)?")
    sizes = pdf_pages(pdf)
    problems = named_cuts(slides, cuts)
    wrong_size = not_16_9(sizes)
    if wrong_size:
        # Every page is the same size, so one line says it; the fix is in the deck, not here.
        problems.append(f"{wrong_size[0]} ({len(wrong_size)} of {len(sizes)} pages): set the deck's "
                        "Reveal.initialize width and height to 16:9, e.g. 1600 and 900")
    if len(sizes) != printed:
        problems.append(f"reveal.js laid out {printed} pages, the PDF has {len(sizes)}")
    if problems:
        raise ExportError("not exported:\n  " + "\n  ".join(problems))

    record = {
        "talk": title,
        "sessionize": SESSIONIZE,
        "source": {"repo": DECK_REPO, "commit": commit, **digest},
        "pdf": {"file": PDF_NAME, "sha256": sha256(pdf), "pages": len(sizes), "page_size_pt": list(sizes[0])},
        "cut_checked": [c["label"] for c in cuts],
        "slide_text": slides,
        "exported_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "renderer": {"playwright": PLAYWRIGHT, "chromium": chromium},
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / PDF_NAME).write_bytes(pdf)
    (out_dir / RECORD_NAME).write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return record


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("command", choices=["export", "check"])
    ap.add_argument("checkout", type=pathlib.Path, help="a checkout of peopleforrester/rounds-agenticburn")
    ap.add_argument("--out", type=pathlib.Path, default=OUT_DIR, help="where the PDF and export.json live")
    args = ap.parse_args()
    ros = RUN_OF_SHOW.read_text(encoding="utf-8")
    try:
        if args.command == "export":
            rec = export(args.checkout, args.out, ros)
            print(f"exported {rec['pdf']['pages']} pages from {DECK_REPO}@{rec['source']['commit'][:12]} "
                  f"to {args.out / PDF_NAME}")
            return 0
        record_path = args.out / RECORD_NAME
        if not record_path.is_file():
            raise ExportError(f"no {record_path}: the deck has not been exported")
        record = json.loads(record_path.read_text(encoding="utf-8"))
        problems = stale(record, args.checkout, (args.out / record["pdf"]["file"]).read_bytes(), ros)
        if problems:
            raise ExportError("STALE, do not upload:\n  " + "\n  ".join(problems))
        print(f"{record['pdf']['file']} matches {DECK_REPO}@{record['source']['commit'][:12]}; upload it")
        return 0
    except ExportError as e:
        print(f"FAILED: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
