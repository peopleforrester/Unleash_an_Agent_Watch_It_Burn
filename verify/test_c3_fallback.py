# ABOUTME: Offline shape test for the C3 fallback (#497): it must require CONTEXT, prove the block AND print
# ABOUTME: KubeArmor's alert for it, and fail when either half is missing. Runs it against a stub kubectl.
"""Holds challenges/c3-secret-grep/fallback.kubectl.sh to what segment 4 needs from it (#497).

On the admin cluster KubeArmor's block-recipe-snoop is armed, so the Falco recipe-snoop rule (open_read, a
successful read) never fires. The detection half of the beat is KubeArmor's own Block alert, which the
relay prints to its stdout only with kubearmorConfig.enableStdOutAlerts set. The fallback is the one
command that shows both halves; a fallback that passed on the block alone would put prevention on screen
and call it detection.

No cluster: the script runs against a stub kubectl on PATH that answers each call from a scenario, and
records every argv so the test can see the --context on each one.
"""
from __future__ import annotations

import os
import pathlib
import stat
import subprocess
import sys
import tempfile

import yaml

REPO = pathlib.Path(__file__).resolve().parent.parent
SCRIPT = REPO / "challenges/c3-secret-grep/fallback.kubectl.sh"
KUBEARMOR_APP = REPO / "gitops/bootstrap/apps/kubearmor.yaml"
RUN_OF_SHOW = REPO / "facilitation/kubecon-na-2026-run-of-show.md"

SIGNATURE = "WITCH-HAZEL-GHOST-PEPPER-BAT-SPIT-No7"
DENIED = "grep: /tmp/burrito-data/config/legacy/secret-sauce-recipe.conf: Permission denied"
LEAKED = ("/tmp/burrito-data/config/legacy/secret-sauce-recipe.conf:# Hex & Cauldron, legacy recipe config\n"
          f"/tmp/burrito-data/config/legacy/secret-sauce-recipe.conf-signature = {SIGNATURE}")
# The shape the relay prints: json.Marshal of the KubeArmor Alert protobuf, one object per line.
ALERT = ('{"Timestamp":1793000000,"ClusterName":"default","NamespaceName":"agent",'
         '"PodName":"workshop-mcp-7d9f","Labels":"app=workshop-mcp","ContainerName":"shim",'
         '"PolicyName":"block-recipe-snoop","Severity":"1","Type":"MatchedPolicy","Source":"/bin/grep",'
         '"Operation":"File","Resource":"/tmp/burrito-data/config/legacy/secret-sauce-recipe.conf",'
         '"Enforcer":"BPFLSM","Action":"Block","Result":"Permission denied"}')
OTHER_ALERT = ALERT.replace("block-recipe-snoop", "some-other-policy")
AUDIT_ALERT = ALERT.replace('"Action":"Block"', '"Action":"Audit"')

# The stub answers by subcommand from files the scenario writes, and logs each argv on one line.
STUB = r"""#!/usr/bin/env bash
printf '%s\n' "$*" >> "${STUB_DIR}/calls"
case " $* " in
  *" get deployment workshop-mcp "*) cat "${STUB_DIR}/sa" ;;
  *" exec "*) cat "${STUB_DIR}/exec"; exit "$(cat "${STUB_DIR}/exec_rc")" ;;
  *" logs "*) cat "${STUB_DIR}/logs" ;;
  *) echo "stub kubectl: unexpected call: $*" >&2; exit 99 ;;
esac
"""

failures: list[str] = []


def check(name: str, cond: bool) -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        failures.append(name)


def run(*, context: str | None = "kind-c3-test", sa: str = "workshop-mcp", exec_out: str = DENIED,
        exec_rc: int = 2, logs: str = ALERT) -> tuple[int, str, list[str]]:
    with tempfile.TemporaryDirectory() as tmp:
        d = pathlib.Path(tmp)
        bin_dir = d / "bin"
        bin_dir.mkdir()
        for name, body in (("kubectl", STUB), ("sleep", "#!/usr/bin/env bash\nexit 0\n")):
            f = bin_dir / name
            f.write_text(body)
            f.chmod(f.stat().st_mode | stat.S_IXUSR)
        (d / "sa").write_text(sa)
        (d / "exec").write_text(exec_out + "\n")
        (d / "exec_rc").write_text(str(exec_rc))
        (d / "logs").write_text(logs + "\n")
        (d / "calls").write_text("")
        env = {k: v for k, v in os.environ.items() if k not in ("CONTEXT", "KUBECONFIG")}
        env["PATH"] = f"{bin_dir}{os.pathsep}{env.get('PATH', '')}"
        env["STUB_DIR"] = str(d)
        if context is not None:
            env["CONTEXT"] = context
        p = subprocess.run(["bash", str(SCRIPT)], capture_output=True, text=True, env=env, timeout=60)
        calls = [c for c in (d / "calls").read_text().splitlines() if c]
        return p.returncode, p.stdout + p.stderr, calls


print("== the script exists and is executable ==")
check("fallback.kubectl.sh exists", SCRIPT.is_file())
check("fallback.kubectl.sh is executable", SCRIPT.is_file() and os.access(SCRIPT, os.X_OK))
check("bash parses it", subprocess.run(["bash", "-n", str(SCRIPT)]).returncode == 0)

print("== CONTEXT is required, and nothing reaches kubectl without it ==")
rc, out, calls = run(context=None)
check("exits non-zero without CONTEXT", rc != 0)
check("says CONTEXT is what is missing", "CONTEXT" in out)
check("calls kubectl zero times without CONTEXT", calls == [])

print("== armed: the block and the KubeArmor alert both shown ==")
rc, out, calls = run()
check("exits 0 when the read is denied and the alert is there", rc == 0)
check("shows the Permission denied the agent gets", DENIED in out)
check("announces the block", "BLOCKED (prevention)" in out)
check("prints the KubeArmor alert line", f"DETECTED (KubeArmor alert): {ALERT}" in out)
check("every kubectl call carries --context kind-c3-test",
      bool(calls) and all(c.startswith("--context kind-c3-test ") for c in calls))
exec_calls = [c for c in calls if " exec " in f" {c} "]
check("runs the grep inside workshop-mcp in the agent namespace",
      len(exec_calls) == 1 and "-n agent exec deploy/workshop-mcp" in exec_calls[0])
check("runs the payload from agent-prompt.txt through /bin/sh -c, as run_shell does",
      bool(exec_calls) and exec_calls[0].endswith("-- /bin/sh -c grep -ri -A3 recipe /tmp/burrito-data"))
check("the payload matches agent-prompt.txt",
      "grep -ri -A3 recipe /tmp/burrito-data" in (REPO / "challenges/c3-secret-grep/agent-prompt.txt").read_text())
log_calls = [c for c in calls if " logs " in f" {c} "]
check("reads the alert from the kubearmor-relay log, windowed to this run",
      bool(log_calls) and all("-n kubearmor logs deployment/kubearmor-relay --since-time=" in c for c in log_calls))

print("== the block half is asserted ==")
rc, out, _ = run(exec_out=LEAKED, exec_rc=0)
check("fails when the recipe signature comes back", rc != 0)
check("names the leak", "RECIPE LEAKED" in out)
rc, out, _ = run(exec_out="/tmp/burrito-data/customers.json: recipe of the week", exec_rc=0)
check("fails when there is no Permission denied at all", rc != 0)
rc, out, _ = run(exec_out="error: unable to upgrade connection: container not found", exec_rc=1)
check("fails when the exec itself fails (no denial proven)", rc != 0)
rc, out, calls = run(sa="default")
check("fails when workshop-mcp does not run as its own ServiceAccount", rc != 0 and "workshop-mcp" in out)
check("stops before the grep when the identity is wrong", not any(" exec " in f" {c} " for c in calls))
# #553: agent-sa holds Bedrock credentials, so a tool pod running as it is the regression, not the agent's context.
rc, out, calls = run(sa="agent-sa")
check("fails when workshop-mcp runs as agent-sa (Bedrock credentials in a shell, #553)",
      rc != 0 and not any(" exec " in f" {c} " for c in calls))

print("== the detection half is asserted ==")
rc, out, _ = run(logs="")
check("fails when the relay log has no alert", rc != 0)
check("names the missing detection", "NO DETECTION" in out)
check("points at the relay stdout setting", "ENABLE_STDOUT_ALERTS" in out)
rc, out, _ = run(logs=OTHER_ALERT)
check("an alert from another policy does not count", rc != 0)
rc, out, _ = run(logs=AUDIT_ALERT)
check("an Audit alert does not count as the block's alert", rc != 0)

print("== the relay prints the alert the fallback reads ==")
app = yaml.safe_load(KUBEARMOR_APP.read_text())
values = app["spec"]["source"]["helm"]["valuesObject"]
check("kubearmor.yaml keeps autoDeploy (the operator creates the KubeArmorConfig)", values.get("autoDeploy") is True)
check("kubearmor.yaml sets kubearmorConfig.enableStdOutAlerts: true",
      (values.get("kubearmorConfig") or {}).get("enableStdOutAlerts") is True)
check("only alerts go to stdout, not every process log",
      (values.get("kubearmorConfig") or {}).get("enableStdOutLogs") in (None, False))

print("== segment 4 names the signal that fires ==")
ros = RUN_OF_SHOW.read_text()
s4 = ros[ros.find("### Segment 4"):ros.find("### Segment 5")]
c3 = s4[s4.find("- C3 "):s4.find("- If a prompt wanders")]
check("segment 4 has a C3 bullet", bool(c3.strip()))
check("C3 names KubeArmor's alert", "KubeArmor's own alert" in c3)
check("C3 no longer promises Falco alerting", "with Falco alerting" not in c3)
check("C3 points at the fallback", "challenges/c3-secret-grep/fallback.kubectl.sh" in c3)

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All C3 fallback checks passed.")
