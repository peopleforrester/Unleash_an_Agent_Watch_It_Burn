#!/bin/bash
# ABOUTME: Watches REAL cluster state and writes a nudge file when the attendee looks genuinely stuck.
# ABOUTME: The lab page polls that file and offers the tutor; it never opens the tutor by itself.
#
# The first version of this grepped the terminal transcript for error strings. That is a weak signal
# and it was dropped: the main terminal is mostly the attendee's own agent UI, so it is full of text
# that reads like an error while nothing is wrong. This polls cluster state instead.
#
# It requires the SAME failure to persist across two polls before saying anything. A build in progress
# churns through CrashLoopBackOff and Degraded on its way to healthy, and a tutor that fires on the
# first sight of those is a tutor the attendee learns to ignore inside five minutes.
set -uo pipefail

export HOME=/home/student
NUDGE="$HOME/.nudge/nudge"
INTERVAL="${TUTOR_WATCH_INTERVAL:-45}"

# This lives in its own directory, NOT alongside the session transcript, because the directory is
# served over HTTP for the lab page to poll. ~/.session holds the transcript of everything the attendee
# typed; publishing that on the pod network would leak whatever they pasted into their shell.
#
# The file is also read by a different uid than writes it. A restrictive inherited umask produced a
# 0600 file once and the endpoint returned 403, which presented as the banner simply never appearing
# with nothing in any log saying why. Set the mask explicitly and chmod after writing.
umask 022
mkdir -p "$HOME/.nudge"

prev=""
while true; do
  sleep "${INTERVAL}"
  now=""

  # Pods wedged in a state that does not resolve on its own.
  bad_pods="$(kubectl get pods -A --no-headers 2>/dev/null \
    | awk '$4 ~ /CrashLoopBackOff|ImagePullBackOff|ErrImagePull|CreateContainerConfigError|InvalidImageName/ {print $2" "$4}' \
    | head -5)"
  [[ -n "${bad_pods}" ]] && now+="pods:${bad_pods}"

  # Applications that ArgoCD has given up reconciling.
  bad_apps="$(kubectl get applications -n argocd \
      -o jsonpath='{range .items[?(@.status.health.status=="Degraded")]}{.metadata.name}{" "}{end}' 2>/dev/null)"
  [[ -n "${bad_apps}" ]] && now+="apps:${bad_apps}"

  if [[ -z "${now}" ]]; then
    prev=""
    [[ -f "${NUDGE}" ]] && rm -f "${NUDGE}"   # cleared itself, so withdraw the offer
    continue
  fi

  # Same failure twice running, so it is not mid-build churn.
  if [[ "${now}" == "${prev}" ]]; then
    {
      printf 'Something on your cluster has been unhealthy for a couple of minutes.\n\n'
      [[ -n "${bad_pods}" ]] && printf 'Pods: %s\n' "$(printf '%s' "${bad_pods}" | tr '\n' ';')"
      [[ -n "${bad_apps}" ]] && printf 'Degraded apps: %s\n' "${bad_apps}"
      printf '\nThis may be the exercise working as intended. Open the Tutor tab and it will tell you which.\n'
    } > "${NUDGE}"
    chmod 0644 "${NUDGE}"
  fi
  prev="${now}"
done
