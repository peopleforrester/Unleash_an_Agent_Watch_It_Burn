#!/usr/bin/env python3
# ABOUTME: The KubeCon failover an attendee sits through (#986): a local copy of the apex router's cluster leg, backups.py's
# ABOUTME: own Watcher promoting a standby, and headless Chromium on attackme.burritobot.co that never reloads the page.
"""One failover drill, from the attendee's side of the router.

    python3 verify/package_cache.py run playwright -- python verify/failover_drill.py \
        --primary watch-it-burn-community --standby watch-it-burn-private --caddy verify/.tools/bin/caddy --out drill.json

What is real, and what stands in:

  - The clusters are real KubeCon clusters, read with `kubectl --context`: --primary serves attackme first, --standby
    takes it. Neither is changed: the drill reads each console Service's load balancer and sends chats to it.
  - The router is a local Caddy (the router image's version, verify/e2e-tools.lock) running the apex router's cluster
    leg as apex-agenticburn's Caddyfile has it: the support and deployments name maps, the routes.map import, and the
    reverse_proxy options (Host and X-Forwarded-For set, lb_try_duration 5s, TLS with tls_insecure_skip_verify,
    dial_timeout 2s). One header is added on the way back, X-Failover-Upstream, so the drill reads which console
    answered each request. The live router on Railway is never touched.
  - The table is the one `fleet.sh routes roster` writes for attackme: its row, the service and villain rows
    (fleet.sh emit_service_hosts) and the burritobot.co twins of all of them, every one on the primary's console LB.
  - The failure: at the fault the primary's LB is replaced, for the router and for the watcher's self-check alike,
    by 192.0.2.1:443 (TEST-NET-1, RFC 5737), where nothing answers, so every dial times out as an unreachable
    region's LB does. The router answers the browser 502 after its 5-second retry budget; the self-check waits out
    its 10-second timeout.
  - The promotion is backups.py's Watcher with the scheduled watcher's settings (a check every 15 s, a chat check
    every 4th tick, promote after 3 failures in a row) and backups.py's own Router, whose reload script here runs
    `caddy reload` on the local router, as the apex repo's reload-routes.sh does on Railway. It was running before
    the fault, as the scheduled one is. It is built with no `arm` and no `link` (#985): the scheduled watcher arms
    Kyverno on a public standby before it takes attackme and links the new pair, which would change the live
    clusters, so the drill leaves both as found. What the room would see of it is a lit Kyverno badge.
  - The attendee is a fresh headless Chromium at a phone's viewport on http://attackme.burritobot.co:<port>/, with
    the name resolved to the local router (TLS is Railway's edge, ahead of the router, and not what moves). It chats
    once, sits through the failure, and chats again on the same page with nobody touching anything else. Then it
    reloads once, as an attendee who refreshes anyway would.

Every chat carries backups.py's probe marker, so it never reaches the prompt wall. The report is one JSON object on
--out (and stdout); verify/test_kubecon_failover_attendee_live.py judges it.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import socket
import subprocess
import sys
import tempfile
import threading
import time

REPO = pathlib.Path(__file__).resolve().parent.parent
FLEET_DIR = REPO / "infra/terraform/fleet"
sys.path.insert(0, str(FLEET_DIR))
import backups as b  # noqa: E402

ROLE = "community"
DOMAIN = "burritobot.co"            # the domain the room is shown (#651); the agenticburn.com rows are its twins
PAGE = REPO / "gitops/ai-layer/web/burritbot.html"
DEAD = "192.0.2.1:443"              # TEST-NET-1: routable nowhere, so a dial to it times out
INTERVAL, CHAT_EVERY, FAIL_AFTER = 15, 4, 3   # backups.py watch's defaults, which the cron line runs with
ERRORS = ("isn't answering", "Couldn't reach the kitchen", "kitchen isn't answering")
PROMPTS = (f"{b.PROBE_MARKER} Hi! What bases do you have?",
           f"{b.PROBE_MARKER} Did you just ask my name? What is my name?",
           f"{b.PROBE_MARKER} are you still there?")


# --- the router -------------------------------------------------------------------------------------------------
def public_host() -> str:
    """attackme's hostname on the room's domain, from fleet.sh's own naming."""
    host = b.fleet_call("public_host_for", "watch-it-burn-community")
    if not host.endswith(".agenticburn.com"):
        raise SystemExit(f"drill: fleet.sh public_host_for watch-it-burn-community gave '{host}'")
    return host.replace(".agenticburn.com", f".{DOMAIN}")


def table_for(lb: str) -> str:
    """The routes.map rows `fleet.sh routes roster` gives attackme, every one on `lb`: twins first, as fleet.sh does."""
    host = b.fleet_call("public_host_for", "watch-it-burn-community")
    rows = [f"{host}  {lb}:443"] + b.fleet_call("emit_service_hosts", host, lb).splitlines()
    twins = [r.replace(".agenticburn.com ", f".{DOMAIN} ", 1) for r in rows]
    return "# routes.map for the failover drill (#986), attackme's rows only\n" + "\n".join(twins + rows) + "\n"


PROXY_OPTS = """
				header_up Host {host}
				header_up X-Forwarded-For {client_ip}
				header_down X-Failover-Upstream {http.reverse_proxy.upstream.hostport}
				lb_try_duration 5s
				lb_try_interval 250ms
				transport http {
					tls
					tls_insecure_skip_verify
					dial_timeout 2s
				}"""


def caddyfile(d: pathlib.Path, port: int, admin: int, page: pathlib.Path | None = None) -> str:
    """The apex router's cluster leg, with a dead map in front of it: an upstream listed there is dialled at DEAD.
    With `page`, the router itself answers / and /burritobot with that file while the upstream is alive, so a page
    change is tried in a real failover before Argo CD ships it; the page still comes from the router's own address,
    as the console's does, so Chromium treats its requests the same way."""
    repo_page = "" if page is None else f"""
		@repo_page {{
			path / /burritobot
			expression `{{dead}} == ""`
		}}
		handle @repo_page {{
			root * {page.parent}
			rewrite * /{page.name}
			file_server
		}}"""
    return f"""{{
	admin localhost:{admin}
	auto_https off
}}
:{port} {{
	map {{host}} {{route_host}} {{
		support.burritobot.co support-attackme.burritobot.co
		deployments.burritobot.co deployments-attackme.burritobot.co
		default {{host}}
	}}
	map {{route_host}} {{upstream}} {{
		import {d}/routes.map
		default ""
	}}
	map {{upstream}} {{dead}} {{
		import {d}/dead.map
		default ""
	}}
	@routed `{{upstream}} != ""`
	handle @routed {{{repo_page}
		@gone `{{dead}} != ""`
		handle @gone {{
			reverse_proxy {{dead}} {{{PROXY_OPTS}
			}}
		}}
		handle {{
			reverse_proxy {{upstream}} {{{PROXY_OPTS}
			}}
		}}
	}}
	handle {{
		respond "unknown host" 404
	}}
}}
"""


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class LocalRouter:
    def __init__(self, caddy: str, d: pathlib.Path, primary_lb: str, page: pathlib.Path | None = None):
        self.caddy, self.d = caddy, d
        self.port, self.admin = free_port(), free_port()
        (d / "routes.map").write_text(table_for(primary_lb))
        (d / "dead.map").write_text("# upstreams the drill has failed\n")
        (d / "Caddyfile").write_text(caddyfile(d, self.port, self.admin, page))
        (d / "scripts").mkdir()
        # What backups.Router runs to apply a table, as apex's reload-routes.sh does on Railway.
        reload = d / "scripts" / "reload-routes.sh"
        reload.write_text(f"#!/usr/bin/env bash\nexec {caddy} reload --config {d}/Caddyfile --adapter caddyfile "
                          f"--address localhost:{self.admin}\n")
        reload.chmod(0o755)
        self.log = (d / "caddy.log").open("w")
        self.proc = subprocess.Popen([caddy, "run", "--config", str(d / "Caddyfile"), "--adapter", "caddyfile"],
                                     stdout=self.log, stderr=subprocess.STDOUT)
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if self.proc.poll() is not None:
                raise SystemExit(f"drill: caddy exited {self.proc.returncode}: {(d / 'caddy.log').read_text()[-800:]}")
            try:
                with socket.create_connection(("127.0.0.1", self.port), timeout=1):
                    return
            except OSError:
                time.sleep(0.2)
        raise SystemExit("drill: the local router did not listen within 20 s")

    def fail(self, lb: str) -> None:
        (self.d / "dead.map").write_text(f"{lb}:443  {DEAD}\n")
        subprocess.run(["bash", str(self.d / "scripts" / "reload-routes.sh")], check=True, timeout=60)

    def stop(self) -> None:
        self.proc.terminate()
        try:
            self.proc.wait(10)
        except subprocess.TimeoutExpired:
            self.proc.kill()
        self.log.close()


def console_lb(context: str) -> str:
    r = subprocess.run(["kubectl", "--context", context, "-n", "agent", "get", "svc", "console", "-o",
                        "jsonpath={.status.loadBalancer.ingress[0].hostname}"], capture_output=True, text=True, timeout=60)
    if r.returncode != 0 or not r.stdout.strip():
        raise SystemExit(f"drill: no console LB on context {context}: {r.stderr.strip()[-300:]}")
    return r.stdout.strip()


# --- the watcher ------------------------------------------------------------------------------------------------
class WatchThread(threading.Thread):
    """backups.py watch's loop, on the drill's pool, router and dead set."""

    def __init__(self, w: b.Watcher):
        super().__init__(daemon=True)
        self.w, self.stop = w, threading.Event()

    def run(self) -> None:
        tick = 0
        while not self.stop.is_set():
            self.w.tick(chat=tick % CHAT_EVERY == 0)
            tick += 1
            self.stop.wait(INTERVAL)


# --- the page ---------------------------------------------------------------------------------------------------
STATE_JS = """() => {
  const inp = document.getElementById('inp'), w = document.getElementById('witch'), nb = document.getElementById('noburritos');
  const bubbles = [...document.querySelectorAll('#stream .msg')].map(d => ({cls: d.className,
      text: d.firstChild ? d.firstChild.textContent : ''}));
  const m = /(?:^|;\\s*)wib_witch=([^;]*)/.exec(document.cookie || '');
  return {witch: w && !w.hidden ? w.textContent : null, cookie: m ? m[1] : null,
          session: sessionStorage.getItem('wib-sess'), saved: JSON.parse(localStorage.getItem('wib-saved') || '[]').length,
          disabled: inp ? inp.disabled : null, placeholder: inp ? inp.placeholder : null,
          noburritos: nb ? getComputedStyle(nb).display : null, typing: !!document.querySelector('#stream .typing'),
          marker: window.__drill || null, bubbles: bubbles, url: location.href};
}"""


def run_drill(primary: str, standby: str, caddy: str, workdir: pathlib.Path, page_from_repo: bool = False) -> dict:
    from playwright.sync_api import sync_playwright

    host = public_host()
    lbs = {primary: console_lb(primary), standby: console_lb(standby)}
    report: dict = {"primary": primary, "standby": standby, "host": host, "lbs": lbs, "events": [], "chats": [],
                    "timeline": [], "page": "repo" if page_from_repo else "served"}
    router_dir = workdir / "apex"
    router_dir.mkdir()
    router = LocalRouter(caddy, router_dir, lbs[primary], PAGE if page_from_repo else None)
    report["rows"] = len(b.table_rows((router_dir / "routes.map").read_text()))
    dead: set[str] = set()
    pools = {ROLE: [b.Cluster(primary, ROLE, "us-west-2", "roster"),
                    b.Cluster(standby, ROLE, "us-west-2", "night-before", "a")]}

    def check(lb: str, h: str, chat: bool) -> tuple[bool, str]:
        return b.self_check("https://" + (DEAD.rsplit(":", 1)[0] if lb in dead else lb), h, chat)

    events = workdir / "failover.jsonl"
    w = b.Watcher(pools, {ROLE: host}, b.Router(router_dir, retries=3, backoff=5, timeout=60), workdir / "promoted.tsv",
                  events, lb_of=lambda c: lbs[c.name], check=check, fail_after=FAIL_AFTER)
    w.refresh()
    t0 = time.monotonic()
    clock = lambda: round(time.monotonic() - t0, 1)  # noqa: E731
    watcher = WatchThread(w)
    try:
        with sync_playwright() as p:
            br = p.chromium.launch(args=[f"--host-resolver-rules=MAP *.{DOMAIN} 127.0.0.1",
                                         "--disable-features=HttpsUpgrades"])
            ctx = br.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
            pg = ctx.new_page()
            navs: list[str] = []
            pg.on("framenavigated", lambda f: navs.append(f.url) if f == pg.main_frame else None)
            sent: list[dict] = []

            def on_response(r):
                if r.request.method == "POST" and r.url.endswith("/chat"):
                    try:
                        body = json.loads(r.request.post_data or "{}")
                    except ValueError:
                        body = {}
                    sent.append({"at": clock(), "status": r.status, "upstream": r.headers.get("x-failover-upstream"),
                                 "witch": body.get("witch"), "session": body.get("session"), "prompt": body.get("prompt")})
            pg.on("response", on_response)
            url = f"http://{host}:{router.port}/"
            pg.goto(url, wait_until="domcontentloaded", timeout=60000)
            pg.wait_for_function("() => document.getElementById('inp') && !document.getElementById('inp').disabled",
                                 timeout=60000)
            pg.evaluate("() => { window.__drill = 'the page the attendee opened'; }")
            report["before"] = pg.evaluate(STATE_JS)
            watcher.start()

            def chat(text: str, timeout: float = 120) -> dict:
                bots = len(pg.evaluate(STATE_JS)["bubbles"])
                n = len(sent)
                pg.fill("#inp", text)
                pg.press("#inp", "Enter")
                deadline = time.monotonic() + timeout
                while time.monotonic() < deadline:
                    s = pg.evaluate(STATE_JS)
                    if len(sent) > n and not s["typing"] and len(s["bubbles"]) >= bots + 2:
                        reply = s["bubbles"][-1]
                        out = {**sent[n], "shown": reply["text"][:400], "shown_class": reply["cls"],
                               "error_shown": any(e in reply["text"] for e in ERRORS)}
                        report["chats"].append(out)
                        return out
                    time.sleep(0.5)
                out = {"at": clock(), "prompt": text, "timeout": True, "state": pg.evaluate(STATE_JS)}
                report["chats"].append(out)
                return out

            report["chat_before"] = chat(PROMPTS[0])

            # The fault: the primary's LB stops answering, for the room and the watcher at once.
            dead.add(lbs[primary])
            router.fail(lbs[primary])
            report["fault_at"] = clock()
            # An attendee mid-conversation sends before the page has noticed.
            report["chat_during"] = chat(PROMPTS[2], timeout=60)

            promoted_at = enabled_at = None
            last = None
            deadline = time.monotonic() + 600
            while time.monotonic() < deadline:
                s = pg.evaluate(STATE_JS)
                now = clock()
                key = (s["disabled"], s["noburritos"], s["placeholder"])
                if key != last:
                    report["timeline"].append({"at": now, "disabled": s["disabled"], "noburritos": s["noburritos"],
                                               "placeholder": s["placeholder"]})
                    last = key
                if promoted_at is None and events.exists() and '"applied": true' in events.read_text():
                    promoted_at = now
                    report["timeline"].append({"at": now, "event": "promoted"})
                if promoted_at is not None and s["disabled"] is False:
                    enabled_at = now
                    break
                time.sleep(1)
            report["promoted_at"], report["enabled_at"] = promoted_at, enabled_at
            report["events"] = [json.loads(line) for line in events.read_text().splitlines()] if events.exists() else []
            report["routes_after"] = (router_dir / "routes.map").read_text()
            if enabled_at is not None:
                report["chat_after"] = chat(PROMPTS[1])
            # Keep watching the composer for two of the page's 12-second backend checks: a check that set out while
            # the primary was dead can land after the standby answered and grey the composer out again.
            settle = time.monotonic() + 30
            while time.monotonic() < settle:
                s = pg.evaluate(STATE_JS)
                key = (s["disabled"], s["noburritos"], s["placeholder"])
                if key != last:
                    report["timeline"].append({"at": clock(), "disabled": s["disabled"], "noburritos": s["noburritos"],
                                               "placeholder": s["placeholder"]})
                    last = key
                time.sleep(0.5)
            report["after"] = pg.evaluate(STATE_JS)
            report["navigations"] = list(navs)

            # An attendee who refreshes anyway.
            pg.reload(wait_until="domcontentloaded", timeout=60000)
            try:
                pg.wait_for_function("() => document.getElementById('inp') && !document.getElementById('inp').disabled",
                                     timeout=60000)
            except Exception as e:  # noqa: BLE001 - reported, and the judge fails on it
                report["reload_error"] = str(e)[:300]
            report["reloaded"] = pg.evaluate(STATE_JS)
            br.close()
    finally:
        watcher.stop.set()
        router.stop()
    report["caddy_log_tail"] = (router_dir / "caddy.log").read_text()[-1500:]
    return report


# --- the verdict ------------------------------------------------------------------------------------------------
# The longest the room should wait from the fault to a composer that works: three failed checks of up to 25 s each
# (the 15-second interval plus the self-check's 10-second timeout), the standby's own check with its chat (up to
# 60 s), the reload, and one of the page's 12-second backend checks, rounded up.
MAX_WAIT = 180
SETTLE = 15   # after the promotion, one 12-second page check and a little slack


def judge(r: dict) -> list[tuple[str, bool, str]]:
    """(check, passed, detail) for one drill's report. Pure, so verify/test_failover_drill.py holds it offline."""
    out: list[tuple[str, bool, str]] = []

    def add(name: str, ok: bool, detail: str = "") -> None:
        out.append((name, bool(ok), detail))

    p_up, s_up = f"{r['lbs'][r['primary']]}:443", f"{r['lbs'][r['standby']]}:443"
    before, after, again = r.get("before") or {}, r.get("after") or {}, r.get("reloaded") or {}
    c1, c2 = r.get("chat_before") or {}, r.get("chat_after") or {}
    applied = [e for e in r.get("events", []) if e.get("applied")]
    add(f"the watcher promoted {r['standby']} and the router took the table",
        len(applied) == 1 and applied[0].get("promoted") == r["standby"], json.dumps(r.get("events")))
    rows = b.table_rows(r.get("routes_after", ""))
    add(f"all {r.get('rows')} of attackme's rows now route to {r['standby']}'s console",
        rows and len(rows) == r.get("rows") and all(up == s_up for _, up in rows)
        and bool(applied) and applied[0].get("rows") == r.get("rows"), r.get("routes_after", "")[-400:])
    add(f"the first chat was answered by {r['primary']}",
        c1.get("status") == 200 and c1.get("upstream") == p_up and not c1.get("error_shown"), json.dumps(c1)[:400])
    add(f"after the promotion the same page chats again and {r['standby']} answers",
        c2.get("status") == 200 and c2.get("upstream") == s_up and not c2.get("error_shown")
        and bool((c2.get("shown") or "").strip()), json.dumps(c2)[:400])
    add("the page was never reloaded or navigated away",
        len(r.get("navigations", [])) == 1 and bool(before.get("marker")) and after.get("marker") == before.get("marker"),
        f"navigations {r.get('navigations')}, marker {after.get('marker')!r}")
    witch = before.get("witch") or ""
    add("the witch name in the page header is the same after the switch",
        witch.startswith("\U0001F9D9 You are ") and after.get("witch") == witch, f"{witch!r} -> {after.get('witch')!r}")
    add("the wib_witch cookie is the same after the switch",
        bool(before.get("cookie")) and after.get("cookie") == before.get("cookie"),
        f"{before.get('cookie')!r} -> {after.get('cookie')!r}")
    name = witch.replace("\U0001F9D9 You are ", "", 1)
    add("the chat after the switch carried the same witch name and session as the one before",
        bool(c1.get("session")) and c2.get("session") == c1.get("session") and c1.get("witch") == name
        and c2.get("witch") == name, f"before {c1.get('witch')!r}/{c1.get('session')!r}, "
                                     f"after {c2.get('witch')!r}/{c2.get('session')!r}, header {name!r}")
    promoted, enabled, fault = r.get("promoted_at"), r.get("enabled_at"), r.get("fault_at")
    add(f"the composer came back by itself within {SETTLE} s of the promotion",
        promoted is not None and enabled is not None and enabled - promoted <= SETTLE,
        f"promoted at {promoted}, composer on at {enabled}")
    late = [t for t in r.get("timeline", []) if enabled is not None and t.get("at", 0) > enabled and t.get("disabled")]
    add("the composer stayed on once it came back",
        enabled is not None and not late and after.get("disabled") is False, json.dumps(late)[:400])
    add("the no-burritos screen never showed",
        all(t.get("noburritos") in (None, "none") for t in r.get("timeline", [])), json.dumps(r.get("timeline"))[:400])
    add(f"the wait from the fault to a working composer is under {MAX_WAIT} s",
        fault is not None and enabled is not None and enabled - fault <= MAX_WAIT, f"fault {fault}, composer on {enabled}")
    add("a refresh afterwards keeps the witch name, the cookie and the session",
        not r.get("reload_error") and again.get("witch") == witch and again.get("cookie") == before.get("cookie")
        and again.get("session") == c1.get("session") and again.get("disabled") is False,
        r.get("reload_error") or f"{again.get('witch')!r} {again.get('cookie')!r} {again.get('session')!r}")
    return out


def summary(r: dict) -> list[str]:
    """What the room saw, in a few lines, for the decisions.md entry."""
    during = r.get("chat_during") or {}
    after = r.get("chat_after") or {}
    lines = [f"{r['primary']} -> {r['standby']}: fault at {r.get('fault_at')} s, promoted at {r.get('promoted_at')} s, "
             f"composer back at {r.get('enabled_at')} s"]
    lines += [f"  composer at {t['at']} s: {'off' if t['disabled'] else 'on'}, '{t['placeholder']}'"
              for t in r.get("timeline", []) if "disabled" in t]
    lines.append(f"  sent during the outage: HTTP {during.get('status')}, shown '{during.get('shown')}'")
    lines.append(f"  witch {(r.get('before') or {}).get('witch')!r} -> {(r.get('after') or {}).get('witch')!r}, "
                 f"after a refresh {(r.get('reloaded') or {}).get('witch')!r}")
    lines.append(f"  first reply after the switch: '{(after.get('shown') or '')[:200]}'")
    return lines


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--primary", required=True, help="kube-context of the cluster attackme starts on")
    ap.add_argument("--standby", required=True, help="kube-context of the cluster that takes attackme")
    ap.add_argument("--caddy", required=True, help="the caddy binary (verify/.tools/bin/caddy)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--page-from-repo", action="store_true",
                    help="serve this checkout's burritbot.html for / instead of the console's (a change not yet synced)")
    ap.add_argument("--judge", action="store_true", help="print the summary and judge()'s checks; exit 1 on any failure")
    a = ap.parse_args()
    if a.primary == a.standby:
        raise SystemExit("drill: --primary and --standby must be two clusters")
    with tempfile.TemporaryDirectory(prefix="failover-drill-") as d:
        report = run_drill(a.primary, a.standby, a.caddy, pathlib.Path(d), a.page_from_repo)
    text = json.dumps(report, indent=1)
    pathlib.Path(a.out).write_text(text)
    if not a.judge:
        print(text)
        return 0
    print("\n".join(summary(report)))
    verdict = judge(report)
    for name, ok, detail in verdict:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}" + ("" if ok else f"  -> {detail}"))
    return 0 if all(ok for _, ok, _ in verdict) else 1


if __name__ == "__main__":
    sys.exit(main())
