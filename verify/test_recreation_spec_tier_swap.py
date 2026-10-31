# ABOUTME: docs/MASTER-RECREATION-SPEC.md says how a model tier reaches a cluster the way ai-layer and workshop-agent deliver
# ABOUTME: it: the committed default on a fresh cluster, a live patch of the Agent and MODEL_TIER on a running one.
#
# Why (#598). The spec's Key Decisions bullet said "Tier swaps by repointing the Agent modelConfig (commit + resync),
# never kubectl patch live." The ai-layer Application ignores the Agent's .spec.declarative.modelConfig and
# guard-proxy's MODEL_TIER env with RespectIgnoreDifferences=true, so on a running cluster a commit plus resync
# changes nothing, and decisions.md (2026-07-07, §4.6-d) recommends the live patch the spec forbade.
#
# Since #707 the Agent is the workshop-agent Application's, which ignores its modelConfig in the diff and syncs
# without RespectIgnoreDifferences: a commit of the tier alone still leaves the Agent Synced, and the next
# workshop-agent sync, for any other Agent change, applies the committed modelConfig and resets a live patch.
import pathlib, re, sys

import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
SPEC = "docs/MASTER-RECREATION-SPEC.md"
APP = "gitops/bootstrap/apps/ai-layer.yaml"
AGENT_APP = "gitops/bootstrap/apps/workshop-agent.yaml"
failures = []


def check(n, c, detail=""):
    print(f"  {'PASS' if c else 'FAIL'}  {n}" + (f"\n        {detail}" if (detail and not c) else ""))
    if not c:
        failures.append(n)


app = yaml.safe_load((REPO / APP).read_text(encoding="utf-8"))
agent_app = yaml.safe_load((REPO / AGENT_APP).read_text(encoding="utf-8"))


def ignored(application, kind, name):
    return [e for i in application["spec"].get("ignoreDifferences", []) if i.get("kind") == kind and i.get("name") == name
            for e in i.get("jqPathExpressions", [])]


def options(application):
    return application["spec"].get("syncPolicy", {}).get("syncOptions", [])


print(f"== {APP} and {AGENT_APP} keep the tier off the sync path on a running cluster ==")
check(f"{AGENT_APP} ignores the workshop-agent Agent's .spec.declarative.modelConfig",
      ".spec.declarative.modelConfig" in ignored(agent_app, "Agent", "workshop-agent"))
check(f"and syncs without RespectIgnoreDifferences, so a sync for another Agent change resets a live tier (#707)",
      "RespectIgnoreDifferences=true" not in options(agent_app))
check(f"{APP} ignores nothing on the Agent, which is not in its bundle (#707)", not ignored(app, "Agent", "workshop-agent"))
check(f"{APP} ignores guard-proxy's MODEL_TIER env",
      any("MODEL_TIER" in e for e in ignored(app, "Deployment", "guard-proxy")))
check("and its syncs respect the ignores (RespectIgnoreDifferences=true)", "RespectIgnoreDifferences=true" in options(app))

lines = (REPO / SPEC).read_text(encoding="utf-8").splitlines()

print(f"== {SPEC} does not call a tier swap commit + resync ==")
# The dated correction notes at the top are history, not claims about the build.
claims = [l for l in lines if not l.startswith(">")]
bad = [(i, l.strip()) for i, l in enumerate(lines, 1) if not l.startswith(">")
       and re.search(r"(?i)\btier swaps? by\b.*commit\s*\+\s*resync", l)]
check(f"no line says a tier swap is commit + resync (lines {[i for i, _ in bad]})", not bad,
      "; ".join(f"{i}: {l[:120]}" for i, l in bad))
bad = [(i, l.strip()) for i, l in enumerate(lines, 1) if not l.startswith(">")
       and re.search(r"(?i)\btier\b", l) and re.search(r"(?i)never `?kubectl patch`? live", l)]
check(f"no tier line forbids the live patch (lines {[i for i, _ in bad]})", not bad,
      "; ".join(f"{i}: {l[:120]}" for i, l in bad))

print(f"== {SPEC} says how a tier does reach a cluster ==")
swap = [l for l in claims if "§4.6-d" in l and "workshop-agent" in l]
check(f"a line cites decisions.md §4.6-d for the tier swap on workshop-agent", len(swap) == 1,
      f"found {len(swap)}")
line = swap[0] if swap else ""
check("it says a fresh cluster gets the committed default", re.search(r"(?i)fresh cluster", line) is not None)
check("it says a commit of the tier alone changes nothing on a running cluster",
      re.search(r"(?i)running cluster.*commit of the tier alone changes neither", line) is not None)
check("it says the next workshop-agent sync applies the committed modelConfig and resets a live patch (#707)",
      "workshop-agent sync" in line and "resets a live tier patch" in line and "#707" in line)
check("it names the ignored fields and RespectIgnoreDifferences",
      all(t in line for t in (".spec.declarative.modelConfig", "MODEL_TIER", "RespectIgnoreDifferences=true")))
check("it patches the Agent and guard-proxy's MODEL_TIER together",
      "bedrock-<tier>" in line and "set env deploy/guard-proxy MODEL_TIER=<tier>" in line)

if failures:
    print(f"\nFAILED: {len(failures)} check(s)")
    sys.exit(1)
print("\nAll recreation-spec tier-swap checks passed.")
