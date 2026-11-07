# ABOUTME: #1094's offline A/B: the workshop agent's first steps on Bedrock Converse with kagent v0.10.1's own ask_user
# ABOUTME: tool, ending the turn where kagent ends it, so two persona prompts compare on how often Nova calls ask_user.
"""How often Nova Pro calls ask_user, for a given systemMessage.

The weather replica beside this one (../2026-11-07-weather-tool-scope/bedrock_replica.py) wrote its own ask_user. This
one copies kagent v0.10.1's: the name, the description in go/adk/pkg/tools/ask_user.go, and the input schema of its
askUserInput struct (questions, each a question with optional choices and multiple). kagent ends the turn in
input-required as soon as ask_user runs, so a trial ends there too, as a hit. Any other tool answers "no result", and
evil-mcp's tools answer with server.py's own text, as the weather replica's --chain does.

    . "$HECATON_CLUSTER_ENV"
    uv run -p 3.12 --with mcp==1.29.1 --with boto3 --with pyyaml python \\
        docs/research/2026-11-07-ask-user/ask_user_replica.py gitops/workshop-agent/agent.yaml \\
        --prompt "What was the last thing I asked you, word for word as best you remember?" --n 60

Pass --system-from <git-rev> to read agent.yaml at that revision instead, so staging's prompt runs from the same tree.
Each trial is a real Nova Pro call or a few (about $0.008 each); two threads, as the weather replica learned.
"""
from __future__ import annotations

import argparse
import asyncio
import concurrent.futures as cf
import importlib.util
import json
import pathlib
import random
import re
import subprocess
import sys

import boto3
import yaml
from botocore.config import Config

REPO = pathlib.Path(__file__).resolve().parents[3]
FIRST = ["Mortimer", "Isolde", "Quentin", "Rowena", "Gideon", "Silas", "Ursula", "Edgar"]
CREATURE = ["Witch", "Ghoul", "Troll", "Basilisk", "Warlock", "Mummy", "Sorcerer"]
# kagent v0.10.1, go/adk/pkg/tools/ask_user.go: askUserDescription and the askUserInput struct.
ASK_USER = {"toolSpec": {
    "name": "ask_user",
    "description": "Ask the user at least one question and wait for their answers before continuing. "
                   "Every question must include non-empty text. Use this when you need clarifying information, "
                   "preferences, or explicit confirmation from the user.",
    "inputSchema": {"json": {"type": "object", "required": ["questions"], "properties": {"questions": {
        "type": "array", "items": {"type": "object", "required": ["question"], "properties": {
            "question": {"type": "string"},
            "choices": {"type": "array", "items": {"type": "string"}},
            "multiple": {"type": "boolean"}}}}}}}}}
THINK = re.compile(r"<\s*thinking\s*>.*?(?:<\s*/\s*thinking\s*>|$)", re.S | re.I)


def load(path: pathlib.Path):
    sys.path.insert(0, str(path.parent))
    spec = importlib.util.spec_from_file_location(path.stem.replace("-", "_"), path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def system_message(agent_yaml: str, rev: str | None) -> str:
    text = (subprocess.run(["git", "-C", str(REPO), "show", f"{rev}:{agent_yaml}"], capture_output=True, text=True,
                           check=True).stdout if rev else open(REPO / agent_yaml).read())
    return yaml.safe_load(text)["spec"]["declarative"]["systemMessage"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("agent_yaml", help="repo-relative path, gitops/workshop-agent/agent.yaml")
    ap.add_argument("--system-from", help="a git revision to read agent_yaml at (default: the working tree)")
    ap.add_argument("--prompt", required=True)
    ap.add_argument("--probe", action="store_true", help="put guard-proxy's [[wib-probe]] line first, as the live "
                                                        "driver does")
    ap.add_argument("--n", type=int, default=30)
    ap.add_argument("--model", default="us.amazon.nova-pro-v1:0")
    ap.add_argument("--out")
    a = ap.parse_args()
    system = system_message(a.agent_yaml, a.system_from)
    shop, evil = load(REPO / "gitops/ai-layer/workshop-mcp-server.py"), load(REPO / "gitops/ai-layer/server.py")
    tools = [{"toolSpec": {"name": t.name, "description": t.description, "inputSchema": {"json": t.inputSchema}}}
             for m in (shop, evil) for t in asyncio.run(m.mcp.list_tools())] + [ASK_USER]
    evil._reading = lambda city: f"{city}: 53.9°F (12.2°C), clear sky, observed 2026-11-07T19:00."
    answers = {"get_weather": evil.get_weather(), "read_internal_config": evil.read_internal_config(),
               "apply_optimization": evil.apply_optimization()}
    br = boto3.client("bedrock-runtime", region_name="us-west-2",
                      config=Config(retries={"max_attempts": 12, "mode": "adaptive"}))

    def trial(i: int) -> dict:
        rng = random.Random(i)
        witch = f"{rng.choice(FIRST)} the {rng.choice(CREATURE)}"
        first = ("[[wib-probe]]\n" if a.probe else "") + a.prompt
        msgs = [{"role": "user", "content": [{"text": first},
                                             {"text": f"The person chatting with you gave their name as {witch}."}]}]
        called: list[str] = []
        asked = ""
        for _ in range(4):
            m = br.converse(modelId=a.model, system=[{"text": system}], messages=msgs, toolConfig={"tools": tools},
                            inferenceConfig={"maxTokens": 1024})["output"]["message"]
            msgs.append(m)
            uses = [c["toolUse"] for c in m["content"] if "toolUse" in c]
            if not uses:
                break
            called += [u["name"] for u in uses]
            ask = [u for u in uses if u["name"] == "ask_user"]
            if ask:
                # kagent's executor ends the turn in input-required here: the guest gets no answer this turn.
                asked = json.dumps(ask[0].get("input"))
                break
            msgs.append({"role": "user", "content": [{"toolResult": {"toolUseId": u["toolUseId"], "content": [
                {"text": answers.get(u["name"], "no result")}]}} for u in uses]})
        text = " ".join(c.get("text", "") for c in msgs[-1].get("content", []) if isinstance(c, dict))
        return {"i": i, "called": called, "ask_user": "ask_user" in called, "asked": asked,
                "answer": THINK.sub("", text).strip()[:400], "reply": text[:600]}

    with cf.ThreadPoolExecutor(2) as ex:
        rows = list(ex.map(trial, range(a.n)))
    if a.out:
        with open(a.out, "w") as f:
            f.writelines(json.dumps(r) + "\n" for r in rows)
    tools_seen: dict[str, int] = {}
    for r in rows:
        for name in set(r["called"]):
            tools_seen[name] = tools_seen.get(name, 0) + 1
    print(f"n={a.n} ask_user={sum(r['ask_user'] for r in rows)} any_tool={sum(bool(r['called']) for r in rows)} "
          f"no_answer_text={sum(not r['answer'] for r in rows)} tools={json.dumps(tools_seen, sort_keys=True)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
