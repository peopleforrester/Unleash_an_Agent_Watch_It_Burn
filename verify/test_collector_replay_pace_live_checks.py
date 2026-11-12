# ABOUTME: Offline checks for verify/test_collector_replay_pace_live.py (#1371): its judges fail run 20295's replay
# ABOUTME: reading from before #1336's split, pass a reading above one core and one keeping pace, and fail each other way.
"""verify/test_collector_replay_pace_live.py runs #1336's last criterion on attackme: with the traces processors behind
the queued loopback, the 500-phone replay finds the collector above one core or keeping pace, with no span dropped and
no restart. It needs the live cluster. This runs its judges and its flow with no cluster and no network:

1. the replay it runs is run 20295's command word for word (`--source catalog --users 500 --seed 1336`), with only
   --json-out added;
2. the sync gate passes this checkout's burn relay as the chart writes it, and fails the relay the cluster ran before
   the split (read on watch-it-burn-community on 2026-11-12 at 08:13 UTC), the mask moved into the intake, `batch` back
   in `traces`, one consumer, no queue, a CPU limit of one core, a DaemonSet not rolled out and a pod not ready;
3. the counters are read from the collector's Prometheus text as the live scrape of 2026-11-12 08:14 UTC wrote it;
4. run 20295's reading of 2026-11-11, before the split (the collector at 0.86 to 1.03 CPU a kubelet interval and idle
   74 to 88 s after the replay's end, four agentgateway exports given up), fails on the pace check and the senders'
   logs; a reading above one core and one keeping pace each pass; each way the criterion can stop holding fails on
   the check that names it, and the bounds (1.2 CPU, 15 s) hold at their edges;
5. the flow against a fake cluster: off attackme or unsynced, no sampler starts and nothing is sent; synced, the replay
   runs under the lock between the sampler's start and stop and the cleanup runs, also when the replay raises; a lock
   that cannot be taken sends nothing.
"""
from __future__ import annotations

import contextlib
import copy
import datetime as dt
import importlib.util
import io
import pathlib
import sys

import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
HERE = REPO / "verify"
LIVE = HERE / "test_collector_replay_pace_live.py"
sys.path.insert(0, str(HERE))
from collector_render import helm_values  # noqa: E402

spec = importlib.util.spec_from_file_location("collector_replay_pace_live", LIVE)
live = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = live              # dataclasses reads its module
spec.loader.exec_module(live)

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"\n        {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def failed(checks) -> list[str]:
    return [name for ok, name, _ in checks if not ok]


def fails_on(checks, fragment: str) -> bool:
    return any(fragment in name for name in failed(checks))


# --- 1. the command --------------------------------------------------------------------------------------------------
print("== the replay is run 20295's command ==")
argv = live.replay_argv(pathlib.Path("/t/report.json"))
want = "verify/load_replay.py attackme.burritobot.co --yes --source catalog --users 500 --seed 1336".split()
check("it runs load_replay.py on attackme with --yes --source catalog --users 500 --seed 1336, adding only --json-out",
      [pathlib.Path(argv[1]).relative_to(REPO).as_posix(), *argv[2:-2]] == want
      and argv[-2:] == ["--json-out", "/t/report.json"], " ".join(argv))
check("it runs under this interpreter", argv[0] == sys.executable, argv[0])

# --- 2. the sync gate ------------------------------------------------------------------------------------------------
print("== the sync gate ==")
VALS = helm_values("burn")


def chart_relay(config: dict) -> dict:
    """relay.yaml as the chart writes it: k8s_attributes prepended to each pipeline's processors."""
    c = copy.deepcopy(config)
    for pipe in c["service"]["pipelines"].values():
        pipe["processors"] = ["k8s_attributes", *pipe.get("processors", [])]
    return c


def daemonset(cpu: str = str(VALS["resources"]["limits"]["cpu"]), updated: int = 1) -> dict:
    return {"metadata": {"generation": 31},
            "spec": {"template": {"spec": {"containers": [
                {"name": live.CONTAINER, "resources": {"limits": {"cpu": cpu, "memory": "512Mi"}}}]}}},
            "status": {"observedGeneration": 31, "desiredNumberScheduled": 1, "updatedNumberScheduled": updated,
                       "numberReady": 1, "numberAvailable": 1}}


PODS = {"otel-collector-opentelemetry-collector-agent-9cwwq": {"node": "ip-10-0-28-179", "restarts": 0, "ready": True}}
SPLIT = chart_relay(VALS["config"])
# The pipelines watch-it-burn-community's relay.yaml held before the split reached it (2026-11-12 08:13 UTC).
BEFORE = copy.deepcopy(SPLIT)
BEFORE["service"]["pipelines"].pop(live.INTAKE)
BEFORE["service"]["pipelines"][live.TRACES] = {
    "receivers": ["otlp"], "exporters": ["span_metrics", "forward/llmobs", "debug"],
    "processors": ["k8s_attributes", "memory_limiter", "transform/kagent_service_name", "filter/drop_noise", "batch",
                   "resource", "transform/set_peer_service", "transform/set_llmobs_workflow",
                   "transform/set_genai_provider", "transform/adk_tool_content", "transform/http_server_error",
                   "transform/adk_model_content", "transform/llmobs_apm_off", "transform/coc_mask",
                   "transform/scrub_pii"]}


def synced(relay, ds=None, pods=None):
    text = relay if isinstance(relay, (str, type(None))) else yaml.safe_dump(relay)
    return live.judge_synced(text, daemonset() if ds is None else ds, PODS if pods is None else pods)


got = synced(SPLIT)
check("this checkout's burn relay, rolled out with its CPU limit, passes every sync check", not failed(got),
      f"failed: {failed(got)}\n{got}")
check("the gate is five checks", len(got) == 5, str(len(got)))
got = synced(BEFORE)
check("the relay before the split fails on the intake and the traces pipeline",
      fails_on(got, live.INTAKE) and fails_on(got, f"{live.TRACES} takes"), str(failed(got)))


def mutant(fn):
    c = copy.deepcopy(SPLIT)
    fn(c)
    return c


GATE = [
    ("the mask moved into the intake",
     mutant(lambda c: c["service"]["pipelines"][live.INTAKE]["processors"].append("transform/coc_mask")), live.INTAKE),
    ("the intake exporting past the relay",
     mutant(lambda c: c["service"]["pipelines"][live.INTAKE]["exporters"].append("debug")), live.INTAKE),
    ("batch put back into traces",
     mutant(lambda c: c["service"]["pipelines"][live.TRACES]["processors"].insert(1, "batch")), f"{live.TRACES} takes"),
    ("traces taking otlp again",
     mutant(lambda c: c["service"]["pipelines"][live.TRACES]["receivers"].append("otlp")), f"{live.TRACES} takes"),
    ("one consumer",
     mutant(lambda c: c["exporters"][live.EXPORTER]["sending_queue"].update(num_consumers=1)), "two consumers"),
    ("no sending queue",
     mutant(lambda c: c["exporters"][live.EXPORTER]["sending_queue"].update(enabled=False)), "two consumers"),
]
for what, relay, fragment in GATE:
    got = synced(relay)
    check(f"{what}: fails on the check naming {fragment!r}, and on that one alone",
          fails_on(got, fragment) and len(failed(got)) == 1, str(failed(got)))
for what, got, fragment in [
        ("a CPU limit of one core", synced(SPLIT, ds=daemonset(cpu="1")), "above one core"),
        ("a CPU limit of 1000m", synced(SPLIT, ds=daemonset(cpu="1000m")), "above one core"),
        ("a DaemonSet not rolled out", synced(SPLIT, ds=daemonset(updated=0)), "rolled out"),
        ("no DaemonSet", live.judge_synced(yaml.safe_dump(SPLIT), None, PODS), "rolled out"),
        ("a pod not ready", synced(SPLIT, pods={k: {**v, "ready": False} for k, v in PODS.items()}), "rolled out"),
        ("no collector pod", synced(SPLIT, pods={}), "rolled out")]:
    check(f"{what}: fails on the check naming {fragment!r}", fails_on(got, fragment), str(failed(got)))
got = synced(SPLIT, ds=daemonset(cpu="1500m"))
check("a CPU limit of 1500m passes", not failed(got), str(failed(got)))
for what, text in (("no relay key", None), ("a relay that is not YAML", "processors: [unclosed"),
                   ("a relay that is a list", "- a\n")):
    got = synced(text)
    check(f"{what}: one failed check, naming the relay", len(got) == 1 and fails_on(got, "holds a relay config"),
          str(got))

# --- 3. the counters -------------------------------------------------------------------------------------------------
print("== the counters, from the collector's Prometheus text ==")
# The live scrape of watch-it-burn-community's collector, 2026-11-12 08:14 UTC, a minute after the split rolled out,
# with a HELP line, an otlp/lab series and failure series added.
SCRAPE = """# HELP otelcol_receiver_accepted_spans Number of spans successfully pushed into the pipeline.
otelcol_exporter_queue_size{data_type="metrics",exporter="datadog"} 0
otelcol_exporter_queue_size{data_type="traces",exporter="datadog"} 0
otelcol_exporter_queue_size{data_type="traces",exporter="otlp_grpc/relay"} 0
otelcol_exporter_queue_size{data_type="traces",exporter="otlp_http/llmobs"} 0
otelcol_exporter_sent_spans{exporter="datadog"} 11
otelcol_exporter_sent_spans{exporter="debug"} 15
otelcol_exporter_sent_spans{exporter="otlp_grpc/relay",server_address="localhost",server_port="4320"} 56
otelcol_exporter_sent_spans{exporter="otlp_http/llmobs",server_address="otlp.datadoghq.com",url_path="/v1/traces"} 4
otelcol_receiver_accepted_spans{receiver="otlp",transport="http"} 56
otelcol_receiver_accepted_spans{receiver="otlp/relay",transport="grpc"} 56
otelcol_receiver_accepted_spans{receiver="otlp/lab",transport="grpc"} 900
otelcol_receiver_failed_spans{receiver="otlp",transport="http"} 0
otelcol_receiver_failed_spans{receiver="otlp/relay",transport="grpc"} 2
otelcol_receiver_refused_spans{receiver="otlp",transport="http"} 3
otelcol_receiver_refused_spans{receiver="otlp/relay",transport="grpc"} 0
otelcol_exporter_enqueue_failed_spans{exporter="otlp_grpc/relay"} 7
otelcol_exporter_send_failed_spans{exporter="datadog"} 40
"""
m = live.reduce_metrics(SCRAPE)
check("each counter is read from its own series, others ignored",
      m == {"intake_accepted": 56, "relay_accepted": 56, "refused": 3, "failed": 2, "relay_sent": 56,
            "relay_enqueue_failed": 7, "relay_send_failed": 0, "relay_queue": 0, "present": 1}, str(m))
m = live.reduce_metrics("otelcol_receiver_accepted_spans_total{receiver=\"otlp\"} 56\n")
check("a renamed intake counter reads as absent, so the coverage check names it", m["present"] == 0, str(m))

# --- 4. the readings -------------------------------------------------------------------------------------------------
print("== the readings ==")
T0 = dt.datetime(2026, 11, 11, 7, 2, 40, tzinfo=dt.timezone.utc).timestamp()   # run 20295's replay
DUR = 150.0                                          # run 20295's replay ran 150.3 s
T_END = T0 + DUR
POD = next(iter(PODS))


def cpu_at(points: list[tuple[float, float]], profile) -> list[tuple[str, float, int]]:
    """Kubelet samples at the given offsets from T0, the counter growing by `profile(a, b)` cores between them."""
    ns, out = 10 ** 12, []
    offs = sorted(points)
    out.append((POD, T0 + offs[0], ns))
    for a, b in zip(offs, offs[1:]):
        ns += int(profile(a, b) * (b - a) * 1e9)
        out.append((POD, T0 + b, ns))
    return out


def every(start: float, stop: float, step: float) -> list[float]:
    out, t = [], start
    while t <= stop + 1e-9:
        out.append(t)
        t += step
    return out


def scrapes(spans: int, relay_spans: int, queue_at=lambda t: 0, **delta) -> list[tuple[float, str, dict]]:
    """Scrapes every 15 s from 35 s before the replay to 60 s past it, the counters rising over the replay."""
    out = []
    times = every(-35, DUR + 60, 15)
    for t in times:
        f = min(1.0, max(0.0, t / DUR))
        m = {k: 0.0 for k in live.METRICS}
        m.update(present=1.0, intake_accepted=11_620 + spans * f, relay_accepted=relay_spans * f,
                 relay_sent=relay_spans * f, relay_queue=float(queue_at(t)))
        for k, v in delta.items():
            m[k] = v * f
        out.append((T0 + t, POD, m))
    return out


REPORT = {"users": 500, "turns": 3, "planned": 1500, "sent": 1500, "answered": 1500, "stop_reason": "",
          "outcomes": {"served": 384, "cluster_limit": 1116, "cost_cap": 0}}
SAMPLES = every(-40, DUR + 60, 12)


def reading(busy: float, idle_after: float, report=REPORT, spans=9_275, relay_spans=9_275, sender_lines=(),
            points=SAMPLES, pods_after=None, cpu=None, scr=None) -> live.Reading:
    """A reading: the collector at `busy` cores from 10 s into the replay to `idle_after` s past its end, then idle."""
    def profile(a, b):
        hot = max(0.0, min(b, DUR + idle_after) - max(a, 10))
        return (busy * hot + 0.005 * ((b - a) - hot)) / (b - a)
    return live.Reading(copy.deepcopy(report), T0, T_END, cpu if cpu is not None else cpu_at(points, profile),
                        scr if scr is not None else scrapes(spans, relay_spans), [], {POD: 0},
                        pods_after if pods_after is not None else {POD: 0},
                        None if sender_lines is None else list(sender_lines))


PACE = "or kept pace: idle"
AGW = ['[pod/agentgateway-5d9f/agentgateway] 2026-11-11T07:04:21Z WARN opentelemetry_sdk: name="BatchSpanProcessor.'
       'Export.Failed.DeadlineExceeded" ... "telemetry data will be lost"'] * 4

# Run 20295, before the split: CPU 0.86 to 1.03 a kubelet interval from 07:03:30 to 07:05:51, idle 74 to 88 s after
# the replay's end; no otlp/relay series yet; agentgateway gave up four exports.
before = live.judge(reading(1.03, 80, relay_spans=0, sender_lines=AGW))
check("run 20295's reading before the split fails on the pace check",
      fails_on(before, PACE), f"failed: {failed(before)}\n{before}")
check("... and on the senders' logs", fails_on(before, "no sender gave up"), str(failed(before)))
check("... and on spans across the loopback, which it had no loopback for",
      fails_on(before, "real work"), str(failed(before)))
check("... and on nothing about the replay itself, the restarts or the coverage",
      set(failed(before)) == {n for n in failed(before)
                              if any(f in n for f in (PACE, "no sender gave up", "real work"))}, str(failed(before)))
alone = live.judge(reading(1.03, 80))
check("its CPU shape alone, with the loopback's counters and clean logs, fails on the pace check alone",
      failed(alone) == [n for n in failed(alone) if PACE in n] and len(failed(alone)) == 1, str(failed(alone)))

above = live.judge(reading(1.6, 40))
check("a reading above one core passes, though it was idle only 40 s after the replay", not failed(above),
      f"failed: {failed(above)}\n{above}")
pace = live.judge(reading(0.9, 5))
check("a reading under one core and idle 5 s after the replay passes", not failed(pace),
      f"failed: {failed(pace)}\n{pace}")
check("the judge is nine checks", len(pace) == 9, str(len(pace)))


def edge_cpu(hot_until: float, busy: float = 0.9) -> list[tuple[str, float, int]]:
    """Samples at fixed offsets and one at `hot_until` s past the replay's end, busy up to it and idle after."""
    pts = sorted(set(SAMPLES) | {DUR + hot_until})
    return cpu_at(pts, lambda a, b: busy if b <= DUR + hot_until and a >= 10 else 0.005)


CASES = [
    ("idle only 30 s after the replay, at 0.95 CPU", reading(0.95, 30), [PACE]),
    ("the relay queue a request deep 20 s after the replay",
     reading(0.9, 5, scr=scrapes(9_275, 9_275, queue_at=lambda t: live.RELAY_REQUEST if t >= DUR + 20 else 0)),
     [PACE]),
    ("a peak of 1.2 CPU, idle late", reading(1.2, 40), [PACE]),
    ("idle from 16 s after the replay", reading(0.9, 0, cpu=edge_cpu(16)), [PACE]),
    ("a collector restart", reading(0.9, 5, pods_after={POD: 1}), ["no restart"]),
    ("a collector pod replaced", reading(0.9, 5, pods_after={POD + "x": 0}), ["no restart"]),
    ("the relay turning spans away", reading(0.9, 5, scr=scrapes(9_275, 9_275, relay_enqueue_failed=40)),
     ["turned no span away"]),
    ("the relay failing to send", reading(0.9, 5, scr=scrapes(9_275, 9_275, relay_send_failed=3)),
     ["turned no span away"]),
    ("the intake refusing spans", reading(0.9, 5, scr=scrapes(9_275, 9_275, refused=10)), ["refused and failed"]),
    ("the loopback receiver failing spans", reading(0.9, 5, scr=scrapes(9_275, 9_275, failed=2)),
     ["refused and failed"]),
    ("a sender giving up an export", reading(0.9, 5, sender_lines=AGW[:1]), ["no sender gave up"]),
    ("the agent's processor export timeout",
     reading(0.9, 5, sender_lines=["[pod/workshop-agent-7c/kagent] traces export: context deadline exceeded: "
                                   "processor export timeout"]), ["no sender gave up"]),
    ("the senders' logs unread", reading(0.9, 5, sender_lines=None), ["senders' logs over the replay were read"]),
    ("too few spans across the loopback", reading(0.9, 5, relay_spans=500), ["real work"]),
    ("the replay cut short", reading(0.9, 5, report={**REPORT, "sent": 900, "answered": 900,
                                                     "stop_reason": "--deadline 900s passed"}),
     ["sent every planned turn"]),
    ("the replay with fewer users", reading(0.9, 5, report={**REPORT, "users": 150, "planned": 450}),
     ["sent every planned turn"]),
    ("too few turns served", reading(0.9, 5, report={**REPORT, "outcomes": {**REPORT["outcomes"], "served": 150}}),
     ["room's ceiling"]),
    ("turns refused by the cost cap",
     reading(0.9, 5, report={**REPORT, "outcomes": {**REPORT["outcomes"], "cost_cap": 5}}), ["room's ceiling"]),
    ("CPU read only from after the replay began", reading(0.9, 5, points=[p for p in SAMPLES if p > 5]),
     ["were read from before"]),
    ("CPU read only to 10 s after the replay, so no idle tail is seen",
     reading(0.9, 5, points=[p for p in SAMPLES if p < DUR + 10]), ["were read from before", PACE]),
    ("a 90 s gap in the CPU samples", reading(0.9, 5, points=[p for p in SAMPLES if not 20 < p < 110]),
     ["were read from before"]),
    ("scrapes ending 10 s after the replay",
     reading(0.9, 5, scr=[s for s in scrapes(9_275, 9_275) if s[0] < T_END + 10]), ["were read from before"]),
    ("a scrape with no intake series",
     reading(0.9, 5, scr=[(t, p, {**m, "present": 0.0}) if i == 3 else (t, p, m)
                          for i, (t, p, m) in enumerate(scrapes(9_275, 9_275))]), ["were read from before"]),
]
print("== each way the criterion stops holding fails, on its own check ==")
for what, r, fragments in CASES:
    got = live.judge(r)
    own = [n for n in failed(got) if any(f in n for f in fragments)]
    check(f"{what}: fails on {fragments}, and on nothing else",
          all(fails_on(got, f) for f in fragments) and own == failed(got), f"failed: {failed(got)}\n{got}")
got = live.judge(reading(0.9, 5, report=None))
check("no report: one failed check, naming it", failed(got) == ["the replay wrote its report"], str(got))

print("== the bounds hold at their edges ==")
for what, r, ok in (("a peak of 1.21 CPU, idle late, passes", reading(1.21, 40), True),
                    ("idle from 15 s after the replay passes", reading(0.9, 0, cpu=edge_cpu(15)), True),
                    ("a relay queue of 255 spans after 15 s passes",
                     reading(0.9, 5, scr=scrapes(9_275, 9_275, queue_at=lambda t: live.RELAY_REQUEST - 1)), True),
                    ("exactly MIN_SERVED served passes",
                     reading(0.9, 5, report={**REPORT, "outcomes": {**REPORT["outcomes"],
                                                                    "served": live.MIN_SERVED}}), True)):
    got = live.judge(r)
    check(what, (not failed(got)) == ok, f"failed: {failed(got)}\n{got}")
iv = live.intervals(edge_cpu(15))[POD]
check("the 15 s edge case's idle tail starts at 15 s exactly",
      abs(live.idle_from(iv, T_END) - (T_END + 15)) < 1e-6, str(live.idle_from(iv, T_END) - T_END))
check("intervals drop a repeated kubelet sample",
      live.intervals([(POD, 0.0, 0), (POD, 10.0, 10 ** 10), (POD, 10.0, 10 ** 10), (POD, 20.0, 2 * 10 ** 10)])[POD]
      == [(0.0, 10.0, 1.0), (10.0, 20.0, 1.0)])

# --- 5. the flow -----------------------------------------------------------------------------------------------------
print("== the flow against a fake cluster ==")


class Clock:
    def __init__(self) -> None:
        self.t = T0 - 100

    def now(self) -> float:
        return self.t

    def sleep(self, s: float) -> None:
        self.t += s


class FakeSampler:
    made: list = []

    def __init__(self, cluster, pods) -> None:
        self.cluster, self.pods, self.events = cluster, pods, cluster.events
        self.cpu, self.scrapes, self.errors = [], [], []
        FakeSampler.made.append(self)

    def start(self) -> None:
        self.events.append("sampler start")
        self.t0 = self.cluster.clock.now()

    def stop(self) -> None:
        self.events.append("sampler stop")
        r = reading(0.9, 5)
        shift = (self.t0 + live.PRE_S) - T0          # the healthy reading, moved to the fake replay's start
        self.cpu = [(p, t + shift, ns) for p, t, ns in r.cpu]
        self.scrapes = [(t + shift, p, m) for t, p, m in r.scrapes]


class FakeCluster:
    context, kubeconfig, profile = "watch-it-burn-community", None, None

    def __init__(self, host="attackme.burritobot.co", relay=SPLIT) -> None:
        self.host, self.relay, self.events, self.clock = host, relay, [], Clock()
        self.forgot = []

    def identity_host(self):
        return self.host

    def collector_pods(self):
        return copy.deepcopy(PODS)

    def relay_text(self):
        return yaml.safe_dump(self.relay)

    def daemonset(self):
        return daemonset()

    def sender_log_lines(self, since):
        self.events.append("logs")
        return []

    def bot_objects(self):
        self.events.append("bot objects")
        return []

    def delete(self, ref):
        return True, ""

    def forget_on_desk(self, names, since):
        self.forgot.append(names)
        return None


def flow(cluster, replay_fn=None, hold_ok=True):
    out, sent = [], []

    def fcheck(name, ok, detail=""):
        out.append((ok, name, detail))

    def replay():
        cluster.events.append("replay")
        sent.append(1)
        cluster.clock.sleep(DUR)
        if replay_fn:
            return replay_fn()
        return copy.deepcopy(REPORT)

    def hold(body):
        if not hold_ok:
            return False
        cluster.events.append("lock")
        body()
        cluster.events.append("unlock")
        return True

    FakeSampler.made = []
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        try:
            live.run_checks(cluster, replay, fcheck, sampler_for=FakeSampler, hold=hold, now=cluster.clock.now,
                            sleep=cluster.clock.sleep)
        except RuntimeError as e:
            out.append((False, f"raised {e}", ""))
    return out, sent


c = FakeCluster(host="attackme-private.burritobot.co")
out, sent = flow(c)
check("off attackme: fails on the context, sends nothing, starts no sampler",
      failed(out) == [f"the context is attackme ({live.TARGET})"] and not sent and not FakeSampler.made, str(out))
c = FakeCluster(relay=BEFORE)
out, sent = flow(c)
check("the split not synced: fails, sends nothing, starts no sampler",
      fails_on(out, "the 500-phone replay ran") and not sent and not FakeSampler.made and "lock" not in c.events,
      str(out))
c = FakeCluster()
out, sent = flow(c)
check("synced: every check passes", not failed(out), f"failed: {failed(out)}\n{out}")
check("synced: the replay runs once, under the lock, between the sampler's start and stop, and the cleanup follows",
      sent == [1] and c.events == ["lock", "bot objects", "sampler start", "replay", "sampler stop", "logs",
                                   "bot objects", "unlock"], str(c.events))
c = FakeCluster()


def boom():
    raise RuntimeError("load_replay.py failed")


out, sent = flow(c, replay_fn=boom)
check("a replay that raises still stops the sampler, reads the logs and cleans up, then fails",
      c.events[-3:] == ["sampler stop", "logs", "bot objects"] and "unlock" not in c.events
      and fails_on(out, "raised"), str(c.events))
c = FakeCluster()
out, sent = flow(c, hold_ok=False)
check("a lock that cannot be taken sends nothing and fails", not sent and fails_on(out, "the 500-phone replay ran"),
      str(out))
c = FakeCluster()
out, sent = flow(c, replay_fn=lambda: None)
check("a replay with no report fails on it alone", failed(out) == ["the replay wrote its report"], str(failed(out)))

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    sys.exit(1)
print("test_collector_replay_pace_live.py fails run 20295's reading before the split, passes a reading above one core "
      "and one keeping pace, and fails on each way #1336's criterion stops holding.")
