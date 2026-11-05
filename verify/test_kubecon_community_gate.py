# ABOUTME: Renders each profile's console (the ai-layer Application's components over console-src, under console.conf)
# ABOUTME: and holds /kubecon to a 404 on the community cluster and to the presenter page on the private one (#909).
"""The community host's half of the /kubecon gate (#909, from Whitney's review, #908).

The apex router's brief_not_roster matcher 404s /kubecon on attendee hosts and passes every roster host. attackme,
the community cluster's host, is a roster host, so on 2026-11-05 `https://attackme.burritobot.co/kubecon` answered
200 with the presenter page. The gate is the cluster's profile: burn and kubecon-community set
console.kubeconBrief false, the ai-layer Application then adds the no-kubecon-brief component, and that takes
kubecon.html out of the console-src ConfigMap. console.conf's `location = /kubecon { try_files /kubecon.html =404; }`
then finds no file. The page is not on the community cluster at all, so no Host header can reach it there.

This renders that without Helm or kustomize: the ai-layer Application as the chart writes it for each profile, the
console-src keys as configMapGenerator names them, each listed component's patches applied to them, and each path
resolved against console.conf's default server the way nginx picks a location (exact first, then the longest
prefix). verify/test_bootstrap_chart_render.py runs the same component through the pinned Helm and kustomize.
The 404s at the file names, /kubecon.html and /..data/kubecon.html, are verify/test_gated_page_names.py's, and
are checked here on both renders too.
"""
from __future__ import annotations

import pathlib
import re
import sys

import yaml

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from bootstrap_chart import (APPS, IMAGE_REGISTRY, LAB_PLATFORM_GHCR, NO_KUBECON_COMPONENT, REPO, REVISION,  # noqa: E402
                             all_profiles, app_names, for_kubecon_brief, kubecon_brief, without_front_door)

AI_LAYER = REPO / "gitops/ai-layer"
CONF = (AI_LAYER / "console.conf").read_text(encoding="utf-8")
ANCHOR = "map $http_upgrade"
if ANCHOR not in CONF:
    print(f"FAILED: console.conf has no '{ANCHOR}' line to end its default server at; the split below cannot run")
    sys.exit(1)
DEFAULT_SERVER = CONF[:CONF.index(ANCHOR)]
KUST = yaml.safe_load((AI_LAYER / "kustomization.yaml").read_text(encoding="utf-8"))
FLEET = (REPO / "infra/terraform/fleet/fleet.sh").read_text(encoding="utf-8")

failures: list[str] = []


def check(name: str, cond: bool, why: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  ({why})" if why and not cond else ""))
    if not cond:
        failures.append(name)


def ai_layer_app(profile: str) -> dict:
    """The ai-layer Application the chart renders for a profile with no frontDoor.certificateArn."""
    raw = for_kubecon_brief((APPS / "ai-layer.yaml").read_text(encoding="utf-8"), kubecon_brief(profile))
    raw = without_front_door(raw).replace(REVISION, "0" * 40).replace(IMAGE_REGISTRY, LAB_PLATFORM_GHCR)
    return yaml.safe_load(raw)


def console_src() -> dict[str, pathlib.Path]:
    """The console-src ConfigMap's keys as configMapGenerator writes them: `key=path`, else the file's own name."""
    gen = next(g for g in KUST["configMapGenerator"] if g["name"] == "console-src")
    out = {}
    for f in gen["files"]:
        key, _, path = f.rpartition("=") if "=" in f else ("", "", f)
        out[key or pathlib.Path(path).name] = AI_LAYER / path
    return out


def apply_component(path: str, data: dict) -> list[str]:
    """Apply one kustomize Component's console-src patches to the keys; return what it could not read, by name."""
    doc = yaml.safe_load((AI_LAYER / path / "kustomization.yaml").read_text(encoding="utf-8"))
    problems = []
    if doc.get("kind") != "Component" or doc.get("apiVersion") != "kustomize.config.k8s.io/v1alpha1":
        problems.append(f"{path} is not a kustomize Component")
    for key in set(doc) - {"apiVersion", "kind", "patches"}:
        problems.append(f"{path} sets {key}, which this render does not model")
    for p in doc.get("patches") or []:
        if p.get("target") != {"kind": "ConfigMap", "name": "console-src"}:
            problems.append(f"{path} patches {p.get('target')}, not the console-src ConfigMap")
            continue
        for op in yaml.safe_load(p["patch"]):
            m = re.fullmatch(r"/data/(.+)", op.get("path", ""))
            if op.get("op") != "remove" or not m:
                problems.append(f"{path}: {op} is not a removal of one console-src key")
            elif m.group(1) not in data:
                problems.append(f"{path} removes {m.group(1)}, which console-src does not have (kustomize fails on it)")
            else:
                del data[m.group(1)]
    return problems


# The default server's locations: `location = /x { ... }` and `location ^~ /x { ... }`, each with its one-line body.
LOCATIONS = re.findall(r"^\s*location\s+(=|\^~)\s+(\S+)\s+\{([^}]*)\}", DEFAULT_SERVER, re.M)


def answer(uri: str, data: dict) -> tuple[int, str]:
    """What this console answers for a URI: nginx's exact match, else its longest ^~ prefix; the file it serves."""
    exact = [body for kind, p, body in LOCATIONS if kind == "=" and p == uri]
    prefix = sorted(((p, body) for kind, p, body in LOCATIONS if kind == "^~" and uri.startswith(p)),
                    key=lambda x: -len(x[0]))
    body = exact[0] if exact else (prefix[0][1] if prefix else None)
    if body is None:
        return 0, f"no exact or ^~ location for {uri}, which this render does not model"
    if re.fullmatch(r"\s*return 404;\s*", body):
        return 404, ""
    m = re.fullmatch(r"\s*try_files (/\S+) =404;\s*", body)
    if not m:
        return 0, f"{uri}'s location is {body.strip()!r}, which this render does not model"
    key = m.group(1).lstrip("/")
    return (200, key) if key in data else (404, "")


print("== the community profiles withhold the page; the presenters' profiles keep it ==")
WITHHOLD = {"burn", "kubecon-community"}
for profile in all_profiles():
    if "ai-layer" not in app_names(profile):
        continue
    check(f"{profile}: console.kubeconBrief is {profile not in WITHHOLD}", kubecon_brief(profile) == (profile not in WITHHOLD))

# The roster role each profile is built for (fleet.sh's bootstrap_profile_for_role, the one place that answers it).
roles = dict((p, r) for _, r, p in re.findall(r"^\s*(workshop|kubecon):(community|admin)\) printf '([a-z-]+)' ;;",
                                                 FLEET, re.M))
check(f"fleet.sh gives the community role burn and kubecon-community, the admin role admin and kubecon-private {roles}",
      roles == {"burn": "community", "admin": "admin", "kubecon-community": "community", "kubecon-private": "admin"})
check("so every profile the community role is built with withholds /kubecon",
      bool(roles) and all(not kubecon_brief(p) for p, r in roles.items() if r == "community"))
check("and every profile the admin role is built with serves it",
      bool(roles) and all(kubecon_brief(p) for p, r in roles.items() if r == "admin"))

print("== the ai-layer Application adds the component on those two alone ==")
for profile in all_profiles():
    if "ai-layer" not in app_names(profile):
        continue
    comps = ((ai_layer_app(profile).get("spec") or {}).get("source") or {}).get("kustomize", {}).get("components")
    want = [NO_KUBECON_COMPONENT] if profile in WITHHOLD else None
    check(f"{profile}: ai-layer's kustomize components are {want}", comps == want, str(comps))

print("== each rendered console answers the gated paths ==")
PAGE = (AI_LAYER / "web/kubecon.html").read_text(encoding="utf-8")
check("kubecon.html is the KubeCon breakout brief", "KubeCon" in PAGE and len(PAGE) > 1000)
for profile in ("kubecon-community", "burn", "kubecon-private", "admin", "attendee", "full"):
    data = console_src()
    comps = ((ai_layer_app(profile).get("spec") or {}).get("source") or {}).get("kustomize", {}).get("components") or []
    problems = [p for c in comps for p in apply_component(c, data)]
    check(f"{profile}: every component applies to console-src {problems or ''}".rstrip(), not problems)
    served = profile not in WITHHOLD
    code, got = answer("/kubecon", data)
    check(f"{profile}: /kubecon is {'200, the brief' if served else '404'} ({code}{' ' + got if got else ''})",
          (code, got) == ((200, "kubecon.html") if served else (404, "")))
    if served:
        check(f"{profile}: and the file it serves is the repo's kubecon.html",
              data.get("kubecon.html") == AI_LAYER / "web/kubecon.html")
    check(f"{profile}: kubecon.html is {'in' if served else 'not in'} its console-src", ("kubecon.html" in data) == served)
    for uri in ("/kubecon.html", "/..data/kubecon.html", "/..data/brief.html", "/.kubecon"):
        code, why = answer(uri, data)
        check(f"{profile}: {uri} is a 404 ({code}{' ' + why if why else ''})", code == 404)
    # The withholding takes the one page: the 2-hour brief and the storefront are where they were.
    for uri, key in (("/brief", "brief.html"), ("/", "burritbot.html"), ("/lab", "lab.html")):
        check(f"{profile}: {uri} still serves {key}", answer(uri, data) == (200, key))
    check(f"{profile}: the component removes kubecon.html alone",
          set(console_src()) - set(data) == (set() if served else {"kubecon.html"}))

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All /kubecon community-gate checks passed.")
