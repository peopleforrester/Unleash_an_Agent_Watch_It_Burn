# ABOUTME: Render gate for #481: the internet-facing console nginx forwards no request to guard-proxy's
# ABOUTME: /toggle, on every profile that deploys it (admin, community), while the exec+localhost toggles stay.
"""Why this exists (#481).

console.conf had `location /a2a/ { proxy_pass http://guard-proxy:8080/; }`. The trailing slash strips the
prefix, so the route forwarded guard-proxy's whole path space, and
`https://<cluster>.agenticburn.com/a2a/toggle?output=off` reached the unauthenticated GET /toggle through the
console's internet-facing NLB. On the community cluster the whole room shares, and on the admin cluster that
is on the projector for KubeCon segments 3 to 7, any phone in the room could switch the guardrails off.

A string check for "no /a2a/" would pass the next prefix route that does the same thing under a new name.
So this resolves request paths the way nginx does (exact, then longest prefix, ^~, then regex in order) on
the server block nginx would use, works out the upstream path each one is forwarded as, and fails if any of
them reaches guard-proxy's /toggle. It also pins that every route to guard-proxy is an exact match on a path
from a short list, so a new prefix route to guard-proxy fails here before it can be probed.

"Rendered": what reaches the pod is the console-conf ConfigMap, generated as default.conf from this one
file, in the ai-layer bundle that both the admin and the community (burn) profiles deploy. Those links
are checked too, so a per-profile override cannot bring the route back unseen.

The live half is verify/test_console_no_toggle_live.py (E2E suite).
"""
from __future__ import annotations

import pathlib
import posixpath
import re
import sys

import yaml

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from bootstrap_chart import deploys, values_path  # noqa: E402

REPO = pathlib.Path(__file__).resolve().parents[1]
AI = REPO / "gitops/ai-layer"
CONF = (AI / "console.conf").read_text(encoding="utf-8")

# The only guard-proxy paths the public console may forward. /chat is the BurritoBot backend; the rest are
# read-only state the pages poll. Adding one here is a decision, not a fix for a red test.
ALLOWED_GUARD_PROXY_PATHS = {"/chat", "/cost", "/guards", "/prompts", "/controls"}

# Request paths an attacker would try, after nginx's own URI normalisation (it resolves ../ and merges
# slashes before matching, which posixpath.normpath models below).
PROBES = ["/toggle", "/toggle/", "/a2a/toggle", "/a2a/toggle/", "/a2a/guards", "/a2a/", "/a2a",
          "//toggle", "/a2a//toggle", "/chat/../toggle", "/cost/../toggle", "/guards/toggle",
          "/controls/toggle", "/prompts/toggle", "/chat/toggle", "/terminal/../toggle", "/toggle.html",
          "/TOGGLE", "/api/toggle", "/guard-proxy/toggle", "/proxy/toggle"]

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}{('  -> ' + detail) if (detail and not cond) else ''}")
    if not cond:
        failures.append(name)


def strip_comments(text: str) -> str:
    """Drop # comments that are not inside a quoted string."""
    out = []
    for line in text.splitlines():
        quote = ""
        for i, ch in enumerate(line):
            if quote:
                if ch == quote:
                    quote = ""
            elif ch in "'\"":
                quote = ch
            elif ch == "#":
                line = line[:i]
                break
        out.append(line)
    return "\n".join(out)


def blocks(text: str, head: str) -> list[tuple[str, str]]:
    """Every top-level `<head> <args> { body }` in text, as (args, body), with braces in strings skipped."""
    found = []
    for m in re.finditer(rf"(?m)^\s*{head}\b([^{{;]*)\{{", text):
        depth, quote, i = 1, "", m.end()
        while i < len(text) and depth:
            ch = text[i]
            if quote:
                quote = "" if ch == quote else quote
            elif ch in "'\"":
                quote = ch
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
            i += 1
        found.append((m.group(1).strip(), text[m.end():i - 1]))
    return found


def locations(server_body: str) -> list[dict]:
    locs = []
    for args, body in blocks(server_body, "location"):
        parts = args.split(None, 1)
        mod, path = (parts[0], parts[1].strip()) if len(parts) == 2 else ("", parts[0])
        pp = re.search(r"\bproxy_pass\s+([^;]+);", body)
        locs.append({"mod": mod, "path": path, "proxy_pass": pp.group(1).strip() if pp else None})
    return locs


def match(locs: list[dict], uri: str) -> dict | None:
    """nginx's location selection for one normalised URI."""
    for loc in locs:
        if loc["mod"] == "=" and loc["path"] == uri:
            return loc
    prefixes = [loc for loc in locs if loc["mod"] in ("", "^~") and uri.startswith(loc["path"])]
    best = max(prefixes, key=lambda loc: len(loc["path"]), default=None)
    if best and best["mod"] == "^~":
        return best
    for loc in locs:
        if loc["mod"] in ("~", "~*"):
            flags = re.I if loc["mod"] == "~*" else 0
            if re.search(loc["path"], uri, flags):
                return loc
    return best


def forwarded(loc: dict, uri: str) -> tuple[str, str] | None:
    """(upstream host, upstream path) nginx sends for uri through loc, or None when it does not proxy."""
    target = loc["proxy_pass"] if loc else None
    if not target:
        return None
    m = re.match(r"https?://([^/]+)(/.*)?$", target)
    if not m:
        return ("<variable>", target)
    host, base = m.group(1), m.group(2)
    if base is None:                        # no URI part: the original request path goes through as is
        return host, uri
    if loc["mod"] == "=":
        return host, base
    return host, base + uri[len(loc["path"]):]   # prefix replaced by the proxy_pass URI


def is_guard_proxy(host: str) -> bool:
    return host.split(":")[0].split(".")[0] == "guard-proxy"


conf = strip_comments(CONF)
servers = blocks(conf, "server")
# Four: the default server, the service-host server, C6's maintenance-shell server (#664) and C6's ticket desk,
# support-<cluster> (2026-10-28 call).
check("console.conf has the default, service-host, C6 villain and C6 ticket-desk servers", len(servers) == 4,
      f"{len(servers)}")
default = servers[0][1] if servers else ""
check("the first server is the default one (server_name _), which every console hostname reaches",
      re.search(r"\bserver_name\s+_\s*;", default) is not None)
locs = locations(default)
check("the default server's locations parse", len(locs) > 10, f"{len(locs)}")

print("== no route forwards to guard-proxy's /toggle ==")
check("there is no /a2a/ route", not any(loc["path"].startswith("/a2a") for loc in locs),
      f"{[loc['path'] for loc in locs if loc['path'].startswith('/a2a')]}")
for raw in PROBES:
    uri = posixpath.normpath("/" + raw.lstrip("/")) + ("/" if raw.endswith("/") and raw != "/" else "")
    uri = uri.replace("//", "/")
    loc = match(locs, uri)
    up = forwarded(loc, uri) if loc else None
    reaches_toggle = bool(up) and is_guard_proxy(up[0]) and up[1].lower().startswith("/toggle")
    where = f"{loc['mod']} {loc['path']} -> {up}" if loc else "no location (static root, 404)"
    check(f"GET {raw} does not reach guard-proxy /toggle", not reaches_toggle, where)

print("== every route to guard-proxy is an exact match on an allowed path ==")
gp = [loc for loc in locs if loc["proxy_pass"] and (fw := forwarded(loc, loc["path"])) and is_guard_proxy(fw[0])]
check("the console still routes to guard-proxy (BurritoBot /chat, the badges)", len(gp) >= 2, f"{gp}")
for loc in gp:
    _, path = forwarded(loc, loc["path"])
    check(f"location {loc['mod']} {loc['path']} is an exact match", loc["mod"] == "=",
          "a prefix or regex route forwards every path under it, the way /a2a/ did")
    check(f"location {loc['mod']} {loc['path']} forwards an allowed path ({path})",
          path in ALLOWED_GUARD_PROXY_PATHS and path == loc["path"], f"allowed: {sorted(ALLOWED_GUARD_PROXY_PATHS)}")

print("== the service-host server cannot reach guard-proxy either ==")
vhost_map = next((body for args, body in blocks(conf, "map") if "$wib_service_upstream" in args), "")
check("the service-host map exists", bool(vhost_map))
check("no service hostname maps to guard-proxy", "guard-proxy" not in vhost_map)
check("the service-host server names no guard-proxy upstream", len(servers) < 2 or "guard-proxy" not in servers[1][1])
c6 = next((body for _, body in servers if "maintenance-shell-" in body), "")
check("C6's villain server exists", bool(c6))
check("C6's villain server names no guard-proxy upstream and only the maintenance-shell Service",
      "guard-proxy" not in c6 and re.findall(r"https?://[a-z0-9.-]+", c6) == ["http://maintenance-shell.agent.svc.cluster.local"],
      f"{re.findall(r'https?://[a-z0-9.-]+', c6)}")

print("== this file is what the admin and community clusters serve ==")
kust = yaml.safe_load((AI / "kustomization.yaml").read_text(encoding="utf-8"))
gens = {g["name"]: g for g in kust.get("configMapGenerator", [])}
check("console-conf is generated as default.conf from console.conf",
      gens.get("console-conf", {}).get("files") == ["default.conf=console.conf"], f"{gens.get('console-conf')}")
check("no kustomize patch rewrites console-conf",
      "console-conf" not in yaml.safe_dump({k: v for k, v in kust.items() if k != "configMapGenerator"}))
app = yaml.safe_load((REPO / "gitops/bootstrap/apps/ai-layer.yaml").read_text(encoding="utf-8"))
srcs = app["spec"].get("sources") or [app["spec"].get("source", {})]
check("the ai-layer Application deploys gitops/ai-layer", any(s.get("path") == "gitops/ai-layer" for s in srcs),
      f"{srcs}")
for profile, chart_profile in (("admin", "admin"), ("community", "burn")):
    check(f"the {profile} profile deploys the ai-layer Application from gitops/bootstrap/apps",
          deploys(chart_profile, "ai-layer.yaml"))
    # Comments are exempt: the burn values file explains in one why the console needs cert-manager.
    vf = values_path(chart_profile)
    extra = [vf.name] if re.search(r"console[-.]conf|guard-proxy", strip_comments(vf.read_text(encoding="utf-8"))) else []
    check(f"the {profile} profile carries no console-conf or guard-proxy override of its own", not extra, f"{extra}")

print("== the students' toggles do not depend on the console ==")
lib = (AI / "web-terminal/entrypoint.sh").read_text(encoding="utf-8")
check("the terminal's _px helper execs into guard-proxy and calls localhost /toggle",
      "kubectl -n agent exec deploy/guard-proxy" in lib and "http://localhost:8080/toggle?$1" in lib)
lab = (AI / "web/lab.html").read_text(encoding="utf-8")
check("the lab's toggle commands exec into guard-proxy and call localhost",
      "exec deploy/guard-proxy" in lab and "http://localhost:8080/toggle?" in lab
      and "agenticburn.com/a2a" not in lab and "/a2a/toggle" not in lab)

if failures:
    print(f"\nFAIL: {len(failures)} check(s) failed: {failures}")
    sys.exit(1)
print("\nPASS: the public console forwards nothing to guard-proxy's /toggle")
