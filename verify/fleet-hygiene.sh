#!/usr/bin/env bash
# ABOUTME: Standing hygiene gate: security advisories, pinned versions, orphaned AWS resources, and
# ABOUTME: whether the internal slot id has leaked back into anything a student reads. Read-only.
#
# WHY THIS IS A SCRIPT AND NOT A CHECKLIST. Every check below was run by hand at least once during the
# 2026-09-02 rehearsal, and hand-rolling them has two failure modes that both already happened. The first
# is that a check gets skipped because nobody remembers it exists. The second is worse and is the reason
# preflight.sh reported GREEN over four missing VPCs for two months: a check written fresh each time is a
# check whose past answers cannot be compared, so a regression looks like a first observation.
#
# Everything here is a READ. It never deletes, never applies, never mutates. The orphan section calls
# `fleet.sh reap-lbs` in its dry-run mode; deleting is a deliberate separate act with WIB_APPLY=1.
#
# Exit codes: 0 clean, 1 something needs a human. Safe to run from cron or before a fleet run.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly SCRIPT_DIR
readonly REPO="${SCRIPT_DIR}/.."
readonly GH_REPO="${WIB_GH_REPO:-peopleforrester/Unleash_an_Agent_Watch_It_Burn}"
WIB_REGION="${WIB_REGION:-us-west-2}"

fail=0
ok()   { printf '  PASS  %s\n' "$1"; }
bad()  { printf '  FAIL  %s\n' "$1"; fail=1; }
note() { printf '  note  %s\n' "$1"; }

# --- 1. Dependency advisories -----------------------------------------------------------------------
# Dependabot covers what is in a lockfile. It says nothing about the Helm charts below, which is the gap
# that made #155 necessary: the repo can show zero alerts while a pinned chart carries a live CVE.
echo "== dependency advisories (Dependabot) =="
if command -v gh >/dev/null 2>&1; then
    alerts="$(gh api "repos/${GH_REPO}/dependabot/alerts" --paginate 2>/dev/null || true)"
    if [[ -n "${alerts}" ]]; then
        counts="$(printf '%s' "${alerts}" | python3 -c '
import sys, json
from collections import Counter
try: a = json.load(sys.stdin)
except Exception: print("unreadable"); raise SystemExit
o = [x for x in a if x.get("state") == "open"]
c = Counter(x["security_advisory"]["severity"] for x in o)
print(f"{len(o)}|{c.get(\"critical\",0)}|{c.get(\"high\",0)}|{c.get(\"medium\",0)}|{c.get(\"low\",0)}")
for x in o:
    if x["security_advisory"]["severity"] in ("critical", "high"):
        print(f"    {x[\"security_advisory\"][\"severity\"].upper():8} "
              f"{x[\"dependency\"][\"package\"][\"name\"]:24} {x[\"security_advisory\"][\"ghsa_id\"]}")
' 2>/dev/null || true)"
        summary="$(printf '%s' "${counts}" | head -1)"
        IFS='|' read -r total crit high med low <<<"${summary}"
        printf '%s\n' "${counts}" | tail -n +2
        if [[ "${crit:-0}" -gt 0 || "${high:-0}" -gt 0 ]]; then
            bad "${total} open alert(s): ${crit} critical, ${high} high"
        elif [[ "${total:-0}" -gt 0 ]]; then
            note "${total} open alert(s), none critical or high (${med} medium, ${low} low)"
        else
            ok "no open Dependabot alerts"
        fi
    else
        note "Dependabot API returned nothing (alerts may be disabled, or gh is unauthenticated)"
    fi
else
    note "gh not installed; skipping the Dependabot check"
fi

# --- 2. Pinned platform versions --------------------------------------------------------------------
# Reported, not judged. A version check that tries to decide on its own what is vulnerable goes stale the
# moment it is written, and a stale opinion is worse than no opinion. This prints what is pinned so the
# comparison against the projects' own advisory pages is a lookup rather than an archaeology exercise.
echo
echo "== pinned platform versions (compare against each project's advisories) =="
python3 - "${REPO}" <<'PY'
import re, sys, pathlib
apps = pathlib.Path(sys.argv[1], "gitops/apps")
rows = []
for f in sorted(apps.glob("*.yaml")):
    t = f.read_text(encoding="utf-8", errors="replace")
    m = re.search(r'targetRevision:\s*"?([^"\s]+)"?', t)
    c = re.search(r'chart:\s*"?([^"\s]+)"?', t)
    if m and c and m.group(1) not in ("staging", "HEAD", "main"):
        rows.append((c.group(1), m.group(1)))
for chart, ver in sorted(set(rows)):
    print(f"    {chart:<34} {ver}")
print(f"    ({len(set(rows))} pinned charts)")
PY
note "advisory pages: kyverno.io/docs, cert-manager.io, falco.org, kubearmor.io, istio.io/news/security"

# --- 3. Orphaned AWS resources ----------------------------------------------------------------------
# A torn-down cluster that leaves its load balancers behind bills indefinitely and nothing looks for it,
# because the cluster it was tagged for no longer exists (#157). Dry-run survey only.
echo
echo "== orphaned load balancers, target groups and volumes =="
if [[ -x "${REPO}/infra/terraform/fleet/fleet.sh" ]]; then
    out="$("${REPO}/infra/terraform/fleet/fleet.sh" reap-lbs 2>&1 | grep -E 'ORPHAN|no orphans|found [0-9]+ orphan' || true)"
    if printf '%s' "${out}" | grep -q "no orphans"; then
        ok "no orphaned AWS resources across the fleet accounts"
    elif [[ -n "${out}" ]]; then
        printf '%s\n' "${out}" | sed 's/^/    /'
        bad "orphaned resources found. Delete with: WIB_APPLY=1 fleet.sh reap-lbs"
    else
        note "reap-lbs produced no output (no AWS credentials?)"
    fi
else
    note "fleet.sh not executable; skipping the orphan survey"
fi

# --- 4. Internal slot id must not reach a student ---------------------------------------------------
# watch-it-burn-attendee-NNN is a provisioning slot id. It is not the hostname the student was given, not
# the name on their claim page, and not something anyone can act on or read aloud. It kept surfacing as a
# heading, a browser title, and a facilitator instruction.
#
# THIS CHECK IS DELIBERATELY LIVE, NOT A GREP. The first version of it grepped the templates for the
# literal string and passed against a template that was actively printing the slot id, because the
# template renders it from a Jinja variable ({{ cluster_name }}) and the literal never appears in source.
# A static check cannot see through a variable, so it answered a question nobody asked. The only honest
# test is to render the page and read it, which is the same discipline as reading a page instead of its
# URL. Query strings are exempt: the lab link needs the parameter and nobody sees it.
echo
echo "== the internal slot id has not leaked back into student-facing text =="
PROBE_EMAIL="${WIB_PROBE_EMAIL:-}"
PROV_URL="${WIB_PROVISIONING_URL:-https://provisioning.agenticburn.com}"
if [[ -z "${PROBE_EMAIL}" ]]; then
    note "set WIB_PROBE_EMAIL to an address that ALREADY holds a claim to run the rendered-page check"
    note "(claiming is idempotent for an existing email, so it consumes nothing)"
else
    body="$(curl -sS -X POST "${PROV_URL}/eks-claim" --data-urlencode "email=${PROBE_EMAIL}" --max-time 40 2>/dev/null || true)"
    if [[ -z "${body}" ]]; then
        bad "could not render the claim page at ${PROV_URL}"
    else
        # Strip tags, then look only at what a human reads.
        visible="$(printf '%s' "${body}" | sed 's/<[^>]*>/ /g' | grep -oE 'watch-it-burn-attendee-[0-9]+' | sort -u || true)"
        if [[ -n "${visible}" ]]; then
            printf '    visible on the claim page: %s\n' "${visible}"
            bad "the claim page prints the slot id where a student reads it"
        else
            ok "claim page shows the friendly hostname, not the slot id"
        fi
        # The browser tab is student-facing too and was missed once already.
        title="$(printf '%s' "${body}" | grep -oE '<title>[^<]*</title>' | head -1 || true)"
        if printf '%s' "${title}" | grep -q 'watch-it-burn-attendee'; then
            bad "the browser title still carries the slot id: ${title}"
        else
            ok "browser title is clean: ${title:-<none>}"
        fi
    fi
fi
# The lab and BurritoBot pages build their label in JS, so a hardcoded literal there IS catchable
# statically and is worth failing on. Comments are stripped first.
leaks=0
for f in "${REPO}"/gitops/ai-layer/web/*.html; do
    [[ -f "${f}" ]] || continue
    hits="$(perl -0777 -pe 's{<!--.*?-->}{}gs; s{^\s*//.*$}{}gm;' "${f}" \
            | grep -nE "'watch-it-burn-attendee|\"watch-it-burn-attendee" || true)"
    if [[ -n "${hits}" ]]; then
        printf '    %s\n' "${f#"${REPO}"/}"; printf '%s\n' "${hits}" | sed 's/^/      /' | cut -c1-120
        leaks=1
    fi
done
[[ "${leaks}" -eq 0 ]] && ok "no lab page hardcodes the slot id" \
                       || bad "a lab page hardcodes the slot id above"

echo
if [[ "${fail}" -eq 0 ]]; then
    echo "HYGIENE CLEAN"
    exit 0
fi
echo "HYGIENE: items above need a human." >&2
exit 1
