# ABOUTME: Offline tests for verify/dd_traces.py (#759): it reads the newest ml_app:burritobot traces with GETs only,
# ABOUTME: through hecaton's sources verb or a new env key pair, never watch-it-burn/datadog, and only in the sandbox org.
"""Nothing here reaches Datadog, AWS or sudo. The org is a fake transport answering the three paths the reader
uses, /api/v2/current_user, the LLM Observability span listing and the APM span listing, and refusing anything
else; the sources verb is a fake `run` that answers as the wrapper's contract says.
"""
from __future__ import annotations

import contextlib
import io
import json
import pathlib
import sys
import urllib.parse

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import dd_traces  # noqa: E402

failures = []


def check(n, c):
    print(f"  {'PASS' if c else 'FAIL'}  {n}")
    if not c:
        failures.append(n)


T0 = 1_793_000_000 * 10**9  # ns


def span(trace, sid, parent, name, kind, start_s, dur_ms=10, tokens=None):
    return {"id": sid, "type": "span", "attributes": {
        "trace_id": trace, "span_id": sid, "parent_id": parent, "name": name, "span_kind": kind, "status": "ok",
        "ml_app": "burritobot", "start_ns": T0 + start_s * 10**9, "duration": dur_ms * 10**6,
        "tags": ["env:burritobot-kubecon-na-26", "service:burritobot"],
        "metrics": {"total_tokens": tokens} if tokens else {}}}


SPANS = [
    span("old", "o1", "undefined", "invoke_agent", "agent", 0),
    span("new", "n1", "undefined", "invoke_agent", "agent", 120, 900),
    span("new", "n2", "n1", "chat", "llm", 121, 400, tokens=812),
    span("new", "n3", "n1", "read_menu", "tool", 122, 30),
    span("mid", "m1", "undefined", "invoke_agent", "agent", 60),
]


class Org:
    def __init__(self, name="Datadog Sandbox Whitney"):
        self.name, self.calls = name, []

    def http(self, method, url, headers, body):
        parts = urllib.parse.urlsplit(url)
        q = {k: v[0] for k, v in urllib.parse.parse_qs(parts.query).items()}
        self.calls.append((method, parts.path, q, headers, body))
        if method != "GET":
            return 405, {"errors": ["fake org: reads only"]}
        if parts.path == "/api/v2/current_user":
            return 200, {"data": {"type": "users"}, "included": [{"type": "orgs", "attributes": {"name": self.name}}]}
        if parts.path == dd_traces.LLMOBS_PATH:
            got = [s for s in SPANS if "filter[trace_id]" not in q or s["attributes"]["trace_id"] == q["filter[trace_id]"]]
            return 200, {"data": got}
        if parts.path == dd_traces.APM_PATH:
            return 200, {"data": [{"attributes": {"service": "burritobot-guard-proxy", "resource_name": "POST /chat",
                                                  "trace_id": "abc", "start_timestamp": "2026-11-01T12:00:00Z"}}]}
        return 404, {"errors": [f"fake org: no {parts.path}"]}


def run_main(argv, org, env=None, run=None):
    out, err = io.StringIO(), io.StringIO()
    lines = []
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = dd_traces.main(argv, env=env or {}, run=run or (lambda *a, **k: None),
                            http=None if run else org.http, say=lines.append)
    return rc, "\n".join(lines), err.getvalue()


ENV = {dd_traces.API_KEY_ENV: "new-api", dd_traces.APP_KEY_ENV: "new-app"}

print("== --via env: the newest traces, each read whole, with GETs only ==")
org = Org()
rc, text, err = run_main(["--via", "env", "--traces", "2"], org, env=ENV)
check("exit 0", rc == 0)
check("every call is a GET with no body", org.calls and all(c[0] == "GET" and c[4] is None for c in org.calls))
check("it names the org first, from /api/v2/current_user (the read-only key cannot read /api/v1/org, #629)",
      org.calls[0][1] == "/api/v2/current_user")
check("the keys sent are the new pair from the env", org.calls[0][3]["DD-API-KEY"] == "new-api"
      and org.calls[0][3]["DD-APPLICATION-KEY"] == "new-app")
listing = org.calls[1][2]
check("the listing asks LLM Observability for ml_app burritobot, newest first, over --minutes",
      org.calls[1][1] == "/api/v2/llm-obs/v1/spans/events" and listing.get("filter[ml_app]") == "burritobot"
      and listing.get("sort") == "-timestamp" and listing.get("filter[from]") == "now-60m")
read = [c[2].get("filter[trace_id]") for c in org.calls[2:]]
check("the two newest traces are read by id, newest first, and the oldest is not", read == ["new", "mid"])
check("a trace prints with its span count and root count", "trace new" in text and "3 spans  1 root(s)" in text)
check("children print under their root, with tokens on the llm span",
      "\n    llm chat  400 ms  ok  812 tokens" in text and "\n    tool read_menu  30 ms  ok" in text)
check("the env tag of the root prints", "env=burritobot-kubecon-na-26" in text)

print("== --via env needs both new keys, and never reads watch-it-burn/datadog ==")
for missing in (dd_traces.API_KEY_ENV, dd_traces.APP_KEY_ENV):
    org = Org()
    rc, text, err = run_main(["--via", "env"], org, env={k: v for k, v in ENV.items() if k != missing})
    check(f"without {missing}: exit 1, named, no call made", rc == 1 and missing in err and org.calls == [])
src = (HERE / "dd_traces.py").read_text()
check("the reader has no path to the clusters' secret or the AWS CLI",
      not hasattr(dd_traces, "read_keys") and not hasattr(dd_traces, "SECRET_ID")
      and "secretsmanager" not in src and '"aws"' not in src)

print("== the org guard: another org reads nothing ==")
org = Org("Acme Production")
rc, text, err = run_main(["--via", "env"], org, env=ENV)
check("exit 1 after the one org lookup", rc == 1 and len(org.calls) == 1 and "Acme Production" in err)
org = Org("Acme Pool 7")
rc, text, err = run_main(["--via", "env"], org, env={**ENV, "WIB_DD_POOL_PREFIX": "Acme Pool"})
check("WIB_DD_POOL_PREFIX names another org instead", rc == 0)

print("== no span is a failure, not an empty success ==")
org = Org()
saved = SPANS[:]
SPANS.clear()
rc, text, err = run_main(["--via", "env"], org, env=ENV)
check("no ml_app:burritobot span: exit 1, said so", rc == 1 and "no ml_app:burritobot span" in err)
SPANS.extend(saved)
org = Org()
rc, text, err = run_main(["--via", "env", "--trace", "gone"], org, env=ENV)
check("--trace of a trace with no span: exit 1, named", rc == 1 and "gone" in err)
org = Org()
rc, text, err = run_main(["--via", "env", "--trace", "new"], org, env=ENV)
check("--trace reads that one trace, with no listing", rc == 0 and len(org.calls) == 2
      and org.calls[1][2].get("filter[trace_id]") == "new")

print("== --apm and --json ==")
org = Org()
rc, text, err = run_main(["--via", "env", "--traces", "1", "--apm", "--json"], org, env=ENV)
got = json.loads(text) if rc == 0 else {}
apm_call = [c for c in org.calls if c[1] == dd_traces.APM_PATH]
check("the APM listing is the env's burritobot services, newest first",
      apm_call and apm_call[0][2].get("filter[query]") == "env:burritobot-kubecon-na-26 service:burritobot*"
      and apm_call[0][2].get("sort") == "-timestamp")
check("--json prints the org, the traces by id and the APM spans",
      got.get("org") == "Datadog Sandbox Whitney" and list(got.get("traces", {})) == ["new"]
      and got.get("apm", [{}])[0].get("service") == "burritobot-guard-proxy")

print("== --via sources: the wrapper holds the key, the reader sends only GET <path> ==")
org = Org()
argvs = []


class Done:
    def __init__(self, rc, out, err=""):
        self.returncode, self.stdout, self.stderr = rc, out, err


def sources_run(argv, **kw):
    argvs.append(argv)
    status, body = org.http(argv[-2], "https://api.datadoghq.com" + argv[-1], {}, None)
    return Done(0, json.dumps({"status": status, "body": body}))


rc, text, err = run_main(["--via", "sources", "--traces", "1"], org, run=sources_run)
check("exit 0, the trace printed", rc == 0 and "trace new" in text)
check("every call is `sudo -n -u michael /var/lib/hecaton/cli/sources datadog GET <path?query>`",
      argvs and all(a[:6] == dd_traces.SOURCES and a[6] == "GET" and a[7].startswith("/api/v2/") and len(a) == 8
                    for a in argvs))
check("no key leaves this side: the headers sent are empty",
      all(c[3] == {} for c in org.calls) and all("new-app" not in " ".join(a) for a in argvs))
rc, text, err = run_main(["--via", "sources"], org, run=lambda argv, **kw: Done(1, "", "REFUSED sources datadog"))
check("a refused verb: exit 1, its reason passed on", rc == 1 and "REFUSED sources datadog" in err)
rc, text, err = run_main(["--via", "sources"], org, run=lambda argv, **kw: Done(0, "not json"))
check("a malformed answer: exit 1, said so", rc == 1 and "no {status, body} object" in err)
rc, text, err = run_main(["--via", "sources"], org,
                         run=lambda argv, **kw: Done(0, json.dumps({"status": 403, "body": {"errors": ["Forbidden"]}})))
check("Datadog's 403 through the wrapper: exit 1 with the status", rc == 1 and "403" in err)
try:
    dd_traces.sources_http(run=sources_run)("POST", "https://api.datadoghq.com/api/v2/x", {}, b"{}")
    refused = False
except RuntimeError:
    refused = True
check("the sources transport refuses anything but a GET", refused)

print("== --via is required: no default, no fallback ==")
with contextlib.redirect_stderr(io.StringIO()):
    try:
        dd_traces.main([], env={}, http=Org().http, say=lambda s: None)
        exited = False
    except SystemExit as e:
        exited = e.code == 2
check("no --via: usage error", exited)

if failures:
    print(f"\nFAILED: {len(failures)}")
    sys.exit(1)
print("\nAll dd_traces checks passed.")
