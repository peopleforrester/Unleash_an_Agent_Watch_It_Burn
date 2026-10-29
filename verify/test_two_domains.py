# ABOUTME: The platform answers on agenticburn.com and burritobot.co at once (#651, step A): the console's host
# ABOUTME: rules, the pages' service links and the console certificate accept both, and no page brands itself agenticburn.
"""Pins step A of #651.

Michael's decision 2026-10-28: serve both domains for redundancy and display burritobot.co. Step A is what is
safe before burritobot.co resolves: everything that matches a hostname accepts both. The regexes are cut from
the real files and run against hostnames on each domain, so a rule that only looks right fails here.
"""
from __future__ import annotations

import pathlib
import re
import sys

import yaml

REPO = pathlib.Path(__file__).resolve().parent.parent
WEB = REPO / "gitops/ai-layer/web"
CONF = (REPO / "gitops/ai-layer/console.conf").read_text()
DOMAINS = ("agenticburn.com", "burritobot.co")
failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  ({detail})" if detail and not cond else ""))
    if not cond:
        failures.append(name)


print("== the console routes <service>-<cluster> on both domains ==")
rules = re.findall(r'"~(\^[a-z-]+-\[a-z0-9-\]\+\\\..*?\$)"\s+(\S+);', CONF)
check("the host map has rules", len(rules) >= 2, str(len(rules)))
for svc in ("grafana", "argocd"):
    for d in DOMAINS:
        host = f"{svc}-burritobot-private.{d}"
        check(f"{host} maps to an upstream", any(re.fullmatch(rx, host) for rx, _ in rules))
check("an unrelated domain maps to nothing",
      not any(re.fullmatch(rx, "grafana-attackme.example.com") for rx, _ in rules))
sn = re.search(r"server_name (~\^\(grafana[^;]*\$);", CONF)
for d in DOMAINS:
    check(f"server_name accepts grafana-attackme.{d}", sn is not None and re.fullmatch(sn.group(1)[1:], f"grafana-attackme.{d}") is not None)

print("== the pages build service links on either domain ==")
for page in ("links.html", "platform.html"):
    src = (WEB / page).read_text()
    m = re.search(r"if\s*\(\s*!\s*/(.+?)/\.test\(h\)\s*\)\s*return", src)
    rx = m.group(1) if m else ""
    for d in DOMAINS:
        check(f"{page}: a host on {d} gets links", bool(rx) and re.search(rx, f"burritobot-private.{d}") is not None, rx)
    check(f"{page}: a raw load balancer name gets none", bool(rx) and re.search(rx, "a1b2.elb.us-west-2.amazonaws.com") is None)

print("== the console certificate names both ==")
docs = [d for d in yaml.safe_load_all((REPO / "gitops/ai-layer/resources.yaml").read_text()) if isinstance(d, dict)]
cert = next((d for d in docs if d.get("kind") == "Certificate" and d["metadata"]["name"] == "console-tls"), {})
names = cert.get("spec", {}).get("dnsNames", [])
check("console-tls names *.agenticburn.com and *.burritobot.co", {"*.agenticburn.com", "*.burritobot.co"} <= set(names), str(names))

print("== the storefront does not brand itself agenticburn ==")
page = (WEB / "burritbot.html").read_text()
title = re.search(r"<title>(.*?)</title>", page, re.S)
check("the title does not say agenticburn", title is not None and "agenticburn" not in title.group(1).lower(), title.group(1) if title else "")
brand = re.search(r'<div class="brand">(.*?)</div>', page, re.S)
check("the brand label does not say agenticburn", brand is not None and "agenticburn" not in brand.group(1).lower())
check("the brand label names burritobot.co", brand is not None and "burritobot.co" in brand.group(1))

print("== the presenter pages name burritobot.co, not agenticburn.com, for the roster (#651 step B) ==")
def visible(src: str) -> str:
    src = re.sub(r"<!--.*?-->", "", src, flags=re.S)
    return re.sub(r"<(script|style)\b.*?</\1>", "", src, flags=re.S | re.I)
for page in ("kubecon.html", "brief.html"):
    v = visible((WEB / page).read_text())
    left = re.findall(r"(?:attackme|burritobot-private|-admin)\.agenticburn\.com", v)
    check(f"{page} shows no roster host on agenticburn.com", not left, str(left))
    check(f"{page} shows attackme.burritobot.co", "attackme.burritobot.co" in v)

print("== the instructor console at start.burritobot.co can read each cluster ==")
# The console polls /cost and /prompts cross-origin; the guard-proxy answers CORS only for CONSOLE_ORIGIN, which
# defaults to start.agenticburn.com. Walked 2026-10-29: start.burritobot.co showed both clusters down and $0.
docs = list(yaml.safe_load_all((REPO / "gitops/ai-layer/resources.yaml").read_text()))
gp = next(d for d in docs if d and d.get("kind") == "Deployment" and d["metadata"]["name"] == "guard-proxy")
env = {e["name"]: e.get("value") for c in gp["spec"]["template"]["spec"]["containers"] for e in c.get("env", [])}
check("guard-proxy sets CONSOLE_ORIGIN to https://start.burritobot.co",
      env.get("CONSOLE_ORIGIN") == "https://start.burritobot.co", str(env.get("CONSOLE_ORIGIN")))
import importlib.util, os  # noqa: E401,E402
os.environ["CONSOLE_ORIGIN"] = str(env.get("CONSOLE_ORIGIN"))
spec = importlib.util.spec_from_file_location("guard_proxy_twin", REPO / "gitops/ai-layer/guard-proxy/proxy.py")
proxy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(proxy)


class _Req:
    def __init__(self, origin: str) -> None:
        self.headers = {"Origin": origin, "Host": "attackme.burritobot.co"}


check("the proxy allows the console's origin", proxy._origin_allowed(_Req("https://start.burritobot.co")))
check("the proxy still refuses a foreign origin", not proxy._origin_allowed(_Req("https://evil.example")))

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    sys.exit(1)
print("All two-domain checks passed.")
