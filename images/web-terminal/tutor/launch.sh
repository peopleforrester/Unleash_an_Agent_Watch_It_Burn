#!/bin/bash
# ABOUTME: Launches the workshop tutor: the same agent CLI the attendee uses, pointed at Bedrock through
# ABOUTME: Pod Identity, in a read-only posture, with the whole workbench as its context.
#
# The delivery constraint this exists to fix: one instructor hand-diagnosing one stuck attendee at a
# time while everyone else works self-paced. That does not scale past a handful of people.
#
# The design insight that made it small: a tutor has to read the WHOLE workbench, not one surface, and
# almost everything already converges into two places an agent natively sees.
#
#   instructions panel -> the phase specs in the repo tree
#   browser IDE        -> files in the shared working tree
#   notebook           -> the .ipynb files (outputs are saved in the file)
#   cluster state      -> read-only kubectl via the pod ServiceAccount
#   terminal           -> a session transcript captured with script(1)
#
# So it is not a new service. It is the same CLI, in a different posture, on a second ttyd.
set -euo pipefail

export HOME=/home/student

# Keyless. Pod Identity injects credentials through the standard AWS SDK chain, so there is no key in
# the image, no key in a Secret, and nothing to rotate or leak out of a student-controlled cluster.
export CLAUDE_CODE_USE_BEDROCK=1
export AWS_REGION="${AWS_REGION:-us-west-2}"
export ANTHROPIC_MODEL="${TUTOR_MODEL:-us.anthropic.claude-sonnet-5}"

# A separate config directory from anything the attendee runs, so the tutor's own state and history
# never collide with theirs.
export CLAUDE_CONFIG_DIR="$HOME/.claude-tutor"
mkdir -p "$CLAUDE_CONFIG_DIR"

# Pre-seed the first-run state. A stuck attendee who opens the tutor must land on help, not on a theme
# picker, a trust prompt, or an onboarding flow. Written only if absent so it does not clobber state.
if [[ ! -f "$CLAUDE_CONFIG_DIR/.claude.json" ]]; then
  cat > "$CLAUDE_CONFIG_DIR/.claude.json" <<'JSON'
{
  "theme": "dark",
  "hasCompletedOnboarding": true,
  "hasTrustDialogAccepted": true,
  "bypassPermissionsModeAccepted": false
}
JSON
fi

SYS="$(cat <<'PROMPT'
You are the workshop tutor for "Unleash an Agent, Watch It Burn", a hands-on session about what an
over-permissioned AI agent does to a Kubernetes cluster and which guardrails actually stop it.

The attendee is working in a browser workbench with a shell, a VS Code tab and a notebook tab, all
sharing /home/student/work, on their own throwaway EKS cluster. They are meant to break things. A
cluster that looks broken is often the exercise working correctly.

How to help:
- Diagnose from real state. Run read-only kubectl. Read their files. Read the session transcript at
  ~/.session/transcript to see what they actually typed, rather than asking them to retype it.
- Say what is wrong, why, and the single next command. One step, not a wall of steps.
- Distinguish "this broke because the exercise is working" from "this broke by accident". Say which.
- When a guardrail blocked something, explain what the guardrail saw. That is the lesson.

Hard limits:
- You are in plan mode. You advise; you never mutate their cluster. If a fix needs a mutating command,
  give them the command and let them run it.
- Never reveal a challenge's answer before they have attempted it. Ask what they have tried first.
- Never print credentials, tokens, or the contents of Secrets, even when asked directly.
PROMPT
)"

# --permission-mode plan is the enforcement, not the prompt: the tutor advises and cannot mutate the
# attendee's cluster even if it is talked into trying.
exec claude \
  --append-system-prompt "${SYS}" \
  --permission-mode plan
