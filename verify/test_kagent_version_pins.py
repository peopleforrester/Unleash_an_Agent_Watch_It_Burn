# ABOUTME: Every place that names the deployed kagent agrees: the chart gitops/apps/kagent.yaml and kagent-crds.yaml
# ABOUTME: pin, the VERSIONS.lock kagent line, the working docs that state the current version, the manifests' comments,
# ABOUTME: and PRD #13's locked kagent service.version.
#
# Why (#556). 20aee62 (2026-09-10) moved kagent and kagent-crds from 0.9.9 to 0.10.1 and nothing else moved:
# VERSIONS.lock went on recording chart 0.9.9 / app v0.9.9, and the walkthrough, the build spec, the recreation
# spec and the tech status went on calling 0.9.9 current for six weeks. It is the drift #495 and #506 fixed for
# agentgateway, and test_agentgateway_config.py holds that one; this holds kagent the same way.
import pathlib, re, sys

import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
failures = []


def check(n, c, detail=""):
    print(f"  {'PASS' if c else 'FAIL'}  {n}" + (f"\n        {detail}" if (detail and not c) else ""))
    if not c:
        failures.append(n)


def target_revision(rel):
    return str(yaml.safe_load((REPO / rel).read_text(encoding="utf-8"))["spec"]["source"]["targetRevision"])


print("== the controller and its CRDs are one version ==")
chart = target_revision("gitops/apps/kagent.yaml")
crds = target_revision("gitops/apps/kagent-crds.yaml")
check(f"gitops/apps/kagent-crds.yaml pins {chart}, the chart gitops/apps/kagent.yaml deploys (found {crds})",
      crds == chart)

print("== VERSIONS.lock records the chart we deploy ==")
lock_lines = [l for l in (REPO / "VERSIONS.lock").read_text(encoding="utf-8").splitlines() if re.match(r"^kagent\s", l)]
check("VERSIONS.lock has one kagent line", len(lock_lines) == 1, f"{lock_lines}")
lock = lock_lines[0] if lock_lines else ""
c = re.search(r"\bchart (\S+)", lock)
a = re.search(r"\bapp (v\S+)", lock)
check(f"VERSIONS.lock records kagent chart {chart} (found {c.group(1) if c else None})", c is not None and c.group(1) == chart)
# kagent releases the chart and the controller image under one tag, so the app version is the chart's with a v.
check(f"VERSIONS.lock records kagent app v{chart} (found {a.group(1) if a else None})", a is not None and a.group(1) == f"v{chart}")

print("== the working docs name the version we deploy ==")
# Each of these states the deployed kagent. A line may name an older release only beside the deployed one, as
# history ("moved from 0.9.9"). decisions.md, the dated research notes and the PRDs are records and are not checked,
# except prds/13-mvp-walking-skeleton.md, whose locked service.version for kagent is checked in its own section below.
CURRENT_DOCS = (
    "docs/STACK-WALKTHROUGH.md",
    "docs/BUILD-SPEC.md",
    "docs/MASTER-RECREATION-SPEC.md",
    "docs/TECH-STATUS.md",
    "docs/UPGRADE-INVENTORY.md",
)
# The releases these docs have called current before. 0.9.x is the only line kagent has been pinned to besides
# the current one, and no other component in these docs is on a 0.9.x version.
STALE = re.compile(r"\b0\.9\.\d+\b")
for rel in CURRENT_DOCS:
    lines = (REPO / rel).read_text(encoding="utf-8").splitlines()
    check(f"{rel} names kagent {chart}", any("kagent" in l and re.search(rf"\b{re.escape(chart)}\b", l) for l in lines))
    stale = [i for i, l in enumerate(lines, 1) if STALE.search(l) and not re.search(rf"\b{re.escape(chart)}\b", l)]
    check(f"{rel} names 0.9.x only beside {chart} (lines {stale})", not stale)

print("== the manifests' comments name the version we deploy ==")
# #586: these comments went on calling kagent 0.9.9 the chart the cluster runs, and kagent-crds.yaml's
# targetRevision comment went on calling 0.10.1 the "current GA (2026-06" after the pin had moved under it.
# Only the comments are read: a value pinned to some other component's 0.9.x is not a claim about kagent.
COMMENTED_MANIFESTS = ("gitops/ai-layer/resources.yaml", "gitops/apps/kagent-crds.yaml")


def comment(line):
    """The comment on a YAML line, or "": a # that starts the line or follows whitespace, outside quotes."""
    quote = None
    for i, ch in enumerate(line):
        if quote:
            if ch == quote:
                quote = None
        elif ch in "'\"":
            quote = ch
        elif ch == "#" and (i == 0 or line[i - 1].isspace()):
            return line[i:]
    return ""


for rel in COMMENTED_MANIFESTS:
    lines = (REPO / rel).read_text(encoding="utf-8").splitlines()
    stale = [i for i, l in enumerate(lines, 1)
             if STALE.search(comment(l)) and not re.search(rf"\b{re.escape(chart)}\b", comment(l))]
    check(f"{rel} comments name 0.9.x only beside {chart} (lines {stale})", not stale)

crds_lines = [l for l in (REPO / "gitops/apps/kagent-crds.yaml").read_text(encoding="utf-8").splitlines()
              if re.match(r"^\s*targetRevision:", l)]
check("gitops/apps/kagent-crds.yaml has one targetRevision line", len(crds_lines) == 1, f"{crds_lines}")
crds_comment = comment(crds_lines[0]) if crds_lines else ""
# A dated "current GA" goes stale the day kagent ships again; the comment ties the pin to the controller's chart.
check(f"gitops/apps/kagent-crds.yaml targetRevision comment does not call the pin the current GA ({crds_comment!r})",
      not re.search(r"current\s+GA", crds_comment, re.I))
check(f"gitops/apps/kagent-crds.yaml targetRevision comment names gitops/apps/kagent.yaml ({crds_comment!r})",
      "gitops/apps/kagent.yaml" in crds_comment)

print("== PRD #13 locks kagent's service.version to the chart we deploy ==")
# #599: PRD #13 locks the UST values every AI-layer pod emits, and #586 moved its two kagent lines to v0.10.1
# with no test reading them, so a revert to v0.9.9 would have passed. kagent tags the chart and the app the same,
# so the service.version is the chart's with a v. The current value is the one the line gives; 0.9.x may follow it
# only as history ("was `v0.9.9` until the 2026-09-10 chart bump").
PRD13 = "prds/13-mvp-walking-skeleton.md"
version = f"v{chart}"
# STALE's \b does not match inside "v0.9.9" (v and 0 are both word characters), and the PRD writes the v.
STALE_V = re.compile(r"(?<![\d.])0\.9\.\d+\b")
prd_lines = (REPO / PRD13).read_text(encoding="utf-8").splitlines()

rows = [l for l in prd_lines if re.match(r"^\|\s*`service\.version` for kagent\s*\|", l)]
check(f"{PRD13} has one Locked Decisions row for `service.version` for kagent", len(rows) == 1, f"{rows}")
cells = [c.strip() for c in rows[0].strip().strip("|").split("|")] if rows else []
value = cells[1] if len(cells) > 1 else ""
current = re.match(r"`([^`]*)`", value)
check(f"{PRD13} Locked Decisions row gives kagent service.version `{version}` "
      f"(found {current.group(1) if current else None})", current is not None and current.group(1) == version,
      f"{rows[0] if rows else None}")
stale = STALE_V.search(value)
check(f"{PRD13} Locked Decisions row names 0.9.x only after `{version}`, as history",
      stale is None or (current is not None and current.group(1) == version and stale.start() >= current.end()),
      value)

# The Milestone 3 exit criteria are the lines between its heading and the next heading.
start = next((i for i, l in enumerate(prd_lines) if re.match(r"^#+\s*Milestone 3\b", l)), None)
end = next((i for i in range(start + 1, len(prd_lines)) if prd_lines[i].startswith("#")), len(prd_lines)) \
    if start is not None else None
check(f"{PRD13} has a Milestone 3 heading", start is not None)
m3 = prd_lines[start:end] if start is not None else []
pods = [l for l in m3 if re.match(r"^\s*-\s*\[[ xX]\]\s*kagent pod has\b", l)]
check(f"{PRD13} Milestone 3 has one exit criterion for the kagent pod", len(pods) == 1, f"{pods}")
pod = pods[0] if pods else ""
given = list(re.finditer(r"service\.version=([^`\s,]+)", pod))
check(f"{PRD13} Milestone 3 kagent pod criterion names `service.version={version}` "
      f"(found {[g.group(1) for g in given]})", [g.group(1) for g in given] == [version], pod)
stale = STALE_V.search(pod)
check(f"{PRD13} Milestone 3 kagent pod criterion names 0.9.x only after `service.version={version}`, as history",
      stale is None or (len(given) == 1 and given[0].group(1) == version and stale.start() >= given[0].end()), pod)

if failures:
    print(f"\nFAILED: {len(failures)} check(s)")
    sys.exit(1)
print("\nAll kagent version pin checks passed.")
