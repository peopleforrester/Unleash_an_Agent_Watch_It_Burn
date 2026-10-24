# ABOUTME: Render-gate check for the attendee chat surface: BurritoBot is the one chat front end, the
# ABOUTME: console's Agent tab loads it, and the retired chat-ui (#240) stays gone. No cluster needed.
import pathlib
import sys

import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
AI = REPO / "gitops" / "ai-layer"
WEB = AI / "web"
kust = yaml.safe_load((AI / "kustomization.yaml").read_text())
res = list(yaml.safe_load_all((AI / "resources.yaml").read_text()))
conf = (AI / "console.conf").read_text()
console_html = (WEB / "console.html").read_text()

failures = []


def check(name, cond):
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        failures.append(name)


# BurritoBot is served by the console nginx and posts to guard-proxy /chat.
gens = {g["name"]: g for g in kust.get("configMapGenerator", [])}
console_files = gens.get("console-src", {}).get("files", [])
check("console-src ships burritbot.html", any("web/burritbot.html" in f for f in console_files))
check("/ serves BurritoBot", "location = /          { try_files /burritbot.html =404; }" in conf)
check("/chat proxies to guard-proxy /chat", "proxy_pass http://guard-proxy:8080/chat;" in conf)

# chat-ui was a second nginx serving an older index.html/app.js, reached only through /console's Agent
# tab. Measured on a cluster with zero requests in its first hour (#240). Removed; the tab loads BurritoBot.
kinds = {(d.get("kind"), d.get("metadata", {}).get("name")) for d in res if d}
check("no chat-ui Deployment", ("Deployment", "chat-ui") not in kinds)
check("no chat-ui Service", ("Service", "chat-ui") not in kinds)
check("no chat-ui-src generator", "chat-ui-src" not in gens)
check("console.conf has no route to chat-ui", "chat-ui" not in conf and "location /chat/" not in conf)
check("the retired index.html and app.js are gone",
      not (WEB / "index.html").exists() and not (WEB / "app.js").exists())
check("the console's Agent tab loads BurritoBot", '<iframe src="/burritbot" title="agent chat">' in console_html)

# Timestamps on chat bubbles, so a student waiting on a trace can tell elapsed time (#282).
_bb = (WEB / "burritbot.html").read_text()
check("bubbles carry a timestamp line", ".msgts" in _bb and "fmtTs(now)" in _bb)
check("the age updates live", "relAge(" in _bb and "setInterval(" in _bb)
check("the reasoning fold stays above the stamp", "insertBefore(det, meta)" in _bb)

if failures:
    print(f"\nFAILED: {len(failures)} check(s)")
    sys.exit(1)
print("\nAll chat surface checks passed.")
