# ABOUTME: Offline tests for verify/dd_purge_public.py (#647): the post-talk purge lists burritobot-public's Agent
# ABOUTME: Observability spans with the read pair, and deletes only the trace ids it listed, with the write key.
"""Nothing here reaches Datadog or AWS. The org is a fake transport answering the four paths the purge uses
(/api/v2/current_user, the Agent Observability span listing, the APM aggregate and the deletion endpoint) and refusing
anything else with 404; it records each request with the application key that sent it. The secret comes from a fake
`keys`, and `read_secret` is run against a fake `aws`.
"""
from __future__ import annotations

import json
import pathlib
import sys
import urllib.parse

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import dd_purge_public as p  # noqa: E402

failures = []


def check(n, c, detail=""):
    print(f"  {'PASS' if c else 'FAIL'}  {n}" + (f"\n        {detail}" if detail and not c else ""))
    if not c:
        failures.append(n)


ORG = "5a6c3583-157d-11f0-845c-2241f983918a"
OTHER = "00000000-1111-2222-3333-444444444444"
SECRET = {"api-key": "API", "app-key": "READ", "write-app-key": "WRITE", "site": "datadoghq.com",
          "org": f"Datadog (Whitney Lee sandbox, {ORG})"}
T0 = 1_794_500_000_000  # ms, 2026-11-12
FROM, TO = "2026-11-12", "2026-11-13"


def span(tid, start_s, ml_app="burritobot"):
    return {"id": f"s-{tid}-{start_s}", "type": "span", "attributes": {
        "trace_id": tid, "ml_app": ml_app, "start_ns": (T0 + start_s * 1000) * 1_000_000}}


def tid(n):
    return f"{n:032x}"


# Five traces over two pages; trace 1 has spans 40 minutes apart, trace 5 is the scrub check's own.
PAGES = [[span(tid(1), 0), span(tid(2), 60), span(tid(1), 2400)],
         [span(tid(3), 120), span(tid(4), 180), span(tid(5), 240, "wib-pii-scrub-check")]]


class Org:
    def __init__(self, pages=PAGES, orgs=None, deletes=None, apm=77):
        self.pages, self.orgs, self.deletes, self.apm = pages, orgs or {}, list(deletes or []), apm
        self.calls = []

    def __call__(self, method, url, headers, body):
        u = urllib.parse.urlparse(url)
        q = dict(urllib.parse.parse_qsl(u.query))
        key = headers.get("DD-APPLICATION-KEY")
        self.calls.append((method, u.path, key, q, json.loads(body) if body else None))
        if method == "GET" and u.path == p.ME_PATH:
            return 200, {"data": {}, "included": [{"type": "orgs", "attributes": {
                "name": "Datadog", "public_id": self.orgs.get(key, ORG)}}]}
        if method == "GET" and u.path == p.LLMOBS_SPANS:
            i = int(q.get("page[cursor]", "0"))
            page = self.pages[i] if i < len(self.pages) else []
            meta = {"page": {"after": str(i + 1)}} if i + 1 < len(self.pages) else {}
            return 200, {"data": page, "meta": meta}
        if method == "POST" and u.path == p.APM_AGGREGATE:
            return 200, {"data": [{"type": "bucket", "attributes": {"compute": {"c0": self.apm}, "by": {}}}]}
        if method == "POST" and u.path == p.DELETE_PATH:
            n = sum(1 for c in self.calls if c[1] == p.DELETE_PATH)
            status = self.deletes.pop(0) if self.deletes else 202
            if status == 202:
                return 202, {"data": {"id": f"req-{n}", "type": "deletion_request",
                                      "attributes": {"product": "llmobs"}}}
            if status == "noid":
                return 202, {"data": {"type": "deletion_request"}}
            return status, {"errors": [f"status {status}"]}
        return 404, {"errors": ["Not found"]}


def run(args, org=None, secret=SECRET):
    org = org or Org()
    out, slept = [], []
    rc = p.main(["--profile", "accen-dev", "--from", FROM, "--to", TO, *args], keys=lambda prof, reg: dict(secret),
                http=org, say=out.append, sleep=slept.append)
    return rc, org, "\n".join(out), slept


def deletes(org):
    return [c for c in org.calls if c[1] == p.DELETE_PATH]


print("== dry run ==")
rc, org, out, _ = run([])
check("a dry run exits 0", rc == 0, out)
check("a dry run sends no deletion", not deletes(org))
check("a dry run never sends the write key", all(c[2] != "WRITE" for c in org.calls))
check("it counts 6 spans in 5 traces and the APM spans", "6 spans in 5 traces" in out and "APM: 77 spans" in out, out)
lists = [c for c in org.calls if c[1] == p.LLMOBS_SPANS]
check("it reads both pages", len(lists) == 2)
check("every listing asks k8s.cluster.name:burritobot-public with no ml_app filter, so the check's spans are in it",
      all(c[3].get("filter[query]") == "k8s.cluster.name:burritobot-public" and "filter[ml_app]" not in c[3]
          for c in lists))
check("every listing asks the window given", all(c[3]["filter[from]"] == str(p.ms(FROM)) and
                                                 c[3]["filter[to]"] == str(p.ms(TO)) for c in lists))
check("the APM count asks kube_cluster_name:burritobot-public",
      any(c[1] == p.APM_AGGREGATE and c[4]["data"]["attributes"]["filter"]["query"] ==
          "kube_cluster_name:burritobot-public" for c in org.calls))

rc, org, out, _ = run(["--service", "wib-pii-scrub-check"])
lists = [c for c in org.calls if c[1] == p.LLMOBS_SPANS]
check("--service narrows the listing to that service on the cluster",
      rc == 0 and lists and all(c[3]["filter[query]"] == "k8s.cluster.name:burritobot-public service:wib-pii-scrub-check"
                                for c in lists), out)
check("--service narrows the APM count the same way",
      any(c[1] == p.APM_AGGREGATE and c[4]["data"]["attributes"]["filter"]["query"] ==
          "kube_cluster_name:burritobot-public service:wib-pii-scrub-check" for c in org.calls))

print("== batches and queries ==")
inv = p.inventory(p.fm.Datadog("datadoghq.com", "API", "READ", http=Org()), p.ms(FROM), p.ms(TO))
check("trace 1's two spans make one entry with its first and last start", inv[tid(1)] == [T0, T0 + 2_400_000, 2], inv)
plan = p.batches(inv, 2)
check("5 traces in batches of 2 are 3 batches, in start order",
      [b[0] for b in plan] == [[tid(1), tid(2)], [tid(3), tid(4)], [tid(5)]], plan)
check("a batch's window runs from its first span less PAD_MS to its last span plus PAD_MS",
      plan[0][1:] == (T0 - p.PAD_MS, T0 + 2_400_000 + p.PAD_MS), plan[0])
check("one id is @trace_id:<id>", p.query_for(["ab"]) == "@trace_id:ab")
check("several are an OR group", p.query_for(["ab", "cd"]) == "@trace_id:(ab OR cd)")

print("== apply ==")
rc, org, out, _ = run(["--apply", "--batch", "2"])
d = deletes(org)
check("--apply exits 0", rc == 0, out)
check("--apply sends one request per batch", len(d) == 3, out)
check("every deletion is sent with the write key, never the read pair", all(c[2] == "WRITE" for c in d))
check("the write key is sent nowhere but the deletion and its org check",
      all(c[1] in (p.DELETE_PATH, p.ME_PATH) for c in org.calls if c[2] == "WRITE"))
named = [c[4]["data"]["attributes"]["query"]["query"] for c in d]
check("each request names its traces by @trace_id and nothing else",
      named == [f"@trace_id:({tid(1)} OR {tid(2)})", f"@trace_id:({tid(3)} OR {tid(4)})", f"@trace_id:{tid(5)}"], named)
check("each request is a create_deletion_req with a window",
      all(c[4]["data"]["type"] == "create_deletion_req" and
          c[4]["data"]["attributes"]["from"] < c[4]["data"]["attributes"]["to"] for c in d))
check("the request ids are printed", "id req-1" in out and "id req-3" in out, out)

print("== the org guard ==")
rc, org, out, _ = run(["--apply"], Org(orgs={"READ": OTHER}))
check("a read pair that reaches another org exits 1 and reads and deletes nothing",
      rc == 1 and not deletes(org) and not any(c[1] == p.LLMOBS_SPANS for c in org.calls), out)
rc, org, out, _ = run(["--apply"], Org(orgs={"WRITE": OTHER}))
check("a write key that reaches another org exits 1 and deletes nothing", rc == 1 and not deletes(org), out)
rc, org, out, _ = run([], secret={**SECRET, "org": "Datadog"})
check("a secret whose org names no uuid exits 1 and reads nothing", rc == 1 and len(org.calls) == 0, out)
rc, org, out, _ = run(["--apply"], secret={k: v for k, v in SECRET.items() if k != "write-app-key"})
check("--apply with no write-app-key exits 1 and deletes nothing", rc == 1 and not deletes(org), out)
rc, org, out, _ = run([], secret={k: v for k, v in SECRET.items() if k != "app-key"})
check("a secret with no read pair exits 1", rc == 1 and not org.calls, out)

print("== refusals ==")
rc, org, out, slept = run(["--apply", "--batch", "5"], Org(deletes=[429, 412, 202]))
check("a 429 and a 412 are waited out and retried", rc == 0 and len(deletes(org)) == 3 and len(slept) == 2, out)
rc, org, out, slept = run(["--apply", "--batch", "5"], Org(deletes=[429] * p.RETRIES))
check("a refusal that never ends exits 1 after RETRIES tries", rc == 1 and len(deletes(org)) == p.RETRIES, out)
rc, org, out, _ = run(["--apply", "--batch", "2"], Org(deletes=[400]))
check("any other refusal stops the purge at once and exits 1", rc == 1 and len(deletes(org)) == 1 and "400" in out, out)
rc, org, out, _ = run(["--apply"], Org(deletes=["noid"]))
check("an accepted request with no id exits 1", rc == 1, out)
rc, org, out, _ = run([], Org(pages=[[span("not a trace id", 0)]]))
check("a span whose trace id no query can name exits 1", rc == 1 and "not a trace id" in out, out)

print("== --verify ==")
rc, org, out, _ = run(["--verify"])
check("--verify exits 1 while spans are left, and deletes nothing", rc == 1 and not deletes(org), out)
rc, org, out, _ = run(["--verify"], Org(pages=[[]]))
check("--verify exits 0 when none is left", rc == 0 and "Purged" in out, out)

print("== times and the secret ==")
check("a bare date is midnight UTC", p.ms("2026-11-12") == 1_794_441_600_000)
check("a time with a zone is read as given", p.ms("2026-11-12T01:00:00-08:00") == 1_794_474_000_000)
rc, org, out, _ = run(["--from", "2026-11-12T10:00:00"])
check("a time with no zone exits 2 and calls nothing", rc == 2 and not org.calls, out)
rc, org, out, _ = run(["--from", "2026-11-14"])
check("--from after --to exits 2", rc == 2 and not org.calls, out)
seen = []


class Done:
    returncode, stdout, stderr = 0, json.dumps(SECRET), ""


got = p.read_secret("accen-dev", "us-west-2", run=lambda argv, **kw: seen.append(argv) or Done())
check("read_secret asks the named profile and region for watch-it-burn/datadog",
      got == SECRET and seen and seen[0][:4] == ["aws", "secretsmanager", "get-secret-value", "--secret-id"]
      and "watch-it-burn/datadog" in seen[0] and seen[0][seen[0].index("--profile") + 1] == "accen-dev"
      and seen[0][seen[0].index("--region") + 1] == "us-west-2", seen)

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    sys.exit(1)
print("dd_purge_public.py deletes only the burritobot-public traces it listed, with the write key, in the org the "
      "secret names.")
