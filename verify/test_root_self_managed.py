# ABOUTME: Static gate for #253: every bootstrap root app-of-apps manages ITSELF from the repo, so a root
# ABOUTME: change reaches live clusters through Argo CD instead of a kubectl apply nobody remembers.
#
# Why. On 2026-09-06 a change to the attendee root's exclude reached six live clusters only by re-applying
# the root by hand, and applying the wrong root on one cluster created a second root over the same
# children. A root that lists its own directory as a source reconciles its own spec on every sync.
import fnmatch, pathlib, re, sys

import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
BOOT = REPO / "gitops/bootstrap"
REPO_URL = "https://github.com/peopleforrester/Unleash_an_Agent_Watch_It_Burn.git"
PROFILES = {
    # full excludes the two CHALLENGE-CONTROL apps for the same reason attendee does (#281): a presenter
    # must start a challenge where the room starts. It differs from attendee only in which collector
    # overlay it drops, because an instructor cluster already IS the instructor org.
    "full": {"name": "app-of-apps", "exclude": "{network-policies,kubearmor-policies,otel-collector-attendee,otel-collector-burn}.yaml"},
    # attendee also drops tempo and falco-talon (#475): no challenge or tour step reads Tempo, and Talon has
    # nothing to act on once the fork bomb is an instructor-box demo. admin and full keep both.
    "attendee": {"name": "app-of-apps-attendee",
                 "exclude": "{network-policies,kubearmor-policies,otel-collector,otel-collector-burn,tempo,falco-talon}.yaml"},
    "burn": {"name": "app-of-apps-burn", "include": True},
    # admin (#294): the presenters' own clusters. The student build with every guardrail ARMED, so a
    # control can be shown already working instead of being staged. It therefore keeps the two challenge
    # -control apps that attendee and full drop, and takes the non-dual collector because it ships to the
    # shared presenter org as its primary (#296).
    "admin": {"name": "app-of-apps-admin", "exclude": "{otel-collector-attendee,otel-collector-burn}.yaml"},
}
failures = []


def check(n, c):
    print(f"  {'PASS' if c else 'FAIL'}  {n}")
    if not c:
        failures.append(n)


deploy = (REPO / "infra/deploy-full-idp.sh").read_text()
for profile, want in PROFILES.items():
    d = BOOT / profile
    print(f"== {profile} root ==")
    manifests = sorted(d.glob("*.yaml")) if d.is_dir() else []
    check(f"gitops/bootstrap/{profile}/ holds exactly one manifest", len(manifests) == 1)
    if len(manifests) != 1:
        continue
    doc = yaml.safe_load(manifests[0].read_text())
    check("it is the root Application for this profile",
          doc.get("kind") == "Application" and doc["metadata"]["name"] == want["name"])
    sources = doc.get("spec", {}).get("sources") or []
    own = [s for s in sources if s.get("path") == f"gitops/bootstrap/{profile}" and s.get("repoURL") == REPO_URL]
    check("its own directory is one of its sources (self-managed)", len(own) == 1)
    apps = [s for s in sources if s.get("path") == "gitops/apps"]
    check("gitops/apps is a source with the profile's selection", len(apps) == 1 and (
        ("include" in want and bool(apps[0].get("directory", {}).get("include")))
        or ("exclude" in want and apps[0].get("directory", {}).get("exclude") == want["exclude"])))
    check("no single 'source:' remains (multi-source only)", "source" not in doc["spec"])
    check("selfHeal and prune stay on", doc["spec"]["syncPolicy"]["automated"] == {"prune": True, "selfHeal": True})
    check("deploy-full-idp applies this root from the new path",
          re.search(rf'{profile}\)\s+ROOT_APP="gitops/bootstrap/{profile}/{manifests[0].name}"', deploy) is not None)

print("== tempo and falco-talon: admin and full only (#475) ==")


def deploys(profile: str, app_file: str) -> bool:
    """Whether a profile's gitops/apps selection takes this file. Argo CD's glob, with its one {a,b} group."""
    root = yaml.safe_load(next((BOOT / profile).glob("*.yaml")).read_text())
    d = next(s for s in root["spec"]["sources"] if s.get("path") == "gitops/apps").get("directory", {})
    globs = []
    for g in filter(None, (d.get("include"), d.get("exclude"))):
        m = re.fullmatch(r"(.*)\{(.*)\}(.*)", g)
        globs.append([m.group(1) + p + m.group(3) for p in m.group(2).split(",")] if m else [g])
    hit = [any(fnmatch.fnmatch(app_file, p) for p in ps) for ps in globs]
    if d.get("include") and not hit[0]:
        return False
    return not (d.get("exclude") and hit[-1])


for app_file in ("tempo.yaml", "falco-talon.yaml"):
    check(f"{app_file} exists in gitops/apps", (REPO / "gitops/apps" / app_file).exists())
    check(f"attendee does not deploy {app_file}", not deploys("attendee", app_file))
    for profile in ("admin", "full"):
        check(f"{profile} deploys {app_file}", deploys(profile, app_file))
# The rest of the attendee observability path still deploys; only the Tempo store and Talon leave.
for app_file in ("prometheus.yaml", "otel-collector-attendee.yaml", "falco.yaml", "falcosidekick.yaml"):
    check(f"attendee still deploys {app_file}", deploys("attendee", app_file))

print("== no root left at the old flat path ==")
check("no app-of-apps*.yaml directly under gitops/bootstrap", not list(BOOT.glob("app-of-apps*.yaml")))

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All root self-management checks passed.")
