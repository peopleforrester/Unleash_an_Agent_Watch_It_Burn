<!-- ABOUTME: Where the KubeCon NA 2026 breakout's Sessionize PDF and its export record live, and how to make
     ABOUTME: and check them. The slides themselves are in peopleforrester/rounds-agenticburn (#449). -->

# KubeCon NA 2026 deck: the Sessionize PDF

The slides for "BurritoBot Said Let's Dance, the Platform Said No" (Sessionize
1249553) are not written here. They are `attendee.html` in
`peopleforrester/rounds-agenticburn`, cut from
`facilitation/kubecon-na-2026-run-of-show.md` (rounds-agenticburn#38). This
directory holds the PDF made from them, for the upload:

- `kubecon-na-2026-deck.pdf`: the file to upload to Sessionize.
- `export.json`: what it was printed from. The rounds-agenticburn commit, the
  sha256 of `attendee.html` and of every image it loads, the PDF's sha256, page
  count and page size, and each slide's text (no speaker notes).

Neither file exists until the deck is final. The upload's due date is a speaker
obligation in conference-knowledge (`kubecon-na-2026`, `obligations`).

## Export

From this repo, with a clean, up-to-date checkout of rounds-agenticburn's `main`:

```
uv run --no-project --with playwright==1.64.1 playwright install chromium
uv run --no-project --with playwright==1.64.1 python -I scripts/kubecon-deck-pdf.py export <rounds-checkout>
```

It prints the deck through reveal.js's own print mode (`?print-pdf`) in
Playwright's Chromium and writes nothing if any of these hold:

- the checkout is not rounds-agenticburn, or the deck has uncommitted changes;
- the first slide is not the talk's title (the workshop deck);
- a slide names an abstract point or challenge the run-of-show marks as cut
  (today, C8);
- the page is not 16:9. reveal.js prints at the deck's own `width` and
  `height`; 1600 by 900 gives an exact 16:9 page;
- the page throws an error or a request fails.

Commit both files together.

## Before uploading

```
python3 scripts/kubecon-deck-pdf.py check <rounds-checkout>
```

It needs no browser. It fails, and says why, if `attendee.html` or any image
changed since the export, if the PDF is not the exported file, if a page is not
16:9, or if a slide names something the run-of-show has cut since. A failed
check means export again; do not upload the old PDF.
