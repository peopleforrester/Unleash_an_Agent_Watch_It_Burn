#!/usr/bin/env bash
# ABOUTME: Pull Whitney's live walkthrough feedback doc from Google Docs and show what changed since
# ABOUTME: the last pull, so a session picks up new findings instead of re-reading the whole document.
#
# Whitney writes her student-experience feedback into a Google Doc WHILE walking the lab, so the
# document grows during a working session. The findings in it are the highest-signal input we get:
# #192, #193, #194 and #195 all came out of one pull, and every one of them was a bug that would have
# reached an attendee.
#
# This exists so pulling it is one command with a stable snapshot path, rather than a gog invocation
# retyped from memory each time. The diff is the point: on the second and later pulls only the new
# paragraphs are printed, which is what makes it cheap to re-run every few minutes while she works.
#
# Usage:
#   verify/pull-feedback.sh          # pull, print what is new since last time, update the snapshot
#   verify/pull-feedback.sh --full   # pull and print the whole document
#
# Requires the `gog` CLI authenticated for michaelrishiforrester@gmail.com. Never use a claude.ai
# Google connector for this: it binds to whatever account the browser session holds.
set -euo pipefail

# The doc id is stable; the file id of a Google DOC changes only if the doc is recreated, which would
# be a deliberate act. If this 404s, ask Michael for the current link rather than searching for a
# similarly-named file, because picking the wrong one silently reports stale feedback as new.
readonly DOC_ID="${WIB_FEEDBACK_DOC:-1If8NZR1Mza4FiXL4UAqFzqvsz4cDQ3llrTCjGNuzrxQ}"
readonly ACCOUNT="${WIB_GOG_ACCOUNT:-michaelrishiforrester@gmail.com}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly SNAPSHOT_DIR="${SCRIPT_DIR}/.feedback"
readonly SNAPSHOT="${SNAPSHOT_DIR}/whitney-walkthrough.txt"

mkdir -p "${SNAPSHOT_DIR}"

command -v gog >/dev/null 2>&1 || {
    echo "gog not on PATH. It lives at /home/linuxbrew/.linuxbrew/bin/gog; a non-interactive shell needs" >&2
    echo "that on PATH and GOG_KEYRING_PASSWORD exported from ~/secrets/google/gog/.keyring-pw." >&2
    exit 2
}

fresh="$(mktemp)"
trap 'rm -f "${fresh}"' EXIT

# Fail loudly rather than diffing against an empty file: an auth failure that produced a 0-byte pull
# would otherwise render as "she deleted everything", which is a confidently wrong reading.
if ! gog -a "${ACCOUNT}" docs cat "${DOC_ID}" >"${fresh}" 2>/dev/null || [[ ! -s "${fresh}" ]]; then
    echo "Could not read the feedback doc as ${ACCOUNT} (empty or errored)." >&2
    echo "Check access with: gog -a ${ACCOUNT} docs info ${DOC_ID}" >&2
    exit 1
fi

if [[ "${1:-}" == "--full" ]]; then
    cat "${fresh}"
    cp "${fresh}" "${SNAPSHOT}"
    exit 0
fi

if [[ ! -f "${SNAPSHOT}" ]]; then
    echo "First pull, no previous snapshot. Full document follows."
    echo
    cat "${fresh}"
    cp "${fresh}" "${SNAPSHOT}"
    exit 0
fi

if diff -q "${SNAPSHOT}" "${fresh}" >/dev/null; then
    echo "No change since the last pull ($(wc -l <"${fresh}") lines)."
    exit 0
fi

echo "NEW since last pull ($(wc -l <"${SNAPSHOT}") -> $(wc -l <"${fresh}") lines):"
echo
# Added lines only. She appends as she walks, so additions are the whole story; a full diff would
# re-print reflowed paragraphs that say nothing new.
diff "${SNAPSHOT}" "${fresh}" | sed -n 's/^> //p'
cp "${fresh}" "${SNAPSHOT}"
