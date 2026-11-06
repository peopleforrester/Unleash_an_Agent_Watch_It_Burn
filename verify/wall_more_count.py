# ABOUTME: The prompt wall's "+N more" check (#935): runs a wall page's own script on a fake clock and holds that the count
# ABOUTME: equals the prompts that arrived and were not shown since the last card, resets on each card, and is never hidden.
"""Shared by test_wall_more_count_e2e.py (the pinned copy of prompts-agenticburn's templates/wall.html, tools tier) and
test_wall_more_count_live.py (the wall the room reads, live suite). Not a test itself: the runners pick up only test_*.

The criterion is #927's third, for the wall's page: a visible "+N more" counter equals the number of prompts that
arrived and were not shown since the last card, and resets to 0 when a card appears. The page's inline script runs in
node through verify/wall-more-harness.js, which models app.py's server: numbered entries, snapshot(since), an /events
stream with its own cursor, and the /api/prompts polling fallback. It is not #933's verify/wall-clock-harness.js, which
answers every fetch with one fixed snapshot and reads no markup: this check needs the fallback to fetch what arrived
after its cursor, a replay of prompts the page holds, the #more element as the markup ships it, and an ordered log of
every answer the page was handed and every card it put up.

The scenario is a burst of 10, one prompt every 100 ms for 6 s from two clusters, a dropped stream whose 7 prompts the
polling fallback picks up, 3 more on the reopened stream, and a replay of 8 the page holds. After every step the #more
line must equal the count read off the log: prompts with a seq the page had not seen, delivered after the last card.
A replayed prompt is not a new arrival. Every prompt is generated, with its own text, and nothing is random.
"""
from __future__ import annotations

import json
import pathlib
import re
import shutil
import subprocess
import tempfile

REPO = pathlib.Path(__file__).resolve().parents[1]
HARNESS = REPO / "verify/wall-more-harness.js"
MORE = re.compile(r"^\+(\d+) more$")
HIDES = r"display\s*:\s*none|visibility\s*:\s*hidden|opacity\s*:\s*0(?:\.0*)?\s*(?:;|$|[\"'])"


def render_template(src: str) -> str:
    """app.py's wall_page() renders wall.html with pinned and interval; the page's script needs both filled in.

    A served page has neither left, so this changes nothing on it. Raises when another template expression is left."""
    src = re.sub(r"\{\{\s*pinned\s*\|\s*tojson\s*\}\}", '"attackme"', src)
    src = re.sub(r"\{\{\s*interval\s*\}\}", "3", src)
    left = re.findall(r"\{\{.*?\}\}|\{%.*?%\}", src)
    if left:
        raise RuntimeError(f"the page has template expressions this check does not render: {left[:3]}")
    return src


def markup_checks(page: str) -> list[tuple[str, bool, str]]:
    """The count is on the page, in the header, and nothing in the markup or the CSS hides it."""
    markup = re.sub(r"<script[\s\S]*?</script>", "", page)
    tag = re.search(r"<[a-zA-Z][\w-]*\b[^>]*\bid=\"more\"[^>]*>", markup)
    out = [('the page has a "+N more" element, id="more"', tag is not None,
            'no element with id="more" in the markup: this wall has no +N more count')]
    if tag is None:
        return out
    t = tag.group(0)
    header = re.search(r"<header\b[\s\S]*?</header>", markup)
    out.append(("it sits in the wall's header, which is always on screen", bool(header) and t in header.group(0), t))
    out.append(("it does not ship with the hidden attribute", not re.search(r"\shidden(\s|=|>|/)", t), t))
    out.append(("it carries no inline style that hides it", not re.search(HIDES, t), t))
    classes = (re.search(r"\bclass=\"([^\"]*)\"", t) or [None, ""])[1].split()
    style = "\n".join(re.findall(r"<style[^>]*>([\s\S]*?)</style>", page))
    style = re.sub(r"/\*[\s\S]*?\*/", "", style)
    own = r"(?:#more|\.(?:%s))(?:[.#:][\w:-]+)*" % "|".join(map(re.escape, classes or ["-"]))
    hiders = []
    for sel, decl in re.findall(r"([^{}]+)\{([^{}]*)\}", style):
        if any(re.fullmatch(own, s.strip()) for s in sel.split(",")) and re.search(HIDES, decl.strip()):
            hiders.append(f"{sel.strip()}{{{decl.strip()}}}")
    out.append(("no CSS rule for its classes or id hides it (display:none, visibility:hidden, opacity:0)", not hiders,
                "; ".join(hiders)))
    return out


def scenario() -> tuple[list[dict], list[dict]]:
    """The history the first /api/prompts answers with, and the steps after it."""
    n = 0

    def prompts(k: int, label: str, cluster: str = "attackme") -> list[dict]:
        nonlocal n
        out = []
        for _ in range(k):
            n += 1
            out.append({"cluster": cluster, "text": f"wall-935 {label} {n:04d}", "witch": f"Witch {n:04d}"})
        return out

    history = prompts(2, "history")
    steps: list[dict] = [{"sse": True}]                           # the stream's first frame: nothing new
    steps += [{"ingest": prompts(10, "burst")}, {"sse": True}]    # a burst of 10 in one frame
    steps += [{"advance": 50}] * 60                               # 3 s in 50 ms steps: the card goes up, the count resets
    for _ in range(60):                                           # one prompt every 100 ms for 6 s, from two clusters
        steps += [{"ingest": prompts(1, "flood", "attackme" if n % 3 else "bane")}, {"sse": True}, {"advance": 100}]
    steps += [{"advance": 100}] * 30                              # the flood drains
    steps += [{"drop": True}, {"ingest": prompts(7, "polled")}]   # the stream drops; the fallback polls these 7 up
    steps += [{"advance": 100}] * 120                             # 12 s: polls, a card, the stream reopens
    steps += [{"ingest": prompts(3, "after")}, {"sse": True}]     # 3 new on the reopened stream
    steps += [{"sse": {"since": n - 8}}]                          # a replay of 8 the page holds: not new arrivals
    steps += [{"advance": 100}] * 60                              # 6 s quiet
    return history, steps


BURST_FRAME = 3  # frame i+1 follows steps[i]: load, the first sse frame, the ingest, then the burst's frame


def run_harness(page: str) -> dict:
    if shutil.which("node") is None:
        raise RuntimeError("node is not on PATH; the wall's script runs in verify/wall-more-harness.js")
    if not HARNESS.is_file():
        raise RuntimeError(f"{HARNESS.relative_to(REPO)} is missing")
    history, steps = scenario()
    with tempfile.TemporaryDirectory() as tmp:
        pp = pathlib.Path(tmp) / "wall.html"
        pp.write_text(page, encoding="utf-8")
        sp = pathlib.Path(tmp) / "script.json"
        sp.write_text(json.dumps({"history": history, "steps": steps}), encoding="utf-8")
        out = subprocess.run(["node", str(HARNESS), str(pp), str(sp)], capture_output=True, text=True, timeout=300)
    if out.returncode != 0:
        raise RuntimeError(f"the harness exited {out.returncode}: {(out.stderr or out.stdout).strip()[:800]}")
    return json.loads(out.stdout.strip().splitlines()[-1])


def expected_at(log: list[dict], log_len: int) -> int:
    """Prompts with a seq the page had not seen, delivered after the last card it put up, in log order."""
    seen: set[int] = set()
    since = 0
    for ev in log[:log_len]:
        if "deliver" in ev:
            for s in ev["deliver"]:
                if s not in seen:
                    seen.add(s)
                    since += 1
        elif "card" in ev:
            since = 0
    return since


def frame_checks(got: dict) -> list[tuple[str, bool, str]]:
    """The count after every step of the scenario."""
    frames, log = got["frames"], got["log"]
    out = []
    shown = [MORE.match(f["more"] or "") for f in frames]
    out.append(('the count always reads "+N more"', all(shown),
                "; ".join(f"t={f['t']} {f['more']!r}" for f, m in zip(frames, shown) if not m)[:600]))
    out.append(("the count is never hidden (hidden attribute or display:none) in any frame",
                all(f["more_hidden"] is False and f["more_display"] != "none" for f in frames),
                "; ".join(f"t={f['t']} hidden={f['more_hidden']} display={f['more_display']!r}" for f in frames
                          if f["more_hidden"] is not False or f["more_display"] == "none")[:600]))
    out.append(("no reload happened (one boot id throughout)", frames[-1]["reloads"] == 0, f"{frames[-1]}"))

    wrong = []
    for f, m in zip(frames, shown):
        want = expected_at(log, f["log_len"])
        if not m or int(m.group(1)) != want:
            wrong.append(f"t={f['t']} after {f['step']}: shows {f['more']!r}, {want} arrived since the last card")
    out.append(("in every frame the count equals the prompts that arrived and were not shown since the last card",
                not wrong, f"{len(wrong)} of {len(frames)} frames wrong; first: " + "; ".join(wrong[:4])))

    burst = frames[BURST_FRAME]
    out.append(("the burst of 10 reads +10 more before its card goes up",
                burst["more"] == "+10 more" and burst["cards"] == 2, f"{burst}"))
    out.append(("the counter climbs to 10 or more, so it is not a constant",
                max((int(m.group(1)) for m in shown if m), default=0) >= 10, ""))

    resets, misses = 0, []
    for prev, f in zip(frames, frames[1:]):
        if f["cards"] > prev["cards"]:
            tail = log[prev["log_len"]:f["log_len"]]
            last_card = max(i for i, ev in enumerate(tail) if "card" in ev)
            if not any("deliver" in ev and ev["deliver"] for ev in tail[last_card + 1:]):
                resets += 1
                if f["more"] != "+0 more":
                    misses.append(f"t={f['t']}: a card went up and the count reads {f['more']!r}")
    out.append(("it resets to +0 more every time a card appears", not misses, "; ".join(misses[:4])))
    out.append(("the scenario put up enough cards to exercise the reset (at least 6)", resets >= 6, f"{resets} cards"))
    out.append(("it reads +0 more once the wall has gone quiet", frames[-1]["more"] == "+0 more", f"{frames[-1]}"))
    out.append(("the replay added no card and no count",
                frames[-61]["more"] == frames[-62]["more"] and frames[-61]["cards"] == frames[-62]["cards"],
                f"{frames[-62]} then {frames[-61]}"))
    return out


def criterion_checks(page: str) -> list[tuple[str, bool, str]]:
    """Every check, as (name, ok, detail). Stops after the markup when the page has no #more at all.

    Raises RuntimeError when the page cannot be run (no node, a template expression left, the harness failing)."""
    page = render_template(page)
    out = markup_checks(page)
    if not out[0][1]:
        return out
    return out + frame_checks(run_harness(page))
