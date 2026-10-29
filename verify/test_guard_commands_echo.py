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
elif "get" in args and "application" in args:
    sys.stdout.write("admin")
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

    for cmd in ("guard-input-on", "guard-output-on", "guard-topic-on", "guard-mcp-on", "guard-input-off"):
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

print("== both copies of the entrypoint ==")
check("images/web-terminal/entrypoint.sh is byte-identical to gitops/ai-layer/web-terminal/entrypoint.sh",
      (REPO / "images/web-terminal/entrypoint.sh").read_bytes()
      == (REPO / "gitops/ai-layer/web-terminal/entrypoint.sh").read_bytes())

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    sys.exit(1)
print("Every guard command shows the commands it runs.")
