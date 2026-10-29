#!/usr/bin/env python3
# ABOUTME: Load test for #644: replays the last delivery's recorded attendee prompts at a live BurritoBot /chat as
# ABOUTME: hundreds of concurrent phone users, and writes down where the cluster gave out, without any prompt text.
"""Replay recorded prompt traffic at one public cluster as N concurrent users.

Agreed on the 2026-10-28 planning call (facilitation/kubecon-na-2026-planning-2026-10-28.md, "Resilience and
load"): load test one cluster at 500 users by replaying the prompts the room typed at the last delivery. The
method, the expected limits and the results are in facilitation/kubecon-na-2026-load-test.md.

    python3 scripts/load-replay.py --target https://<spare-public-host> --dry-run
    python3 scripts/load-replay.py --target https://<spare-public-host>                  # 500 users, 3 turns
    python3 scripts/load-replay.py --target https://<host> --users 50 --turns 1          # a smaller first pass

The recording. scripts/harvest/run.sh writes every attendee prompt it recovered from Datadog to
.harvest/<event>/prompts/<cluster>.json, one span per entry, the typed text under "user" as "user: <text>".
The default is the last delivery, DevOpsDays Portland 2026 (.harvest/devopsdays-portland). That directory is
gitignored because it holds attendee-typed text, so this runs where the harvest was taken.

The users. Each virtual user is one browser session (its own session id, so its own conversation, its own
10-a-minute allowance and its own budget), starts at a point spread across --ramp seconds, and sends --turns
recorded prompts, reading each reply for --think seconds before typing the next. Consecutive prompts of one
recorded cluster go to the same user, so a user replays something close to one attendee's conversation.

What is kept. Every request's user, turn, timing, outcome and spend go to <out>/requests.jsonl, and the limits
to <out>/summary.json and <out>/summary.md. A prompt is named by its index in the recording and a short hash,
never by its text, and no reply is kept, so the results can be committed and the recording cannot leak out
through them. Each prompt carries guard-proxy's probe marker by default, which keeps the replayed attendee text
off the side-screen and the prompt wall; --on-wall sends it bare.

Stopping. New turns stop at --duration seconds or once the replies have reported --budget-usd of spend; turns
in flight finish. A refusal is not a stop: the rate limits, the cost backstop and the errors are what this is
here to measure.

Exit status: 0 the run finished and its limits are written, 1 not one request was served (the target is down
or is not BurritoBot), 2 a usage or recording error.
"""
from __future__ import annotations

import argparse
import dataclasses
import hashlib
import http.client
import json
import math
import pathlib
import socket
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

REPO = pathlib.Path(__file__).resolve().parents[1]
# The last delivery: DevOpsDays Portland 2026 (talks-knowledge talks/register.md, section 2).
DEFAULT_RECORDING = REPO / ".harvest/devopsdays-portland"
DEFAULT_USERS = 500
DEFAULT_TURNS = 3
DEFAULT_THINK_S = 20.0
DEFAULT_RAMP_S = 60.0
# The console's nginx gives /chat 160 seconds (console.conf); wait a little longer so nginx's own 504 is what
# gets recorded, rather than a client timeout that hides which hop gave up.
DEFAULT_TIMEOUT_S = 170.0
DEFAULT_BUDGET_USD = 10.0
DEFAULT_DURATION_S = 900.0
# guard-proxy's PROBE_MARKER: a prompt carrying it never reaches the side-screen feed (proxy.py _is_probe).
PROBE_MARKER = "[[wib-probe]]"
EMPTY_REPLY = "..."
USER_AGENT = "wib-load-replay/1 (Unleash_an_Agent_Watch_It_Burn#644)"

# Every outcome a request can have. "served" means the platform answered the turn itself: the bot's reply, or
# one of its guardrails turning the prompt away. The rest are the limits and failures being measured.
SERVED = ("answered", "guardrail")
KINDS = SERVED + ("session_limit", "cluster_limit", "cost_cap", "empty", "http_error", "timeout",
                  "unreachable", "not_chat")
# guard-proxy answers its limits with HTTP 200 and guarded:true without calling the model. Prefixes and
# fragments of proxy.py's own reply text, checked against it by verify/test_load_replay.py.
RATE_LIMIT_PREFIX = "Slow down, hungry traveler."
SESSION_LIMIT_FRAGMENT = "per conversation"
CLUSTER_LIMIT_FRAGMENT = "cap on this cluster"
COST_CAP_PREFIX = "The kitchen tab is frozen."


class RecordingError(Exception):
    """The recording is missing, unreadable, or holds no prompt."""


@dataclasses.dataclass
class Result:
    kind: str
    status: int | None = None
    detail: str = ""
    cost_usd: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0


# ---------------------------------------------------------------------------------------------------------
# The recording


def prompts_dir(path: pathlib.Path) -> pathlib.Path:
    """An event directory (.harvest/<event>) or its prompts/ directory -> the prompts/ directory."""
    return path / "prompts" if (path / "prompts").is_dir() else path


def load_recording(path: pathlib.Path) -> list[tuple[str, str]]:
    """Every distinct prompt the recording holds, as (cluster, text), cluster files in name order and each
    cluster's prompts in time order.

    A span's "user" list is the conversation as the model saw it, so only its last user entry is the turn's
    own prompt; the earlier ones are history. One turn makes several spans (the /chat root, its chat child,
    the agent's model calls), so a text already taken from a cluster is not taken again. Earlier probes
    (guard-proxy's PROBE_MARKER) were never attendee input and are dropped."""
    pdir = prompts_dir(path)
    if not pdir.is_dir():
        raise RecordingError(f"no recording at {path}: run scripts/harvest/run.sh <event> while the event's "
                             f"clusters are up, or name the harvest with --recording")
    files = sorted(pdir.glob("*.json"))
    if not files:
        raise RecordingError(f"{pdir} holds no <cluster>.json prompt files")
    out: list[tuple[str, str]] = []
    for f in files:
        try:
            spans = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise RecordingError(f"cannot read {f}: {exc}") from exc
        if not isinstance(spans, list):
            raise RecordingError(f"{f}: expected a list of spans, as scripts/harvest/01-clusters.py writes")
        seen: set[str] = set()
        for span in sorted((s for s in spans if isinstance(s, dict)), key=lambda s: str(s.get("ts") or "")):
            users = [u for u in span.get("user") or [] if isinstance(u, str) and u.startswith("user: ")]
            if not users:
                continue
            text = users[-1][len("user: "):].strip()
            if not text or PROBE_MARKER in text or text in seen:
                continue
            seen.add(text)
            out.append((f.stem, text))
    if not out:
        raise RecordingError(f"{pdir}: {len(files)} file(s) but not one user prompt in them")
    return out


def assign(n_prompts: int, users: int, turns: int) -> list[list[int]]:
    """Prompt indices for each user's turns. User u takes prompts u*turns .. u*turns+turns-1, wrapping round the
    recording, so neighbouring prompts (one attendee's) stay together and the whole recording gets used."""
    return [[(u * turns + t) % n_prompts for t in range(turns)] for u in range(users)]


def prompt_id(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:10]


# ---------------------------------------------------------------------------------------------------------
# One request


def site_url(target: str, path: str) -> str:
    """https://host or https://host/chat -> https://host<path>. Anything else is a usage error."""
    parsed = urllib.parse.urlsplit(target.strip())
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError(f"--target must be an http(s) URL such as https://attackme.agenticburn.com, got {target!r}")
    if parsed.path.rstrip("/") not in ("", "/chat"):
        raise ValueError(f"--target must be the site root or its /chat, got path {parsed.path!r}")
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


def classify(status: int, body: bytes) -> Result:
    if status != 200:
        return Result("http_error", status, _snippet(body))
    try:
        data = json.loads(body)
    except ValueError:
        return Result("not_chat", status, "HTTP 200 but the body is not JSON")
    if not isinstance(data, dict) or not isinstance(data.get("reply"), str):
        return Result("not_chat", status, "HTTP 200 but no reply field: this is not BurritoBot's /chat")
    reply = data["reply"].strip()
    spend = dict(cost_usd=float(data.get("cost_usd") or 0.0), input_tokens=int(data.get("input_tokens") or 0),
                 output_tokens=int(data.get("output_tokens") or 0))
    if not reply or reply == EMPTY_REPLY:
        return Result("empty", status, "the bot sent back an empty reply", **spend)
    if reply.startswith(RATE_LIMIT_PREFIX):
        kind = "session_limit" if SESSION_LIMIT_FRAGMENT in reply else "cluster_limit"
        return Result(kind, status, reply[:120], **spend)
    if reply.startswith(COST_CAP_PREFIX):
        return Result("cost_cap", status, reply[:120], **spend)
    return Result("guardrail" if data.get("guarded") else "answered", status, **spend)


def _snippet(body: bytes) -> str:
    text = body.decode("utf-8", "replace")
    try:
        data = json.loads(text)
        if isinstance(data, dict) and isinstance(data.get("reply"), str):
            text = data["reply"]
    except ValueError:
        pass
    return " ".join(text.split())[:120]


def _is_timeout(exc: BaseException) -> bool:
    reason = getattr(exc, "reason", exc)
    return isinstance(reason, (socket.timeout, TimeoutError)) or "timed out" in str(reason)


def send_chat(url: str, text: str, session: str, timeout: float) -> Result:
    """POST one turn the way the storefront does ({prompt, session}) and classify what came back."""
    req = urllib.request.Request(url, method="POST",
                                 data=json.dumps({"prompt": text, "session": session}).encode(),
                                 headers={"Content-Type": "application/json", "User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return classify(resp.status, resp.read())
    except urllib.error.HTTPError as exc:
        return classify(exc.code, exc.read())
    except (urllib.error.URLError, http.client.HTTPException, OSError) as exc:
        if _is_timeout(exc):
            return Result("timeout", None, f"no reply in {timeout:g}s")
        return Result("unreachable", None, str(getattr(exc, "reason", exc))[:120])


def read_cost(url: str, timeout: float = 20.0) -> dict:
    """The cluster's own spend meter (guard-proxy /cost): usd so far and the backstop it stops at."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read())
        return {"usd": float(data["usd"]), "cap_usd": float(data.get("cap_usd") or 0.0),
                "requests": int(data.get("requests") or 0)}
    except (urllib.error.URLError, http.client.HTTPException, OSError, ValueError, KeyError, TypeError) as exc:
        return {"error": f"{url} unreadable: {getattr(exc, 'reason', exc)}"}


# ---------------------------------------------------------------------------------------------------------
# The run


@dataclasses.dataclass
class Config:
    users: int = DEFAULT_USERS
    turns: int = DEFAULT_TURNS
    think_s: float = DEFAULT_THINK_S
    ramp_s: float = DEFAULT_RAMP_S
    timeout_s: float = DEFAULT_TIMEOUT_S
    budget_usd: float = DEFAULT_BUDGET_USD
    duration_s: float = DEFAULT_DURATION_S
    on_wall: bool = False


class LoadRun:
    def __init__(self, url: str, prompts: list[tuple[str, str]], cfg: Config, run_id: str, send=send_chat):
        self.url, self.prompts, self.cfg, self.run_id, self.send = url, prompts, cfg, run_id, send
        self.plan = assign(len(prompts), cfg.users, cfg.turns)
        self.records: list[dict] = []
        self.lock = threading.Lock()
        self.stop = threading.Event()
        self.stopped_by: str | None = None
        self.spent = 0.0
        self.in_flight = 0
        self.peak_in_flight = 0
        self.t0 = 0.0

    def session(self, user: int) -> str:
        return f"sess-load-{self.run_id}-{user:04d}"

    def _halt(self, why: str) -> None:
        with self.lock:
            if self.stopped_by is None:
                self.stopped_by = why
        self.stop.set()

    def _user(self, user: int) -> None:
        cfg = self.cfg
        start = self.t0 + (cfg.ramp_s * user / cfg.users if cfg.users > 1 else 0.0)
        if self.stop.wait(max(0.0, start - time.monotonic())):
            return
        for turn, idx in enumerate(self.plan[user]):
            if self.stop.is_set():
                return
            if time.monotonic() - self.t0 >= cfg.duration_s:
                self._halt("duration")
                return
            text = self.prompts[idx][1]
            sent = text if cfg.on_wall else f"{text} {PROBE_MARKER}"
            with self.lock:
                self.in_flight += 1
                self.peak_in_flight = max(self.peak_in_flight, self.in_flight)
            began = time.monotonic()
            result = self.send(self.url, sent, self.session(user), cfg.timeout_s)
            ended = time.monotonic()
            with self.lock:
                self.in_flight -= 1
                self.spent += result.cost_usd
                over = cfg.budget_usd > 0 and self.spent >= cfg.budget_usd
                self.records.append({
                    "user": user, "turn": turn, "prompt": idx, "prompt_id": prompt_id(text),
                    "start_s": round(began - self.t0, 3), "elapsed_s": round(ended - began, 3),
                    "kind": result.kind, "status": result.status, "detail": result.detail,
                    "cost_usd": result.cost_usd, "input_tokens": result.input_tokens,
                    "output_tokens": result.output_tokens})
            if over:
                self._halt("budget")
                return
            if turn + 1 < len(self.plan[user]) and self.stop.wait(cfg.think_s):
                return

    def run(self) -> list[dict]:
        self.t0 = time.monotonic()
        threads = [threading.Thread(target=self._user, args=(u,), daemon=True, name=f"user-{u}")
                   for u in range(self.cfg.users)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.records.sort(key=lambda r: r["start_s"])
        return self.records


# ---------------------------------------------------------------------------------------------------------
# The limits


def percentile(values: list[float], p: float) -> float | None:
    """Nearest-rank percentile; None for no values."""
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(p / 100.0 * len(ordered)) - 1)]


def peak_per_minute(times: list[float]) -> int:
    """The most events inside any 60-second window."""
    ordered = sorted(times)
    best, lo = 0, 0
    for hi, t in enumerate(ordered):
        while t - ordered[lo] >= 60.0:
            lo += 1
        best = max(best, hi - lo + 1)
    return best


def summarize(run: LoadRun, wall_s: float, cost_before: dict, cost_after: dict) -> dict:
    recs, cfg = run.records, run.cfg
    counts = {k: sum(1 for r in recs if r["kind"] == k) for k in KINDS}
    served = [r for r in recs if r["kind"] in SERVED]
    first = {k: min((r["start_s"] for r in recs if r["kind"] == k), default=None) for k in KINDS}
    lat = [r["elapsed_s"] for r in served]
    users_served = len({r["user"] for r in served})
    statuses: dict[str, int] = {}
    for r in recs:
        if r["kind"] == "http_error":
            statuses[str(r["status"])] = statuses.get(str(r["status"]), 0) + 1
    return {
        "run_id": run.run_id, "target": run.url,
        "config": dataclasses.asdict(cfg),
        "recording_prompts": len(run.prompts),
        "requests": len(recs), "planned_requests": cfg.users * cfg.turns,
        "outcomes": counts, "http_statuses": statuses,
        "first_seen_s": {k: v for k, v in first.items() if v is not None},
        "served": len(served), "served_share": round(len(served) / len(recs), 4) if recs else 0.0,
        "users_served": users_served, "users_never_served": cfg.users - users_served,
        "served_latency_s": {"p50": percentile(lat, 50), "p90": percentile(lat, 90),
                             "p99": percentile(lat, 99), "max": max(lat) if lat else None},
        "peak_served_per_minute": peak_per_minute([r["start_s"] + r["elapsed_s"] for r in served]),
        "peak_in_flight": run.peak_in_flight,
        "spend_reported_usd": round(run.spent, 6),
        "cluster_cost_before": cost_before, "cluster_cost_after": cost_after,
        "stopped_by": run.stopped_by, "wall_s": round(wall_s, 1),
    }


def render(s: dict) -> str:
    """The summary as markdown, for the Results section of facilitation/kubecon-na-2026-load-test.md."""
    c = s["config"]
    lat = s["served_latency_s"]

    def sec(v):
        return "n/a" if v is None else f"{v:.1f} s"

    lines = [
        f"### Run {s['run_id']} against {s['target']}",
        "",
        f"{c['users']} users, {c['turns']} turns each, {c['think_s']:g} s think time, {c['ramp_s']:g} s ramp, "
        f"replaying {s['recording_prompts']} recorded prompts. {s['requests']} of {s['planned_requests']} planned "
        f"requests sent in {s['wall_s']:g} s" + (f"; new turns stopped by the {s['stopped_by']} limit." if
                                                 s["stopped_by"] else "."),
        "",
        "| Outcome | Requests | First seen |",
        "|---|---|---|",
    ]
    for k in KINDS:
        if s["outcomes"][k]:
            first = s["first_seen_s"].get(k)
            lines.append(f"| {k} | {s['outcomes'][k]} | {sec(first)} into the run |")
    if s["http_statuses"]:
        lines += ["", "HTTP statuses: " + ", ".join(f"{k} x{v}" for k, v in sorted(s["http_statuses"].items()))]
    lines += [
        "",
        f"- Served (answered or turned away by a guardrail): {s['served']} ({s['served_share']:.0%}); "
        f"{s['users_served']} of {c['users']} users got at least one turn served, {s['users_never_served']} none.",
        f"- Served latency: p50 {sec(lat['p50'])}, p90 {sec(lat['p90'])}, p99 {sec(lat['p99'])}, max {sec(lat['max'])}.",
        f"- Peak served in any 60 s: {s['peak_served_per_minute']}. Peak requests in flight: {s['peak_in_flight']}.",
        f"- Spend the replies reported: ${s['spend_reported_usd']:.4f}.",
    ]
    for label, key in (("before", "cluster_cost_before"), ("after", "cluster_cost_after")):
        cost = s[key]
        lines.append(f"- Cluster /cost {label}: " + (cost["error"] if "error" in cost else
                     f"${cost['usd']:.4f} of its ${cost['cap_usd']:.2f} backstop, {cost['requests']} requests."))
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------------------------------------


def _count(text: str) -> int:
    value = int(text)
    if value < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return value


def _seconds(text: str) -> float:
    value = float(text)
    if value < 0:
        raise argparse.ArgumentTypeError("must not be negative")
    return value


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--target", required=True, help="the bot's site root or its /chat, e.g. https://attackme.agenticburn.com")
    ap.add_argument("--recording", type=pathlib.Path, default=DEFAULT_RECORDING,
                    help=f"harvest directory or its prompts/ (default {DEFAULT_RECORDING.relative_to(REPO)})")
    ap.add_argument("--users", type=_count, default=DEFAULT_USERS, help=f"concurrent users (default {DEFAULT_USERS})")
    ap.add_argument("--turns", type=_count, default=DEFAULT_TURNS, help=f"prompts per user (default {DEFAULT_TURNS})")
    ap.add_argument("--think", type=_seconds, default=DEFAULT_THINK_S,
                    help=f"seconds a user reads a reply before the next prompt (default {DEFAULT_THINK_S:g})")
    ap.add_argument("--ramp", type=_seconds, default=DEFAULT_RAMP_S,
                    help=f"seconds over which the users start (default {DEFAULT_RAMP_S:g})")
    ap.add_argument("--timeout", type=_seconds, default=DEFAULT_TIMEOUT_S,
                    help=f"seconds to wait for one reply (default {DEFAULT_TIMEOUT_S:g})")
    ap.add_argument("--budget-usd", type=_seconds, default=DEFAULT_BUDGET_USD,
                    help=f"stop new turns once replies report this much spend; 0 for none (default {DEFAULT_BUDGET_USD:g})")
    ap.add_argument("--duration", type=_seconds, default=DEFAULT_DURATION_S,
                    help=f"stop new turns after this many seconds (default {DEFAULT_DURATION_S:g})")
    ap.add_argument("--on-wall", action="store_true",
                    help="send the prompts without the probe marker, so they reach the side-screen and prompt wall")
    ap.add_argument("--out", type=pathlib.Path, default=None,
                    help="results directory (default .harvest/load-<run id>, gitignored)")
    ap.add_argument("--run-id", default="", help="session id stem; default a fresh random one")
    ap.add_argument("--dry-run", action="store_true", help="print the plan, touch no network")
    args = ap.parse_args(argv)

    try:
        chat = site_url(args.target, "/chat")
        cost_url = site_url(args.target, "/cost")
        prompts = load_recording(args.recording)
    except (ValueError, RecordingError) as exc:
        print(f"load-replay: {exc}", file=sys.stderr)
        return 2
    cfg = Config(users=args.users, turns=args.turns, think_s=args.think, ramp_s=args.ramp,
                 timeout_s=args.timeout, budget_usd=args.budget_usd, duration_s=args.duration, on_wall=args.on_wall)
    run_id = args.run_id or uuid.uuid4().hex[:8]
    out = args.out or REPO / ".harvest" / f"load-{run_id}"
    clusters = len({c for c, _ in prompts})
    print(f"run {run_id}: {cfg.users} users x {cfg.turns} turns at {chat}, replaying {len(prompts)} prompts "
          f"recorded on {clusters} cluster(s); think {cfg.think_s:g}s, ramp {cfg.ramp_s:g}s, budget "
          f"${cfg.budget_usd:g}, at most {cfg.duration_s:g}s; prompts {'on' if cfg.on_wall else 'off'} the wall")
    if args.dry_run:
        run = LoadRun(chat, prompts, cfg, run_id)
        for u in range(min(cfg.users, 5)):
            print(f"  {run.session(u)}: prompts {run.plan[u]}")
        if cfg.users > 5:
            print(f"  ... {cfg.users - 5} more users")
        print("DRY RUN: nothing sent")
        return 0

    before = read_cost(cost_url)
    if "error" not in before and before["cap_usd"]:
        print(f"cluster spend ${before['usd']:.4f} of its ${before['cap_usd']:.2f} backstop before the run")
    run = LoadRun(chat, prompts, cfg, run_id)
    began = time.monotonic()
    run.run()
    wall = time.monotonic() - began
    summary = summarize(run, wall, before, read_cost(cost_url))

    out.mkdir(parents=True, exist_ok=True)
    with (out / "requests.jsonl").open("w", encoding="utf-8") as fh:
        for r in run.records:
            fh.write(json.dumps(r) + "\n")
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    md = render(summary)
    (out / "summary.md").write_text(md, encoding="utf-8")
    print(md)
    print(f"wrote {out}/requests.jsonl, summary.json and summary.md")
    if summary["served"] == 0:
        print(f"load-replay: not one of {summary['requests']} requests was served; the target is down or is "
              f"not BurritoBot's /chat", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
