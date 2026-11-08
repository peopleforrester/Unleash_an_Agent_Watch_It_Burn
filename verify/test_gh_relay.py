# ABOUTME: Offline check of the gh relay the wib-e2e-tools image uses (#1188): `gh issue view` inside the container is
# ABOUTME: answered by the host's gh through verify/gh_relay.py, and every other gh call is refused by name.
"""Offline: a stand-in host gh, a real relay server on a Unix socket, and the image's own client, verify/e2e-image/gh,
run with this host's python (its shebang names the image's).

What it holds:
  - `gh issue view <n> -R <repo> --json comments` comes back with the host gh's stdout, stderr and exit code, the exit
    4 of a gh with no token included, which verify/gh_comments.py reads as "no token";
  - any other gh call (`gh api`, `gh issue comment`, `gh pr view`) gets exit 2 and a line naming what was refused, and
    the host gh never runs for it;
  - the client with no socket exits 4 naming where it looked, and the server with no gh on PATH fails before serving.
"""
from __future__ import annotations

import os
import pathlib
import subprocess
import sys
import tempfile
import time

HERE = pathlib.Path(__file__).resolve().parent
CLIENT = HERE / "e2e-image" / "gh"
SERVER = HERE / "gh_relay.py"

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail and not ok else ""))
    if not ok:
        failures.append(name)


with tempfile.TemporaryDirectory() as tmp:
    t = pathlib.Path(tmp)
    log = t / "gh.log"
    fake = t / "gh"
    fake.write_text(f"""#!/bin/sh
echo "$*" >> "{log}"
case "$3" in
  no-token) echo "To get started with GitHub CLI, please run:  gh auth login" >&2; exit 4 ;;
esac
printf '{{"comments": [{{"body": "from the host, issue %s"}}]}}\\n' "$3"
echo "a warning on stderr" >&2
""")
    fake.chmod(0o755)
    sock = t / "gh.sock"
    server = subprocess.Popen([sys.executable, str(SERVER), "serve", str(sock), "--gh", str(fake)],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        for _ in range(100):
            if sock.exists():
                break
            time.sleep(0.05)
        check("the relay serves a socket", sock.exists())
        check("the socket is the user's alone", sock.exists() and (sock.stat().st_mode & 0o077) == 0,
              oct(sock.stat().st_mode) if sock.exists() else "")
        env = {**os.environ, "WIB_GH_SOCKET": str(sock)}

        def gh(*args: str) -> subprocess.CompletedProcess:
            return subprocess.run([sys.executable, str(CLIENT), *args], capture_output=True, text=True, env=env,
                                  timeout=60)

        r = gh("issue", "view", "1188", "-R", "peopleforrester/Unleash_an_Agent_Watch_It_Burn", "--json", "comments")
        check("`gh issue view` is answered by the host's gh", r.returncode == 0
              and '"from the host, issue 1188"' in r.stdout, r.stdout + r.stderr)
        check("with its stderr passed through", "a warning on stderr" in r.stderr, r.stderr)
        check("the host gh got the same arguments",
              log.read_text().splitlines()[-1] == "issue view 1188 -R peopleforrester/Unleash_an_Agent_Watch_It_Burn "
                                                  "--json comments")
        r = gh("issue", "view", "no-token", "-R", "o/r", "--json", "comments")
        check("a host gh with no token exits 4 through the relay", r.returncode == 4 and "gh auth login" in r.stderr,
              f"{r.returncode} {r.stderr}")
        calls = log.read_text()
        for refused in (["api", "repos/o/r/issues/1/comments"], ["issue", "comment", "1", "--body", "x"],
                        ["pr", "view", "1"], ["issue"], []):
            r = gh(*refused)
            check(f"`gh {' '.join(refused)}` is refused with exit 2, naming it",
                  r.returncode == 2 and "only `gh issue view` is relayed" in r.stderr, f"{r.returncode} {r.stderr}")
        check("and the host gh ran for none of them", log.read_text() == calls, log.read_text())
    finally:
        server.terminate()
        server.wait(timeout=10)

    r = subprocess.run([sys.executable, str(CLIENT), "issue", "view", "1"], capture_output=True, text=True,
                       env={**os.environ, "WIB_GH_SOCKET": str(t / "none.sock")}, timeout=30)
    check("with no relay socket, gh exits 4 naming where it looked",
          r.returncode == 4 and str(t / "none.sock") in r.stderr, r.stderr)
    r = subprocess.run([sys.executable, str(SERVER), "serve", str(t / "x.sock")], capture_output=True, text=True,
                       env={**os.environ, "PATH": str(t / "empty")}, timeout=30)
    check("the relay with no gh on the host's PATH fails before serving",
          r.returncode == 1 and "no gh on the host's PATH" in r.stderr and not (t / "x.sock").exists(), r.stderr)

check("the image's gh is the relay client", (HERE / "e2e-image" / "gh").read_text().startswith(
    "#!/opt/wib-e2e-tools/py/bin/python3\n"))
check("and the Containerfile puts it on PATH as gh",
      "COPY e2e-image/gh /usr/local/bin/gh" in (HERE / "e2e-image" / "Containerfile").read_text())

if failures:
    print(f"\nFAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("\nAll gh relay checks passed.")
