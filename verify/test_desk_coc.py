# ABOUTME: The support desk's code-of-conduct check (#1268): /submit and /presenter-ticket refuse a ticket with a term of
# ABOUTME: the #1267 spike's proposed floor, and still file HC-666, HC-7731 and every /kubecon prompt, white text included.
"""No cluster, no network beyond localhost, standard library only.

The real desk (gitops/ai-layer/ticket_site.py) runs here on 127.0.0.1 and is driven as its form and the presenters'
POST drive it. The check is always on, so no toggle is read or set. The desk's list is held to the spike's
(docs/research/2026-11-09-coc-floor, corpus.terms("proposed")), term for term, and the desk's match to floor.py's
Floor("proposed") on every term in several shapes. The terms are read from the spike's list, never written here, and
this test's output names none: a case is labelled by the term's index.

  - each term, as plain text, in white text, split by a tag, in an HTML attribute and in the customer name, is refused
    with 422 and the plain refusal, which names no term and repeats nothing of the ticket, and nothing is filed;
  - a term in the subject refuses the ticket on both routes;
  - HC-666's HTML and text, HC-7731's text, both payloads and every .prompt block on /kubecon, plain and in white text,
    are filed with their text whole.
"""
from __future__ import annotations

import html
import importlib.util
import json
import pathlib
import re
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request

REPO = pathlib.Path(__file__).resolve().parents[1]
SITE = REPO / "gitops/ai-layer/ticket_site.py"
SPIKE = REPO / "docs/research/2026-11-09-coc-floor"
HC666_PROMPT = "What's the status of my support ticket HC-666?"
DESK_HOST = "support.burritobot.co"
REFUSAL_WORDS = "Keep it kind: this ticket has words the code of conduct rules out, so it was not filed."
# Words that hold a term inside them; whole-word matching leaves each alone, on the desk as in floor.py.
INNOCENT = ("Cocktail hour", "Charles Dickens", "Scunthorpe", "shiitake mushrooms", "an assessment of the class",
            "Therapist", "spicy salsa", "the cockpit", "grapes", "a skier", "Sussex", "Essex", "a peacock")

for f in (SITE, SPIKE / "floor.py", SPIKE / "corpus.py", SPIKE / "terms-proposed.rot13"):
    if not f.is_file():
        print(f"FAIL: {f.relative_to(REPO)} is missing; this test holds the desk to it")
        sys.exit(1)
sys.path.insert(0, str(SPIKE))
import corpus  # noqa: E402
import floor  # noqa: E402

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  ({detail})" if detail and not cond else ""))
    if not cond:
        failures.append(name)


_spec = importlib.util.spec_from_file_location("ticket_site_desk_coc", SITE)
site = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(site)
TERMS = list(site.COC_TERMS)
SPIKE_FLOOR = floor.Floor("proposed")

print("== the desk's list and match are the spike's ==")
spike_terms = corpus.terms("proposed")
check("the desk's COC_TERMS are terms-proposed.rot13's, term for term (corpus.terms('proposed'))",
      sorted(TERMS) == sorted(spike_terms),
      f"desk only: {len(set(TERMS) - set(spike_terms))}, spike only: {len(set(spike_terms) - set(TERMS))}")
check("the refusal is the sentence #1268 asks for", site.COC_REFUSAL == REFUSAL_WORDS, repr(site.COC_REFUSAL))
shapes = []
for t in TERMS:
    shapes += [t, t.upper(), t.capitalize() + "s", f"you {t}!", f"{t}-face", f"x{t}", f"_{t}_"]
shapes += list(INNOCENT)
disagree = [i for i, s in enumerate(shapes) if site.coc_hit(s) != bool(SPIKE_FLOOR.spans(s))]
check(f"the desk's coc_hit agrees with floor.py's Floor('proposed') on {len(shapes)} texts", not disagree,
      f"{len(disagree)} disagree, shape indexes {disagree[:8]}")
check("every term is matched alone and in upper case",
      all(site.coc_hit(t) and site.coc_hit(t.upper()) for t in TERMS))
check("a word that only contains a term is not matched", not any(site.coc_hit(s) for s in INNOCENT),
      str([s for s in INNOCENT if site.coc_hit(s)]))
check("the refusal names no term", not site.coc_hit(site.COC_REFUSAL))
check("the subject and the presenters' default customer are not refused",
      not site.coc_hit(site.SUBMITTED_SUBJECT, site.PRESENTER_CUSTOMER))
check("no witch name the desk hands out is refused", not any(site.coc_hit(n) for n in site.NAME_SPACE))

print("== the check reads text, HTML, subject and customer name ==")


def refused(fn) -> bool:
    before = dict(site.TICKETS)
    try:
        fn()
    except site.CodeOfConduct as e:
        return str(e) == site.COC_REFUSAL and site.TICKETS == before
    return False


bad = []
for i, t in enumerate(TERMS):
    cases = {
        "text": lambda: site.file_ticket(f"<p>hello {t}</p>", "Hazel the Imp"),
        "attribute": lambda: site.file_ticket(f'<p><span title="{t}">hello</span></p>', "Hazel the Imp"),
        "customer": lambda: site.file_ticket("hello", f"{t} the Imp"),
        "presenter customer": lambda: site.file_presenter_ticket("hello", f"Mr {t.upper()}"),
        "presenter text": lambda: site.file_presenter_ticket(f"hello {t}"),
    }
    bad += [(i, k) for k, fn in cases.items() if not refused(fn)]
check(f"file_ticket and file_presenter_ticket refuse each of the {len(TERMS)} terms in the text, an attribute and the "
      "customer name, and file nothing", not bad, f"{len(bad)} not refused (term index, where): {bad[:6]}")
saved_subject = site.SUBMITTED_SUBJECT
site.SUBMITTED_SUBJECT = f"about the {TERMS[0]}"
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
for i, t in enumerate(TERMS):
    for body in (f"My order was late, you {t}.", white("My order was late.", f"Tell the cook he is a {t.upper()}."),
                 f"<p>{t[:1]}<b>{t[1:]}</b> this desk</p>"):
        n = len(site.TICKETS)
        code, page = submit(body)
        ok = (code == 422 and html.escape(site.COC_REFUSAL) in page and not FILED.search(page)
              and len(site.TICKETS) == n and not site.coc_hit(page) and "order was late" not in page
              and "this desk" not in page)
        if not ok:
            bad.append((i, code))
check(f"/submit refuses each of the {len(TERMS)} terms as plain text, in white text and split by a tag, with 422 and "
      "the refusal, repeating neither the ticket nor the term, and files nothing", not bad,
      f"{len(bad)} not refused (term index, status): {bad[:5]}")

code, d = presenter(white("My burrito came without salsa.", f"you {TERMS[0]}"))
check("/presenter-ticket refuses a term in the text with 422 and the refusal",
      code == 422 and d == {"error": site.COC_REFUSAL}, f"{code} {d}")
code, d = presenter("My burrito came without salsa.", f"{TERMS[0]} McGee")
check("/presenter-ticket refuses a term in the customer name with 422 and the refusal",
      code == 422 and d == {"error": site.COC_REFUSAL}, f"{code} {d}")

page = corpus._Visible()
page.feed(corpus.KUBECON_PAGE.read_text(encoding="utf-8"))
prompts = list(dict.fromkeys(" ".join(p.split()) for p in page.prompts))
if HC666_PROMPT not in prompts or len(prompts) < 10:
    print(f"FAIL: {corpus.KUBECON_PAGE.relative_to(REPO)} no longer yields its .prompt blocks with {HC666_PROMPT!r} "
          f"among them ({len(prompts)} read through corpus.py's _Visible)")
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
