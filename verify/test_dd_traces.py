# ABOUTME: Offline tests for verify/dd_traces.py (#759): it reads the newest ml_app:burritobot traces with GETs only,
# ABOUTME: with watch-it-burn/datadog's pair as the named profile, only in the sandbox org, and names a refused scope;
# ABOUTME: --credential fails unless the pair is new, made for the secret, and neither rotated nor revoked (#890).
"""Nothing here reaches Datadog or AWS. The org is a fake transport answering the four paths the reader uses,
/api/v2/current_user, the LLM Observability span listing, the APM span listing and the org's application key
and API key listings (for --scopes and --credential), and refusing anything else; the
key pair comes from a fake `keys` that records the profile and region it was asked for, and a fake `aws` run that
answers as Secrets Manager does. The secret's metadata for --credential comes from a fake `describe`.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import pathlib
import re
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


READ_SCOPES = ["apm_read", "llm_observability_read", "ai_guard_view", "timeseries_query", "user_self_profile_read",
               "logs_read_data", "logs_read_index_data"]


def keyrec(last4, scopes, name="Burritobot-app-key"):
    return {"type": "application_keys", "attributes": {"name": name, "last4": last4, "scopes": scopes,
                                                       "created_at": "2026-10-28T10:37:27Z"}}


# The live pair's times (run 17742, 2026-11-06): the API key, then the application key, then the secret two minutes on.
API_MADE = "2026-10-28T10:36:34.828511+00:00"
SECRET_MADE = "2026-10-28T11:39:34.153000+01:00"


def apirec(last4, created=API_MADE, modified=None, status="active", name="BurritoBot"):
    return {"type": "api_keys", "attributes": {"name": name, "last4": last4, "created_at": created,
                                               "modified_at": created if modified is None else modified,
                                               "status": status}}


class Org:
    def __init__(self, name="Datadog Sandbox Whitney", refuse=(), keys=None, api_keys=None):
        self.name, self.refuse, self.calls = name, set(refuse), []
        self.keys = [keyrec("-app", READ_SCOPES), keyrec("zzzz", ["dashboards_write"], "someone-else")] \
            if keys is None else keys
        self.api_keys = [apirec("-api"), apirec("yyyy", "2025-01-01T00:00:00+00:00", name="someone-else")] \
            if api_keys is None else api_keys

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
        if parts.path in (dd_traces.KEYS_PATH, dd_traces.API_KEYS_PATH):
            size, number = int(q["page[size]"]), int(q["page[number]"])
            listed = self.keys if parts.path == dd_traces.KEYS_PATH else self.api_keys
            return 200, {"data": listed[size * number:size * (number + 1)]}
        return 404, {"errors": [f"fake org: no {parts.path}"]}


asked = []


def fake_keys(profile, region):
    asked.append((profile, region))
    return "sec-api", "sec-app", "datadoghq.com"


described = []


def fake_describe(profile, region, meta=None):
    described.append((profile, region))
    return {"Name": "watch-it-burn/datadog", "CreatedDate": SECRET_MADE} if meta is None else meta


def run_main(argv, org, env=None, keys=fake_keys, describe=fake_describe):
    err = io.StringIO()
    lines = []
    with contextlib.redirect_stderr(err):
        rc = dd_traces.main(argv, env=env or {}, keys=keys, http=org.http, say=lines.append, describe=describe)
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

print("== --scopes: the pair's own key, every scope read-only ==")
org = Org()
rc, text, err = run_main(BASE + ["--scopes"], org)
check("a read-only key: exit 0, its name, creation and every scope printed",
      rc == 0 and "'Burritobot-app-key', created 2026-10-28T10:37:27Z, 7 scopes" in text
      and all(f"\n  {s}" in text for s in READ_SCOPES) and "Every scope is read-only." in text)
check("only the pair's own key is printed, matched by its last four characters", "dashboards_write" not in text
      and "someone-else" not in text)
check("--scopes names the org first, lists keys with GETs only, and reads no span",
      org.calls[0][1] == dd_traces.ME_PATH and all(c[0] == "GET" for c in org.calls)
      and {c[1] for c in org.calls[1:]} == {dd_traces.KEYS_PATH})
org = Org(keys=[keyrec("-app", READ_SCOPES + ["monitors_write", "user_access_manage"])])
rc, text, err = run_main(BASE + ["--scopes"], org)
check("a write scope: exit 1, each one named", rc == 1 and "monitors_write" in err and "user_access_manage" in err)
org = Org(keys=[keyrec("-app", None)])
rc, text, err = run_main(BASE + ["--scopes"], org)
check("an unscoped key (scopes null): exit 1, said so", rc == 1 and "unscoped" in err)
org = Org(keys=[keyrec("zzzz", READ_SCOPES)])
rc, text, err = run_main(BASE + ["--scopes"], org)
check("the pair's key is not in the listing: exit 1, said so", rc == 1 and "0 application keys" in err)
org = Org(keys=[keyrec("-app", READ_SCOPES), keyrec("-app", ["dashboards_write"])])
rc, text, err = run_main(BASE + ["--scopes"], org)
check("two keys share the last four: exit 1 rather than guess", rc == 1 and "2 application keys" in err)
org = Org(keys=[keyrec(f"k{i:03d}", READ_SCOPES) for i in range(150)] + [keyrec("-app", READ_SCOPES)])
rc, text, err = run_main(BASE + ["--scopes"], org)
check("the key on the second page of the listing is found",
      rc == 0 and [c[2].get("page[number]") for c in org.calls if c[1] == dd_traces.KEYS_PATH] == ["0", "1"])
org = Org(refuse=[dd_traces.KEYS_PATH])
rc, text, err = run_main(BASE + ["--scopes"], org)
check("403 on the key listing: exit 1, org_app_keys_read named", rc == 1 and "org_app_keys_read" in err)
check("each read-only extra is a scope the read/view rule would otherwise refuse",
      all(not ({"read", "view"} & set(s.split("_"))) for s in dd_traces.READ_ONLY_EXTRAS))
for s in ("logs_write_archives", "logs_modify_indexes", "monitors_write", "dashboards_public_share", "workflows_run",
          "user_access_manage", "api_keys_delete", "logs_read_write", "synthetics_global_variable_write"):
    check(f"{s} is not read-only", not dd_traces.read_only(s))
for s in ("logs_read_data", "logs_read_archives", "apm_read", "ndm_device_profiles_view", "timeseries_query"):
    check(f"{s} is read-only", dd_traces.read_only(s))

print("== --credential: the pair is new, made for the secret, and neither rotated nor revoked (#890) ==")
org = Org()
described.clear()
rc, text, err = run_main(BASE + ["--credential"], org)
check("the live pair's shape: exit 0, both keys and the secret's creation printed, and said new",
      rc == 0 and "API key 'BurritoBot', created 2026-10-28T10:36:34" in text and "rotation off" in text
      and "Every scope is read-only." in text and "The pair is new" in text and err == "")
check("the secret is described as the named profile and region", described == [("accen-dev", "us-west-2")])
check("--credential sends only GETs, to the org, the application key and the API key listings",
      all(c[0] == "GET" and c[4] is None for c in org.calls)
      and {c[1] for c in org.calls} == {dd_traces.ME_PATH, dd_traces.KEYS_PATH, dd_traces.API_KEYS_PATH})
check("another user's API key in the listing is not the one judged", "someone-else" not in text)
cases = [
    ("an application key made a day before the secret (an existing key reused)",
     dict(keys=[{**keyrec("-app", READ_SCOPES), "attributes": {**keyrec("-app", READ_SCOPES)["attributes"],
                                                                "created_at": "2026-10-27T10:37:27Z"}}]),
     "application key was created 2026-10-27T10:37:27Z, more than 1:00:00 before the secret"),
    ("an API key made a month before the secret (an existing key reused)",
     dict(api_keys=[apirec("-api", "2026-09-28T10:36:34+00:00")]), "an existing key, not one made for it"),
    ("an application key made after the secret (the pair replaced)",
     dict(keys=[{**keyrec("-app", READ_SCOPES), "attributes": {**keyrec("-app", READ_SCOPES)["attributes"],
                                                                "created_at": "2026-11-05T14:59:01Z"}}]),
     "after the secret (2026-10-28T11:39:34.153000+01:00): the pair was replaced"),
    ("an API key made after the secret (the pair replaced)",
     dict(api_keys=[apirec("-api", "2026-11-05T14:59:01+00:00")]), "API key was created 2026-11-05T14:59:01"),
    ("an API key modified after it was made", dict(api_keys=[apirec("-api", modified="2026-11-01T09:00:00+00:00")]),
     "the API key was modified 2026-11-01T09:00:00+00:00"),
    ("an API key that is not active", dict(api_keys=[apirec("-api", status="disabled")]),
     "status is disabled, not active"),
    ("an API key with no status (Datadog dropped the field)", dict(api_keys=[{"attributes": {
        "last4": "-api", "created_at": API_MADE, "modified_at": API_MADE}}]), "status is None, not active"),
    ("a revoked API key (not listed)", dict(api_keys=[apirec("yyyy")]), "0 API keys"),
    ("a revoked application key (not listed)", dict(keys=[keyrec("zzzz", READ_SCOPES)]), "0 application keys"),
    ("an application key with no creation time", dict(keys=[{"attributes": {"last4": "-app",
                                                                            "scopes": READ_SCOPES}}]),
     "the application key has no creation time"),
]
for name, kw, said in cases:
    rc, text, err = run_main(BASE + ["--credential"], Org(**kw))
    check(f"{name}: exit 1, said so", rc == 1 and said in err and "The pair is new" not in text)
for name, meta, said in (
        ("the secret set to rotate", {"CreatedDate": SECRET_MADE, "RotationEnabled": True}, "is set to rotate"),
        ("the secret with no creation time", {"Name": "watch-it-burn/datadog"}, "has no creation time")):
    rc, text, err = run_main(BASE + ["--credential"], Org(), describe=lambda p, r, m=meta: fake_describe(p, r, m))
    check(f"{name}: exit 1, said so", rc == 1 and said in err)
for minutes, ok in ((59, True), (61, False)):
    made = (dd_traces.stamp(SECRET_MADE) - dd_traces.dt.timedelta(minutes=minutes)).isoformat()
    rc, _, _ = run_main(BASE + ["--credential"], Org(api_keys=[apirec("-api", made)]))
    check(f"an API key made {minutes} minutes before the secret: {'new' if ok else 'not new'}", (rc == 0) == ok)
org = Org(keys=[keyrec("-app", READ_SCOPES + ["monitors_write"])])
described.clear()
rc, text, err = run_main(BASE + ["--credential"], org)
check("a write scope still fails --credential, before any API key or secret is read",
      rc == 1 and "monitors_write" in err and described == []
      and dd_traces.API_KEYS_PATH not in {c[1] for c in org.calls})
org = Org(refuse=[dd_traces.API_KEYS_PATH])
rc, text, err = run_main(BASE + ["--credential"], org)
check("403 on the API key listing: exit 1, api_keys_read named", rc == 1 and "api_keys_read" in err)
rc, text, err = run_main(BASE + ["--credential"], Org(), describe=lambda p, r: dd_traces.secret_meta(
    p, r, run=lambda argv, **kw: Done(255, "", "AccessDeniedException: DescribeSecret")))
check("a secret that cannot be described: exit 1 with AWS's reason", rc == 1 and "DescribeSecret" in err)
for s, want in (("2026-10-28T10:37:27.418955Z", "2026-10-28T10:37:27.418955+00:00"),
                ("2026-11-05T23:01:50.211479335Z", "2026-11-05T23:01:50.211479+00:00"),
                (SECRET_MADE, SECRET_MADE)):
    check(f"stamp reads {s}", dd_traces.stamp(s).isoformat() == want)
for s in ("2026-10-28T10:37:27", None, ""):
    try:
        dd_traces.stamp(s)
        refused = False
    except ValueError:
        refused = True
    check(f"stamp refuses {s!r} (no zone, or no time)", refused)

print("== nothing the reader runs can make, rotate or revoke a key, and it sends only the secret's read pair ==")
aws_argvs = []
SECRET = {"api-key": "sec-api", "app-key": "sec-app", "site": "datadoghq.com", "write-app-key": "WRITE-KEY-wxyz"}


def aws_all(argv, **kw):
    aws_argvs.append(argv)
    if argv[:3] == ["aws", "secretsmanager", "get-secret-value"]:
        return Done(0, json.dumps(SECRET))
    if argv[:3] == ["aws", "secretsmanager", "describe-secret"]:
        return Done(0, json.dumps({"Name": "watch-it-burn/datadog", "CreatedDate": SECRET_MADE}))
    return Done(1, "", f"fake aws: no {argv[1:3]}")


saved_env = dict(os.environ)
os.environ.update({"DD_API_KEY": "ENV-API-KEY", "DD_APP_KEY": "ENV-APP-KEY",
                   "WIB_FLEET_MONITORS_APP_KEY": "ENV-WRITE-KEY"})
sent, paths, methods = set(), set(), set()
try:
    for mode in (["--traces", "2"], ["--trace", "new"], ["--apm", "--json"], ["--scopes"], ["--credential"]):
        org = Org()
        rc, _, err = run_main(BASE + mode, org, keys=lambda p, r: dd_traces.fm.read_keys(p, r, run=aws_all),
                              describe=lambda p, r: dd_traces.secret_meta(p, r, run=aws_all))
        check(f"{' '.join(mode)}: exit 0 with the secret's pair", rc == 0)
        sent |= {(c[3]["DD-API-KEY"], c[3]["DD-APPLICATION-KEY"]) for c in org.calls}
        paths |= {c[1] for c in org.calls}
        methods |= {c[0] for c in org.calls}
finally:
    os.environ.clear()
    os.environ.update(saved_env)
check("every mode sends the secret's api-key and app-key, never its write-app-key or a key from the environment",
      sent == {("sec-api", "sec-app")})
check("every mode only GETs, and only the five read paths (no key's own path, where a rotate or revoke would go)",
      methods == {"GET"} and paths == {dd_traces.ME_PATH, dd_traces.LLMOBS_PATH, dd_traces.APM_PATH,
                                       dd_traces.KEYS_PATH, dd_traces.API_KEYS_PATH})
check("the only AWS calls are get-secret-value and describe-secret on watch-it-burn/datadog, as the named profile",
      aws_argvs and {tuple(a[:5]) for a in aws_argvs} == {
          ("aws", "secretsmanager", verb, "--secret-id", "watch-it-burn/datadog")
          for verb in ("get-secret-value", "describe-secret")}
      and all(a[a.index("--profile") + 1] == "accen-dev" for a in aws_argvs))
src = (HERE / "dd_traces.py").read_text()
check("dd_traces.py calls Datadog in one place, with GET (so no write path can be added beside it)",
      re.findall(r"\.call\(\s*\"?(\w+)", src) == ["GET"])

if failures:
    print(f"\nFAILED: {len(failures)}")
    sys.exit(1)
print("\nAll dd_traces checks passed.")
