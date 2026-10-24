# ABOUTME: The fleet's `event` cost-allocation tag comes from one setting (fleet/event.sh), reaches both
# ABOUTME: Terraform roots as var.event, and is never a literal. Offline: the dry run stubs terraform/aws.
#
# Why (#494). The tag was a literal in each root's default_tags, so the KubeCon NA fleet built from
# staging was still tagged devopsdays-portland-2026 and its spend landed in Portland's bucket. Now each
# root declares `variable "event"` with no default, and every script that applies or destroys a root
# passes -var event= from WIB_EVENT. A script that forgets it fails at apply rather than mis-tagging, so
# the last check below reads every such command and requires the variable on it.
import os, pathlib, re, stat, subprocess, sys, tempfile
REPO = pathlib.Path(__file__).resolve().parents[1]
TF = REPO / "infra" / "terraform"
EVENT_SH = TF / "fleet" / "event.sh"
FLEET = TF / "fleet" / "fleet.sh"
failures = []
def check(n, c):
    print(f"  {'PASS' if c else 'FAIL'}  {n}");  failures.append(n) if not c else None

# The one setting.
event_sh = EVENT_SH.read_text()
settings = re.findall(r'^WIB_EVENT="\$\{WIB_EVENT:-([^}]*)\}"$', event_sh, re.M)
check("fleet/event.sh sets WIB_EVENT once, overridable from the environment", len(settings) == 1)
check("and its default is the KubeCon NA value (#454)", settings == ["kubecon-na-2026"])

# Both roots take event from a variable that has no default.
for root in ("network", "cluster"):
    txt = (TF / "aws" / root / "main.tf").read_text()
    m = re.search(r'variable "event" \{(.*?)\n\}', txt, re.S)
    check(f"aws/{root} declares variable \"event\"", m is not None)
    check(f"aws/{root} var.event has no default (an apply that forgets it fails)",
          m is not None and not re.search(r"^\s*default\s*=", m.group(1), re.M))
    check(f"aws/{root} tags event = var.event", re.search(r"^\s*event\s*=\s*var\.event\s*$", txt, re.M) is not None)
    check(f"aws/{root} carries no other event = literal",
          not re.search(r'^\s*event\s*=\s*"', txt, re.M))

# fleet.sh reads the setting and passes it.
fleet = FLEET.read_text()
check("fleet.sh sources event.sh", re.search(r'^\. "\$\{SCRIPT_DIR\}/event\.sh"$', fleet, re.M) is not None)
check("fleet.sh does not set WIB_EVENT itself (one setting, not two)", "WIB_EVENT=" not in fleet)
check("fleet.sh passes -var event=${WIB_EVENT}", '-var "event=${WIB_EVENT}"' in fleet)

# No Portland literal remains under infra/terraform outside .terraform/ and state.
def is_state(p):
    rel = p.relative_to(TF).parts
    return ".terraform" in rel or "states" in rel or p.name.endswith((".tfstate", ".tfstate.backup"))
stale = [str(p.relative_to(REPO)) for p in TF.rglob("*")
         if p.is_file() and not is_state(p) and "devopsdays-portland-2026" in p.read_text(errors="ignore")]
check(f"no literal devopsdays-portland-2026 under infra/terraform (found: {stale})", not stale)

# Every terraform apply/destroy of either root, in any script under infra/terraform, passes event: the
# variable has no default, so one that does not is a teardown or a build that fails on the night.
missing, seen = [], 0
for sh in sorted(TF.rglob("*.sh")):
    if is_state(sh):
        continue
    lines = sh.read_text().splitlines()
    for i, line in enumerate(lines):
        if not re.search(r"terraform -chdir=\S+ (apply|destroy)\b", line) or line.lstrip().startswith("#"):
            continue
        cmd, j = line, i
        # A continuation is a trailing backslash, or `\\"` where the command is a printed hint in a log.
        while cmd.rstrip().endswith(("\\", '\\\\"')) and j + 1 < len(lines):
            j += 1; cmd += "\n" + lines[j]
        seen += 1
        if "event=" not in cmd:
            missing.append(f"{sh.relative_to(REPO)}:{i + 1}")
check(f"found the terraform apply/destroy commands to inspect ({seen})", seen >= 8)
check(f"every terraform apply/destroy passes event (missing: {missing})", not missing)
# The scripts that pass it outside fleet.sh read it from the same setting rather than their own copy.
for rel in ("fleet/preflight.sh", "aws/teardown/sgwipe.sh", "aws/teardown/clean-sgs-and-destroy.sh",
            "aws/teardown/sweep-account.sh"):
    txt = (TF / rel).read_text()
    check(f"{rel} sources fleet/event.sh", re.search(r'^\. ".*/event\.sh"$', txt, re.M) is not None
          and "WIB_EVENT=" not in txt)

# The dry run shows the tag each cluster would be built with, and the env override reaches it.
def dry_run(extra_env):
    with tempfile.TemporaryDirectory() as d:
        for tool in ("terraform", "aws"):
            p = pathlib.Path(d) / tool
            p.write_text("#!/bin/sh\nexit 0\n"); p.chmod(p.stat().st_mode | stat.S_IEXEC)
        env = {k: v for k, v in os.environ.items() if k != "WIB_EVENT"}
        env.update(PATH=f"{d}:{env['PATH']}", WIB_DRY_RUN="1", WIB_STATE_DIR=f"{d}/states",
                   WIB_DOCKERHUB_ENV=f"{d}/none.env", **extra_env)
        r = subprocess.run(["bash", str(FLEET), "up", "watch-it-burn-attendee-007"],
                           env=env, capture_output=True, text=True, timeout=120)
        return r.returncode, r.stdout + r.stderr
rc, out = dry_run({})
line = next((l for l in out.splitlines() if "DRY-RUN watch-it-burn-attendee-007" in l), "")
check(f"WIB_DRY_RUN fleet.sh up exits 0 (rc={rc})", rc == 0)
check(f"and shows -var event=kubecon-na-2026 ({line.strip() or out[-300:]})", "-var event=kubecon-na-2026" in line)
rc, out = dry_run({"WIB_EVENT": "next-event-2027"})
check("WIB_EVENT in the environment overrides the setting for one run",
      rc == 0 and "-var event=next-event-2027" in out and "kubecon-na-2026" not in out)

if failures:
    print(f"\nFAILED: {len(failures)} check(s)"); sys.exit(1)
print("\nAll event-tag checks passed.")
