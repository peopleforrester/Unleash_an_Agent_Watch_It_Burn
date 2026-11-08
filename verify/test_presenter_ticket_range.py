# ABOUTME: Holds #1156: the room's tickets (POST /submit) never take a number in the presenters' range HC-900..HC-999,
# ABOUTME: and the in-cluster-only POST /presenter-ticket issues numbers in that range, refused by the console outside.
"""The real ticket site runs here on localhost (gitops/ai-layer/ticket_site.py), driven over HTTP. No cluster, no model.

Per CLAUDE.md "Tests own their inputs", the room's draw is enumerated, not sampled: every value secrets.randbelow can
return to _room_draw is tried, and then every number from 0 to 10999 is fed to file_ticket as the draw, so the guard
holds for any draw, today's or a changed one. The presenter path draws nothing: it takes the lowest free number.
"""
from __future__ import annotations

import importlib.util
import json
import pathlib
import re
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request

import yaml

REPO = pathlib.Path(__file__).resolve().parent.parent
AI = REPO / "gitops/ai-layer"
SITE_SRC = (AI / "ticket_site.py").read_text()
CONF = (AI / "console.conf").read_text()
RES = [d for d in yaml.safe_load_all((AI / "resources.yaml").read_text()) if isinstance(d, dict)]
failures: list[str] = []

# The console.conf headings this test cuts the desk's and the deployments page's server blocks on.
DESK_ANCHOR = "# Challenge 6's ticket desk (2026-10-28 call, #685)"
PAGE_ANCHOR = "# Challenge 2's deployments page (#773)"
for anchor in (DESK_ANCHOR, PAGE_ANCHOR):
    if anchor not in CONF:
        print(f"FAILED: the anchor {anchor!r} is not in gitops/ai-layer/console.conf; reword this test with it")
        sys.exit(1)


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  ({detail})" if detail and not cond else ""))
    if not cond:
        failures.append(name)


spec = importlib.util.spec_from_file_location("ticket_site_presenter_range", AI / "ticket_site.py")
site = importlib.util.module_from_spec(spec)
spec.loader.exec_module(site)
site.Handler.log_message = lambda *a: None
server = site.Server(("127.0.0.1", 0), site.Handler)
threading.Thread(target=server.serve_forever, daemon=True).start()
DESK = f"http://127.0.0.1:{server.server_address[1]}"
PRESENTER = set(range(900, 1000))
FIXED = set(site.FIXED_TICKETS)


def request(method: str, path: str, data: bytes | None = None, headers: dict | None = None) -> tuple[int, str]:
    req = urllib.request.Request(DESK + path, data=data, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def presenter_post(body, host: str = "") -> tuple[int, dict]:
    data = body if isinstance(body, bytes) else json.dumps(body).encode()
    headers = {"Content-Type": "application/json"}
    if host:
        headers["Host"] = host
    code, text = request("POST", "/presenter-ticket", data, headers)
    try:
        return code, json.loads(text)
    except ValueError:
        return code, {"raw": text}


def submit(body: str) -> tuple[int, str]:
    return request("POST", "/submit", urllib.parse.urlencode({"body": body}).encode(),
                   {"User-Agent": "range-test", "X-Forwarded-For": "203.0.113.9"})


def number(tid: str) -> int:
    return int(tid.removeprefix("HC-"))


print("== the two ranges ==")
check("the presenters' range is HC-900 to HC-999", set(site.PRESENTER_NUMBERS) == PRESENTER, str(site.PRESENTER_NUMBERS))
check("the room's range is HC-1000 to HC-9999", site.ROOM_NUMBERS == range(1000, 10000), str(site.ROOM_NUMBERS))
check("the ranges do not overlap", not PRESENTER & set(site.ROOM_NUMBERS))
check("no fixed ticket sits in the presenters' range", not any(site.is_presenter_ticket(t) for t in FIXED), str(FIXED))
check("is_presenter_ticket reads HC-900 and HC-999 as the presenters', HC-899, HC-1000 and HC-666 not",
      site.is_presenter_ticket("HC-900") and site.is_presenter_ticket("HC-999")
      and not any(site.is_presenter_ticket(t) for t in ("HC-899", "HC-1000", "HC-666", "HC-9xx", "900")))

print("== every value the room's draw can return ==")


class Every:
    """secrets stand-in: randbelow(n) records n and returns the value the test sets."""

    def __init__(self) -> None:
        self.bounds: list[int] = []
        self.value = 0

    def randbelow(self, n: int) -> int:
        self.bounds.append(n)
        return self.value


real_secrets = site.secrets
stub = Every()
site.secrets = stub
site._room_draw()
bound = stub.bounds[-1] if stub.bounds else 0
drawn = set()
for v in range(bound):
    stub.value = v
    drawn.add(site._room_draw())
site.secrets = real_secrets
check("the draw asks secrets.randbelow for exactly the room's 9000 numbers", bound == 9000, str(stub.bounds[:3]))
check("across all of them it returns every room number and nothing else", drawn == set(range(1000, 10000)),
      f"{len(drawn)} numbers, min {min(drawn, default=None)}, max {max(drawn, default=None)}")
check("so no value of it is a presenter number", not drawn & PRESENTER)

print("== file_ticket refuses a presenter number whatever the draw returns ==")
real_draw = site._room_draw
FALLBACK = 7777
bad: list[str] = []
for v in range(0, 11000):
    seq = iter((v, FALLBACK))
    site._room_draw = lambda: next(seq)
    t = site.file_ticket("<p>a room ticket</p>", "Edgar the Kelpie")
    n = number(t["id"])
    want = v if v in site.ROOM_NUMBERS and f"HC-{v}" not in FIXED else FALLBACK
    if n != want or n in PRESENTER:
        bad.append(f"draw {v} -> {t['id']}")
    site.clear_filed_tickets()
check("each of the 11000 draws 0..10999 files a room number, and every presenter or out-of-range draw is drawn again",
      not bad, "; ".join(bad[:5]))

seq = iter(list(range(900, 1000)) + [4321])
site._room_draw = lambda: next(seq)
code, page = submit("<p>my card keeps failing</p>")
site._room_draw = real_draw
check("POST /submit fed all 100 presenter numbers first files HC-4321, the first room number", code == 200
      and "Your ticket is HC-4321" in page, f"{code} {page[:300]}")
code, page = submit("<p>an ordinary draw</p>")
got = re.search(r"Your ticket is (HC-\d+)", page)
check("an ordinary POST /submit gets a four-digit room number", code == 200 and got is not None
      and number(got.group(1)) in site.ROOM_NUMBERS, f"{code} {page[:300]}")
site.clear_filed_tickets()

print("== the presenters' filing path ==")
code, t = presenter_post({"body": '<p>My order is late.</p><p><span style="color:#ffffff">hidden line</span></p>',
                          "customer": "Whitney at the front"})
check("POST /presenter-ticket answers 201 with HC-900, the first presenter number", code == 201
      and t.get("id") == "HC-900", f"{code} {t}")
check("and keeps the customer the presenter gave", t.get("customer") == "Whitney at the front", str(t))
code2, t2 = presenter_post({"body": "a second demo ticket"})
check("the next one is HC-901, with the walk-in customer when none is given", code2 == 201 and t2.get("id") == "HC-901"
      and t2.get("customer") == site.PRESENTER_CUSTOMER, f"{code2} {t2}")
code, text = request("GET", "/ticket?id=HC-900")
read = json.loads(text) if code == 200 else {}
check("the bot's read path, GET /ticket?id=HC-900, returns it with the white-text line in its text",
      read.get("id") == "HC-900" and "hidden line" in read.get("body", ""), f"{code} {text[:200]}")
code, text = request("GET", "/HC-900")
check("its one-ticket page keeps the white-text line white, as a room ticket's does", code == 200
      and '<span style="color:#ffffff">hidden line</span>' in text, text[:400])
check("a presenter ticket has no owner, so it shows on no visitor's /me page",
      "owner" not in site.TICKETS["HC-900"] and "HC-900" not in site.me_page("Edgar the Kelpie"))

for body, why in ((b"not json", "a body that is not JSON"), ({"customer": "x"}, "no body"),
                  ({"body": 5}, "a body that is not text"), ({"body": "x", "customer": ["a"]}, "a customer that is not text"),
                  ({"body": "<p>  </p>"}, "a body with no text")):
    code, _ = presenter_post(body)
    check(f"{why} is a 400", code == 400, str(code))
code, _ = presenter_post({"body": "x" * (site.MAX_BODY + 1)})
check("a body past MAX_BODY is a 413", code == 413, str(code))
code, _ = presenter_post({"body": "from outside"}, host="deployments.burritobot.co")
check("the deployments host answers POST /presenter-ticket with a 404", code == 404, str(code))
check("none of those filed a ticket", sorted(k for k in site.TICKETS if site.is_presenter_ticket(k)) == ["HC-900", "HC-901"],
      str(sorted(site.TICKETS)))

site.TICKETS.pop("HC-900")
code, t = presenter_post({"body": "refill"})
check("a freed number is reused: the lowest free one, HC-900, again", code == 201 and t.get("id") == "HC-900", str(t))
for _ in range(98):
    presenter_post({"body": "filler"})
check("all 100 presenter numbers can be filed", all(f"HC-{n}" in site.TICKETS for n in PRESENTER))
code, t = presenter_post({"body": "one too many"})
check("the 101st is a 409 that names the range", code == 409 and "HC-900 to HC-999" in t.get("error", ""), f"{code} {t}")
check("and no room ticket number was ever taken by the presenter path",
      all(site.is_presenter_ticket(k) for k in site.TICKETS if k not in FIXED))

print("== a busy room cannot evict the presenters' tickets ==")
site.clear_filed_tickets()
presenter_post({"body": "the demo ticket"})
real_max = site.MAX_TICKETS
site.MAX_TICKETS = len(FIXED) + 20
for _ in range(60):
    site.file_ticket("<p>room</p>", "Mabel the Imp")
site.MAX_TICKETS = real_max
check("past MAX_TICKETS room tickets are evicted and HC-900 stays", "HC-900" in site.TICKETS
      and len(site.TICKETS) < len(FIXED) + 60, str(len(site.TICKETS)))
check("every fixed ticket stays too", FIXED <= set(site.TICKETS))

print("== the desk reset clears both kinds and keeps the fixed tickets ==")
site.file_ticket("<p>room</p>", "Mabel the Imp")
removed = site.clear_filed_tickets()
check("clear_filed_tickets removes every room and presenter ticket", set(site.TICKETS) == FIXED and removed > 1,
      f"{removed} {sorted(site.TICKETS)}")
code, t = presenter_post({"body": "after the reset"})
check("after it the presenters' numbering starts again at HC-900", code == 201 and t.get("id") == "HC-900", str(t))
site.clear_filed_tickets()

print("== the console refuses the path from outside ==")
desk_block = CONF[CONF.find(DESK_ANCHOR):]
desk_block = desk_block[:desk_block.find(PAGE_ANCHOR)]
check("the support desk's server refuses /presenter-ticket, as it does /landed and /cluster-read",
      re.search(r"location = /presenter-ticket \{\s*deny all;", desk_block) is not None
      and re.search(r"location = /landed \{\s*deny all;", desk_block) is not None, desk_block[-900:])
# Every route the console has to the desk: each must be the desk's server (which denies the path) or a GET-only one.
routes = []
for m in re.finditer(r"set \$\w+ http://fake-ticket\.agent\.svc\.cluster\.local:8080;", CONF):
    loc = CONF.rfind("location", 0, m.start())
    routes.append((m.start(), CONF[loc:CONF.find("{", loc)].strip()))
desk_start, desk_end = CONF.find(DESK_ANCHOR), CONF.find(PAGE_ANCHOR)
others = [r for pos, r in routes if not desk_start < pos < desk_end]
check("the console's only other routes to the desk are /deployments.json and the deployments page's three paths",
      sorted(others) == sorted(["location = /deployments.json", r"location ~ ^/(|mine|deployments\.json)$"]),
      str(routes))
check("neither of them is a prefix route that /presenter-ticket could fall into",
      all("presenter" not in r and not r.endswith("/") for r in others), str(others))

print("== no Secret, and not the presenter terminal login ==")
check("ticket_site.py names no TTYD_CREDENTIAL and reads no Secret file", "TTYD_CREDENTIAL" not in SITE_SRC
      and "/var/run/secrets" not in SITE_SRC and "/etc/secret" not in SITE_SRC)
check("the presenter path takes no token header", "X-Admin-Token" not in SITE_SRC and "Authorization" not in SITE_SRC)
dep = [d for d in RES if d.get("kind") == "Deployment" and d["metadata"]["name"] == "fake-ticket"]
pod = dep[0]["spec"]["template"]["spec"] if len(dep) == 1 else {}
pod_txt = json.dumps(pod)
check("the fake-ticket Deployment mounts no Secret and takes no env from one", len(dep) == 1
      and "secret" not in pod_txt.lower() and "terminal-auth" not in pod_txt, pod_txt[:400])
check("and still holds no ServiceAccount token", pod.get("automountServiceAccountToken") is False)

server.shutdown()
print()
if failures:
    print(f"FAILED: {len(failures)} check(s): " + "; ".join(failures))
    sys.exit(1)
print("ALL PRESENTER TICKET RANGE CHECKS PASSED")
