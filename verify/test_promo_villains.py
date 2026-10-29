# ABOUTME: Challenge 2 hands out lab-platform's promo/ villains (#653): every copy names the `:v1` references in
# ABOUTME: verify/promo_villains.py, the roster matches, and restrict-image-registries refuses the path.
"""Offline. The anonymous pull of each image is verify/test_promo_villains_public.py (tools tier).

The villains moved from docker.io/peopleforrester/<name>:latest to ghcr.io/peopleforrester/lab-platform/promo/<name>:v1.
ghcr.io is on the allow-list, so the refusal Challenge 2 teaches rests on the policy's refusedPaths variable; if
that went, the student's flip to Deny would admit the villain and the challenge would have no fix.
"""
from __future__ import annotations

import html
import pathlib
import re
import sys

import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "verify"))
import kubecon_probe as kp  # noqa: E402
from promo_villains import COVERS, DIGESTS, PROMO, TAG, ref  # noqa: E402
from registry_allowlist import allowed, refused_paths  # noqa: E402

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"\n        {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


LAB = (REPO / "gitops/ai-layer/web/lab.html").read_text(encoding="utf-8")
C2 = LAB[LAB.find("Challenge 2: Deploy"):LAB.find("Challenge 3: Get the secret")]
README = (REPO / "images/villains/README.md").read_text(encoding="utf-8")
POLICY = next(d for d in yaml.safe_load_all((REPO / "policies/kyverno/restrict-image-registries.yaml").read_text()) if d)

print("== the roster is lab-platform's ten, by digest ==")
check("ten villains, each with a sha256 digest",
      len(DIGESTS) == 10 and all(re.fullmatch(r"sha256:[0-9a-f]{64}", d) for d in DIGESTS.values()), str(DIGESTS))
roster = set(re.findall(r"`([a-z][a-z-]+)`", README.split("## Roster", 1)[1].split("## How", 1)[0]))
check("images/villains/README.md's roster is the same ten", roster == set(DIGESTS), str(sorted(roster ^ set(DIGESTS))))
check(f"the roster heading names {PROMO}/<name>:{TAG}", f"## Roster (all `{PROMO}/<name>:{TAG}`)" in README)
check("the three covers are on the roster", set(COVERS) <= set(DIGESTS))

print("== /lab hands out the three covers by their :v1 tag ==")
handed = re.findall(r'<div class="cmd noterm" onclick="cp\(this\)">([^<\s]+)<button', C2)
check("the copy boxes are the three cover references, in order", handed == [ref(n) for n in COVERS], str(handed))
check("no digest in Challenge 2: the lesson is the path, and a digest would read as vetted", "@sha256" not in C2)
check("the stuck prompt asks for promo-mascot at its promo/ reference",
      f"One-replica Deployment named promo-mascot, image {ref('promo-mascot')}. " in C2)
check("the fix names the path the villain lives on", f"<code class=\"inl\">{PROMO}/...</code>" in C2)

print("== every C2 copy names the promo/ references, none the Docker Hub ones ==")
COPIES = ("gitops/ai-layer/web/lab.html", "challenges/LAB-TEXT.md", "challenges/PROMPT-CATALOG.md",
          "challenges/c2-villain-image/README.md", "challenges/c2-villain-image/fallback.kubectl.sh",
          "challenges/01-cncf-wall/toggle-kyverno-enforce.sh", "verify/kubecon_probe.py")
for path in COPIES:
    text = (REPO / path).read_text(encoding="utf-8")
    old = [n for n in DIGESTS if f"docker.io/peopleforrester/{n}:latest" in text and n != "joker"]
    check(f"{path} names no Docker Hub villain other than C6's Joker", not old, str(old))
    check(f"{path} names the promo/ path", f"{PROMO}/" in text)
check("the probe's C2 Deployment is promo-mascot's reference", kp.VILLAIN_IMAGE == ref("promo-mascot"), kp.VILLAIN_IMAGE)
fallback = (REPO / "challenges/c2-villain-image/fallback.kubectl.sh").read_text(encoding="utf-8")
villain = re.search(r'^readonly VILLAIN="([^"]+)"$', fallback, re.M)
check("the C2 fallback creates a roster villain at its promo/ reference",
      villain is not None and villain.group(1) in DIGESTS
      and f'readonly IMAGE="{PROMO}/${{VILLAIN}}:{TAG}"' in fallback)

print("== restrict-image-registries refuses the path, on ghcr.io and through an ECR cache ==")
check("ghcr.io stays on the allow-list (lab-platform's mirror/ and web images run in apps and agent)",
      allowed("ghcr.io/peopleforrester/lab-platform/web:v1")
      and allowed("ghcr.io/peopleforrester/lab-platform/mirror/mcp/grafana:latest-208f8ea16064"))
check("the policy's refusedPaths names lab-platform's promo/ path", any(p in f"{PROMO}/x" for p in refused_paths()),
      str(refused_paths()))
for name in DIGESTS:
    check(f"{ref(name)} is refused", not allowed(ref(name)))
cache = "123456789012.dkr.ecr.us-west-2.amazonaws.com/ghcr/" + ref("joker").split("/", 1)[1]
check("and through an ECR pull-through cache", not allowed(cache), cache)
expr = " ".join(v["expression"] for v in POLICY["spec"]["variables"] if v["name"] in ("imageAllowed", "alreadyViolating"))
check("both the admission check and the UPDATE exemption read refusedPaths", expr.count("variables.refusedPaths") == 2)

print("== the refusal /lab quotes is the policy's message ==")
msg = " ".join(POLICY["spec"]["validations"][0]["message"].split())
pre = re.search(r'<pre class="yaml">(restrict-image-registries: .*?)</pre>', C2, re.S)
quoted = " ".join(html.unescape(re.sub(r"<[^>]+>", "", pre.group(1))).split()) if pre else ""
check("the lab's report line is restrict-image-registries' message", quoted == f"restrict-image-registries: {msg}",
      f"{quoted!r} != {msg!r}")
check("and it names the refused path", "lab-platform/promo/" in msg, msg)

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    sys.exit(1)
print("All promo villain checks passed.")
