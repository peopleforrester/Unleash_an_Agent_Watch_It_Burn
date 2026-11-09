# ABOUTME: Offline check of the /chat code-of-conduct guardrail in the cluster root (#1279): the spike's chosen settings
# ABOUTME: with BLOCK on input, and guard-proxy's grant reaching ApplyGuardrail on that guardrail and nothing more.
"""Why. The spike (#1267, docs/research/2026-11-09-coc-floor/) measured one definition, guardrail-standard.json, with
every filter in detect mode, and chose a mix of it: HATE, INSULTS and SEXUAL at MEDIUM, VIOLENCE at LOW, MISCONDUCT
and PROMPT_ATTACK off, Standard tier on the US cross-Region profile, "Keep it kind." as the block message. Its zero
stage false positives hold for that mix only: MISCONDUCT at MEDIUM flags 25 stage texts. So the Terraform is held to
the measured file and to the README's choice, and the grant to guard-proxy's own ServiceAccount, by name in the
Deployment. What the simulator says of the grant is check 4 of the policy pipeline (infra/org/effect-tests.yaml,
verify/test_iam_policy_aws.py); that the provider plans it is verify/test_iam_policy_structural.py's render.

Offline: python3 and PyYAML."""
from __future__ import annotations

import json
import pathlib
import re
import sys

import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
MAIN_TF = REPO / "infra/terraform/aws/cluster/main.tf"
SPIKE = REPO / "docs/research/2026-11-09-coc-floor"
RESOURCES = REPO / "gitops/ai-layer/resources.yaml"
failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"\n        {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def block(text: str, header: str, path: pathlib.Path) -> str:
    """The brace-balanced block that starts at `header`; exits naming the anchor when it is not there."""
    i = text.find(header)
    if i < 0:
        sys.exit(f"anchor missing: {header!r} is not in {path.relative_to(REPO)}")
    depth, start = 0, text.index("{", i)
    for j in range(start, len(text)):
        depth += {"{": 1, "}": -1}.get(text[j], 0)
        if depth == 0:
            return text[i:j + 1]
    sys.exit(f"unbalanced block after {header!r} in {path.relative_to(REPO)}")


tf = MAIN_TF.read_text(encoding="utf-8")
measured = json.loads((SPIKE / "guardrail-standard.json").read_text(encoding="utf-8"))
readme = (SPIKE / "README.md").read_text(encoding="utf-8")
locals_ = block(tf, "locals {\n  coc_guardrail_profile", MAIN_TF)
guardrail = block(tf, 'resource "aws_bedrock_guardrail" "coc"', MAIN_TF)
version = block(tf, 'resource "aws_bedrock_guardrail_version" "coc"', MAIN_TF)
grant = block(tf, 'resource "aws_iam_policy" "guard_proxy_guardrail"', MAIN_TF)
pod_identity = block(tf, 'module "guard_proxy_pod_identity"', MAIN_TF)

print("the guardrail is the spike's choice")
filters = dict(re.findall(r"^\s+([A-Z_]+)\s*=\s*\"(LOW|MEDIUM|HIGH)\"", block(locals_, "coc_guardrail_filters = {", MAIN_TF), re.M))
CHOSEN = {"HATE": "MEDIUM", "INSULTS": "MEDIUM", "SEXUAL": "MEDIUM", "VIOLENCE": "LOW"}
check("HATE, INSULTS and SEXUAL at MEDIUM, VIOLENCE at LOW", filters == CHOSEN, f"{filters}")
for phrase in ("HATE, INSULTS and SEXUAL at MEDIUM", "VIOLENCE at LOW", "MISCONDUCT and PROMPT_ATTACK stay off"):
    if phrase not in " ".join(readme.split()):
        sys.exit(f"anchor missing: {phrase!r} is not in {(SPIKE / 'README.md').relative_to(REPO)}")
check("which is the README's choice, word for word, so a change to one is a change to both", True)
measured_types = {f["type"] for f in measured["contentPolicyConfig"]["filtersConfig"]}
check("each chosen filter is one the spike measured", set(CHOSEN) <= measured_types, f"{sorted(measured_types)}")
check("MISCONDUCT and PROMPT_ATTACK are off: neither is named in the guardrail or its filters",
      not re.search(r"MISCONDUCT|PROMPT_ATTACK", locals_ + guardrail))
check("the managed profanity list the spike also measured is not added (the term floor covers it)",
      "word_policy_config" not in guardrail)
check("Standard tier", 'tier_config = [{ tier_name = "STANDARD" }]' in guardrail
      and measured["contentPolicyConfig"]["tierConfig"]["tierName"] == "STANDARD")
profile = re.search(r'coc_guardrail_profile\s*=\s*"([^"]+)"', locals_)
check("on the profile the spike measured", profile is not None
      and profile.group(1) == measured["crossRegionConfig"]["guardrailProfileIdentifier"] == "us.guardrail.v1:0")
check("which the guardrail names as an ARN in its own Region", re.search(
    r'guardrail_profile_identifier = "arn:aws:bedrock:\$\{var\.region\}:[^"]*:guardrail-profile/\$\{local\.coc_guardrail_profile\}"',
    guardrail) is not None)
msg = re.search(r'coc_guardrail_message\s*=\s*"([^"]+)"', locals_)
check("the block message is the measured one, on input and output", msg is not None
      and msg.group(1) == measured["blockedInputMessaging"] == measured["blockedOutputsMessaging"] == "Keep it kind."
      and "blocked_input_messaging   = local.coc_guardrail_message" in guardrail
      and "blocked_outputs_messaging = local.coc_guardrail_message" in guardrail)
check("every filter BLOCKs on input, where the spike only detected",
      'input_action   = "BLOCK"' in guardrail and "input_enabled  = true" in guardrail
      and {f["inputAction"] for f in measured["contentPolicyConfig"]["filtersConfig"]} == {"NONE"})
check("and is not evaluated on output, which guard-proxy never sends",
      'output_action   = "NONE"' in guardrail and "output_enabled  = false" in guardrail)
check("each filter takes its strength from the chosen map", "for_each = local.coc_guardrail_filters" in guardrail
      and "input_strength = filters_config.value" in guardrail)
check("tagged consumer = guard-proxy, which the grant matches", 'merge(local.fleet_tags, { consumer = "guard-proxy" })' in guardrail)
check("a numbered version is published from it, and kept when the next replaces it",
      "guardrail_arn = aws_bedrock_guardrail.coc.guardrail_arn" in version and "skip_destroy  = true" in version)

print("guard-proxy's grant is ApplyGuardrail on that guardrail and nothing more")
deployment = next(d for d in yaml.safe_load_all(RESOURCES.read_text(encoding="utf-8"))
                  if d and d.get("kind") == "Deployment" and d["metadata"]["name"] == "guard-proxy")
sa = deployment["spec"]["template"]["spec"]["serviceAccountName"]
check("guard-proxy runs as guard-proxy-reader", sa == "guard-proxy-reader", sa)
check("the Pod Identity association binds that ServiceAccount in agent",
      f'namespace       = "agent"\n      service_account = "{sa}"' in pod_identity, pod_identity)
check("the role carries the canonical boundary",
      "permissions_boundary_arn = data.aws_iam_policy.permissions_boundary.arn" in pod_identity)
check("and its one policy is the guardrail grant",
      "additional_policy_arns = { coc_guardrail = aws_iam_policy.guard_proxy_guardrail.arn }" in pod_identity)
actions = re.findall(r"Action\s*=\s*(\[[^\]]*\]|\"[^\"]*\")", grant)
check("both statements allow bedrock:ApplyGuardrail alone", actions == ['["bedrock:ApplyGuardrail"]'] * 2, f"{actions}")
resources = re.findall(r'Resource\s*=\s*"([^"]+)"', grant)
check("on guardrails in the cluster's Region and the US guardrail profile, nothing else", resources == [
    "arn:aws:bedrock:${var.region}:${data.aws_caller_identity.current.account_id}:guardrail/*",
    "arn:aws:bedrock:*:${data.aws_caller_identity.current.account_id}:guardrail-profile/${local.coc_guardrail_profile}"],
    f"{resources}")
check("the guardrail statement holds to this cluster's guardrail by its tags",
      all(s in grant for s in ('"aws:ResourceTag/project"                     = local.fleet_tags.project',
                               '"aws:ResourceTag/attendee"                    = var.name',
                               '"aws:ResourceTag/consumer"                    = "guard-proxy"')))
check("both statements hold to guard-proxy's ServiceAccount on this cluster",
      grant.count(f'"aws:PrincipalTag/kubernetes-service-account" = "{sa}"') == 2
      and grant.count('"aws:PrincipalTag/eks-cluster-name"           = var.name') == 2
      and grant.count('"aws:PrincipalTag/kubernetes-namespace"       = "agent"') == 2)
check("the grant does not name the guardrail's ARN, unknown at plan, which would blind the policy pipeline",
      "aws_bedrock_guardrail" not in grant)

print()
if failures:
    print(f"FAIL: {len(failures)} check(s): " + "; ".join(failures))
    sys.exit(1)
print("PASS: the code-of-conduct guardrail and guard-proxy's grant")
