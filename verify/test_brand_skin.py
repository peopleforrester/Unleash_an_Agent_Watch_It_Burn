# ABOUTME: Every attendee- or instructor-facing page carries the Datadog colour and names both sponsors
# ABOUTME: (Datadog and Neo4j, #769), and no page still carries the Packt palette the ported tabs arrived with.
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
WEB = REPO / "gitops" / "ai-layer" / "web"

# Two acceptable renderings of each brand colour. Dark surfaces (the projected side screen, the
# instructor brief) MUST use the lightened pair: measured against #000 the print values give 2.19:1 and
# 3.56:1, and AA needs 4.5:1, so insisting on the print values would mandate unreadable text.
DATADOG = ("632CA6", "B98CFF")      # print / lightened-for-dark
# The sponsor changed from Accenture to Neo4j (#769). Only the footer text changed; the pages still carry
# the old purple accent, so no specific sponsor-colour is asserted any more, just that both names appear.
PACKT = ("FA7040", "E85F2E", "FEF1EA")  # the orange palette the Packt tabs were ported with

failures = []


def check(name, cond):
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        failures.append(name)


pages = sorted(WEB.glob("*.html"))
# Eight since the retired chat-ui's index.html went (#240).
check("there are pages to check", len(pages) >= 8)

for p in pages:
    s = p.read_text()
    up = s.upper()
    # The sponsor line is contractual: these are sponsored surfaces and both sponsors are named on them.
    check(f"{p.name} names both sponsors (Datadog and Neo4j)",
          "Co-sponsored" in s and "Datadog" in s and "Neo4j" in s)
    # Accenture no longer co-sponsors (Michael, #766). Only the footer line is checked: burritbot.html's
    # comments and skins.js's selectable Accenture skin still name it on purpose.
    footer = [line for line in s.splitlines() if "Co-sponsored" in line]
    check(f"{p.name} footer does not name Accenture (#766)",
          bool(footer) and not any("Accenture" in line for line in footer))
    check(f"{p.name} carries a Datadog colour", any(c in up for c in DATADOG))
    # links.html and diagram.html were ported from the Packt workshop; their orange must not survive.
    check(f"{p.name} has no leftover Packt palette", not any(c in up for c in PACKT))

if failures:
    print(f"\nFAILED: {len(failures)} check(s)")
    sys.exit(1)
print(f"\nAll brand-skin checks passed ({len(pages)} pages).")
