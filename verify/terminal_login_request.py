# ABOUTME: Holds the mrf-secrets request for the presenter terminal login to what fleet.sh reads (#910, #932): it asks
# ABOUTME: for a new login to be generated and stored, names fleet.sh's file and keys, and carries no login value.
"""The agent-task issue on mrf-secrets that asks for the presenter terminal login (#910, #932).

Why. #910 took the presenter login's literal default out of `infra/terraform/fleet/fleet.sh`. fleet.sh's
`presenter_login` now reads it from mrf-secrets, the file its `WIB_TERMINAL_ENV` default names under `~/secrets/`,
as the keys it hands to `_terminal_env_value`. Nothing stores it there until an agent-task issue on mrf-secrets asks
for it. #910's criterion is that this issue asks for the new login to be generated and stored, names the file and
keys this repo reads, and carries no login value. No run can open mrf-secrets (gh refuses it as a data vault), so the
request's text is kept in this repo at `docs/requests/mrf-secrets-terminal-login.md`, and this module checks it.

`problems(title, body, labels, need)` returns what a request leaves out or carries that it must not, empty when it
meets the criterion. `need` is read from fleet.sh by `fleet_reads()`, never written here, so a rename of the file or a
key in fleet.sh fails the request until the request follows it. "No login value" means three things: fleet.sh's own
`_terminal_env_value`, run on the request's text, reads nothing for either key; no line assigns either key, or
`TTYD_CREDENTIAL`, a value in any of the forms `KEY=v`, `export KEY="v"`, `KEY: v`, `"KEY": "v"`; and no token hashes
to the old login, whose digests `verify/test_no_presenter_login.py` holds.

Live use, on a host whose gh can read mrf-secrets (none a run reaches):

    gh issue list -R peopleforrester/mrf-secrets --label agent-task --state all \\
        --search "WIB_TERMINAL_USER in:body" --json number,title,body,labels,url >issues.json
    python3 verify/terminal_login_request.py --issues issues.json

or `--gh` to call gh itself. It exits 0 naming the first issue that meets the criterion, and 1 when none does or gh
cannot read the repo, with each issue's problems. It never prints an issue's body. With no flag it checks the
committed request.
"""
from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

REPO = pathlib.Path(__file__).resolve().parent.parent
FLEET = REPO / "infra" / "terraform" / "fleet" / "fleet.sh"
GUARD = REPO / "verify" / "test_no_presenter_login.py"
REQUEST = REPO / "docs" / "requests" / "mrf-secrets-terminal-login.md"
VAULT = "peopleforrester/mrf-secrets"
LABEL = "agent-task"

PATH_ANCHOR = re.compile(r'^WIB_TERMINAL_ENV="\$\{WIB_TERMINAL_ENV:-\$\{HOME\}/secrets/([^}"]+)\}"', re.M)
KEY_ANCHOR = re.compile(r'_terminal_env_value (\w+) "\$\{WIB_TERMINAL_ENV\}"')
FN_ANCHOR = re.compile(r"^_terminal_env_value\(\) \{\n.*?^\}\n", re.M | re.S)
DIGESTS_ANCHOR = re.compile(r"OLD_LOGIN_SHA256 = frozenset\(\{(.*?)\}\)", re.S)
TOKEN = re.compile(r"[A-Za-z0-9]+")


class AnchorMissing(Exception):
    """A literal this module reads from fleet.sh or the guard test is not there: the file changed shape."""


@dataclasses.dataclass(frozen=True)
class Need:
    path: str                     # the file under ~/secrets/, as fleet.sh's WIB_TERMINAL_ENV default names it
    keys: tuple[str, ...]         # the keys presenter_login asks _terminal_env_value for, in order
    parser: str                   # fleet.sh's _terminal_env_value, as bash source
    old_login: frozenset[str]     # sha256 digests of the old login, from the guard test


def fleet_reads(fleet: pathlib.Path = FLEET, guard: pathlib.Path = GUARD) -> Need:
    """The file, keys and parser fleet.sh reads the presenter login with, and the old login's digests."""
    src = fleet.read_text(encoding="utf-8")
    m = PATH_ANCHOR.search(src)
    if not m:
        raise AnchorMissing(f"{fleet}: no line {PATH_ANCHOR.pattern!r} (WIB_TERMINAL_ENV's default under ~/secrets/)")
    keys = tuple(dict.fromkeys(KEY_ANCHOR.findall(src)))
    if len(keys) < 2:
        raise AnchorMissing(f"{fleet}: expected presenter_login to read two keys with {KEY_ANCHOR.pattern!r}, "
                            f"found {list(keys)}")
    fn = FN_ANCHOR.search(src)
    if not fn:
        raise AnchorMissing(f"{fleet}: no function `_terminal_env_value() {{ ... }}`")
    g = DIGESTS_ANCHOR.search(guard.read_text(encoding="utf-8"))
    digests = frozenset(re.findall(r'"([0-9a-f]{64})"', g.group(1))) if g else frozenset()
    if not digests:
        raise AnchorMissing(f"{guard}: no OLD_LOGIN_SHA256 = frozenset({{...}}) holding sha256 digests")
    return Need(m.group(1), keys, fn.group(0), digests)


PARSER_TIMEOUT_S = 120


def parsed_values(text: str, need: Need) -> list[str]:
    """The keys fleet.sh's own parser reads a non-empty value for from `text`, as if it were the env file."""
    with tempfile.TemporaryDirectory() as tmp:
        env = pathlib.Path(tmp) / "request.env"
        env.write_text(text, encoding="utf-8")
        found = []
        for key in need.keys:
            # 120s, not 30: one bash of this small parser took over 30s on the shared host at load 68 (run 17944).
            try:
                p = subprocess.run(["bash", "-c", need.parser + '\n_terminal_env_value "$1" "$2"', "_", key, str(env)],
                                   capture_output=True, text=True, timeout=PARSER_TIMEOUT_S)
            except subprocess.TimeoutExpired:
                raise RuntimeError(f"fleet.sh's _terminal_env_value did not answer for {key} in {PARSER_TIMEOUT_S}s")
            if p.returncode != 0:
                raise RuntimeError(f"fleet.sh's _terminal_env_value exited {p.returncode}: {p.stderr.strip()[:200]}")
            if p.stdout:
                found.append(key)
        return found


def assigned(text: str, keys: tuple[str, ...]) -> list[str]:
    """`key (line n)` for each line that gives a key, or TTYD_CREDENTIAL, a value."""
    names = "|".join(re.escape(k) for k in (*keys, "TTYD_CREDENTIAL"))
    pat = re.compile(rf"(?<![\w-])({names})[`'\"]?\s*[:=]\s*[`'\"]?(?=[^\s`'\",])")
    return [f"{m.group(1)} (line {n})" for n, line in enumerate(text.splitlines(), 1) for m in pat.finditer(line)]


def old_login_lines(text: str, digests: frozenset[str]) -> list[int]:
    """Line numbers holding a token whose sha256, as written or lowercased, is one of `digests`."""
    def h(t: str) -> str:
        return hashlib.sha256(t.encode("utf-8")).hexdigest()
    return [n for n, line in enumerate(text.splitlines(), 1)
            if any(h(t) in digests or h(t.lower()) in digests for t in TOKEN.findall(line))]


def problems(title: str, body: str, labels: list[str], need: Need) -> list[str]:
    """What the request leaves out or must not carry; empty when it meets #910's criterion."""
    text = f"{title}\n{body}"
    low = text.lower()
    out = []
    if LABEL not in labels:
        out.append(f"it is not labelled {LABEL} (labels: {', '.join(labels) or 'none'})")
    if not re.search(r"\bgenerat(e|ed|es|ing)\b", low):
        out.append("it does not ask for the login to be generated")
    if not re.search(r"\bnew\b", low):
        out.append("it does not ask for a new login")
    if not re.search(r"\bstor(e|ed|es|ing)\b", low):
        out.append("it does not ask for the login to be stored")
    if "terminal" not in low:
        out.append("it does not say the login is the presenter terminal's")
    if not re.search(rf"(?<![\w./-]){re.escape(need.path)}(?![\w.-])", text):
        out.append(f"it does not name the file fleet.sh reads, {need.path}")
    for key in need.keys:
        if not re.search(rf"(?<![\w-]){re.escape(key)}(?![\w-])", text):
            out.append(f"it does not name the key {key}, which fleet.sh's presenter_login reads")
    got = parsed_values(body, need)
    if got:
        out.append(f"fleet.sh's _terminal_env_value reads a value for {', '.join(got)} from it")
    hits = assigned(text, need.keys)
    if hits:
        out.append(f"it assigns a login value: {', '.join(hits)}")
    old = old_login_lines(text, need.old_login)
    if old:
        out.append(f"it carries the old login (line {', '.join(map(str, old))})")
    return out


def read_request(path: pathlib.Path = REQUEST) -> tuple[str, str, list[str], str]:
    """(title, body, labels, repo) of the committed request: a `# title` line, `Repo:` and `Label:` lines, then
    the issue body after a `---` line."""
    text = path.read_text(encoding="utf-8")
    head, sep, body = text.partition("\n---\n")
    if not sep:
        raise AnchorMissing(f"{path}: no `---` line between the header and the issue body")
    title = next((ln[2:].strip() for ln in head.splitlines() if ln.startswith("# ")), "")
    fields = dict(re.findall(r"^(Repo|Label): `?([^`\n]+?)`?\s*$", head, re.M))
    return title, body.strip("\n"), [fields["Label"]] if "Label" in fields else [], fields.get("Repo", "")


def check_issues(issues: list[dict], need: Need, say=print) -> int:
    """0 naming the first issue that meets the criterion, else 1 with each issue's problems. Never prints a body."""
    if not issues:
        say(f"FAIL  no {LABEL} issue on {VAULT} names {need.keys[0]}: the request was never filed")
        return 1
    for i in issues:
        labels = [lb.get("name", "") if isinstance(lb, dict) else str(lb) for lb in i.get("labels") or []]
        got = problems(i.get("title") or "", i.get("body") or "", labels, need)
        ref = f"{VAULT}#{i.get('number', '?')}"
        if not got:
            say(f"PASS  {ref} asks for a new presenter terminal login to be generated and stored at {need.path} "
                f"under {' and '.join(need.keys)}, and carries no login value")
            return 0
        say(f"  {ref}: " + "; ".join(got))
    say(f"FAIL  no {LABEL} issue on {VAULT} meets #910's criterion")
    return 1


def gh_issues(timeout: int = 90) -> list[dict]:
    gh = shutil.which("gh")
    if not gh:
        raise RuntimeError("no gh on PATH")
    p = subprocess.run([gh, "issue", "list", "-R", VAULT, "--label", LABEL, "--state", "all",
                        "--search", "WIB_TERMINAL_USER in:body", "--json", "number,title,body,labels,url"],
                       capture_output=True, text=True, timeout=timeout)
    if p.returncode != 0:
        said = " | ".join(ln.strip() for ln in (p.stderr or p.stdout).strip().splitlines()[-3:])
        raise RuntimeError(f"gh issue list -R {VAULT} exit {p.returncode}: {said or 'no output'}")
    return json.loads(p.stdout or "[]")


def main(argv: list[str] | None = None, say=print) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    src = ap.add_mutually_exclusive_group()
    src.add_argument("--issues", type=pathlib.Path, help="gh issue list --json number,title,body,labels output")
    src.add_argument("--gh", action="store_true", help=f"read {VAULT}'s {LABEL} issues with gh")
    src.add_argument("--request", type=pathlib.Path, default=REQUEST, help="a request file in the committed shape")
    ap.add_argument("--fleet", type=pathlib.Path, default=FLEET)
    a = ap.parse_args(argv)
    need = fleet_reads(a.fleet)
    if a.gh or a.issues:
        try:
            issues = gh_issues() if a.gh else json.loads(a.issues.read_text(encoding="utf-8"))
        except (RuntimeError, OSError, ValueError, subprocess.TimeoutExpired) as e:
            say(f"FAIL  cannot read {VAULT}'s issues: {e}")
            return 1
        if not isinstance(issues, list):
            say("FAIL  the issues file is not a JSON list, as `gh issue list --json` writes")
            return 1
        return check_issues(issues, need, say)
    title, body, labels, repo = read_request(a.request)
    got = problems(title, body, labels, need)
    if repo != VAULT:
        got.insert(0, f"it is not addressed to {VAULT} (Repo: {repo or 'none'})")
    for g in got:
        say(f"FAIL  {a.request.name}: {g}")
    if not got:
        say(f"PASS  {a.request.name} asks {VAULT} for a new presenter terminal login, generated and stored at "
            f"{need.path} under {' and '.join(need.keys)}, and carries no login value")
    return 1 if got else 0


if __name__ == "__main__":
    sys.exit(main())
