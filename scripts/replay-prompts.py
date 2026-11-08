#!/usr/bin/env python3
# ABOUTME: Sends the KubeCon audience prompt set to a live BurritoBot /chat at a paced rate, standing in for
# ABOUTME: the room's phones when the venue network fails, and stops at the first prompt that is not delivered (#452).
"""Replay the recorded audience input for the KubeCon NA 2026 breakout.

In every segment of facilitation/kubecon-na-2026-run-of-show.md the room plays on the public bot from their
phones over the venue Wi-Fi. When that network cannot carry the room, a presenter runs this from a laptop on a
phone hotspot, and the bot gets the room's questions anyway: they land on the cluster, climb the cost counter,
and show on the prompt wall and the feed (/display), exactly as typed ones would.

    python3 scripts/replay-prompts.py --target https://attackme.burritobot.co --segment 1   # Night Before, segment 1
    python3 scripts/replay-prompts.py --target https://attackme.burritobot.co --segment 3   # the segment on stage
    python3 scripts/replay-prompts.py --target https://attackme.burritobot.co --dry-run     # no network

The target is required. A replay that guessed its cluster could spend the room's prompts on the wrong one.

Pacing. guard-proxy allows RATE_LIMIT_RPM (150) model-bound requests per sliding 60 seconds for the whole
cluster, and the presenters' own asks share that window. The replay sends one prompt at a time, waits for
the reply, and starts the next no sooner than --interval seconds after the last one started (default 6,
about ten a minute). Intervals that would take more than half the window are refused.

Stopping. The replay stops at the first prompt that was not delivered to the bot and answered by it:
a network or TLS error, a timeout, any status but 200, a body that is not the /chat reply shape, an empty
reply ("..." is guard-proxy's empty-reply placeholder), or one of the refusals that come back as HTTP 200
without calling the model (guard-proxy's rate limits, its cost cap and its budget guard, and the console
nginx's per-conversation limit). A guardrail blocking a prompt is not a failure: on the admin
cluster that is the demo working. A marker that does not appear is not a failure either: the model declines
sometimes, and challenges/PROMPT-CATALOG.md says what to send next.

Exit status: 0 every selected prompt delivered, 1 stopped at a failure, 2 a usage or prompt-set error.
"""
from __future__ import annotations

import argparse
import dataclasses
import http.client
import json
import pathlib
import re
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from typing import Callable

import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_PROMPTS = REPO / "facilitation/kubecon-na-2026/fallback/prompts.yaml"

# guard-proxy's RATE_LIMIT_RPM as deployed (gitops/ai-layer/resources.yaml; verify/test_replay_prompts.py holds the
# two together). One window for the whole cluster (#450); the replay may use at most half of it, so the
# presenters' own asks still get through.
GUARD_PROXY_RPM = 150
MIN_INTERVAL_S = 60.0 / (GUARD_PROXY_RPM / 2)
DEFAULT_INTERVAL_S = 6.0
# The console's nginx gives /chat 285 seconds (console.conf); wait a little longer so nginx's own 504 is
# what the replay reports, rather than a client timeout that hides which hop gave up.
DEFAULT_TIMEOUT_S = 300.0
TAGS = frozenset({"on-topic", "off-topic", "attack", "smoke"})
SEGMENTS = frozenset(range(1, 7))  # the run-of-show's six segments
EMPTY_REPLY = "..."
# The storefront sends a witch name, `<First> the <Creature>`, with every prompt; HC-666 names the Joker it
# deploys from it. guard-proxy drops a name of any other shape (_WITCH_NAME_RE in proxy.py).
WITCH_NAME_RE = r"[A-Z][a-z]{1,15} the [A-Z][a-z]{1,15}"
DEFAULT_WITCH = "Replay the Raven"
# These come back as HTTP 200 and guarded:true without calling the model. They are a limit refusing, not the
# bot answering, so the room's input did not land. Prefixes of the reply text in proxy.py (its two rate
# limits, its cost cap and its budget guard) and console.conf (nginx's per-conversation limit).
PROXY_REFUSALS = (
    ("Slow down, hungry traveler.", "a rate limit refused it (guard-proxy's window, or one conversation's)"),
    ("The kitchen is closed:", "guard-proxy's cost cap refused it: the cluster hit its spend cap"),
    ("The kitchen tab is frozen.", "guard-proxy's budget guard refused it: the conversation hit its budget"),
)
# Nova Pro opens many replies with a <thinking> block, which the storefront folds away under "model reasoning".
# The log and the marker read what the room reads.
THINKING_RE = re.compile(r"<thinking>.*?</thinking>", re.S)
USER_AGENT = "wib-replay-prompts/1 (Unleash_an_Agent_Watch_It_Burn#452)"


class PromptSetError(Exception):
    """The prompt file is missing, unreadable, or breaks a rule in its header."""


@dataclasses.dataclass(frozen=True)
class Prompt:
    id: str
    tags: tuple[str, ...]
    prompt: str
    expect: str
    marker: str | None = None
    segments: tuple[int, ...] = ()
    thread: str | None = None

    @property
    def conversation(self) -> str:
        """The session stem: the thread when the prompt has one, so a follow-up joins its conversation."""
        return self.thread or self.id


@dataclasses.dataclass
class Outcome:
    delivered: bool
    status: int | None
    reason: str = ""
    reply: str = ""
    guarded: bool = False
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    elapsed_s: float = 0.0


def load_prompts(path: pathlib.Path) -> list[Prompt]:
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise PromptSetError(f"cannot read {path}: {exc}") from exc
    if not isinstance(doc, dict) or doc.get("version") != 1 or not isinstance(doc.get("prompts"), list):
        raise PromptSetError(f"{path}: expected a mapping with version: 1 and a prompts: list")
    out: list[Prompt] = []
    seen: set[str] = set()
    for n, raw in enumerate(doc["prompts"], 1):
        where = f"{path.name} prompt #{n}"
        if not isinstance(raw, dict):
            raise PromptSetError(f"{where}: not a mapping")
        unknown = set(raw) - {"id", "segments", "tags", "prompt", "expect", "marker", "thread"}
        if unknown:
            raise PromptSetError(f"{where}: unknown field(s) {sorted(unknown)}")
        pid, tags, text, expect = raw.get("id"), raw.get("tags"), raw.get("prompt"), raw.get("expect")
        if not isinstance(pid, str) or not pid or pid != pid.strip().lower() or " " in pid:
            raise PromptSetError(f"{where}: id must be a non-empty lower-case word, got {pid!r}")
        if pid in seen:
            raise PromptSetError(f"{where}: duplicate id {pid!r}")
        seen.add(pid)
        if not isinstance(tags, list) or not tags or not set(tags) <= TAGS:
            raise PromptSetError(f"{where} ({pid}): tags must be a non-empty list from {sorted(TAGS)}, got {tags!r}")
        segments = raw.get("segments")
        if (not isinstance(segments, list)
                or not all(isinstance(n, int) and not isinstance(n, bool) and n in SEGMENTS for n in segments)):
            raise PromptSetError(f"{where} ({pid}): segments must be a non-empty list of run-of-show segments "
                                 f"1 to 6, got {segments!r}")
        # An empty list is the smoke check alone (#1104): a prompt the room does not send, so no --segment picks it.
        if not segments and set(tags) != {"on-topic", "smoke"}:
            raise PromptSetError(f"{where} ({pid}): segments must be a non-empty list of run-of-show segments "
                                 f"1 to 6; only the smoke prompt, tagged [on-topic, smoke], may have segments: []")
        if not isinstance(text, str) or not text.strip():
            raise PromptSetError(f"{where} ({pid}): prompt is empty")
        if not isinstance(expect, str) or not expect.strip():
            raise PromptSetError(f"{where} ({pid}): expect is empty; say what the presenter should see")
        marker = raw.get("marker")
        if marker is not None and (not isinstance(marker, str) or not marker.strip()):
            raise PromptSetError(f"{where} ({pid}): marker, when present, must be a non-empty string")
        thread = raw.get("thread")
        if thread is not None and (not isinstance(thread, str) or not thread or thread != thread.strip().lower()
                                   or " " in thread):
            raise PromptSetError(f"{where} ({pid}): thread, when present, must be a lower-case word, got {thread!r}")
        out.append(Prompt(pid, tuple(tags), text, expect, marker, tuple(segments), thread))
    if not out:
        raise PromptSetError(f"{path}: the prompt set is empty")
    return out


def select(prompts: list[Prompt], tags: list[str], only: list[str],
           segments: list[int] | None = None) -> list[Prompt]:
    """Prompts sent in any of segments and carrying any of tags (all when none), narrowed to the ids in only
    (all when none), in file order."""
    known = {p.id for p in prompts}
    missing = [i for i in only if i not in known]
    if missing:
        raise PromptSetError(f"--only names prompt id(s) not in the set: {', '.join(missing)}")
    segments = segments or []
    picked = [p for p in prompts
              if (not segments or set(segments) & set(p.segments))
              and (not tags or set(tags) & set(p.tags)) and (not only or p.id in only)]
    if not picked:
        raise PromptSetError("the --segment/--tag/--only selection matches no prompts")
    return picked


def chat_url(target: str) -> str:
    """https://host or https://host/chat -> https://host/chat. Anything else is a usage error."""
    parsed = urllib.parse.urlsplit(target.strip())
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError(f"--target must be an http(s) URL such as https://attackme.burritobot.co, got {target!r}")
    path = parsed.path.rstrip("/")
    if path not in ("", "/chat"):
        raise ValueError(f"--target must be the site root or its /chat, got path {parsed.path!r}")
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, "/chat", "", ""))


def classify(status: int, body: bytes) -> Outcome:
    """Judge one /chat response: delivered to the bot and answered by it, or the reason it was not."""
    if status != 200:
        return Outcome(False, status, f"HTTP {status}{_detail(body)}")
    try:
        data = json.loads(body)
    except ValueError:
        return Outcome(False, status, f"HTTP 200 but the body is not JSON{_detail(body)}")
    if not isinstance(data, dict) or not isinstance(data.get("reply"), str):
        return Outcome(False, status, "HTTP 200 but no reply field: this is not BurritoBot's /chat")
    reply = data["reply"].strip()
    if not reply or reply == EMPTY_REPLY:
        return Outcome(False, status, "the bot sent back an empty reply (an empty reply usually means the "
                                      "MCP servers are down; see the workshop runbook's failure playbook)")
    for prefix, why in PROXY_REFUSALS:
        if reply.startswith(prefix):
            return Outcome(False, status, why, reply=reply, guarded=True)
    return Outcome(True, status, reply=reply, guarded=bool(data.get("guarded")),
                   input_tokens=int(data.get("input_tokens") or 0),
                   output_tokens=int(data.get("output_tokens") or 0),
                   cost_usd=float(data.get("cost_usd") or 0.0))


def _detail(body: bytes) -> str:
    text = body.decode("utf-8", "replace").strip()
    try:
        data = json.loads(text)
        if isinstance(data, dict) and isinstance(data.get("reply"), str):
            text = data["reply"]
    except ValueError:
        pass
    text = " ".join(text.split())
    return f": {text[:160]}" if text else ""


def send_one(url: str, prompt: Prompt, session: str, timeout: float, witch: str = DEFAULT_WITCH) -> Outcome:
    """POST one prompt the way the storefront does ({prompt, session, witch}, with the session as the
    X-BurritoBot-Session header the console's nginx limits each conversation by) and classify what came back."""
    parsed = urllib.parse.urlsplit(url)
    req = urllib.request.Request(
        url, method="POST",
        data=json.dumps({"prompt": prompt.prompt, "session": session, "witch": witch}).encode(),
        headers={"Content-Type": "application/json", "User-Agent": USER_AGENT, "X-BurritoBot-Session": session,
                 "Origin": f"{parsed.scheme}://{parsed.netloc}"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return classify(resp.status, resp.read())
    except urllib.error.HTTPError as exc:
        return classify(exc.code, exc.read())
    except (urllib.error.URLError, http.client.HTTPException, socket.timeout, OSError) as exc:
        reason = getattr(exc, "reason", exc)
        return Outcome(False, None, f"could not reach {parsed.netloc}: {reason}")


def replay(prompts: list[Prompt], url: str, *, interval: float, timeout: float, run_id: str,
           send: Callable[[str, Prompt, str, float], Outcome] = send_one,
           sleep: Callable[[float], None] = time.sleep,
           clock: Callable[[], float] = time.monotonic,
           out: Callable[[str], None] = print) -> tuple[int, Prompt | None]:
    """Send prompts in order, paced, stopping at the first one not delivered.

    Returns (number delivered, the prompt it stopped on or None)."""
    total = len(prompts)
    last_start: float | None = None
    delivered = 0
    for n, p in enumerate(prompts, 1):
        if last_start is not None:
            wait = last_start + interval - clock()
            if wait > 0:
                sleep(wait)
        last_start = clock()
        result = send(url, p, session_id(run_id, p), timeout)
        result.elapsed_s = clock() - last_start
        head = f"[{n}/{total}] {p.id:<20} {','.join(p.tags)}"
        if not result.delivered:
            out(f"{head}  FAILED after {result.elapsed_s:.1f}s: {result.reason}")
            out(f"STOPPED at {p.id}: {delivered} of {total} delivered. Do not retry from the stage; "
                f"move to the next rollback step.")
            return delivered, p
        delivered += 1
        line = (f"{head}  ok {result.elapsed_s:.1f}s  in={result.input_tokens} out={result.output_tokens}"
                f"  ${result.cost_usd:.4f}")
        if result.guarded:
            line += "  guarded"
        if p.marker:
            line += f"  marker {'hit' if p.marker in visible(result.reply) else 'MISS (model declined; resend or see PROMPT-CATALOG)'}"
        out(line)
        out(f"    {visible(result.reply)[:160]}")
    out(f"DONE: {delivered} of {total} delivered to {url}")
    return delivered, None


def visible(reply: str) -> str:
    """The reply as the storefront shows it, with the model's <thinking> blocks folded away."""
    return " ".join(THINKING_RE.sub("", reply).split())


def session_id(run_id: str, p: Prompt) -> str:
    return f"sess-replay-{run_id}-{p.conversation}"


def _witch(text: str) -> str:
    if not re.fullmatch(WITCH_NAME_RE, text):
        raise argparse.ArgumentTypeError(f"{text!r} is not shaped <First> the <Creature>; guard-proxy would drop it")
    return text


def _interval(text: str) -> float:
    value = float(text)
    if value < MIN_INTERVAL_S:
        raise argparse.ArgumentTypeError(
            f"{value:g}s is faster than {MIN_INTERVAL_S:g}s, which would take more than half of guard-proxy's "
            f"{GUARD_PROXY_RPM}/min window and leave the presenters' own asks rate-limited")
    return value


def _positive(text: str) -> float:
    value = float(text)
    if value <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return value


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--target", required=True,
                    help="the bot's site root or its /chat, e.g. https://attackme.burritobot.co")
    ap.add_argument("--prompts", type=pathlib.Path, default=DEFAULT_PROMPTS,
                    help=f"prompt set (default {DEFAULT_PROMPTS.relative_to(REPO)})")
    ap.add_argument("--segment", action="append", default=[], type=int, choices=sorted(SEGMENTS),
                    help="send only the prompts the room sends in this run-of-show segment; repeatable")
    ap.add_argument("--tag", action="append", default=[], choices=sorted(TAGS),
                    help="send only prompts carrying this tag; repeat for several (any of)")
    ap.add_argument("--only", action="append", default=[], metavar="ID", help="send only this prompt id; repeatable")
    ap.add_argument("--interval", type=_interval, default=DEFAULT_INTERVAL_S,
                    help=f"seconds between the start of one send and the next (default {DEFAULT_INTERVAL_S:g}, "
                         f"floor {MIN_INTERVAL_S:g})")
    ap.add_argument("--timeout", type=_positive, default=DEFAULT_TIMEOUT_S,
                    help=f"seconds to wait for one reply (default {DEFAULT_TIMEOUT_S:g})")
    ap.add_argument("--run-id", default="", help="session id stem; default a fresh random one per run")
    ap.add_argument("--witch", type=_witch, default=DEFAULT_WITCH,
                    help=f"the witch name sent with each prompt, as the storefront does (default {DEFAULT_WITCH!r})")
    ap.add_argument("--dry-run", action="store_true", help="print what would be sent, touch no network")
    args = ap.parse_args(argv)

    try:
        url = chat_url(args.target)
        prompts = select(load_prompts(args.prompts), args.tag, args.only, args.segment)
    except (ValueError, PromptSetError) as exc:
        print(f"replay-prompts: {exc}", file=sys.stderr)
        return 2
    run_id = args.run_id or uuid.uuid4().hex[:8]

    print(f"replaying {len(prompts)} prompt(s) to {url}, one every {args.interval:g}s or slower, "
          f"run {run_id}")
    if args.dry_run:
        for n, p in enumerate(prompts, 1):
            print(f"[{n}/{len(prompts)}] {p.id:<20} {','.join(p.tags)}  session {session_id(run_id, p)}")
            print(f"    {p.prompt}")
        print("DRY RUN: nothing sent")
        return 0
    _, stopped = replay(prompts, url, interval=args.interval, timeout=args.timeout, run_id=run_id,
                        send=lambda u, p, s, t: send_one(u, p, s, t, args.witch))
    return 1 if stopped else 0


if __name__ == "__main__":
    sys.exit(main())
