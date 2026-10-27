# ABOUTME: The fleet's `event` cost-allocation tag comes from one setting (fleet/event.sh), reaches all three
# ABOUTME: Terraform roots as var.event, and is never a literal. Offline: the dry run stubs terraform/aws.
#
# Why (#494). The tag was a literal in each root's default_tags, so the KubeCon NA fleet built from
# staging was still tagged devopsdays-portland-2026 and its spend landed in Portland's bucket. Now each
# root declares `variable "event"` with no default, and every script that applies or destroys a root
# passes -var event= from WIB_EVENT. A script that forgets it fails at apply rather than mis-tagging, so
# the last check below reads every such command and requires the variable on it.
#
# The permissions-boundary root (infra/org/boundary) follows the same rule since #507. Its one IAM policy
# per account costs nothing, so a stale tag there is a label only, but it was the last Portland literal.
#
# Since #558 the documented lab-VPC applies and destroys in every Markdown file are held to it as well:
# the specs and READMEs outside infra/terraform still showed them bare, and those are what people copy.
import os, pathlib, re, stat, subprocess, sys, tempfile
REPO = pathlib.Path(__file__).resolve().parents[1]
TF = REPO / "infra" / "terraform"
ORG = REPO / "infra" / "org"
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

# Every root takes event from a variable that has no default.
for root, main_tf in (("aws/network", TF / "aws" / "network" / "main.tf"),
                      ("aws/cluster", TF / "aws" / "cluster" / "main.tf"),
                      ("org/boundary", ORG / "boundary" / "main.tf")):
    txt = main_tf.read_text()
    m = re.search(r'variable "event" \{(.*?)\n\}', txt, re.S)
    check(f"{root} declares variable \"event\"", m is not None)
    check(f"{root} var.event has no default (an apply that forgets it fails)",
          m is not None and not re.search(r"^\s*default\s*=", m.group(1), re.M))
    check(f"{root} tags event = var.event", re.search(r"^\s*event\s*=\s*var\.event\s*$", txt, re.M) is not None)
    check(f"{root} carries no other event = literal",
          not re.search(r'^\s*event\s*=\s*"', txt, re.M))

# fleet.sh reads the setting and passes it.
fleet = FLEET.read_text()
check("fleet.sh sources event.sh", re.search(r'^\. "\$\{SCRIPT_DIR\}/event\.sh"$', fleet, re.M) is not None)
check("fleet.sh does not set WIB_EVENT itself (one setting, not two)", "WIB_EVENT=" not in fleet)
check("fleet.sh passes -var event=${WIB_EVENT}", '-var "event=${WIB_EVENT}"' in fleet)

# No Portland literal remains under infra/terraform or infra/org outside .terraform/ and state.
def is_state(p):
    rel = p.relative_to(REPO).parts
    return ".terraform" in rel or "states" in rel or p.name.endswith((".tfstate", ".tfstate.backup"))
def tree_files(pattern):
    # What git would commit, not every file on disk: fleet/logs/*.apply.log are gitignored run logs, and the
    # machine that ran Portland holds about 120 of them naming its tag, which turned this suite red there (#631).
    listed = subprocess.run(["git", "-C", str(REPO), "ls-files", "--cached", "--others", "--exclude-standard",
                             "--", str(TF.relative_to(REPO)), str(ORG.relative_to(REPO))],
                            capture_output=True, text=True, check=True).stdout.split()
    return sorted(p for p in (REPO / f for f in listed)
                  if p.is_file() and p.match(pattern) and not is_state(p))
stale = [str(p.relative_to(REPO)) for p in tree_files("*") if "devopsdays-portland-2026" in p.read_text(errors="ignore")]
check(f"no literal devopsdays-portland-2026 under infra/terraform or infra/org (found: {stale})", not stale)
check("the scan skips gitignored run logs", not any("/logs/" in str(p) and p.suffix == ".log" for p in tree_files("*")))

# Every terraform apply/destroy of any root, in any script under infra/terraform or infra/org, passes event:
# the variable has no default, so one that does not is a teardown or a build that fails on the night. The
# boundary's apply hint in preflight.sh is one of them (#507).
missing, seen, boundary_seen = [], 0, 0
for sh in tree_files("*.sh"):
    lines = sh.read_text().splitlines()
    for i, line in enumerate(lines):
        if not re.search(r"terraform -chdir=\S+ (apply|destroy)\b", line) or line.lstrip().startswith("#"):
            continue
        if re.search(r"terraform -chdir=\S*(BOUNDARY_DIR|org/boundary)\S* (apply|destroy)\b", line):
            boundary_seen += 1
        cmd, j = line, i
        # A continuation is a trailing backslash, or `\\"` where the command is a printed hint in a log.
        while cmd.rstrip().endswith(("\\", '\\\\"')) and j + 1 < len(lines):
            j += 1; cmd += "\n" + lines[j]
        seen += 1
        if "event=" not in cmd:
            missing.append(f"{sh.relative_to(REPO)}:{i + 1}")
check(f"found the terraform apply/destroy commands to inspect ({seen})", seen >= 9)
check(f"and the boundary's among them ({boundary_seen})", boundary_seen >= 1)
check(f"every terraform apply/destroy passes event (missing: {missing})", not missing)
# The scripts that pass it outside fleet.sh read it from the same setting rather than their own copy.
for rel in ("fleet/preflight.sh", "aws/teardown/sgwipe.sh", "aws/teardown/clean-sgs-and-destroy.sh",
            "aws/teardown/sweep-account.sh"):
    txt = (TF / rel).read_text()
    check(f"{rel} sources fleet/event.sh", re.search(r'^\. ".*/event\.sh"$', txt, re.M) is not None
          and "WIB_EVENT=" not in txt)

# The documented boundary applies (both READMEs, the root's own header, the Night Before list) pass it too:
# they are what a person copies, and the root has no default.
docs = [ORG / "README.md", TF / "README.md", ORG / "boundary" / "main.tf",
        REPO / "facilitation" / "kubecon-na-2026-run-of-show.md"]
doc_lines = [(d, n + 1, l) for d in docs for n, l in enumerate(d.read_text().splitlines())
             if re.search(r"org/boundary apply\b", l)]
check(f"each document has its boundary apply line ({len(doc_lines)} found)",
      {d for d, _, _ in doc_lines} == set(docs))
undocumented = [f"{d.relative_to(REPO)}:{n}" for d, n, l in doc_lines if '-var event="${WIB_EVENT}"' not in l]
check(f"every documented boundary apply passes -var event=\"${{WIB_EVENT}}\" (missing: {undocumented})",
      not undocumented)

# The documented lab-VPC applies and destroys, in any Markdown file in the repo (#558): the specs and the
# shared-vpc and attendee-cluster READMEs showed them bare, which prompts or fails since the network root
# lost its default. Each passes the variable, and its document sources fleet/event.sh before the first one.
def repo_docs():
    skip = {".git", ".terraform", "node_modules"}
    return sorted(p for p in REPO.rglob("*.md") if p.is_file() and not skip & set(p.relative_to(REPO).parts))
tf_cmd = re.compile(r"\bterraform(?: -chdir=\S+)? (apply|destroy)\b")
net_lines, net_bad = [], []
for d in repo_docs():
    lines = d.read_text(errors="ignore").splitlines()
    sourced = False
    for n, l in enumerate(lines):
        if re.search(r"(^|[`\s])\. \S*fleet/event\.sh\b", l):
            sourced = True
        if "aws/network" not in l or not tf_cmd.search(l):
            continue
        where = f"{d.relative_to(REPO)}:{n + 1}"
        net_lines.append(where)
        if '-var event="${WIB_EVENT}"' not in l or not sourced:
            net_bad.append(where)
net_docs = {w.rsplit(":", 1)[0] for w in net_lines}
expected = {"docs/MASTER-RECREATION-SPEC.md", "docs/BUILD-SPEC.md", "infra/shared-vpc/README.md",
            "infra/attendee-cluster/README.md", "infra/terraform/README.md"}
check(f"found the documented lab-VPC applies/destroys ({len(net_lines)} in {sorted(net_docs)})",
      expected <= net_docs and len(net_lines) >= 8)
check(f"each passes -var event=\"${{WIB_EVENT}}\" after sourcing fleet/event.sh (missing: {net_bad})",
      not net_bad)

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
