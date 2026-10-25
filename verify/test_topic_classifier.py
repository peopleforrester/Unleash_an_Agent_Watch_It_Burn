# ABOUTME: Runs LLM Guard's real BanTopics scanner (llm-guard 0.3.16, the image's version) over every ask the
# ABOUTME: on-topic guard's phrase step leaves to it (#455): off-topic paraphrases must refuse, vague menu asks pass.
# SUITE: e2e
# E2E TIER: tools (no cluster, no AWS: run-e2e-tools.sh runs it with the pinned tools, #572)
"""The executed half of verify/test_topic_guard.py.

The phrase lists decide the canonical asks. Everything with neither an off nor an on phrase goes to BanTopics,
and this is where that classifier is judged, with the settings in verify/topic_cases.py and the phrase lists
deployed on guard-proxy:

- every off-topic ask the phrases leave over is refused;
- every vague on-topic ask ("what do you recommend", "do you deliver") passes;
- the model and revision are the ones llm-guard 0.3.16 itself pins for BanTopics, so the copy the offline
  image bakes is the copy measured here.

Needs uv, and network on the first run: uv fetches llm-guard 0.3.16 and torch 2.14.0+cpu (CPU index, so no
CUDA packages), and the scanner downloads the model from Hugging Face. A missing tool or no network is a
failure, never a skip.
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
import topic_cases as tc  # noqa: E402

if shutil.which("uv") is None:
    print("FAIL  uv is not on PATH; it runs the pinned llm-guard without installing it globally", file=sys.stderr)
    sys.exit(1)

docs = [d for d in yaml.safe_load_all((REPO / "gitops/ai-layer/resources.yaml").read_text()) if d]
proxy = next(d for d in docs if d.get("kind") == "Deployment" and d["metadata"]["name"] == "guard-proxy")
env = {e["name"]: e.get("value") for c in proxy["spec"]["template"]["spec"]["containers"] for e in c["env"]}
off = tc.split_list(env["TOPIC_OFF_LIST"])
on = tc.split_list(env["TOPIC_ON_LIST"])

cases = [{"ask": a, "want": "refuse"} for a in tc.OFF_TOPIC if tc.phrase_verdict(a, off, on) is None]
cases += [{"ask": a, "want": "pass"} for a in tc.VAGUE_ON_TOPIC if tc.phrase_verdict(a, off, on) is None]

# Runs inside the uv environment. It builds the scanner the way the LLM Guard API does (use_onnx=True,
# llm_guard_api's BanTopics model), so the verdicts are the ones guard-proxy will get from /analyze/prompt.
CHILD = r"""
import json, sys, time
from llm_guard.input_scanners.ban_topics import BanTopics, MODEL_DEBERTA_BASE_V2 as M
cfg, cases = json.loads(sys.argv[1]), json.loads(sys.argv[2])
t = time.time()
s = BanTopics(topics=cfg["topics"], threshold=cfg["threshold"], model=M, use_onnx=True)
out = {"model": M.path, "revision": M.revision, "onnx_revision": M.onnx_revision,
       "load_s": round(time.time() - t, 1), "rows": []}
for c in cases:
    t = time.time()
    _, valid, risk = s.scan(c["ask"])
    out["rows"].append({**c, "valid": valid, "risk": risk, "ms": round((time.time() - t) * 1000)})
print("RESULT " + json.dumps(out))
"""

cmd = ["uv", "run", "--no-project", "--python", "3.12",
       "--index", "https://download.pytorch.org/whl/cpu", "--index-strategy", "unsafe-best-match",
       "--with", "torch==2.14.0+cpu", "--with", f"llm-guard[onnxruntime]=={tc.CLASSIFIER['llm_guard']}",
       "python", "-I", "-c", CHILD, json.dumps(tc.CLASSIFIER), json.dumps(cases)]
print(f"== BanTopics over the {len(cases)} asks the phrase step leaves to it ==")
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


check("the scanner's model is the one topic_cases measured",
      res["model"] == tc.CLASSIFIER["model"] and res["revision"] == tc.CLASSIFIER["revision"]
      and res["onnx_revision"] == tc.CLASSIFIER["revision"],
      f"{res['model']}@{res['revision']}")
for row in res["rows"]:
    got = "pass" if row["valid"] else "refuse"
    check(f"{row['want']}: {row['ask']!r}", got == row["want"], f"risk {row['risk']}, {row['ms']} ms")
ms = sorted(r["ms"] for r in res["rows"])
print(f"  model load {res['load_s']} s; scan median {ms[len(ms) // 2]} ms, slowest {ms[-1]} ms")

if failures:
    print(f"\n{len(failures)} check(s) FAILED")
    sys.exit(1)
print("\nBanTopics holds the asks the phrase step leaves to it")
