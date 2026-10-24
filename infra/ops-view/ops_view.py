# ABOUTME: The shared ops view (#308): one row per cluster answering who has it, is it up, and where they are,
# ABOUTME: joined from the provisioning claims, the apex routing table plus each console's /cost, and the instructor org.
"""One question, one view: for this cluster, who has it, is it up, and where are they?

Before this the answer took three credentials and two URLs, and neither page could answer the other's half:
provisioning's /admin/roster knows who claimed what and nothing about the cluster, start.agenticburn.com knows
which routed consoles answer and nothing about who holds them, and challenge progress was nowhere but the
projector leaderboard, which by design never names a person. This joins the three, by cluster name.

The sources, each read the way its owner already exposes it, and nothing asked of any of them:
    claims     provisioning GET /admin/export (claimed rows, CSV), token-gated with the provisioning ADMIN_TOKEN.
               fleet.sh resolves the token (resolve_admin_token) and hands it over in WIB_ADMIN_TOKEN.
    liveness   apex GET start.agenticburn.com/roster.json (the routed hosts, public), then each host's
               GET /cost, the same probe start.agenticburn.com makes. Plus the instructor org's agent heartbeat.
    progress   the instructor Datadog org, keys from Secrets Manager watch-it-burn/datadog (fleet_monitors.py).
               The queries ARE the leaderboard's (infra/datadog-fleet/leaderboard.yaml), sent to the scalar
               query API one at a time, so this view and the projector board cannot disagree about a column.

Names join everything. Claims and Datadog carry the cluster name (watch-it-burn-attendee-042); the routing table
carries the public host (<two-word-name>.agenticburn.com). The name-to-host table comes from fleet.sh hosts, which
asks public_host_for, the one function that decides a cluster's hostname. This file holds no copy of the grid.

Unknown is not no. A source that cannot be read is reported at the top in red and its cells show "?", never a
blank that reads as "unclaimed" or "not done". In a one-shot run any failed source makes the exit status 1.

The output names attendees by email. It is for the people running the room: never put it on the projector, which
is what the leaderboard is for. The HTML file is written mode 0600.

Usage (fleet.sh resolves the token and passes the account, region and hosts table; it is the normal way in):
    fleet.sh ops                         # one table on stdout, plus logs/ops-view.html
    fleet.sh ops attendee-04 alice@      # only rows whose cluster, host or email contains a term
    fleet.sh ops --watch 30              # refresh every 30s; open the HTML file, it reloads itself
    fleet.sh ops --json                  # the joined rows as JSON
"""
from __future__ import annotations

import argparse
import concurrent.futures
import csv
import datetime as dt
import html
import io
import json
import os
import pathlib
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "datadog-fleet"))
import fleet_monitors as fm  # noqa: E402

ROSTER_URL = "https://start.agenticburn.com/roster.json"
CONSOLE_TIMEOUT = 6      # seconds; the same bound start.agenticburn.com puts on its /cost poll
PROBE_WORKERS = 32
LIVE_SPAN_RE = re.compile(r"^(\d+)([mhd])$")
SPAN_SECONDS = {"m": 60, "h": 3600, "d": 86400}
UNKNOWN = None
# Exit statuses. A source that could not be read is EXIT_SOURCES; a run refused before it reads anything (no
# token, an interval faster than the start page polls, no name table) is EXIT_USAGE, the argparse convention.
EXIT_SOURCES = 1
EXIT_USAGE = 2


# ---- HTTP: one injectable seam, so the tests drive every source through fakes ----------------------------------

def http_get(url: str, timeout: float, headers: dict | None = None) -> tuple[int, str]:
    req = urllib.request.Request(url, headers=headers or {}, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode(errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(errors="replace")


class SourceError(RuntimeError):
    """A source could not be read. The message never carries a credential or a token-bearing URL."""


# ---- the name table (fleet.sh hosts) ----------------------------------------------------------------------------

def load_hosts(text: str) -> dict[str, dict]:
    """name<TAB>host<TAB>kind lines from `fleet.sh hosts` -> {name: {host, kind}}."""
    table = {}
    for line in text.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) != 3 or not all(parts):
            raise SourceError(f"hosts table: malformed line {line!r} (want name<TAB>host<TAB>kind)")
        name, host, kind = parts
        table[name] = {"host": host, "kind": kind}
    if not table:
        raise SourceError("hosts table is empty; it comes from `fleet.sh hosts`")
    return table


# ---- claims (provisioning /admin/export) -------------------------------------------------------------------------

def fetch_claims(base_url: str, token: str, get=http_get) -> dict[str, dict]:
    url = f"{base_url.rstrip('/')}/admin/export?{urllib.parse.urlencode({'token': token})}"
    where = f"{base_url.rstrip('/')}/admin/export"
    try:
        status, body = get(url, 20)
    except (OSError, urllib.error.URLError) as e:
        raise SourceError(f"{where}: {getattr(e, 'reason', e)}") from None
    if status == 403:
        raise SourceError(f"{where}: 403, the admin token was refused")
    if status != 200:
        raise SourceError(f"{where}: HTTP {status}")
    reader = csv.DictReader(io.StringIO(body))
    if not {"email", "cluster_name"} <= set(reader.fieldnames or []):
        raise SourceError(f"{where}: not the export CSV (want email and cluster_name columns, got "
                          f"{reader.fieldnames})")
    claims = {}
    for r in reader:
        name = (r.get("cluster_name") or "").strip()
        if not name:
            raise SourceError(f"{where}: a row has no cluster_name; has the export's header changed?")
        claims[name] = {"email": (r.get("email") or "").strip(), "claimed_at": (r.get("claimed_at") or "").strip(),
                        "console_url": (r.get("console_url") or "").strip()}
    return claims


# ---- liveness (apex roster + each console's /cost) ---------------------------------------------------------------

def fetch_routed(url: str = ROSTER_URL, get=http_get) -> list[str]:
    try:
        status, body = get(url, 10)
    except (OSError, urllib.error.URLError) as e:
        raise SourceError(f"{url}: {getattr(e, 'reason', e)}") from None
    if status != 200:
        raise SourceError(f"{url}: HTTP {status}")
    try:
        data = json.loads(body)
    except ValueError:
        raise SourceError(f"{url}: not JSON") from None
    if not isinstance(data, list):
        raise SourceError(f"{url}: not a list")
    return [c["host"] for c in data if isinstance(c, dict) and isinstance(c.get("host"), str)]


def probe_console(host: str, get=http_get) -> dict:
    """GET https://<host>/cost. Up means a 200 with a JSON body, which is what the start page counts."""
    try:
        status, body = get(f"https://{host}/cost", CONSOLE_TIMEOUT)
    except (OSError, urllib.error.URLError) as e:
        return {"console": "down", "why": str(getattr(e, "reason", e))[:80], "usd": None}
    if status != 200:
        return {"console": "down", "why": f"HTTP {status}", "usd": None}
    try:
        usd = float(json.loads(body).get("usd") or 0)
    except (ValueError, AttributeError, TypeError):
        return {"console": "down", "why": "/cost is not JSON", "usd": None}
    return {"console": "up", "why": "", "usd": usd}


def probe_all(hosts: list[str], get=http_get) -> dict[str, dict]:
    with concurrent.futures.ThreadPoolExecutor(max_workers=PROBE_WORKERS) as pool:
        return dict(zip(hosts, pool.map(lambda h: probe_console(h, get), hosts)))


# ---- progress (the leaderboard's own queries, against the instructor org) ---------------------------------------

def leaderboard_columns(board: dict) -> tuple[int, list[dict]]:
    """The leaderboard's table as (window seconds, columns). A column is one formula over one query.

    kind: "online" for the agent heartbeat, "tick" for a challenge that is done at >= 1, "number" for one shown
    as a value (Challenge 4's bill). Decided from the board's own conditional formats, so a column added there
    arrives here with the right shape and nobody edits this file.
    """
    tables = [w["definition"] for w in board["widgets"] if w["definition"]["type"] == "query_table"]
    if len(tables) != 1:
        raise SourceError("leaderboard.yaml must hold exactly one query_table")
    table = tables[0]
    m = LIVE_SPAN_RE.match(str(table.get("time", {}).get("live_span", "")))
    if not m:
        raise SourceError("leaderboard.yaml's table has no live_span like 4h")
    window = int(m.group(1)) * SPAN_SECONDS[m.group(2)]
    req = table["requests"][0]
    queries = {q["name"]: q for q in req["queries"]}
    cols = []
    for f in req["formulas"]:
        name = f["formula"]
        if name not in queries:
            raise SourceError(f"leaderboard formula {name!r} is not a single query this view can send")
        ticks = [c for c in f.get("conditional_formats", []) if c.get("comparator") == ">=" and c.get("value") == 1]
        kind = "online" if name == "online" else ("tick" if ticks else "number")
        cols.append({"name": name, "alias": f.get("alias", name), "kind": kind, "query": queries[name]})
    return window, cols


def scalar_body(query: dict, window: int, now: dt.datetime) -> dict:
    to_ms = int(now.timestamp() * 1000)
    return {"data": {"type": "scalar_request", "attributes": {
        "from": to_ms - window * 1000, "to": to_ms,
        "queries": [query], "formulas": [{"formula": query["name"]}]}}}


def parse_scalar(resp: dict, group: str = fm.GROUP_BY) -> dict[str, float]:
    """A scalar response -> {kube_cluster_name: value}. Fails on a shape it does not know."""
    try:
        cols = resp["data"]["attributes"]["columns"]
    except (KeyError, TypeError):
        raise SourceError("scalar response has no data.attributes.columns") from None
    groups = [c for c in cols if c.get("type") == "group" and c.get("name") == group]
    numbers = [c for c in cols if c.get("type") == "number"]
    if not cols or (not groups and not numbers):
        return {}
    if len(groups) != 1 or len(numbers) != 1:
        raise SourceError(f"scalar response: want one {group} column and one number column, got "
                          f"{[(c.get('type'), c.get('name')) for c in cols]}")
    out = {}
    for g, v in zip(groups[0]["values"], numbers[0]["values"]):
        name = g[0] if isinstance(g, list) else g
        if isinstance(name, str) and v is not None:
            out[name] = float(v)
    return out


def fetch_progress(dd: fm.Datadog, window: int, cols: list[dict], now: dt.datetime) -> dict[str, dict]:
    progress: dict[str, dict] = {}
    for c in cols:
        try:
            resp = dd.call("POST", "/api/v2/query/scalar", scalar_body(c["query"], window, now))
        except (RuntimeError, OSError) as e:
            raise SourceError(f"instructor org, column {c['alias']!r}: {e}") from None
        for name, v in parse_scalar(resp).items():
            progress.setdefault(name, {})[c["name"]] = v
    return progress


# ---- the join ------------------------------------------------------------------------------------------------------

def kind_of(name: str, hosts: dict) -> str:
    return hosts.get(name, {}).get("kind", "unknown")


def build_rows(hosts: dict, routed: list[str] | None, claims: dict | None, probes: dict,
               progress: dict | None, cols: list[dict]) -> list[dict]:
    """One row per cluster any source knows about, keyed by cluster name where one can be found."""
    by_host = {v["host"]: n for n, v in hosts.items()}
    routed_set = set(routed or [])
    names: set[str] = set()
    orphans: list[str] = []          # a routed host no name in the table maps to
    for h in routed or []:
        if h in by_host:
            names.add(by_host[h])
        else:
            orphans.append(h)
    names |= set(claims or {})
    names |= set(progress or {})

    rows = []
    for key in sorted(names) + sorted(orphans):
        is_name = key in names
        name = key if is_name else ""
        host = hosts.get(name, {}).get("host", "") if is_name else key
        if not host and claims and name in claims:
            host = urllib.parse.urlsplit(claims[name]["console_url"]).hostname or ""
        claim = (claims or {}).get(name)
        probe = probes.get(host)
        prog = (progress or {}).get(name, {})
        row = {
            "name": name,
            "host": host,
            "kind": kind_of(name, hosts) if name else "unknown",
            "email": UNKNOWN if claims is None else (claim["email"] if claim else ""),
            "claimed_at": "" if not claim else claim["claimed_at"],
            "routed": UNKNOWN if routed is None else (host in routed_set),
            "console": (UNKNOWN if routed is None else "unrouted") if probe is None else probe["console"],
            "console_why": "" if probe is None else probe["why"],
            "usd": None if probe is None else probe["usd"],
            "agent": UNKNOWN if progress is None else bool(prog.get("online", 0) >= 1),
            "progress": {c["name"]: (UNKNOWN if progress is None else prog.get(c["name"], 0.0))
                         for c in cols if c["kind"] != "online"},
        }
        row["attention"] = attention(row)
        rows.append(row)
    rows.sort(key=lambda r: (rank(r), r["name"] or r["host"]))
    return rows


def attention(row: dict) -> str:
    """Why a presenter should walk over, or "" if nothing says so. Only a claimed cluster has someone waiting."""
    if not row["email"]:
        return ""
    if row["console"] in ("down", "unrouted"):
        return f"console {row['console']}" + (f" ({row['console_why']})" if row["console_why"] else "")
    if row["agent"] is False:
        return "the instructor org has not heard from its agent"
    return ""


def rank(row: dict) -> int:
    if row["attention"]:
        return 0
    if row["email"]:
        return 1
    if row["kind"] == "attendee":
        return 2
    return 3


def summarise(rows: list[dict], errors: dict[str, str]) -> dict:
    claimed = [r for r in rows if r["email"]]
    return {
        "clusters": len(rows),
        "claimed": None if "claims" in errors else len(claimed),
        "free": None if "claims" in errors or "routes" in errors else
        sum(1 for r in rows if r["kind"] == "attendee" and r["routed"] and not r["email"]),
        "consoles_up": None if "routes" in errors else sum(1 for r in rows if r["console"] == "up"),
        "routed": None if "routes" in errors else sum(1 for r in rows if r["routed"]),
        "attention": sum(1 for r in rows if r["attention"]),
    }


def matches(row: dict, terms: list[str]) -> bool:
    hay = " ".join(str(row.get(k) or "") for k in ("name", "host", "email")).lower()
    return all(t.lower() in hay for t in terms)


# ---- rendering -------------------------------------------------------------------------------------------------------

def label_of(row: dict) -> str:
    return row["host"].split(".", 1)[0] if row["host"] else "?"


def short_name(row: dict) -> str:
    return row["name"].removeprefix("watch-it-burn-") if row["name"] else "(not in the name table)"


def cell(v, kind: str) -> str:
    if v is UNKNOWN:
        return "?"
    if kind == "tick":
        return "x" if v >= 1 else "."
    return f"{v:.2f}"


def yes_no(v) -> str:
    return "?" if v is UNKNOWN else ("up" if v is True else ("silent" if v is False else str(v)))


def render_text(rows: list[dict], cols: list[dict], summary: dict, errors: dict[str, str], stamp: str) -> str:
    out = io.StringIO()
    n = lambda v: "?" if v is None else str(v)  # noqa: E731
    out.write(f"ops view, {stamp}: {summary['clusters']} clusters, {n(summary['claimed'])} claimed, "
              f"{n(summary['free'])} free routed seats, {n(summary['consoles_up'])}/{n(summary['routed'])} "
              f"consoles up, {summary['attention']} need attention\n")
    for src, why in errors.items():
        out.write(f"  UNAVAILABLE {src}: {why}\n")
    pcols = [c for c in cols if c["kind"] != "online"]
    head = ["cluster", "name", "claimed by", "console", "agent"] + [c["alias"].split(" ")[0] for c in pcols] + ["note"]
    body = [[label_of(r), short_name(r), "?" if r["email"] is UNKNOWN else (r["email"] or "-"),
             yes_no(r["console"]), yes_no(r["agent"])]
            + [cell(r["progress"][c["name"]], c["kind"]) for c in pcols] + [r["attention"]] for r in rows]
    widths = [max(len(str(x)) for x in col) for col in zip(head, *body)] if body else [len(h) for h in head]
    for line in [head] + body:
        out.write("  ".join(str(x).ljust(w) for x, w in zip(line, widths)).rstrip() + "\n")
    legend = ", ".join(c["alias"] for c in pcols)
    out.write(f"progress columns, from the leaderboard: {legend}. x done, . not yet, ? unknown\n")
    return out.getvalue()


CSS = """body{font:14px/1.4 system-ui,sans-serif;margin:16px;background:#111;color:#eee}
h1{font-size:20px;margin:0 0 4px}.muted{color:#999}.err{color:#ff6b6b;font-weight:600}
.warn{background:#3a1d1d;border:1px solid #ff6b6b;padding:6px 10px;margin:8px 0}
table{border-collapse:collapse;margin-top:10px}th,td{padding:3px 8px;border-bottom:1px solid #333;text-align:left}
th{position:sticky;top:0;background:#222}td.c{text-align:center}.up{color:#5fd35f}.down,.unrouted,.silent{color:#ff6b6b}
.done{background:#1f5f1f}.att{background:#2a1515}input{font:inherit;padding:4px 8px;margin-top:8px;width:320px}"""


def render_html(rows: list[dict], cols: list[dict], summary: dict, errors: dict[str, str], stamp: str,
                refresh: int | None) -> str:
    e = html.escape
    n = lambda v: "?" if v is None else str(v)  # noqa: E731
    pcols = [c for c in cols if c["kind"] != "online"]
    meta = f'<meta http-equiv="refresh" content="{int(refresh)}">' if refresh else ""
    errs = "".join(f'<div class="err">UNAVAILABLE {e(s)}: {e(w)}. Its cells show ?, not "no".</div>'
                   for s, w in errors.items())
    head = "".join(f"<th>{e(h)}</th>" for h in ["cluster", "name", "claimed by", "claimed at", "console", "agent"]) \
        + "".join(f"<th>{e(c['alias'])}</th>" for c in pcols) + "<th>needs attention</th>"
    trs = []
    for r in rows:
        tds = [f"<td>{e(label_of(r))}</td>", f"<td class=muted>{e(short_name(r))}</td>",
               f"<td>{'?' if r['email'] is UNKNOWN else e(r['email'] or '-')}</td>",
               f"<td class=muted>{e(r['claimed_at'])}</td>",
               f"<td class='{e(str(r['console']))}'>{e(yes_no(r['console']))}</td>",
               f"<td class='{e(yes_no(r['agent']))}'>{e(yes_no(r['agent']))}</td>"]
        for c in pcols:
            v = r["progress"][c["name"]]
            done = c["kind"] == "tick" and v is not UNKNOWN and v >= 1
            tds.append(f"<td class='c{' done' if done else ''}'>{e(cell(v, c['kind']))}</td>")
        tds.append(f"<td>{e(r['attention'])}</td>")
        trs.append(f"<tr class='{'att' if r['attention'] else ''}'>{''.join(tds)}</tr>")
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">{meta}<title>Watch It Burn: ops view</title>
<style>{CSS}</style></head><body>
<h1>Ops view: who has it, is it up, where are they</h1>
<div class="muted">{e(stamp)}. {summary['clusters']} clusters, {n(summary['claimed'])} claimed,
{n(summary['free'])} free routed seats, {n(summary['consoles_up'])}/{n(summary['routed'])} consoles answer /cost,
{summary['attention']} need attention.</div>
<div class="warn">Names attendees by email. For the people running the room: never on the projector
(that is the challenge leaderboard).</div>
{errs}
<input id="q" type="search" placeholder="find a cluster, host or email" autocomplete="off">
<table><thead><tr>{head}</tr></thead><tbody id="rows">{''.join(trs)}</tbody></table>
<p class="muted">Claims: provisioning /admin/export. Console: start.agenticburn.com's routing table, then each
host's /cost. Agent and progress: the instructor Datadog org, the leaderboard's own queries.</p>
<script>
const q = document.getElementById("q");
q.addEventListener("input", () => {{
  const t = q.value.trim().toLowerCase();
  for (const tr of document.getElementById("rows").rows)
    tr.style.display = !t || tr.textContent.toLowerCase().includes(t) ? "" : "none";
}});
</script></body></html>
"""


def write_private(path: pathlib.Path, text: str) -> None:
    """Atomic and 0600 from the first byte: the file names every attendee who claimed a seat."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


# ---- one cycle ---------------------------------------------------------------------------------------------------

class Sources:
    """Everything a cycle reads, with each seam injectable for the tests."""

    def __init__(self, hosts: dict, provisioning_url: str, token: str, roster_url: str, profile: str, region: str,
                 get=http_get, keys=fm.read_keys, dd_http=None, board=None):
        self.hosts, self.provisioning_url, self.token = hosts, provisioning_url, token
        self.roster_url, self.profile, self.region = roster_url, profile, region
        self.get, self.keys, self.dd_http = get, keys, dd_http
        self.board = board if board is not None else fm.load_dashboard(fm.LEADERBOARD_FILE)
        self.dd: fm.Datadog | None = None

    def datadog(self) -> fm.Datadog:
        if self.dd is None:
            try:
                api, app, site = self.keys(self.profile, self.region)
            except FileNotFoundError:
                raise SourceError("the aws CLI is not on PATH, so the instructor org keys cannot be read") from None
            except (RuntimeError, OSError, ValueError, subprocess.TimeoutExpired) as e:
                raise SourceError(f"instructor org keys: {e}") from None
            self.dd = fm.Datadog(site, api, app, http=self.dd_http)
        return self.dd


def cycle(src: Sources, now: dt.datetime) -> tuple[list[dict], list[dict], dict[str, str]]:
    errors: dict[str, str] = {}
    window, cols = leaderboard_columns(src.board)
    claims = routed = progress = None
    try:
        claims = fetch_claims(src.provisioning_url, src.token, src.get)
    except SourceError as e:
        errors["claims"] = str(e)
    try:
        routed = fetch_routed(src.roster_url, src.get)
    except SourceError as e:
        errors["routes"] = str(e)
    probes = probe_all(routed, src.get) if routed else {}
    try:
        progress = fetch_progress(src.datadog(), window, cols, now)
    except SourceError as e:
        errors["progress"] = str(e)
    return build_rows(src.hosts, routed, claims, probes, progress, cols), cols, errors


def main(argv=None, get=http_get, keys=fm.read_keys, dd_http=None, now=None, sleep=time.sleep, out=sys.stdout) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("terms", nargs="*", help="only rows whose cluster, host or email contains every term")
    p.add_argument("--hosts", required=True, help="the name table from `fleet.sh hosts`")
    p.add_argument("--provisioning-url", required=True)
    p.add_argument("--roster-url", default=ROSTER_URL)
    p.add_argument("--profile", required=True, help="AWS profile holding watch-it-burn/datadog (never the ambient one)")
    p.add_argument("--region", required=True)
    p.add_argument("--html", help="also write the view here (mode 0600)")
    p.add_argument("--json", action="store_true", help="print the joined rows as JSON instead of the table")
    p.add_argument("--watch", type=int, metavar="SECONDS", help="refresh forever; the HTML reloads itself")
    a = p.parse_args(argv)
    token = os.environ.get("WIB_ADMIN_TOKEN", "")
    if not token:
        print("ops: WIB_ADMIN_TOKEN is not set. Run it as `fleet.sh ops`, which resolves the provisioning admin "
              "token, or export WIB_ADMIN_TOKEN for this one command.", file=sys.stderr)
        return EXIT_USAGE
    if a.watch is not None and a.watch < 10:
        print("ops: --watch below 10s would poll every console faster than the start page does", file=sys.stderr)
        return EXIT_USAGE
    try:
        hosts = load_hosts(pathlib.Path(a.hosts).read_text(encoding="utf-8"))
    except (OSError, SourceError) as e:
        print(f"ops: {e}", file=sys.stderr)
        return EXIT_USAGE
    src = Sources(hosts, a.provisioning_url, token, a.roster_url, a.profile, a.region, get=get, keys=keys,
                  dd_http=dd_http)
    while True:
        t = now() if now else dt.datetime.now(dt.timezone.utc)
        rows, cols, errors = cycle(src, t)
        shown = [r for r in rows if matches(r, a.terms)]
        summary = summarise(rows, errors)
        stamp = t.strftime("%Y-%m-%d %H:%M:%SZ")
        if a.html:
            write_private(pathlib.Path(a.html), render_html(shown, cols, summary, errors, stamp, a.watch))
        if a.json:
            out.write(json.dumps({"at": stamp, "summary": summary, "errors": errors, "rows": shown}, indent=2) + "\n")
        else:
            out.write(render_text(shown, cols, summary, errors, stamp))
            if a.html:
                out.write(f"html: {a.html}\n")
        out.flush()
        if a.watch is None:
            return EXIT_SOURCES if errors else 0
        sleep(a.watch)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(0)
