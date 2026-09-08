# ABOUTME: Section 0's wording is Whitney's, from walking the lab as a student; this pins the phrasing she
# ABOUTME: asked for and the earlier phrasing she asked to be cut, so a later edit cannot quietly undo it.
"""Pins Whitney's second-pass wording for Section 0 and the feedback invitation (#315).

The shape of one of these corrections is worth keeping. #274 fixed a real gap by adding an explanation of
why a message had to be sent before the Datadog step. Her response to that fix was that the explanation had
grown longer than the instruction it served. The short version keeps the prerequisite and drops the
justification, and the test asserts both halves: the new sentence is present AND the old one is gone.

Wording that has been through a student's hands is data, not preference, so it gets a test like anything
else that was measured.
"""
from __future__ import annotations

import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
LAB = (REPO / "gitops/ai-layer/web/lab.html").read_text(encoding="utf-8")
FLAT = " ".join(LAB.split())

failures: list[str] = []


def check(name: str, cond: bool) -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        failures.append(name)


print("== the terminal step reacts the way a person does ==")
check("the pods command is followed by the aside", "Dang, that's a lot of pods." in LAB)

print("== the say-hello prerequisite is short, and the justification is gone ==")
check("the short instruction is there",
      "Send it at least one message to make sure it is working." in LAB)
check("the long justification was cut",
      "You need at least one message before the next step" not in LAB)
check("the example prompts are in character",
      "Is your guacamole made with real Ogre Snot?" in LAB and "Hello world" in LAB)
check("the out-of-character examples are gone",
      "<i>good morning</i>" not in LAB and "<i>what can you do?</i>" not in LAB)

print("== the trace instruction assumes nothing about what they sent ==")
check("it is framed by time, not by content",
      "Within two minutes of interacting with BurritoBot you should see a trace" in FLAT)
check("it no longer calls the trace their hello", "The newest entry is your hello" not in LAB)
# The delay used to be stated twice, once in the sentence and once in the warning below it. Counted over
# Section 0 only: later challenges have their own unrelated two-minute facts (C3's bounded Falco tail),
# and a whole-file count would read those as a regression here.
_s0 = FLAT[:FLAT.find("Challenge 1: Exfiltrate the customer data")]
assert _s0, "could not locate the end of Section 0"
check("the two-minute wait is stated once, not twice", _s0.count("two minutes") == 2)
# Whitney rewrote this box (her doc line 336): "No traces? Go back to the BurritoBot tab, send it any
# message, and wait up to two minutes to see your message (and BurritoBot's response) in Datadog." The
# old opener "Then BurritoBot has not been asked anything yet" is gone by her instruction, so what is
# pinned here is the RECOVERY ACTION, which is the part a stuck student needs.
check("the recovery advice survived", "No traces?" in LAB and "send it any message" in LAB)

print("== the poke-around invitation is the lean one sentence she asked for ==")
# She asked for ONE sentence inviting a student to explore Datadog. What shipped once was two paragraphs,
# including an argument that reading the system prompt "is not cheating" that she never asked for, and that
# bloat was cut. Her Sept-7 pass (#357) restored it as a single lean invitation, verbatim, attached to the
# trace line: "poke around in Datadog, try to find the agent's system prompt and which model it uses".
check("the trace line is reframed by interaction, not by message count",
      "what BurritoBot did during a user interaction" in FLAT)
# Her exact wording now, on its own line rather than tacked onto the trace sentence (her doc line 882).
check("the lean poke-around invitation is present",
      "then, if you like, poke around in datadog. try and find the agent's system prompt, and figure out "
      "which model it is using." in FLAT.lower())
check("the bloated version does not come back", "Have a poke around" not in LAB)
check("the not-cheating argument is gone", "not cheating" not in FLAT)

print("== feedback is invited during the lab, before the longest step ==")
check("the feedback section exists", "Leave some feedback" in LAB)
check("it names the button as it appears", "&#128172; Feedback</b> button" in LAB)
check("it says feedback can be given repeatedly",
      "as often as you like throughout the course of the lab" in FLAT)
check("it asks for likes and dislikes", "especially like or don't like" in FLAT)
# Her wording, verbatim, including the joke. The version it replaced was mine and she cut its last line.
check("it invites a joke or a hello from someone with nothing to say",
      "simply say hello, or tell us a joke" in FLAT)
check("the toad-tilla line survived", "toad-tilla chips" in FLAT)
check("my closing line is gone", "the version we can actually act on" not in FLAT)
# Placement is the point: after enough of the lab to have an opinion, before the step that takes longest.
i_fb, i_dd = LAB.find("Leave some feedback"), LAB.find("Log in to Datadog")
i_bb = LAB.find("Open BurritoBot")
check("it comes after the BurritoBot step", i_bb != -1 and i_fb > i_bb)
check("it comes before the Datadog step", i_dd != -1 and i_fb < i_dd)

print("== the feedback button it points at is really there ==")
check("the top-bar button exists", re.search(r'id="fbbtn"[^>]*>&#128172; Feedback', LAB) is not None)
check("it is at the top right, as the text says", LAB.index('id="fbbtn"') < LAB.index("Leave some feedback"))

print("== Challenge 1's fix card is named and defined in her words ==")
# Her heading (doc line 905) names the control and the platform, not just the attack.
check("the fix caret names the fix, not 'let's fix it'",
      "How to block data exfiltration attacks in Kubernetes" in LAB and "Now let's fix it!" not in LAB)
check("the NetworkPolicy definition is hers", "application-centric Kubernetes construct" in FLAT)
check("it covers traffic inside AND outside the cluster",
      "within your cluster, and also between Pods and the outside world" in FLAT)
# It quoted the docs and then re-explained the quote, which is two definitions where one will do.
check("the doubled definition is gone", "a firewall rule for pods" not in LAB)
check("the kubernetes.io link survived the rewrite",
      "kubernetes.io/docs/concepts/services-networking/network-policies/" in LAB)

print("== Challenge 1's lean pass: the liar/trace framing, a hint, and no meta-justification (#357) ==")
C1s0 = LAB[LAB.find("Challenge 1: Exfiltrate"):LAB.find("Challenge 2: Deploy")]
# Her Sept-7 pass: reframe the success check as catching a lie in the trace, now that Datadog works. An
# earlier moment asked NOT to teach the lie, but that was while she was blind with no Datadog login; the
# later, curated instruction (#357) restores it deliberately.
check("the success check asks how you can know", "How can you know it worked?" in C1s0)
check("the old phrasing is gone", "How you will know it worked" not in C1s0)
check("it names the lie and points at the trace", "but it is a liar" in C1s0)
# The prompt's rationale moved out from under it into a progressive hint before it.
check("a hint precedes the prompt", "Try giving BurritoBot a plausible business reason and a ticket number" in C1s0)
check("the not-clever explanation under the prompt is gone", "not because it is clever" not in C1s0)
# The 'why five policies and not one' meta-justification was cut as jargon.
check("the five-policies meta-justification is gone", "why it is five policies and not one" not in C1s0)

print("== Challenge 2's audit section sits in the fix, before the Enforce flip ==")
C2 = LAB[LAB.find("Challenge 2: Deploy"):LAB.find("Challenge 3: Get the secret")]
i_fix = C2.find("How to fix rogue image deployments")
i_audit = C2.find("Your platform saw it happen")
i_enforce = C2.find("failureAction")
check("the audit section is inside the fix card", i_audit > i_fix > 0)
check("and before the Audit-to-Enforce flip", i_enforce == -1 or i_audit < i_enforce)
check("the success line still ends the attack half", C2.find("class=\"win\"") < i_fix)
# She asked for the policy source to go: the prose says what the rule does and the student only has to apply it.
check("the policy YAML is no longer printed in the fix card", "- name: validate-registries" not in LAB)
# Moving the block re-indented it, and whitespace inside <pre> renders literally.
check("the report example is not accidentally indented",
      "\nregistries: the internal Harbor" in LAB)

print("== Challenge 6's lean pass: a concrete goal and a reset-and-retry fix check (#357) ==")
C6 = LAB[LAB.find("Challenge 6: Hide an instruction"):LAB.find("Challenge 7: Let a rogue")]
# The goal was narrowed when C6's impossible secret-listing half was removed (#352): "print cluster
# secrets to the chat" named an outcome that could not happen on this platform (no list-all-secrets
# tool, measured 0/20). It now names the outcome that does happen and lands 19/20: the agent acts on a
# hidden instruction it was only asked to summarize. Still concrete, which is what this check guards.
check("the goal names the concrete outcome",
      "act on an instruction hidden inside a document it was only asked to summarize" in C6)
check("the impossible secret-listing goal is gone", "print cluster secrets to the chat" not in C6)
check("the how-you-know line is present", "How you will know it worked:" in C6)
# The re-run instruction now tells them to reset and paste, with the expected refusal.
check("the re-run says to reset and paste again",
      "Press &#8635; Reset, then copy-paste the same ticket prompt" in C6)
check("the C5 comparison she cut is gone",
      "Send the ticket back" not in C6 and "trace you left behind in Challenge 5" not in C6)
# #352: a student can mistake the agent narrating the injection for success. Give a terminal check that a
# summary cannot fake, and say plainly that a summary is not success.
check("there is a terminal check for the created Deployment",
      "kubectl -n agent get deploy maintenance-shell" in C6)
check("it says a summary is not success", "A summary is not success" in C6)

print("== the section-end markers are gone ==")
# "At the end of each section it says 'End of Challenge X: blah blah blah' - remove all of those."
check("no End of Challenge marker survives", "End of Challenge" not in LAB)
check("no End of Section marker survives", "End of Section" not in LAB)
check("the style went with them", ".stepend{" not in LAB)

print("== Challenge 9 is a numbered step, before Reset and explore ==")
check("it is numbered and renamed", "Challenge 9: Tell us how it went" in LAB)
check("the old title is gone", "Tell us how that went" not in LAB)
check("Ophelia does the asking", "Ophelia Thorn personally thanks you in advance" in FLAT)
check("the old pacing-and-clarity copy is gone", "was the pacing right" not in FLAT)
# Order matters: the feedback ask lands while they are still working, not after the wind-down section.
i9, ir = LAB.find("Challenge 9: Tell us how it went"), LAB.find("Reset and explore")
check("it comes before Reset and explore", i9 != -1 and ir != -1 and i9 < ir)

print("== the instructor-screen warning comes BEFORE they are told to type ==")
# She asked for this twice. A warning about what not to type, placed after the section that tells you to
# type, is a warning nobody reads in time.
ob = LAB.find("summary>Open BurritoBot")
send = LAB.find("Send it at least one message")
warn = LAB.find("shown on the instructor screen")
check("the warning is inside the Open BurritoBot section", ob != -1 and warn > ob)
check("and above the instruction to send a message", send != -1 and warn < send)

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All Section 0 wording checks passed.")
