# ABOUTME: A service hostname on a cluster whose profile omits that service must explain itself, not
# ABOUTME: return a bare 502 that sends somebody hunting for a component that was never installed.
"""Pins the not-installed page on the console's service vhosts (#341, #273).

`grafana-attackme.agenticburn.com` returned 502 on event day. It is not a fault: the burn profile installs
no Prometheus and no Grafana, so the vhost resolves nothing. The console's own comment already said a
missing Service "is a 502 for that one host rather than a console that refuses to start", which is the
right engineering answer and the wrong answer for a person standing in front of it.

Two things this asserts. That the vhost catches its own upstream failure and answers with something
readable. And that the page is self-contained, because the moment somebody is most likely to hit it is
after Challenge 1's default-deny is applied, when the browser can fetch nothing else.

Verified by running nginx against this exact config and requesting the Grafana host with nothing behind it:
HTTP 200 and the page, where it used to be 502 and nothing.
"""
from __future__ import annotations

import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
CONF = (REPO / "gitops/ai-layer/console.conf").read_text(encoding="utf-8")
BURN = (REPO / "gitops/bootstrap/burn/app-of-apps-burn.yaml").read_text(encoding="utf-8")

failures: list[str] = []


def check(name: str, cond: bool) -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        failures.append(name)


print("== the vhost intercepts its own upstream failure ==")
check("errors are intercepted", "proxy_intercept_errors on;" in CONF)
# 503 and 504 as well as 502: a resolver timeout and an unready Service produce those, and they are the
# same situation from the visitor's side.
check("502, 503 and 504 all reach the page", re.search(r"error_page 502 503 504 = @wib_not_here;", CONF) is not None)
check("the named location exists", "location @wib_not_here {" in CONF)
check("it answers 200, not another error", re.search(r"@wib_not_here \{.*?return 200", CONF, re.S) is not None)

print("== the page is self-contained ==")
# Challenge 1's default-deny is exactly when someone lands here, so anything fetched is anything missing.
body = CONF[CONF.index("location @wib_not_here"):]
body = body[:body.index("';") + 2]
check("no external stylesheet", "<link" not in body)
check("no external script", "<script" not in body)
check("no image", "<img" not in body)
check("styles are inline", "<style>" in body)

print("== it says the true thing, and where to go instead ==")
check("it says the service is not running here", "not running on this cluster" in body)
check("it names AttackMe as deliberate", "deliberately runs no" in body)
check("it sends them to Datadog instead", "app.datadoghq.com/llm/traces" in body)
check("it says Datadog works everywhere, which is why it is the answer",
      "works\non every cluster" in body or "works on every cluster" in body)
# The same 502 also means "installed but not ready", so the page must not assert it was never installed.
check("it allows for a service that is merely starting", "may simply be starting" in body)
check("it gives them a command to tell the difference", "kubectl get pods -A" in body)

print("== the burn profile really does omit these, so the page is telling the truth ==")
check("no prometheus in the burn profile", "prometheus" not in BURN)
check("no grafana in the burn profile", "grafana" not in BURN)
check("no argocd app in the burn profile include list",
      re.search(r"include: '\{[^}]*\bargocd\b[^}]*\}", BURN) is None)
check("but Datadog IS there, or the page would be sending them nowhere",
      "datadog-agent-cr" in BURN and "otel-collector" in BURN)

print("== every page that ships is actually routed (#338) ==")
# display.html shipped in the image and was asserted by test_brand_skin, but console.conf had no location
# for it, so it 404'd on every cluster while the suite stayed green on a page nobody could fetch. A test
# that checks a file's CONTENT without checking it is REACHABLE is the trap. Assert both display routes,
# and, generally, that every served-looking web page has a location.
check("display is routed", "location = /display " in CONF)
check("the historical /display.html is routed too", "location = /display.html " in CONF)
WEB = REPO / "gitops/ai-layer/web"
# Pages the console serves at an extensionless path; each must have a matching location.
for name in ("burritbot", "lab", "brief", "platform", "diagram", "links", "console", "display"):
    check(f"/{name} has a location", f"/{name} " in CONF and (f"{name}.html" in CONF or name == "console.js"))

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All console service-vhost checks passed.")
