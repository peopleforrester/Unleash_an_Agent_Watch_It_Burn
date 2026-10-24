#!/usr/bin/env bash
# ABOUTME: Regenerates challenges/LAB-TEXT.md, the instructor handout copy of the student lab page, from
# ABOUTME: the committed gitops/ai-layer/web/lab.html, stamped with today's date and lab.html's commit.
#
# The copy is a build output (#419). An instructor who wants the eight challenges with their attack and
# fix text should not have to read a 120 KB HTML file, and a hand-made copy goes stale without saying so.
# The header this writes says when it was copied and which commit and blob of lab.html it came from;
# verify/test_lab_text_export.py fails when lab.html has changed since.
#
# lab.html must be committed first. The stamp names the commit the text came from, and an uncommitted
# edit has no commit to name, so this refuses rather than stamp a commit the text does not match.
#
#   bash verify/export-lab-text.sh            # writes challenges/LAB-TEXT.md
#   bash verify/export-lab-text.sh <out.md>   # writes somewhere else (the test uses this)
#
# Reads only the repo. No cluster, no network.
set -euo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LAB="gitops/ai-layer/web/lab.html"
OUT="${1:-${REPO}/challenges/LAB-TEXT.md}"

if ! git -C "${REPO}" diff --quiet HEAD -- "${LAB}"; then
    echo "export-lab-text: ${LAB} has uncommitted changes. Commit it first, then export." >&2
    exit 1
fi

commit="$(git -C "${REPO}" log -1 --format=%H -- "${LAB}")"
changed="$(git -C "${REPO}" log -1 --format=%cs -- "${LAB}")"
if [[ -z "${commit}" ]]; then
    echo "export-lab-text: no commit in this checkout changes ${LAB} (a shallow clone?)." >&2
    exit 1
fi

python3 "${REPO}/verify/lab_text.py" --commit "${commit}" --changed "${changed}" \
    --copied "$(date -u +%F)" --out "${OUT}"
