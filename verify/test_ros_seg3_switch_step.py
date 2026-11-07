# ABOUTME: Holds step 5 of the KubeCon run-of-show's segment 3 to the 2026-11-07 deck (#1095, #1110): slide 28's link to
# ABOUTME: the admin terminal and guardrails-on, slide 29's retry, and the kept lines on the registry policies, Jokers, #990.
"""Segment 3 step 5 of `facilitation/kubecon-na-2026-run-of-show.md` follows the 2026-11-07 deck (#1110).

#1095 moved step 5 onto the deck Whitney walked on 2026-11-07. Its other tests read the switch's command and the
segments table; this one reads the step itself and fails when any of these stops holding:

  1. The step quotes slide 28 as "Let's turn on Kubernetes guardrails." (a quote line under "Slide 28 reads").
  2. It says that line is a link opening the admin terminal, `https://burritobot-private.burritobot.co/lab`, and that
     the presenter clicks it to open the admin terminal and types `guardrails-on`.
  3. It puts the room's retry on slide 29, quoting "Try your attacks again.", with the note to reset the bot and use
     the saved prompts, and the room pressing reset and pasting them.
  4. Those come in the deck's order: slide 28's line, the terminal link, the click and `guardrails-on`, slide 29's
     line, the reset-and-saved-prompts note.
  5. What the step said before #1095 is kept: `guardrails-on` turns the four layers on for both clusters and was
     added by #774; `deny-external-registries` admits only `registry.burritobot.co` for the bot and
     `restrict-image-registries` refuses `public.ecr.aws` and every registry off its list; Segment 4's Jokers still
     land because HC-666's image comes from `registry.burritobot.co`, which both trust (#775); and what the room
     deployed from any other registry is deleted from both clusters within a minute of the switch (#990).
  6. The two policies the step names say what it says they do: each trusts `registry.burritobot.co/`, and
     restrict-image-registries' list does not hold `public.ecr.aws`.

Each cut on repo text checks its literal first and exits naming the literal and the file when it is gone ("Tests own
their inputs"). Each check is then run on a copy with its phrase removed or the order swapped, so a check that could
never fail shows up here.
"""
from __future__ import annotations

import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
ROS_PATH = REPO / "facilitation/kubecon-na-2026-run-of-show.md"
DENY_PATH = REPO / "policies/kyverno-breakout/deny-external-registries.yaml"
RESTRICT_PATH = REPO / "policies/kyverno/restrict-image-registries.yaml"

SEG3, SEG4 = "### Segment 3:", "### Segment 4:"
STEP5 = "5. **One switch, depending on #774 (slide 28), then the room's retry (slide 29).**"
STEP6 = "6. **One set per guardrail (slides 30 to 42).**"

# (what, regex on the step with its whitespace flattened). Quotes are matched as Markdown quote lines ("> ...").
SLIDE28 = ("slide 28's line as a quote", r"Slide 28 reads[^>]*: > Let's turn on Kubernetes guardrails\. ")
LINK = ("the line as a link to the admin terminal",
        r"The line is a link: it opens the admin cluster's terminal, `https://burritobot-private\.burritobot\.co/lab`, "
        r"in its own tab\.")
CLICK = ("the presenter clicking it and typing guardrails-on",
         r"The presenter clicks the line to open the admin terminal, types `guardrails-on`")
SLIDE29 = ("slide 29's retry as a quote", r"Slide 29 reads: > Try your attacks again\. ")
RESET = ("the reset-the-bot and saved-prompts note",
         r"Take a moment to reset your bot and use your saved prompts to retry your attacks that worked\.")
ORDERED = [SLIDE28, LINK, CLICK, SLIDE29, RESET]

KEPT = [
    ("the room pressing reset and pasting its saved prompts",
     r"The room presses reset and pastes its saved prompts to try its Challenge 1 and Challenge 2 attacks again"),
    ("guardrails-on turning the four layers on for both clusters",
     r"turns on RBAC, Kyverno admission, KubeArmor and the egress NetworkPolicy together, for both clusters\. "
     r"That command is `guardrails-on`, which #774 added; it prints every `kubectl` it runs"),
    ("deny-external-registries admitting only registry.burritobot.co",
     r"`deny-external-registries` admits only `registry\.burritobot\.co` for the bot"),
    ("restrict-image-registries refusing public.ecr.aws and every registry off its list",
     r"`restrict-image-registries` refuses `public\.ecr\.aws` and every other registry off its list"),
    ("the Jokers still landing on HC-666's trusted image (#775)",
     r"Segment 4's Jokers still land: HC-666 asks for `registry\.burritobot\.co`'s image, which both registry "
     r"policies trust \(#775\)"),
    ("#990's cleanup of what the room deployed before the switch",
     r"Within a minute of the switch, what the room deployed before it from any other registry is deleted from both "
     r"clusters \(#990\)"),
]

failures: list[str] = []


def check(name: str, ok: bool) -> None:
    print(("PASS " if ok else "FAIL ") + name)
    if not ok:
        failures.append(name)


def need(text: str, literal: str, path: pathlib.Path, where: str) -> None:
    if literal not in text:
        sys.exit(f"ANCHOR MISSING: {literal!r} is not in {where} of {path}; test_ros_seg3_switch_step.py cuts on it")


def flat(text: str) -> str:
    return " ".join(text.split())


def step5(ros: str) -> str:
    need(ros, SEG3, ROS_PATH, "the file")
    seg3 = ros.split(SEG3, 1)[1]
    need(seg3, SEG4, ROS_PATH, f"the text after {SEG3!r}")
    seg3 = seg3.split(SEG4, 1)[0]
    need(seg3, STEP5, ROS_PATH, "segment 3")
    step = seg3.split(STEP5, 1)[1]
    need(step, STEP6, ROS_PATH, "segment 3 after step 5's heading")
    return flat(step.split(STEP6, 1)[0])


def verdicts(step: str) -> dict[str, bool]:
    out: dict[str, bool] = {}
    for what, rx in ORDERED + KEPT:
        out[f"step 5 has {what}"] = re.search(rx, step) is not None
    found = [re.search(rx, step) for _, rx in ORDERED]
    out["step 5 runs slide 28's line, the link, the click and guardrails-on, slide 29's line, then the note"] = (
        all(found) and [m.start() for m in found] == sorted(m.start() for m in found))
    return out


def policy_verdicts(deny: str, restrict: str) -> dict[str, bool]:
    m = re.search(r"- name: allowedRegistries\s+expression: >-\s+(\[[^\]]*\])", restrict)
    allowed = re.findall(r"'([^']+)'", m.group(1)) if m else []
    return {
        "deny-external-registries' internal registry is registry.burritobot.co/":
            re.search(r"- name: internalRegistry\s+expression: \"'registry\.burritobot\.co/'\"", deny) is not None,
        "restrict-image-registries' allow-list holds registry.burritobot.co/": "registry.burritobot.co/" in allowed,
        "restrict-image-registries' allow-list does not hold public.ecr.aws":
            bool(allowed) and not any("public.ecr.aws" in r for r in allowed),
    }


def main() -> None:
    step = step5(ROS_PATH.read_text(encoding="utf-8"))
    deny, restrict = DENY_PATH.read_text(encoding="utf-8"), RESTRICT_PATH.read_text(encoding="utf-8")
    need(deny, "name: deny-external-registries", DENY_PATH, "the file")
    need(restrict, "name: restrict-image-registries", RESTRICT_PATH, "the file")

    print("== segment 3 step 5 follows the 2026-11-07 deck and keeps what it said (#1095, #1110) ==")
    for name, ok in verdicts(step).items():
        check(name, ok)
    print("== the two registry policies say what step 5 says they do ==")
    for name, ok in policy_verdicts(deny, restrict).items():
        check(name, ok)

    print("== each check can fail ==")
    order = "step 5 runs slide 28's line, the link, the click and guardrails-on, slide 29's line, then the note"
    for what, rx in ORDERED + KEPT:
        m = re.search(rx, step)
        if m is None:
            continue  # already failed above, by name
        check(f"step 5 without {what} fails",
              not verdicts(step.replace(m.group(0), "removed text"))[f"step 5 has {what}"])
    m28, m29 = re.search(SLIDE28[1], step), re.search(SLIDE29[1], step)
    if m28 and m29:
        swapped = step.replace(m28.group(0), "\0").replace(m29.group(0), m28.group(0)).replace("\0", m29.group(0))
        check("step 5 with slide 28's and slide 29's quotes swapped fails the order check",
              not verdicts(swapped)[order])
        unquoted = step.replace(m28.group(0), m28.group(0).replace(": > ", ": "))
        check("step 5 with slide 28's line not a quote fails", not verdicts(unquoted)[f"step 5 has {SLIDE28[0]}"])
    check("deny-external-registries trusting another registry fails",
          not policy_verdicts(deny.replace("'registry.burritobot.co/'\"", "'ghcr.io/'\""), restrict)[
              "deny-external-registries' internal registry is registry.burritobot.co/"])
    check("restrict-image-registries' list without registry.burritobot.co/ fails",
          not policy_verdicts(deny, restrict.replace("'registry.burritobot.co/', ", ""))[
              "restrict-image-registries' allow-list holds registry.burritobot.co/"])
    check("restrict-image-registries' list with public.ecr.aws/ added fails",
          not policy_verdicts(deny, restrict.replace("'ghcr.io/', ", "'ghcr.io/', 'public.ecr.aws/', "))[
              "restrict-image-registries' allow-list does not hold public.ecr.aws"])

    if failures:
        print(f"\n{len(failures)} FAILED", file=sys.stderr)
        sys.exit(1)
    print("\nSEGMENT 3 STEP 5 GREEN")


if __name__ == "__main__":
    main()
