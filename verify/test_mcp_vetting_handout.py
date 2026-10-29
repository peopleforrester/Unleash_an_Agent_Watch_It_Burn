# ABOUTME: The MCP server vetting checklist handout (#649) is a verbatim copy of the Toronto keynote's checklist;
# ABOUTME: this fails when the copy no longer matches its stamped sha256, or the close stops linking it.
"""Keeps the C7 handout honest and reachable (#649).

docs/mcp-server-vetting-checklist.md copies `04-approval-gates-checklist/approval-gates.md` from
peopleforrester/mcp-for-a-city, which is generated from the keynote site's gate data. An edit made here would
drift from the talk it credits, so the copy carries the sha256 of the source file and this checks that
everything below the marker still hashes to it. Refresh the copy from the source and update the stamp; do not
hand-edit the body.

The close is where the room is pointed at the handout, so the run-of-show's close and the /kubecon page's
close both have to carry the public link to it.
"""
from __future__ import annotations

import hashlib
import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parent.parent
HANDOUT = REPO / "docs/mcp-server-vetting-checklist.md"
RUN_OF_SHOW = REPO / "facilitation/kubecon-na-2026-run-of-show.md"
KUBECON_PAGE = REPO / "gitops/ai-layer/web/kubecon.html"
MARKER = "<!-- verbatim copy below -->\n"
PUBLIC_URL = ("https://github.com/peopleforrester/Unleash_an_Agent_Watch_It_Burn/blob/main/"
              "docs/mcp-server-vetting-checklist.md")

failures: list[str] = []


def check(name: str, cond: bool) -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        failures.append(name)


doc = HANDOUT.read_text(encoding="utf-8")

print("== the copy is the source, unchanged ==")
check("the handout has exactly one verbatim-copy marker", doc.count(MARKER) == 1)
header, _, body = doc.partition(MARKER)
stamp = re.search(r"Source sha256: `([0-9a-f]{64})`", header)
check("the header stamps the source's sha256", stamp is not None)
check("the copy below the marker hashes to the stamped sha256 (refresh from the source, do not hand-edit)",
      stamp is not None and hashlib.sha256(body.encode("utf-8")).hexdigest() == stamp.group(1))
check("the header names the source repo, path and a full commit",
      re.search(r"`peopleforrester/mcp-for-a-city`, `04-approval-gates-checklist/approval-gates.md` at commit\s+"
                r"`[0-9a-f]{40}`", header) is not None)
check("the header carries the CC BY 4.0 licence and the author", "CC BY 4.0" in header and "Forrester" in header)
check("it is dated", re.search(r"Copied out: 20\d\d-[01]\d-[0-3]\d", header) is not None)

print("== it is the six-gate checklist ==")
gates = re.findall(r"^## Gate (\d): ", body, flags=re.M)
check("the copy carries gates 1 to 6, in order", gates == [str(n) for n in range(1, 7)])
check("every gate has something to verify", len(re.findall(r"^Verify:$", body, flags=re.M)) == 6)

print("== the close links it ==")
ros = RUN_OF_SHOW.read_text(encoding="utf-8")
close = ros.partition("- **The close (Michael, 2 min):**")[2].partition("\n- **Delivers:**")[0]
check("the run-of-show's close carries the handout's public link", PUBLIC_URL in close)
c7 = ros.partition("### Segment 4: C7")[2].partition("### Segment 5")[0]
check("C7's hand-out line names the handout file", "docs/mcp-server-vetting-checklist.md" in c7)
page = KUBECON_PAGE.read_text(encoding="utf-8")
page_close = page.partition("<b>The close (Michael")[2].partition("</div>")[0]
check("the /kubecon page's close links the handout", f'href="{PUBLIC_URL}"' in page_close)

if failures:
    print(f"\n{len(failures)} check(s) failed")
    raise SystemExit(1)
print("\nall checks passed")
