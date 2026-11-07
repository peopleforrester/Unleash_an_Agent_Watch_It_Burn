# Generate and store a new presenter terminal login for the KubeCon clusters

Repo: `peopleforrester/mrf-secrets`
Label: `agent-task`
Discovered from: `peopleforrester/Unleash_an_Agent_Watch_It_Burn#910`

This file is the body of the agent-task issue that asks mrf-secrets for the presenter terminal login. It is kept here
because no run can open or file on mrf-secrets, and `verify/test_terminal_login_request.py` holds it to the file and
keys `infra/terraform/fleet/fleet.sh` reads. The issue body is everything below the line.

---

The workshop repo `Unleash_an_Agent_Watch_It_Burn` no longer carries a default for the presenter login of its web
terminal (ttyd, code-server and Jupyter) on the private admin cluster, watch-it-burn-private. The community cluster,
watch-it-burn-community, takes the same login. Since #910 there, `infra/terraform/fleet/fleet.sh` reads the login from
this repo, and this repo does not hold it yet.

Asked here:

1. Generate a new presenter login. The user name holds no colon and no whitespace, since ttyd splits its credential
   on the first colon. The password is random, at least 24 characters, with no whitespace.
2. Store it in the file `projects/watch-it-burn-terminal.env`, beside `projects/watch-it-burn-provisioning.env`, as
   the two keys `WIB_TERMINAL_USER` and `WIB_TERMINAL_PASSWORD`, one key per line in the same shape as the
   provisioning file. These are the file and keys fleet.sh's `presenter_login` reads from `~/secrets`.
3. Commit and push it the way this repo's rules ask for a rotation.

The old login is in the workshop repo's public history and is treated as known, so do not reuse it. This issue
carries no login value, old or new, and nothing posted on it should carry one either.

Once it is stored, `./fleet.sh terminal-password watch-it-burn-private watch-it-burn-community`, run on tanjiro-wsl2
from `infra/terraform/fleet/`, writes it to both clusters, and `bash verify/terminal-login-live.sh` checks that each
terminal takes it and refuses the old one (#912 in the workshop repo).

(Note kept in the workshop repo, not part of the body: on 2026-11-07 the login on both clusters was set by hand
instead (#1069), and since #1074 `fleet.sh terminal-password` refuses those two clusters.)
