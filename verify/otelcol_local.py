# ABOUTME: Starts a local otelcol-contrib on a loopback port for the E2E tools tier and waits until it says it is ready,
# ABOUTME: retrying on a fresh port when another process took the chosen one first (#969).
"""One start for every tier test that runs the pinned collector between OTLP/HTTP in and a file out.

Run 17806 (#954) saw verify/test_collector_act2_redaction_e2e.py's attendee Act 1 report that the collector never
took the turn, with an empty collector log, and pass on the rerun. The test gave the collector 30 seconds from its
Popen to answer the POST. Two things could make that fail on the loaded shared host, and this module removes both:

  - A slow start. The 30-second send clock started at the Popen, so a collector that took longer than that to come
    up (nothing logged at all: run 17806's log was empty) lost the turn. start() waits for the collector's own
    "Everything is ready" line first, which it logs only once every receiver is bound, and only then does the
    caller's send clock start. The wait counts polls, not wall seconds, so a host stall that freezes this process
    with the collector spends none of it (the lesson of #799).
  - A taken port. free_port() closes its socket before the collector binds the port, so another process can take
    it in between. The collector then exits at once, logging "bind: address already in use"; start() sees that and
    starts again on a fresh port, up to ATTEMPTS times. Once the collector is ready the port is its own: Linux admits
    no second listener on an address while one is listening, so a POST to it reaches this collector and no other.

When the start fails, Collector.detail() is what the check prints: proc.poll() (the exit code, or that it is still
running), how long the wait ran, the host's pressure stall over it, and the log of every attempt.
"""
from __future__ import annotations

import pathlib
import socket
import subprocess
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field

READY = "Everything is ready"
IN_USE = "address already in use"
ATTEMPTS = 5
POLL = 0.3
READY_POLLS = 600  # 180 s of polls at least; run 17806's collector logged nothing in its first 30


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def stalled() -> dict[str, float]:
    """The host's pressure stall totals in seconds (/proc/pressure), as verify/test_trace_shape_e2e.py reads them."""
    out = {}
    for res, kind in (("cpu", "some"), ("memory", "full"), ("io", "full")):
        path = pathlib.Path(f"/proc/pressure/{res}")
        if not path.exists():
            continue
        line = next(ln for ln in path.read_text().splitlines() if ln.startswith(kind))
        out[f"{kind} {res}"] = int(line.rsplit("total=", 1)[1]) / 1e6
    return out


@dataclass
class Collector:
    proc: subprocess.Popen | None = None
    port: int = 0
    log_file: pathlib.Path | None = None
    ready: bool = False
    polls: int = 0
    seconds: float = 0.0
    pressure: str = ""
    logs: list[tuple[int, str]] = field(default_factory=list)  # (port, log) of each attempt that did not come up

    def log(self) -> str:
        return self.log_file.read_text() if self.log_file and self.log_file.exists() else ""

    def detail(self) -> str:
        rc = None if self.proc is None else self.proc.poll()
        lines = [f"proc.poll() = {rc}" + (" (still running)" if self.proc is not None and rc is None else ""),
                 f"ready: {self.ready}, port {self.port}, after {len(self.logs) + 1} start(s), waited {self.polls} "
                 f"polls over {self.seconds:.1f} s; the host's pressure stall over the wait: {self.pressure or 'n/a'}"]
        for port, text in self.logs:
            lines.append(f"collector log of the start on port {port}:\n{text[-1500:] or '(empty)'}")
        lines.append(f"collector log on port {self.port}:\n{self.log()[-3000:] or '(empty)'}")
        return "\n        ".join(lines)

    def stop(self) -> None:
        if self.proc is not None and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(timeout=15)


def start(argv: Callable[[int], list[str]], log_file: pathlib.Path, env: dict[str, str] | None = None,
          ports: Iterator[int] | None = None, attempts: int = ATTEMPTS, ready_polls: int = READY_POLLS) -> Collector:
    """Start argv(port), whose config listens on 127.0.0.1:port, and wait for its ready line. Returns the Collector,
    ready or not; the caller checks .ready, prints .detail() when it is not, and always calls .stop()."""
    pick = ports.__next__ if ports is not None else free_port
    c = Collector(log_file=log_file)
    before, t0 = stalled(), time.monotonic()
    for _ in range(attempts):
        if c.proc is not None:
            c.logs.append((c.port, c.log()))
        c.port = pick()
        with log_file.open("w") as fh:
            c.proc = subprocess.Popen(argv(c.port), stdout=fh, stderr=subprocess.STDOUT, env=env)
        while c.polls < ready_polls:
            c.polls += 1
            done = c.proc.poll() is not None
            if READY in c.log() and not done:
                c.ready = True
                break
            if done:
                break
            time.sleep(POLL)
        if c.ready or c.polls >= ready_polls or IN_USE not in c.log():
            break
    c.seconds = time.monotonic() - t0
    after = stalled()
    c.pressure = ", ".join(f"{k} {after[k] - v:.1f} s" for k, v in before.items() if k in after)
    return c
