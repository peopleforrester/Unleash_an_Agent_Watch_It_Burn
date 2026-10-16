#!/usr/bin/env bash
# ABOUTME: Heavy suite: installs the Backstage workspace and runs its Playwright browser tests, which
# ABOUTME: start the app and backend locally. No cluster needed; Node 24 and yarn 4 (corepack) are.
#
# One script rather than a chained command line because the hecaton gate runs the declared command
# without a shell: `&&` and `env -u` reach the first program as arguments.
# CI is unset on purpose: with CI set, playwright.config.ts starts no web servers and expects one to be
# running already on :7007.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}/../images/watch-it-burn-backstage"
unset CI

for tool in node yarn; do
    command -v "${tool}" >/dev/null || { printf 'FAIL: %s not on PATH (needs Node 24 and yarn 4)\n' "${tool}" >&2; exit 1; }
done

yarn install --immutable
yarn playwright install chromium
yarn test:e2e
