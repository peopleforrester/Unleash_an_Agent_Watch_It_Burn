# ABOUTME: The Night Before stage-switch check as one command (#1183, part of #1146): each stage switch run in the private
# ABOUTME: terminal, both clusters' /controls judged PASS or FAIL after it, then guards-off and guardrails-off, under the lock.
"""Runs every stage switch the way the presenter types it, and judges it on both KubeCon clusters.

    python3 verify/stage_switch_run.py --context watch-it-burn-private --kubeconfig "$KUBECONFIG" --profile accen-dev

The context is the private cluster's, and it is required: the command never falls back to the current-context
(CLAUDE.md, kube-context safety). Before anything is switched, the context's cluster-identity ConfigMap and the
private bot's /controls must both name burritobot-private, by the probe's judge_identity, so the switches cannot run
in another cluster's terminal.

What it does, in order, holding both clusters' guard lock (verify/guard_lease.py, the Lease agent/wib-guard-lock,
through hold_switch, as the probe does) from the first read to the last:

1. Reads both clusters' /controls (https://burritobot-private.burritobot.co and https://attackme.burritobot.co, no
   login). When a field the closing commands turn off reads anything but off on either cluster, it stops there,
   switching nothing (exit 4): the run ends by turning everything off, so starting from another state would not
   leave the clusters as found. A field the pinned guard-proxy does not send yet (stage_switch_check.WAITS_ON,
   agency_scoped today) does not stop it.
2. Runs guardrails-on, guard-agency-on, guard-input-on and guard-mcp-on, in talk order, each in the private
   terminal pod through kubecon_probe.TERMINAL_EXEC (`kubectl exec deploy/web-terminal -c ttyd -- bash
   /home/student/<switch>`), printing what the terminal printed. After each it waits out guard-proxy's 5-second
   /controls cache (kubecon_probe.CONTROLS_CACHE_S), reads both clusters again, and prints
   stage_switch_check.judge_switch's PASS or FAIL per cluster, the read before it being the read after the one
   before. A switch the terminal answers with a non-zero exit is a FAIL of its own (the `terminal` line); one that
   raises (a kubectl timeout) is a FAIL and the next switch still runs.
3. Runs guards-off, then guardrails-off, from the same terminal, whatever happened above: a failing switch, one
   that raised, a ^C or a SIGTERM. While they run, a ^C or SIGTERM is held until both have run. Then it waits out
   the cache, reads both clusters, and prints two verdicts per cluster: `start-state`, the judge's
   judge_start_state, and `as-found`, every field the closing commands turn off reading what it read in step 1.

Until this repo's guard-proxy pin carries agency_scoped (guard-proxy-agenticburn#76), guard-agency-on and the
start state are FAIL on both clusters, and the summary names them as waiting on #1132. #1132 itself, the three
Challenge 3 and 4 fixes switching both clusters from the private terminal, is on staging and in the terminals.

Exit codes: 0 every line PASS; 1 any FAIL; 2 no --context; 3 the lock stayed busy (nothing switched); 4 the clusters
were not at the start state (nothing switched); 130 after a ^C, 143 after a SIGTERM (the closing commands ran).

The command never reads or writes the agent/terminal-auth Secret: it runs the terminal's commands through kubectl
exec as the run's own identity, not through ttyd's login.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from typing import Any, Callable, NamedTuple

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import guard_lease  # noqa: E402
import kubecon_probe as kp  # noqa: E402
import stage_switch_check as ssc  # noqa: E402
from stage_switch_check import FAIL, PASS  # noqa: E402

TERMINAL_HOME = "/home/student"
SWITCHES = tuple(ssc.SWITCHES)
CLOSE = ("guards-off", "guardrails-off")
# guard-mcp-on waits up to 180 s per cluster for the gateway or kagent to serve its change (_c7wait in entrypoint.sh).
TERMINAL_TIMEOUT_S = 420
NOT_AT_START_EXIT = 4
INTERRUPTED_EXIT = 130
# What guards-off turns off besides the switches' own fields: the AI guards that are not stage switches.
CLOSE_ALSO = (("ai", "output"), ("ai", "budget"), ("ai", "topic"))
CLOSED_FIELDS = tuple(f for fields in ssc.SWITCHES.values() for f in fields) + CLOSE_ALSO
_MISSING = object()


def terminal_command(name: str) -> list[str]:
    """The kubectl arguments that run one of the terminal's commands in the private terminal pod, as the probe does."""
    return [*kp.TERMINAL_EXEC, f"{TERMINAL_HOME}/{name}"]


def fetch_controls(host: str, timeout: float = 20) -> bytes | None:
    """One cluster's /controls, as guard-proxy sends it; None, said on stderr, when it could not be read."""
    try:
        with urllib.request.urlopen(f"https://{host}/controls", timeout=timeout) as r:
            return r.read()
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        print(f"stage-switch: GET https://{host}/controls failed: {e}", file=sys.stderr, flush=True)
        return None


class Row(NamedTuple):
    step: str
    cluster: str
    result: str
    reason: str


def _controls(cluster: str, raw: Any) -> tuple[dict | None, str]:
    """read_controls, plus the check that the read filed under a cluster answers as that cluster."""
    controls, why = ssc.read_controls(raw)
    if controls is None:
        return None, why
    host = controls.get("host")
    if host and kp.identity_name(host) != kp.identity_name(ssc.CLUSTERS[cluster]):
        return None, f"/controls answers as {host!r}, not {ssc.CLUSTERS[cluster]}"
    return controls, ""


def _value(controls: dict, field: tuple[str, str]) -> Any:
    return controls[field[0]].get(field[1], _MISSING)


def not_at_start(reads: dict[str, Any]) -> dict[str, list[str]]:
    """Per cluster, what keeps it from the start state the closing commands leave: a field that reads anything but
    false, or a read that cannot be judged. A field the pinned guard-proxy does not send yet (WAITS_ON) is not counted;
    one it no longer sends is. Empty when both clusters may be switched and closed again without a change."""
    out: dict[str, list[str]] = {}
    for cluster in ssc.CLUSTERS:
        controls, why = _controls(cluster, reads.get(cluster))
        if controls is None:
            out[cluster] = [why]
            continue
        bad = []
        for field in CLOSED_FIELDS:
            v = _value(controls, field)
            if v is _MISSING:
                if field not in ssc.WAITS_ON:
                    bad.append(f"{'.'.join(field)} is missing from /controls")
            elif v is not False:
                bad.append(f"{'.'.join(field)} reads {json.dumps(v)}")
        if bad:
            out[cluster] = bad
    return out


def judge_as_found(opening: dict[str, Any], closing: dict[str, Any]) -> dict[str, ssc.Verdict]:
    """PASS on a cluster when every field the closing commands turn off reads at the end what it read at the start."""
    verdicts = {}
    for cluster in ssc.CLUSTERS:
        first, why = _controls(cluster, opening.get(cluster))
        if first is None:
            verdicts[cluster] = ssc.Verdict(FAIL, f"the opening read cannot be compared: {why}")
            continue
        last, why = _controls(cluster, closing.get(cluster))
        if last is None:
            verdicts[cluster] = ssc.Verdict(FAIL, f"the closing read cannot be compared: {why}")
            continue
        moved = []
        for field in CLOSED_FIELDS:
            a, b = _value(first, field), _value(last, field)
            if a != b:
                show = lambda v: "missing" if v is _MISSING else json.dumps(v)  # noqa: E731
                moved.append(f"{'.'.join(field)} read {show(a)} at the start and {show(b)} at the end")
        verdicts[cluster] = (ssc.Verdict(FAIL, "; ".join(moved)) if moved else
                             ssc.Verdict(PASS, "every field the closing commands turn off reads as it did at the start"))
    return verdicts


class StageSwitchRun:
    """One run of the check against the private cluster's terminal. `runner` is subprocess.run's shape and carries
    every kubectl call, the guard lock's included; `fetch` reads one host's /controls."""

    def __init__(self, context: str, kubeconfig: str | None = None, profile: str | None = None, *,
                 runner: Callable = subprocess.run, fetch: Callable[[str], Any] = fetch_controls,
                 sleep: Callable[[float], None] = time.sleep, out: Callable[[str], None] | None = None,
                 lock_wait: float = guard_lease.WAIT_S, cache_s: float = kp.CONTROLS_CACHE_S,
                 lease_kw: dict | None = None) -> None:
        if not context:
            raise ValueError("the stage-switch check needs the private cluster's kube-context; it never falls back "
                             "to the current one")
        self.context = context
        self.kubeconfig = kubeconfig
        self.profile = profile
        self.runner = runner
        self.fetch = fetch
        self.sleep = sleep
        self.out = out or (lambda s: print(s, flush=True))
        self.lock_wait = lock_wait
        self.cache_s = cache_s
        self.lease_kw = lease_kw or {}
        self.cluster = kp.KubeconCluster(ssc.CLUSTERS["private"], context, profile, kubeconfig, 120, runner=runner)
        self.rows: list[Row] = []
        self.deferred: int | None = None

    # --- output ------------------------------------------------------------------------------------------------
    def _row(self, step: str, cluster: str, result: str, reason: str) -> None:
        self.rows.append(Row(step, cluster, result, reason))
        self.out(f"  {result}  {step:<16} {cluster:<10} {reason}")

    def _verdicts(self, step: str, verdicts: dict[str, ssc.Verdict]) -> None:
        for cluster, v in verdicts.items():
            self._row(step, cluster, v.result, v.reason)

    # --- the cluster -------------------------------------------------------------------------------------------
    def read_both(self) -> dict[str, Any]:
        return {cluster: self.fetch(host) for cluster, host in ssc.CLUSTERS.items()}

    def terminal(self, name: str) -> int:
        """Run one terminal command in the private terminal pod, print what it printed, and return its exit code. In
        a session of its own, so a ^C at the keyboard reaches this script and not a closing command midway."""
        args = terminal_command(name)
        self.out(f"$ kubectl --context {self.context} {' '.join(args)}")
        p = self.runner(["kubectl", "--context", self.context, *args], capture_output=True, text=True,
                        timeout=TERMINAL_TIMEOUT_S, env=self.cluster.env(), start_new_session=True)
        for line in ((p.stdout or "") + (p.stderr or "")).splitlines():
            self.out(f"    | {line}")
        return p.returncode

    def _run_terminal(self, name: str) -> None:
        """A terminal command as a step: a non-zero exit or a raise is a FAIL line; neither stops the run."""
        try:
            rc = self.terminal(name)
        except Exception as e:  # noqa: BLE001 - a kubectl timeout or a failed exec is a verdict, not the end
            self._row(name, "terminal", FAIL, f"raised {type(e).__name__}: {str(e)[:200]}")
            return
        if rc != 0:
            self._row(name, "terminal", FAIL, f"the terminal's {name} exited {rc}")

    # --- the run -----------------------------------------------------------------------------------------------
    def run(self) -> int:
        """The whole check. Returns the exit code; a ^C or SIGTERM comes back out as KeyboardInterrupt or SystemExit,
        after the closing commands ran and the lock was released."""
        self.out(f"stage-switch check: the switches run in {self.context}'s terminal, judged on "
                 f"{' and '.join(ssc.CLUSTERS.values())}")
        try:
            with guard_lease.hold_switch(self.context, self.kubeconfig, self.profile,
                                         what=f"stage_switch_run.py {self.context}", wait=self.lock_wait,
                                         runner=self.runner, **self.lease_kw) as lock:
                self.out(f"holding the guard lock on {', '.join(lock.contexts)} as {lock.holder!r}")
                code = self._held()
            # Read after the release, which also says so when the Lease was gone or someone else's by then.
            lost = lock.lost
        except guard_lease.LeaseBusy as e:
            self.out(f"\nSTAGE SWITCH CHECK NOT RUN: another holder kept the guard lock: {e} (nothing was switched)")
            return guard_lease.BUSY_EXIT
        if lost:
            self._row("guard-lock", "-", FAIL, f"{lost}: another run may have switched guards during the check")
            code = code or 1
        if code in (0, 1):
            code = self._summary()
        return code

    def _held(self) -> int:
        opening = self.read_both()
        controls, _ = _controls("private", opening.get("private"))
        ok, note = kp.judge_identity(ssc.CLUSTERS["private"], self.cluster.identity_host(),
                                     (controls or {}).get("host") or ssc.CLUSTERS["private"])
        if not ok:
            self._row("identity", "private", FAIL, note)
            self.out("\nSTAGE SWITCH CHECK NOT RUN: the context is not the private cluster (nothing was switched)")
            return 1
        self._row("identity", "private", PASS, note)
        blockers = not_at_start(opening)
        if blockers:
            for cluster, bad in blockers.items():
                self._row("start", cluster, FAIL, "; ".join(bad))
            self.out("\nSTAGE SWITCH CHECK NOT RUN: the clusters are not at the start state, and the closing "
                     "guards-off and guardrails-off would change that (nothing was switched). Turn them off from "
                     "the private terminal first, or find out who turned them on.")
            return NOT_AT_START_EXIT
        for cluster in ssc.CLUSTERS:
            self._row("start", cluster, PASS, "every field the closing commands turn off reads off")
        interrupted: BaseException | None = None
        before = opening
        try:
            for switch in SWITCHES:
                self._run_terminal(switch)
                self.sleep(self.cache_s)
                after = self.read_both()
                self._verdicts(switch, ssc.judge_switch(switch, before, after))
                before = after
        except (KeyboardInterrupt, SystemExit) as e:
            interrupted = e
            self._row("interrupted", "-", FAIL, f"{type(e).__name__} during the switches: closing anyway")
        finally:
            self._close(opening)
        if interrupted is not None:
            raise interrupted
        if self.deferred is not None:
            raise KeyboardInterrupt if self.deferred == signal.SIGINT else SystemExit(128 + self.deferred)
        return 0

    def _close(self, opening: dict[str, Any]) -> None:
        """guards-off then guardrails-off, with a ^C or SIGTERM held until both have run, then the start state."""
        def hold_signal(signum, _frame):
            self.deferred = signum
            self.out(f"(signal {signum} held: guards-off and guardrails-off run first)")
        saved = {}
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                saved[sig] = signal.signal(sig, hold_signal)
            except ValueError:  # not the main thread: nothing to hold
                pass
        try:
            for name in CLOSE:
                self._run_terminal(name)
            self.sleep(self.cache_s)
            closing = self.read_both()
            self._verdicts("start-state", ssc.judge_start_state(closing))
            self._verdicts("as-found", judge_as_found(opening, closing))
        finally:
            for sig, handler in saved.items():
                signal.signal(sig, handler)

    def _summary(self) -> int:
        fails = [r for r in self.rows if r.result == FAIL]
        waiting: dict[str, list[str]] = {}
        for r in fails:
            if "#1132" in r.reason:
                waiting.setdefault(r.step, []).append(r.cluster)
        self.out(f"\n{len(self.rows)} lines: {len(self.rows) - len(fails)} PASS, {len(fails)} FAIL")
        if waiting:
            self.out("waiting on #1132 (agency_scoped, guard-proxy-agenticburn#76, not yet in this repo's guard-proxy "
                     "pin): " + "; ".join(f"{step} on {', '.join(cs)}" for step, cs in waiting.items()))
        self.out("STAGE SWITCH CHECK GREEN" if not fails else "STAGE SWITCH CHECK RED")
        return 1 if fails else 0


def main(argv: list[str] | None = None, **kw) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--context", help="the private cluster's kube-context (required; never the current one)")
    ap.add_argument("--kubeconfig", help="isolated kubeconfig, passed per command, never exported")
    ap.add_argument("--profile", help="AWS_PROFILE for kubectl, passed per command")
    ap.add_argument("--lock-wait", type=float, default=None,
                    help=f"seconds to wait for another run's guard lock (default ${guard_lease.WAIT_ENV}, else "
                         f"{guard_lease.WAIT_S})")
    args = ap.parse_args(argv)
    if not args.context:
        print("stage_switch_run.py needs --context, the private cluster's kube-context: it runs the stage switches "
              "in that cluster's terminal and never falls back to the current-context", file=sys.stderr)
        return 2
    wait = guard_lease.default_wait() if args.lock_wait is None else args.lock_wait
    run = StageSwitchRun(args.context, args.kubeconfig, args.profile, lock_wait=wait, **kw)
    # A SIGTERM (a timeout, a stopped run) unwinds like a ^C, so the closing commands run and the lock is released.
    previous = signal.signal(signal.SIGTERM, lambda *_: sys.exit(128 + signal.SIGTERM))
    try:
        return run.run()
    except (KeyboardInterrupt, SystemExit) as e:
        run._summary()
        print("STAGE SWITCH CHECK INTERRUPTED: guards-off and guardrails-off ran (see above)", flush=True)
        return e.code if isinstance(e, SystemExit) and isinstance(e.code, int) else INTERRUPTED_EXIT
    finally:
        signal.signal(signal.SIGTERM, previous)


if __name__ == "__main__":
    sys.exit(main())
