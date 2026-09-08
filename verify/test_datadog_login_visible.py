# ABOUTME: The lab must never promise "the credentials below" when there are none, and the roster clusters
# ABOUTME: must get a lab link that carries the Datadog login they never receive from provisioning.
"""Pins the Datadog login path for clusters outside the pool (#339).

The credential box hides itself when the URL carries no `ddu`/`ddp`, which is right: a hand-typed `/lab`
should degrade rather than render empty copy boxes. The sentence above it did not degrade with it, so on
every admin cluster the page said "log in with the credentials below" and showed nothing below.

That is not an edge case. Admin clusters are deliberately outside the provisioning pool, so nothing ever
builds a params-carrying link for them, and they are exactly where a presenter stands when they need that
login.

Two halves, and both are asserted because either alone leaves the contradiction: the page stops promising
what it is not showing, and `fleet.sh` prints a link for the roster clusters that actually carries it.
"""
from __future__ import annotations

import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
LAB = (REPO / "gitops/ai-layer/web/lab.html").read_text(encoding="utf-8")
FLEET = (REPO / "infra/terraform/fleet/fleet.sh").read_text(encoding="utf-8")

failures: list[str] = []


def check(name: str, cond: bool) -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        failures.append(name)


print("== the page's promise is conditional on there being something to show ==")
check("the sentence is addressable", 'id="ddlead"' in LAB)
check("the box still hides by default", 'id="ddcreds" style="display:none"' in LAB)
check("the box appears only with BOTH halves", "if(ddu&&ddp){" in LAB)
check("there is an else branch that rewrites the sentence", "var lead=document.getElementById('ddlead');" in LAB)
check("the fallback does not promise a box", "it is on the provisioning page you started from" in LAB)
# The fallback still has to send them somewhere real, and keep the docs link the sweep nearly lost twice.
check("the fallback still links Datadog's docs",
      LAB.count('href="https://docs.datadoghq.com/"') >= 2)

print("== fleet.sh hands the roster clusters a link that carries the login ==")
check("bootstrap hints print the lab links", "print_roster_lab_links" in FLEET)
check("the links are built from the public hostname", 'public_host_for "${name}"' in FLEET)
check("they carry all three params", "&ddu=" in FLEET and "&ddp=" in FLEET and "&dds=" in FLEET)
# A trial password with punctuation truncates the query string at the first & or #, handing over half a
# credential, which is the same failure the page's both-halves guard exists to prevent.
check("the values are percent-encoded", "urlenc" in FLEET and "'$s|@uri'" in FLEET)
check("a missing Datadog row degrades to a link without one",
      "no Datadog row resolved" in FLEET)

print("== the row is chosen by role, the same rule ingest uses ==")
check("there is a role-based resolver", "datadog_row_for_role()" in FLEET)
check("community and admin share the instructor org",
      re.search(r"community\|admin\) : ;;", FLEET) is not None)
check("it selects admin-instructor by role, not by pool index",
      '(.role//"")=="admin-instructor"' in FLEET)
check("any other role gets nothing", re.search(r"\*\) echo '\{\}'; return 0 ;;", FLEET) is not None)
# It runs on the provision path, outside register_with_provisioning, so it cannot rely on POOL1/POOL2.
check("it loads the pools itself", FLEET.count("watch-it-burn/datadog-pool") >= 4)
check("an unreachable secret does not fail a provision", "|| echo '[]'" in FLEET)

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All Datadog-login visibility checks passed.")
