# ABOUTME: Runs LLM Guard's real Regex input scanner (llm-guard 0.3.16, the image's version), built from the deployed
# ABOUTME: llm-guard-scanners params as the API builds it: the five PII prompts are refused, the workshop's own text is not.
# SUITE: e2e
# E2E TIER: tools (no cluster, no AWS: run-e2e-tools.sh runs it with the pinned tools, #572)
"""The cluster-free half of `stage_traces.py pii` (#648).

verify/test_input_pii_guard.py proves the pattern with Python's re and a fake LLM Guard. This builds the scanner with
llm-guard itself, through `llm_guard.input_scanners.get_scanner_by_name("Regex", params)`, the call the API's
scanner.py makes for a scanners.yml entry, so a param llm-guard reads differently (match_type, redact, is_blocked) is
caught here, not on the private cluster:

- the scanner's class is named Regex, which is what guard-proxy's refusal names and what scanners_suppress matches;
- the four kinds `pii` sends, and the stage's c3-pii prompt, are refused with risk 1.0, and the prompt is not rewritten;
- a plain order, every probe prompt, every topic case and every support-desk ticket pass.

Needs uv, and network on the first run: uv fetches llm-guard 0.3.16 and torch 2.14.0+cpu, the same environment
test_injection_classifier.py uses. The Regex scanner loads no model. A missing tool or no network is a failure,
never a skip.
"""
from __future__ import annotations

import json
import pathlib
import shutil
import subprocess
import sys

import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "verify"))
import kubecon_probe as kp  # noqa: E402
import stage_traces as st  # noqa: E402
import topic_cases as tc  # noqa: E402
from agent_probe import MCP_PROMPT, ticket_site  # noqa: E402

LLM_GUARD = "0.3.16"

if shutil.which("uv") is None:
    print("FAIL  uv is not on PATH; it runs the pinned llm-guard without installing it globally", file=sys.stderr)
    sys.exit(1)

docs = [d for d in yaml.safe_load_all((REPO / "gitops/ai-layer/resources.yaml").read_text()) if d]
cm = next(d for d in docs if d.get("kind") == "ConfigMap" and d["metadata"]["name"] == "llm-guard-scanners")
regex = [s for s in yaml.safe_load(cm["data"]["scanners.yml"])["input_scanners"] if s["type"] == "Regex"]
if len(regex) != 1:
    print(f"FAIL  scanners.yml has {len(regex)} Regex input scanners; the PII stage needs exactly one", file=sys.stderr)
    sys.exit(1)
params = regex[0]["params"]

cases = [{"name": f"the {kind} sample", "text": text, "want": "refuse"} for kind, text in st.PII_SAMPLES]
cases.append({"name": "the plain order `pii` checks", "text": st.PII_CONTROL, "want": "pass"})
cases += [{"name": n, "text": t, "want": "pass"} for n, t in (
    ("CEO_PROMPT", kp.CEO_PROMPT), ("FRIENDLY_CEO_PROMPT", kp.FRIENDLY_CEO_PROMPT), ("ROOM_PROMPT", kp.ROOM_PROMPT),
    ("MCP_PROMPT", MCP_PROMPT), ("OFF_TOPIC_PROMPT", kp.OFF_TOPIC_PROMPT))]
cases += [{"name": repr(a), "text": a, "want": "pass"} for a in tc.ON_TOPIC + tc.VAGUE_ON_TOPIC + tc.CANONICAL_OFF]
cases += [{"name": f"ticket {tid}", "text": yaml.safe_dump(t), "want": "pass"} for tid, t in ticket_site.TICKETS.items()]

# Runs inside the uv environment, building the scanner as llm_guard_api/app/scanner.py does for a Regex entry.
CHILD = r"""
import json, sys
from llm_guard import input_scanners
params, cases = json.loads(sys.argv[1]), json.loads(sys.argv[2])
s = input_scanners.get_scanner_by_name("Regex", params)
out = {"class": type(s).__name__, "rows": []}
for c in cases:
    sanitized, valid, risk = s.scan(c["text"])
    out["rows"].append({"name": c["name"], "want": c["want"], "valid": valid, "risk": risk,
                        "rewritten": sanitized != c["text"]})
print("RESULT " + json.dumps(out))
"""

cmd = ["uv", "run", "--no-project", "--python", "3.12",
       "--index", "https://download.pytorch.org/whl/cpu", "--index-strategy", "unsafe-best-match",
       "--with", "torch==2.14.0+cpu", "--with", f"llm-guard[onnxruntime]=={LLM_GUARD}",
       "python", "-I", "-c", CHILD, json.dumps(params),
       json.dumps([{k: c[k] for k in ("name", "text", "want")} for c in cases])]
print(f"== Regex over {len(cases)} texts ==")
r = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
line = next((ln for ln in r.stdout.splitlines() if ln.startswith("RESULT ")), None)
if r.returncode != 0 or line is None:
    print(f"FAIL  the scanner did not run (exit {r.returncode})\n{r.stderr[-3000:]}", file=sys.stderr)
    sys.exit(1)
res = json.loads(line[len("RESULT "):])

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"   ({detail})" if detail else ""))
    if not cond:
        failures.append(name)


check("the scanner's class is Regex, the name guard-proxy's refusal gives and scanners_suppress matches",
      res["class"] == st.PII_SCANNER, res["class"])
for row in res["rows"]:
    got = "pass" if row["valid"] else "refuse"
    check(f"{row['want']}: {row['name']}", got == row["want"], f"risk {row['risk']}")
    if row["want"] == "refuse":
        check(f"  with risk 1.0 and the prompt left as sent: {row['name']}",
              row["risk"] == 1.0 and not row["rewritten"], f"risk {row['risk']}, rewritten {row['rewritten']}")

if failures:
    print(f"\n{len(failures)} check(s) FAILED")
    sys.exit(1)
print("\nThe deployed Regex input scanner refuses the five PII prompts and passes the workshop's own text")
