# ABOUTME: Runs the three rendered chat-page layout tests with Chromium reading DejaVu fonts alone, about 15% wider than
# ABOUTME: the Liberation Sans the tier draws in, so the page is held to fit a wide font, not only the host's (#1253).
# SUITE: e2e
# E2E TIER: tools (no cluster, no AWS: run-e2e-tools.sh runs it with the pinned tools, #572)
"""The chat page on a DejaVu-wide font (#1253).

#1252 made the CI tier draw the BurritoBot chat page (gitops/ai-layer/web/burritbot.html) in Liberation Sans, as
netcup does, since Tanjiro's runner had no Liberation Sans and its Arial fell to DejaVu Sans. That holds the tier to
one font. But #1047 meant the page to fit whatever fonts it gets, and a desktop Linux browser whose sans-serif is
DejaVu Sans drew three breaks: the 390 and 412px witch line in two lines with a 91px card header, the private bot's
bar 29px past a 768px screen, and the wide-font copy's icons past a 320px screen.

So this test writes a fonts.conf that reads the DejaVu fonts alone, the issue's own reproduction, and a second that
reads them with Noto Color Emoji, the set Tanjiro's runner had, and with each one as FONTCONFIG_FILE it runs
verify/test_chat_phone_screen_e2e.py, verify/test_chat_pane_overlap_e2e.py and verify/test_mobile_titles_e2e.py
whole. Each must pass. Before that, Chromium measures the page's own font stack under each set and it must draw as
DejaVu Sans, so a fonts.conf that fontconfig ignored cannot pass as a wide-font run.

The fonts are found where the host's fontconfig reads them: the directories of the FONTCONFIG_FILE in force (the one
verify/ci_chromium_libs.py writes on CI, with fonts-dejavu-core and fonts-noto-color-emoji unpacked when the host
lacks them) and the system's and the user's own. A host without DejaVuSans.ttf or NotoColorEmoji.ttf fails, naming
the file and the directories searched.

Needs uv and network on a cold host, as the three tests it runs do (verify/playwright_browsers.py).
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from ci_chromium_libs import font_dirs  # noqa: E402
from playwright_browsers import UV, ensure  # noqa: E402

HERE = pathlib.Path(__file__).resolve().parent
PAGE = HERE.parent / "gitops/ai-layer/web/burritbot.html"
TESTS = ["test_chat_phone_screen_e2e.py", "test_chat_pane_overlap_e2e.py", "test_mobile_titles_e2e.py"]
DEJAVU = "DejaVuSans.ttf"
EMOJI = "NotoColorEmoji.ttf"
# The page's body font stack, read from the page so the measure below follows it.
STACK_RULE = re.compile(r"\n  body\{font-family:([^;]+);")

failures: list[str] = []


def check(name: str, cond: bool, why: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  ({why})" if why and not cond else ""))
    if not cond:
        failures.append(name)


def fail(why: str) -> None:
    print(f"FAILED: {why}")
    sys.exit(1)


def search_dirs() -> list[pathlib.Path]:
    """The FONTCONFIG_FILE's <dir> entries, then the system's and the user's font directories, each once."""
    dirs: list[pathlib.Path] = []
    conf = os.environ.get("FONTCONFIG_FILE", "")
    if conf and pathlib.Path(conf).is_file():
        for d in re.findall(r"<dir[^>]*>([^<]+)</dir>", pathlib.Path(conf).read_text(encoding="utf-8")):
            dirs.append(pathlib.Path(os.path.expanduser(d.strip())))
    dirs.extend(font_dirs())
    seen: list[pathlib.Path] = []
    for d in dirs:
        if d not in seen:
            seen.append(d)
    return seen


def find(name: str, dirs: list[pathlib.Path]) -> pathlib.Path:
    for d in dirs:
        if d.is_dir():
            for p in sorted(d.rglob(name)):
                if p.is_file():
                    return p
    fail(f"no {name} under any font directory ({', '.join(map(str, dirs))}), so the wide-font run cannot be built; "
         "this is a failure, not a skip")
    raise AssertionError  # unreachable: fail() exits


def font_set(root: pathlib.Path, label: str, files: list[pathlib.Path]) -> pathlib.Path:
    """A directory linking exactly `files`, and a fonts.conf that reads it alone, with its own cache."""
    fonts = root / label / "fonts"
    fonts.mkdir(parents=True)
    for f in files:
        (fonts / f.name).symlink_to(f)
    conf = root / label / "fonts.conf"
    conf.write_text('<?xml version="1.0"?>\n<!DOCTYPE fontconfig SYSTEM "urn:fontconfig:fonts.dtd">\n<fontconfig>\n'
                    f"  <dir>{fonts}</dir>\n  <cachedir>{root / label / 'cache'}</cachedir>\n</fontconfig>\n",
                    encoding="utf-8")
    return conf


# Runs inside the uv environment: the canvas width of one line in the page's stack, in DejaVu Sans, and in a family
# no host has, so the stack is shown to draw as DejaVu Sans.
FACES = r"""
import json, sys
from playwright.sync_api import sync_playwright
stack = sys.argv[1]
JS = '''s => { const c = document.createElement('canvas').getContext('2d');
  const w = f => { c.font = '600 16px ' + f; return c.measureText('Get a new witch name, Wilhelmina').width; };
  return {stack: w(s), dejavu: w('"DejaVu Sans"'), none: w('"WIB No Such Family"')}; }'''
with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page()
    pg.set_content('<body></body>')
    print(json.dumps(pg.evaluate(JS, stack)))
    b.close()
"""

if shutil.which("uv") is None:
    fail("uv is not on PATH; this E2E check cannot run, which is a failure, not a skip")
if not PAGE.is_file():
    fail(f"{PAGE} is missing, so there is no page to render")
stack = STACK_RULE.search(PAGE.read_text(encoding="utf-8"))
if not stack:
    fail(f"{PAGE} has no '  body{{font-family:...;' rule, so the page's font stack cannot be measured")
for t in TESTS:
    if not (HERE / t).is_file():
        fail(f"{HERE / t} is missing, so it cannot be run on the wide font")
not_ready = ensure()
if not_ready:
    fail("Chromium cannot run; this is a failure, not a skip:\n" + "\n".join(f"  - {p}" for p in not_ready))

dirs = search_dirs()
dejavu = find(DEJAVU, dirs)
emoji = find(EMOJI, dirs)
dejavu_files = sorted(p for p in dejavu.parent.glob("DejaVu*") if p.is_file())
print(f"DejaVu fonts from {dejavu.parent}: {[p.name for p in dejavu_files]}; colour emoji {emoji}")

root = pathlib.Path(tempfile.mkdtemp(prefix="chat-wide-font-"))
try:
    SETS = [("DejaVu alone", font_set(root, "dejavu", dejavu_files)),
            ("DejaVu with colour emoji", font_set(root, "dejavu-emoji", [*dejavu_files, emoji]))]
    for label, conf in SETS:
        env = {**os.environ, "FONTCONFIG_FILE": str(conf)}
        print(f"== {label} ({conf}) ==")
        run = subprocess.run([*UV, "python", "-I", "-c", FACES, stack.group(1)], capture_output=True, text=True,
                             env=env)
        widths = json.loads(run.stdout.strip().splitlines()[-1]) if run.returncode == 0 and run.stdout.strip() else {}
        check(f"{label}: Chromium measures the font stack", bool(widths),
              f"exit {run.returncode}: {run.stdout[-500:]}{run.stderr[-500:]}")
        if not widths:
            continue
        check(f"{label}: the page's font stack ({stack.group(1)}) draws as DejaVu Sans",
              abs(widths["stack"] - widths["dejavu"]) < 0.01, f"widths {widths}")
        for t in TESTS:
            r = subprocess.run([sys.executable, str(HERE / t)], capture_output=True, text=True, env=env)
            out = r.stdout + r.stderr
            fails = [ln for ln in out.splitlines() if ln.strip().startswith("FAIL")]
            check(f"{label}: {t} passes", r.returncode == 0,
                  f"exit {r.returncode}; " + ("; ".join(x.strip() for x in fails[:12]) if fails else out[-1500:]))
finally:
    shutil.rmtree(root, ignore_errors=True)

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All wide-font chat-page checks passed.")
