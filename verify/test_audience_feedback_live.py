# ABOUTME: Live half of #1162 (#1241): the console ConfigMap Argo CD rolled on the community cluster serves the
# ABOUTME: committed event.js on attackme.burritobot.co, and the served page's own init sends Feedback to the talk form.
# SUITE: e2e
"""Needs kubectl, node, COMMUNITY_CONTEXT naming the community cluster's kube-context (watch-it-burn-community, the
cluster behind attackme), and the public internet. Every missing prerequisite is a failure with the reason, never a
skip.

#1162 pointed the storefront's Feedback button at the talk's own form, `https://feedback.burritobot.co/?source=burritobot`,
through `feedbackUrl` in gitops/ai-layer/web/event.js. The offline tests hold the committed file
(test_audience_event.py) and run the page's init on it (test_audience_page_e2e.py). Neither reads what the room's
phones get. This does, in three parts, and fails when any stops holding:

1. Argo CD rolled it (#252). On COMMUNITY_CONTEXT the `ai-layer` Application is Synced and Healthy, the console
   Deployment's `web` volume names a content-hashed `console-src-<hash>` ConfigMap that Argo CD tracks for
   `ai-layer`, the rollout is finished, and every console pod mounts that same ConfigMap. Its event.js is the
   committed event.js byte for byte, so the change reached the cluster through the hash roll, not a hand edit.
2. attackme serves it. `https://attackme.burritobot.co/event.js` is that ConfigMap's event.js byte for byte, and
   `https://attackme.burritobot.co/` is its burritbot.html and loads event.js ahead of the page's init.
3. The Feedback button opens the form. The served page's own `(function init(){...})();` block runs in node with
   the served event.js, on the host attackme.burritobot.co, once as a phone that opened the projector QR (no query)
   and once with a cluster and user in the query. Both times the Feedback href is the form's URL exactly, with no
   cluster or user. The form itself answers 200 and posts a hidden `source=burritobot`.

Read-only: kubectl get and HTTPS GETs. Nothing is submitted to the form.

Usage: COMMUNITY_CONTEXT=watch-it-burn-community python3 verify/test_audience_feedback_live.py
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request

REPO = pathlib.Path(__file__).resolve().parent.parent
WEB = REPO / "gitops/ai-layer/web"
EVENT_JS = (WEB / "event.js").read_text(encoding="utf-8")
CONTEXT = os.environ.get("COMMUNITY_CONTEXT", "")
NAMESPACE = "agent"
APP = "ai-layer"
PUBLIC = "https://attackme.burritobot.co/"
HOST = "attackme.burritobot.co"
FORM = "https://feedback.burritobot.co/?source=burritobot"
TIMEOUT_S = 20

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"\n        {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def finish() -> None:
    print()
    if failures:
        print(f"FAILED: {len(failures)} check(s)")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    print("All live audience Feedback checks passed.")


def kubectl_json(*args: str) -> dict:
    # --context on every call: the current-context belongs to whoever else is on this box (CLAUDE.md).
    r = subprocess.run(["kubectl", "--context", CONTEXT, "--request-timeout=20s", *args, "-o", "json"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        check(f"kubectl {' '.join(args)}", False, r.stderr.strip()[-400:])
        finish()
    return json.loads(r.stdout)


def fetch(url: str) -> tuple[int, str]:
    req = urllib.request.Request(url, headers={"User-Agent": "wib-verify/1241", "Cache-Control": "no-cache"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
            return r.status, r.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, OSError) as e:
        return 0, f"{type(e).__name__}: {e}"


# The stub DOM test_audience_page_e2e.py uses: the elements init touches, with href as a plain string, and every
# network call init makes (checkBackend, setInterval) a no-op, because only the links are under test. The Feedback
# button starts with the href the served page's own markup gives it.
HARNESS = r"""
const vm = require('vm');
const [eventSrc, initSrc, search, host, fbDefault] = JSON.parse(require('fs').readFileSync(0, 'utf8'));
const els = {};
for (const id of ['vttbtn', 'ddbtn', 'fbbtn', 'clusterid', 'clusterfoot']) els[id] = { href: '', textContent: '', title: '', hidden: false };
els.fbbtn.href = fbDefault;
const window = {};
const ctx = {
  window, URLSearchParams, URL, encodeURIComponent, JSON,
  location: { search, hostname: host },
  document: { getElementById: (id) => els[id] || null },
  localStorage: { getItem: () => null },
  loadSaved() {}, setBackendUp() {}, checkBackend() {}, setInterval() {},
};
vm.createContext(ctx);
if (eventSrc) vm.runInContext(eventSrc, ctx);
vm.runInContext(initSrc, ctx);
process.stdout.write(els.fbbtn.href);
"""


def feedback_href(event_src: str, init_src: str, search: str, fb_default: str) -> str:
    payload = json.dumps([event_src, init_src, search, HOST, fb_default])
    r = subprocess.run(["node", "-e", HARNESS], input=payload, capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else f"<node failed: {r.stderr.strip()[-300:]}>"


print("== prerequisites ==")
missing = [f"{t} is not on PATH" for t in ("kubectl", "node") if shutil.which(t) is None]
if not CONTEXT:
    missing.append("COMMUNITY_CONTEXT is not set: name the kube-context of the community cluster behind attackme "
                   "(watch-it-burn-community)")
for m in missing:
    check(m, False)
if missing:
    finish()
check("the committed event.js still names attackme.burritobot.co as publicUrl",
      f'publicUrl: "{PUBLIC}"' in EVENT_JS, f"no publicUrl: \"{PUBLIC}\" in {WEB / 'event.js'}")
check("the committed event.js still sets feedbackUrl to the talk form",
      f'feedbackUrl: "{FORM}"' in EVENT_JS, f"no feedbackUrl: \"{FORM}\" in {WEB / 'event.js'}")

print(f"== Argo CD rolled the console ConfigMap on {CONTEXT} (#252) ==")
app = kubectl_json("-n", "argocd", "get", "applications.argoproj.io", APP)
sync = app.get("status", {}).get("sync", {}).get("status")
health = app.get("status", {}).get("health", {}).get("status")
check(f"the {APP} Application is Synced", sync == "Synced", f"sync status {sync!r}")
check(f"the {APP} Application is Healthy", health == "Healthy", f"health status {health!r}")

dep = kubectl_json("-n", NAMESPACE, "get", "deployment", "console")
web = [v for v in dep["spec"]["template"]["spec"].get("volumes", []) if v.get("name") == "web"]
cm_name = (web[0].get("configMap") or {}).get("name", "") if web else ""
check("the console Deployment's web volume names a content-hashed console-src ConfigMap",
      re.fullmatch(r"console-src-[a-z0-9]{10}", cm_name) is not None,
      f"web volume ConfigMap {cm_name!r}: a bare name means a change would not roll the pod")
st = dep.get("status", {})
want = dep["spec"].get("replicas", 1)
check("the console rollout is finished",
      st.get("observedGeneration") == dep["metadata"].get("generation")
      and st.get("updatedReplicas") == want and st.get("readyReplicas") == want and st.get("replicas") == want,
      f"generation {dep['metadata'].get('generation')}, status {json.dumps(st)[:300]}")

pods = kubectl_json("-n", NAMESPACE, "get", "pods", "-l", "app.kubernetes.io/name=console")["items"]
running = [p for p in pods if p.get("status", {}).get("phase") == "Running" and not p["metadata"].get("deletionTimestamp")]
mounts = sorted({next((v.get("configMap", {}).get("name", "") for v in p["spec"].get("volumes", [])
                       if v.get("name") == "web"), "") for p in running})
check("every running console pod mounts that ConfigMap", bool(running) and mounts == [cm_name],
      f"{len(running)} running pod(s) mount {mounts}, the Deployment names {cm_name!r}")

cm = kubectl_json("-n", NAMESPACE, "get", "configmap", cm_name) if cm_name else {"metadata": {}, "data": {}}
tracking = cm["metadata"].get("annotations", {}).get("argocd.argoproj.io/tracking-id", "")
check(f"Argo CD tracks that ConfigMap for {APP}", tracking == f"{APP}:/ConfigMap:{NAMESPACE}/{cm_name}",
      f"tracking-id {tracking!r}")
cm_event = cm.get("data", {}).get("event.js", "")
cm_page = cm.get("data", {}).get("burritbot.html", "")
check("its event.js is the committed event.js, byte for byte (the change is promoted)", cm_event == EVENT_JS,
      "the cluster's event.js differs from gitops/ai-layer/web/event.js: not promoted yet, or edited by hand")

print(f"== {PUBLIC} serves that ConfigMap ==")
code, served_event = fetch(PUBLIC + "event.js")
check("GET /event.js answers 200", code == 200, f"HTTP {code}: {served_event[:200]}")
check("the served event.js is the ConfigMap's, byte for byte", code == 200 and served_event == cm_event,
      "attackme is not serving what the community cluster's console mounts")
code, served_page = fetch(PUBLIC)
check("GET / answers 200", code == 200, f"HTTP {code}: {served_page[:200]}")
check("the served page is the ConfigMap's burritbot.html, byte for byte", code == 200 and served_page == cm_page)
start = served_page.find("(function init(){")
end = served_page.find("})();", start)
check("the served page has its (function init(){ ... })(); block", start >= 0 and end > start)
loads = served_page.find('<script src="event.js"></script>')
check("the served page loads event.js ahead of init", 0 <= loads < start, f"event.js script at {loads}, init at {start}")
fb_tag = re.search(r'<a [^>]*id="fbbtn"[^>]*>', served_page)
fb_default = re.search(r'href="([^"]*)"', fb_tag.group(0)).group(1).replace("&amp;", "&") if fb_tag else ""
check("the served page has its Feedback button", bool(fb_default), "no <a id=\"fbbtn\" href=...> in the served page")
if start < 0 or end <= start or not fb_default:
    finish()
init_src = served_page[start:end + len("})();")]

print(f"== on {HOST}, the served page's own init sends Feedback to the talk form ==")
# The harness can tell the two apart: with no event set the button keeps the page's own default.
got = feedback_href("", init_src, "", fb_default)
check("self-check: with no event set, init leaves the page's default (not the form)",
      got == fb_default and got != FORM, got)
got = feedback_href(served_event, init_src, "", fb_default)
check("a phone that opened the QR (no query) gets the form, exactly", got == FORM, got)
got = feedback_href(served_event, init_src, "?cluster=watch-it-burn-community&user=a%40b.example", fb_default)
check("with a cluster and user in the query it is still the form, exactly, with neither appended", got == FORM, got)

print("== the form the button opens ==")
code, form = fetch(FORM)
check(f"GET {FORM} answers 200", code == 200, f"HTTP {code}: {form[:200]}")
check("the form posts a hidden source=burritobot",
      re.search(r'<input[^>]*type="hidden"[^>]*name="source"[^>]*value="burritobot"', form) is not None)

finish()
