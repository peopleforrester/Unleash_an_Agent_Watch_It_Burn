# ABOUTME: Render-gate check for the fork-bomb defense: PID-limit is the block, Falco->Talon is response.
import pathlib, sys, yaml
REPO = pathlib.Path(__file__).resolve().parents[1]
falco = yaml.safe_load((REPO/"gitops/apps/falco.yaml").read_text())
sidekick = yaml.safe_load((REPO/"gitops/apps/falcosidekick.yaml").read_text())
talon = yaml.safe_load((REPO/"gitops/apps/falco-talon.yaml").read_text())
node = yaml.safe_load((REPO/"infra/node-config/pid-limit-nodeadm.yaml").read_text())
cr = falco["spec"]["source"]["helm"]["valuesObject"]["customRules"]
forkrules = yaml.safe_load(cr.get("workshop-forkbomb-rules.yaml", "[]"))
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
check("Falco has a fork-bomb detection rule", any(r.get("rule") == FORK_RULE for r in forkrules if isinstance(r, dict)))
check("the fork-bomb rule is CRITICAL (so it routes to Talon)", any(r.get("rule")==FORK_RULE and r.get("priority")=="CRITICAL" for r in forkrules if isinstance(r,dict)))
check("Falcosidekick forwards to Talon", sidekick["spec"]["source"]["helm"]["valuesObject"]["config"].get("talon", {}).get("address","").startswith("http://falco-talon"))
check("Talon terminates the pod on the fork-bomb rule",
      "kubernetes:terminate" in talon_rules and FORK_RULE in talon_rules)
check("Talon chart pinned (verify-at-build noted)", talon["spec"]["source"]["targetRevision"])
if failures: print(f"\nFAILED: {len(failures)}"); sys.exit(1)
print("\nAll fork-bomb-defense checks passed.")
