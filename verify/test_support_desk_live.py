# ABOUTME: Asks the one support desk both KubeCon clusters use for its page and HC-666 (200), the one deployments page for
# ABOUTME: its rows, the bot hosts for /support (404), and #916's body for the desk (#931, #946, #1160), with gh's token.
# SUITE: e2e (needs the network: the desk and bot hosts are asked over HTTPS, and gh with a token reads #916's body)
# E2E TIER: tools (no cluster, no AWS: run-e2e-tools.sh runs it with the pinned tools, #572)
#
# Why. #931's criterion "The support page the talk uses returns 200 on both clusters, and the run-of-show and #916 name
# that URL" was checked once by hand and recorded only in decisions.md (#946). This asks every desk host in
# verify/support_desk_hosts.py, the ones verify/test_support_desk_named.py holds the run-of-show's segment 4 to, for
# `/` and `/ticket/HC-666`: each must answer 200 with gitops/ai-layer/ticket_site.py's desk heading, and the ticket page
# must carry HC-666. Each bot host must answer 404 on `/support`, as segment 4 tells the presenters. Then it reads #916's
# body through verify/gh_comments.py and fails unless the body names each cluster's desk host as an https URL with
# HC-666's path, and its bot-host criterion lists no `/support`. So a desk that stops answering, a route that starts
# serving `/support` on a bot host, or an edit to #916 that drops the desk all fail here.
#
# Since #1145 both clusters' bots read one desk and deploy to one page (#1158), so support_desk_hosts.py lists the same
# desk for both and this asks each of its hosts once, for both clusters (#1160). It also asks the one deployments page
# for `/deployments.json`, which must answer 200 with a JSON list of rows, and `/presenter-ticket` on the desk, which
# must answer 403 from outside, since the presenters' range is filed only from inside the cluster (#1156).
#
# Reads only. Nothing on either cluster or on the router changes: the one POST, to `/presenter-ticket`, carries an empty
# body, which the desk itself would refuse with 400 if the public server ever let it through.
from __future__ import annotations

import json
import pathlib
import re
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import gh_comments  # noqa: E402
import support_desk_hosts as sd  # noqa: E402

ISSUE = "peopleforrester/Unleash_an_Agent_Watch_It_Burn#916"
OWNER_REPO, _, NUMBER = ISSUE.partition("#")
TICKET_SITE = sd.REPO / "gitops/ai-layer/ticket_site.py"
# The heading every desk page carries, as ticket_site.py's page shell writes it.
DESK_HEADING = "<h1>Hex &amp; Cauldron support desk</h1>"
TIMEOUT = 30
# A transport error (DNS, TLS, a reset) is tried again, up to this many times; a status the host answers never is.
ATTEMPTS = 3

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail and not ok else ""))
    if not ok:
        failures.append(name)


def get(url: str, data: bytes | None = None) -> tuple[int, str, str]:
    """(status, body, transport error). A status of 0 means no host answered; the error says why. With data, a POST."""
    req = urllib.request.Request(url, data=data, headers={"User-Agent": "watch-it-burn-verify/946",
                                                          "Cache-Control": "no-cache",
                                                          "Content-Type": "application/json"})
    last = ""
    for attempt in range(1, ATTEMPTS + 1):
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                return r.status, r.read().decode("utf-8", "replace"), ""
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode("utf-8", "replace"), ""
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
            last = f"attempt {attempt}: {e}"
            print(f"    ({url}: {last})")
            time.sleep(2 * attempt)
    return 0, "", last


def post(url: str) -> tuple[int, str, str]:
    """A POST of an empty presenter ticket, which the desk's public server must refuse before the desk sees it."""
    return get(url, data=b'{"body": ""}')


if DESK_HEADING not in TICKET_SITE.read_text(encoding="utf-8"):
    sys.exit(f"ANCHOR MISSING: {DESK_HEADING!r} is not in {TICKET_SITE}; the live checks read each desk page for it")

print("== the one desk answers 200 with its page and HC-666, for both clusters ==")
for cluster, host in sd.desk_hosts():
    status, body, err = get(f"https://{host}/")
    check(f"https://{host}/ ({cluster}) answers 200 with the desk's page",
          status == 200 and DESK_HEADING in body, err or f"status {status}" + ("" if DESK_HEADING in body else
                                                                              ", no desk heading"))
    status, body, err = get(f"https://{host}{sd.TICKET}")
    check(f"https://{host}{sd.TICKET} ({cluster}) answers 200 with HC-666 on the desk's page",
          status == 200 and "HC-666" in body and DESK_HEADING in body,
          err or f"status {status}" + ("" if "HC-666" in body else ", no HC-666"))

print("== the one deployments page answers with its rows, and the presenters' path is closed from outside ==")
status, body, err = get(f"https://{sd.DEPLOYMENTS}/deployments.json")
try:
    rows = json.loads(body) if status == 200 else None
except ValueError:
    rows = None
check(f"https://{sd.DEPLOYMENTS}/deployments.json (both clusters) answers 200 with a JSON list",
      isinstance(rows, list), err or f"status {status}" + ("" if status != 200 else ", not a JSON list"))
for _, host in sd.desk_hosts():
    status, _, err = post(f"https://{host}/presenter-ticket")
    check(f"POST https://{host}/presenter-ticket from outside answers 403 (#1156)", status == 403,
          err or f"status {status}")

print("== the bot hosts serve no /support (404), as segment 4 says ==")
for cluster, host in sd.BOT_HOSTS.items():
    status, _, err = get(f"https://{host}/support")
    check(f"https://{host}/support ({cluster}) answers 404", status == 404, err or f"status {status}")

print(f"== {ISSUE}'s body names the same desk ==")
got = gh_comments.read_body(OWNER_REPO, NUMBER)
gh_comments.check_read(got, ISSUE, check, what="body")
if got.ok:
    body = sd.flat(got.body)
    for host in dict.fromkeys(hosts[0] for hosts in sd.DESKS.values()):
        clusters = " and ".join(c for c, hosts in sd.DESKS.items() if hosts[0] == host)
        check(f"{ISSUE} names the desk of {clusters} as `https://{host}`", f"`https://{host}`" in body)
    check(f"{ISSUE} names HC-666's page at `{sd.TICKET}`", f"`{sd.TICKET}`" in body)
    check(f"{ISSUE} says the bot hosts serve no `/support`", "serve no `/support`" in body)
    # #916 first asked for 200 on `/support` of the bot hosts, a path never served. A clause that asks for 200 on a
    # list of paths runs to the end of its sentence; none may hold `/support`.
    asks = re.findall(r"200 on (?:`[^`]*`|[^.`])*", body)
    check(f"no criterion of {ISSUE} asks for 200 on `/support`", not [a for a in asks if "`/support`" in a],
          f"{[a for a in asks if '`/support`' in a]}")

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("The one desk answers 200 with HC-666 for both clusters, the one deployments page lists its rows, the bot hosts "
      "serve no /support, and #916 names the desk.")
