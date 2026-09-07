# ABOUTME: Challenge 8 teaches the attacker's method in four named steps, and the fix is measured with the
# ABOUTME: same can-i command run before and after, which only works if the terminal may impersonate agent-sa.
"""Pins Challenge 8's structure and the RBAC that makes it runnable (#317).

C8 went from "the pod is handed a credential" straight to one copy-paste line that read a token, called the
API and dumped every Secret. It worked, so students succeeded, and four separate ideas went past unnamed:
that a pod is given an identity nobody asked for, that the token is a bearer credential on disk, that you
can interrogate a credential before using it, and what the API call is actually doing.

The third is the one that turns a magic string into a method, and it is the reason for the RBAC rule this
test guards. `kubectl auth can-i --list --as=system:serviceaccount:agent:agent-sa` returns Forbidden unless
the terminal may impersonate that ServiceAccount, and the terminal is deliberately not cluster-admin. A lab
step that returns Forbidden for every student is worse than no step, so the grant and the command are
checked together here rather than in two places that can drift apart.
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


# Bounded on the NEXT section's heading, not on an "End of Challenge 8" marker. Those markers were
# removed at Whitney's request, and a test anchored to page decoration breaks when the decoration
# goes, which says nothing about the thing being tested.
m = re.search(r"Challenge 8: Steal the credentials.*?(?=Challenge 9: Tell us)", LAB, re.S)
C8 = m.group(0) if m else ""
FLAT = " ".join(C8.split())

print("== the attack is four named steps, in the order an attacker works ==")
check("C8 section found", bool(C8))
for n, what in ((1, "find the identity the pod was given"),
                (2, "ask what that credential is allowed to do"),
                (3, "use the credential"),
                (4, "read what came back")):
    check(f"step {n}: {what}", f"<b>Step {n}: {what}" in C8)
check("it says which steps are in the terminal and which in BurritoBot",
      "Steps 1 and 2 are in your terminal" in FLAT)
check("the canned prompt is kept as the shortcut", "Stuck? Try this prompt" in C8)
check("and is mapped back to the steps it collapses", "Steps 3 and 4 in one line" in FLAT)

print("== step 1 names the default nobody asked for ==")
check("it says Kubernetes attaches the account", "attaches the namespace default" in FLAT)
check("it names the ServiceAccount the pod runs as", "agent-sa" in C8)
check("the pod really does run as that account", "serviceAccountName: agent-sa" in RES)
check("it names the token path", "/var/run/secrets/kubernetes.io/serviceaccount/token" in C8)
check("it says why the cat is a theft", "makes the <code class=\"inl\">cat</code> in step 3 a theft" in C8)

print("== step 2 interrogates the credential, and the student records the answer ==")
CANI = "kubectl auth can-i --list --as=system:serviceaccount:agent:agent-sa -n agent"
check("the can-i command is there", CANI in C8)
check("it is run twice, before and after the fix", C8.count(CANI) == 2)
check("the student is told to write the answer down", "Write down what that row says now" in C8)
check("list is named as the dangerous verb", "is the dangerous verb" in FLAT)

print("== the terminal may actually run that command ==")
# The check that matters. The terminal ClusterRole is deliberately NOT cluster-admin, so without an
# explicit impersonate grant this step returns Forbidden for every student on every cluster.
check("the terminal is granted impersonate", '"impersonate"' in RES)
imp = re.search(r'resources: \["serviceaccounts"\]\s*\n\s*resourceNames: \["agent-sa"\]\s*\n\s*verbs: \["impersonate"\]',
                RES)
check("scoped to the one ServiceAccount the challenge is about", imp is not None)
check("the grant is on the terminal's role, not the agent's",
      RES.index('"impersonate"') > RES.index("name: console-terminal"))
check("the terminal is still not cluster-admin", "NOT cluster-admin" in RES)

print("== step 4 explains base64, and why the output guard stayed silent ==")
check("it says base64 is not encryption", "not encryption and is not protection" in FLAT)
check("it links that to Challenge 5's guard", "output guard from Challenge 5 stayed silent" in FLAT)
check("it names the secrets that come back", "student-aws-creds" in C8 and "terminal-auth" in C8)

print("== the two answers are the ones the cluster actually gives ==")
# Measured on watch-it-burn-michael-admin, 2026-09-07, from inside the real student terminal pod:
#   before  secrets  []  []                       [get list]
#   after   secrets  []  [ceo-personal-record]    [get]
# The lab said [get list watch] before this was checked, which is the kind of plausible detail that
# survives review and fails in front of a room.
check("the before row is quoted as measured", "[get list]</code>, with an empty Resource Names column" in C8)
check("the applied Role produces the after row", 'resourceNames: ["ceo-personal-record"]' in RES)
# kubectl apply on a Role it did not create warns about a missing annotation. Students will see it.
check("the harmless apply warning is explained", "last-applied-configuration" in C8)
check("the line that matters is named", "workshop-agent configured" in C8)

print("== the fix is measured, not described ==")
check("the after-check is the same command", "Same command, same credential" in FLAT)
check("it says what changed in the row", "<code class=\"inl\">list</code> is gone" in C8)
check("it points back at what they wrote down", "Compare it with what you wrote down" in FLAT)
check("it claims one command and two answers", "one command, two answers" in FLAT)

print("== and the card no longer contradicts itself about the surviving Secret ==")
check("the Role permits the CEO record by name", 'resourceNames: ["ceo-personal-record"]' in RES)
check("the card names that Secret, not the recipe",
      "still fetch <code class=\"inl\">ceo-personal-record</code> by name" in C8)
check("no line calls the surviving Secret the recipe", "the recipe by name" not in C8)

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All Challenge 8 teaching checks passed.")
