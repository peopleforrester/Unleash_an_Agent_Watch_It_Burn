# ABOUTME: Offline tests for verify/last_trace.py (#268): the one Datadog query the admin console's "last trace
# ABOUTME: seen" column comes from, the newest non-zero point per cluster, and a failed query as a loud exit 1.
import contextlib
import io
import pathlib
import sys
import urllib.parse

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import last_trace  # noqa: E402

failures = []


def check(n, c):
    print(f"  {'PASS' if c else 'FAIL'}  {n}")
    if not c:
        failures.append(n)


def series(cluster, points):
    return {"scope": f"kube_cluster_name:{cluster}", "tag_set": [f"kube_cluster_name:{cluster}"], "pointlist": points}


T0 = 1_790_000_000  # seconds; Datadog points are milliseconds
print("== last_seen picks the newest point that carries spans ==")
got = last_trace.last_seen([
    series("watch-it-burn-attendee-001", [[T0 * 1000, 3.0], [(T0 + 60) * 1000, 1.0], [(T0 + 120) * 1000, 0.0]]),
    series("watch-it-burn-attendee-002", [[T0 * 1000, 0.0], [(T0 + 60) * 1000, None]]),
    {"scope": "*", "tag_set": [], "pointlist": [[T0 * 1000, 5.0]]},
])
check("a zero point is not a trace: 001 is seen at its last non-zero point", got.get("watch-it-burn-attendee-001")
      == "2026-09-21T14:14:20+00:00")
check("a cluster whose points are all zero or empty is absent, not 'now'", "watch-it-burn-attendee-002" not in got)
check("a series with no cluster tag is ignored", len(got) == 1)

print("== main makes one query over the window, with the profile and region it was given ==")
calls = []


def http(method, url, headers, body):
    calls.append((method, url, headers))
    return 200, {"status": "ok", "series": [series("watch-it-burn-whitney-admin", [[T0 * 1000, 2.0]])]}


asked = []
out = io.StringIO()
with contextlib.redirect_stdout(out):
    rc = last_trace.main(["--profile", "accen-dev", "--region", "us-west-2", "--hours", "2"],
                         keys=lambda p, r: asked.append((p, r)) or ("api", "app", "datadoghq.com"), http=http, now=T0)
q = urllib.parse.parse_qs(urllib.parse.urlparse(calls[0][1]).query) if calls else {}
check("exit 0", rc == 0)
check("keys read for the profile and region passed, never ambient ones", asked == [("accen-dev", "us-west-2")])
check("exactly one Datadog call for the whole fleet", len(calls) == 1 and calls[0][0] == "GET")
check("it queries the no-traces monitor's metric, grouped by cluster",
      q.get("query") == [last_trace.QUERY] and "traces.span.metrics.calls" in last_trace.QUERY
      and "by {kube_cluster_name}" in last_trace.QUERY)
check("the window is --hours back from now", q.get("from") == [str(T0 - 7200)] and q.get("to") == [str(T0)])
check("prints <cluster>\\t<ISO time>", out.getvalue() == "watch-it-burn-whitney-admin\t2026-09-21T14:13:20+00:00\n")

print("== a failed query fails loudly, so the column reads unknown rather than silent ==")
for label, keys, resp in [
    ("Datadog refuses the call", lambda p, r: ("a", "b", "datadoghq.com"), (403, {"errors": ["Forbidden"]})),
    ("the query itself errors", lambda p, r: ("a", "b", "datadoghq.com"), (200, {"status": "error", "error": "bad"})),
    ("the keys cannot be read", lambda p, r: (_ for _ in ()).throw(RuntimeError("no secret")), (200, {})),
]:
    err, out = io.StringIO(), io.StringIO()
    with contextlib.redirect_stderr(err), contextlib.redirect_stdout(out):
        rc = last_trace.main(["--profile", "p", "--region", "r"], keys=keys, http=lambda *a, resp=resp: resp, now=T0)
    check(f"{label}: exit 1, a reason on stderr, nothing on stdout",
          rc == 1 and err.getvalue().startswith("last_trace: ") and out.getvalue() == "")

if failures:
    print(f"\nFAILED: {len(failures)}")
    sys.exit(1)
print("\nAll last-trace checks passed.")
