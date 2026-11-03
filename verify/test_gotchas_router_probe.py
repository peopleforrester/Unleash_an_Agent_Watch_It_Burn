# ABOUTME: Holds the gotchas doc's "router is healthy" probe to the roster URL fleet.sh router-check reads by
# ABOUTME: default (#827), so a retired host (provisioning.agenticburn.com) cannot come back into the triage steps.
"""The TLS-hop section of docs/GOTCHAS-FLEET-AND-DELIVERY.md tells an operator who sees every cluster host 502 to
curl the router first. Until #827 that probe hit provisioning.agenticburn.com, retired on 2026-10-29 (#651), which
answers the apex router's unknown-host 404 while the router is healthy. fleet.sh router-check reads the router's own
view, the roster URL in its WIB_ROUTER_ROSTER_URL default, so the doc's probe is that URL and this check fails when
the two differ. It also proves, on edited copies of both texts, that it catches a mismatch and a missing anchor."""
import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
DOC = REPO / "docs/GOTCHAS-FLEET-AND-DELIVERY.md"
FLEET = REPO / "infra/terraform/fleet/fleet.sh"
HEALTHY = "# 200 = router is healthy"
RETIRED = "provisioning.agenticburn.com"

failures = []


def check(name, ok):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    if not ok:
        failures.append(name)


def fleet_default(text):
    """The default in fleet.sh's `${WIB_ROUTER_ROSTER_URL:-<url>}`, or an error naming what is missing."""
    found = re.findall(r"\$\{WIB_ROUTER_ROSTER_URL:-([^}\s]+)\}", text)
    if len(found) != 1:
        raise ValueError(f"{FLEET.relative_to(REPO)}: expected one ${{WIB_ROUTER_ROSTER_URL:-<url>}}, "
                         f"found {len(found)}")
    return found[0]


def doc_probe(text):
    """The URL the doc's one "router is healthy" line curls, or an error naming the anchor and the file."""
    lines = [line for line in text.splitlines() if HEALTHY in line]
    if len(lines) != 1:
        raise ValueError(f"{DOC.relative_to(REPO)}: expected one line carrying {HEALTHY!r}, found {len(lines)}")
    line = lines[0]
    if not line.lstrip().startswith("curl "):
        raise ValueError(f"{DOC.relative_to(REPO)}: the {HEALTHY!r} line is not a curl: {line!r}")
    urls = re.findall(r"https?://\S+", line.split("#", 1)[0])
    if len(urls) != 1:
        raise ValueError(f"{DOC.relative_to(REPO)}: the {HEALTHY!r} line names {len(urls)} URLs: {line!r}")
    return urls[0]


def agree(doc_text, fleet_text):
    """None when the doc probes fleet.sh's default roster URL, else the reason it does not."""
    try:
        want, got = fleet_default(fleet_text), doc_probe(doc_text)
    except ValueError as e:
        return str(e)
    return None if got == want else f"the doc probes {got}, fleet.sh router-check reads {want}"


doc = DOC.read_text(encoding="utf-8")
fleet = FLEET.read_text(encoding="utf-8")

print("== the gotchas doc's router probe is the roster URL fleet.sh router-check reads (#827) ==")
reason = agree(doc, fleet)
check(f"the doc's {HEALTHY!r} probe equals fleet.sh's WIB_ROUTER_ROSTER_URL default"
      + (f" ({reason})" if reason else ""), reason is None)
check(f"the doc names no {RETIRED} URL", RETIRED not in doc)

print("== the check catches what it is for, on edited copies ==")
# Built from the real texts, so the edits use the values read above; each anchor is confirmed before it is replaced.
try:
    want = fleet_default(fleet)
    probe = doc_probe(doc)
except ValueError as e:
    print(f"  FAIL  cannot build the edited copies: {e}")
    failures.append("edited copies")
else:
    other = "https://start.example.invalid/roster.json"
    stale_doc = doc.replace(probe, f"https://{RETIRED}/", 1)
    check("a doc probing the retired host fails", agree(stale_doc, fleet) is not None)
    moved_fleet = fleet.replace(f"${{WIB_ROUTER_ROSTER_URL:-{want}}}", f"${{WIB_ROUTER_ROSTER_URL:-{other}}}", 1)
    check("the anchor ${WIB_ROUTER_ROSTER_URL:-<url>} is in fleet.sh as read", moved_fleet != fleet)
    check("fleet.sh moving its default without the doc fails", agree(doc, moved_fleet) is not None)
    check("both moving together passes", agree(doc.replace(probe, other, 1), moved_fleet) is None)
    unanchored = doc.replace(HEALTHY, "# 200 = ok", 1)
    check(f"a doc without the {HEALTHY!r} line fails, naming the anchor",
          HEALTHY in (agree(unanchored, fleet) or ""))
    no_default = fleet.replace("WIB_ROUTER_ROSTER_URL:-", "WIB_ROUTER_ROSTER_URL-", 1)
    check("a fleet.sh without the default fails, naming it", "WIB_ROUTER_ROSTER_URL" in (agree(doc, no_default) or ""))

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("The gotchas doc's router probe reads fleet.sh's roster URL.")
