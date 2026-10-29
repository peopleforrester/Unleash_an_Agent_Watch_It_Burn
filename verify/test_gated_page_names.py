# ABOUTME: The roster-only pages (/brief, /kubecon) answer on the console only at the names the apex router gates,
# ABOUTME: never at their file names, which nginx would otherwise serve straight from its root past the gate (#511).
"""Holds the console half of the roster-only gate (#152, #511).

The apex router 404s `/brief` and `/kubecon` on attendee hosts with an exact path match
(peopleforrester/apex-agenticburn, `@brief_not_roster`, `path /brief /kubecon` since #37). The console's default
server has a `root` over the whole console-src ConfigMap and no catch-all location, so nginx also serves each
page by its file name. Measured 2026-10-26 with nginx 1.27-alpine on this console.conf behind Caddy v2.11.4 and
the #37 matcher: `/kubecon.html` and `/brief.html` answered 200 on an attendee host while `/kubecon` was a 404.
So each gated page's file name must be a 404 on the console, and the clean name must still serve the page.
"""
from __future__ import annotations

import pathlib
import re
import sys

import yaml

REPO = pathlib.Path(__file__).resolve().parent.parent
CONF = (REPO / "gitops/ai-layer/console.conf").read_text(encoding="utf-8")
DEFAULT_SERVER = CONF[:CONF.index("map $http_upgrade")]
KUST = yaml.safe_load((REPO / "gitops/ai-layer/kustomization.yaml").read_text(encoding="utf-8"))

# The paths the router's @brief_not_roster matcher gates, as decisions.md records them (#152, #511).
GATED = ("brief", "kubecon")

failures: list[str] = []


def check(name: str, cond: bool) -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        failures.append(name)


console_src = next(g for g in KUST["configMapGenerator"] if g["name"] == "console-src")
shipped = {pathlib.Path(f.split("=")[-1]).name for f in console_src["files"]}

print("== each gated page serves at its gated name ==")
for page in GATED:
    check(f"/{page} serves {page}.html",
          re.search(rf"location = /{page} \{{ try_files /{page}\.html =404; \}}", DEFAULT_SERVER) is not None)
    check(f"{page}.html ships in console-src, under the console's root", f"{page}.html" in shipped)

print("== and is a 404 at its file name ==")
for page in GATED:
    check(f"/{page}.html is a 404",
          re.search(rf"location = /{page}\.html\s+\{{ return 404; \}}", DEFAULT_SERVER) is not None)
    # Nothing else in the default server may route the file name back to the page.
    others = [m.group(0) for m in re.finditer(rf"location [^{{]*/{page}\.html[^{{]*\{{[^}}]*\}}", DEFAULT_SERVER)
              if "return 404;" not in m.group(0)]
    check(f"no other location serves /{page}.html", not others)

# The console-src volume's own entries (#650). kubelet mounts a ConfigMap as a `..data` symlink to a
# `..<timestamp>` directory, with each key a symlink into it, so with no location for them nginx served
# /..data/brief.html straight from root. Every path whose first segment starts with a dot is a 404.
print("== and is a 404 under the volume's dot entries ==")
check("a ^~ /. prefix location returns 404",
      re.search(r"location \^~ /\. \{ return 404; \}", DEFAULT_SERVER) is not None)
dot_named = [f for f in shipped if f.startswith(".")]
check(f"console-src ships no file whose name starts with a dot {dot_named or ''}".rstrip(), not dot_named)

# An exact location beats every other kind in nginx, so the 404s above hold whatever is added later. A regex
# location could still hand a gated file out under some third name the router does not gate, so there is none.
print("== no regex location can alias a gated file ==")
check("the default server has no regex location", re.search(r"location\s+~", DEFAULT_SERVER) is None)

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All gated-page name checks passed.")
