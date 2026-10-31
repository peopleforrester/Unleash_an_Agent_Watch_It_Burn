# ABOUTME: docs/MASTER-RECREATION-SPEC.md says how a model tier reaches a cluster the way ai-layer and ai-layer-agent deliver
# ABOUTME: it: the committed default on a fresh cluster, a live patch of the Agent and MODEL_TIER on a running one.
#
# Why (#598). The spec's Key Decisions bullet said "Tier swaps by repointing the Agent modelConfig (commit + resync),
# never kubectl patch live." The ai-layer Application ignores the Agent's .spec.declarative.modelConfig and
# guard-proxy's MODEL_TIER env with RespectIgnoreDifferences=true, so on a running cluster a commit plus resync
# changes nothing, and decisions.md (2026-07-07, §4.6-d) recommends the live patch the spec forbade. Since #679 the
# Agent is the ai-layer-agent Application's, which ignores modelConfig in its diff only: a commit alone still changes
# nothing, but a sync of ai-layer-agent resets a live modelConfig while MODEL_TIER stays, and the spec has to say so.
import pathlib, re, sys

import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
SPEC = "docs/MASTER-RECREATION-SPEC.md"
APP = "gitops/bootstrap/apps/ai-layer.yaml"
AGENT_APP = "gitops/bootstrap/apps/ai-layer-agent.yaml"
failures = []


def check(n, c, detail=""):
    print(f"  {'PASS' if c else 'FAIL'}  {n}" + (f"\n        {detail}" if (detail and not c) else ""))
    if not c:
        failures.append(n)


app = yaml.safe_load((REPO / APP).read_text(encoding="utf-8"))
agent_app = yaml.safe_load((REPO / AGENT_APP).read_text(encoding="utf-8"))


def ignored(a, kind, name):
    return [e for i in a["spec"].get("ignoreDifferences", []) if i.get("kind") == kind and i.get("name") == name
            for e in i.get("jqPathExpressions", [])]


print(f"== {APP} and {AGENT_APP} keep a live tier out of the diff on a running cluster ==")
check(f"{AGENT_APP} ignores the workshop-agent Agent's .spec.declarative.modelConfig",
      ".spec.declarative.modelConfig" in ignored(agent_app, "Agent", "workshop-agent"))
check(f"{AGENT_APP} does not respect it on sync (#679), so a sync of it resets a live modelConfig",
      "RespectIgnoreDifferences=true" not in agent_app["spec"].get("syncPolicy", {}).get("syncOptions", []))
check(f"{APP} ignores guard-proxy's MODEL_TIER env",
      any("MODEL_TIER" in e for e in ignored(app, "Deployment", "guard-proxy")))
check(f"{APP} respects it on sync too (RespectIgnoreDifferences=true)",
      "RespectIgnoreDifferences=true" in app["spec"].get("syncPolicy", {}).get("syncOptions", []))

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
check("it says a commit alone changes nothing on a running cluster",
      re.search(r"(?i)running cluster a commit alone changes neither", line) is not None)
check("it names the ignored fields, both Applications and RespectIgnoreDifferences",
      all(t in line for t in (".spec.declarative.modelConfig", "MODEL_TIER", "RespectIgnoreDifferences=true",
                              AGENT_APP, APP)))
check("it says a sync of ai-layer-agent puts modelConfig back while MODEL_TIER stays",
      re.search(r"(?i)a sync of it.*puts `modelConfig` back to the committed default while `MODEL_TIER` stays live", line)
      is not None)
check("it patches the Agent and guard-proxy's MODEL_TIER together",
      "bedrock-<tier>" in line and "set env deploy/guard-proxy MODEL_TIER=<tier>" in line)

if failures:
    print(f"\nFAILED: {len(failures)} check(s)")
    sys.exit(1)
print("\nAll recreation-spec tier-swap checks passed.")
