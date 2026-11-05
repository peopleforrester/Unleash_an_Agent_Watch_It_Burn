# ABOUTME: Opens the KubeCon screenshots deck from disk in headless Chrome with the network cut off (#452) and steps through
# ABOUTME: it: every committed shot loads, every missing one is a MISSING card naming its file, and nothing is fetched.
# SUITE: e2e
# E2E TIER: tools (no cluster, no AWS: run-e2e-tools.sh runs it with the pinned tools, #572)
"""The deck is for the case where nothing live works, so this opens it the way a presenter will: a file:// URL, no
network. Chromium, through the playwright pinned in verify/playwright_browsers.py, presses the right arrow through
every slide and reports what each one shows. Every request that is not file:// is aborted and counted.

Two decks are stepped through. One is built here in a temporary directory from a manifest this test writes, with one
PNG this test draws and one it leaves out, so the checks own their inputs. The other is the committed deck, held to
the committed manifest and the PNGs on disk.

Needs uv, and network on the first run (playwright_browsers.ensure() installs a missing browser). A missing tool is
a failure, not a skip.
"""
from __future__ import annotations

import importlib.util
import json
import pathlib
import shutil
import struct
import subprocess
import sys
import tempfile
import zlib

import yaml

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "verify"))
from playwright_browsers import UV, ensure  # noqa: E402

FALLBACK = REPO / "facilitation/kubecon-na-2026/fallback"
failures: list[str] = []


def check(name: str, cond: bool, why: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  ({why})" if why and not cond else ""))
    if not cond:
        failures.append(name)


spec = importlib.util.spec_from_file_location("check_fallback_assets", REPO / "scripts/check-fallback-assets.py")
cfa = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cfa)


def png(width: int, height: int) -> bytes:
    """A plain RGB PNG of the given size, drawn here so the test owns it."""
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    rows = b"".join(b"\x00" + b"\x80\x20\xa0" * width for _ in range(height))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))


if shutil.which("uv") is None:
    print("FAILED: uv is not on PATH; this E2E check cannot run, which is a failure, not a skip")
    sys.exit(1)
not_ready = ensure()
if not_ready:
    print("FAILED: " + "; ".join(not_ready))
    sys.exit(1)

# Runs inside the uv environment: steps through each deck it is given and prints, per deck, what every slide showed.
STEP = r"""
import json, sys
from playwright.sync_api import sync_playwright
out = []
with sync_playwright() as p:
    b = p.chromium.launch()
    for url, slides in json.loads(sys.argv[1]):
        page = b.new_page()
        fetched = []
        def gate(route):
            if route.request.url.startswith("file://"):
                route.continue_()
            else:
                fetched.append(route.request.url)
                route.abort()
        page.route("**/*", gate)
        page.goto(url)
        seen = []
        for n in range(slides):
            if n:
                page.keyboard.press("ArrowRight")
            page.wait_for_function("() => { const i = document.querySelector('#slide img');"
                                   " return !i || i.complete; }", timeout=10_000)
            page.wait_for_timeout(100)
            seen.append(page.evaluate('''() => {
                const img = document.querySelector('#slide img'), miss = document.querySelector('#slide .missing');
                return {num: document.getElementById('num').textContent, seg: document.getElementById('seg').textContent,
                        title: (document.querySelector('#slide .title h1') || {}).textContent || '',
                        cap: (document.getElementById('cap') || {}).textContent || '',
                        width: img ? img.naturalWidth : 0, missing: miss ? miss.textContent : ''};
            }'''))
        page.keyboard.press("ArrowRight")
        last = page.evaluate("() => document.getElementById('num').textContent")
        out.append({"slides": seen, "after_last": last, "fetched": fetched})
        page.close()
    b.close()
print(json.dumps(out))
"""

with tempfile.TemporaryDirectory() as td:
    base = pathlib.Path(td)
    (base / "screenshots").mkdir()
    shutil.copy(FALLBACK / "screenshots/deck.html", base / "screenshots/deck.html")
    manifest = base / "assets.yaml"
    manifest.write_text(yaml.safe_dump({
        "version": 1, "deck": "screenshots/deck.html",
        "segments": [{"segment": 1, "title": "The first segment"}, {"segment": 2, "title": "The second segment"}],
        "screenshots": [
            {"segment": 1, "file": "screenshots/01-1-drawn.png", "caption": "A shot that is on disk.",
             "capture": {"by_hand": "drawn by the test"}},
            {"segment": 2, "file": "screenshots/02-1-absent.png", "caption": "A shot that is not.",
             "capture": {"by_hand": "left out by the test"}}]}), encoding="utf-8")
    (base / "screenshots/01-1-drawn.png").write_bytes(png(64, 36))
    cfa.write_deck(manifest)

    doc = cfa.load(FALLBACK / "assets.yaml")
    committed = [(s["file"], (FALLBACK / s["file"]).is_file()) for s in doc["screenshots"]]
    jobs = [((base / "screenshots/deck.html").as_uri(), 3), ((FALLBACK / doc["deck"]).as_uri(), 1 + len(committed))]
    run = subprocess.run([*UV, "python", "-I", "-c", STEP, json.dumps(jobs)], capture_output=True, text=True, timeout=300)
if run.returncode != 0:
    print(f"FAILED: the browser run exited {run.returncode}: {run.stderr[-600:]}")
    sys.exit(1)
built, real = json.loads(run.stdout.strip().splitlines()[-1])

print("== a deck built from a manifest this test wrote ==")
title, drawn, absent = built["slides"]
check("the first slide is the title, with the session's name", title["title"] == "BurritoBot Said Let's Dance, the Platform Said No"
      and title["num"] == "1 / 3", str(title))
check("a shot on disk loads, at its own size", drawn["width"] == 64 and not drawn["missing"], str(drawn))
check("its slide names the segment by the title --write-deck wrote, and shows its caption",
      drawn["seg"] == "Segment 1: The first segment" and drawn["cap"] == "A shot that is on disk.", str(drawn))
check("a shot that is not on disk is a MISSING card naming the file", absent["missing"] == "MISSING: screenshots/02-1-absent.png"
      and absent["seg"] == "Segment 2: The second segment", str(absent))
check("the right arrow stops at the last slide", built["after_last"] == "3 / 3", built["after_last"])
check("nothing is fetched from the network", built["fetched"] == [], str(built["fetched"]))

print("== the committed deck, against the committed manifest and the PNGs on disk ==")
shots = real["slides"][1:]
check("one slide per shot in assets.yaml, after the title", len(shots) == len(committed), f"{len(shots)} vs {len(committed)}")
for (file, present), slide in zip(committed, shots):
    check(f"{file} is on disk and loads as an image, with no MISSING card", present and slide["width"] > 0
          and not slide["missing"], str(slide))
check("the committed deck fetches nothing from the network", real["fetched"] == [], str(real["fetched"]))

if failures:
    print(f"\nFAILED: {len(failures)}")
    sys.exit(1)
print("\nFALLBACK DECK GREEN")
