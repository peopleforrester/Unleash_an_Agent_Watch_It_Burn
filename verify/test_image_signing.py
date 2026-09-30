# ABOUTME: Render gate for image signing: the policy enforces, its key matches the committed one, and
# ABOUTME: verification stays offline so a cluster running Challenge 1's default-deny egress still works.
"""Why this exists (#331, #415).

`verify-image-signatures.yaml` spent months claiming Audit in its header while its rule said Enforce,
scoped to a Harbor host nothing pulled from, with a keyless attestor whose subject was the literal
string `https://github.com/<org>/<repo>/.github/workflows/*`. It could never have verified anything.
Nothing failed, which said only that no matching image was being admitted.

So the checks below are about the ways this specific file has been wrong or could quietly become wrong
again: a placeholder attestor, a key that has drifted from the one we sign with, a scope so wide it
catches third-party images, and a Rekor dependency that would make admission fail the moment attendees
seal the cluster in Challenge 1.

What this file does NOT check is whether the images are actually signed. That needs the registry, so it
lives in `verify/sign-images.sh --check`, which is the thing to run before deploying.
"""
from __future__ import annotations

import pathlib
import sys

import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
POLICY = REPO / "policies/kyverno/verify-image-signatures.yaml"
PUBKEY = REPO / "policies/cosign/watch-it-burn.pub"
OUR_REGISTRY = "ghcr.io/peopleforrester/watch-it-burn"

failures: list[str] = []


def check(name: str, cond: bool) -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        failures.append(name)


raw = POLICY.read_text(encoding="utf-8")
policy = next(d for d in yaml.safe_load_all(raw) if d)
rule = policy["spec"]["rules"][0]
vi = rule["verifyImages"][0]
entry = vi["attestors"][0]["entries"][0]

print("== the policy enforces, rather than describing an intent ==")
check("failureAction is Enforce", vi.get("failureAction") == "Enforce")
check("a signature is required, not optional", vi.get("required") is True)
check("the digest is verified", vi.get("verifyDigest") is True)
# The header used to say Audit while the rule said Enforce. Whatever the file does, it has to say so.
flat = " ".join(raw.split())
check("the header does not claim Audit while the rule enforces",
      not ("Starts in Audit" in flat or "starts in Audit" in flat))

print("== the attestor is a real key, not a placeholder ==")
check("it is a keys attestor", "keys" in entry)
check("it is NOT a keyless attestor", "keyless" not in entry)
# Tested against the PARSED policy, not the raw file: the header legitimately quotes the old
# placeholder while explaining what was wrong with it, and a placeholder only does harm in a field.
config = yaml.safe_dump(policy)
check("no template placeholder survives in any field",
      "<org>" not in config and "<repo>" not in config and "verify-at-build" not in config)

print("== the committed key and the policy's key are the same key ==")
check("the public key file exists", PUBKEY.exists())
if PUBKEY.exists():
    on_disk = PUBKEY.read_text(encoding="utf-8").strip()
    in_policy = (entry.get("keys") or {}).get("publicKeys", "").strip()
    check("the policy embeds it verbatim", in_policy == on_disk)
    check("it is a PEM public key", on_disk.startswith("-----BEGIN PUBLIC KEY-----")
          and on_disk.endswith("-----END PUBLIC KEY-----"))
    # A private key must never reach this repo. The pair lives in the mrf-secrets key store.
    check("no private key is committed alongside it",
          not any(p.suffix == ".key" for p in PUBKEY.parent.iterdir())
          and "BEGIN ENCRYPTED" not in raw and "PRIVATE KEY" not in raw)

print("== verification works on a cluster with no egress ==")
# Challenge 1 has attendees apply default-deny egress. Anything Kyverno must fetch from the internet
# after that point is a control that stops working halfway through the workshop.
keys = entry.get("keys") or {}
check("the transparency log is not consulted at admission",
      (keys.get("rekor") or {}).get("ignoreTlog") is True)
check("certificate-transparency SCT is not consulted either",
      (keys.get("ctlog") or {}).get("ignoreSCT") is True)

print("== the scope catches our images and nothing else ==")
refs = vi.get("imageReferences") or []
check(f"scoped to our registry ({refs})", f"{OUR_REGISTRY}*" in refs)
check("not scoped to everything", "*" not in refs)
# Carried over from the version of this file that this one replaced. That version asserted the policy
# was scoped to Harbor ONLY, and rescoping to ghcr would have dropped the Harbor requirement without
# anything noticing. Harbor is documented in infra/harbor/ and allowlisted, so it stays in scope.
check("harbor is still required to be signed", "harbor.agenticburn.com/*" in refs)
for foreign in ("docker.io/library/nginx:1.27-alpine", "cr.agentgateway.dev/agentgateway:v1.5.0",
                "ghcr.io/open-telemetry/opentelemetry-operator/autoinstrumentation-python:0.63b1",
                "registry.k8s.io/pause:3.9"):
    # A glob of the form "prefix*" matches only references starting with that prefix.
    matched = any(foreign.startswith(r.rstrip("*")) for r in refs)
    check(f"does not demand a signature from {foreign.split('/')[0]}", not matched)
ours = f"{OUR_REGISTRY}:workshop-mcp@sha256:" + "0" * 64
check("does demand one from our own registry",
      any(ours.startswith(r.rstrip("*")) for r in refs))

print("== it applies wherever our images run, not in one namespace ==")
# The old rule was scoped to the `apps` namespace while the ai-layer runs in `agent`, so the control
# could be sidestepped by deploying elsewhere.
check("the rule is not namespace-scoped", "namespaces" not in str(rule.get("match")))
check("it matches Pods", "Pod" in str(rule.get("match")))

print("== the registry allowlist and the signature rule agree ==")
# Also carried over. A signature rule naming a registry the allowlist forbids can never fire, and an
# allowlisted registry with no signature rule is an unguarded path.
allow = yaml.safe_load((REPO / "policies/kyverno/restrict-image-registries.yaml").read_text(encoding="utf-8"))
allow_pat = allow["spec"]["rules"][0]["validate"]["pattern"]["spec"]["containers"][0]["image"]
check("the allowlist permits Harbor", "harbor.agenticburn.com/*" in allow_pat)
check("the allowlist still permits the public demo registries", "docker.io/library/*" in allow_pat)
check("every registry the signature rule names is allowlisted",
      all(r.rstrip("*").split("/")[0] in allow_pat for r in refs))

print("== the signing procedure is written down and runnable ==")
script = REPO / "verify/sign-images.sh"
check("verify/sign-images.sh exists and is executable",
      script.exists() and script.stat().st_mode & 0o111)
if script.exists():
    body = script.read_text(encoding="utf-8")
    # cosign 3.x writes a bundle format Kyverno 1.19 cannot read. The script must refuse it rather
    # than produce signatures that verify locally and fail at admission.
    check("the script refuses cosign 3.x", "refusing to sign with cosign" in body)
    check("and says why in the file rather than only in a commit message",
          "DO NOT VERIFY UNDER KYVERNO" in body)
check("key custody is documented", (REPO / "policies/cosign/README.md").exists())
# Carried over: the Harbor path has its own signing script and it must use the same key and the same
# cosign constraint, or Harbor images would be signed in a way this policy cannot verify.
harbor_sign = REPO / "infra/harbor/sign-and-push.sh"
check("the Harbor script exists", harbor_sign.exists())
if harbor_sign.exists():
    hs = harbor_sign.read_text(encoding="utf-8")
    check("the Harbor script signs with cosign", "cosign" in hs and "sign" in hs)
    check("the Harbor script uses the KEY, not keyless", "--key" in hs and "COSIGN_EXPERIMENTAL=1 cosign sign --yes" not in hs)
    check("the Harbor script refuses cosign 3.x too", "refusing to sign with cosign" in hs)
    check("the Harbor script signs a digest, not a tag", "RepoDigests" in hs)

if failures:
    print(f"\nFAILED: {len(failures)} check(s)")
    sys.exit(1)
print("\nAll image-signing checks passed.")
