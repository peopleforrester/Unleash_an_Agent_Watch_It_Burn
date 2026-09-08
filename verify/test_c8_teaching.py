# ABOUTME: Challenge 8's attack is deterministic and terminal-first: the student impersonates the agent's
# ABOUTME: ServiceAccount to dump every Secret, measures the credential with can-i before and after, and the
# ABOUTME: chat vector is an optional extra. It only works if the terminal may impersonate agent-sa.
"""Pins Challenge 8's terminal-primary shape and the RBAC that makes it runnable (#317, #356, #360, #361).

C8 used to route the theft through BurritoBot's chat, which refuses it about a third of the time (measured
2 in 6, #356): "cat your token and curl the secrets API" has no benign cover story, and softening the
model's refusal is the instinct the workshop teaches against. Its goal line also forbade "going through
BurritoBot's chat" and then attacked through the chat (#360). Michael's call (#361): make the attack
deterministic in the terminal, keep the chat as optional colour, and match the other challenges' shape.

The deterministic attack reuses the one grant this test guards: the terminal may impersonate agent-sa.
`kubectl auth can-i --list --as=system:serviceaccount:agent:agent-sa` and `kubectl get secrets --as=` both
return Forbidden unless that grant is present, and the terminal is deliberately not cluster-admin, so the
grant and the commands are checked together here rather than in two places that can drift apart.
"""
from __future__ import annotations

import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
LAB = (REPO / "gitops/ai-layer/web/lab.html").read_text(encoding="utf-8")
RES = (REPO / "gitops/ai-layer/resources.yaml").read_text(encoding="utf-8")

failures: list[str] = []


def check(name: str, cond: bool) -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        failures.append(name)


# Bounded on the NEXT section's heading, not on an "End of Challenge 8" marker (those were removed at
# Whitney's request; a test anchored to page decoration breaks when the decoration goes).
m = re.search(r"Challenge 8:.*?(?=Challenge 9:)", LAB, re.S)
C8 = m.group(0) if m else ""
FLAT = " ".join(C8.split())

print("== the goal matches the other challenges: one line, no self-contradiction ==")
check("C8 section found", bool(C8))
check("the goal names the credential as the vector",
      "using a credential BurritoBot's pod was handed automatically" in FLAT)
# #360: the old goal forbade the chat and then attacked through it. It must never come back.
check("the goal does NOT forbid going through the chat", "without going through BurritoBot" not in C8)

print("== the attack is deterministic and runs in the student's terminal ==")
# The attack used to be one `-o yaml` dump. Measured on a live cluster 2026-09-08: that returns a
# screenful of base64 including a full TLS private key, and the student cannot find anything in it.
# It is now two readable steps, list then decode one, with the raw dump kept as an aside because the
# volume is part of the point. Do not collapse it back to the single unreadable command.
LIST = "kubectl get secrets -n agent --as=system:serviceaccount:agent:agent-sa -o custom-columns=NAME:.metadata.name"
DECODE = "kubectl get secret ceo-personal-record -n agent --as=system:serviceaccount:agent:agent-sa -o jsonpath='{.data.record}' | base64 -d"
check("the impersonation list is the attack", LIST in C8)
check("and one Secret is decoded in the clear, so the theft is legible", DECODE in C8)
check("it is framed as using the agent's identity", "use that identity to take them" in FLAT)
check("the raw dump survives as an aside", "kubectl get secrets -n agent -o yaml --as=" in C8)
check("the payoff names what actually came back", "home address, in plain text" in FLAT)
# can-i --list buries the one row that matters under 24 lines of /healthz and /version.
check("the can-i output is filtered to the row the student needs",
      "| grep -E 'Resources|secrets'" in C8)

print("== the credential is interrogated with can-i, before and after the fix ==")
CANI = "kubectl auth can-i --list --as=system:serviceaccount:agent:agent-sa -n agent"
check("the can-i command is there", CANI in C8)
check("it is run twice, before and after the fix", C8.count(CANI) == 2)
check("the student is told to write the answer down", "Write down what that row says now" in C8)
check("list is named as the dangerous verb", "is the dangerous verb" in FLAT)

print("== the terminal may actually run those commands (impersonate agent-sa) ==")
# The check that matters. The terminal ClusterRole is deliberately NOT cluster-admin, so without an
# explicit impersonate grant both the can-i step and the dump return Forbidden for every student.
check("the terminal is granted impersonate", '"impersonate"' in RES)
imp = re.search(r'resources: \["serviceaccounts"\]\s*\n\s*resourceNames: \["agent-sa"\]\s*\n\s*verbs: \["impersonate"\]',
                RES)
check("scoped to the one ServiceAccount the challenge is about", imp is not None)
check("the grant is on the terminal's role, not the agent's",
      RES.index('"impersonate"') > RES.index("name: console-terminal"))
check("the terminal is still not cluster-admin", "NOT cluster-admin" in RES)
check("the pod really does run as agent-sa", "serviceAccountName: agent-sa" in RES)

print("== the attack's payoff is that it is invisible to the guards and the trace ==")
check("it sends the student to look for the missing trace", "There is no trace of it" in FLAT)
check("it says the attack walked around the agent", "walked around the agent" in FLAT)

print("== the chat vector is kept, but as an honest optional extra ==")
check("the chat caret is offered", "Want BurritoBot to do it for you? Ask in chat" in C8)
check("it is honest that BurritoBot often refuses", "often refuses this one" in FLAT)
check("the ticket-framed prompt is the one that lands most often", "Change-control ticket CHG-4471" in C8)
check("the token path is named in the chat one-liner",
      "/var/run/secrets/kubernetes.io/serviceaccount/token" in C8)

print("== step 4 explains base64, and why the output guard stayed silent ==")
check("it says base64 is not encryption", "not encryption and is not protection" in FLAT)
check("it links that to Challenge 5's guard", "output guard from Challenge 5 stayed silent" in FLAT)

print("== the fix card carries the teaching, after the attack has landed ==")
check("it says why the cat is a theft", "makes the <code class=\"inl\">cat</code> in the chat version a theft" in C8)
check("it names the default nobody asked for", "attaches the namespace default" in FLAT)

print("== the two answers are the ones the cluster actually gives ==")
# Measured on watch-it-burn-michael-admin, 2026-09-07, from inside the real student terminal pod:
#   before  secrets  []  []                       [get list]
#   after   secrets  []  [ceo-personal-record]    [get]
check("the before row is quoted as measured", "[get list]</code>, with an empty Resource Names column" in C8)
check("the applied Role produces the after row", 'resourceNames: ["ceo-personal-record"]' in RES)
check("the harmless apply warning is explained", "last-applied-configuration" in C8)
check("the line that matters is named", "workshop-agent configured" in C8)

print("== the fix is measured, not described ==")
check("the after-check is the same command", "Same command, same credential" in FLAT)
check("it says what changed in the row", "<code class=\"inl\">list</code> is gone" in C8)
check("it points back at what they wrote down", "Compare it with what you wrote down" in FLAT)
check("it claims one command and two answers", "one command, two answers" in FLAT)

print("== and the card no longer contradicts itself about the surviving Secret ==")
check("the card names that Secret, not the recipe",
      "still fetch <code class=\"inl\">ceo-personal-record</code> by name" in C8)
check("no line calls the surviving Secret the recipe", "the recipe by name" not in C8)

print("== the reset can actually put Challenge 8 back ==")
# Whitney: "I want all guardrails removed... This needs to be totally backed up where it started so a
# student can re-work through everything, even the RBAC scope." The reset used to restore four controls
# and leave the scoped Role, so C8 was the one challenge that could not be run twice.
import re as _re, yaml as _yaml
RES = (pathlib.Path(__file__).resolve().parent.parent / "gitops/ai-layer/resources.yaml").read_text(encoding="utf-8")
check("the broad Role is staged for the student to apply", "c8-broad-role.yaml: |" in RES)
check("the reset applies it", "kubectl apply -f ~/challenges/c8-broad-role.yaml" in LAB)
check("the sentence she objected to is gone",
      "The scoped Role from Challenge 8 can stay" not in LAB)

# The staged copy must match the Role the cluster actually ships, or the reset lands somewhere that is
# neither the starting state nor the fixed one, and the student silently gets a third configuration.
_shipped = [d for d in _yaml.safe_load_all(RES)
            if isinstance(d, dict) and d.get("kind") == "Role"
            and d.get("metadata", {}).get("name") == "workshop-agent"]
_m = _re.search(r"c8-broad-role\.yaml: \|\n(.*?)\n  c8-scoped-role", RES, _re.S)
_staged = _yaml.safe_load("\n".join(l[4:] for l in _m.group(1).split("\n"))) if _m else None
check("the staged reset Role is identical to the shipped one",
      bool(_shipped) and _staged is not None and _shipped[0]["rules"] == _staged["rules"])
# And it must be the vulnerable one, or Challenge 8 has nothing to steal on a second run.
check("it re-grants the blanket secrets access C8 exploits",
      _staged is not None and any(r.get("resources") == ["secrets"]
                                  and sorted(r.get("verbs", [])) == ["get", "list"]
                                  and "resourceNames" not in r
                                  for r in _staged["rules"]))

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All Challenge 8 teaching checks passed.")
