# ABOUTME: The cluster's guard lock (#1024): a Lease in the agent namespace that a run holds while it flips guards, so
# ABOUTME: two runs sharing a cluster take turns. `hold` wraps a command in it; the probes take it from Python.
"""One run at a time flips the guards on a cluster.

On 2026-11-06 run 17950 (#900) ran the admin KubeCon probe five times on watch-it-burn-private, and three of those runs
went red because the output guard was on when the probe expected it off. That run never turned it on. Three other runs
were working on the same cluster, guard-proxy's /toggle answers only inside the cluster, and guard-proxy does not log
toggles, so nobody could name the caller. This lock is the half of #1024 that lives in this repo: the probe and every
verify script that flips guards through the cluster hold it while they do, and a second holder waits for it, then
gives up naming the holder, instead of flipping guards under the first.

The lock is the Lease `wib-guard-lock` in the namespace `agent`. Its holderIdentity names the script, the process,
the host and the checkout (a hecaton run's worktree is named <id>-<issue>-<run>, so the checkout names the run).
The holder renews it every RENEW_S seconds; a holder that dies without releasing frees it LEASE_S seconds after its
last renewal, so a killed run blocks the cluster for minutes, not for good. Every write is optimistic: a create
that finds the Lease there, a replace and a delete that carry the resourceVersion they read, so two runs racing for a
free or expired Lease cannot both win.

    # wrap a command: it runs only once the lock is held, and the lock is released when it exits
    python3 verify/guard_lease.py hold --context watch-it-burn-private --profile accen-dev -- bash verify/beat-02.sh ...

    # who holds it now
    python3 verify/guard_lease.py show --context watch-it-burn-private --profile accen-dev

A command run under `hold` finds the context in WIB_GUARD_LEASE (a JSON map of context to holder), so a script that
`hold` already wraps, or that the probe runs, does not try to take the lock a second time. The shell scripts check it
with `held`, which reads only that variable and runs no kubectl.

The lock is advisory, as any lock is: it holds back only the scripts that take it. The presenters' terminal helpers
(guard-input-on and the rest) do not take it; they are the stage, and no run flips guards on a cluster during a
live session.
"""
from __future__ import annotations

import argparse
import datetime as dt
import getpass
import json
import os
import pathlib
import signal
import socket
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from typing import Callable, Iterator

REPO = pathlib.Path(__file__).resolve().parents[1]
NAME = "wib-guard-lock"
NAMESPACE = "agent"
# A holder that dies frees the lock this long after its last renewal.
LEASE_S = 300
RENEW_S = 60
# How long a second holder waits by default. A full admin KubeCon probe takes about 15 minutes.
WAIT_S = 1800
POLL_S = 15
# How often a waiting holder says whom it waits on, so a long wait is never a silent one.
WAIT_NOTE_S = 60
ENV = "WIB_GUARD_LEASE"
# `hold`'s exit code when the lock stayed busy for the whole wait.
BUSY_EXIT = 3
API_PATH = f"/apis/coordination.k8s.io/v1/namespaces/{NAMESPACE}/leases/{NAME}"


class LeaseBusy(RuntimeError):
    """The lock stayed held by someone else for the whole wait."""


def micro_time(t: float) -> str:
    """A Kubernetes MicroTime: RFC 3339 in UTC with six fraction digits."""
    return dt.datetime.fromtimestamp(t, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def parse_micro_time(s: str | None) -> float | None:
    if not s:
        return None
    try:
        return dt.datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def holder_identity(what: str, pid: int | None = None, host: str | None = None, checkout: str | None = None,
                    user: str | None = None) -> str:
    """Who is flipping guards, in words a person reading `kubectl get lease` can trace back to a run."""
    return (f"{what or 'guard-lease'} pid {pid or os.getpid()} by {user or getpass.getuser()}"
            f"@{host or socket.gethostname()} in {checkout or REPO.name}")


def held_map(environ: dict | None = None) -> dict[str, str]:
    """WIB_GUARD_LEASE as a map of context to holder; empty when unset or not a JSON object."""
    raw = (os.environ if environ is None else environ).get(ENV, "")
    try:
        m = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        return {}
    return {str(k): str(v) for k, v in m.items()} if isinstance(m, dict) else {}


def caller(context: str | None, environ: dict | None = None) -> str:
    """The holder of the lock on `context` as this process knows it, for a /toggle's X-WIB-Caller header: guard-proxy
    logs it beside the peer address, which is only 127.0.0.1 for a kubectl exec. "" when no lock is held here."""
    return held_map(environ).get(context or "", "")


def expired(lease: dict, now: float) -> bool:
    """True when nobody holds the Lease, or its holder stopped renewing it more than its duration ago."""
    spec = lease.get("spec") or {}
    if not spec.get("holderIdentity"):
        return True
    last = parse_micro_time(spec.get("renewTime")) or parse_micro_time(spec.get("acquireTime"))
    if last is None:
        return True
    return now > last + int(spec.get("leaseDurationSeconds") or LEASE_S)


def describe(lease: dict | None, now: float) -> str:
    """One line on who holds the lock, for a waiting holder's log and for `show`."""
    if not lease:
        return f"{NAME} is free (no Lease in {NAMESPACE})"
    spec = lease.get("spec") or {}
    holder = spec.get("holderIdentity") or ""
    if not holder:
        return f"{NAME} is free (the Lease names no holder)"
    since = spec.get("acquireTime") or "?"
    last = parse_micro_time(spec.get("renewTime"))
    ago = f"{int(now - last)} s ago" if last is not None else "never"
    state = "expired" if expired(lease, now) else "held"
    return f"{NAME} {state} by {holder!r} since {since}, last renewed {ago}"


class GuardLease:
    """The Lease on one cluster, read and written with kubectl, one explicit --context per call."""

    def __init__(self, context: str, kubeconfig: str | None = None, profile: str | None = None, what: str = "",
                 runner: Callable = subprocess.run, clock: Callable[[], float] = time.time,
                 sleep: Callable[[float], None] = time.sleep, log: Callable[[str], None] | None = None,
                 holder: str | None = None, duration: int = LEASE_S, poll: float = POLL_S) -> None:
        if not context:
            raise ValueError("the guard lock needs an explicit kube-context; it never falls back to the current one")
        self.context = context
        self.kubeconfig = kubeconfig
        self.profile = profile
        self.holder = holder or holder_identity(what)
        self.runner = runner
        self.clock = clock
        self.sleep = sleep
        self.log = log or (lambda msg: print(f"guard-lease: {msg}", file=sys.stderr, flush=True))
        self.duration = duration
        self.poll = poll
        self.held = False
        # True when a holder further up (WIB_GUARD_LEASE) already holds it: this one neither renews nor releases.
        self.nested = False
        # Set when a renewal finds the Lease gone or someone else's: the guards were no longer this holder's alone.
        self.lost: str | None = None
        self._lock = threading.Lock()

    # --- kubectl ------------------------------------------------------------------------------------------------
    def _env(self) -> dict[str, str]:
        env = dict(os.environ)
        if self.kubeconfig:
            env["KUBECONFIG"] = self.kubeconfig
        if self.profile:
            env["AWS_PROFILE"] = self.profile
        return env

    def _kubectl(self, *args: str, stdin: str | None = None) -> tuple[int, str, str]:
        p = self.runner(["kubectl", "--context", self.context, *args], capture_output=True, text=True, timeout=60,
                        env=self._env(), input=stdin)
        return p.returncode, p.stdout or "", p.stderr or ""

    def read(self) -> dict | None:
        rc, out, err = self._kubectl("-n", NAMESPACE, "get", "lease", NAME, "--ignore-not-found", "-o", "json")
        if rc != 0:
            raise RuntimeError(f"could not read Lease {NAMESPACE}/{NAME}: {(err or out).strip()[:200]}")
        return json.loads(out) if out.strip() else None

    def _manifest(self, now: float, base: dict | None = None, acquired: float | None = None) -> str:
        spec = {"holderIdentity": self.holder, "leaseDurationSeconds": self.duration,
                "acquireTime": micro_time(acquired if acquired is not None else now), "renewTime": micro_time(now)}
        meta = {"name": NAME, "namespace": NAMESPACE,
                "labels": {"app.kubernetes.io/part-of": "watch-it-burn", "watch-it-burn/lock": "guards"}}
        if base is not None:
            meta["resourceVersion"] = (base.get("metadata") or {}).get("resourceVersion", "")
        return json.dumps({"apiVersion": "coordination.k8s.io/v1", "kind": "Lease", "metadata": meta, "spec": spec})

    # --- the lock -----------------------------------------------------------------------------------------------
    def try_acquire(self) -> tuple[bool, dict | None]:
        """One attempt: create the Lease, or take it over when it is expired. Returns (won, the Lease it found)."""
        now = self.clock()
        rc, out, err = self._kubectl("create", "-f", "-", "-o", "json", stdin=self._manifest(now))
        if rc == 0:
            return True, None
        if "AlreadyExists" not in err + out:
            raise RuntimeError(f"could not create Lease {NAMESPACE}/{NAME}: {(err or out).strip()[:200]}")
        lease = self.read()
        if lease is None:
            return False, None  # released between the create and the read: try again at once
        if (lease.get("spec") or {}).get("holderIdentity") == self.holder:
            return True, lease  # ours already (a retry after a create whose answer was lost)
        if not expired(lease, now):
            return False, lease
        rc, out, err = self._kubectl("replace", "-f", "-", "-o", "json", stdin=self._manifest(now, base=lease))
        if rc == 0:
            self.log(f"took over an expired lock: {describe(lease, now)}")
            return True, None
        if "Conflict" in err + out or "NotFound" in err + out:
            return False, None  # another holder won the race for it: look again
        raise RuntimeError(f"could not take over Lease {NAMESPACE}/{NAME}: {(err or out).strip()[:200]}")

    def acquire(self, wait: float = WAIT_S) -> None:
        """Take the lock, waiting up to `wait` seconds for its holder; raise LeaseBusy naming the holder after."""
        above = held_map().get(self.context)
        if above:
            self.nested, self.held, self.holder = True, True, above
            return
        start = self.clock()
        last_note = None
        while True:
            won, lease = self.try_acquire()
            if won:
                self.held = True
                self.log(f"holding {NAME} on {self.context} as {self.holder!r}")
                return
            now = self.clock()
            if now - start >= wait:
                raise LeaseBusy(f"gave up after {int(now - start)} s: {describe(lease, now)} on {self.context}")
            if lease is None:
                self.sleep(1)  # released or raced between two calls: look again soon
                continue
            if last_note is None or now - last_note >= WAIT_NOTE_S:
                self.log(f"waiting for {self.context}: {describe(lease, now)}")
                last_note = now
            self.sleep(self.poll)

    def renew(self) -> bool:
        """Push renewTime forward. False, with `lost` set, when the Lease is gone or names someone else."""
        if self.nested or not self.held:
            return True
        with self._lock:
            lease = self.read()
            spec = (lease or {}).get("spec") or {}
            if lease is None or spec.get("holderIdentity") != self.holder:
                self.lost = f"the lock was lost: {describe(lease, self.clock())}"
                self.held = False
                self.log(self.lost)
                return False
            acquired = parse_micro_time(spec.get("acquireTime"))
            rc, out, err = self._kubectl("replace", "-f", "-", "-o", "json",
                                         stdin=self._manifest(self.clock(), base=lease, acquired=acquired))
            if rc != 0:
                self.log(f"renewal failed, will retry: {(err or out).strip()[:200]}")
            return True

    def release(self, unsure: bool = False) -> None:
        """Delete the Lease if it is still this holder's, with its resourceVersion as the precondition. `unsure` is
        for an acquire that was interrupted: whether it won is not known, so a Lease that is not ours is no loss."""
        if self.nested or not (self.held or unsure):
            return
        with self._lock:
            self.held = False
            lease = self.read()
            if lease is None or (lease.get("spec") or {}).get("holderIdentity") != self.holder:
                if not unsure:
                    self.lost = self.lost or f"the lock was lost before release: {describe(lease, self.clock())}"
                    self.log(self.lost)
                return
            rv = (lease.get("metadata") or {}).get("resourceVersion", "")
            body = json.dumps({"kind": "DeleteOptions", "apiVersion": "v1",
                               "preconditions": {"resourceVersion": rv}})
            rc, out, err = self._kubectl("delete", "--raw", API_PATH, "-f", "-", stdin=body)
            if rc != 0:
                self.log(f"could not release {NAME} on {self.context}: {(err or out).strip()[:200]}; "
                         f"it frees itself {self.duration} s after its last renewal")
            else:
                self.log(f"released {NAME} on {self.context}")


@contextmanager
def hold(context: str, kubeconfig: str | None = None, profile: str | None = None, what: str = "",
         wait: float = WAIT_S, renew_every: float = RENEW_S, **kw) -> Iterator[GuardLease]:
    """Hold the lock for the body: acquire (or join a holder further up), renew in the background, release after.
    WIB_GUARD_LEASE names the context for the body's own children, and is put back as it was afterwards."""
    lease = GuardLease(context, kubeconfig, profile, what, **kw)
    try:
        lease.acquire(wait)
    except LeaseBusy:
        raise
    except BaseException:
        # Interrupted (a SIGTERM, a ^C) after a create that may have won: delete the Lease if it is ours.
        lease.release(unsure=True)
        raise
    before = os.environ.get(ENV)
    stop = threading.Event()
    renewer = None
    if not lease.nested:
        os.environ[ENV] = json.dumps({**held_map(), context: lease.holder})

        def renew_loop() -> None:
            while not stop.wait(renew_every):
                try:
                    if not lease.renew():
                        return
                except Exception as e:  # noqa: BLE001 - a failed renewal is retried, the Lease outlives a blip
                    lease.log(f"renewal failed, will retry: {e}")

        renewer = threading.Thread(target=renew_loop, name="guard-lease-renew", daemon=True)
        renewer.start()
    try:
        yield lease
    finally:
        stop.set()
        if renewer is not None:
            renewer.join(timeout=70)
            if before is None:
                os.environ.pop(ENV, None)
            else:
                os.environ[ENV] = before
        lease.release()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name, text in (("hold", "run a command while holding the lock"), ("show", "print who holds the lock"),
                       ("held", "exit 0 when WIB_GUARD_LEASE already names this context (no kubectl)"),
                       ("caller", "print the holder WIB_GUARD_LEASE names for this context, for X-WIB-Caller")):
        p = sub.add_parser(name, help=text)
        p.add_argument("--context", required=True, help="kube-context of the cluster (never the current one)")
        if name not in ("held", "caller"):
            p.add_argument("--kubeconfig", help="isolated kubeconfig, passed per command, never exported")
            p.add_argument("--profile", help="AWS_PROFILE for kubectl, passed per command")
        if name == "hold":
            p.add_argument("--what", default="", help="what is flipping guards, for the holder name")
            p.add_argument("--wait", type=float, default=WAIT_S,
                           help=f"seconds to wait for another holder before giving up (default {WAIT_S})")
            p.add_argument("command", nargs=argparse.REMAINDER, help="-- then the command to run")
    args = ap.parse_args(argv)

    if args.cmd == "held":
        return 0 if args.context in held_map() else 1
    if args.cmd == "caller":
        print(caller(args.context))
        return 0
    if args.cmd == "show":
        print(describe(GuardLease(args.context, args.kubeconfig, args.profile).read(), time.time()))
        return 0
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        ap.error("hold needs a command after --")
    what = args.what or " ".join(pathlib.Path(c).name for c in command[:2])
    # A SIGTERM (a timeout, a stopped run) never leaves the lock to expire. Before the command starts it unwinds
    # through hold, which deletes the Lease if it is ours; once the command runs it is passed on to the command, and
    # the lock is released when the command exits.
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(128 + signal.SIGTERM))
    try:
        with hold(args.context, args.kubeconfig, args.profile, what=what, wait=args.wait) as lease:
            child = subprocess.Popen(command)
            signal.signal(signal.SIGTERM, lambda *_: child.send_signal(signal.SIGTERM))
            rc = child.wait()
            rc = 128 - rc if rc < 0 else rc
        if lease.lost:
            print(f"guard-lease: {lease.lost}; another holder may have flipped guards during the command",
                  file=sys.stderr)
            return rc or 1
        return rc
    except LeaseBusy as e:
        print(f"guard-lease: {e}; nothing was run", file=sys.stderr)
        return BUSY_EXIT


if __name__ == "__main__":
    sys.exit(main())
