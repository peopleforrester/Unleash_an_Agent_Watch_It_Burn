# ABOUTME: Offline tests for verify/dd_traces.py (#759): it reads the newest ml_app:burritobot traces with GETs only,
# ABOUTME: with watch-it-burn/datadog's pair as the named profile, only in the sandbox org, and names a refused scope.
"""Nothing here reaches Datadog or AWS. The org is a fake transport answering the three paths the reader uses,
/api/v2/current_user, the LLM Observability span listing and the APM span listing, and refusing anything else; the
key pair comes from a fake `keys` that records the profile and region it was asked for, and a fake `aws` run that
answers as Secrets Manager does.
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
    def __init__(self, name="Datadog Sandbox Whitney", refuse=()):
        self.name, self.refuse, self.calls = name, set(refuse), []

    def http(self, method, url, headers, body):
        parts = urllib.parse.urlsplit(url)
        q = {k: v[0] for k, v in urllib.parse.parse_qs(parts.query).items()}
        self.calls.append((method, parts.path, q, headers, body, parts.netloc))
        if method != "GET":
            return 405, {"errors": ["fake org: reads only"]}
        if parts.path in self.refuse:
            return 403, {"errors": ["Forbidden"]}
        if parts.path == "/api/v2/current_user":
            return 200, {"data": {"type": "users"}, "included": [{"type": "orgs", "attributes": {"name": self.name}}]}
        if parts.path == dd_traces.LLMOBS_PATH:
            got = [s for s in SPANS if "filter[trace_id]" not in q or s["attributes"]["trace_id"] == q["filter[trace_id]"]]
            return 200, {"data": got}
        if parts.path == dd_traces.APM_PATH:
            return 200, {"data": [{"attributes": {"service": "burritobot-guard-proxy", "resource_name": "POST /chat",
                                                  "trace_id": "abc", "start_timestamp": "2026-11-01T12:00:00Z"}}]}
        return 404, {"errors": [f"fake org: no {parts.path}"]}


asked = []


def fake_keys(profile, region):
    asked.append((profile, region))
    return "sec-api", "sec-app", "datadoghq.com"


def run_main(argv, org, env=None, keys=fake_keys):
    err = io.StringIO()
    lines = []
    with contextlib.redirect_stderr(err):
        rc = dd_traces.main(argv, env=env or {}, keys=keys, http=org.http, say=lines.append)
    return rc, "\n".join(lines), err.getvalue()


BASE = ["--profile", "accen-dev"]

print("== the newest traces, each read whole, with GETs only ==")
org = Org()
asked.clear()
rc, text, err = run_main(BASE + ["--traces", "2"], org)
check("exit 0", rc == 0)
check("the pair is read as the named profile, in us-west-2 by default", asked == [("accen-dev", "us-west-2")])
check("every call is a GET with no body", org.calls and all(c[0] == "GET" and c[4] is None for c in org.calls))
check("it names the org first, from /api/v2/current_user (the read-only key cannot read /api/v1/org, #629)",
      org.calls[0][1] == "/api/v2/current_user")
check("the keys sent are the secret's pair, to the secret's site",
      org.calls[0][3]["DD-API-KEY"] == "sec-api" and org.calls[0][3]["DD-APPLICATION-KEY"] == "sec-app"
      and org.calls[0][5] == "api.datadoghq.com")
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

print("== the key pair: watch-it-burn/datadog as a named profile, nothing ambient ==")
with contextlib.redirect_stderr(io.StringIO()):
    try:
        dd_traces.main([], env={}, keys=fake_keys, http=Org().http, say=lambda s: None)
        exited = False
    except SystemExit as e:
        exited = e.code == 2
check("no --profile: usage error, no AWS default", exited)
asked.clear()
rc, _, _ = run_main(BASE + ["--region", "eu-west-1"], Org())
check("--region is passed through", asked == [("accen-dev", "eu-west-1")])
argvs = []


class Done:
    def __init__(self, rc, out, err=""):
        self.returncode, self.stdout, self.stderr = rc, out, err


def aws_run(argv, **kw):
    argvs.append(argv)
    return Done(0, json.dumps({"api-key": "a", "app-key": "b", "site": "datadoghq.com"}))


org = Org()
rc, _, _ = run_main(BASE, org, keys=lambda p, r: dd_traces.fm.read_keys(p, r, run=aws_run))
check("the default keys reader asks Secrets Manager for watch-it-burn/datadog as that profile and region",
      rc == 0 and argvs and argvs[0][:5] == ["aws", "secretsmanager", "get-secret-value", "--secret-id",
                                              "watch-it-burn/datadog"]
      and argvs[0][argvs[0].index("--profile") + 1] == "accen-dev"
      and argvs[0][argvs[0].index("--region") + 1] == "us-west-2")
org = Org()
rc, text, err = run_main(BASE, org, keys=lambda p, r: dd_traces.fm.read_keys(
    p, r, run=lambda argv, **kw: Done(255, "", "Unable to locate credentials")))
check("an unreadable secret: exit 1 with AWS's reason, and Datadog is never called",
      rc == 1 and "Unable to locate credentials" in err and org.calls == [])
check("the reader is the repo's one Datadog client, no transport of its own",
      dd_traces.fm.SECRET_ID == "watch-it-burn/datadog" and "urllib.request" not in (HERE / "dd_traces.py").read_text())

print("== a refused read names the scope it needs ==")
for path, scope in ((dd_traces.LLMOBS_PATH, "llm_observability_read"), (dd_traces.APM_PATH, "apm_read"),
                    (dd_traces.ME_PATH, "user_self_profile_read")):
    org = Org(refuse=[path])
    rc, text, err = run_main(BASE + ["--apm"], org)
    check(f"403 on {path}: exit 1, Datadog's words and {scope} named",
          rc == 1 and "403" in err and "Forbidden" in err and scope in err and "watch-it-burn/datadog" in err)
org = Org()
org.http = (lambda inner: lambda m, u, h, b: (500, {"errors": ["boom"]}) if "llm-obs" in u else inner(m, u, h, b))(org.http)
rc, text, err = run_main(BASE, org)
check("another refusal (500) is reported as is, with no scope claimed", rc == 1 and "500" in err
      and "permission" not in err)

print("== the org guard: another org reads nothing ==")
org = Org("Acme Production")
rc, text, err = run_main(BASE, org)
check("exit 1 after the one org lookup", rc == 1 and len(org.calls) == 1 and "Acme Production" in err)
org = Org("Acme Pool 7")
rc, text, err = run_main(BASE, org, env={"WIB_DD_POOL_PREFIX": "Acme Pool"})
check("WIB_DD_POOL_PREFIX names another org instead", rc == 0)

print("== no span is a failure, not an empty success ==")
org = Org()
saved = SPANS[:]
SPANS.clear()
rc, text, err = run_main(BASE, org)
check("no ml_app:burritobot span: exit 1, said so", rc == 1 and "no ml_app:burritobot span" in err)
SPANS.extend(saved)
org = Org()
rc, text, err = run_main(BASE + ["--trace", "gone"], org)
check("--trace of a trace with no span: exit 1, named", rc == 1 and "gone" in err)
org = Org()
rc, text, err = run_main(BASE + ["--trace", "new"], org)
check("--trace reads that one trace, with no listing", rc == 0 and len(org.calls) == 2
      and org.calls[1][2].get("filter[trace_id]") == "new")

print("== --apm and --json ==")
org = Org()
rc, text, err = run_main(BASE + ["--traces", "1", "--apm", "--json"], org)
got = json.loads(text) if rc == 0 else {}
apm_call = [c for c in org.calls if c[1] == dd_traces.APM_PATH]
check("the APM listing is the env's burritobot services, newest first",
      apm_call and apm_call[0][2].get("filter[query]") == "env:burritobot-kubecon-na-26 service:burritobot*"
      and apm_call[0][2].get("sort") == "-timestamp")
check("--json prints the org, the traces by id and the APM spans",
      got.get("org") == "Datadog Sandbox Whitney" and list(got.get("traces", {})) == ["new"]
      and got.get("apm", [{}])[0].get("service") == "burritobot-guard-proxy")
check("still nothing but GETs", all(c[0] == "GET" for c in org.calls))

if failures:
    print(f"\nFAILED: {len(failures)}")
    sys.exit(1)
print("\nAll dd_traces checks passed.")
