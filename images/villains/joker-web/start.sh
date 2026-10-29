#!/bin/sh
# ABOUTME: The C6 Joker's entrypoint (#664): busybox httpd serves the "HA HA HA" page on $PORT, and the old
# ABOUTME: catchphrase loop keeps laughing in the logs. Ends on SIGTERM, so a delete does not wait out the grace.
set -eu
: "${PORT:?PORT is not set: build.sh sets PORT=8080 on the image}"
ROOT="$(dirname "$0")"
LINE='HAHAHA! The Joker runs on your cluster now. Why so SERIOUS about admission control?'

# Each child is started in the background and the shell waits, because PID 1 gets no default signal
# handling: an httpd exec'd as PID 1 would ignore the kubelet's SIGTERM and be killed 30 seconds later.
( while true; do echo "${LINE}"; sleep 10; done ) &
LOOP=$!
httpd -f -p "${PORT}" -h "${ROOT}/www" &
HTTPD=$!
trap 'kill "${LOOP}" "${HTTPD}" 2>/dev/null; exit 0' TERM INT
echo "${LINE} (serving the proof on :${PORT})"
wait
