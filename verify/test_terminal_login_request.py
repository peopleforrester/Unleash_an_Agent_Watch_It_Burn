# ABOUTME: Fails unless the mrf-secrets request for the presenter terminal login asks for a new one to be generated and
# ABOUTME: stored, names the file and keys fleet.sh reads, and carries no login value (#910's criterion, #932).
#
# Why (#932). #910's criterion is an agent-task issue on mrf-secrets that asks for the new private terminal login to
# be generated and stored, names the key this repo reads, and contains no login value. No run can read or file on
# mrf-secrets, so the request's text is kept at docs/requests/mrf-secrets-terminal-login.md and
# verify/terminal_login_request.py checks it, reading the file, the keys and the parser from fleet.sh itself. This
# test runs that check on the committed request, then proves each part of it fails: a request that drops the file or
# a key, stops asking for a new login to be generated or stored, or carries a value in any assignment form or the old
# login; a fleet.sh that renames a key or the file; and the live mode (`--issues`, gh's JSON for the filed issue) on
# test-owned issue lists. Every input is test-owned except the committed request, fleet.sh and the guard's digests.
from __future__ import annotations

import dataclasses
import hashlib
import io
import json
import os
import pathlib
import subprocess
import sys
import tempfile

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "verify"))
import terminal_login_request as tlr  # noqa: E402

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail and not ok else ""))
    if not ok:
        failures.append(name)


def fails_with(got: list[str], words: str) -> bool:
    return any(words in g for g in got)


print("== fleet.sh names the file, the keys and the parser ==")
need = tlr.fleet_reads()
check("WIB_TERMINAL_ENV's default is projects/watch-it-burn-terminal.env under ~/secrets",
      need.path == "projects/watch-it-burn-terminal.env", need.path)
check("presenter_login reads WIB_TERMINAL_USER and WIB_TERMINAL_PASSWORD",
      need.keys == ("WIB_TERMINAL_USER", "WIB_TERMINAL_PASSWORD"), str(need.keys))
check("the old login's digests come from the guard test", len(need.old_login) == 2, str(len(need.old_login)))

print("== the committed request meets #910's criterion ==")
title, body, labels, repo = tlr.read_request()
check("it is addressed to peopleforrester/mrf-secrets", repo == tlr.VAULT, repo)
got = tlr.problems(title, body, labels, need)
check("it asks for a new login, generated and stored, names the file and both keys, and carries no value",
      not got, "; ".join(got))
out: list[str] = []
check("the module's own check of the request exits 0", tlr.main([], say=out.append) == 0, " | ".join(out))

print("== fleet.sh's parser is the one that reads the request (self-test) ==")
env_forms = {
    "KEY=v": "WIB_TERMINAL_PASSWORD=placeholderValue932\n",
    "export KEY=\"v\"": 'export WIB_TERMINAL_PASSWORD="placeholderValue932"\n',
    "  KEY='v'": "  WIB_TERMINAL_PASSWORD='placeholderValue932'\n",
}
for form, text in env_forms.items():
    check(f"_terminal_env_value reads a value from {form}", tlr.parsed_values(text, need) == ["WIB_TERMINAL_PASSWORD"])
check("and reads nothing from a key named in prose",
      tlr.parsed_values("the key `WIB_TERMINAL_PASSWORD` in the file\n", need) == [])

print("== each part of the criterion fails when the request stops holding it ==")


def mutated(old: str, new: str) -> list[str]:
    if old not in body:
        print(f"  ANCHOR MISSING  {old!r} is not in {tlr.REQUEST}; the request was reworded, update this case")
        failures.append(f"anchor {old!r}")
        return ["anchor missing"]
    return tlr.problems(title, body.replace(old, new), labels, need)


check("a request without the file fails",
      fails_with(mutated("projects/watch-it-burn-terminal.env", "projects/other.env"),
                 "does not name the file fleet.sh reads"))
check("a request without WIB_TERMINAL_PASSWORD fails",
      fails_with(mutated("`WIB_TERMINAL_PASSWORD`", "`WIB_TERMINAL_PW`"), "the key WIB_TERMINAL_PASSWORD"))
check("a request that does not ask to generate fails",
      fails_with(tlr.problems(title.replace("Generate", "Keep"), body.replace("Generate", "Pick"), labels, need),
                 "generated"))
check("a request that does not ask to store fails",
      fails_with(tlr.problems(title.replace("store", "share"),
                              body.replace("Store", "Put").replace("stored", "kept"), labels, need), "stored"))
check("a request without the agent-task label fails",
      fails_with(tlr.problems(title, body, [], need), "not labelled agent-task"))
leaks = {
    "an env-file line": "WIB_TERMINAL_PASSWORD=placeholderValue932",
    "an export line": 'export WIB_TERMINAL_USER="placeholder-presenter"',
    "a colon pair": "WIB_TERMINAL_USER: placeholder-presenter",
    "a JSON pair": '{"WIB_TERMINAL_PASSWORD": "placeholderValue932"}',
    "a code span": "`WIB_TERMINAL_PASSWORD=placeholderValue932`",
    "the Secret's key": "TTYD_CREDENTIAL=cGxhY2Vob2xkZXI6cGxhY2Vob2xkZXI=",
}
for form, line in leaks.items():
    check(f"a request carrying a value as {form} fails",
          fails_with(tlr.problems(title, f"{body}\n\n{line}\n", labels, need), "assigns a login value"))
check("and an env-file line is also read by fleet.sh's parser",
      fails_with(tlr.problems(title, f"{body}\nWIB_TERMINAL_USER=placeholder-presenter\n", labels, need),
                 "_terminal_env_value reads a value for WIB_TERMINAL_USER"))
planted = "placeholderOldLogin932"
need_planted = dataclasses.replace(need, old_login=frozenset({hashlib.sha256(planted.lower().encode()).hexdigest()}))
check("a request carrying the old login fails, found by digest",
      fails_with(tlr.problems(title, f"{body}\nThe old one was {planted.upper()}.\n", labels, need_planted),
                 "carries the old login"))

print("== a fleet.sh that renames the file or a key fails the request until it follows ==")
fleet_src = tlr.FLEET.read_text(encoding="utf-8")
with tempfile.TemporaryDirectory() as tmp:
    t = pathlib.Path(tmp)
    for what, old, new, words in [
        ("a key", "_terminal_env_value WIB_TERMINAL_PASSWORD ", "_terminal_env_value WIB_PRESENTER_PASSWORD ",
         "the key WIB_PRESENTER_PASSWORD"),
        ("the file", "/secrets/projects/watch-it-burn-terminal.env}", "/secrets/projects/wib-presenter.env}",
         "projects/wib-presenter.env"),
    ]:
        if old not in fleet_src:
            print(f"  ANCHOR MISSING  {old!r} is not in {tlr.FLEET}; fleet.sh changed shape, update this case")
            failures.append(f"anchor {old!r}")
            continue
        f = t / f"fleet-{what.replace(' ', '-')}.sh"
        f.write_text(fleet_src.replace(old, new), encoding="utf-8")
        check(f"renaming {what} in fleet.sh fails the committed request",
              fails_with(tlr.problems(title, body, labels, tlr.fleet_reads(f)), words))
    bare = t / "fleet-bare.sh"
    bare.write_text(fleet_src.replace("_terminal_env_value()", "_env_value()"), encoding="utf-8")
    try:
        tlr.fleet_reads(bare)
        check("a fleet.sh without _terminal_env_value is named as a missing anchor", False)
    except tlr.AnchorMissing as e:
        check("a fleet.sh without _terminal_env_value is named as a missing anchor", "_terminal_env_value" in str(e))

print("== the live mode reads gh's JSON for the filed issue ==")
good = {"number": 7, "title": title, "body": body, "labels": [{"name": "agent-task"}], "url": "u"}
leaky = dict(good, number=8, body=f"{body}\nWIB_TERMINAL_PASSWORD=placeholderValue932\n")
unlabelled = dict(good, number=9, labels=[])
with tempfile.TemporaryDirectory() as tmp:
    t = pathlib.Path(tmp)

    def live(issues) -> tuple[int, str]:
        f = t / "issues.json"
        f.write_text(json.dumps(issues) if not isinstance(issues, str) else issues, encoding="utf-8")
        said: list[str] = []
        return tlr.main(["--issues", str(f)], say=said.append), "\n".join(said)

    rc, said = live([leaky, unlabelled, good])
    check("one issue that meets the criterion passes, named", rc == 0 and "mrf-secrets#7" in said, said)
    rc, said = live([leaky, unlabelled])
    check("issues that each fail one part fail, each named with its problem",
          rc == 1 and "#8: " in said and "assigns a login value" in said and "#9: " in said
          and "not labelled agent-task" in said, said)
    check("and no issue's value is printed", "placeholderValue932" not in said)
    rc, said = live([])
    check("no filed issue fails as never filed", rc == 1 and "never filed" in said, said)
    rc, said = live("not json")
    check("an unreadable issues file fails, named", rc == 1 and "cannot read" in said, said)

    # A gh that refuses the vault, as the hecaton wrapper does, fails the --gh mode by name.
    stub = t / "bin"
    stub.mkdir()
    (stub / "gh").write_text("#!/bin/sh\necho 'REFUSED peopleforrester/mrf-secrets is a data vault' >&2\nexit 1\n")
    (stub / "gh").chmod(0o755)
    p = subprocess.run([sys.executable, str(REPO / "verify" / "terminal_login_request.py"), "--gh"],
                       capture_output=True, text=True, timeout=120,
                       env={**os.environ, "PATH": f"{stub}{os.pathsep}{os.environ.get('PATH', '')}"})
    check("a gh that refuses mrf-secrets fails --gh, quoting gh", p.returncode == 1 and "REFUSED" in p.stdout,
          f"exit {p.returncode}: {p.stdout.strip()[-200:]}")

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    print(f"The mrf-secrets request ({tlr.REQUEST.relative_to(REPO)}) must ask for a new presenter terminal login "
          "to be generated and stored at the file and keys fleet.sh reads, and carry no login value (#910, #932).")
    sys.exit(1)
print("The mrf-secrets request asks for the login fleet.sh reads and carries no value.")
