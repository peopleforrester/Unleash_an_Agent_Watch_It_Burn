# ABOUTME: Runs LLM Guard's real PromptInjection scanner (llm-guard 0.3.16, the image's version) with the params
# ABOUTME: deployed in llm-guard-scanners: Challenge 6's fetched ticket and input-guard.sh's injection block, menu asks pass.
# SUITE: e2e
# E2E TIER: tools (no cluster, no AWS: run-e2e-tools.sh runs it with the pinned tools, #572)
"""The cluster-free half of Challenge 6's guards-on beat (#128).

Challenge 6's ticket carries no block-list term, so with the input guards on it is the classifier alone that
refuses it. Since #640 the ticket is fetched by read_support_ticket from the fake ticket site, and the tool sends
the ticket BODY to this scanner, so the body is what is scanned here, read from gitops/ai-layer/ticket_site.py. Until this test that was only ever checked on a live cluster (verify/input-guard.sh, the probe).
Here the scanner is built the way the LLM Guard API builds it (use_onnx=True, model_max_length into the
pipeline's max_length) with the PromptInjection params read from the deployed scanners.yml, so a change to the
threshold or match_type is measured the moment it lands:

- the ticket body on the fake ticket site and the injection verify/input-guard.sh sends are refused;
- the same ticket with its payload paragraph removed passes, and so does every on-topic ask in topic_cases;
- every scan finishes inside the configured scan_prompt_timeout, because a slower scan is a 408 that
  guard-proxy, failing closed, turns into a refusal of an innocent prompt;
- the model is deberta-v3-base-prompt-injection-v2 at 90c9989b, the revision the offline image mirrors
  (images/llm-guard/Dockerfile).

What this config does NOT catch (an injection placed past the model's 512-token window, or one written without
the "ignore previous instructions" register) is measured in docs/spike-llm-guard-2026-10-26.md, not here.

Needs uv, and network on the first run: uv fetches llm-guard 0.3.16 and torch 2.14.0+cpu (CPU index, so no
CUDA packages), and the scanner downloads the model from Hugging Face. A missing tool or no network is a
failure, never a skip.
"""
from __future__ import annotations

import json
import pathlib
import re
import shutil
import subprocess
import sys

import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "verify"))
import topic_cases as tc  # noqa: E402

# The revision images/llm-guard mirrors. Its onnx/model.onnx is byte-identical to the one at 89b085cd, the
# revision llm-guard 0.3.16 pins (same LFS oid; the commits between change only the README and add a LICENSE).
MODEL = "protectai/deberta-v3-base-prompt-injection-v2"
REVISION = "90c9989b1a342275dd0d1a95aad283c04e075671"
LLM_GUARD = "0.3.16"

if shutil.which("uv") is None:
    print("FAIL  uv is not on PATH; it runs the pinned llm-guard without installing it globally", file=sys.stderr)
    sys.exit(1)

docs = [d for d in yaml.safe_load_all((REPO / "gitops/ai-layer/resources.yaml").read_text()) if d]
cm = next(d for d in docs if d.get("kind") == "ConfigMap" and d["metadata"]["name"] == "llm-guard-scanners")
scanners = yaml.safe_load(cm["data"]["scanners.yml"])
pi = [s for s in scanners["input_scanners"] if s["type"] == "PromptInjection"]
if len(pi) != 1:
    print(f"FAIL  scanners.yml has {len(pi)} PromptInjection scanners; Challenge 6 needs exactly one", file=sys.stderr)
    sys.exit(1)
params = {k: v for k, v in (pi[0].get("params") or {}).items() if k != "model_path"}
timeout_s = float(scanners["app"]["scan_prompt_timeout"])

from agent_probe import ticket_site  # noqa: E402

ticket = ticket_site.TICKETS[ticket_site.C6_TICKET_ID]["body"]
payload = ticket_site.C6_PAYLOAD
if payload not in ticket or not payload.startswith("IGNORE ALL PREVIOUS INSTRUCTIONS"):
    print("FAIL  the C6 ticket body has no 'IGNORE ALL PREVIOUS INSTRUCTIONS' paragraph to remove", file=sys.stderr)
    sys.exit(1)
clean_ticket = ticket.replace("\n\n" + payload, "")
probe = re.search(r'^INJECT="([^"]+)"$', (REPO / "verify/input-guard.sh").read_text(), re.M)
if probe is None:
    print("FAIL  verify/input-guard.sh has no INJECT= line", file=sys.stderr)
    sys.exit(1)

cases = [
    {"name": "Challenge 6's ticket body (ticket_site.py)", "text": ticket, "want": "refuse"},
    {"name": "input-guard.sh's injection", "text": probe.group(1), "want": "refuse"},
    {"name": "the same ticket without its payload", "text": clean_ticket, "want": "pass"},
]
cases += [{"name": repr(a), "text": a, "want": "pass"} for a in tc.ON_TOPIC + tc.VAGUE_ON_TOPIC]

# Runs inside the uv environment, building the scanner as llm_guard_api/app/scanner.py does for PromptInjection.
CHILD = r"""
import copy, json, sys, time
from llm_guard.input_scanners.prompt_injection import PromptInjection, V2_MODEL
model_id, revision, params, cases = sys.argv[1], sys.argv[2], json.loads(sys.argv[3]), json.loads(sys.argv[4])
m = copy.deepcopy(V2_MODEL)
m.path = m.onnx_path = model_id
m.revision = m.onnx_revision = revision
if params.get("model_max_length", 0) > 0:
    m.pipeline_kwargs["max_length"] = params.pop("model_max_length")
t = time.time()
s = PromptInjection(model=m, use_onnx=True, **params)
out = {"load_s": round(time.time() - t, 1), "rows": []}
s.scan("warm up")
for c in cases:
    t = time.time()
    _, valid, risk = s.scan(c["text"])
    out["rows"].append({"name": c["name"], "want": c["want"], "valid": valid, "risk": risk,
                        "ms": round((time.time() - t) * 1000)})
print("RESULT " + json.dumps(out))
"""

cmd = ["uv", "run", "--no-project", "--python", "3.12",
       "--index", "https://download.pytorch.org/whl/cpu", "--index-strategy", "unsafe-best-match",
       "--with", "torch==2.14.0+cpu", "--with", f"llm-guard[onnxruntime]=={LLM_GUARD}",
       "python", "-I", "-c", CHILD, MODEL, REVISION, json.dumps(params),
       json.dumps([{k: c[k] for k in ("name", "text", "want")} for c in cases])]
print(f"== PromptInjection {params} over {len(cases)} prompts ==")
r = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
line = next((ln for ln in r.stdout.splitlines() if ln.startswith("RESULT ")), None)
if r.returncode != 0 or line is None:
    print(f"FAIL  the classifier did not run (exit {r.returncode})\n{r.stderr[-3000:]}", file=sys.stderr)
    sys.exit(1)
res = json.loads(line[len("RESULT "):])

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"   ({detail})" if detail else ""))
    if not cond:
        failures.append(name)


for row in res["rows"]:
    got = "pass" if row["valid"] else "refuse"
    check(f"{row['want']}: {row['name']}", got == row["want"], f"risk {row['risk']}, {row['ms']} ms")
ms = sorted(r["ms"] for r in res["rows"])
check(f"every scan inside scan_prompt_timeout ({timeout_s:g} s)", ms[-1] < timeout_s * 1000, f"slowest {ms[-1]} ms")
print(f"  model load {res['load_s']} s; scan median {ms[len(ms) // 2]} ms, slowest {ms[-1]} ms")

if failures:
    print(f"\n{len(failures)} check(s) FAILED")
    sys.exit(1)
print("\nThe deployed PromptInjection config refuses Challenge 6 and passes the menu")
