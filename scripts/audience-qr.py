# ABOUTME: Writes the projector QR code for the room from publicUrl in gitops/ai-layer/web/event.js, so the
# ABOUTME: slide and the storefront's event knob can never name two different addresses (#451).
"""Render the audience QR code.

    python3 -m venv /tmp/qr && /tmp/qr/bin/pip install segno==1.6.6
    /tmp/qr/bin/python scripts/audience-qr.py            # rewrites the committed SVG
    /tmp/qr/bin/python scripts/audience-qr.py --check    # exit 1 if the committed SVG is stale

segno is pinned in decisions.md (2026-10-24, #451). It is pure Python and deterministic, so the same URL
always gives the same bytes, which is what lets verify/test_audience_qr_render.py compare them.

The code is built for a ballroom, not a phone held at arm's length: error correction M, the smallest
version that fits (fewer, bigger modules scan from further back), the standard four-module quiet zone,
and plain black on white. The SVG names the URL it encodes in <title> and <desc>, so the offline suite
can spot a stale code without decoding the image.
"""
from __future__ import annotations

import argparse
import io
import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
EVENT_JS = REPO / "gitops/ai-layer/web/event.js"
OUT = REPO / "facilitation/kubecon-na-2026-audience-qr.svg"


def public_url() -> str:
    m = re.search(r'^\s*publicUrl:\s*"([^"]*)"', EVENT_JS.read_text(encoding="utf-8"), re.M)
    if not m or not m.group(1).startswith("https://"):
        sys.exit(f"no https publicUrl in {EVENT_JS.relative_to(REPO)}; set it before rendering the QR")
    return m.group(1)


def render(url: str) -> bytes:
    import segno  # imported here so --help works without it

    qr = segno.make(url, error="m", micro=False)
    buf = io.BytesIO()
    qr.save(buf, kind="svg", scale=10, border=4, dark="#000000", light="#ffffff",
            title=url, desc=f"Projector QR for the audience page: {url}", xmldecl=False, nl=True)
    return buf.getvalue()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="fail if the committed SVG does not match")
    args = ap.parse_args()
    want = render(public_url())
    if args.check:
        if not OUT.exists() or OUT.read_bytes() != want:
            print(f"STALE: {OUT.relative_to(REPO)} does not encode the current publicUrl; rerun without --check")
            return 1
        print(f"{OUT.relative_to(REPO)} is current")
        return 0
    OUT.write_bytes(want)
    print(f"wrote {OUT.relative_to(REPO)} for {public_url()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
