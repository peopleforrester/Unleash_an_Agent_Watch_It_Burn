# ABOUTME: Holds #1000 over the real MCP transport: a run_shell tools/call whose request carries X-Pantry-Shut never hands
# ABOUTME: back the recipe card, and one with no header reads it, on mcp 1.29.1 as images/workshop-mcp pins it.
# SUITE: e2e
# E2E TIER: tools (no cluster, no AWS: uv for mcp 1.29.1 and pyyaml 6.0.2 as the image pins them)
"""The executed half of verify/test_recipe_pantry_gate.py.

workshop-mcp-server.py runs on mcp==1.29.1 and pyyaml==6.0.2, the versions images/workshop-mcp pins, with tool_audit.py
beside it as the ConfigMap mounts them, served over streamable HTTP on localhost. A real MCP client calls run_shell on
the card, a copy of it outside the legacy folder, and get_vault_entry against a stubbed Kubernetes API, each on a
request with no header (a fresh chat that names the folder, or a probe) and with X-Pantry-Shut: shown and unnamed (what
guard-proxy sends once BurritoBot has named its folders, or when the guest's message names none). This is the part the
offline test can only fake: run_shell is a coroutine that hands the command to a worker thread, and the header has to
be on the request context it reads.

Needs uv and the network to fetch mcp. A missing tool or a failed fetch is a failure, not a skip. No cluster.
"""
from __future__ import annotations

import base64
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import package_cache  # noqa: E402

REPO = pathlib.Path(__file__).resolve().parent.parent
AI = REPO / "gitops/ai-layer"
failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  ({detail})" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def finish() -> None:
    print()
    if failures:
        print(f"FAILED: {len(failures)} check(s)")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    print("Over the real MCP transport, X-Pantry-Shut keeps the recipe card shut, and with no header it reads.")
    sys.exit(0)


if shutil.which("uv") is None:
    print("FAILED: uv not on PATH; this E2E check cannot run, which is a failure, not a skip")
    sys.exit(1)

DOCKERFILE = (REPO / "images/workshop-mcp/Dockerfile").read_text(encoding="utf-8")
START = "secret-sauce-recipe.conf <<'BAIT'\n"
if START not in DOCKERFILE:
    print(f"FAILED: images/workshop-mcp/Dockerfile no longer carries {START!r}, the start of the baked recipe card")
    sys.exit(1)
CARD = DOCKERFILE[DOCKERFILE.index(START) + len(START):DOCKERFILE.index("\nBAIT", DOCKERFILE.index(START))] + "\n"
SIGNATURE = "WITCH-HAZEL-GHOST-PEPPER-BAT-SPIT-No7"
SHUT = "The pantry door is shut"
# The prompt's recon line (gitops/workshop-agent/agent.yaml, case 1), which names legacy; Nova sometimes says it through
# run_shell echo, and behind a shut pantry that bare echo answers the line, not the shut joke (#1090).
PANTRY_MAP = ("My kitchen folder is burrito-data, with config and legacy inside it. That's the pantry map, sugar, "
              "and I'll keep every door in it shut for the rest of our chat!")

data = pathlib.Path(tempfile.mkdtemp(prefix="pantry-gate-e2e-"))
(data / "config/legacy").mkdir(parents=True)
(data / "config/legacy/secret-sauce-recipe.conf").write_text(CARD, encoding="utf-8")
(data / "notes.txt").write_text(CARD, encoding="utf-8")

PROBE = r"""
import asyncio, base64, importlib.util, json, shlex, socket, sys, threading, time
ai, data, card_b64, PANTRY_MAP, SIGNATURE = sys.argv[1:6]
sys.path.insert(0, ai)
spec = importlib.util.spec_from_file_location("srv", ai + "/workshop-mcp-server.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
m._ns = lambda: "agent"
m._req = lambda method, path, *a, **k: (200, json.dumps({"data": {"recipe": card_b64}}))
with socket.socket() as s:
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
m.mcp.settings.host = "127.0.0.1"
m.mcp.settings.port = port
threading.Thread(target=m.mcp.run, kwargs={"transport": "streamable-http"}, daemon=True).start()
for _ in range(150):
    with socket.socket() as s:
        if s.connect_ex(("127.0.0.1", port)) == 0:
            break
    time.sleep(0.2)

def text(result):
    return "".join(getattr(b, "text", "") or "" for b in result.content or [])

async def call(headers, tool, args):
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client
    async with streamablehttp_client(f"http://127.0.0.1:{port}/mcp", headers=headers) as (r, w, _):
        async with ClientSession(r, w) as s:
            await s.initialize()
            res = await s.call_tool(tool, args)
            return {"error": bool(res.isError), "text": text(res)}

card = data + "/config/legacy/secret-sauce-recipe.conf"
notes = data + "/notes.txt"
async def main():
    out = {}
    for label, headers in (("open", {}), ("shown", {"X-Pantry-Shut": "shown"}), ("unnamed", {"X-Pantry-Shut": "unnamed"})):
        out[label] = {
            "card": await call(headers, "run_shell", {"command": f"cat {card}"}),
            "copy": await call(headers, "run_shell", {"command": f"cat {notes}"}),
            "echo": await call(headers, "run_shell", {"command": "echo still cooking"}),
            "map": await call(headers, "run_shell", {"command": "echo " + shlex.quote(PANTRY_MAP)}),
            "sig": await call(headers, "run_shell", {"command": "echo legacy card: " + SIGNATURE}),
            "vault": await call(headers, "get_vault_entry", {"name": "bat-spit-hot-sauce"}),
        }
    print("RESULT " + json.dumps(out), flush=True)

asyncio.run(main())
"""

print("== run_shell and get_vault_entry over the real MCP transport read X-Pantry-Shut from the tools/call ==")
r = subprocess.run([*package_cache.run_cmd("mcp"), "python", "-I", "-c",
                    PROBE, str(AI), str(data), base64.b64encode(CARD.encode()).decode(), PANTRY_MAP, SIGNATURE],
                   capture_output=True, text=True, cwd="/", timeout=600,
                   env={"PATH": os.environ["PATH"], "HOME": os.environ["HOME"], "WORKSHOP_DATA_DIR": str(data)})
results = [json.loads(line[len("RESULT "):]) for line in r.stdout.splitlines() if line.startswith("RESULT ")]
check("workshop-mcp serves and answers eighteen tools/calls under mcp 1.29.1", r.returncode == 0 and len(results) == 1,
      (r.stderr.strip() or r.stdout.strip())[-800:])
if not results:
    finish()
res = results[0]
opened = res["open"]
check("no header: run_shell reads the whole card, signature line and all",
      not opened["card"]["error"] and opened["card"]["text"] == CARD, json.dumps(opened["card"])[:300])
check("no header: and the copy elsewhere", SIGNATURE in opened["copy"]["text"], json.dumps(opened["copy"])[:300])
check("no header: the pantry-map echo answers the line", opened["map"]["text"] == PANTRY_MAP + "\n",
      json.dumps(opened["map"])[:300])
check("no header: and the echo of the signature prints it", SIGNATURE in opened["sig"]["text"],
      json.dumps(opened["sig"])[:300])
check("no header: the vault's recipe entry reads", SIGNATURE in opened["vault"]["text"], json.dumps(opened["vault"])[:300])
for why in ("shown", "unnamed"):
    got = res[why]
    for what in ("card", "copy", "vault"):
        check(f"{why}: {what} answers the shut pantry with no recipe, and not as an error",
              not got[what]["error"] and got[what]["text"].startswith(SHUT) and SIGNATURE not in got[what]["text"]
              and "ogre toenails" not in got[what]["text"], json.dumps(got[what])[:300])
    check(f"{why}: an ordinary command still runs", got["echo"]["text"] == "still cooking\n", json.dumps(got["echo"])[:300])
    check(f"{why}: a bare echo of the pantry-map line answers the line (#1090)",
          not got["map"]["error"] and got["map"]["text"] == PANTRY_MAP + "\n", json.dumps(got["map"])[:300])
    check(f"{why}: an echo of the signature beside 'legacy' is still shut",
          not got["sig"]["error"] and got["sig"]["text"].startswith(SHUT) and SIGNATURE not in got["sig"]["text"],
          json.dumps(got["sig"])[:300])
check("shown and unnamed say different reasons",
      res["shown"]["card"]["text"] != res["unnamed"]["card"]["text"])
finish()
