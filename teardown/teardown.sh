#!/usr/bin/env bash
# ABOUTME: Thin wrapper over `fleet.sh down all`, kept only so existing callers and docs keep working.
# ABOUTME: It adds nothing of its own: every step it used to perform now lives in fleet.sh.
#
# Why this file is now three lines (#398).
#
# There used to be two implementations of "tear it down" and they did different work. This script ran
# the fleet destroy, then a tag audit, then a log-group cleanup, and optionally a lab VPC destroy.
# `fleet.sh down` did only the first. `scheduled-down.sh`, the cron path and therefore the one that
# actually runs unattended, calls `fleet.sh down`.
#
# So the unattended path was the LESS complete one. That is how 107 orphaned log groups and about 111 GB
# accumulated while a correct cleanup-log-groups.sh sat in the repo, wired into the path nobody runs.
#
# Two implementations of one verb guarantee that whichever is run, something is skipped, and because both
# exit zero the gap is invisible until somebody sweeps by hand. Everything this script used to do is now
# in `fleet.sh down all`:
#
#   fleet destroy      down_one, per cluster, account-aware
#   tag audit          absorbed here, runs across every attendee account before the sweeps
#   log groups         sweep_orphan_log_group, per cluster
#   security groups    sweep_orphan_sgs, per cluster
#   lab VPC            cmd_down_infra, chained unless WIB_KEEP_VPC=1
#   audit              audit_zero
#
# Secrets are NOT included, deliberately: the Datadog pool is what the next `up` provisions against.
# Use `fleet.sh reap-secrets` when that is actually wanted.
#
# Usage: teardown/teardown.sh [--keep-vpc]
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly FLEET="$(cd "${SCRIPT_DIR}/../infra/terraform/fleet" && pwd)/fleet.sh"

[[ "${1:-}" == "--keep-vpc" ]] && export WIB_KEEP_VPC=1
echo "teardown: delegating to fleet.sh down all (this script adds nothing of its own)" >&2
exec env WIB_APPLY=1 "${FLEET}" down all
