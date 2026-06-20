# ABOUTME: Render-gate check for P5 attendee chat UI: the UI talks to the guard-proxy (A2A + /cost)
# ABOUTME: and is wired to be served (configMapGenerator + nginx Deployment/Service). No cluster needed.
import pathlib
import sys

import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
WEB = REPO / "gitops" / "ai-layer" / "web"
html = (WEB / "index.html").read_text()
appjs = (WEB / "app.js").read_text()
kust = yaml.safe_load((REPO / "gitops" / "ai-layer" / "kustomization.yaml").read_text())
res = list(yaml.safe_load_all((REPO / "gitops" / "ai-layer" / "resources.yaml").read_text()))

failures = []


def check(name, cond):
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        failures.append(name)


# UI structure: loads app.js, has the cost counter + chat controls.
check("index.html loads app.js", "app.js" in html)
check("index.html has the live cost counter element", 'id="cost"' in html)
check("index.html has the prompt input + send", 'id="prompt"' in html and 'id="send"' in html)

# UI behavior: A2A message/send to the proxy + polls /cost + parses the reply.
check("app.js sends an A2A message/send to the proxy", "message/send" in appjs and 'PROXY + "/"' in appjs)
check("app.js polls the guard-proxy /cost", '"/cost"' in appjs)
check("app.js extracts the agent reply text", "extractText" in appjs)

# Serving wiring: configMapGenerator + nginx Deployment + Service.
gens = {g["name"]: g for g in kust.get("configMapGenerator", [])}
check("kustomization generates chat-ui-src from the web files",
      "chat-ui-src" in gens and "web/index.html" in gens["chat-ui-src"]["files"])
kinds = {(d.get("kind"), d.get("metadata", {}).get("name")) for d in res if d}
check("chat-ui Deployment present", ("Deployment", "chat-ui") in kinds)
check("chat-ui Service present", ("Service", "chat-ui") in kinds)

if failures:
    print(f"\nFAILED: {len(failures)} check(s)")
    sys.exit(1)
print("\nAll chat-UI (P5) checks passed.")
