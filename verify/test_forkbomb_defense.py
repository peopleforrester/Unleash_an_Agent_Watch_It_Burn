# ABOUTME: Render-gate check for the fork-bomb defense: PID-limit is the block, Falco->Talon is response.
import pathlib, sys, yaml
REPO = pathlib.Path(__file__).resolve().parents[1]
falco = yaml.safe_load((REPO/"gitops/apps/falco.yaml").read_text())
sidekick = yaml.safe_load((REPO/"gitops/apps/falcosidekick.yaml").read_text())
talon = yaml.safe_load((REPO/"gitops/apps/falco-talon.yaml").read_text())
node = yaml.safe_load((REPO/"infra/node-config/pid-limit-nodeadm.yaml").read_text())
cr = falco["spec"]["source"]["helm"]["valuesObject"]["customRules"]
# 00- prefix so the fork-bomb rule loads first in rules.d and is not shadowed by the generic
# "Exec Into Pod Detected" rule (Falco fires only the first matching rule per event).
forkrules = yaml.safe_load(cr.get("00-workshop-forkbomb-rules.yaml", "[]"))
talon_rules = talon["spec"]["source"]["helm"]["valuesObject"].get("rulesOverride", "")
FORK_RULE = "Fork Bomb In Workload Container"
failures = []
def check(n, c):
    print(f"  {'PASS' if c else 'FAIL'}  {n}");  failures.append(n) if not c else None

check("PID limit (the real block) sets podPidsLimit", node["spec"]["kubelet"]["config"]["podPidsLimit"] >= 1)
# The PID cap is inert unless the nodegroup actually delivers it. Confirm every cluster config ships
# podPidsLimit via overrideBootstrapCommand (the live gate run added this; dry-run + node pids.max verified).
for rel in ["infra/test-cluster/cluster.yaml", "infra/attendee-cluster/cluster.yaml", "infra/burn-clusters/cluster.yaml"]:
    cfg = yaml.safe_load((REPO / rel).read_text())
    obc = " ".join((ng.get("overrideBootstrapCommand", "") or "") for ng in cfg.get("managedNodeGroups", []))
    check(f"{rel}: nodegroup delivers podPidsLimit via overrideBootstrapCommand", "podPidsLimit" in obc)
# Falco fires only the FIRST matching rule per event and rules.d loads alphabetically; the fork-bomb
# rules file must sort before any custom file that defines the generic "Exec Into Pod Detected" rule,
# or that rule shadows the fork-bomb rule and nothing routes to Talon (caught live, watch-it-burn-test).
fb_key = next((k for k in cr if "forkbomb" in k), "")
exec_keys = [k for k, v in cr.items() if "Exec Into Pod Detected" in (v or "")]
check("fork-bomb rules file sorts before the generic exec-detection file (not shadowed)",
      bool(fb_key) and all(fb_key < k for k in exec_keys))
check("Falco has a fork-bomb detection rule", any(r.get("rule") == FORK_RULE for r in forkrules if isinstance(r, dict)))
check("the fork-bomb rule is CRITICAL (so it routes to Talon)", any(r.get("rule")==FORK_RULE and r.get("priority")=="CRITICAL" for r in forkrules if isinstance(r,dict)))
check("Falcosidekick forwards to Talon", sidekick["spec"]["source"]["helm"]["valuesObject"]["config"].get("talon", {}).get("address","").startswith("http://falco-talon"))
check("Talon terminates the pod on the fork-bomb rule",
      "kubernetes:terminate" in talon_rules and FORK_RULE in talon_rules)
check("Talon chart pinned (verify-at-build noted)", talon["spec"]["source"]["targetRevision"])
if failures: print(f"\nFAILED: {len(failures)}"); sys.exit(1)
print("\nAll fork-bomb-defense checks passed.")
