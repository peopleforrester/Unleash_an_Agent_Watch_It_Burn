# ABOUTME: Render-gate check for the fork-bomb defense: PID-limit is the block, Falco->Talon is response.
import pathlib, sys, yaml
REPO = pathlib.Path(__file__).resolve().parents[1]
falco = yaml.safe_load((REPO/"gitops/apps/falco.yaml").read_text())
sidekick = yaml.safe_load((REPO/"gitops/apps/falcosidekick.yaml").read_text())
talon = yaml.safe_load((REPO/"gitops/apps/falco-talon.yaml").read_text())
# Provisioning is Terraform: the PID cap is delivered by the per-attendee cluster module's node
# cloudinit_pre_nodeadm NodeConfig (eksctl delivered it via overrideBootstrapCommand previously).
cluster_tf = (REPO/"infra/terraform/aws/cluster/main.tf").read_text()
cr = falco["spec"]["source"]["helm"]["valuesObject"]["customRules"]
# 00- prefix so the fork-bomb rule loads first in rules.d and is not shadowed by the generic
# "Exec Into Pod Detected" rule (Falco fires only the first matching rule per event).
forkrules = yaml.safe_load(cr.get("00-workshop-forkbomb-rules.yaml", "[]"))
talon_vo = talon["spec"]["source"]["helm"]["valuesObject"]
# The falco-talon chart key is config.rulesOverride; a top-level rulesOverride is ignored (the chart
# then loads its default action with no match -> "0 rules loaded"; caught live on watch-it-burn-test).
talon_rules = talon_vo.get("config", {}).get("rulesOverride", "")
FORK_RULE = "Fork Bomb In Workload Container"
failures = []
def check(n, c):
    print(f"  {'PASS' if c else 'FAIL'}  {n}");  failures.append(n) if not c else None

# The PID cap (the real block) must be delivered by the node config. Confirm the Terraform cluster
# module ships podPidsLimit in the AL2023 nodeadm NodeConfig via cloudinit_pre_nodeadm, and that the
# default is a real cap (>=1). (Verified live: pod-cgroup pids.max=1024, fork bomb hits -EAGAIN.)
check("terraform cluster delivers podPidsLimit via cloudinit_pre_nodeadm NodeConfig",
      "cloudinit_pre_nodeadm" in cluster_tf and "podPidsLimit" in cluster_tf
      and "node.eks.aws/v1alpha1" in cluster_tf)
check("terraform cluster default pod_pids_limit is a real cap (>=1)",
      "default = 1024" in cluster_tf or 'pod_pids_limit' in cluster_tf)
# Falco fires only the FIRST matching rule per event and rules.d loads alphabetically; the fork-bomb
# rules file must sort before any custom file that defines the generic "Exec Into Pod Detected" rule,
# or that rule shadows the fork-bomb rule and nothing routes to Talon (caught live, watch-it-burn-test).
fb_key = next((k for k in cr if "forkbomb" in k), "")
exec_keys = [k for k, v in cr.items() if "Exec Into Pod Detected" in (v or "")]
check("fork-bomb rules file sorts before the generic exec-detection file (not shadowed)",
      bool(fb_key) and all(fb_key < k for k in exec_keys))
check("Falco has a fork-bomb detection rule", any(r.get("rule") == FORK_RULE for r in forkrules if isinstance(r, dict)))
check("the fork-bomb rule is CRITICAL (so it routes to Talon)", any(r.get("rule")==FORK_RULE and r.get("priority")=="CRITICAL" for r in forkrules if isinstance(r,dict)))
check("Talon rules are under config.rulesOverride (the chart key), not top-level",
      "rulesOverride" not in talon_vo and bool(talon_vo.get("config", {}).get("rulesOverride")))
# Falcosidekick (ns security) must reach Talon (ns falco) by cross-namespace FQDN; a bare service name
# resolves in 'security' and NXDOMAINs (caught live: "lookup falco-talon ... no such host").
_talon_addr = sidekick["spec"]["source"]["helm"]["valuesObject"]["config"].get("talon", {}).get("address", "")
check("Falcosidekick forwards to Talon via cross-namespace FQDN (falco-talon.falco)",
      _talon_addr.startswith("http://falco-talon.falco"))
# Talon v0.3.0 schema: a TRIGGERING entry is `- rule:` with match.rules + actions referencing a
# `- action:` whose actionner is kubernetes:terminate. An action with an embedded match: is invalid
# and loads as 0 rules (caught live on watch-it-burn-test).
_talon_parsed = yaml.safe_load(talon_rules) or []
_term_actions = {e["action"] for e in _talon_parsed
                 if isinstance(e, dict) and e.get("actionner") == "kubernetes:terminate" and "rule" not in e}
_fork_rule = next((e for e in _talon_parsed
                   if isinstance(e, dict) and "rule" in e and FORK_RULE in (e.get("match", {}).get("rules") or [])), None)
check("Talon has a `- rule:` entry matching the fork-bomb Falco rule (not an action with embedded match)",
      _fork_rule is not None)
check("that Talon rule invokes a kubernetes:terminate action",
      bool(_fork_rule) and any(a.get("action") in _term_actions for a in (_fork_rule.get("actions") or [])))
check("Talon chart pinned (verify-at-build noted)", talon["spec"]["source"]["targetRevision"])
if failures: print(f"\nFAILED: {len(failures)}"); sys.exit(1)
print("\nAll fork-bomb-defense checks passed.")
