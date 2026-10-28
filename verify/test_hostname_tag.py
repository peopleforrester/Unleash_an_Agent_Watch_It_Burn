# ABOUTME: Each cluster carries its attendee hostname as the hostname= tag (#602), set from public_host_for, on
# ABOUTME: every apply and destroy of the cluster root. Offline: the dry run stubs terraform/aws.
#
# Why. lab-platform's `labctl harvest` (lab-platform#84) finds the fleet by its project and event tags and reads
# each cluster's attendee hostname from a tag the operator names with --host-tag. It does not derive a host from
# a cluster name. Without the tag it reported every cluster as having no hostname and wrote no pool file. The
# host comes from fleet.sh's public_host_for, the one function routes and ingest already use, so the tag cannot
# name a host the router does not serve for that cluster: attackme.agenticburn.com for the community cluster,
# burritobot-private.agenticburn.com for the presenters' shared cluster, and the two-word name of the slot for an attendee's.
import os, pathlib, re, stat, subprocess, sys, tempfile
REPO = pathlib.Path(__file__).resolve().parents[1]
CLUSTER_TF = (REPO / "infra" / "terraform" / "aws" / "cluster" / "main.tf").read_text()
FLEET = REPO / "infra" / "terraform" / "fleet" / "fleet.sh"
FLEET_SH = FLEET.read_text()
failures = []
def check(n, c):
    print(f"  {'PASS' if c else 'FAIL'}  {n}");  failures.append(n) if not c else None

print("== the cluster root tags every resource with var.hostname ==")
tags = re.search(r"^\s*fleet_tags = \{(.*?)^\s*\}", CLUSTER_TF, re.S | re.M)
check("fleet_tags is found", tags is not None)
check("fleet_tags carries hostname = var.hostname",
      tags is not None and re.search(r"^\s*hostname\s*=\s*var\.hostname\s*$", tags.group(1), re.M) is not None)
check("the provider's default_tags are fleet_tags, so the cluster itself carries it",
      re.search(r"default_tags \{\s*tags = local\.fleet_tags\s*\}", CLUSTER_TF) is not None)
var = re.search(r'variable "hostname" \{(.*?)\n\}', CLUSTER_TF, re.S)
check('the root declares variable "hostname"', var is not None)
check("var.hostname has no default (a cluster built without its host fails instead of being tagged wrong)",
      var is not None and not re.search(r"^\s*default\s*=", var.group(1), re.M))
rx = re.search(r'condition\s*=\s*can\(regex\("(.*?)", var\.hostname\)\)', var.group(1) if var else "")
check("var.hostname is validated by a regex", rx is not None)
host_re = re.compile(rx.group(1).replace("\\\\", "\\")) if rx else None

print("== fleet.sh passes the host public_host_for gives, on apply and destroy ==")
tfvars = re.search(r"local tfvars=\((.*?)\)\n", FLEET_SH, re.S)
check("up_one's tfvars carry -var hostname=${host}", tfvars is not None and '-var "hostname=${host}"' in tfvars.group(1))
check("and ${host} is public_host_for of the cluster", 'local host; host="$(public_host_for "${name}")"' in FLEET_SH)
# Every apply and destroy of the cluster root, continuation lines included: the variable has no default, so one
# that forgets it is a build or a teardown that fails on the night.
lines, cmds = FLEET_SH.splitlines(), []
for i, line in enumerate(lines):
    if line.lstrip().startswith("#") or not re.search(r'terraform -chdir="\$\{CLUSTER_DIR\}" (apply|destroy)\b', line):
        continue
    cmd, j = line, i
    while cmd.rstrip().endswith("\\") and j + 1 < len(lines):
        j += 1; cmd += "\n" + lines[j]
    cmds.append((i + 1, cmd))
check(f"found the cluster root's apply and destroy ({len(cmds)})",
      {m for _, c in cmds for m in re.findall(r'CLUSTER_DIR\}" (apply|destroy)', c)} == {"apply", "destroy"})
bare = [n for n, c in cmds if "hostname=" not in c and '"${tfvars[@]}"' not in c]
check(f"each passes hostname, directly or through tfvars (missing at lines {bare})", not bare)
check("down_one's destroy passes public_host_for of the cluster",
      '-var "hostname=$(public_host_for "${name}")"' in FLEET_SH)
check("the adopt step's imports get the same variables as the apply",
      'adopt_attendee_iam_user "${name}" "${TF_PROFILE:-${WIB_DEFAULT_ACCOUNT}}" -var "event=${WIB_EVENT}" "${tfvars[@]}"'
      in FLEET_SH)

def run_fleet(*args):
    with tempfile.TemporaryDirectory() as d:
        for tool in ("terraform", "aws"):
            p = pathlib.Path(d) / tool
            p.write_text("#!/bin/sh\nexit 0\n"); p.chmod(p.stat().st_mode | stat.S_IEXEC)
        env = dict(os.environ, PATH=f"{d}:{os.environ['PATH']}", WIB_DRY_RUN="1", WIB_STATE_DIR=f"{d}/states",
                   WIB_DOCKERHUB_ENV=f"{d}/none.env")
        r = subprocess.run(["bash", str(FLEET), *args], env=env, capture_output=True, text=True, timeout=180)
        return r.returncode, r.stdout + r.stderr

# The reference table is fleet.sh's own `hosts` verb, which routes, ingest and the ops view all agree with.
rc, out = run_fleet("hosts")
table = dict(l.split("\t")[:2] for l in out.splitlines() if l.count("\t") == 2)
check(f"fleet.sh hosts lists the roster and the attendee grid (rc={rc}, {len(table)} rows)", rc == 0 and len(table) >= 250)
want = {"watch-it-burn-community": "attackme.agenticburn.com",
        "watch-it-burn-private": "burritobot-private.agenticburn.com"}
check("the roster's hosts are attackme and burritobot-private", all(table.get(k) == v for k, v in want.items()))
bad = [h for h in table.values() if host_re is None or not host_re.fullmatch(h)]
check(f"every host the fleet assigns passes var.hostname's validation ({len(bad)} do not: {bad[:3]})", not bad)
rejected = ["https://attackme.agenticburn.com", "Attackme.agenticburn.com", "attackme", "", "soot-.agenticburn.com"]
check("and the validation refuses a scheme, capitals, a bare label, empty and a dangling hyphen",
      host_re is not None and not any(host_re.fullmatch(h) for h in rejected))

def dry_lines(out):
    return dict(re.findall(r"DRY-RUN (\S+): apply .*?-var hostname=(\S+)", out))
rc, out = run_fleet("up", "watch-it-burn-attendee-001", "watch-it-burn-attendee-007", "watch-it-burn-attendee-042")
got = dry_lines(out)
check(f"WIB_DRY_RUN fleet.sh up of three attendees exits 0 and shows a hostname for each (rc={rc}, {got})",
      rc == 0 and len(got) == 3)
check("each attendee's hostname is its two-word name from the slot grid",
      got and all(table.get(k) == v and re.fullmatch(r"[a-z]+-[a-z]+\.agenticburn\.com", v) for k, v in got.items()))
rc, out = run_fleet("instructors", "up", "all")
got = dry_lines(out)
check(f"WIB_DRY_RUN fleet.sh instructors up all exits 0 and tags the roster with its hosts (rc={rc}, {got})",
      rc == 0 and got == want)

if failures:
    print(f"\nFAILED: {len(failures)} check(s)"); sys.exit(1)
print("\nAll hostname-tag checks passed.")
