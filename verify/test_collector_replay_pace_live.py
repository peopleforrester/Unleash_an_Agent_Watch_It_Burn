# ABOUTME: Live check of #1336's last criterion (#1371): with the traces processors behind the queued loopback, the
# ABOUTME: 500-phone replay on attackme finds the collector above one core or keeping pace, no span dropped, no restart.
# SUITE: e2e
"""Needs kubectl, COMMUNITY_CONTEXT naming the kube-context of watch-it-burn-community (attackme, the live public bot),
and the public internet. Every missing prerequisite is a failure, never a skip.

#1334's 500-phone replay held the community collector flat at one core and working about 70 s past its last reply,
and #1336's reading of the same replay (run 20295, 2026-11-11) found agentgateway's SDK giving up four span batches at
its 10 s export deadline. #1336 split the traces pipeline: `traces/intake` batches the senders' spans onto the queued
`otlp_grpc/relay` exporter, whose two consumers feed this pod's own `otlp/relay` receiver, and the `traces` pipeline
behind it runs the masks once per relay request, so two batches are masked at once. Its criterion: "the traces
pipeline is changed so the heavy processors run on more than one core, and a replay reading shows the collector above
one core or keeping pace, with no restart". verify/test_collector_relay.py holds the shape offline; this runs the
reading on the cluster, and fails when the criterion stops holding:

1. the context is attackme: its cluster-identity public-host is attackme's;
2. the cluster runs the split: the live relay.yaml's `traces/intake` takes `otlp`, runs nothing that reads span
   content and exports to `otlp_grpc/relay` alone; `traces` takes `otlp/relay` alone and runs no `batch`; the relay
   exporter has a sending queue with two consumers or more; the collector's CPU limit is above one core; and the
   DaemonSet has rolled out with every pod ready. When any of these fails the replay is not sent and nothing is spent;
3. the replay is run 20295's, `load_replay.py attackme.burritobot.co --yes --source catalog --users 500 --seed 1336`,
   held under the cluster's guard lock (verify/guard_lease.py), and it sent every planned turn, each came back, at
   least MIN_SERVED were served (the room's ceiling: guard-proxy's cluster window refuses the rest) and the cost cap
   refused none, and at least MIN_SPANS spans crossed the loopback, so the collector had real work;
4. above one core or keeping pace: from PRE_S before the replay to POST_S after it, the kubelet's CPU counter for each
   collector pod and the collector's own :8888 counters (through a port-forward) are read every SAMPLE_S. The
   collector passes when a kubelet interval during the replay read above ABOVE_CORES, or when, by PACE_S after the
   replay's end, every pod was idle (under IDLE_CORES for every interval from then on) and the relay's queue held under
   one request's RELAY_REQUEST spans at every scrape from then on. ABOVE_CORES is 1.2, not 1.0: before the split the
   collector's one busy goroutine read 0.86 to 1.03 a kubelet interval (run 20295), so a reading of 1.03 is one core;
   PACE_S is the "about 15 s" of #1336's entry;
5. no span was dropped: the collector's receivers refused and failed none on `otlp` and `otlp/relay`, the relay
   exporter's `enqueue_failed` and `send_failed` counters did not move, and no sender (agentgateway, workshop-agent,
   guard-proxy, evil-mcp-shim) logged an export it gave up on (`Export.Failed`, `DeadlineExceeded`, `traces export`,
   `export timeout`, `Queue is full`, `telemetry data will be lost`);
6. no restart: the collector's pods are the same before and after, with the same restart counts, and the readings
   covered the whole window (a CPU interval that opens before the replay and one that closes after PACE_S; a scrape of
   each pod before the replay and after PACE_S; no gap over GAP_S).

What it changes, and puts back. The replay spends about $3.70 of Bedrock on the public bot (run 20295: $3.7144 for
384 served turns), each prompt marked [[wib-probe]] so the room's feed skips it; it stays on /cost until
`./fleet.sh reset-bot watch-it-burn-community` before the room opens. The catalog's C6 asks make the bot deploy
`joker-*` workloads, and afterwards every object in namespace agent that workshop-mcp created during the replay is
deleted and taken off the one deployments page by test_load_replay_live.py's own cleanup, whatever the verdict. The
port-forwards end with the sampler.

verify/test_collector_replay_pace_live_checks.py runs these judges offline on run 20295's reading before the split,
which fails, on readings that pass by each arm, and on each way the criterion can stop holding.

Usage: COMMUNITY_CONTEXT=<kube-context> [KUBECONFIG=<isolated file>] [AWS_PROFILE=<profile>] \\
           python3 verify/test_collector_replay_pace_live.py
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import json
import os
import pathlib
import re
import select
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from typing import Callable

import yaml

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import guard_lease  # noqa: E402
import test_load_replay_live as lrl  # noqa: E402

kp = lrl.kp
TARGET = "attackme.burritobot.co"
USERS = 500
SEED = 1336
LOAD_REPLAY = HERE / "load_replay.py"
REPLAY_TIMEOUT_S = 1800            # load_replay.py's --deadline is 900 s; a sent turn then has nginx's 285 s to end

NAMESPACE = "monitoring"
DAEMONSET = CONFIGMAP = "otel-collector-opentelemetry-collector-agent"
KEY = "relay"
CONTAINER = "opentelemetry-collector"
COLLECTOR_SELECTOR = "app.kubernetes.io/instance=otel-collector,component=agent-collector"
METRICS_PORT = 8888
INTAKE, TRACES = "traces/intake", "traces"
RECEIVER, EXPORTER = "otlp/relay", "otlp_grpc/relay"
# What the intake may run: the chart's prepended k8s_attributes and #1336's three, none of which reads span content.
INTAKE_OK = {"k8s_attributes", "memory_limiter", "k8s_attributes/intake", "batch"}
SENDERS = ("agentgateway", "workshop-agent", "guard-proxy", "evil-mcp-shim")
EXPORT_FAIL = re.compile(r"Export\.Failed|DeadlineExceeded|traces export|export timeout|Queue is full"
                         r"|telemetry data will be lost", re.I)

ABOVE_CORES = 1.2                  # a kubelet interval above this is more than one goroutine's core
IDLE_CORES = 0.1                   # the collector at rest reads under 0.01 core
PACE_S = 15                        # "idle within about 15 s of the replay's end" (#1336's entry)
RELAY_REQUEST = 256                # otlp_grpc/relay's request size: a queue under it holds no backlog
MIN_SERVED = 200                   # run 20295: 384 served, 1,116 refused by the cluster window
MIN_SPANS = 1000                   # run 20295: 9,275 spans over the replay
SAMPLE_S = 5
PRE_S = 30
POST_S = 60
GAP_S = 60
SKEW_S = 10


def replay_argv(json_out: pathlib.Path) -> list[str]:
    """Run 20295's replay, word for word, with --json-out added so the verdict is read from its report."""
    return [sys.executable, str(LOAD_REPLAY), TARGET, "--yes", "--source", "catalog", "--users", str(USERS),
            "--seed", str(SEED), "--json-out", str(json_out)]


# --- the judges, run offline by test_collector_replay_pace_live_checks.py --------------------------------------------
def cores(raw) -> float:
    s = str(raw or "0")
    return float(s[:-1]) / 1000 if s.endswith("m") else float(s)


def judge_synced(relay_text: str | None, ds: dict | None, pods: dict | None) -> list[tuple[bool, str, str]]:
    """Does the cluster run #1336's split? (ok, check, detail) each. `pods` is collector_pods()' reading."""
    out = []
    relay = None
    try:
        relay = yaml.safe_load(relay_text) if relay_text else None
    except yaml.YAMLError:
        relay = None
    if not isinstance(relay, dict):
        return [(False, f"the relay ConfigMap {NAMESPACE}/{CONFIGMAP} holds a {KEY} config",
                 "no such ConfigMap or key" if not relay_text else f"{KEY} is not a YAML map")]
    pipes = (relay.get("service") or {}).get("pipelines") or {}
    intake, traces = pipes.get(INTAKE) or {}, pipes.get(TRACES) or {}
    extra = [p for p in intake.get("processors") or [] if p not in INTAKE_OK]
    out.append((intake.get("receivers") == ["otlp"] and intake.get("exporters") == [EXPORTER] and not extra
                and "batch" in (intake.get("processors") or []),
                f"{INTAKE} takes otlp, batches, runs nothing that reads span content and exports to {EXPORTER} alone",
                f"{INTAKE}: {intake or 'missing'}"))
    tp = traces.get("processors") or []
    out.append((traces.get("receivers") == [RECEIVER] and "batch" not in tp and "transform/coc_mask" in tp,
                f"{TRACES} takes {RECEIVER} alone and runs the masks with no batch, one relay request a goroutine",
                f"{TRACES}: receivers {traces.get('receivers')}, processors {tp}"))
    q = (((relay.get("exporters") or {}).get(EXPORTER) or {}).get("sending_queue")) or {}
    out.append((bool(q.get("enabled")) and int(q.get("num_consumers") or 0) >= 2,
                f"{EXPORTER} has a sending queue with two consumers or more", f"sending_queue: {q or 'none'}"))
    spec = ((ds or {}).get("spec") or {}).get("template", {}).get("spec", {})
    limit = next((cores(((c.get("resources") or {}).get("limits") or {}).get("cpu"))
                  for c in spec.get("containers") or [] if c.get("name") == CONTAINER), 0.0)
    out.append((limit > 1, "the collector's CPU limit is above one core", f"limit {limit:g} CPU"))
    st, md = (ds or {}).get("status") or {}, (ds or {}).get("metadata") or {}
    want = st.get("desiredNumberScheduled")
    rolled = (ds is not None and st.get("observedGeneration") == md.get("generation") and bool(want)
              and st.get("updatedNumberScheduled") == want and st.get("numberReady") == want)
    out.append((rolled and bool(pods) and all(p["ready"] for p in pods.values()),
                "the collector DaemonSet has rolled out and its pods are ready",
                f"status {st or 'no DaemonSet'}; pods {pods}"))
    return out


METRICS = {
    # name: (metric, label, values the label may take)
    "intake_accepted": ("otelcol_receiver_accepted_spans", "receiver", ("otlp",)),
    "relay_accepted": ("otelcol_receiver_accepted_spans", "receiver", (RECEIVER,)),
    "refused": ("otelcol_receiver_refused_spans", "receiver", ("otlp", RECEIVER)),
    "failed": ("otelcol_receiver_failed_spans", "receiver", ("otlp", RECEIVER)),
    "relay_sent": ("otelcol_exporter_sent_spans", "exporter", (EXPORTER,)),
    "relay_enqueue_failed": ("otelcol_exporter_enqueue_failed_spans", "exporter", (EXPORTER,)),
    "relay_send_failed": ("otelcol_exporter_send_failed_spans", "exporter", (EXPORTER,)),
    "relay_queue": ("otelcol_exporter_queue_size", "exporter", (EXPORTER,)),
}
_SERIES = re.compile(r'^([a-zA-Z_:][a-zA-Z0-9_:]*)(?:\{(.*)\})?\s+(\S+)')
_LABEL = re.compile(r'([a-zA-Z_][a-zA-Z0-9_]*)="((?:[^"\\]|\\.)*)"')


def reduce_metrics(text: str) -> dict[str, float]:
    """The collector's Prometheus text summed into METRICS' names. A series that is absent reads 0, as the collector
    writes no failure series until a failure happens; `present` counts the intake series, so a renamed metric shows."""
    out = {k: 0.0 for k in METRICS}
    out["present"] = 0.0
    for line in text.splitlines():
        m = _SERIES.match(line)
        if not m or line.startswith("#"):
            continue
        name, labels = m.group(1), dict(_LABEL.findall(m.group(2) or ""))
        try:
            value = float(m.group(3))
        except ValueError:
            continue
        for key, (metric, label, values) in METRICS.items():
            if name == metric and labels.get(label) in values:
                out[key] += value
                if key == "intake_accepted":
                    out["present"] += 1
    return out


@dataclasses.dataclass
class Reading:
    """What the sampler and the replay left: everything the verdict reads. Times are epoch seconds."""
    report: dict | None
    t_start: float
    t_end: float
    cpu: list[tuple[str, float, int]]                  # (pod, kubelet sample time, usageCoreNanoSeconds)
    scrapes: list[tuple[float, str, dict]]             # (time, pod, reduce_metrics)
    scrape_errors: list[str]
    pods_before: dict
    pods_after: dict
    sender_lines: list[str] | None


def intervals(cpu: list[tuple[str, float, int]]) -> dict[str, list[tuple[float, float, float]]]:
    """Per pod, the kubelet's consecutive distinct samples as (from, to, cores)."""
    by: dict[str, dict[float, int]] = {}
    for pod, t, ns in cpu:
        by.setdefault(pod, {})[t] = ns
    out: dict[str, list[tuple[float, float, float]]] = {}
    for pod, pts in by.items():
        ts = sorted(pts)
        out[pod] = [(a, b, (pts[b] - pts[a]) / 1e9 / (b - a)) for a, b in zip(ts, ts[1:]) if b - a >= 1]
    return out


def idle_from(iv: list[tuple[float, float, float]], t_end: float) -> float | None:
    """The start of the idle tail after t_end: every interval from it on read under IDLE_CORES. None when the last
    interval was not idle."""
    start = None
    for a, b, c in iv:
        if b <= t_end:
            continue
        if c < IDLE_CORES:
            start = a if start is None else start
        else:
            start = None
    return start


def deltas(r: Reading) -> dict[str, float]:
    """Each counter's last scrape minus its first, per pod, summed over the pods read before the replay."""
    delta = {k: 0.0 for k in METRICS}
    for pod in r.pods_before:
        mine = sorted(((t, m) for t, p, m in r.scrapes if p == pod), key=lambda x: x[0])
        if mine:
            for k in METRICS:
                delta[k] += mine[-1][1][k] - mine[0][1][k]
    return delta


def judge(r: Reading) -> list[tuple[bool, str, str]]:
    """Above one core or keeping pace, no span dropped, no restart. (ok, check, detail) each."""
    if r.report is None:
        return [(False, "the replay wrote its report", "load_replay.py wrote no --json-out report (output above)")]
    out = []
    rep, o = r.report, r.report.get("outcomes") or {}
    planned = USERS * 3
    out.append((rep.get("users") == USERS and rep.get("planned") == planned and rep.get("sent") == planned
                and rep.get("answered") == planned,
                f"the replay sent every planned turn ({USERS} users x 3) and each came back",
                f"users {rep.get('users')}, planned {rep.get('planned')}, sent {rep.get('sent')}, answered "
                f"{rep.get('answered')}" + (f", stopped: {rep['stop_reason']}" if rep.get("stop_reason") else "")))
    out.append((int(o.get("served") or 0) >= MIN_SERVED and int(o.get("cost_cap") or 0) == 0,
                f"the replay reached the room's ceiling: {MIN_SERVED} or more served and none refused by the cost cap",
                f"served {o.get('served')}, cluster window {o.get('cluster_limit')}, cost cap {o.get('cost_cap')}"))

    end = r.t_end + PACE_S
    pods = sorted(r.pods_before)
    out.append((bool(pods) and r.pods_before == r.pods_after,
                "no restart: the collector's pods and their restart counts are the same before and after",
                f"before {r.pods_before}, after {r.pods_after}"))

    # coverage
    iv = intervals(r.cpu)
    gaps = []
    for pod in pods:
        pts = sorted({t for p, t, _ in r.cpu if p == pod})
        pts_ok = bool(pts) and pts[0] <= r.t_start and pts[-1] >= end
        gap = max((b - a for a, b in zip(pts, pts[1:])), default=float("inf"))
        if not pts_ok or gap > GAP_S:
            gaps.append(f"{pod}: kubelet samples {len(pts)}, first {pts[0] - r.t_start if pts else None} s from the "
                        f"replay's start, last {pts[-1] - r.t_end if pts else None} s after its end, widest gap {gap} s")
        st = sorted(t for t, p, _ in r.scrapes if p == pod)
        sgap = max((b - a for a, b in zip(st, st[1:])), default=float("inf"))
        if not st or st[0] > r.t_start or st[-1] < end or sgap > GAP_S:
            gaps.append(f"{pod}: scrapes {len(st)}, widest gap {sgap} s")
        if any(m["present"] == 0 for t, p, m in r.scrapes if p == pod):
            gaps.append(f"{pod}: a scrape had no otelcol_receiver_accepted_spans{{receiver=\"otlp\"}} series")
    out.append((bool(pods) and not gaps,
                f"the kubelet's CPU and the collector's counters were read from before the replay to {PACE_S} s past "
                f"its end, no gap over {GAP_S} s",
                "; ".join(gaps + [f"scrape errors: {r.scrape_errors[:5]}"] if r.scrape_errors else gaps)))

    delta = deltas(r)
    out.append((delta["intake_accepted"] >= MIN_SPANS and delta["relay_accepted"] >= MIN_SPANS,
                f"the collector had real work: {MIN_SPANS} or more spans in at otlp and across the loopback",
                f"otlp accepted {delta['intake_accepted']:,.0f}, {RECEIVER} accepted {delta['relay_accepted']:,.0f}"))

    # above one core or keeping pace
    peaks = {p: max((c for a, b, c in iv.get(p, []) if b > r.t_start and a < end), default=0.0) for p in pods}
    above = any(c > ABOVE_CORES for c in peaks.values())
    idle = {p: idle_from(iv.get(p, []), r.t_end) for p in pods}
    idle_ok = bool(pods) and all(t is not None and t <= end for t in idle.values())
    late_queue = [(round(t - r.t_end, 1), p, m["relay_queue"]) for t, p, m in r.scrapes
                  if t >= end and m["relay_queue"] >= RELAY_REQUEST]
    pace = idle_ok and not late_queue
    out.append((above or pace,
                f"the collector went above one core ({ABOVE_CORES:g}) during the replay, or kept pace: idle and its "
                f"relay queue under {RELAY_REQUEST} spans within {PACE_S} s of the replay's end",
                "peak " + ", ".join(f"{p} {c:.2f} CPU" for p, c in peaks.items()) + "; idle from "
                + ", ".join(f"{p} {'never' if t is None else f'{t - r.t_end:+.0f} s'}" for p, t in idle.items())
                + " of the replay's end" + (f"; relay queue after {PACE_S} s: {late_queue[:5]}" if late_queue else "")))

    # no span dropped
    out.append((delta["refused"] == 0 and delta["failed"] == 0,
                f"the collector's receivers refused and failed no span (otlp, {RECEIVER})",
                f"refused {delta['refused']:,.0f}, failed {delta['failed']:,.0f}"))
    out.append((delta["relay_enqueue_failed"] == 0 and delta["relay_send_failed"] == 0,
                f"{EXPORTER} turned no span away and failed no send",
                f"enqueue_failed {delta['relay_enqueue_failed']:,.0f}, send_failed {delta['relay_send_failed']:,.0f}"))
    if r.sender_lines is None:
        out.append((False, "the senders' logs over the replay were read", "kubectl could not read them"))
    else:
        out.append((not r.sender_lines, "no sender gave up a span export (" + ", ".join(SENDERS) + ")",
                    f"{len(r.sender_lines)}: " + " | ".join(ln[:240] for ln in r.sender_lines[:6])))
    return out


# --- the cluster -----------------------------------------------------------------------------------------------------
def _epoch(text: str) -> float:
    return dt.datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()


class PaceCluster(lrl.LiveCluster):
    """test_load_replay_live.py's cluster (its cleanup reads and deletes), plus the collector's reads."""

    def collector_pods(self) -> dict:
        """name: {node, restarts, ready} for each collector pod."""
        d = self.get_json("-n", NAMESPACE, "get", "pods", "-l", COLLECTOR_SELECTOR) or {}
        out = {}
        for p in d.get("items") or []:
            cs = [c for c in (p.get("status") or {}).get("containerStatuses") or [] if c.get("name") == CONTAINER]
            out[p["metadata"]["name"]] = {"node": (p.get("spec") or {}).get("nodeName"),
                                          "restarts": sum(int(c.get("restartCount") or 0) for c in cs),
                                          "ready": bool(cs) and all(c.get("ready") for c in cs)}
        return out

    def relay_text(self) -> str | None:
        cm = self.get_json("-n", NAMESPACE, "get", "configmap", CONFIGMAP)
        return ((cm or {}).get("data") or {}).get(KEY)

    def daemonset(self) -> dict | None:
        return self.get_json("-n", NAMESPACE, "get", "daemonset", DAEMONSET)

    def cpu(self, node: str) -> dict[str, tuple[float, int]]:
        """pod: (sample time, usageCoreNanoSeconds) of the collector container, from the node's kubelet."""
        rc, out = self._stdout_rc("get", "--raw", f"/api/v1/nodes/{node}/proxy/stats/summary")
        if rc != 0:
            raise RuntimeError(f"stats/summary of {node} could not be read")
        res = {}
        for p in json.loads(out).get("pods") or []:
            ref = p.get("podRef") or {}
            if ref.get("namespace") != NAMESPACE:
                continue
            for c in p.get("containers") or []:
                cpu = c.get("cpu") or {}
                if c.get("name") == CONTAINER and cpu.get("time") and cpu.get("usageCoreNanoSeconds") is not None:
                    res[ref.get("name")] = (_epoch(cpu["time"]), int(cpu["usageCoreNanoSeconds"]))
        return res

    def port_forward(self, pod: str) -> tuple[subprocess.Popen, int]:
        """kubectl port-forward to the pod's :8888 on a port kubectl picks; the process and the local port."""
        p = subprocess.Popen(["kubectl", "--context", self.context, "-n", NAMESPACE, "port-forward", f"pod/{pod}",
                              f":{METRICS_PORT}"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                             env=self.env())
        deadline = time.time() + 20
        seen = []
        while time.time() < deadline:
            ready, _, _ = select.select([p.stdout], [], [], 1)
            if ready:
                line = p.stdout.readline()
                seen.append(line.strip())
                m = re.search(r"Forwarding from 127\.0\.0\.1:(\d+)", line)
                if m:
                    threading.Thread(target=lambda: [None for _ in p.stdout], daemon=True).start()  # keep it drained
                    return p, int(m.group(1))
                if not line and p.poll() is not None:
                    break
        p.kill()
        raise RuntimeError(f"port-forward to {pod}:{METRICS_PORT} did not start: {' | '.join(seen)[:300]}")

    def sender_log_lines(self, since: float) -> list[str] | None:
        """The senders' log lines since `since` that report an export given up."""
        lines = []
        for name in SENDERS:
            dep = self.get_json("-n", "agent", "get", "deployment", name)
            labels = (((dep or {}).get("spec") or {}).get("selector") or {}).get("matchLabels") or {}
            if not labels:
                return None
            sel = ",".join(f"{k}={v}" for k, v in sorted(labels.items()))
            rc, out = self._stdout_rc("-n", "agent", "logs", "-l", sel, "--all-containers", "--prefix", "--tail=-1",
                                      "--max-log-requests=10", f"--since-time={lrl.stamp(since - SKEW_S)}")
            if rc != 0:
                return None
            lines += [ln.strip() for ln in out.splitlines() if EXPORT_FAIL.search(ln)]
        return lines


class Sampler:
    """Reads the kubelet's CPU counter and the collector's :8888 counters for each pod every SAMPLE_S, in a thread."""

    def __init__(self, cluster: PaceCluster, pods: dict, every: float = SAMPLE_S,
                 clock: Callable[[], float] = time.time) -> None:
        self.cluster, self.pods, self.every, self.clock = cluster, pods, every, clock
        self.cpu: list[tuple[str, float, int]] = []
        self.scrapes: list[tuple[float, str, dict]] = []
        self.errors: list[str] = []
        self.forwards: dict[str, tuple[subprocess.Popen, int]] = {}
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def scrape(self, pod: str) -> str:
        import urllib.request
        _, port = self.forwards[pod]
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/metrics", timeout=10) as r:  # loopback port-forward
            return r.read().decode("utf-8", "replace")

    def sample_once(self) -> None:
        for node in sorted({p["node"] for p in self.pods.values()}):
            try:
                for pod, (t, ns) in self.cluster.cpu(node).items():
                    if pod in self.pods:
                        self.cpu.append((pod, t, ns))
            except Exception as e:  # noqa: BLE001 - a missed sample shows as a gap in the verdict
                self.errors.append(f"cpu {node}: {e}")
        for pod in self.pods:
            t = self.clock()
            try:
                self.scrapes.append((t, pod, reduce_metrics(self.scrape(pod))))
            except Exception as e:  # noqa: BLE001 - as above
                self.errors.append(f"scrape {pod}: {type(e).__name__}: {e}")

    def start(self) -> None:
        for pod in self.pods:
            self.forwards[pod] = self.cluster.port_forward(pod)
        self.sample_once()

        def loop() -> None:
            while not self._stop.wait(self.every):
                self.sample_once()
        self._thread = threading.Thread(target=loop, name="pace-sampler", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=60)
        if self.forwards:
            self.sample_once()
        for p, _ in self.forwards.values():
            p.terminate()
            try:
                p.wait(timeout=10)
            except subprocess.TimeoutExpired:
                p.kill()


def run_checks(cluster, replay: Callable[[], dict | None], check: Callable[[str, bool, str], None],
               sampler_for: Callable = Sampler, hold: Callable[[Callable[[], None]], bool] | None = None,
               now: Callable[[], float] = time.time, sleep: Callable[[float], None] = time.sleep) -> Reading | None:
    """Every check after the prerequisites, against one cluster. The reading when the replay ran, else None."""
    host = cluster.identity_host()
    check(f"the context is attackme ({TARGET})", kp.identity_name(host) == kp.identity_name(TARGET),
          f"its cluster-identity public-host is {host!r}")
    if kp.identity_name(host) != kp.identity_name(TARGET):
        return None
    pods = cluster.collector_pods()
    synced = judge_synced(cluster.relay_text(), cluster.daemonset(), pods)
    for ok, name, detail in synced:
        check(name, ok, detail)
    if not all(ok for ok, _, _ in synced):
        check("the 500-phone replay ran", False, "not sent, so nothing is spent: #1336's split is not what runs")
        return None

    box: dict = {}

    def body() -> None:
        before_uids = {(o.get("metadata") or {}).get("uid") for o in cluster.bot_objects()}
        pods_before = {n: p["restarts"] for n, p in cluster.collector_pods().items()}
        sampler = sampler_for(cluster, cluster.collector_pods())
        sampler.start()
        report, t_start, t_end = None, now(), None
        try:
            sleep(PRE_S)
            t_start = now()
            report = replay()
        finally:
            t_end = now()
            try:
                sleep(POST_S)
            finally:
                sampler.stop()
                lines = cluster.sender_log_lines(t_start)
                pods_after = {n: p["restarts"] for n, p in cluster.collector_pods().items()}
                lrl.cleanup(cluster, before_uids, t_start, check)
        box["reading"] = Reading(report, t_start, t_end, sampler.cpu, sampler.scrapes, sampler.errors,
                                 pods_before, pods_after, lines)

    held = hold(body) if hold else guard_lease.run_held(
        cluster.context, body, check, "test_collector_replay_pace_live.py", kubeconfig=cluster.kubeconfig,
        profile=cluster.profile)
    if not held:
        check("the 500-phone replay ran", False, "the guard lock could not be taken (above)")
        return None
    reading = box["reading"]
    for ok, name, detail in judge(reading):
        check(name, ok, detail)
    return reading


def subprocess_replay() -> Callable[[], dict | None]:
    def run() -> dict | None:
        with tempfile.TemporaryDirectory(prefix="wib-pace-replay-") as tmp:
            out = pathlib.Path(tmp) / "report.json"
            argv = replay_argv(out)
            print("$ " + " ".join(argv[1:]), flush=True)
            try:
                rc = subprocess.run(argv, timeout=REPLAY_TIMEOUT_S).returncode
            except subprocess.TimeoutExpired:
                print(f"load_replay.py ran past {REPLAY_TIMEOUT_S} s and was stopped", flush=True)
                return None
            print(f"load_replay.py exit {rc}", flush=True)
            return json.loads(out.read_text()) if out.is_file() else None
    return run


def main() -> int:
    failures: list[str] = []

    def check(name: str, cond: bool, detail: str = "") -> None:
        print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"\n        {detail}" if detail and not cond else ""),
              flush=True)
        if not cond:
            failures.append(name)

    context = os.environ.get("COMMUNITY_CONTEXT", "")
    missing = []
    if not context:
        missing.append("COMMUNITY_CONTEXT is not set: name the kube-context of watch-it-burn-community (attackme)")
    if shutil.which("kubectl") is None:
        missing.append("kubectl is not on PATH")
    cluster = None
    if not missing:
        cluster = PaceCluster(TARGET, context, os.environ.get("AWS_PROFILE") or None,
                              os.environ.get("KUBECONFIG") or None, timeout=60.0)
        rc, out = cluster.kubectl_rc("--request-timeout=15s", "get", "--raw", "/readyz", timeout=30)
        if rc != 0:
            missing.append(f"cluster for context {context!r} is not reachable: {out.strip()[:200]}")
    if missing:
        print("FAILED: the live collector pace check cannot run; this is a failure, not a skip:")
        for m in missing:
            print(f"  - {m}")
        return 1

    print(f"== #1336: the 500-phone replay on attackme finds the collector above one core or keeping pace "
          f"({context}) ==", flush=True)
    reading = run_checks(cluster, subprocess_replay(), check)
    if reading is not None:
        iv = intervals(reading.cpu)
        for pod, rows in iv.items():
            print(f"  note  {pod} CPU a kubelet interval, seconds from the replay's start: "
                  + ", ".join(f"{a - reading.t_start:+.0f}..{b - reading.t_start:+.0f} {c:.2f}" for a, b, c in rows))
        print("  note  counters over the reading: " + ", ".join(f"{k} {v:,.0f}" for k, v in deltas(reading).items()
                                                           if k != "relay_queue"))
        print(f"  note  replay {reading.t_end - reading.t_start:.1f} s, from {lrl.stamp(reading.t_start)} to "
              f"{lrl.stamp(reading.t_end)}")
    print()
    if failures:
        print(f"FAILED: {len(failures)} check(s)")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("The 500-phone replay on attackme found the collector above one core or keeping pace, no span dropped, "
          "no restart.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
