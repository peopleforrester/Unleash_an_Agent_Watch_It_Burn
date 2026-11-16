# ABOUTME: Offline check of the gh relay the wib-e2e-tools image uses (#1188): `gh issue view` inside the container is
# ABOUTME: answered by the host's gh through verify/gh_relay.py, and every other gh call is refused by name.
"""Offline: a stand-in host gh, a real relay server on a Unix socket, and the image's own client, verify/e2e-image/gh,
run with this host's python (its shebang names the image's).

What it holds:
  - `gh issue view <n> -R <repo> --json comments` comes back with the host gh's stdout, stderr and exit code, the exit
    4 of a gh with no token included, which verify/gh_comments.py reads as "no token";
  - any other gh call (`gh api`, `gh issue comment`, `gh pr view`) fails with exit code 1 and a line naming what was
    refused, and the host gh never runs for it;
  - the client with no socket exits 4 naming where it looked, and the server with no gh on PATH fails before serving;
  - a socket whose path is longer than a Unix socket address holds (107 bytes) is served all the same, and the host's
    gh still runs in the directory the relay started in (#1481). verify/e2e-image.sh makes the socket under TMPDIR,
    and hecaton's gate has a temp root whose length goes with its pool's name; the long path here is this test's own.
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
            check(f"`gh {' '.join(refused)}` is refused with exit code 1, naming it",
                  r.returncode == 1 and "only `gh issue view` is relayed" in r.stderr, f"{r.returncode} {r.stderr}")
        check("and the host gh ran for none of them", log.read_text() == calls, log.read_text())
    finally:
        server.terminate()
        server.wait(timeout=10)

    # A socket path past the 107 bytes a Unix socket address holds (#1481). The relay is started in `started`, and the
    # client reaches the socket by its name from inside its directory, as the container does by its short mount path.
    deep = t / ("a-temp-root-longer-than-a-socket-address-holds-" + "x" * 80)
    deep.mkdir()
    started = t / "started-here"
    started.mkdir()
    cwd_log = t / "gh.cwd"
    recorder = t / "gh-cwd"
    recorder.write_text(f'#!/bin/sh\npwd > "{cwd_log}"\necho \'{{"comments": []}}\'\n')
    recorder.chmod(0o755)
    long_sock = deep / "gh.sock"
    check("the long socket path is longer than a Unix socket address holds", len(os.fsencode(long_sock)) > 107,
          str(len(os.fsencode(long_sock))))
    server = subprocess.Popen([sys.executable, str(SERVER), "serve", str(long_sock), "--gh", str(recorder)],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=started)
    try:
        for _ in range(100):
            if long_sock.exists() or server.poll() is not None:
                break
            time.sleep(0.05)
        check("the relay serves a socket whose path is longer than that", long_sock.exists() and server.poll() is None,
              server.stderr.read()[-600:] if server.poll() is not None else "no socket yet")
        check("and that socket is the user's alone", long_sock.exists() and (long_sock.stat().st_mode & 0o077) == 0,
              oct(long_sock.stat().st_mode) if long_sock.exists() else "")
        r = subprocess.run([sys.executable, str(CLIENT), "issue", "view", "1481", "-R", "o/r", "--json", "comments"],
                           capture_output=True, text=True, cwd=deep, timeout=60,
                           env={**os.environ, "WIB_GH_SOCKET": "gh.sock"})
        check("`gh issue view` is answered through it", r.returncode == 0 and '"comments"' in r.stdout,
              f"{r.returncode} {r.stdout} {r.stderr}")
        check("and the host's gh ran in the directory the relay started in, not the socket's",
              cwd_log.exists() and cwd_log.read_text().strip() == str(started.resolve()),
              cwd_log.read_text() if cwd_log.exists() else "the host gh never ran")
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
