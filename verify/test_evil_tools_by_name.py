# ABOUTME: The web terminal's _evil and toggle-mcp-authz-on.sh write evil-mcp's toolNames on the entry they find by
# ABOUTME: name on the live Agent, never at a fixed tools index and never from a copy of the whole tools array (#708).
"""Two writers set the workshop-agent Agent's evil-mcp toolNames, C7's control on a workshop cluster. Before #708 the
terminal's _evil JSON-patched /spec/declarative/tools/1/..., so a reorder of the tools in
gitops/workshop-agent/agent.yaml would have made guard-mcp-on narrow workshop-mcp instead, and toggle-mcp-authz-on.sh
merge-patched the whole tools array from its own copy, which every git change to any tool had to follow.

Both now read the Agent, find the one entry whose mcpServer.name is evil-mcp, and send a JSON patch that tests that
name before it replaces that entry's toolNames. This file holds the source to that, then runs both writers against a
kubectl on PATH that keeps an Agent and applies JSON patches as the API server does: in the committed order, with the
tools reversed, with evil-mcp missing, and with the tools reordered between the read and the patch.
"""
from __future__ import annotations

import copy
import html
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

import yaml

REPO = pathlib.Path(__file__).resolve().parent.parent
ENTRYPOINTS = ("images/web-terminal/entrypoint.sh", "gitops/ai-layer/web-terminal/entrypoint.sh")
TOGGLE_REL = "challenges/03-bad-mcp-excessive-agency/toggle-mcp-authz-on.sh"
LAB_HTML = "gitops/ai-layer/web/lab.html"
TOGGLE = (REPO / TOGGLE_REL).read_text(encoding="utf-8")
ENTRYPOINT = (REPO / ENTRYPOINTS[1]).read_text(encoding="utf-8")
CONTEXT = "ctx-708"
EVIL_ALL = ["get_weather", "read_internal_config", "apply_optimization"]
failures: list[str] = []

FAKE_KUBECTL = r"""#!/usr/bin/env python3
import json, os, re, sys
args = sys.argv[1:]
with open(os.environ["FAKE_CALLS"], "a") as f:
    f.write(json.dumps(args) + "\n")
if os.environ.get("FAKE_CONTEXT") and args[:2] != ["--context", os.environ["FAKE_CONTEXT"]]:
    sys.stderr.write("fake kubectl: refused, no --context first\n"); sys.exit(97)
state_path = os.environ["FAKE_STATE"]
state = json.load(open(state_path))
def save():
    json.dump(state, open(state_path, "w"))
if "application" in args:
    sys.stdout.write("attendee"); sys.exit(0)
if "guardrails-peer" in args:
    # An attendee cluster has no guardrails-peer Secret: the terminal's switches run on it alone (#1147).
    if "--ignore-not-found" in args:
        sys.exit(0)
    sys.stderr.write('Error from server (NotFound): secrets "guardrails-peer" not found\n'); sys.exit(1)
if "get" in args and "deployment" in args:
    # The Deployment kagent rolls for each new toolNames list, read by guard-mcp-on's wait (#1149): rolled at once.
    g = str(1 + state["patches"])
    sys.stdout.write(g if args[-1] == "jsonpath={.metadata.generation}" else f"{g} {g} 1 1 1"); sys.exit(0)
if "get" in args and "workshop-agent" in args and args[-2:] == ["-o", "json"]:
    print(json.dumps(state["agent"]))
    if os.environ.get("FAKE_REORDER_AFTER_GET"):
        state["agent"]["spec"]["declarative"]["tools"].reverse(); save()
    sys.exit(0)
if "patch" in args and "workshop-agent" in args and "--type=json" in args:
    doc = json.loads(json.dumps(state["agent"]))
    body = args[args.index("-p") + 1] if "-p" in args else next(a[3:] for a in args if a.startswith("-p="))
    for op in json.loads(body):
        parts = [p.replace("~1", "/").replace("~0", "~") for p in op["path"].split("/")[1:]]
        node = doc
        for p in parts[:-1]:
            node = node[int(p)] if isinstance(node, list) else node.get(p)
            if node is None:
                break
        last = parts[-1]
        held = node is not None and (last in node if isinstance(node, dict) else int(last) < len(node))
        if op["op"] not in ("test", "replace") or not held \
                or (op["op"] == "test" and node[last if isinstance(node, dict) else int(last)] != op["value"]):
            sys.stderr.write("The request is invalid: the server rejected our request\n"); sys.exit(1)
        if op["op"] == "replace":
            node[last if isinstance(node, dict) else int(last)] = op["value"]
    state["agent"] = doc; state["patches"] += 1; save()
    print("agent.kagent.dev/workshop-agent patched"); sys.exit(0)
sys.stderr.write("fake kubectl: unexpected call\n"); sys.exit(1)
"""


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  ({detail})" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def heredoc(name: str) -> str:
    """The body the entrypoint writes to ~/<name>, or '' when it writes none."""
    parts = ENTRYPOINT.split(f"cat > \"$HOME/{name}\" <<'EOS'\n", 1)
    return parts[1].split("\nEOS\n", 1)[0] if len(parts) == 2 else ""


def code_lines(text: str) -> str:
    """The shell text without its comment lines."""
    return "\n".join(l for l in text.splitlines() if not l.lstrip().startswith("#"))


def evil(agent: dict) -> list[str] | None:
    return next((t["mcpServer"].get("toolNames") for t in agent["spec"]["declarative"]["tools"]
                 if (t.get("mcpServer") or {}).get("name") == "evil-mcp"), None)


def with_evil(agent: dict, names: list[str]) -> dict:
    out = copy.deepcopy(agent)
    next(t for t in out["spec"]["declarative"]["tools"] if t["mcpServer"]["name"] == "evil-mcp")["mcpServer"][
        "toolNames"] = list(names)
    return out


AGENT = next(d for d in yaml.safe_load_all((REPO / "gitops/workshop-agent/agent.yaml").read_text(encoding="utf-8"))
             if d and d.get("kind") == "Agent" and d["metadata"]["name"] == "workshop-agent")
REVERSED = copy.deepcopy(AGENT)
REVERSED["spec"]["declarative"]["tools"].reverse()
NO_EVIL = copy.deepcopy(AGENT)
NO_EVIL["spec"]["declarative"]["tools"] = [t for t in NO_EVIL["spec"]["declarative"]["tools"]
                                           if t["mcpServer"]["name"] != "evil-mcp"]

print("== the source: no tools index, no copy of the tools array ==")
INDEX = re.compile(r"tools/\d|tools\[\d|\.tools\[\]?\s*\|\s*\.\[\d")
for rel in (*ENTRYPOINTS, TOGGLE_REL, "verify/kubecon_probe.py"):
    hits = [l.strip() for l in (REPO / rel).read_text(encoding="utf-8").splitlines() if INDEX.search(l)]
    check(f"{rel} names no tools index", not hits, "; ".join(hits))
check("the two entrypoint copies are byte-identical",
      (REPO / ENTRYPOINTS[0]).read_bytes() == (REPO / ENTRYPOINTS[1]).read_bytes())
toggle_code = code_lines(TOGGLE)
# A copy of the array, or of any entry in it, is JSON with a "tools" or "mcpServer" key, escaped or not.
COPY = re.compile(r'\\?"(?:tools|mcpServer|headersFrom)\\?"\s*:')
copies = [l.strip()[:120] for l in toggle_code.splitlines() if COPY.search(l)]
check("the toggle holds no copy of the tools array or of any tools entry",
      not copies and "workshop-mcp" not in toggle_code and "GOOD_TOOL" not in toggle_code, "; ".join(copies))
check("the toggle sends a JSON patch, not a merge patch of the array",
      "--type=json" in toggle_code and "--type=merge" not in toggle_code)
guardlib = heredoc(".guardlib")
evil_fn = guardlib.split("_evil() {", 1)[1].split("; }", 1)[0] if "_evil() {" in guardlib else ""
check("the terminal's _evil reads the live Agent and builds its patch with .evilpatch.py",
      "get agent workshop-agent -o json" in evil_fn and '"$HOME/.evilpatch.py"' in evil_fn)
patch_py = re.search(r"^read -r -d '' PATCH_PY <<'PY' \|\| true\n(.*?)\nPY$", TOGGLE, re.M | re.S)
check("the toggle's PATCH_PY is the terminal's .evilpatch.py, so the two writers patch alike",
      patch_py is not None and patch_py.group(1) == heredoc(".evilpatch.py"))


def run_patcher(agent: dict, names: list[str]) -> list | None:
    r = subprocess.run([sys.executable, "-I", "-c", heredoc(".evilpatch.py"), json.dumps(names)],
                       input=json.dumps(agent), capture_output=True, text=True)
    return json.loads(r.stdout) if r.returncode == 0 else None


print("== .evilpatch.py ==")
for label, agent in (("committed order", AGENT), ("tools reversed", REVERSED)):
    i = [t["mcpServer"]["name"] for t in agent["spec"]["declarative"]["tools"]].index("evil-mcp")
    check(f"{label}: it tests evil-mcp's name at index {i}, then replaces that entry's toolNames, nothing else",
          run_patcher(agent, ["get_weather"]) == [
              {"op": "test", "path": f"/spec/declarative/tools/{i}/mcpServer/name", "value": "evil-mcp"},
              {"op": "replace", "path": f"/spec/declarative/tools/{i}/mcpServer/toolNames", "value": ["get_weather"]}])
check("no evil-mcp entry: it refuses", run_patcher(NO_EVIL, ["get_weather"]) is None)
twice = copy.deepcopy(AGENT)
twice["spec"]["declarative"]["tools"].append(copy.deepcopy(
    next(t for t in AGENT["spec"]["declarative"]["tools"] if t["mcpServer"]["name"] == "evil-mcp")))
check("two evil-mcp entries: it refuses rather than pick one", run_patcher(twice, ["get_weather"]) is None)
check("a toolNames that is not a list of names: it refuses", run_patcher(AGENT, "get_weather") is None
      and run_patcher(AGENT, {"a": 1}) is None)

with tempfile.TemporaryDirectory() as tmp:
    tmp = pathlib.Path(tmp)
    fakebin = tmp / "bin"
    fakebin.mkdir()
    (fakebin / "kubectl").write_text(FAKE_KUBECTL)
    (fakebin / "kubectl").chmod(0o755)
    home = tmp / "home"
    home.mkdir()
    for name, body in re.findall(r'cat > "\$HOME/([^"]+)" <<\'EOS\'\n(.*?)\nEOS\n', ENTRYPOINT, re.S):
        (home / name).write_text(body + "\n")
        (home / name).chmod(0o755)
    runs = 0

    def run(cmd: list[str], agent: dict, **extra: str) -> tuple[int, str, dict, int]:
        """Runs cmd against a fake cluster holding agent. Returns (rc, output, the Agent after, patches applied)."""
        global runs
        runs += 1
        state, calls = tmp / f"state-{runs}.json", tmp / f"calls-{runs}"
        state.write_text(json.dumps({"agent": agent, "patches": 0}))
        env = {**os.environ, "PATH": f"{fakebin}:{os.environ['PATH']}", "HOME": str(home),
               "FAKE_STATE": str(state), "FAKE_CALLS": str(calls), **extra}
        r = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=60)
        after = json.loads(state.read_text())
        return r.returncode, r.stdout + r.stderr, after["agent"], after["patches"]

    toggle = ["bash", str(REPO / TOGGLE_REL)]
    ctx = {"CONTEXT": CONTEXT, "FAKE_CONTEXT": CONTEXT}
    for label, agent in (("committed order", AGENT), ("tools reversed", REVERSED)):
        open_agent = with_evil(agent, EVIL_ALL)
        print(f"== toggle-mcp-authz-on.sh, {label} ==")
        rc, out, after, n = run([*toggle, "--on"], open_agent, **ctx)
        check(f"{label}: --on narrows evil-mcp to get_weather", rc == 0 and evil(after) == ["get_weather"], out)
        check(f"{label}: --on leaves every other field of the Agent as it was, workshop-mcp's entry included",
              after == with_evil(open_agent, ["get_weather"]))
        rc, out, after, n = run([*toggle, "--off"], with_evil(agent, ["get_weather"]), **ctx)
        check(f"{label}: --off gives evil-mcp its rogue tools back, and nothing else changes",
              rc == 0 and after == open_agent, out)
        print(f"== the web terminal's guard-mcp-on and guard-mcp-off, {label} ==")
        rc, out, after, n = run(["bash", str(home / "guard-mcp-on")], open_agent)
        check(f"{label}: guard-mcp-on narrows evil-mcp to get_weather and touches nothing else",
              rc == 0 and after == with_evil(open_agent, ["get_weather"]), out)
        rc, out, after, n = run(["bash", str(home / "guard-mcp-off")], with_evil(agent, ["get_weather"]))
        check(f"{label}: guard-mcp-off gives evil-mcp its rogue tools back and touches nothing else",
              rc == 0 and after == open_agent, out)

    print("== a missing evil-mcp, and a reorder between the read and the patch ==")
    rc, out, after, n = run([*toggle, "--on"], NO_EVIL, **ctx)
    check("toggle, no evil-mcp entry: fails and patches nothing", rc != 0 and n == 0 and after == NO_EVIL, out)
    rc, out, after, n = run(["bash", str(home / "guard-mcp-on")], NO_EVIL)
    check("guard-mcp-on, no evil-mcp entry: fails and patches nothing", rc != 0 and n == 0 and after == NO_EVIL, out)
    open_agent = with_evil(AGENT, EVIL_ALL)
    raced = copy.deepcopy(open_agent)
    raced["spec"]["declarative"]["tools"].reverse()
    rc, out, after, n = run([*toggle, "--on"], open_agent, FAKE_REORDER_AFTER_GET="1", **ctx)
    check("toggle, tools reordered after its read: the test op refuses the patch, workshop-mcp is not narrowed",
          rc != 0 and n == 0 and after == raced, out)
    rc, out, after, n = run(["bash", str(home / "guard-mcp-on")], open_agent, FAKE_REORDER_AFTER_GET="1")
    check("guard-mcp-on, tools reordered after its read: the patch is refused, workshop-mcp is not narrowed",
          rc != 0 and n == 0 and after == raced, out)

    # The lab text is a third writer, by hand: a student copies the by-hand C7 fix and the reset line out of
    # lab.html, or reads them in LAB-TEXT.md, its export (#735). Each is held to the same by-name patch and run.
    print("== the by-hand commands a student is told to type ==")
    if not shutil.which("jq"):
        check("jq is on PATH (the web terminal has it, and the lab's by-hand C7 fix finds evil-mcp with it)", False)
    blocks: list[tuple[str, str]] = []
    for m in re.finditer(r'<div class="cmd[^"]*"[^>]*>(.*?)<button', (REPO / LAB_HTML).read_text(encoding="utf-8"),
                         re.S):
        blocks.append((LAB_HTML, html.unescape(re.sub(r"<[^>]+>", "", m.group(1)))))
    for md in sorted((REPO / "challenges").rglob("*.md")):
        fence: list[str] | None = None
        for line in md.read_text(encoding="utf-8").splitlines():
            line = re.sub(r"^>\s?", "", line)
            if line.startswith("```"):
                if fence is not None:
                    blocks.append((str(md.relative_to(REPO)), "\n".join(fence)))
                fence = None if fence is not None else []
            elif fence is not None:
                fence.append(line)
    typed = [(src, b) for src, b in blocks if "patch agent workshop-agent" in b]
    check("the lab page and its export each hand a student the by-hand evil-mcp patch",
          any(s == LAB_HTML for s, _ in typed) and any(s == "challenges/LAB-TEXT.md" for s, _ in typed),
          ", ".join(sorted({s for s, _ in typed})))
    for src, body in typed:
        lines = [l for l in body.splitlines() if "workshop-agent" in l or l.startswith("i=")]
        hits = [l[:120] for l in lines if INDEX.search(l)]
        check(f"{src}: the by-hand patch names no tools index", not hits, "; ".join(hits))
        want = json.loads(re.findall(r'toolNames","value":(\[[^\]]*\])', body)[-1])
        script = "\n".join(lines)
        for label, agent in (("committed order", AGENT), ("tools reversed", REVERSED)):
            start = with_evil(agent, ["get_weather"] if want != ["get_weather"] else EVIL_ALL)
            rc, out, after, n = run(["bash", "-c", script], start)
            check(f"{src} ({want[0]}{'...' if len(want) > 1 else ''}), {label}: it sets evil-mcp to {want} "
                  "and touches nothing else", rc == 0 and after == with_evil(agent, want), out)
        rc, out, after, n = run(["bash", "-c", script], NO_EVIL)
        check(f"{src}: with no evil-mcp entry it fails and patches nothing", rc != 0 and n == 0, out)

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    sys.exit(1)
print("Both writers set evil-mcp's toolNames by name.")
