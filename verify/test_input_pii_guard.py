# ABOUTME: The input guard's PII stage (#648): LLM Guard's Regex input scanner refuses the four kinds the public trace
# ABOUTME: scrub rewrites, with the scrub's own patterns, and none of the workshop's own prompts or tickets trips it.
"""Pins the input guard's double duty, which Whitney shows on stage in Challenge 3.

Measured from the repo on 2026-10-30, the input guard caught no PII at all: guard-proxy's block-list holds destructive
verbs and recipe phrases, and LLM Guard's input scanners were PromptInjection alone. #648 added a Regex input scanner.
This holds:

  - it is one Regex input scanner that blocks, with one pattern: the burn collector's four scrub patterns (#647,
    gitops/otel-collector/values-burn.yaml) joined as an alternation, so the guard refuses what the trace scrubs;
  - it matches every kind on its own and every PII value in the stage's prompt, and leaves the scrub's untouched
    text alone;
  - nothing the workshop itself sends trips it: no ticket on the support desk (read_support_ticket's check runs the
    same scanners), and no prompt the probe, /kubecon, the prompt catalog or the topic cases send;
  - guard-proxy's input classifier stage runs it (it suppresses only BanTopics), the block-list does not catch PII,
    and the /chat root span gets the prompt's content only after the input stages pass, so a refused prompt's
    trace carries none of it.

Python's re runs the pattern, as llm-guard's Regex scanner does. Offline.
"""
from __future__ import annotations

import importlib.util
import pathlib
import re
import sys

import yaml

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parent
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
scanners = yaml.safe_load(cm["data"]["scanners.yml"])

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
pages = [REPO / "challenges/PROMPT-CATALOG.md", *sorted((REPO / "gitops/ai-layer/web").glob("*.html"))]
for page in pages:
    hits = [m.group(0) for m in pii.finditer(page.read_text(encoding="utf-8", errors="replace"))]
    check(f"no prompt in {page.relative_to(REPO)} trips it", not hits, str(hits[:5]))

print("== guard-proxy runs it in the input classifier stage, and keeps the prompt off a refused trace ==")
proxy_path = REPO / "gitops/ai-layer/guard-proxy/proxy.py"
src = proxy_path.read_text(encoding="utf-8")
payload = '_post_guard("/analyze/prompt", {"prompt": text, "scanners_suppress": ["BanTopics"]})'
check("input_allowed suppresses only BanTopics, so the Regex scanner runs", payload in src)
check("`pii` and the seed's pii-scanner step ask LLM Guard exactly as input_allowed does",
      "proxy._post_guard('/analyze/prompt', {'prompt': t, 'scanners_suppress': ['BanTopics']})" in st.GUARD_VERDICT_PY)
mcp_src = (REPO / "gitops/ai-layer/workshop-mcp-server.py").read_text(encoding="utf-8")
check("read_support_ticket's check suppresses only BanTopics too, so a ticket is held to the same scanner",
      '"scanners_suppress": ["BanTopics"]' in mcp_src)
chat = src[src.index("def _handle_chat"):]
check("/chat stamps the classifier's refusal and returns before the root span is given the prompt",
      0 < chat.index('self._stamp("witb.guard.decision", "input_classifier")')
      < chat.index('_root_span.set_attribute("gen_ai.input.messages"'))
check("the refusal guard-proxy sends is the one the seed judges on",
      f'"BurritoBot can\'t help with that ({st.CLASSIFIER_BLOCK})."' in chat)
spec = importlib.util.spec_from_file_location("guard_proxy_pii", proxy_path)
proxy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(proxy)
caught = [kind for kind, text in st.PII_SAMPLES if proxy.blocklisted(text)]
check("the block-list catches none of the PII samples: the Regex scanner is the input guard's only PII stage",
      not caught, str(caught))

if failures:
    print(f"\n{len(failures)} FAILED")
    sys.exit(1)
print("\nALL INPUT PII GUARD CHECKS PASS")
