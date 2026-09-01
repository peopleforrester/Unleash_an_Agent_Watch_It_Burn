# ABOUTME: Every attendee- or instructor-facing page carries the Datadog/Accenture skin and the sponsor
# ABOUTME: line, and no page still carries the Packt palette the ported tabs arrived with.
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
WEB = REPO / "gitops" / "ai-layer" / "web"

# Two acceptable renderings of each brand colour. Dark surfaces (the projected side screen, the
# instructor brief) MUST use the lightened pair: measured against #000 the print values give 2.19:1 and
# 3.56:1, and AA needs 4.5:1, so insisting on the print values would mandate unreadable text.
DATADOG = ("632CA6", "B98CFF")      # print / lightened-for-dark
ACCENTURE = ("A100FF", "D08BFF")
PACKT = ("FA7040", "E85F2E", "FEF1EA")  # the orange palette the Packt tabs were ported with

failures = []


def check(name, cond):
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        failures.append(name)


pages = sorted(WEB.glob("*.html"))
check("there are pages to check", len(pages) >= 9)

for p in pages:
    s = p.read_text()
    up = s.upper()
    # The sponsor line is contractual: these are sponsored surfaces and the sponsors are named on them.
    check(f"{p.name} names both sponsors", "Co-sponsored" in s)
    check(f"{p.name} carries a Datadog colour", any(c in up for c in DATADOG))
    check(f"{p.name} carries an Accenture colour", any(c in up for c in ACCENTURE))
    # links.html and diagram.html were ported from the Packt workshop; their orange must not survive.
    check(f"{p.name} has no leftover Packt palette", not any(c in up for c in PACKT))

if failures:
    print(f"\nFAILED: {len(failures)} check(s)")
    sys.exit(1)
print(f"\nAll brand-skin checks passed ({len(pages)} pages).")
