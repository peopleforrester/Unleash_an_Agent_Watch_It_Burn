# ABOUTME: Offline check of #784's model rename in Agent Observability's copy: one rule set per Bedrock ModelConfig,
# ABOUTME: keyed as fleet.sh writes monitoring/bedrock-profile-models, loaded on every profile, and never in APM's copy.
"""Datadog cannot price a model call named by an application profile ARN, so the copy names the system id.

Live, each Bedrock ModelConfig calls the cluster's tagged application profile (#513), and kagent's generate_content
spans name that ARN. On 2026-11-05 every such row in Whitney's sandbox org read cost_estimate_status
skipped_unsupported_model_pricing; a row named us.amazon.nova-pro-v1:0 read success. transform/llmobs_model, in the
traces/llmobs pipeline only, renames the ARN to the system id the ModelConfig commits. The ARNs are per cluster: fleet.sh
pin_bedrock_profiles writes them to monitoring/bedrock-profile-models, and the collector loads that ConfigMap with
extraEnvsFrom. This test holds the three ends together:

  - the tiers and system ids in the rules are exactly the Bedrock ModelConfigs in gitops/ai-layer/resources.yaml;
  - each rule reads the key fleet.sh's profile_models_key writes for that ModelConfig, with a default no name equals;
  - every profile loads the ConfigMap fleet.sh writes, optional, and runs the rules in traces/llmobs only.

verify/test_collector_llmobs_model_e2e.py runs the rules through the real collector; verify/test_pin_bedrock_profiles.sh
runs fleet.sh's half.
"""
from __future__ import annotations

import pathlib
import re
import subprocess
import sys

import yaml

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from collector_render import REPO, collector_config, helm_values  # noqa: E402
# Offline means offline (#859): the test sources fleet.sh, so aws, kubectl, eksctl, terraform and helm are stubs that
# log the call and fail, even when the test is run by hand (verify/no_cloud.py). The last check reads the log.
import no_cloud  # noqa: E402
no_cloud.setup()

FLEET = REPO / "infra/terraform/fleet/fleet.sh"
RESOURCES = REPO / "gitops/ai-layer/resources.yaml"
PROC = "transform/llmobs_model"
PROFILES = ("instructor", "attendee", "burn")

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"\n        {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def fleet(snippet: str) -> str:
    """Runs a line of bash with fleet.sh's functions loaded. Sourcing defines functions and runs nothing that calls out."""
    out = subprocess.run(["bash", "-c", f"source '{FLEET}' >/dev/null 2>&1; {snippet}"], capture_output=True, text=True,
                         cwd=REPO)
    return out.stdout.strip()


configs = {d["metadata"]["name"]: d["spec"]["model"] for d in yaml.safe_load_all(RESOURCES.read_text(encoding="utf-8"))
           if d and d.get("kind") == "ModelConfig" and (d.get("spec") or {}).get("provider") == "Bedrock"}
print("== the rules are the Bedrock ModelConfigs, keyed as fleet.sh writes them ==")
check(f"resources.yaml commits the four Bedrock ModelConfigs ({sorted(configs)})",
      sorted(configs) == ["bedrock-haiku", "bedrock-nova", "bedrock-opus", "bedrock-sonnet"])
key_of = {name: fleet(f"profile_models_key {name}") for name in configs}
check("fleet.sh names each key WIB_BEDROCK_PROFILE_<TIER>", key_of.get("bedrock-nova") == "WIB_BEDROCK_PROFILE_NOVA"
      and all(re.fullmatch(r"WIB_BEDROCK_PROFILE_[A-Z0-9_]+", k) for k in key_of.values()), str(key_of))
cm_name = fleet('echo "${PROFILE_MODELS_CM}"')
check("fleet.sh writes the ConfigMap bedrock-profile-models", cm_name == "bedrock-profile-models", cm_name)

vals = helm_values("instructor")
statements = [st for group in vals["config"]["processors"][PROC]["trace_statements"] for st in group["statements"]]
contexts = [group["context"] for group in vals["config"]["processors"][PROC]["trace_statements"]]
check(f"{PROC} runs in span context", contexts == ["span"], str(contexts))
check(f"{PROC} ignores a statement error rather than dropping the batch",
      vals["config"]["processors"][PROC].get("error_mode") == "ignore")
RULE = re.compile(r'^set\((?P<target>attributes\["gen_ai\.(?:request|response)\.model"\]|name), "(?P<new>[^"]+)"\) '
                  r'where (?P<field>attributes\["gen_ai\.(?:request|response)\.model"\]|name) == '
                  r'"(?P<prefix>(?:generate_content )?)\$\{env:(?P<key>[A-Z0-9_]+):-(?P<default>[^}]*)\}"$')
# The ARN is kept on the copy under an attribute of its own (#876), before the rename overwrites it.
KEEP = re.compile(r'^set\(attributes\["witb\.bedrock\.application_profile"\], attributes\["gen_ai\.request\.model"\]\) '
                  r'where attributes\["gen_ai\.request\.model"\] == "\$\{env:(?P<key>[A-Z0-9_]+):-(?P<default>[^}]*)\}"$')
kept = [KEEP.match(st) for st in statements]
parsed = [RULE.match(st) for st in statements]
check(f"every statement keeps the ARN or renames one field, each from one key ({len(statements)} statements)",
      all(k or m for k, m in zip(kept, parsed)), str([st for st, k, m in zip(statements, kept, parsed) if not (k or m)]))
rules = {(m["key"], m["target"]): m for m in parsed if m}
for name, model in sorted(configs.items()):
    key = key_of[name]
    first = next((i for i, st in enumerate(statements) if f"{{env:{key}:" in st), None)
    check(f"{name}: the copy first keeps the ARN it calls as witb.bedrock.application_profile",
          first is not None and kept[first] is not None and kept[first]["key"] == key,
          statements[first] if first is not None else "no statement")
    for target, prefix in (('attributes["gen_ai.request.model"]', ""), ('attributes["gen_ai.response.model"]', ""),
                           ("name", "generate_content ")):
        m = rules.get((key, target))
        check(f"{name}: {target} reads {key} and becomes {prefix}{model}",
              m is not None and m["field"] == target and m["prefix"] == prefix and m["new"] == prefix + model,
              m.group(0) if m else "no rule")
check("and nothing else: four rules per Bedrock ModelConfig", len(statements) == 4 * len(configs), str(len(statements)))
defaults = {m["default"] for m in parsed + kept if m}
check("every key falls back to a value no model name equals, so an unpinned cluster renames nothing",
      defaults == {"unpinned"}, str(defaults))

print("== every profile loads the map and runs the rules on Agent Observability's copy only ==")
for profile in PROFILES:
    hv = helm_values(profile)
    refs = [e.get("configMapRef") or {} for e in hv.get("extraEnvsFrom") or []]
    check(f"{profile}: the collector loads every key of {cm_name}, optional so a cluster without it still starts",
          {"name": cm_name, "optional": True} in refs, str(refs))
    for secret in (True, False):
        conf = collector_config(profile, datadog_secret=secret)
        pipes = conf["service"]["pipelines"]
        lprocs = pipes.get("traces/llmobs", {}).get("processors", [])
        label = f"{profile}, datadog-secret {'present' if secret else 'absent'}"
        check(f"{label}: traces/llmobs runs {PROC} after the copy takes its own ids, before its filter",
              PROC in lprocs and lprocs.index("transform/llmobs_one_root") < lprocs.index(PROC)
              < lprocs.index("filter/llmobs_one_root"), str(lprocs))
        others = sorted(p for p, pipe in pipes.items() if p != "traces/llmobs" and PROC in pipe.get("processors", []))
        check(f"{label}: no other pipeline renames, so APM keeps the ARN the bill's tags trace", not others, str(others))
        check(f"{label}: the rules are the same on this profile", conf["processors"][PROC] == vals["config"]["processors"][PROC])

_calls = no_cloud.calls()
check("no check above called aws, kubectl, eksctl, terraform or helm", not _calls, _calls)

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All llmobs model-name checks passed.")
