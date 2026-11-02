# ABOUTME: The input guard's PII stage (#648): LLM Guard's Regex input scanner refuses the four kinds the public trace
# ABOUTME: scrub rewrites, with the scrub's own patterns, and none of the workshop's own prompts or tickets trips it.
"""Pins the input guard's double duty, which Whitney shows on stage in Challenge 3.

Measured from the repo on 2026-10-31, the input guard caught no PII at all: guard-proxy's block-list holds destructive
verbs and recipe phrases, and LLM Guard's input scanners were PromptInjection alone. #648 adds a Regex input scanner.
This holds:

  - it is one Regex input scanner that blocks, with one pattern: the burn collector's four scrub patterns (#647,
    gitops/otel-collector/values-burn.yaml) joined as an alternation, so the guard refuses what the trace scrubs;
  - llm-guard's pod template carries sha256(scanners.yml), so a scanner change restarts the API that reads it once;
  - it matches every kind on its own and every PII value in the stage's prompt, and leaves the scrub's untouched
    text alone;
  - nothing the workshop itself sends trips it: no ticket on the support desk (read_support_ticket's check runs the
    same scanners), and no prompt the probe, /kubecon, the prompt catalog or the topic cases send;
  - the pinned guard-proxy runs it: stage_traces.py's in-pod script, run here against the pinned proxy.py and a fake
    LLM Guard applying the configured scanners, refuses 5 of 5; and the pinned proxy's /chat, with the input
    classifier on, refuses the stage's prompt by the Regex scanner with zero tokens, before the root span is given
    the prompt, so a refused prompt's trace carries none of it.

Python's re runs the pattern, as llm-guard's Regex scanner does. Offline.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import pathlib
import re
import subprocess
import sys
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import yaml

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parent
PROXY_DIR = REPO / "gitops/ai-layer/guard-proxy"
sys.path.insert(0, str(HERE))
import kubecon_probe as kp  # noqa: E402
import stage_traces as st  # noqa: E402
import topic_cases as tc  # noqa: E402
from agent_probe import MCP_PROMPT, ticket_site  # noqa: E402
from pii_scrub_cases import ATTENDEE, UNTOUCHED, burn_scrub, patterns, unquote  # noqa: E402

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"\n        {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


docs = [d for d in yaml.safe_load_all((REPO / "gitops/ai-layer/resources.yaml").read_text(encoding="utf-8")) if d]
cm = next(d for d in docs if d.get("kind") == "ConfigMap" and d["metadata"]["name"] == "llm-guard-scanners")
scanners_yml = cm["data"]["scanners.yml"]
scanners = yaml.safe_load(scanners_yml)

print("== one Regex input scanner, the collector's patterns ==")
regex = [s for s in scanners["input_scanners"] if s["type"] == "Regex"]
check("exactly one Regex input scanner", len(regex) == 1, str(regex))
params = (regex[0] if regex else {}).get("params") or {}
check("it blocks on the first match and does not rewrite the prompt",
      params.get("is_blocked") is True and params.get("redact") is False and params.get("match_type") == "search",
      str({k: v for k, v in params.items() if k != "patterns"}))
check("PromptInjection is still the first input scanner",
      [s["type"] for s in scanners["input_scanners"]] == ["PromptInjection", "Regex"])
span_statements = burn_scrub()["trace_statements"][0]["statements"]
scrub = [(unquote(p), label) for _, p, label in patterns(span_statements)]
check("the burn scrub has its four labels", [label for _, label in scrub] == ["[EMAIL]", "[CARD]", "[SSN]", "[PHONE]"])
want = "|".join(f"(?:{p})" for p, _ in scrub)
check("the scanner's one pattern is the scrub's four, joined in order",
      params.get("patterns") == [want], f"{params.get('patterns')}\n        want {want}")
pii = re.compile((params.get("patterns") or ["(?!)"])[0])

print("== a scanner change restarts llm-guard ==")
llm_guard = next(d for d in docs if d.get("kind") == "Deployment" and d["metadata"]["name"] == "llm-guard")
got = (llm_guard["spec"]["template"]["metadata"].get("annotations") or {}).get("checksum/scanners-yml")
digest = hashlib.sha256(scanners_yml.encode()).hexdigest()[:12]
check(f"llm-guard's pod template carries checksum/scanners-yml = sha256(scanners.yml)[:12] (want {digest})",
      got == digest, f"got {got}: set it to {digest} in gitops/ai-layer/resources.yaml")
check("llm-guard mounts that ConfigMap", any((v.get("configMap") or {}).get("name") == "llm-guard-scanners"
                                             for v in llm_guard["spec"]["template"]["spec"]["volumes"]))

print("== what it refuses and what it leaves ==")
for (pattern, label) in scrub:
    for m in re.finditer(pattern, ATTENDEE):
        check(f"{label} {m.group(0)!r} is refused", bool(pii.search(m.group(0))))
for kind, text in st.PII_SAMPLES:
    check(f"the {kind} sample `pii` measures is refused", bool(pii.search(text)), text)
for v in st.PII_VALUES:
    check(f"the stage prompt's {v!r} is refused", bool(pii.search(v)) and v in st.PII_PROMPT)
for text in UNTOUCHED:
    check(f"text the scrub leaves alone passes: {text[:50]!r}", not pii.search(text), str(pii.findall(text)))
check("the `pii` control, a plain order, passes", not pii.search(st.PII_CONTROL))

print("== nothing the workshop sends trips it ==")
for tid, ticket in ticket_site.TICKETS.items():
    hits = [m.group(0) for m in pii.finditer(yaml.safe_dump(ticket))]
    check(f"ticket {tid} passes read_support_ticket's check", not hits, str(hits))
prompts = {"CEO_PROMPT": kp.CEO_PROMPT, "FRIENDLY_CEO_PROMPT": kp.FRIENDLY_CEO_PROMPT, "ROOM_PROMPT": kp.ROOM_PROMPT,
           "MCP_PROMPT": MCP_PROMPT, "ORDER_PROMPT": kp.ORDER_PROMPT, "OFF_TOPIC_PROMPT": kp.OFF_TOPIC_PROMPT}
prompts.update({f"CANONICAL_OFF[{i}]": t for i, t in enumerate(tc.CANONICAL_OFF)})
prompts.update({f"CANONICAL_ON[{i}]": t for i, t in enumerate(tc.CANONICAL_ON)})
for name, text in prompts.items():
    check(f"the probe's {name} passes", not pii.search(text), str(pii.findall(text)))
pages = [REPO / "challenges/PROMPT-CATALOG.md", REPO / "challenges/LAB-TEXT.md",
         *sorted((REPO / "gitops/ai-layer/web").glob("*.html"))]
for page in pages:
    hits = [m.group(0) for m in pii.finditer(page.read_text(encoding="utf-8", errors="replace"))]
    check(f"no prompt in {page.relative_to(REPO)} trips it", not hits, str(hits[:5]))

print("== guard-proxy asks for it, and keeps the prompt off a refused trace ==")
proxy_path = PROXY_DIR / "proxy.py"
src = proxy_path.read_text(encoding="utf-8")
verdict_fn = src[src.index("def input_verdict("):src.index("def input_allowed(")]
check("input_verdict suppresses only BanTopics, so the Regex scanner runs",
      re.search(r'_post_guard\("/analyze/prompt", \{"prompt": text, "scanners_suppress": \["BanTopics"\]\}',
                verdict_fn) is not None)
check("`pii` and the seed's check ask LLM Guard exactly as input_verdict does",
      "proxy._post_guard('/analyze/prompt', {'prompt': t, 'scanners_suppress': ['BanTopics']})" in st.GUARD_VERDICT_PY)
mcp_src = (REPO / "gitops/ai-layer/workshop-mcp-server.py").read_text(encoding="utf-8")
check("read_support_ticket's check suppresses only BanTopics too, so a ticket is held to the same scanner",
      '"scanners_suppress": ["BanTopics"]' in mcp_src)
chat = src[src.index("def _chat_turn"):]
check("/chat stamps the classifier's refusal and returns before the root span is given the prompt",
      0 < chat.index('self._stamp("witb.guard.decision", "input_classifier")')
      < chat.index('_root_span.set_attribute("gen_ai.input.messages"'))


# A fake LLM Guard API: the configured input scanners, less the suppressed ones. Regex is applied as llm-guard's
# scanner does (re.search per pattern, risk 1.0 on a match); PromptInjection needs its model, so it scores 0 here.
class FakeLLMGuard(BaseHTTPRequestHandler):
    seen: list[dict] = []

    def do_POST(self):  # noqa: N802
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))) or b"{}")
        FakeLLMGuard.seen.append({"path": self.path, **body})
        suppress = set(body.get("scanners_suppress") or [])
        scores, valid = {}, True
        for s in scanners["input_scanners"]:
            if s["type"] in suppress:
                continue
            hit = s["type"] == "Regex" and any(re.search(p, body.get("prompt", "")) for p in s["params"]["patterns"])
            scores[s["type"]] = 1.0 if hit else (-1.0 if s["type"] == "Regex" else 0.0)
            valid &= not hit
        raw = json.dumps({"is_valid": valid, "scanners": scores, "sanitized_prompt": body.get("prompt", "")}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, *a):
        pass


guard = ThreadingHTTPServer(("127.0.0.1", 0), FakeLLMGuard)
threading.Thread(target=guard.serve_forever, daemon=True).start()
GUARD_URL = f"http://127.0.0.1:{guard.server_address[1]}"

print("== `pii`'s in-pod script, run on the pinned proxy.py ==")
env = {**os.environ, "LLM_GUARD_URL": GUARD_URL, "OTEL_SDK_DISABLED": "true"}
code = st.GUARD_VERDICT_PY.replace("sys.path.insert(0, '/app')", f"sys.path.insert(0, {str(PROXY_DIR)!r})")
check("the script imports proxy from /app, where the pod mounts proxy.py", code != st.GUARD_VERDICT_PY)
texts = [t for _, t in st.PII_SAMPLES] + [st.PII_CONTROL]
r = subprocess.run([sys.executable, "-c", code, json.dumps(texts)], capture_output=True, text=True, env=env,
                   timeout=60)
check("it runs and prints its verdicts last", r.returncode == 0, r.stderr[-400:])
verdicts = json.loads(r.stdout.strip().splitlines()[-1]) if r.returncode == 0 else [{} for _ in texts]
caught = [st.judge_pii_caught(v) for v in verdicts[:-1]]
check("it refuses 5 of 5, each by the Regex scanner rather than the block-list",
      all(ok for ok, _ in caught) and all("Regex" in why for _, why in caught), str(caught))
check("the plain order passes both stages", st.judge_control_passes(verdicts[-1])[0], str(verdicts[-1]))
check("the block-list catches none of the PII samples: the Regex scanner is the input guard's only PII stage",
      not any(v.get("blocklist") for v in verdicts), str([v.get("blocklist") for v in verdicts]))

print("== the pinned proxy's /chat refuses the stage's prompt before the model ==")
# AGENT_URL points nowhere: a prompt the guard let through would fail here rather than reach a model.
os.environ.update({"LLM_GUARD_URL": GUARD_URL, "INPUT_CLASSIFIER": "on", "INPUT_BLOCKLIST": "on",
                   "AGENT_URL": "http://127.0.0.1:9"})
os.environ.setdefault("OTEL_SDK_DISABLED", "true")
spec = importlib.util.spec_from_file_location("guard_proxy_pii", proxy_path)
proxy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(proxy)
proxy.Handler.log_message = lambda *a: None
srv = ThreadingHTTPServer(("127.0.0.1", 0), proxy.Handler)
threading.Thread(target=srv.serve_forever, daemon=True).start()
FakeLLMGuard.seen.clear()
req = urllib.request.Request(f"http://127.0.0.1:{srv.server_address[1]}/chat",
                             data=json.dumps({"prompt": st.PII_PROMPT, "session": "wib-stage-c3-pii-test"}).encode(),
                             headers={"Content-Type": "application/json"})
with urllib.request.urlopen(req, timeout=30) as resp:
    d = json.load(resp)
ok, why = st.judge_pii_blocked(d)
check("the reply is the input guard's refusal by its Regex scanner, zero tokens, as the seed judges it", ok,
      f"{why}: {d}")
check("LLM Guard was asked once, with only BanTopics suppressed, and nothing went past it",
      [(c["path"], c.get("scanners_suppress")) for c in FakeLLMGuard.seen] == [("/analyze/prompt", ["BanTopics"])],
      str(FakeLLMGuard.seen))

srv.shutdown()
guard.shutdown()
if failures:
    print(f"\n{len(failures)} FAILED")
    sys.exit(1)
print("\nALL INPUT PII GUARD CHECKS PASS")
