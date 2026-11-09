# ABOUTME: Offline gate for #1132: guards-on and guards-off send every AI guard through _both, so the terminal's
# ABOUTME: one-command reset reaches this cluster and the KubeCon peer, and each runs every step, then names each that failed.
"""guards-on and guards-off used to set the guard-proxy guards with _px and C7 with _mcp, on this cluster alone. Since
#1132 they run `_both _toggle <query>` and `_both _mcp on|off`, the same steps guard-input-on and guard-mcp-on use, so
the room's public bot is reset too. What _both, _toggle and _mcp do on two clusters is held by
verify/test_guard_switch_both.py, verify/test_guard_input_both.py and verify/test_guard_mcp_both.py; this test holds
that guards-on and guards-off call them, and nothing else:

  * guards-on calls `_both _toggle` once with output, both input stages and budget on, then `_both _mcp on`;
  * guards-off calls `_both _toggle` once with output, both input stages, budget and topic off, then `_both _mcp off`;
  * neither calls _px or _mcp outside _both;
  * a refused toggle still runs C7 after it (#1203), and each refused step is named in the closing line with exit 1;
  * a refused C7 step exits 1 naming guard-mcp-on/off;
  * the images/ twin is byte-identical.

The scripts are run by bash from the entrypoint's own heredocs, with a ~/.guardlib whose _both records its arguments.
"""
from __future__ import annotations

import os
import pathlib
import re
import subprocess
import sys
import tempfile

REPO = pathlib.Path(__file__).resolve().parent.parent
ENTRYPOINT = REPO / "gitops/ai-layer/web-terminal/entrypoint.sh"
TWIN = REPO / "images/web-terminal/entrypoint.sh"

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(("PASS " if ok else "FAIL ") + name + (f"\n     {detail}" if detail and not ok else ""))
    if not ok:
        failures.append(name)


text = ENTRYPOINT.read_text(encoding="utf-8")
scripts = dict(re.findall(r'cat > "\$HOME/([^"]+)" <<\'EOS\'\n(.*?)\nEOS\n', text, re.S))
for name in ("guards-on", "guards-off"):
    if name not in scripts:
        sys.exit(f"ANCHOR MISSING: no `cat > \"$HOME/{name}\"` heredoc in {ENTRYPOINT}")

# A .guardlib whose _both records what it was asked and fails on each step FAIL names (space-separated).
STUB = r'''
_both() { local f; printf '%s\n' "$*" >> "$CALLS"
  for f in $FAIL; do case " $* " in *" $f "*) return 1 ;; esac; done; return 0; }
_px() { printf 'BARE _px %s\n' "$*" >> "$CALLS"; }
_mcp() { printf 'BARE _mcp %s\n' "$*" >> "$CALLS"; }
'''


def run(name: str, fail: str = "none") -> tuple[int, str, list[str]]:
    with tempfile.TemporaryDirectory() as tmp:
        home = pathlib.Path(tmp)
        (home / ".guardlib").write_text(STUB)
        (home / name).write_text(scripts[name] + "\n")
        calls = home / "calls"
        env = {**os.environ, "HOME": str(home), "CALLS": str(calls), "FAIL": fail}
        r = subprocess.run(["bash", str(home / name)], capture_output=True, text=True, env=env, timeout=30)
        got = calls.read_text().splitlines() if calls.exists() else []
        return r.returncode, r.stdout + r.stderr, got


ON_Q = "_toggle output=on&input_blocklist=on&input_classifier=on&budget=on"
OFF_Q = "_toggle output=off&input_blocklist=off&input_classifier=off&budget=off&topic=off"

rc, out, got = run("guards-on")
check("guards-on sends the guard-proxy guards, then C7, through _both, and exits 0",
      rc == 0 and got == [ON_Q, "_mcp on"], f"exit {rc}, calls {got}: {out}")
rc, out, got = run("guards-off")
check("guards-off sends the guard-proxy guards, topic included, then C7, through _both, and exits 0",
      rc == 0 and got == [OFF_Q, "_mcp off"], f"exit {rc}, calls {got}: {out}")
for name in ("guards-on", "guards-off"):
    body = scripts[name]
    bare = [ln for ln in body.splitlines() if re.search(r"(^|[;&|]\s*|if !?\s*)_(px|mcp)\b", ln.strip())]
    check(f"{name} calls neither _px nor _mcp outside _both", not bare, str(bare))

# #1203: a failing first step does not stop the run. The toggle refused, C7 still runs, and the closing line names
# the step that failed, for each script.
for name, query, word, mcp in (("guards-on", ON_Q, "on", "_mcp on"), ("guards-off", OFF_Q, "off", "_mcp off")):
    rc, out, got = run(name, fail="_toggle")
    check(f"a refused guard-proxy toggle still runs {name}'s C7 step after it",
          got == [query, mcp], f"exit {rc}, calls {got}: {out}")
    check(f"{name} exits 1 and names the guard-proxy guards alone when only the toggle was refused",
          rc == 1 and f"{name} ran every step; these did not switch {word}: the guard-proxy guards." in out
          and "the MCP tool restriction did not" not in out, f"exit {rc}: {out}")
    rc, out, got = run(name, fail="_toggle _mcp")
    check(f"{name} with both steps refused runs both and names both",
          rc == 1 and got == [query, mcp]
          and f"these did not switch {word}: the guard-proxy guards, the MCP tool restriction." in out
          and f"guard-mcp-{word}" in out, f"exit {rc}, calls {got}: {out}")
    check(f"{name} does not claim success when a step was refused", "ALL AI guards" not in out, out)
rc, out, got = run("guards-off", fail="_mcp")
check("a refused C7 step makes guards-off exit 1 and name guard-mcp-off",
      rc == 1 and "guard-mcp-off" in out, f"exit {rc}, calls {got}: {out}")
rc, out, got = run("guards-on", fail="_mcp")
check("a refused C7 step makes guards-on exit 1 and name guard-mcp-on",
      rc == 1 and "guard-mcp-on" in out, f"exit {rc}, calls {got}: {out}")

check("images/web-terminal/entrypoint.sh is kept byte-identical", TWIN.read_bytes() == ENTRYPOINT.read_bytes())

# The check can fail: guards-off with its pre-#1203 early exit put back stops before C7, which the check above reads.
early = scripts["guards-off"].replace(
    '  failed="${failed:+$failed, }the guard-proxy guards"\n', '  exit 1\n', 1)
if early == scripts["guards-off"]:
    sys.exit(f"ANCHOR MISSING: guards-off's guard-proxy failure line in {ENTRYPOINT}")
scripts["guards-off-early"] = early
rc, out, got = run("guards-off-early", fail="_toggle")
check("self-check: a guards-off that exits on its first failing step is caught", got == [OFF_Q], f"calls {got}")

# The check can fail: guards-off with its old bare _px line put back.
old = scripts["guards-off"].replace(
    'if ! _both _toggle "output=off&input_blocklist=off&input_classifier=off&budget=off&topic=off"; then',
    '_px "output=off" && _px "input_blocklist=off&input_classifier=off"\nif false; then', 1)
bare_old = [ln for ln in old.splitlines() if re.search(r"(^|[;&|]\s*|if !?\s*)_(px|mcp)\b", ln.strip())]
check("self-check: the pre-#1132 bare _px line is caught", bool(bare_old))

if failures:
    print(f"\n{len(failures)} check(s) failed")
    sys.exit(1)
print("\nguards-on and guards-off send every AI guard through _both (#1132) and run every step (#1203)")
