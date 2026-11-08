# ABOUTME: Offline check that docs/floor.md says how to rebuild the fleet's lost Terraform states and gives the commands
# ABOUTME: that rebuild them on tanjiro-wsl2, the machine the daily drift report runs on (#979, #1045).
"""Offline: python3 and the repo. Nothing runs terraform or reaches AWS.

#979 added "### Rebuilding a lost state" to docs/floor.md: the commands that rebuild accen-dev's boundary and lab VPC
states and the two KubeCon cluster states from AWS with infra/terraform/fleet/import-state.py. The daily drift
report's own subsection names tanjiro-wsl2 as the machine the report runs on and says those states were rebuilt
there with that section. This test holds both: the section is there and names the states, its `terraform init`
loop names each root the script rebuilds, every import-state.py line is one the script's own argument rules accept,
the boundary and lab VPC come before the clusters (a cluster's plan reads both), and the schedule paragraph names
tanjiro-wsl2 with its checkout path and points at the section. Each rule is then broken on a copy of the doc to show
the check fails when the doc stops saying it.
"""
from __future__ import annotations

import importlib.util
import pathlib
import re
import shlex
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
FLOOR = REPO / "docs/floor.md"
SCRIPT = REPO / "infra/terraform/fleet/import-state.py"
SCRIPT_REL = "infra/terraform/fleet/import-state.py"
HEADING = "### Rebuilding a lost state"
SCHEDULE_HEADING = "### The daily drift plan"
MACHINE = "tanjiro-wsl2"
CHECKOUT = "/home/michael/repos/talks/Unleash_an_Agent_Watch_It_Burn"
CLUSTERS = ("watch-it-burn-community", "watch-it-burn-private")
PROFILE = "accen-dev"
WANT = {("boundary", PROFILE, None), ("network", PROFILE, None)} | {("cluster", PROFILE, c) for c in CLUSTERS}
failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  ({detail})" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def load_script():
    spec = importlib.util.spec_from_file_location("import_state", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


MOD = load_script()
SCRIPT_SRC = SCRIPT.read_text(encoding="utf-8")
# The roots the script rebuilds, as the `infra/<r>` paths the doc's init loop names.
ROOT_DIRS = {k: p.resolve().relative_to((REPO / "infra").resolve()).as_posix() for k, p in MOD.ROOTS.items()}


def subsection(doc: str, heading: str) -> str | None:
    m = re.search(rf"^{re.escape(heading)}\n(.*?)(?=^#{{1,3}} |\Z)", doc, re.M | re.S)
    return m.group(1) if m else None


def problems(doc: str) -> list[str]:
    """What the doc no longer says. Empty means it says how to rebuild the states and where."""
    out: list[str] = []
    sec = subsection(doc, HEADING)
    if sec is None:
        return [f"no '{HEADING}' section"]
    flat = " ".join(sec.split())
    for c in CLUSTERS:
        if c not in flat:
            out.append(f"the section does not name {c} among the states it rebuilds")
    if not re.search(r"accen-dev's lab VPC and boundary states|accen-dev's boundary and lab VPC", flat):
        out.append("the section does not name accen-dev's lab VPC and boundary states")
    if "boundary and lab VPC first" not in flat:
        out.append("the section does not say the boundary and lab VPC are rebuilt first")
    fence = re.search(r"^```bash\n(.*?)^```", sec, re.M | re.S)
    if not fence:
        return out + ["the section has no bash block of rebuild commands"]
    lines = [ln.strip() for ln in fence.group(1).splitlines() if ln.strip()]

    init = [ln for ln in lines if "terraform -chdir=infra/$r init" in ln]
    loop = re.fullmatch(r"for r in (.+?); do terraform -chdir=infra/\$r init; done", init[0]) if init else None
    if not loop:
        out.append("no `for r in ...; do terraform -chdir=infra/$r init; done` loop")
    else:
        named = loop.group(1).split()
        if set(named) != set(ROOT_DIRS.values()):
            out.append(f"the init loop names {sorted(named)}, the script rebuilds {sorted(ROOT_DIRS.values())}")
        for r in named:
            if not (REPO / "infra" / r / "main.tf").is_file():
                out.append(f"the init loop's infra/{r} has no main.tf")
        if lines.index(init[0]) > min((i for i, ln in enumerate(lines) if SCRIPT_REL in ln), default=len(lines)):
            out.append("the init loop comes after an import-state.py command")

    calls: list[tuple[str, str, str | None]] = []
    for ln in lines:
        if SCRIPT_REL not in ln:
            continue
        argv = shlex.split(ln)
        if argv[:2] != ["python3", SCRIPT_REL]:
            out.append(f"`{ln}` is not run as `python3 {SCRIPT_REL}` from the checkout's root")
            continue
        pos = [a for a in argv[2:] if not a.startswith("-")]
        opts = [a for a in argv[2:] if a.startswith("-")]
        for o in opts:
            if f'"{o}"' not in SCRIPT_SRC:
                out.append(f"`{ln}` passes {o}, which import-state.py does not take")
        if not 2 <= len(pos) <= 3 or pos[0] not in MOD.ROOTS:
            out.append(f"`{ln}` is not `<{'|'.join(sorted(MOD.ROOTS))}> <profile> [cluster]`")
            continue
        kind, profile, name = pos[0], pos[1], pos[2] if len(pos) == 3 else None
        if (kind == "cluster") != bool(name):   # the script's own rule: a name with `cluster` and only with it
            out.append(f"`{ln}` breaks the script's rule that a cluster name comes with `cluster` and only with it")
        if name and not name.startswith("watch-it-burn-"):
            out.append(f"`{ln}` names {name}, not a watch-it-burn-* cluster")
        calls.append((kind, profile, name))
    missing = sorted(WANT - set(calls), key=str)
    if missing:
        out.append(f"no rebuild command for {missing}")
    kinds = [k for k, _, _ in calls]
    if "cluster" in kinds and any(k in ("boundary", "network") for k in kinds[kinds.index("cluster"):]):
        out.append("a cluster is rebuilt before the boundary or lab VPC its plan reads")

    sched = subsection(doc, SCHEDULE_HEADING)
    if sched is None:
        return out + [f"no '{SCHEDULE_HEADING}' section naming the machine the report runs on"]
    paras = [" ".join(p.split()) for p in re.split(r"\n\s*\n", sched)]
    cron = next((i for i, p in enumerate(paras) if "scheduled-drift.sh" in p and "crontab" in p), None)
    host = next((i for i, p in enumerate(paras) if f"The machine is {MACHINE}" in p), None)
    if cron is None:
        out.append("the daily report's crontab line is gone")
    if host is None:
        out.append(f"the daily report's section does not say `The machine is {MACHINE}`")
    else:
        p = paras[host]
        if cron is not None and host < cron:
            out.append(f"{MACHINE} is named before the crontab line it is the machine for")
        if f"`{CHECKOUT}`" not in p:
            out.append(f"the {MACHINE} paragraph does not give the checkout `{CHECKOUT}` the commands run from")
        if f'"{HEADING.lstrip("# ")}"' not in p:
            out.append(f"the {MACHINE} paragraph does not say its states were rebuilt with \"{HEADING.lstrip('# ')}\"")
        for what in ("boundary", "lab VPC", "both KubeCon cluster states"):
            if what not in p:
                out.append(f"the {MACHINE} paragraph does not say the {what} were rebuilt there")
    return out


def broken(doc: str, old: str, new: str) -> str:
    if old not in doc:
        sys.exit(f"anchor missing: {old!r} is not in {FLOOR.relative_to(REPO)}; the mutation checks edit on it")
    return doc.replace(old, new, 1)


DOC = FLOOR.read_text(encoding="utf-8")

print("docs/floor.md says how to rebuild the lost states, and where:")
found = problems(DOC)
check("the section, its commands and the tanjiro-wsl2 paragraph hold", not found, "; ".join(found))
check("import-state.py rebuilds the three roots the doc's commands name",
      set(ROOT_DIRS) == {"boundary", "network", "cluster"}, f"{ROOT_DIRS}")

print("Each rule fails when the doc stops saying it:")
community = f"python3 {SCRIPT_REL} cluster accen-dev watch-it-burn-community\n"
boundary = f"python3 {SCRIPT_REL} boundary accen-dev\n"
cases = {
    "the section's heading is gone": broken(DOC, HEADING + "\n", "### Rebuilding\n"),
    "a cluster's rebuild command is dropped": broken(DOC, community, ""),
    "a cluster is rebuilt before the boundary": broken(broken(DOC, boundary, ""), community, community + boundary),
    "a command takes a kind the script lacks": broken(DOC, f"{SCRIPT_REL} network accen-dev", f"{SCRIPT_REL} vpc accen-dev"),
    "the boundary command gains a cluster name": broken(DOC, boundary, boundary.replace("accen-dev", "accen-dev watch-it-burn-x")),
    "a command passes a flag the script lacks": broken(DOC, boundary, boundary.replace("accen-dev", "accen-dev --force")),
    "the init loop drops a root": broken(DOC, "for r in org/boundary terraform/aws/network", "for r in terraform/aws/network"),
    "the machine is no longer named": broken(DOC, f"The machine is {MACHINE}", "The machine is the operator's"),
    "the checkout path is dropped": broken(DOC, f"`<repo>` as `{CHECKOUT}`", "`<repo>` as the checkout"),
    "the paragraph no longer points at the section": broken(
        DOC, 'were rebuilt there with "Rebuilding a lost state"', "were rebuilt there"),
}
for name, doc in cases.items():
    got = problems(doc)
    check(name, bool(got), "problems() found nothing")

if failures:
    print(f"\nFAIL: {len(failures)} check(s): " + "; ".join(failures))
    sys.exit(1)
print("\nPASS: docs/floor.md's state rebuild")
