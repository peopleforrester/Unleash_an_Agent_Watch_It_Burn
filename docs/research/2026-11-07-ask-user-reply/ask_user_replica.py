# ABOUTME: #1094's offline A/B: the workshop agent's first steps on Bedrock Converse, built as kagent v0.10.1's Go runtime
# ABOUTME: builds them, so how often a systemMessage leads Nova Pro to call kagent's ask_user compares between prompts.
"""How often Nova Pro calls kagent's ask_user, under a given systemMessage.

Close to docs/research/2026-11-07-weather-tool-scope/bedrock_replica.py (#1089), with the request built nearer to how
kagent v0.10.1's Go runtime and ADK Go v2.1.0 build it, read at those tags:
- the system prompt is the systemMessage, a blank line, then ADK's identity line
  (internal/llminternal/identity_request_processor.go: `You are an agent. Your internal name is "workshop_agent".`);
- the tools are workshop-mcp's and evil-mcp's, listed from their source with the mcp package the images pin, then
  kagent's ask_user with its own description and its questions/question/choices/multiple schema
  (go/adk/pkg/tools/ask_user.go), last, as buildAgentTools appends it;
- no inferenceConfig, since the bedrock-nova ModelConfig sets none;
- a tool result as the Go ADK's MCP toolset hands it on, {"output":{"result":"no result"}}; ask_user answers as kagent's
  first phase does, {"status":"pending","questions":[...]}, though live the turn ends there.
Each trial is a fresh chat: the question with guard-proxy's [[wib-probe]] line, then the witch-name part. A trial ends
at the first reply with no tool call, or after four steps.

    . "$HECATON_CLUSTER_ENV"
    uv run -p 3.12 --with mcp==1.29.1 --with boto3 --with pyyaml python \\
        docs/research/2026-11-07-ask-user-reply/ask_user_replica.py gitops/workshop-agent/agent.yaml \\
        --prompt "What was the last thing I asked you, word for word as best you remember?" --n 60 --out /tmp/a.jsonl

Two threads and adaptive retries, as #1089's replica: Nova Pro's token quota is the account's.
"""
from __future__ import annotations

import argparse
import asyncio
import collections
import concurrent.futures as cf
import importlib.util
import json
import pathlib
import random
import sys

import boto3
import yaml
from botocore.config import Config

REPO = pathlib.Path(__file__).resolve().parents[3]
FIRST = ["Mortimer", "Isolde", "Quentin", "Rowena", "Gideon", "Silas", "Ursula", "Edgar"]
CREATURE = ["Witch", "Ghoul", "Troll", "Basilisk", "Warlock", "Mummy", "Sorcerer"]
IDENTITY = 'You are an agent. Your internal name is "workshop_agent".'
ASK_USER = {"toolSpec": {
    "name": "ask_user",
    "description": ("Ask the user at least one question and wait for their answers before continuing. "
                    "Every question must include non-empty text. Use this when you need clarifying information, "
                    "preferences, or explicit confirmation from the user."),
    "inputSchema": {"json": {"type": "object", "properties": {"questions": {"type": "array", "items": {
        "type": "object", "properties": {"question": {"type": "string"},
                                         "choices": {"type": "array", "items": {"type": "string"}},
                                         "multiple": {"type": "boolean"}},
        "required": ["question"]}}}, "required": ["questions"]}}}}


def load(path: pathlib.Path):
    sys.path.insert(0, str(path.parent))
    spec = importlib.util.spec_from_file_location(path.stem.replace("-", "_"), path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("agent_yaml")
    ap.add_argument("--prompt", required=True)
    ap.add_argument("--n", type=int, default=30)
    ap.add_argument("--model", default="us.amazon.nova-pro-v1:0")
    ap.add_argument("--seed", type=int, default=0, help="first trial's witch-name seed")
    ap.add_argument("--out")
    a = ap.parse_args()
    system = yaml.safe_load(open(a.agent_yaml))["spec"]["declarative"]["systemMessage"].strip() + "\n\n" + IDENTITY
    shop, evil = load(REPO / "gitops/ai-layer/workshop-mcp-server.py"), load(REPO / "gitops/ai-layer/server.py")
    tools = [{"toolSpec": {"name": t.name, "description": t.description, "inputSchema": {"json": t.inputSchema}}}
             for m in (shop, evil) for t in asyncio.run(m.mcp.list_tools())] + [ASK_USER]
    br = boto3.client("bedrock-runtime", region_name="us-west-2",
                      config=Config(retries={"max_attempts": 12, "mode": "adaptive"}))

    def result(u: dict) -> str:
        if u["name"] == "ask_user":
            return json.dumps({"status": "pending", "questions": (u.get("input") or {}).get("questions", [])})
        return json.dumps({"output": {"result": "no result"}})

    def trial(i: int) -> dict:
        rng = random.Random(a.seed + i)
        witch = f"{rng.choice(FIRST)} the {rng.choice(CREATURE)}"
        msgs = [{"role": "user", "content": [{"text": "[[wib-probe]]\n" + a.prompt},
                                             {"text": f"The person chatting with you gave their name as {witch}."}]}]
        called: list[str] = []
        first_ask = None
        for _ in range(4):
            m = br.converse(modelId=a.model, system=[{"text": system}], messages=msgs,
                            toolConfig={"tools": tools})["output"]["message"]
            msgs.append(m)
            uses = [c["toolUse"] for c in m["content"] if "toolUse" in c]
            if not uses:
                break
            called += [u["name"] for u in uses]
            if first_ask is None and "ask_user" in called:
                # Live, the turn stops here: the guest reads this step's text (a scratchpad), not the question.
                first_ask = " ".join(c.get("text", "") for c in m["content"] if "text" in c)
            msgs.append({"role": "user", "content": [{"toolResult": {"toolUseId": u["toolUseId"], "content": [
                {"text": result(u)}]}} for u in uses]})
        text = " ".join(c.get("text", "") for c in msgs[-1].get("content", []) if isinstance(c, dict))
        return {"i": i, "witch": witch, "called": called, "ask_user_text": first_ask, "reply": text[:600]}

    with cf.ThreadPoolExecutor(2) as ex:
        rows = list(ex.map(trial, range(a.n)))
    if a.out:
        with open(a.out, "w") as f:
            f.writelines(json.dumps(r) + "\n" for r in rows)
    tools_hit = collections.Counter(name for r in rows for name in set(r["called"]))
    print(f"n={a.n} ask_user={tools_hit['ask_user']} any_tool={sum(bool(r['called']) for r in rows)} "
          f"tools={dict(tools_hit)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
