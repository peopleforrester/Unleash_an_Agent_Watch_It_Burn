#!/usr/bin/env python3
# ABOUTME: Takes the KubeCon screenshots deck's shots on the live clusters (#452): sends each shot's prompt in the real
# ABOUTME: storefront in headless Chromium and saves the reply as the PNG facilitation/kubecon-na-2026/fallback/assets.yaml names.
"""Capture the worst-case screenshots deck from the live KubeCon clusters.

    python3 scripts/capture-fallback-screenshots.py \\
        --community https://attackme.burritobot.co --private https://burritobot-private.burritobot.co
    python3 scripts/capture-fallback-screenshots.py --community ... --private ... --shot 06-1-burritos-only
    python3 scripts/capture-fallback-screenshots.py --community ... --private ... --list

Both sites are required: a capture that guessed its cluster could screenshot the wrong one.

Each `chat` shot in assets.yaml names a prompts.yaml prompt and the cluster it is sent on. The script first reads
that cluster's /controls and refuses the shot unless every control the shot lists reads as listed, so a "guarded"
shot is never taken on an open bot or the other way round. It never flips a guard: a shot with a `toggle` waits
for a presenter (or a run, through the private terminal) to run that command first, and --shot takes it then.
The prompt goes in through the storefront's own composer, in a fresh browser context, so the shot is exactly what
a phone or the projector shows; a prompt with a thread sends the thread's earlier prompts first. A reply that is a
limit's refusal or empty fails the shot. `page` shots screenshot their URL. `by_hand` shots are listed, not taken.

Needs uv: Chromium comes through the playwright pinned in verify/playwright_browsers.py. Each chat shot is one or
two model calls on the cluster it names. Exit status: 0 every selected shot taken, 1 any shot failed or refused,
2 a usage error.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import pathlib
import shutil
import subprocess
import sys
import urllib.error
import urllib.request

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "verify"))
from playwright_browsers import UV, ensure  # noqa: E402

FALLBACK = REPO / "facilitation/kubecon-na-2026/fallback"
MANIFEST = FALLBACK / "assets.yaml"


def _load(name: str, path: pathlib.Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod  # dataclasses look their module up here while the class is being built
    spec.loader.exec_module(mod)
    return mod


rp = _load("replay_prompts", REPO / "scripts/replay-prompts.py")
cfa = _load("check_fallback_assets", REPO / "scripts/check-fallback-assets.py")

VIEWPORT = {"width": 1600, "height": 900}
REPLY_TIMEOUT_MS = int(rp.DEFAULT_TIMEOUT_S * 1000)

# Runs inside the uv environment with playwright. Reads the jobs as JSON on stdin and prints one JSON result per job.
BROWSER = r"""
import json, sys
from playwright.sync_api import sync_playwright

jobs = json.load(sys.stdin)
with sync_playwright() as p:
    browser = p.chromium.launch()
    for job in jobs:
        out = {"file": job["file"], "ok": False, "replies": [], "error": ""}
        ctx = browser.new_context(viewport=job["viewport"])
        page = ctx.new_page()
        try:
            page.goto(job["url"], wait_until="networkidle", timeout=90_000)
            for text in job.get("prompts", []):
                page.wait_for_function("() => { const i = document.getElementById('inp'); return i && !i.disabled; }",
                                       timeout=90_000)
                before = page.evaluate("() => document.querySelectorAll('#stream .msg.bot').length")
                page.fill("#inp", text)
                page.click("#sendbtn")
                page.wait_for_function(
                    "n => document.querySelectorAll('#stream .msg.bot').length > n && !document.querySelector('#stream .typing')",
                    arg=before, timeout=job["reply_timeout_ms"])
                out["replies"].append(page.evaluate(
                    "() => { const b = document.querySelectorAll('#stream .msg.bot'); return b[b.length - 1].innerText; }"))
            if job.get("prompts"):
                # The last prompt and the start of its reply at the top of the screen, as the projector reads it.
                page.evaluate("() => { const m = document.querySelectorAll('#stream .msg.me'); "
                              "m[m.length - 1].scrollIntoView({block: 'start'}); }")
                page.wait_for_timeout(500)
            page.screenshot(path=job["path"])
            out["ok"] = True
        except Exception as exc:
            out["error"] = f"{type(exc).__name__}: {exc}".splitlines()[0][:300]
        finally:
            ctx.close()
        print(json.dumps(out), flush=True)
    browser.close()
"""


def site(text: str) -> str:
    url = rp.chat_url(text)  # the same rule as the replay: an http(s) site root
    return url[: -len("/chat")]


def controls_mismatch(controls: dict, wanted: dict) -> list[str]:
    """Each `group.key` in wanted whose value in a /controls answer differs, as 'key is X, the shot needs Y'."""
    bad = []
    for key, want in wanted.items():
        group, name = key.split(".", 1)
        have = (controls.get(group) or {}).get(name)
        if have is not want:
            bad.append(f"{key} is {json.dumps(have)}, the shot needs {json.dumps(want)}")
    return bad


def read_controls(base: str) -> dict:
    req = urllib.request.Request(f"{base}/controls", headers={"User-Agent": rp.USER_AGENT, "Cache-Control": "no-store"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def thread_upto(prompts: list, pid: str) -> list:
    """The prompt and, when it has a thread, the thread's earlier prompts before it, in file order."""
    by_id = {p.id: p for p in prompts}
    target = by_id[pid]
    if not target.thread:
        return [target]
    chain = []
    for p in prompts:
        if p.thread == target.thread:
            chain.append(p)
        if p.id == pid:
            break
    return chain


def refused(reply: str) -> str:
    """Why a reply as the storefront shows it is not the bot answering, or ''."""
    text = reply.strip()
    if not text or text in ("…", rp.EMPTY_REPLY):
        return "the bot sent back an empty reply"
    for prefix, why in rp.PROXY_REFUSALS:
        if text.startswith(prefix):
            return why
    if text.startswith("BurritoBot's kitchen isn't answering") or text.startswith("Hmm, the kitchen isn't answering"):
        return "the kitchen did not answer (a 502 or 504 behind the console)"
    return ""


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--community", required=True, help="the community (public) site, e.g. https://attackme.burritobot.co")
    ap.add_argument("--private", required=True, help="the private site, e.g. https://burritobot-private.burritobot.co")
    ap.add_argument("--shot", action="append", default=[], metavar="NAME",
                    help="take only this shot (its file name, with or without .png); repeatable")
    ap.add_argument("--list", action="store_true", help="list every shot, how it is captured and its state; take none")
    args = ap.parse_args(argv)
    try:
        sites = {"community": site(args.community), "private": site(args.private)}
        doc = cfa.load(MANIFEST)
        prompts = rp.load_prompts(rp.DEFAULT_PROMPTS)
    except (ValueError, OSError, rp.PromptSetError) as exc:
        print(f"capture-fallback-screenshots: {exc}", file=sys.stderr)
        return 2
    known = {p.id for p in prompts}
    shots = doc["screenshots"]
    stems = {pathlib.Path(s["file"]).stem: s for s in shots}
    wanted = [w[:-4] if w.endswith(".png") else w for w in args.shot]
    unknown = [w for w in wanted if w not in stems]
    if unknown:
        print(f"capture-fallback-screenshots: no such shot: {', '.join(unknown)}", file=sys.stderr)
        return 2
    bad_prompts = [s["file"] for s in shots if "chat" in s["capture"] and s["capture"]["chat"] not in known]
    if bad_prompts:
        print(f"capture-fallback-screenshots: shot(s) name a prompt not in prompts.yaml: {', '.join(bad_prompts)}",
              file=sys.stderr)
        return 2
    selected = [stems[w] for w in wanted] if wanted else shots

    if args.list:
        for s in selected:
            cap = s["capture"]
            have = "taken" if (FALLBACK / s["file"]).is_file() else "missing"
            if "chat" in cap:
                how = f"chat {cap['chat']} on {cap['cluster']}" + (f" after {cap['toggle']}" if cap.get("toggle") else "")
            elif "page" in cap:
                how = f"page {cap['page']}"
            else:
                how = f"by hand: {cap['by_hand']}"
            print(f"  {have:<8} {s['file']:<44} {how}")
        return 0

    failed = 0
    jobs, meta = [], []
    cached: dict[str, dict] = {}
    for s in selected:
        cap = s["capture"]
        if "by_hand" in cap:
            print(f"  BY HAND  {s['file']}: {cap['by_hand']}")
            if wanted:
                failed += 1
            continue
        path = FALLBACK / s["file"]
        job = {"file": s["file"], "path": str(path), "viewport": VIEWPORT, "reply_timeout_ms": REPLY_TIMEOUT_MS}
        if "page" in cap:
            job["url"] = cap["page"]
        else:
            base = sites[cap["cluster"]]
            try:
                controls = cached.get(base) or read_controls(base)
            except (urllib.error.URLError, OSError, ValueError) as exc:
                print(f"  FAILED   {s['file']}: could not read {base}/controls: {exc}")
                failed += 1
                continue
            cached[base] = controls
            mismatch = controls_mismatch(controls, cap["controls"])
            if mismatch:
                how = f"; run {cap['toggle']} on the private terminal first" if cap.get("toggle") else ""
                print(f"  REFUSED  {s['file']}: on {base}, {'; '.join(mismatch)}{how}")
                failed += 1
                continue
            job["url"] = base + "/"
            job["prompts"] = [p.prompt for p in thread_upto(prompts, cap["chat"])]
        jobs.append(job)
        meta.append(s)
    if not jobs:
        return 1 if failed else 0

    if shutil.which("uv") is None:
        print("capture-fallback-screenshots: uv is not on PATH; Chromium comes through it", file=sys.stderr)
        return 1
    not_ready = ensure()
    if not_ready:
        print("capture-fallback-screenshots: " + "; ".join(not_ready), file=sys.stderr)
        return 1
    (FALLBACK / "screenshots").mkdir(exist_ok=True)
    r = subprocess.run([*UV, "python", "-c", BROWSER], input=json.dumps(jobs), capture_output=True, text=True)
    results, taken = {}, 0
    for line in r.stdout.splitlines():
        try:
            got = json.loads(line)
        except ValueError:
            continue
        results[got.get("file")] = got
    for s in meta:
        got = results.get(s["file"])
        if got is None:
            print(f"  FAILED   {s['file']}: the browser exited {r.returncode} before it: {' '.join(r.stderr.split())[:300]}")
            failed += 1
            continue
        why = got["error"] or next((refused(rep) for rep in got["replies"] if refused(rep)), "")
        if why or not got["ok"]:
            pathlib.Path(FALLBACK / s["file"]).unlink(missing_ok=True)
            print(f"  FAILED   {s['file']}: {why or 'not taken'}")
            failed += 1
            continue
        last = " ".join((got["replies"][-1] if got["replies"] else "").split())
        print(f"  ok       {s['file']}" + (f"  reply: {last[:200]}" if last else ""))
        taken += 1
    print(f"\n{taken} of {len(meta)} shot(s) taken; read each PNG before committing it: the script checks the bot "
          f"answered, not what it said")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
