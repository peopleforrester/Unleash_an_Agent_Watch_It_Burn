# ABOUTME: Holds platform-baseline.yaml to the repo: every Application file is claimed, every sister component is
# ABOUTME: accounted for exactly once, and every entry carries what its status needs. Offline.
"""Why this exists (#394).

The two IDPs were meant to be the same platform and are not, and the question "why is component X missing"
had been asked twice with no answer in the repo. platform-baseline.yaml is that answer, one entry per
component. A list like that is only worth having if it cannot quietly fall behind, so this checks it
against the two things it describes:

- this repo: every file in gitops/bootstrap/apps and gitops/apps-disabled is claimed by an entry, and every
  file an entry claims exists, in the directory its status implies. A new Application cannot land without a
  line saying what it is. An opt-in entry's files are listed by its own profile and by no fleet profile.
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

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from bootstrap_chart import APPS, REPO, all_profiles, app_files, profiles  # noqa: E402

BASELINE = REPO / "platform-baseline.yaml"
DISABLED = REPO / "gitops/apps-disabled"
DECISIONS = REPO / "decisions.md"

# The twenty components #394 measured as missing here on 2026-09-17. Each must stay accounted for: the
# issue's whole complaint was that nobody could say what happened to them.
ISSUE_394 = (
    "openbao", "openbao-config", "argo-rollouts", "argo-workflows", "argo-events", "keda", "gitea",
    "gitea-config", "cert-manager-issuers", "kserve", "kserve-crd", "llm-d", "vllm", "kgateway",
    "kgateway-crds", "gateway-api", "ai-dashboards", "ai-policies", "demo-agent", "agent-service",
)
# The profiles a fleet of clusters is built from: the roster's two and the attendee pool, plus full, which the
# old instructor rounds ran. An opt-in component reaches none of them.
FLEET = ("attendee", "burn", "admin", "full")

STATUSES = {"adopted", "equivalent", "disabled", "rejected", "proposed", "local", "opt-in"}
TIER_PROFILE = {1: "fleet", 2: "opt-in", 3: "none"}

failures: list[str] = []


def check(name: str, cond: bool) -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        failures.append(name)


def problems(baseline: dict, apps: set[str], disabled: set[str], headings: list[str],
             listed: dict[str, set[str]]) -> list[str]:
    """Everything wrong with a baseline, given the Application files on disk, the decisions.md headings and
    the app files each profile lists."""
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
        claimed_apps.update(entry_apps)
        home = disabled if status == "disabled" else apps
        for a in entry_apps:
            if a not in home:
                where = "gitops/apps-disabled" if status == "disabled" else "gitops/bootstrap/apps"
                out.append(f"{name}: claims {a}, which is not in {where}")
        if status in ("proposed", "rejected", "equivalent") and entry_apps:
            out.append(f"{name}: {status}, so nothing of it is installed, yet it claims {entry_apps}")

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
        if status == "opt-in":
            profile = c.get("profile")
            if profile in FLEET or profile not in listed:
                out.append(f"{name}: opt-in needs a profile the chart has a values file for and the fleet is not "
                           f"built from, not {profile!r}")
            elif not entry_apps or not set(entry_apps) <= listed[profile]:
                out.append(f"{name}: opt-in, but {profile} does not list all of {entry_apps}")
            for fleet in FLEET:
                if set(entry_apps) & listed.get(fleet, set()):
                    out.append(f"{name}: opt-in, but the fleet profile {fleet} lists "
                               f"{sorted(set(entry_apps) & listed[fleet])}")
        if status in ("proposed", "opt-in"):
            cost = c.get("cost")
            if not isinstance(cost, dict) or not isinstance(cost.get("measured"), bool) or not cost.get("known"):
                out.append(f"{name}: {status} needs cost.measured (true or false) and cost.known")
            elif cost["measured"] and not (isinstance(cost.get("build_seconds"), (int, float)) and cost.get("requests")):
                out.append(f"{name}: cost.measured is true, so it needs build_seconds and requests")
        if status == "proposed":
            tier = c.get("tier")
            if tier not in TIER_PROFILE:
                out.append(f"{name}: proposed with tier {tier!r}, not 1, 2 or 3")
            elif c.get("profile") != TIER_PROFILE[tier]:
                out.append(f"{name}: tier {tier} goes with profile {TIER_PROFILE[tier]!r}, not {c.get('profile')!r}")
            if not c.get("recommendation"):
                out.append(f"{name}: proposed with no recommendation")

    for s in sister_all:
        owners = claimed_sister.get(s, [])
        if len(owners) != 1:
            out.append(f"sister component {s!r} is claimed by {len(owners)} entries {owners}, needs exactly 1")
    for a in sorted((apps | disabled) - claimed_apps):
        out.append(f"{a} is an Application here that no baseline entry claims")
    for s in ISSUE_394:
        if s not in claimed_sister:
            out.append(f"{s!r}, one of the twenty #394 named, is not accounted for")
    return out


baseline = yaml.safe_load(BASELINE.read_text(encoding="utf-8"))
apps = {p.name for p in APPS.glob("*.yaml")}
disabled = {p.name for p in DISABLED.glob("*.yaml")}
headings = [l for l in DECISIONS.read_text(encoding="utf-8").splitlines() if l.startswith("## ")]
listed = {p: app_files(p) for p in all_profiles()}

print("== the baseline describes this repo and the sister snapshot ==")
found = problems(baseline, apps, disabled, headings, listed)
for p in found:
    print(f"        {p}")
check(f"no problems ({len(found)} found)", not found)
snapshot = baseline["sister"]["snapshot"]
check("the snapshot holds the sister's 38 components",
      sum(len(v) for v in snapshot.values()) == 38)
check("there is something to check: Applications were found on disk", len(apps) > 0)
check(f"every fleet profile is declared in lab-platform.yaml {list(FLEET)}", set(FLEET) <= set(profiles()))

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


def measured_without_numbers(b: dict) -> None:
    entry(b, "vllm")["cost"]["measured"] = True


def rejection_without_record(b: dict) -> None:
    entry(b, "gitea")["decision"] = "a decision nobody wrote down"


def disabled_app_claimed_as_live(b: dict) -> None:
    entry(b, "backstage")["status"] = "adopted"


def opt_in_on_a_fleet_profile(b: dict) -> None:
    entry(b, "vllm")["profile"] = "full"


def proposal_claiming_an_install(b: dict) -> None:
    entry(b, "openbao")["apps"] = ["vllm-qwen3.yaml"]


on_full = {**listed, "full": listed["full"] | {"vllm-qwen3.yaml"}}
for label, mutate, extra_app, lists in (
    ("an Application nobody claims is caught", lambda b: None, "new-thing.yaml", listed),
    ("a sister component nobody claims is caught", drop_sister_claim, None, listed),
    ("a proposal with no cost is caught", proposal_without_cost, None, listed),
    ("measured: true with no numbers is caught", measured_without_numbers, None, listed),
    ("a rejection with no decisions.md entry is caught", rejection_without_record, None, listed),
    ("a disabled app claimed as live is caught", disabled_app_claimed_as_live, None, listed),
    ("an opt-in entry naming a fleet profile is caught", opt_in_on_a_fleet_profile, None, listed),
    ("an opt-in app a fleet profile lists is caught", lambda b: None, None, on_full),
    ("a proposal that claims an installed file is caught", proposal_claiming_an_install, None, listed),
):
    broken = copy.deepcopy(baseline)
    mutate(broken)
    on_disk = apps | {extra_app} if extra_app else apps
    check(label, bool(problems(broken, on_disk, disabled, headings, lists)))

if failures:
    print(f"\nFAILED: {len(failures)} check(s)")
    sys.exit(1)
print("\nAll platform-baseline checks passed.")
