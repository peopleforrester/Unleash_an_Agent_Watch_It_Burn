# ABOUTME: Offline tests for the shared ops view (#308): the three sources join by cluster name, an unreadable
# ABOUTME: source shows as unknown and never as "no", progress is the leaderboard's own queries, and no token leaks.
"""Nothing here reaches provisioning, the apex router, a console, AWS or Datadog. Every source is a fake.

What is held:
  * the name table is fleet.sh's own public_host_for, run for real, so the view joins on the hostnames the
    router actually publishes and carries no second copy of the grid;
  * the progress columns are leaderboard.yaml's queries, sent verbatim, so the ops view and the projector
    board cannot disagree about what "done" means;
  * the join: who has it (claims), is it up (routing table, /cost, agent heartbeat), where are they (columns);
  * unknown is not no: a source that fails is named at the top, its cells read "?", and the run exits 1;
  * the admin token appears nowhere in the output, and the HTML, which names attendees, is mode 0600.
"""
from __future__ import annotations

import datetime as dt
import io
import json
import os
import pathlib
import re
import stat
import subprocess
import sys
import tempfile

REPO = pathlib.Path(__file__).resolve().parents[1]
FLEET = REPO / "infra/terraform/fleet/fleet.sh"
sys.path.insert(0, str(REPO / "infra" / "ops-view"))
import ops_view as ov  # noqa: E402

fm = ov.fm
failures: list[str] = []
TOKEN = "s3cret-admin-token-xyz"
NOW = dt.datetime(2026, 9, 8, 17, 0, tzinfo=dt.timezone.utc)


def check(name: str, cond: bool) -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        failures.append(name)


def fleet(*args: str, env: dict | None = None) -> subprocess.CompletedProcess:
    e = {k: v for k, v in os.environ.items() if k != "WIB_ADMIN_TOKEN"}
    e.update(env or {})
    return subprocess.run(["bash", str(FLEET), *args], capture_output=True, text=True, env=e, timeout=120)


def host_of(name: str) -> str:
    out = subprocess.run(["bash", "-c", f'source "{FLEET}" 2>/dev/null; public_host_for "$1"', "_", name],
                         capture_output=True, text=True, timeout=60)
    return out.stdout.strip()


print("== the name table is fleet.sh's, not a copy ==")
r = fleet("hosts")
check("fleet.sh hosts exits 0 offline", r.returncode == 0)
HOSTS_TSV = r.stdout
hosts = ov.load_hosts(HOSTS_TSV)
rows_tsv = [line.split("\t") for line in HOSTS_TSV.splitlines()]
check("every line is name, host, kind", all(len(x) == 3 and all(x) for x in rows_tsv))
check("no host is listed for two clusters", len({x[1] for x in rows_tsv}) == len(rows_tsv))
check("the roster comes first, by kind",
      [x[2] for x in rows_tsv[:3]] == ["community", "presenter", "presenter"]
      and hosts["watch-it-burn-community"]["host"] == "attackme.agenticburn.com")
check("presenters by owner, as public_host_for names them",
      hosts["watch-it-burn-michael-admin"]["host"] == "michael-admin.agenticburn.com"
      and hosts["watch-it-burn-whitney-admin"]["host"] == "whitney-admin.agenticburn.com")
attendees = [x for x in rows_tsv if x[2] == "attendee"]
check("every slot of the name grid is listed (the 250-seat plan fits with room)", len(attendees) >= 250)
for n in ("watch-it-burn-attendee-001", "watch-it-burn-attendee-042", "watch-it-burn-attendee-250"):
    check(f"{n} carries public_host_for's answer", hosts[n]["host"] == host_of(n) != "")
grid = subprocess.run(["bash", "-c", f'source "{FLEET}" 2>/dev/null; echo "${{WIB_ADJECTIVES[@]}} ${{WIB_ANIMALS[@]}}"'],
                      capture_output=True, text=True, timeout=60).stdout.split()
src = set(re.findall(r"[a-z]+", (REPO / "infra/ops-view/ops_view.py").read_text().lower()))
check("ops_view.py holds no word of the name grid (it asks fleet.sh)",
      len(grid) > 40 and [w for w in grid if w in src] == [])

print("== progress columns are the leaderboard's ==")
board = fm.load_dashboard(fm.LEADERBOARD_FILE)
window, cols = ov.leaderboard_columns(board)
kinds = {c["name"]: c["kind"] for c in cols}
check("the window is the board's 4h", window == 4 * 3600)
check("online is the heartbeat, 4 is a number, 1 2 3 5 6 are ticks",
      kinds == {"online": "online", "c1": "tick", "c2": "tick", "c3": "tick", "c4": "number",
                "c5": "tick", "c6": "tick"})
check("headers are the board's aliases", [c["alias"] for c in cols if c["kind"] != "online"]
      == ["1 exfil", "2 villain", "3 recipe", "4 bill (USD)", "5 guarded", "6 blocked"])

# ---- fakes ---------------------------------------------------------------------------------------------------------

A1, A2, A3, A5 = (f"watch-it-burn-attendee-00{i}" for i in (1, 2, 3, 5))
H = {n: hosts[n]["host"] for n in (A1, A2, A3, A5, "watch-it-burn-michael-admin")}
EVIL = "<script>alert(1)</script>@x.test"
CSV = ("email,cluster_name,region,console_url,datadog_org,claimed_at,email_sent\n"
       f"alice@x.test,{A1},us-west-2,https://{H[A1]},org-3,2026-09-08T16:01:00Z,1\n"
       f"bob@x.test,{A2},us-west-2,https://{H[A2]},org-4,2026-09-08T16:02:00Z,1\n"
       f"{EVIL},{A5},us-west-2,https://{H[A5]},org-7,2026-09-08T16:03:00Z,0\n")
ROUTED = [H[A1], H[A2], H[A3], H["watch-it-burn-michael-admin"], "mystery.agenticburn.com"]
SERIES = {"online": {A1: 1, A3: 1, "watch-it-burn-michael-admin": 1, A2: 1}, "c1": {A1: 3}, "c4": {A1: 1.234}}


def fake_get(claims_status=200, routed_status=200):
    calls = []

    def get(url, timeout, headers=None):
        calls.append(url)
        if "/admin/export" in url:
            return (claims_status, CSV) if claims_status == 200 else (claims_status, "forbidden")
        if url.endswith("/roster.json"):
            return routed_status, json.dumps([{"host": h, "name": h.split(".")[0]} for h in ROUTED])
        if url == f"https://{H[A2]}/cost":
            return 502, "bad gateway"
        if url == "https://mystery.agenticburn.com/cost":
            raise OSError("timed out")
        if url.endswith("/cost"):
            return 200, json.dumps({"usd": 0.5})
        raise AssertionError(f"unexpected GET {url}")
    get.calls = calls
    return get


def fake_dd(status=200):
    sent = []

    def http(method, url, headers, body):
        req = json.loads(body)
        sent.append((method, url, req))
        if status != 200:
            return status, {"errors": ["bad query"]}
        q = req["data"]["attributes"]["queries"][0]
        series = SERIES.get(q["name"], {})
        return 200, {"data": {"type": "scalar_response", "attributes": {"columns": [
            {"type": "group", "name": "kube_cluster_name", "values": [[n] for n in series]},
            {"type": "number", "name": q["name"], "values": list(series.values())}]}}}
    http.sent = sent
    return http


def keys(profile, region):
    assert (profile, region) == ("accen-dev", "us-west-2"), (profile, region)
    return "api", "app", "datadoghq.com"


def run(*extra, get=None, dd=None, env_token=TOKEN, keys_fn=keys):
    tmp = pathlib.Path(tempfile.mkdtemp())
    (tmp / "hosts.tsv").write_text(HOSTS_TSV)
    page = tmp / "out" / "ops.html"
    argv = ["--hosts", str(tmp / "hosts.tsv"), "--provisioning-url", "https://prov.test",
            "--roster-url", "https://start.test/roster.json", "--profile", "accen-dev", "--region", "us-west-2",
            "--html", str(page), *extra]
    old = os.environ.get("WIB_ADMIN_TOKEN")
    os.environ["WIB_ADMIN_TOKEN"] = env_token
    out = io.StringIO()
    try:
        rc = ov.main(argv, get=get or fake_get(), keys=keys_fn, dd_http=dd or fake_dd(), now=lambda: NOW, out=out)
    finally:
        os.environ.pop("WIB_ADMIN_TOKEN", None)
        if old is not None:
            os.environ["WIB_ADMIN_TOKEN"] = old
    return rc, out.getvalue(), page


print("== Datadog is asked exactly the leaderboard's questions ==")
dd = fake_dd()
rc, _, _ = run("--json", dd=dd)
board_queries = board["widgets"][1]["definition"]["requests"][0]["queries"]
check("one scalar request per column, to the scalar query API",
      [(m, u) for m, u, _ in dd.sent] == [("POST", "https://api.datadoghq.com/api/v2/query/scalar")] * len(cols))
check("each request carries the leaderboard's query verbatim",
      [b["data"]["attributes"]["queries"] for _, _, b in dd.sent] == [[q] for q in board_queries])
spans = {b["data"]["attributes"]["to"] - b["data"]["attributes"]["from"] for _, _, b in dd.sent}
check("over the board's window, ending now", spans == {4 * 3600 * 1000}
      and dd.sent[0][2]["data"]["attributes"]["to"] == int(NOW.timestamp() * 1000))

print("== one row per cluster: who has it, is it up, where are they ==")
rc, js, page = run("--json")
doc = json.loads(js)
rows = {r["name"] or r["host"]: r for r in doc["rows"]}
check("all sources read, exit 0", rc == 0 and doc["errors"] == {})
a1 = rows[A1]
check("a claimed, live, scoring cluster: email, console up, agent up, C1 done, the bill",
      a1["email"] == "alice@x.test" and a1["console"] == "up" and a1["agent"] is True
      and a1["progress"]["c1"] == 3 and abs(a1["progress"]["c4"] - 1.234) < 1e-9 and a1["progress"]["c2"] == 0
      and a1["attention"] == "")
check("a claimed cluster whose console 502s needs attention, and says why",
      rows[A2]["attention"] == "console down (HTTP 502)")
check("a claimed cluster with no route needs attention", rows[A5]["console"] == "unrouted"
      and rows[A5]["attention"] == "console unrouted" and rows[A5]["host"] == H[A5])
check("a claimed cluster the instructor org cannot hear needs attention",
      rows[A5]["agent"] is False)
check("a routed, unclaimed attendee cluster is a free seat", rows[A3]["email"] == "" and doc["summary"]["free"] == 1)
check("a presenter cluster is not a seat", rows["watch-it-burn-michael-admin"]["kind"] == "presenter")
check("a routed host the name table cannot place still gets a row",
      rows["mystery.agenticburn.com"]["name"] == "" and rows["mystery.agenticburn.com"]["console"] == "down")
order = [r["name"] or r["host"] for r in doc["rows"]]
check("the clusters that need a presenter come first", set(order[:2]) == {A2, A5} and order[2] == A1)
check("counts: 3 claimed, 3 of 5 routed consoles up, 2 need attention",
      doc["summary"]["claimed"] == 3 and doc["summary"]["consoles_up"] == 3 and doc["summary"]["routed"] == 5
      and doc["summary"]["attention"] == 2)

print("== the table and the page ==")
rc, text, page = run()
check("the text table names the cluster by the host the room hears", "bane-sabrina" in text or H[A1].split(".")[0] in text)
check("the text table carries the progress legend from the board", "1 exfil" in text and "6 blocked" in text)
body = page.read_text()
check("the HTML is written mode 0600 (it names attendees)", stat.S_IMODE(page.stat().st_mode) == 0o600)
check("an email is escaped, never markup", EVIL not in body and "&lt;script&gt;" in body)
check("the page says it is not for the projector", "never on the projector" in body)
check("a one-shot page does not reload itself", 'http-equiv="refresh"' not in body)
check("no leftover temp file beside it", [p.name for p in page.parent.iterdir()] == ["ops.html"])
rc, text, _ = run("sabrina", "--json")
check("terms filter rows by cluster, host or email",
      [r["name"] for r in json.loads(text)["rows"]] == [n for n in hosts if "sabrina" in hosts[n]["host"]
                                                         and n in (A1, A2, A3, A5)])
check("nothing printed or written carries the admin token",
      all(TOKEN not in s for s in (js, text, body)))

print("== unknown is not no ==")
get = fake_get(claims_status=403)
rc, js, page = run("--json", get=get)
doc = json.loads(js)
check("a refused token is named, and the run fails", rc == ov.EXIT_SOURCES and "403" in doc["errors"].get("claims", ""))
check("with claims unreadable, nobody reads as unclaimed", all(r["email"] is None for r in doc["rows"])
      and doc["summary"]["claimed"] is None and doc["summary"]["free"] is None)
check("the error and the page carry no token", TOKEN not in js and TOKEN not in page.read_text()
      and "UNAVAILABLE claims" in page.read_text())
check("the token went only to the export request",
      [u for u in get.calls if TOKEN in u] == [f"https://prov.test/admin/export?token={TOKEN}"])
rc, js, _ = run("--json", dd=fake_dd(status=400))
doc = json.loads(js)
check("a Datadog failure leaves progress unknown, not undone",
      rc == ov.EXIT_SOURCES and "progress" in doc["errors"]
      and all(v is None for r in doc["rows"] for v in r["progress"].values())
      and all(r["agent"] is None for r in doc["rows"]))
rc, js, _ = run("--json", get=fake_get(routed_status=500))
doc = json.loads(js)
check("an unreadable routing table leaves every console unknown",
      rc == ov.EXIT_SOURCES and all(r["console"] is None for r in doc["rows"]) and doc["summary"]["consoles_up"] is None)


def no_aws(profile, region):
    raise FileNotFoundError("aws")


rc, js, _ = run("--json", keys_fn=no_aws)
check("no aws CLI is a named failure, not a crash", rc == ov.EXIT_SOURCES and "aws CLI" in json.loads(js)["errors"]["progress"])
try:
    ov.parse_scalar({"data": {"attributes": {"columns": [
        {"type": "number", "name": "a", "values": [1]}, {"type": "number", "name": "b", "values": [2]}]}}})
    refused = False
except ov.SourceError:
    refused = True
check("the scalar parser refuses a shape it does not know", refused)

print("== the CLI refuses what it cannot do ==")
get = fake_get()
rc, _, _ = run(env_token="", get=get)
check("no token is refused as a usage error before any request, never sent anonymously",
      rc == ov.EXIT_USAGE and get.calls == [])
get = fake_get()
rc, _, _ = run("--watch", "3", get=get)
check("--watch faster than the start page is refused as a usage error before any request",
      rc == ov.EXIT_USAGE and get.calls == [])
check("a refusal and a failed source are told apart by their status", ov.EXIT_USAGE != ov.EXIT_SOURCES != 0)
slept = []


def one_sleep(s):
    slept.append(s)
    raise KeyboardInterrupt


tmp = pathlib.Path(tempfile.mkdtemp())
(tmp / "h.tsv").write_text(HOSTS_TSV)
os.environ["WIB_ADMIN_TOKEN"] = TOKEN
try:
    ov.main(["--hosts", str(tmp / "h.tsv"), "--provisioning-url", "https://prov.test", "--roster-url",
             "https://start.test/roster.json", "--profile", "accen-dev", "--region", "us-west-2",
             "--html", str(tmp / "w.html"), "--watch", "30"],
            get=fake_get(), keys=keys, dd_http=fake_dd(), now=lambda: NOW, sleep=one_sleep, out=io.StringIO())
except KeyboardInterrupt:
    pass
finally:
    os.environ.pop("WIB_ADMIN_TOKEN", None)
check("--watch sleeps its interval and the page reloads on it",
      slept == [30] and 'http-equiv="refresh" content="30"' in (tmp / "w.html").read_text())

print("== fleet.sh ops: resolves the token, states the account, fails loudly ==")
fake_bin = pathlib.Path(tempfile.mkdtemp())
(fake_bin / "railway").write_text("#!/bin/sh\nexit 1\n")
(fake_bin / "python3").write_text('#!/bin/sh\nprintf "token=%s\\n" "$WIB_ADMIN_TOKEN"; printf "%s\\n" "$@"\n')
for f in fake_bin.iterdir():
    f.chmod(0o755)
empty_home = tempfile.mkdtemp()
path = f"{fake_bin}:{os.environ['PATH']}"
r = fleet("ops", env={"PATH": path, "HOME": empty_home})
check("no resolvable token: exit 1 with the two ways to supply one",
      r.returncode == 1 and "cannot resolve the provisioning admin token" in r.stderr)
logs = pathlib.Path(tempfile.mkdtemp())
r = fleet("ops", "sabrina", "--watch", "30",
          env={"PATH": path, "HOME": empty_home, "WIB_ADMIN_TOKEN": TOKEN, "WIB_OPS_HTML": str(logs / "v.html"),
               "WIB_DEFAULT_ACCOUNT": "accen-dev", "WIB_REGION": "us-west-2"})
argv = r.stdout.splitlines()
check("the token reaches the view in its environment, never its argv",
      r.returncode == 0 and argv[0] == f"token={TOKEN}" and all(TOKEN not in a for a in argv[1:]))
pairs = dict(zip(argv[1:], argv[2:]))
check("the account and region are passed explicitly (AGENTS.md rule 6)",
      pairs.get("--profile") == "accen-dev" and pairs.get("--region") == "us-west-2")
check("the provisioning URL is the fleet's", pairs.get("--provisioning-url") == "https://provisioning.agenticburn.com")
check("the hosts table it passes is fleet.sh hosts", pathlib.Path(pairs.get("--hosts", "/nonexistent")).read_text()
      == HOSTS_TSV)
check("WIB_OPS_HTML places the page, and the operator's own arguments follow",
      pairs.get("--html") == str(logs / "v.html") and argv[-3:] == ["sabrina", "--watch", "30"])
check("fleet.sh usage documents ops and hosts", "  ops [terms...]" in FLEET.read_text()
      and "\n    hosts  " in FLEET.read_text())

if failures:
    print(f"\n{len(failures)} FAILED", file=sys.stderr)
    sys.exit(1)
print("\nThe ops view joins claims, liveness and progress by cluster, and says so when it cannot.")
