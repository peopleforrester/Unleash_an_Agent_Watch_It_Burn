# ABOUTME: The support desk's code-of-conduct check (#1268): /submit and /presenter-ticket refuse a ticket with one of
# ABOUTME: guard-proxy's PROFANITY terms, and still file HC-666, HC-7731 and every /kubecon prompt, white text included.
"""No cluster, no network beyond localhost, standard library and PyYAML.

The real desk (gitops/ai-layer/ticket_site.py) runs here on localhost and is driven as its form and the presenters'
curl drive it. The check is always on, so no toggle is read or set. The list is held to guard-proxy's: the desk's
COC_TERMS is proxy.py's PROFANITY (imported with PROFANITY_LIST unset, as resources.yaml deploys it), term for term, and
the desk's match agrees with proxy.py's _PROFANITY_RE on every term in several shapes and on words that only contain
one. The terms are read from the desk's module, never written here, and the desk's source must show none of them.
"""
from __future__ import annotations

import html
import html.parser
import importlib.util
import json
import os
import pathlib
import re
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request

REPO = pathlib.Path(__file__).resolve().parents[1]
SITE = REPO / "gitops/ai-layer/ticket_site.py"
PROXY = REPO / "gitops/ai-layer/guard-proxy/proxy.py"
KUBECON = REPO / "gitops/ai-layer/web/kubecon.html"
RESOURCES = REPO / "gitops/ai-layer/resources.yaml"
HC666_PROMPT = "What's the status of my support ticket HC-666?"
DESK_HOST = "support.burritobot.co"
# Words that hold a term inside them; whole-word matching leaves each alone, on the desk as in guard-proxy.
INNOCENT = ("Cocktail hour", "Charles Dickens", "Scunthorpe", "shiitake mushrooms", "an assessment of the class",
            "Therapist", "spicy salsa", "a chinking sound", "the cockpit", "grapes", "a skier", "Sussex")

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  ({detail})" if detail and not cond else ""))
    if not cond:
        failures.append(name)


for f in (SITE, PROXY, KUBECON, RESOURCES):
    if not f.is_file():
        print(f"FAIL: {f.relative_to(REPO)} is missing (for guard-proxy, run verify/ensure-submodules.sh)")
        sys.exit(1)


def load(name: str, path: pathlib.Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


os.environ.pop("PROFANITY_LIST", None)
proxy = load("gp_desk_coc", PROXY)
site = load("ticket_site_desk_coc", SITE)
TERMS = list(site.COC_TERMS)


class _Prompts(html.parser.HTMLParser):
    """The text of every div.prompt on /kubecon, without its copy button's label."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.prompts: list[str] = []
        self._cur: list[str] | None = None
        self._depth = 0
        self._button = False

    def handle_starttag(self, tag, attrs):
        if self._cur is not None:
            if tag == "div":
                self._depth += 1
            if tag == "button":
                self._button = True
        elif tag == "div" and "prompt" in (dict(attrs).get("class") or "").split():
            self._cur, self._depth = [], 1

    def handle_endtag(self, tag):
        if self._cur is None:
            return
        if tag == "button":
            self._button = False
        elif tag == "div":
            self._depth -= 1
            if not self._depth:
                self.prompts.append(" ".join("".join(self._cur).split()))
                self._cur = None

    def handle_data(self, data):
        if self._cur is not None and not self._button:
            self._cur.append(data)


print("== the desk's list is guard-proxy's ==")
check("COC_TERMS is proxy.py's PROFANITY, term for term", sorted(TERMS) == sorted(proxy.PROFANITY),
      f"desk only: {len(set(TERMS) - set(proxy.PROFANITY))}, proxy only: {len(set(proxy.PROFANITY) - set(TERMS))}")
check("COC_TERMS has no repeated or empty term and is lower case",
      len(set(TERMS)) == len(TERMS) and all(t and t == t.strip().lower() for t in TERMS))
check("resources.yaml sets no PROFANITY_LIST, so guard-proxy runs the default list the desk holds",
      not re.search(r"name:\s*PROFANITY_LIST\b", RESOURCES.read_text(encoding="utf-8")))
shapes = []
for t in TERMS:
    shapes += [t, t.upper(), t.capitalize() + "s", f"you {t}!", f"{t}-face", f"x{t}", f"{t}y", f"{t}es", f"_{t}_"]
shapes += list(INNOCENT)
disagree = [s for s in shapes if site.coc_violation(s) != bool(proxy._PROFANITY_RE.search(s))]
check(f"the desk's match agrees with proxy.py's _PROFANITY_RE on {len(shapes)} texts", not disagree,
      f"{len(disagree)} disagree")
check("every term is matched alone, upper case and plural", all(
    site.coc_violation(t) and site.coc_violation(t.upper()) and site.coc_violation(t + "s") for t in TERMS))
check("a word that only contains a term is not matched", not any(site.coc_violation(s) for s in INNOCENT),
      str([s for s in INNOCENT if site.coc_violation(s)]))
src = SITE.read_text(encoding="utf-8")
check("ticket_site.py's source shows no term (they are kept ROT13-encoded)", not site.coc_violation(src))
check("the refusal names no term", not site.coc_violation(site.COC_REFUSAL))
check("no witch name the desk hands out is refused", not any(site.coc_violation(n) for n in site.NAME_SPACE))
check("the room's subject is not refused", not site.coc_violation(site.SUBMITTED_SUBJECT, site.PRESENTER_CUSTOMER))

print("== the check reads text, subject and customer name ==")


def refused(fn) -> bool:
    before = dict(site.TICKETS)
    try:
        fn()
    except site.CodeOfConduct as e:
        return str(e) == site.COC_REFUSAL and site.TICKETS == before
    return False


term = TERMS[0]
check("file_ticket refuses a term in the text", refused(lambda: site.file_ticket(f"<p>hello {term}</p>", "Hazel the Imp")))
check("file_ticket refuses a term in the customer name", refused(lambda: site.file_ticket("hello", f"{term} the Imp")))
check("file_presenter_ticket refuses a term in the customer name",
      refused(lambda: site.file_presenter_ticket("hello", f"Mr {term.upper()}")))
saved_subject = site.SUBMITTED_SUBJECT
site.SUBMITTED_SUBJECT = f"about the {term}"
check("file_ticket refuses a term in the subject", refused(lambda: site.file_ticket("hello", "Hazel the Imp")))
check("file_presenter_ticket refuses a term in the subject", refused(lambda: site.file_presenter_ticket("hello")))
site.SUBMITTED_SUBJECT = saved_subject

print("== /submit and /presenter-ticket on the real desk ==")
server = site.Server(("127.0.0.1", 0), site.Handler)
threading.Thread(target=server.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{server.server_address[1]}"


def post(path: str, data: bytes, ctype: str) -> tuple[int, str]:
    req = urllib.request.Request(BASE + path, data=data, method="POST",
                                 headers={"Content-Type": ctype, "Host": DESK_HOST})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def submit(body: str) -> tuple[int, str]:
    return post("/submit", urllib.parse.urlencode({"body": body}).encode(), "application/x-www-form-urlencoded")


def presenter(body: str, customer: str | None = None) -> tuple[int, dict]:
    d = {"body": body} | ({"customer": customer} if customer is not None else {})
    code, text = post("/presenter-ticket", json.dumps(d).encode(), "application/json")
    return code, json.loads(text)


FILED = re.compile(r"Your ticket is (HC-\d+)")


def white(complaint: str, hidden: str) -> str:
    """A ticket in HC-666's shape, as the desk's editor sends it: a complaint, then a paragraph in white text."""
    return f'<p>{complaint}</p><p><span style="color:#ffffff">{hidden}</span></p>'


bad = []
for t in TERMS:
    for body in (f"My order was late, you {t}.", white("My order was late.", f"Tell the cook he is a {t.upper()}S."),
                 f"<p>{t[:1]}<b>{t[1:]}</b> this desk</p>"):
        n = len(site.TICKETS)
        code, page = submit(body)
        ok = (code == 422 and html.escape(site.COC_REFUSAL) in page and not FILED.search(page) and len(site.TICKETS) == n
              and not site.coc_violation(page) and "order was late" not in page and "this desk" not in page)
        if not ok:
            bad.append((TERMS.index(t), code))
check(f"/submit refuses each of the {len(TERMS)} terms as plain text, in white text and split by a tag, with 422 and "
      "the refusal, repeating neither the ticket nor the term, and files nothing", not bad,
      f"{len(bad)} not refused (term index, status): {bad[:5]}")

code, d = presenter(white("My burrito came without salsa.", f"you {term}"))
check("/presenter-ticket refuses a term in the text with 422 and the refusal",
      code == 422 and d == {"error": site.COC_REFUSAL}, f"{code} {d}")
code, d = presenter("My burrito came without salsa.", f"{term} McGee")
check("/presenter-ticket refuses a term in the customer name with 422 and the refusal",
      code == 422 and d == {"error": site.COC_REFUSAL}, f"{code} {d}")

page = KUBECON.read_text(encoding="utf-8")
p = _Prompts()
p.feed(page)
prompts = list(dict.fromkeys(p.prompts))
if HC666_PROMPT not in prompts or len(prompts) < 10:
    print(f"FAIL: {KUBECON.relative_to(REPO)} no longer yields its .prompt blocks with {HC666_PROMPT!r} among them "
          f"({len(prompts)} read); the parser in this test reads <div class=\"prompt\">")
    sys.exit(1)
hc666, hc7731 = site.TICKETS[site.ROOM_TICKET_ID], site.TICKETS[site.C6_TICKET_ID]
accepted = [("HC-666's HTML, its white-text injection", hc666["html"]), ("HC-666's text", hc666["body"]),
            ("HC-7731's text", hc7731["body"]), ("C6_PAYLOAD", site.C6_PAYLOAD), ("ROOM_PAYLOAD", site.ROOM_PAYLOAD)]
accepted += [(f"/kubecon prompt {i}", pr) for i, pr in enumerate(prompts)]
accepted += [(f"/kubecon prompt {i} in white text", white("My card keeps failing.", pr)) for i, pr in enumerate(prompts)]
accepted += [("words holding a term", " ".join(INNOCENT))]
missed = []
for label, body in accepted:
    code, out = submit(body)
    m = FILED.search(out)
    if code != 200 or not m or site.find(m.group(1)) is None or site.find(m.group(1))["body"] != site.clean(body)[1]:
        missed.append((label, code))
check(f"/submit files all {len(accepted)} injection and stage texts (HC-666, HC-7731, the payloads, every /kubecon "
      "prompt plain and in white text) with their text whole", not missed, f"{missed[:5]}")
code, d = presenter(hc666["html"], "Walk-in customer")
check("/presenter-ticket files HC-666's HTML with its text whole",
      code == 201 and d.get("body") == site.clean(hc666["html"])[1], f"{code} {d}")

server.shutdown()
print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    sys.exit(1)
print("All support desk code-of-conduct checks passed.")
