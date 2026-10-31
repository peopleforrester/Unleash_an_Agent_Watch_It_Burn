#!/usr/bin/env bash
# ABOUTME: Finds or requests the ACM certificate a roster cluster's console NLB presents (#638), prints the DNS
# ABOUTME: validation records it waits on, and once ISSUED prints its bare ARN, the value labctl's --front-door-cert takes.
#
# Why. lab-platform's gateway proxies attackme and burritobot-private to the console Service lab-platform.yaml
# declares as each roster profile's front_door, and verifies its certificate against the system roots. nginx's
# self-signed certificate is refused there. One ACM certificate per account and region, for the two domains the
# platform answers on (#651), covers every roster cluster in it: ACM renews it while a load balancer uses it and
# its validation CNAMEs stay in DNS, so this runs once per account and region, not once per build. One left unused
# between events can expire; it is not reused, and this requests a new one and prints its records.
#
# Each validation record goes on the domain's DNS. agenticburn.com and burritobot.co are both on Namecheap (#651),
# written with infra/dns/set-demo-dns.py (dry run first, --apply only with Michael's go); the lines below are its
# arguments.
#
# AWS profile and region are both required and passed on every call (repo CLAUDE.md rule 6).
#
# Usage:
#   infra/front-door-cert.sh <aws-profile> <region>
# Exit 0 with the certificate ISSUED; 3 while it waits on its validation records; anything else is an error.
#
# Once issued, stdout is the ARN alone, so it goes straight into labctl:
#   labctl event up ... --front-door-cert="$(infra/front-door-cert.sh <aws-profile> <region>)"
# labctl hands it to each roster cluster's lab-bootstrap root as frontDoor.certificateArn, and refuses the pasted
# 'frontDoor.certificateArn=<arn>' line this printed before (lab-platform#297). A root built by hand takes the same
# ARN as --set frontDoor.certificateArn=<arn>.
set -euo pipefail

PROFILE="${1:?usage: front-door-cert.sh <aws-profile> <region>}"
REGION="${2:?usage: front-door-cert.sh <aws-profile> <region>}"
DOMAIN="*.agenticburn.com"
SAN="*.burritobot.co"

acm() { AWS_PROFILE="${PROFILE}" aws acm --region "${REGION}" "$@"; }

# An existing certificate for both names, issued or still waiting, is reused: a second request would leave two
# certificates and two sets of validation records for the same pair.
arn="$(acm list-certificates --certificate-statuses ISSUED PENDING_VALIDATION \
  --query "CertificateSummaryList[?DomainName=='${DOMAIN}' && contains(SubjectAlternativeNameSummaries, '${SAN}')].CertificateArn | [0]" \
  --output text)"
if [[ -z "${arn}" || "${arn}" == "None" ]]; then
  arn="$(acm request-certificate --domain-name "${DOMAIN}" --subject-alternative-names "${SAN}" \
    --validation-method DNS --idempotency-token wibfrontdoor \
    --tags Key=project,Value=watch-it-burn Key=component,Value=front-door-cert \
    --query CertificateArn --output text)"
  echo "requested ${arn}" >&2
else
  echo "found ${arn}" >&2
fi
[[ "${arn}" == arn:aws*:acm:"${REGION}":*:certificate/* ]] || { echo "ERROR: ACM returned no certificate ARN (got '${arn}')" >&2; exit 1; }

# ACM fills in the validation records a few seconds after the request; until then they read None.
for _ in $(seq 1 12); do
  status="$(acm describe-certificate --certificate-arn "${arn}" --query Certificate.Status --output text)"
  records="$(acm describe-certificate --certificate-arn "${arn}" \
    --query "Certificate.DomainValidationOptions[].[DomainName, ResourceRecord.Name, ResourceRecord.Value]" \
    --output text)"
  [[ "${status}" == ISSUED || ( -n "${records}" && "${records}" != *None* ) ]] && break
  sleep 5
done

case "${status}" in
  ISSUED)
    echo "ISSUED: give it to labctl event up as --front-door-cert=<arn> for the roster clusters in ${REGION}:" >&2
    echo "${arn}"
    ;;
  PENDING_VALIDATION)
    [[ -n "${records}" && "${records}" != *None* ]] || { echo "ERROR: ${arn} is pending with no validation records yet; run again" >&2; exit 1; }
    echo "PENDING_VALIDATION: ${arn} is issued once these CNAMEs resolve; then run this again." >&2
    while read -r name rec value; do
      zone="${name#\*.}"
      host="${rec%.}"; host="${host%."${zone}"}"
      echo "  ${zone}: CNAME ${host} -> ${value%.}" >&2
      echo "    python3 infra/dns/set-demo-dns.py --domain ${zone} ${host}=${value%.}" >&2
    done <<<"${records}"
    exit 3
    ;;
  *)
    echo "ERROR: ${arn} is ${status}; delete it in the ACM console or with aws acm delete-certificate and run again" >&2
    exit 1
    ;;
esac
