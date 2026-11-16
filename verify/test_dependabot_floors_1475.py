# ABOUTME: Holds the versions #1475 moved past their Dependabot advisories: every copy each lock resolves sits outside
# ABOUTME: the advisory's affected range, and no glob older than 14 resolves onto minimatch 11, which it cannot read.
"""#1475 cleared 24 Dependabot alerts across three manifests. This test reads each lock as committed:

- images/watch-it-burn-backstage/yarn.lock: every resolved copy of isomorphic-git, node-forge, @hono/node-server,
  basic-ftp, hono, fast-xml-parser and minimatch (from 7.0.0) is at or past the release that fixed its advisories.
- minimatch 11 matches a pattern's portions with Matcher objects in place of RegExps, and glob 10 to 13 test each
  portion with `instanceof RegExp`, so a glob below 14 resolved onto minimatch 11 matches nothing and says nothing.
  Moving minimatch 9 and 10 to 11 is what moved glob 10 and 13 to 14 in package.json's resolutions; this holds the
  two in step: each glob entry in the lock whose minimatch dependency resolves to 11 or later is glob 14 or later.
- images/web-terminal/requirements.txt (and requirements.in): jupyterlab 4.6.4 or later, tornado 6.6.1 or later.
- docs/research/2026-10-30-argo-sync-replay/go.mod: go.opentelemetry.io/otel/trace 1.47.0 or later.
"""
from __future__ import annotations

import pathlib
import re
import sys

import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
APP = REPO / "images/watch-it-burn-backstage"
YARN_LOCK = APP / "yarn.lock"
PACKAGE_JSON = APP / "package.json"
REQ_TXT = REPO / "images/web-terminal/requirements.txt"
REQ_IN = REPO / "images/web-terminal/requirements.in"
GO_MOD = REPO / "docs/research/2026-10-30-argo-sync-replay/go.mod"

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"\n        {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def ver(s: str) -> tuple[int, ...]:
    """1.38.6 -> (1, 38, 6); a pre-release or build suffix is cut, so 1.47.0-rc.1 reads as 1.47.0."""
    m = re.match(r"v?(\d+(?:\.\d+)*)", s)
    if not m:
        raise SystemExit(f"test_dependabot_floors_1475: cannot read a version from {s!r}")
    return tuple(int(p) for p in m.group(1).split("."))


assert ver("1.38.6") == (1, 38, 6) and ver("v1.47.0-rc.1") == (1, 47, 0) and ver("2.10") < ver("3.0.2")


def lock_entries(text: str) -> tuple[dict[str, list[tuple[str, dict]]], dict]:
    """(name -> [(version, entry)] for each npm resolution in a Yarn 4 lock, the parsed lock itself)."""
    out: dict[str, list[tuple[str, dict]]] = {}
    doc = yaml.load(text, Loader=getattr(yaml, "CSafeLoader", yaml.SafeLoader))
    for key, entry in doc.items():
        if key == "__metadata" or not isinstance(entry, dict):
            continue
        name, _, ref = entry["resolution"].rpartition("@")
        if not ref.startswith("npm:"):
            continue
        out.setdefault(name, []).append((entry["version"], entry))
    return out, doc


print("== the Backstage yarn.lock ==")
lock_text = YARN_LOCK.read_text(encoding="utf-8")
entries, doc = lock_entries(lock_text)
# (package, the first fixed release, the lowest version the advisory covers) from the issue's alert table.
FLOORS = [
    ("isomorphic-git", "1.38.6", "0"),           # alerts 284, 285, 286
    ("node-forge", "1.4.3", "0"),                # alerts 288-291
    ("@hono/node-server", "2.1.6", "2.0.0"),     # alerts 292, 293
    ("basic-ftp", "6.2.4", "0"),                 # alerts 295, 296
    ("hono", "4.13.16", "0"),                    # alerts 297-301
    ("fast-xml-parser", "5.12.0", "0"),          # alert 287
    ("minimatch", "11.0.1", "7.0.0"),            # alert 279
]
for name, fixed, low in FLOORS:
    got = sorted({v for v, _ in entries.get(name, [])}, key=ver)
    bad = [v for v in got if ver(low) <= ver(v) < ver(fixed)]
    check(f"{name}: every copy the lock resolves is outside the advisory's range (resolved {', '.join(got)})",
          bool(got) and not bad, f"{', '.join(bad)} is at or above {low} and below {fixed}")


def resolved_version(name: str, descriptor: str) -> str | None:
    """The version yarn.lock resolves `name@<descriptor>` to, read from the lock key that lists it."""
    want = f"{name}@{descriptor}"
    for key, entry in doc.items():
        if isinstance(entry, dict) and want in [d.strip() for d in key.split(",")]:
            return entry["version"]
    return None


globs = entries.get("glob", [])
check(f"the lock resolves glob ({len(globs)} copies)", bool(globs))
for v, entry in globs:
    mm = (entry.get("dependencies") or {}).get("minimatch")
    if mm is None:
        continue
    mv = resolved_version("minimatch", mm)
    check(f"glob {v} reads minimatch {mm}, resolved to {mv}: glob 14 or later wherever minimatch is 11 or later",
          mv is not None and (ver(mv) < (11,) or ver(v) >= (14,)),
          f"glob {v} tests minimatch's patterns with instanceof RegExp, and minimatch {mv} returns Matcher objects")

pkg = yaml.safe_load(PACKAGE_JSON.read_text(encoding="utf-8"))
res = pkg.get("resolutions", {})
mm_keys = {k: v for k, v in res.items() if k.startswith("minimatch@")}
glob_keys = {k: v for k, v in res.items() if k.startswith("glob@")}
check("package.json moves minimatch 9 and 10 onto 11 and glob 10 and 13 onto 14 together",
      bool(mm_keys) and bool(glob_keys) and all(ver(v) >= (11, 0, 1) for v in mm_keys.values())
      and all(ver(v) >= (14,) for v in glob_keys.values()), f"{mm_keys} {glob_keys}")

print("== the web-terminal notebook lock ==")
for path in (REQ_TXT, REQ_IN):
    text = path.read_text(encoding="utf-8")
    jl = re.search(r"^jupyterlab==(\S+)", text, re.M)
    check(f"{path.name}: jupyterlab pinned at 4.6.4 or later (alerts 280-283)",
          bool(jl) and ver(jl.group(1)) >= (4, 6, 4), jl.group(0) if jl else "no jupyterlab== line")
req_txt = REQ_TXT.read_text(encoding="utf-8")
tor = re.search(r"^tornado==(\S+)", req_txt, re.M)
check("requirements.txt: tornado at 6.6.1 or later (alert 306)",
      bool(tor) and ver(tor.group(1)) >= (6, 6, 1), tor.group(0) if tor else "no tornado== line")
floor = re.search(r"^tornado>=(\S+)", REQ_IN.read_text(encoding="utf-8"), re.M)
check("requirements.in holds tornado's floor at 6.6.1, so a regenerated lock keeps it",
      bool(floor) and ver(floor.group(1)) >= (6, 6, 1), floor.group(0) if floor else "no tornado>= line")

print("== the argo-sync-replay go.mod ==")
gomod = GO_MOD.read_text(encoding="utf-8")
otel = re.search(r"^\s*go\.opentelemetry\.io/otel/trace (v\S+)", gomod, re.M)
check("go.opentelemetry.io/otel/trace at v1.47.0 or later (alert 304)",
      bool(otel) and ver(otel.group(1)) >= (1, 47, 0), otel.group(0) if otel else "no otel/trace require line")

if failures:
    print(f"\nFAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("\nAll #1475 Dependabot floor checks passed.")
