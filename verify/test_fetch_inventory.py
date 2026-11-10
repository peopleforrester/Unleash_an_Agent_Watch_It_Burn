#!/usr/bin/env python3
# ABOUTME: Re-runs the fetch call-site scan of verify/, .github/workflows/, scripts/ and images/ and fails, naming the
# ABOUTME: file and line, on a site verify/fetch-inventory.yaml does not list or does not classify (#1116, #1251).
"""verify/fetch-inventory.yaml accounts for every fetch call site the scan finds (#1116).

#1115 (Michael, 2026-11-07: never download an artifact we already hold a pinned copy of) starts from a list of every
line under verify/, .github/workflows/ and scripts/ that names a fetch, each classed as a pinned artifact or a live
check, and #1251 adds images/, whose build scripts workflows and tier tests run. verify/fetch_inventory.py holds the scan
and the check; this test runs them:

  - on the repo: every line the scan finds is claimed by an entry of its file, each entry claims exactly the number of
    lines it says, and each entry has a class and that class's fields (a pinned site's kind, pin and cached, a live
    site's kind and target, a loopback or none line's why); a pinned site's pin, when it starts with a repo path,
    names a file or directory that is there
  - images/: the build scripts a workflow or tier test runs (the Kyverno counter-fix build, both Joker builds) and the
    Dockerfiles are scanned and listed, the vendored yarn release is the one file under it left out, and a call site in
    an images/ file of a scratch repository fails like one under verify/
  - on a scratch repository: a new call site in a listed file, a call site in a file the inventory does not list (an
    untracked one too), an entry with no class, an entry with a field missing, a count that is off and an entry for a
    file with no call site each fail, naming the file and line or the file and entry
  - each command family's pattern finds a line of its own, and the names that only look like one (a fallback.curl.sh
    path, the curlimages/curl image, a curl/8 user agent, the CRANE variable) find none; a crane held in a variable is
    found where it runs a crane verb, and an image_cache platform layout is found as a layout is
  - a Dockerfile's base and its apt installs (#1274): a FROM line in any case, with flags and an AS name, or opening a
    string, COPY --from and `buildah from` are found, and so is apt or apt-get with an archive verb after its options,
    in a shell line or a list; a Python import, prose that opens with "from", and apt as a path (/var/lib/apt/lists)
    are not. Every FROM line of every Dockerfile under images/ is found and claimed by a pinned container-image entry,
    and a new Dockerfile with an unpinned FROM and an apt-get install of other packages fails on both lines

The fixtures build each command name from pieces, so this file names none whole.
"""
from __future__ import annotations

import os
import pathlib
import subprocess
import sys
import tempfile

VERIFY = pathlib.Path(__file__).resolve().parent
REPO = VERIFY.parent
sys.path.insert(0, str(VERIFY))
import fetch_inventory as fi  # noqa: E402

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"\n        {detail}" if detail and not ok else ""))
    if not ok:
        failures.append(name)


CU, UO, HE, CR, GC = "cu" + "rl", "url" + "open", "he" + "lm", "cr" + "ane", "git " + "clone"
FR, AG = "FR" + "OM", "ap" + "t-get"

print("== the repo: every call site the scan finds is listed and classified ==")
problems, before_rule = fi.check_split()
check(f"verify/fetch-inventory.yaml accounts for every call site a change under the rule touched ({len(problems)} "
      f"problems; {fi.FIX_HINT})", not problems,
      "\n        ".join(problems[:40]) + (f"\n        and {len(problems) - 40} more" if len(problems) > 40 else ""))
if before_rule:
    print(f"  NOTE  {len(before_rule)} places behind, each in a file last changed in a commit made before the "
          "inventory's rule; the next change to the file brings its entry current:"
          + "".join(f"\n        {b}" for b in before_rule[:20]))
check("this fetch_inventory.py carries the rule owed() reads in each commit's copy",
      fi.DRIFT_RULE in (VERIFY / "fetch_inventory.py").read_text())
s = fi.summary()
counted = sum(sum(c.values()) for c in s["by_kind"].values())
check(f"the summary counts each of the {s['total']} sites once, by class and kind", counted == s["total"] > 0,
      f"{counted} counted")
pinned, live = sum(s["by_kind"]["pinned"].values()), sum(s["by_kind"]["live"].values())
check(f"it finds pinned ({pinned}) and live ({live}) sites", pinned > 0 and live > 0)
check("the scan leaves out only the inventory, the module and this test",
      fi.SELF == ("verify/fetch-inventory.yaml", "verify/fetch_inventory.py", "verify/test_fetch_inventory.py"))
sites = fi.load(REPO / fi.INVENTORY_REL)
missing_pins = []
for rel, entries in sites.items():
    for e in entries if isinstance(entries, list) else []:
        if isinstance(e, dict) and e.get("class") == "pinned" and isinstance(e.get("pin"), str):
            head = e["pin"].split()[0]
            if "/" in head and not head.startswith("<") and not (REPO / head.rstrip("/")).exists():
                missing_pins.append(f"{rel}: pin {e['pin']!r} names {head}, which is not in the repo")
check("each pinned site's pin that starts with a repo path names a file or directory that is there", not missing_pins,
      "; ".join(missing_pins))
fetch_tools = [rel for rel in sites if rel == "verify/fetch-e2e-tools.sh"]
check("the E2E tools fetch is listed, through the artifact cache", fetch_tools == ["verify/fetch-e2e-tools.sh"] and
      all(e.get("class") == "pinned" and e.get("cached") is True for e in sites["verify/fetch-e2e-tools.sh"]))

print("== images/: the build scripts workflows and tier tests run are scanned and classed (#1251) ==")
scanned = set(fi.tracked())
BUILD_SCRIPTS = ("images/kyverno-counter-fix/build.sh", "images/villains/build.sh", "images/villains/build-loopback.sh")
for rel in BUILD_SCRIPTS + ("images/web-terminal/Dockerfile", "images/workshop-mcp/Dockerfile", "images/tool-pin/Dockerfile"):
    check(f"{rel} is scanned and the inventory lists it", rel in scanned and rel in sites,
          f"scanned {rel in scanned}, listed {rel in sites}")
workflows = "".join(p.read_text(encoding="utf-8") for p in sorted((REPO / ".github" / "workflows").glob("*.y*ml")))
for rel in ("images/kyverno-counter-fix/build.sh", "images/villains/build-loopback.sh"):
    check(f"a workflow runs {rel}, so its scan is the one #1251 asks for", rel in workflows)
check("build-loopback.sh runs build.sh, so build.sh's crane calls run in the workflow and the tier test",
      'bash "${HERE}/build.sh"' in (REPO / "images/villains/build-loopback.sh").read_text(encoding="utf-8"))
check("the scan leaves out only the vendored yarn release under images/",
      fi.VENDORED == ("images/watch-it-burn-backstage/.yarn/releases/",) and "images" in fi.ROOTS)
for rel, want in (("images/kyverno-counter-fix/build.sh", {"git_mirror.py\" ensure", "image_cache.py\" platform-layout"}),
                  ("images/villains/build-loopback.sh", {"image_cache.py\" layout"}),
                  ("images/villains/build.sh", {'"$CR" append', '"$CR" mutate'})):
    found = [line for r, _, line in fi.scan(REPO, [rel])]
    missing = [w for w in want if not any(w in line for line in found)]
    check(f"the scan finds {', '.join(sorted(want))} in {rel}", not missing, f"missing {missing}")

print("== the patterns: each command family finds a line of its own ==")
samples = {
    "curl": f"{CU} -fsS https://example.test/",
    "wget": "wg" + "et -qO- http://x/",
    "urlopen": f"with urllib.request.{UO}(req) as r:",
    "helm": f'subprocess.run([{HE}, "pull", chart])',
    "terraform-init": "terra" + "form -chdir=root init -input=false",
    "pip-uv": "python3 -m pi" + "p install x==1",
    "node": "np" + "m ci",
    "playwright-install": "play" + "wright install chromium",
    "image-pull": "dock" + "er pull ghcr.io/x@sha256:0",
    "crane": f"{CR} digest ghcr.io/x",
    "git-clone": f"{GC} --depth 1 https://github.com/x/y",
    "setup-action": "- uses: actions/" + "setup-node@abc",
    "artifact-cache": 'archive="$(bash verify/artifact' + '-cache.sh get "${sha}" "${url}")"',
    "dockerfile-from": f"{FR} python:3.12-slim",
    "apt": f"RUN {AG} update && {AG} install -y --no-install-recommends jq",
}
# #1122's two entry points, each in the artifact-cache family: an image layout and a git mirror, by call and by command.
# #1314: uv installing a Python itself downloads a CPython build, in shell and in list form.
for line in ("u" + "v python install 3.12", 'subprocess.run(["u' + 'v", "python", "install", "--no-config", version])'):
    check(f"pip-uv: the scan finds {line!r}", "pip-uv" in fi.families(line), str(fi.families(line)))
for line in ("base = image" + "_cache.layout(ref)", 'layout="$(python3 verify/image' + '_cache.py layout "${base}")"',
             "d = image" + "_cache.platform_layout(ref, out)",
             'digest="$(python3 "${VERIFY}/image' + '_cache.py" platform-layout "${ref}" "${out}" linux/amd64)"',
             "m = git" + "_mirror.ensure(url, pin)", 'python3 "${REPO_DIR}/verify/git' + '_mirror.py" submodules "${REPO_DIR}"'):
    check(f"artifact-cache: the scan finds {line!r}", "artifact-cache" in fi.families(line), str(fi.families(line)))
check("every family has a sample", set(samples) == set(fi.PATTERNS), str(set(fi.PATTERNS) ^ set(samples)))
for fam, line in samples.items():
    check(f"{fam}: the scan finds {line!r}", bool(fi.SCAN.search(line)) and fam in fi.families(line), str(fi.families(line)))
for line in ('"$CR" append --platform linux/amd64 -b "$JOKER_BASE" -f l.tar -t "${ref}"',
             '"${CRANE}" --insecure push "${layout}" "${addr}/x"'):
    check(f"crane: the scan finds a crane held in a variable in {line!r}", "crane" in fi.families(line), str(fi.families(line)))
for line in (f"challenges/02-sanitization/fallback.{CU}.sh", f"image: {CU}images/{CU}:8.1", f'"User-Agent": "{CU}/8"',
             'CRANE="${TOOLS_BIN}/' + CR + '"', f"{HE} template . --values v.yaml", 'CR="${CRANE:-' + CR + '}"',
             'echo "$CR" is set'):
    check(f"the scan finds nothing in {line!r}", not fi.SCAN.search(line), str(fi.families(line)))

print("== a Dockerfile's FROM and apt-get (#1274) ==")
for fam, line in (("dockerfile-from", f"{FR} --platform=$BUILDPLATFORM ghcr.io/x/y:1@sha256:0 AS build"),
                  ("dockerfile-from", f"{FR.lower()} debian:bookworm-slim"),
                  ("dockerfile-from", f"{FR} build \\"),
                  ("dockerfile-from", f'ok = parse("{FR} scratch\\n{FR.lower()} debian:bookworm-slim\\n")'),
                  ("dockerfile-from", "COPY --chown=1000 --from=ghcr.io/x/tools:1 /bin/t /bin/t"),
                  ("dockerfile-from", "ctr=$(buil" + "dah from ghcr.io/x/node:24@sha256:0)"),
                  ("apt", f"{AG} -o Acquire::Check-Valid-Until=false -o Acquire::Retries=3 update; \\"),
                  ("apt", f"    {AG} install -y --no-install-recommends libsqlite3-dev && \\"),
                  ("apt", f'run(["{AG}", *opts, "-q", "download", *pkgs], "download")'),
                  ("apt", "sudo ap" + "t install -y jq"),
                  ("apt", f"/usr/bin/{AG} -qq upgrade")):
    check(f"{fam}: the scan finds {line!r}", fam in fi.families(line), str(fi.families(line)))
for line in ("from __future__ import annotations", "from lab-platform's build (lab-platform#372).",
             'and "from v1.37.0" not in line]', f'{FR}, TO = "2026-11-12", "2026-11-13"', "    rm -rf /var/lib/ap" + "t/lists/*",
             "RUN --mount=type=cache,target=/var/cache/ap" + "t,sharing=locked \\", "buil" + "dah, from this directory:",
             "    rm -f /etc/ap" + "t/sources.list; \\"):
    check(f"the scan finds nothing in {line!r}", not fi.SCAN.search(line), str(fi.families(line)))
dockerfiles = [rel for rel in scanned if rel.startswith("images/") and pathlib.PurePath(rel).name == "Dockerfile"]
check("the scan reads the Dockerfiles under images/", len(dockerfiles) >= 5, str(dockerfiles))
_, claimed = fi.assign(sites, fi.scan(REPO, dockerfiles))
by_line = {(rel, n): sites[rel][i] for (rel, i), got in claimed.items() for n, _ in got}
for rel in dockerfiles:
    lines = (REPO / rel).read_text(encoding="utf-8").splitlines()
    froms = [n for n, line in enumerate(lines, 1) if line.lstrip().upper().startswith(FR + " ")]
    bad = [f"{rel}:{n} is claimed by {by_line.get((rel, n))}" for n in froms
           if (by_line.get((rel, n)) or {}).get("kind") != "container-image"]
    check(f"{rel}: each of its {len(froms)} {FR} lines is found and classed a pinned container-image", froms and not bad,
          "; ".join(bad))

print("== a scratch repository: each way the inventory can fall behind fails by name ==")


def scratch(files: dict[str, str], inventory: str) -> list[str]:
    with tempfile.TemporaryDirectory(dir=os.environ.get("TMPDIR") or None) as td:
        root = pathlib.Path(td)
        subprocess.run(["git", "init", "-q", str(root)], check=True)
        (root / ".gitignore").write_text("ignored/\n")
        for rel, text in files.items():
            (root / rel).parent.mkdir(parents=True, exist_ok=True)
            (root / rel).write_text(text)
        subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
        inv = root / "inventory.yaml"
        inv.write_text(inventory)
        return fi.check(root, inv)


BASE = {"verify/probe.sh": f"#!/bin/sh\n# reads the bot\n{CU} -s https://lab.test/cost\n",
        "scripts/read.py": f"import urllib.request\nurllib.request.{UO}('https://lab.test/')\n"}
LIVE = "      class: live\n      kind: lab-endpoint\n      target: the lab\n"
GOOD = ("sites:\n"
        f"  verify/probe.sh:\n    - match: '{CU} -s'\n      lines: 1\n" + LIVE +
        f"  scripts/read.py:\n    - match: '{UO}'\n      lines: 1\n" + LIVE)
got = scratch(BASE, GOOD)
check("a repository whose call sites are all listed passes", got == [], str(got))

got = scratch({**BASE, "verify/probe.sh": BASE["verify/probe.sh"] + f"{CU} -s https://lab.test/controls\n"}, GOOD)
check("a second call site in a listed file fails, naming the entry's count and both lines",
      any("verify/probe.sh: entry 1" in p and "claims 2 lines, the inventory says 1" in p and "verify/probe.sh:4" in p
          for p in got), str(got))

got = scratch({**BASE, "images/app/Dockerfile": f"FROM x\nRUN {CU} -fsSL https://example.test/t.tgz | tar -xz\n",
              "images/app/.yarn/releases/yarn-9.cjs": f"{CU} https://x/\n",
              "images/watch-it-burn-backstage/.yarn/releases/yarn-9.cjs": f"{CU} https://x/\n"}, GOOD)
check("a call site in an images/ Dockerfile the inventory does not list fails, naming its file and line",
      any(p.startswith("images/app/Dockerfile:2: a fetch call site missing from the inventory") for p in got), str(got))
check("the vendored yarn release is not scanned, and a .yarn/releases file elsewhere under images/ is",
      not any(p.startswith("images/watch-it-burn-backstage/") for p in got)
      and any(p.startswith("images/app/.yarn/releases/yarn-9.cjs:1:") for p in got), str(got))

got = scratch({**BASE, "images/new/Dockerfile": f"# a new image\n{FR} python:3.12\nRUN {AG} update \\\n"
                                                 f" && {AG} install -y --no-install-recommends jq\n"}, GOOD)
check(f"a new Dockerfile's unpinned {FR} and its {AG} lines fail, naming each, though none names another command",
      [p.split(": a fetch")[0] for p in got] == ["images/new/Dockerfile:2", "images/new/Dockerfile:3",
                                                 "images/new/Dockerfile:4"], str(got))

got = scratch({**BASE, "verify/new.py": f"x = 1\nurllib.request.{UO}(u)\n"}, GOOD)
check("a call site in a file the inventory does not list fails, naming its file and line",
      any(p.startswith("verify/new.py:2: a fetch call site missing from the inventory (no entry for this file)")
          for p in got), str(got))

with tempfile.TemporaryDirectory(dir=os.environ.get("TMPDIR") or None) as td:
    root = pathlib.Path(td)
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    (root / ".gitignore").write_text("verify/ignored/\n")
    for rel, text in {**BASE, "verify/ignored/x.sh": f"{CU} https://x/\n"}.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text)
    subprocess.run(["git", "-C", str(root), "add", "verify/probe.sh"], check=True)
    (root / "inv.yaml").write_text(GOOD)
    got = fi.check(root, root / "inv.yaml")
check("an untracked file's call site is found and claimed, and an ignored file's is not scanned", got == [], str(got))

got = scratch({**BASE, "verify/probe.sh": f"#!/bin/sh\n{CU} -s https://lab.test/cost\n"},
              GOOD.replace(f"match: '{CU} -s'", "match: 'wget'"))
check("a call site no entry of its file matches fails, naming its file and line",
      any(p.startswith("verify/probe.sh:2: a fetch call site missing from the inventory (no entry of this file matches it)")
          for p in got), str(got))

got = scratch(BASE, GOOD.replace("      class: live\n      kind: lab-endpoint\n      target: the lab\n", "", 1))
check("an entry with no class fails as unclassified, naming the file, the entry and its line",
      any("verify/probe.sh: entry 1" in p and "has no classification" in p for p in got)
      and any(p.startswith("verify/probe.sh:3: a fetch call site with no classification") for p in got), str(got))

got = scratch(BASE, GOOD.replace("class: live", "class: maybe", 1))
check("an entry with a class that is not one of the four fails as unclassified",
      any("has no classification: class is 'maybe'" in p for p in got)
      and any(p.startswith("verify/probe.sh:3: a fetch call site with no classification") for p in got), str(got))

got = scratch(BASE, GOOD.replace("      target: the lab\n", "", 1))
check("a live entry with no target fails, naming the file and entry",
      any("verify/probe.sh: entry 1" in p and "is live but has no target" in p for p in got), str(got))

pinned = GOOD.replace(LIVE, "      class: pinned\n      kind: tool\n      pin: verify/x.lock\n", 1)
got = scratch(BASE, pinned)
check("a pinned entry with no `cached` fails, naming the file and entry",
      any("verify/probe.sh: entry 1" in p and "`cached` is not true or false" in p for p in got), str(got))
got = scratch(BASE, pinned.replace("kind: tool", "kind: gadget"))
check("a pinned entry whose kind is not a pinned kind fails",
      any("has kind 'gadget', not one of" in p for p in got), str(got))

got = scratch(BASE, GOOD + f"  verify/gone.sh:\n    - match: '{CU}'\n      lines: 1\n" + LIVE)
check("an entry for a file with no call site fails, naming the file",
      "verify/gone.sh: the inventory lists it, but the scan finds no fetch call site there" in got, str(got))

got = scratch(BASE, GOOD.replace("lines: 1", "lines: 0", 1))
check("an entry whose count is not 1 or more fails", any("has no `lines` count of 1 or more" in p for p in got), str(got))

got = scratch(BASE, GOOD.replace(f"match: '{CU} -s'", "match: '('", 1))
check("an entry whose match is not a regular expression fails, naming it",
      any("has a match that is not a regular expression" in p for p in got), str(got))

print("== the drift rule: drift from a commit made before the inventory is named, not failed on ==")
with tempfile.TemporaryDirectory(dir=os.environ.get("TMPDIR") or None) as td:
    root = pathlib.Path(td)

    def g(*args: str) -> None:
        subprocess.run(["git", "-C", str(root), "-c", "user.name=t", "-c", "user.email=t@t", *args], check=True,
                       capture_output=True)
    g("init", "-q")
    for rel, text in BASE.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text)
    (root / "verify" / "old.sh").write_text(f"{CU} -s https://lab.test/old\n")
    g("add", "-A")
    g("commit", "-q", "-m", "before fetch_inventory.py existed")
    (root / "verify" / "fetch_inventory.py").write_text(f"# the rule\n{fi.DRIFT_RULE}\n")
    (root / "verify" / "ruled.sh").write_text(f"{CU} -s https://lab.test/ruled\n")
    g("add", "-A")
    g("commit", "-q", "-m", "under the rule")
    (root / "inv.yaml").write_text(GOOD)
    fails, named = fi.check_split(root, root / "inv.yaml",
                                  ["verify/probe.sh", "scripts/read.py", "verify/old.sh", "verify/ruled.sh"])
    check("drift on a file last committed before fetch_inventory.py existed is named, not failed on",
          any(p.startswith("verify/old.sh:1:") for p in named) and not any(p.startswith("verify/old.sh") for p in fails),
          f"fails {fails}, named {named}")
    check("drift on a file last committed under the rule fails",
          any(p.startswith("verify/ruled.sh:1:") for p in fails), f"fails {fails}")
    (root / "verify" / "old.sh").write_text(f"{CU} -s https://lab.test/old\n# touched\n")
    fails, named = fi.check_split(root, root / "inv.yaml", ["verify/probe.sh", "scripts/read.py", "verify/old.sh"])
    check("and the same file, edited and not yet committed, fails", any(p.startswith("verify/old.sh:1:") for p in fails),
          f"fails {fails}")
    bad = GOOD.replace("class: live", "class: maybe", 1)
    (root / "inv.yaml").write_text(bad)
    g("checkout", "-q", "--", "verify/old.sh")
    fails, named = fi.check_split(root, root / "inv.yaml", ["verify/probe.sh", "scripts/read.py"])
    check("a malformed entry fails whenever its file was last changed",
          any("has no classification" in p for p in fails), f"fails {fails}")

print()
if failures:
    print(f"FAIL: {len(failures)} fetch inventory checks failed")
    sys.exit(1)
print("All fetch inventory checks passed.")
