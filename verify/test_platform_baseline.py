# ABOUTME: Holds platform-baseline.yaml to the repo: every Application is claimed, every sister component is
# ABOUTME: accounted for exactly once, and every entry carries what its status needs. Offline.
"""Why this exists (#394).

The two IDPs were meant to be the same platform and are not, and the question "why is component X missing"
had been asked twice with no answer in the repo. platform-baseline.yaml is that answer, one entry per
component. A list like that is only worth having if it cannot quietly fall behind, so this checks it
against the two things it describes:

- this repo: every file in gitops/apps and gitops/apps-disabled is claimed by an entry, and every file an
  entry claims exists, in the directory its status implies. A new Application cannot land without a line
  saying what it is.
- the sister: every component directory in the recorded snapshot is claimed by exactly one entry. Whether
  the snapshot still matches the sister's main branch needs the network, so that half is
  test_platform_baseline_sister.py in the E2E suite.

The negative controls at the end break a copy of the baseline in each way that matters and require the
validator to notice, so it cannot go vacuous.
"""
from __future__ import annotations

import copy
import pathlib
import sys

import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
BASELINE = REPO / "platform-baseline.yaml"
APPS = REPO / "gitops/apps"
DISABLED = REPO / "gitops/apps-disabled"
OPT_IN = REPO / "gitops/opt-in"
DECISIONS = REPO / "decisions.md"

# The twenty components #394 measured as missing here on 2026-09-17. Each must stay accounted for: the
# issue's whole complaint was that nobody could say what happened to them.
ISSUE_394 = (
    "openbao", "openbao-config", "argo-rollouts", "argo-workflows", "argo-events", "keda", "gitea",
    "gitea-config", "cert-manager-issuers", "kserve", "kserve-crd", "llm-d", "vllm", "kgateway",
    "kgateway-crds", "gateway-api", "ai-dashboards", "ai-policies", "demo-agent", "agent-service",
)

STATUSES = {"adopted", "equivalent", "disabled", "rejected", "proposed", "local", "opt-in"}
TIER_PROFILE = {1: "fleet", 2: "opt-in", 3: "none"}

failures: list[str] = []


def check(name: str, cond: bool) -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        failures.append(name)


def check_cost(name: str, cost, out: list[str]) -> None:
    if not isinstance(cost, dict) or not isinstance(cost.get("measured"), bool) or not cost.get("known"):
        out.append(f"{name}: needs cost.measured (true or false) and cost.known")
    elif cost["measured"] and not (isinstance(cost.get("build_seconds"), (int, float)) and cost.get("requests")):
        out.append(f"{name}: cost.measured is true, so it needs build_seconds and requests")


def problems(baseline: dict, apps: set[str], disabled: set[str], headings: list[str],
             opt_in: dict[str, set[str]]) -> list[str]:
    """Everything wrong with a baseline, given the Application files on disk (gitops/apps, gitops/apps-disabled,
    and gitops/opt-in/<profile> keyed by profile) and the decisions.md headings."""
    out: list[str] = []
    if baseline.get("schema_version") != 1:
        out.append(f"schema_version is {baseline.get('schema_version')!r}, this checker reads 1")

    snapshot = baseline.get("sister", {}).get("snapshot", {})
    sister_all = [c for layer in snapshot.values() for c in layer]
    if len(sister_all) != len(set(sister_all)):
        out.append("the sister snapshot lists a component twice")

    components = baseline.get("components", [])
    names = [c.get("name") for c in components]
    for n in sorted({n for n in names if names.count(n) > 1}):
        out.append(f"two entries are named {n!r}")

    claimed_sister: dict[str, list[str]] = {}
    claimed_apps: set[str] = set()
    for c in components:
        name = c.get("name", "<unnamed>")
        status = c.get("status")
        if status not in STATUSES:
            out.append(f"{name}: status {status!r} is not one of {sorted(STATUSES)}")
            continue
        for s in c.get("sister", []):
            claimed_sister.setdefault(s, []).append(name)
            if s not in sister_all:
                out.append(f"{name}: claims sister component {s!r}, which is not in the snapshot")

        entry_apps = c.get("apps", [])
        if status == "opt-in":
            profile = c.get("profile", "")
            home, where = opt_in.get(profile, set()), f"gitops/opt-in/{profile}"
            claimed_apps.update(f"{profile}/{a}" for a in entry_apps)
            if profile not in opt_in:
                out.append(f"{name}: opt-in profile {profile!r} has no gitops/opt-in/{profile} or no root in gitops/bootstrap/{profile}")
            if not entry_apps:
                out.append(f"{name}: opt-in but names no apps")
            if not c.get("why"):
                out.append(f"{name}: opt-in with no why")
            check_cost(name, c.get("cost"), out)
        else:
            claimed_apps.update(entry_apps)
            home = disabled if status == "disabled" else apps
            where = "gitops/apps-disabled" if status == "disabled" else "gitops/apps"
        for a in entry_apps:
            if a not in home:
                out.append(f"{name}: claims {a}, which is not in {where}")

        if status in ("adopted", "local") and not entry_apps and not c.get("installed_by"):
            out.append(f"{name}: {status} but names neither apps nor installed_by")
        if c.get("installed_by"):
            script = REPO / c["installed_by"]
            if not script.is_file():
                out.append(f"{name}: installed_by {c['installed_by']} does not exist")
            elif name not in script.read_text(encoding="utf-8"):
                out.append(f"{name}: installed_by {c['installed_by']} never mentions {name}")
        if status == "local" and c.get("sister"):
            out.append(f"{name}: local but claims sister components")
        if status == "local" and not c.get("why"):
            out.append(f"{name}: local with no why")
        if status == "equivalent" and not c.get("by"):
            out.append(f"{name}: equivalent but does not say by what")
        if status == "disabled" and not (c.get("why") and c.get("revisit")):
            out.append(f"{name}: disabled needs both why and revisit")
        if status == "rejected":
            decision = c.get("decision", "")
            if not c.get("why"):
                out.append(f"{name}: rejected with no why")
            if not decision or not any(decision in h for h in headings):
                out.append(f"{name}: rejected, but decision {decision!r} is not a decisions.md heading")
        if status == "proposed":
            tier = c.get("tier")
            if tier not in TIER_PROFILE:
                out.append(f"{name}: proposed with tier {tier!r}, not 1, 2 or 3")
            elif c.get("profile") != TIER_PROFILE[tier]:
                out.append(f"{name}: tier {tier} goes with profile {TIER_PROFILE[tier]!r}, not {c.get('profile')!r}")
            if not c.get("recommendation"):
                out.append(f"{name}: proposed with no recommendation")
            check_cost(name, c.get("cost"), out)

    for s in sister_all:
        owners = claimed_sister.get(s, [])
        if len(owners) != 1:
            out.append(f"sister component {s!r} is claimed by {len(owners)} entries {owners}, needs exactly 1")
    on_disk = apps | disabled | {f"{p}/{a}" for p, files in opt_in.items() for a in files}
    for a in sorted(on_disk - claimed_apps):
        out.append(f"{a} is an Application here that no baseline entry claims")
    for s in ISSUE_394:
        if s not in claimed_sister:
            out.append(f"{s!r}, one of the twenty #394 named, is not accounted for")
    return out


baseline = yaml.safe_load(BASELINE.read_text(encoding="utf-8"))
apps = {p.name for p in APPS.glob("*.yaml")}
disabled = {p.name for p in DISABLED.glob("*.yaml")}
headings = [l for l in DECISIONS.read_text(encoding="utf-8").splitlines() if l.startswith("## ")]
# An opt-in profile counts only when it has both halves: its Applications and a root that takes them.
opt_in = {d.name: {p.name for p in d.glob("*.yaml")} for d in sorted(OPT_IN.glob("*"))
          if d.is_dir() and (REPO / "gitops/bootstrap" / d.name).is_dir()}

print("== the baseline describes this repo and the sister snapshot ==")
found = problems(baseline, apps, disabled, headings, opt_in)
for p in found:
    print(f"        {p}")
check(f"no problems ({len(found)} found)", not found)
snapshot = baseline["sister"]["snapshot"]
check("the snapshot holds the sister's 38 components",
      sum(len(v) for v in snapshot.values()) == 38)
check("there is something to check: Applications were found on disk", len(apps) > 0)
check("and the local-inference opt-in profile was found", "vllm-qwen3.yaml" in opt_in.get("local-inference", set()))

by_status: dict[str, int] = {}
for c in baseline["components"]:
    by_status[c["status"]] = by_status.get(c["status"], 0) + 1
print(f"        entries by status: {dict(sorted(by_status.items()))}")

print("== the validator is not vacuous ==")


def entry(b: dict, name: str) -> dict:
    return next(c for c in b["components"] if c["name"] == name)


def drop_sister_claim(b: dict) -> None:
    entry(b, "openbao")["sister"] = ["openbao"]


def proposal_without_cost(b: dict) -> None:
    entry(b, "argo-rollouts").pop("cost")


def opt_in_without_cost(b: dict) -> None:
    entry(b, "vllm").pop("cost")


def opt_in_on_a_missing_profile(b: dict) -> None:
    entry(b, "vllm")["profile"] = "no-such-profile"


def measured_without_numbers(b: dict) -> None:
    entry(b, "vllm")["cost"]["measured"] = True


def rejection_without_record(b: dict) -> None:
    entry(b, "gitea")["decision"] = "a decision nobody wrote down"


def disabled_app_claimed_as_live(b: dict) -> None:
    entry(b, "backstage")["status"] = "adopted"


for label, mutate, extra_app in (
    ("an Application nobody claims is caught", lambda b: None, "new-thing.yaml"),
    ("a sister component nobody claims is caught", drop_sister_claim, None),
    ("a proposal with no cost is caught", proposal_without_cost, None),
    ("an opt-in with no cost is caught", opt_in_without_cost, None),
    ("an opt-in naming a profile that does not exist is caught", opt_in_on_a_missing_profile, None),
    ("measured: true with no numbers is caught", measured_without_numbers, None),
    ("a rejection with no decisions.md entry is caught", rejection_without_record, None),
    ("a disabled app claimed as live is caught", disabled_app_claimed_as_live, None),
):
    broken = copy.deepcopy(baseline)
    mutate(broken)
    on_disk = apps | {extra_app} if extra_app else apps
    check(label, bool(problems(broken, on_disk, disabled, headings, opt_in)))
broken_opt_in = {**opt_in, "local-inference": opt_in.get("local-inference", set()) | {"unclaimed.yaml"}}
check("an opt-in Application nobody claims is caught",
      bool(problems(baseline, apps, disabled, headings, broken_opt_in)))

if failures:
    print(f"\nFAILED: {len(failures)} check(s)")
    sys.exit(1)
print("\nAll platform-baseline checks passed.")
