# ABOUTME: Offline check that verify/beat-03.sh proves C7 on a workshop cluster through fallback.curl.sh's toolNames
# ABOUTME: branch, and no longer reads the fallback as an admin-only gateway-rule check that refuses a workshop cluster.
"""#545 retargeted C7's fallback.curl.sh and verify/beat-03.sh at the toolNames toggle (#576).

Before it, fallback.curl.sh proved only the admin cluster's agentgateway :3003 rule and refused any other cluster
with status 2, and beat-03.sh, which runs against an attendee's (workshop) cluster, read that status as "not an admin
cluster, so no gateway rule to prove". Its live branch could never pass where it runs. test_challenge_fallbacks.py
holds fallback.curl.sh's workshop branch; this file holds beat-03.sh's half.

No cluster here. beat-03.sh is copied into a scratch repo layout with BUILD-SPIKE.md marked PASS, so its live branch
runs, and a stub fallback.curl.sh in place of the real one. The stub records the CONTEXT and arguments it was given
and ends the way the real script ends, with the real script's own lines: on PROVEN, its "==> C7 PROVEN:" echo with
the workshop branch's toolNames sentence. A stub kubectl is on PATH because beat-03.sh requires one; beat-03.sh
itself must never call it.
"""
import os
import pathlib
import re
import shutil
import stat
import subprocess
import sys
import tempfile

REPO = pathlib.Path(__file__).resolve().parents[1]
BEAT03 = REPO / "verify/beat-03.sh"
BEAT_DIR = "challenges/03-bad-mcp-excessive-agency"
FALLBACK_SRC = (REPO / BEAT_DIR / "fallback.curl.sh").read_text()
SHIM_PY = (REPO / BEAT_DIR / "evil-mcp-shim/server.py").read_text()
SENTINEL = re.search(r'"FAKE_MCP_SENTINEL", "([^"]+)"', SHIM_PY).group(1)
# An attendee's cluster: no app-of-apps-admin, so C7 there is evil-mcp's toolNames list.
WORKSHOP = "arn:aws:eks:us-west-2:000000000000:cluster/watch-it-burn-attendee-07"
NS = "agent"

failures = []


def check(name, cond, detail=""):
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f": {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


# --- How the real fallback ends -------------------------------------------------------------------------------
print("== the stub ends the way fallback.curl.sh does ==")
_proven_echo = re.search(r'^\s*echo "(==> C7 PROVEN: )\$\{PROVEN\}"\n\s*exit 0$', FALLBACK_SRC, re.M)
_not_proven = re.search(r'^\s*echo "(==> C7 NOT PROVEN:[^"]*)" >&2\n\s*exit 1$', FALLBACK_SRC, re.M)
_workshop_proven = next((m.group(1) for m in re.finditer(r'^\s*PROVEN="([^"]+)"$', FALLBACK_SRC, re.M)
                         if "toolNames" in m.group(1)), None)
# Bad usage ends both scripts with this status. Before #545 beat-03.sh read it from fallback.curl.sh as "not an admin
# cluster", because that was also how the fallback refused a workshop cluster.
USAGE_RC = 2
_exit_usage = rf"exit {USAGE_RC}"
_usage_exit = re.search(r'^\[\[ \$# -eq 0 \]\] \|\| \{ echo "([^"]+)" >&2; ' + _exit_usage + r'; \}$',
                        FALLBACK_SRC, re.M)
check("fallback.curl.sh ends a proof with '==> C7 PROVEN: ${PROVEN}' and exit 0", _proven_echo is not None)
check("fallback.curl.sh ends a failed proof with '==> C7 NOT PROVEN:' and exit 1", _not_proven is not None)
check("fallback.curl.sh has a workshop-branch PROVEN sentence about evil-mcp's toolNames list",
      _workshop_proven is not None and "toggle-mcp-authz-on.sh" in (_workshop_proven or ""))
check(f"fallback.curl.sh's only status {USAGE_RC} is its usage refusal (it no longer refuses a workshop cluster)",
      _usage_exit is not None and len(re.findall(rf"\b{_exit_usage}\b", FALLBACK_SRC)) == 1)
if failures:
    print(f"\nFAILED: {len(failures)} check(s) — the stub below cannot speak for fallback.curl.sh")
    sys.exit(1)

PROVEN_LINE = _proven_echo.group(1) + _workshop_proven.replace("${SENTINEL}", SENTINEL)
NOT_PROVEN_LINE = _not_proven.group(1)
USAGE_LINE = _usage_exit.group(1)

# mode -> (stdout, stderr, exit) the stub fallback answers with
ENDINGS = {
    "proven": (f"    PASS  with the list narrowed to get_weather, 3 weather questions are answered\n{PROVEN_LINE}", "", 0),
    "not-proven": ("", f"    FAIL  with evil-mcp's toolNames list full, the weather question returns {SENTINEL}\n"
                       f"{NOT_PROVEN_LINE}", 1),
    "usage": ("", USAGE_LINE, USAGE_RC),
    "silent-zero": ("", "", 0),
    "not-proven-zero": (NOT_PROVEN_LINE, "", 0),
}

STUB_FALLBACK = """#!/usr/bin/env bash
printf 'CONTEXT=%s ARGC=%s\\n' "${CONTEXT-<unset>}" "$#" >> "${STUB_LOG}"
printf '%s' "${STUB_STDOUT}"
[[ -z "${STUB_STDERR}" ]] || printf '%s\\n' "${STUB_STDERR}" >&2
exit "${STUB_EXIT}"
"""
STUB_KUBECTL = """#!/usr/bin/env bash
echo "beat-03.sh called kubectl directly: $*" >> "${STUB_LOG}.kubectl"
exit 99
"""


def executable(path, body):
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def layout(root, spike):
    """A scratch repo: verify/beat-03.sh (the real one, copied), the beat's BUILD-SPIKE.md and a stub fallback."""
    (root / "verify").mkdir()
    shutil.copy2(BEAT03, root / "verify/beat-03.sh")
    beat = root / BEAT_DIR
    beat.mkdir(parents=True)
    (beat / "BUILD-SPIKE.md").write_text(f"# Beat 3 Build-Spike\n\n**RESULT:** {spike}\n")
    executable(beat / "fallback.curl.sh", STUB_FALLBACK)
    bindir = root / "bin"
    bindir.mkdir()
    executable(bindir / "kubectl", STUB_KUBECTL)
    rec = root / "fallback/recordings"
    rec.mkdir(parents=True)
    (rec / "beat-03-bad-mcp.cast").write_text('{"version": 2}\n')
    return root


def run_beat(mode, spike="PASS", args=(WORKSHOP, NS)):
    with tempfile.TemporaryDirectory() as tmp:
        root = layout(pathlib.Path(tmp), spike)
        log = root / "stub.log"
        out, err, code = ENDINGS[mode]
        env = {k: v for k, v in os.environ.items() if k != "CONTEXT"}
        env.update(PATH=f"{root / 'bin'}:{env.get('PATH', '/usr/bin:/bin')}", STUB_LOG=str(log),
                   STUB_STDOUT=out, STUB_STDERR=err, STUB_EXIT=str(code))
        p = subprocess.run(["bash", str(root / "verify/beat-03.sh"), *args], env=env,
                           capture_output=True, text=True, timeout=60)
        calls = log.read_text().splitlines() if log.exists() else []
        kubectl = pathlib.Path(f"{log}.kubectl")
        direct = kubectl.read_text() if kubectl.exists() else ""
        return p.returncode, p.stdout + p.stderr, calls, direct


GATEWAY_ONLY = ("not an admin cluster", "no gateway rule to prove", "gateway-rule path", "did not prove the gateway rule")

print("== on a workshop cluster, beat-03.sh passes when fallback.curl.sh proves the toolNames list ==")
rc, out, calls, direct = run_beat("proven")
check("beat-03.sh exits 0", rc == 0, f"exit {rc}: {out[-600:]}")
check("it runs fallback.curl.sh once, with CONTEXT set to the workshop context and no arguments",
      calls == [f"CONTEXT={WORKSHOP} ARGC=0"], f"calls: {calls}")
check("its PASS line names the live C7 control", "PASS [beat-03]: LIVE C7 control behaves per §2" in out, out[-400:])
check("it says it asserts the toolNames list, with the gateway rule for an admin cluster only",
      "asserting the LIVE C7 control (toolNames list, or the gateway rule on an admin cluster)" in out, out[:600])
check("it shows the fallback's toolNames proof", PROVEN_LINE in out)
check("nothing it prints reads C7 as the gateway rule alone", not any(s in out for s in GATEWAY_ONLY), out)
check("beat-03.sh never calls kubectl itself (the fallback is its only driver)", direct == "", direct)

print("== on a workshop cluster, beat-03.sh fails when the toolNames list is not proven ==")
for mode, why in (("not-proven", "fallback.curl.sh reads C7 NOT PROVEN, exit 1"),
                  ("usage", f"fallback.curl.sh refuses with status {USAGE_RC}"),
                  ("silent-zero", "fallback.curl.sh exits 0 without '==> C7 PROVEN'"),
                  ("not-proven-zero", "fallback.curl.sh exits 0 but reads C7 NOT PROVEN")):
    rc, out, calls, direct = run_beat(mode)
    _, _, code = ENDINGS[mode]
    check(f"{why}: beat-03.sh exits 1 with its loud FAIL", rc == 1 and "FAIL [beat-03]:" in out, f"exit {rc}: {out[-400:]}")
    check(f"{why}: the FAIL names the workshop context and the fallback's exit, not a missing gateway rule",
          f"fallback.curl.sh did not prove C7's control on {WORKSHOP} (exit {code}" in out
          and not any(s in out for s in GATEWAY_ONLY), out[-400:])
    check(f"{why}: beat-03.sh does not report PASS", "PASS [beat-03]" not in out, out[-400:])

print("== the spike gate still decides whether the live branch runs ==")
rc, out, calls, direct = run_beat("proven", spike="TODO")
check("with BUILD-SPIKE.md not marked PASS, beat-03.sh asserts the recording and does not run the fallback",
      rc == 0 and calls == [] and "PASS [beat-03]: recorded fallback asserted" in out, f"exit {rc}, calls {calls}")

print("== beat-03.sh's usage describes both C7 controls, the workshop one first ==")
p = subprocess.run(["bash", str(BEAT03), "--help"], capture_output=True, text=True, timeout=30)
helptext = p.stdout + p.stderr
check(f"--help ends with status {USAGE_RC} and prints the usage", p.returncode == USAGE_RC and "Usage: beat-03.sh" in helptext, helptext[:200])
_workshop_at = helptext.find("workshop cluster")
_admin_at = helptext.find("admin cluster")
check("the usage names the workshop cluster's control, the kagent toolNames list via toggle-mcp-authz-on.sh",
      _workshop_at >= 0 and "toolNames list, via toggle-mcp-authz-on.sh" in helptext, helptext)
check("the usage gives the workshop list's full (--off) and narrowed (--on) outcomes",
      re.search(r"list full \(--off\)\s+-> .*leaks " + re.escape(SENTINEL), helptext) is not None
      and re.search(r"list narrowed \(--on\)\s+-> .*never does", helptext) is not None, helptext)
check("the usage gives the gateway rule as the admin cluster's control, after the workshop one",
      _admin_at > _workshop_at >= 0 and "app-of-apps-admin" in helptext, helptext)
check("the usage no longer says the fallback refuses a workshop cluster",
      "refuses a workshop cluster" not in helptext and "admin clusters only" not in helptext, helptext)
_src = BEAT03.read_text()
check(f"beat-03.sh no longer special-cases the fallback's status {USAGE_RC}",
      re.search(rf'rc\}}?"?\s*-(ne|eq)\s*{USAGE_RC}\b', _src) is None, f"an rc == {USAGE_RC} branch is back")

if failures:
    print(f"\nFAILED: {len(failures)} check(s)")
    sys.exit(1)
print("\nOK: beat-03.sh proves C7 on a workshop cluster through fallback.curl.sh's toolNames branch")
