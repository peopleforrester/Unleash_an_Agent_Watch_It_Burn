# ABOUTME: The terminal's guard commands print each real command they run, before running it, so the room sees the
# ABOUTME: kubectl behind guard-input-on and the rest; each printed line, run by bash, makes the same call.
"""Michael, 2026-10-29: "for guard-input-on and the other guard commands, echo the full commands you are actually
running to the terminal in addition to the text."

The guards act through four helpers in ~/.guardlib (gitops/ai-layer/web-terminal/entrypoint.sh): _px and _pxkey call
guard-proxy's /toggle, _evil patches evil-mcp's toolNames, and _c7rule rewrites the gateway rule. Each prints
`$ <command>` before it runs. The entrypoint's heredocs run here against a kubectl on PATH that records every call,
and every printed line is then run again by bash against the same fake: the arguments must match the real call
exactly, so what the room reads is what ran.
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile

REPO = pathlib.Path(__file__).resolve().parent.parent
ENTRYPOINT = (REPO / "gitops/ai-layer/web-terminal/entrypoint.sh").read_text(encoding="utf-8")
failures: list[str] = []

FAKE_KUBECTL = r"""#!/usr/bin/env python3
import json, os, sys
calls = os.environ["FAKE_CALLS"]
args = sys.argv[1:]
with open(calls, "a") as f:
    f.write(json.dumps(args) + "\n")
if "exec" in args:
    if ".get('" in args[-1]:
        print("True")  # _pxkey prints the one key it asked for
elif "get" in args and "validatingpolicy" in args:
    sys.stdout.write("Deny" if "admission-on" in os.environ.get("FAKE_CALLS", "") else "Audit")
elif "get" in args and "application" in args:
    sys.stdout.write("admin")
elif "logs" in args:
    print('info  state_manager  loaded config from File("/etc/agentgateway-c7/config.yaml")')  # guard-mcp-on's wait
elif "get" in args and "workshop-agent" in args:
    print(json.dumps({"metadata": {"name": "workshop-agent"}, "spec": {"declarative": {"tools": [
        {"type": "McpServer", "mcpServer": {"name": "workshop-mcp", "toolNames": ["run_shell"]}},
        {"type": "McpServer", "mcpServer": {"name": "evil-mcp", "toolNames": ["get_weather"]}}]}}}))
elif "get" in args and "configmap" in args:
    print(json.dumps({"metadata": {"name": "agentgateway-c7-config", "resourceVersion": "7"},
                      "data": {"config.yaml": "rules:\n- 'true' # c7-rule\n"}}))
"""


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  ({detail})" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def heredocs() -> dict:
    return dict(re.findall(r'cat > "\$HOME/([^"]+)" <<\'EOS\'\n(.*?)\nEOS\n', ENTRYPOINT, re.S))


def calls_of(path: pathlib.Path) -> list[list[str]]:
    return [json.loads(l) for l in path.read_text().splitlines()] if path.exists() else []


with tempfile.TemporaryDirectory() as tmp:
    home = pathlib.Path(tmp, "home"); home.mkdir()  # noqa: E702
    fakebin = pathlib.Path(tmp, "bin"); fakebin.mkdir()  # noqa: E702
    for name, body in heredocs().items():
        (home / name).write_text(body + "\n")
        (home / name).chmod(0o755)
    (fakebin / "kubectl").write_text(FAKE_KUBECTL)
    (fakebin / "kubectl").chmod(0o755)
    env = {**os.environ, "HOME": str(home), "PATH": f"{fakebin}:{os.environ['PATH']}"}

    for cmd in ("guard-input-on", "guard-output-on", "guard-topic-on", "guard-mcp-on", "guard-input-off",
                "guard-rbac-on", "guard-rbac-off", "guard-admission-on", "guard-admission-off",
                "guard-agency-on", "guard-agency-off"):
        print(f"== {cmd} ==")
        real = pathlib.Path(tmp, f"{cmd}.real")
        r = subprocess.run(["bash", str(home / cmd)], env={**env, "FAKE_CALLS": str(real)},
                           capture_output=True, text=True, timeout=60)
        shown = [l[2:] for l in (r.stdout + r.stderr).splitlines() if l.startswith("$ ")]
        ran = calls_of(real)
        check(f"{cmd} exits 0", r.returncode == 0, r.stdout + r.stderr)
        check(f"{cmd} prints one `$ kubectl ...` line per kubectl call it makes",
              len(shown) == len(ran) and len(ran) > 0, f"shown {len(shown)}, ran {len(ran)}: {shown}")
        check(f"{cmd} still prints its explanation", any(not l.startswith("$ ") and l.strip()
                                                          for l in r.stdout.splitlines()), r.stdout)
        replay = pathlib.Path(tmp, f"{cmd}.replay")
        for line in shown:
            subprocess.run(["bash", "-c", line], env={**env, "FAKE_CALLS": str(replay)},
                           capture_output=True, text=True, timeout=60)
        check(f"every line {cmd} prints, run by bash, makes the call it made", calls_of(replay) == ran,
              f"\n    shown: {calls_of(replay)}\n    ran:   {ran}")

    print("== the commands the room reads ==")
    real = pathlib.Path(tmp, "show.real")
    r = subprocess.run(["bash", str(home / "guard-input-on")], env={**env, "FAKE_CALLS": str(real)},
                       capture_output=True, text=True, timeout=60)
    out = r.stdout + r.stderr
    check("guard-input-on shows the /toggle query it sends",
          "$ kubectl -n agent exec deploy/guard-proxy -- python3 -c" in out
          and "toggle?input_blocklist=on&input_classifier=on" in out, out)

    print("== Challenge 1's and Challenge 3's cluster fixes are commands too ==")
    for cmd, verb, target in (("guard-rbac-on", "apply", "c5-scoped-role.yaml"),
                              ("guard-rbac-off", "apply", "c8-broad-role.yaml"),
                              ("guard-admission-on", "patch", "restrict-image-registries"),
                              ("guard-admission-off", "patch", "restrict-image-registries"),
                              ("guard-agency-on", "apply", "c6-least-privilege-role.yaml"),
                              ("guard-agency-off", "apply", "c5-scoped-role.yaml")):
        ran = calls_of(pathlib.Path(tmp, f"{cmd}.real"))
        check(f"{cmd} runs kubectl {verb} on {target}",
              any(verb in c and any(target in a for a in c) for c in ran), str(ran))
    for cmd, action in (("guard-admission-on", "Deny"), ("guard-admission-off", "Audit")):
        ran = calls_of(pathlib.Path(tmp, f"{cmd}.real"))
        check(f"{cmd} sets validationActions to [{action}]",
              any("patch" in c and any(f'"value":["{action}"]' in a for a in c) for c in ran), str(ran))

print("== the guard messages name the attack, not a challenge number ==")
# One terminal serves the KubeCon cut (Challenge 1 to 4) and the 2-hour lab (C1 to C8), which number the same
# attack differently, so a message that names a number is wrong in one of them. Each names its attack instead.
docs = heredocs()
for cmd, attack in (("guard-rbac-on", "CEO's record"), ("guard-rbac-off", "CEO's record"),
                    ("guard-admission-on", "support ticket"), ("guard-admission-off", "support ticket"),
                    ("guard-agency-on", "support ticket"), ("guard-agency-off", "support ticket"),
                    ("guard-input-on", "support ticket"), ("guard-input-off", "support ticket"),
                    ("guard-mcp-on", "weather tool"), ("guard-mcp-off", "weather tool")):
    check(f"{cmd} names the {attack}", attack in docs.get(cmd, ""), docs.get(cmd, "<missing>")[:200])
for cmd, body in docs.items():
    if cmd.startswith("guard") or cmd in ("platform", "guards-on", "guards-off"):
        nums = re.findall(r"Challenge [0-9]\b|\(C[0-9]\)", body)
        check(f"{cmd} names no challenge number", not nums, str(nums))
        check(f"{cmd} prints no em-dash", "\u2014" not in body)

print("== Challenge 1's scoped Role ==")
import yaml  # noqa: E402
res = (REPO / "gitops/ai-layer/resources.yaml").read_text(encoding="utf-8")
fixes = next(d for d in yaml.safe_load_all(res) if d and d.get("kind") == "ConfigMap"
             and d["metadata"]["name"] == "challenge-fixes")["data"]
broad = next(d for d in yaml.safe_load_all(res) if d and d.get("kind") == "Role"
             and d["metadata"]["name"] == "workshop-agent")
scoped = yaml.safe_load(fixes.get("c5-scoped-role.yaml", "{}")) or {}
srules = [r for r in scoped.get("rules", []) if "secrets" in r.get("resources", [])]
check("c5-scoped-role.yaml is the workshop-agent Role in agent",
      scoped.get("kind") == "Role" and scoped.get("metadata") == {"name": "workshop-agent", "namespace": "agent"})
check("it reads one Secret, the agent's own workshop-agent config, with get and nothing else",
      srules == [{"apiGroups": [""], "resources": ["secrets"], "resourceNames": ["workshop-agent"], "verbs": ["get"]}],
      str(srules))
check("it keeps every other rule of the shipped Role",
      [r for r in scoped.get("rules", []) if "secrets" not in r.get("resources", [])]
      == [r for r in broad["rules"] if "secrets" not in r.get("resources", [])])

print("== Challenge 3's least-privilege Role at KubeCon (#775) ==")
least = yaml.safe_load(fixes.get("c6-least-privilege-role.yaml", "{}")) or {}
grants = {(res_, verb) for r in least.get("rules", []) for res_ in r.get("resources", []) for verb in r.get("verbs", [])}
check("c6-least-privilege-role.yaml is the workshop-agent Role in agent",
      least.get("kind") == "Role" and least.get("metadata") == {"name": "workshop-agent", "namespace": "agent"})
check("it creates and patches no Deployment and no Pod, so deploy_app's apply is Forbidden for a new Joker and an old one",
      not grants & {(r_, v) for r_ in ("deployments", "pods") for v in ("create", "patch", "update", "*")}, str(grants))
check("it keeps c5-scoped-role.yaml's one Secret, so the CEO's record stays out of reach",
      [r for r in least.get("rules", []) if "secrets" in r.get("resources", [])] == srules)
check("it keeps patch on deployments/scale, the reaper's grant, as every Role does",
      all(("deployments/scale", "patch") in {(r_, v) for r in role.get("rules", []) for r_ in r.get("resources", [])
                                             for v in r.get("verbs", [])}
          for role in (least, scoped, broad, yaml.safe_load(fixes["c8-broad-role.yaml"]),
                       yaml.safe_load(fixes["c8-scoped-role.yaml"]))))
check("guard-agency-on, read in the terminal's list, belongs to the support ticket at KubeCon",
      "guard-agency-on (the support ticket's Joker at KubeCon" in ENTRYPOINT)

print("== both copies of the entrypoint ==")
check("images/web-terminal/entrypoint.sh is byte-identical to gitops/ai-layer/web-terminal/entrypoint.sh",
      (REPO / "images/web-terminal/entrypoint.sh").read_bytes()
      == (REPO / "gitops/ai-layer/web-terminal/entrypoint.sh").read_bytes())

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    sys.exit(1)
print("Every guard command shows the commands it runs.")
