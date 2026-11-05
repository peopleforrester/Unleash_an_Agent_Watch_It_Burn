# ABOUTME: Reads #759's comments with gh's token (#863) and checks one records where the Datadog read pair lives
# ABOUTME: (Secrets Manager watch-it-burn/datadog in accen-dev) and the command a run reads traces with, as the code has them (#891).
# SUITE: e2e (needs the network and gh with a token: `gh issue view` is asked for the issue's comments)
# E2E TIER: tools (no cluster, no AWS: run-e2e-tools.sh runs it with the pinned tools, #572)
#
# Why. #759's criterion "This issue records where the credential lives and how a run uses it" is met by a comment
# on the issue (Michael's, issuecomment-6605670550, and the later one of run 17391's live read), and no test read it:
# test_dd_traces.py checks that the reader asks Secrets Manager for watch-it-burn/datadog, which is the code path,
# not the record (#891). This asks GitHub for #759's comments through verify/gh_comments.py, with gh's token and
# not the host's shared anonymous quota (#863), and fails unless one comment by hecaton or Michael names:
#   where: Secrets Manager, the secret id fleet_monitors.read_keys asks for, the fields it reads, and the account
#          AGENTS.md names for a run's session;
#   how:   sourcing $HECATON_CLUSTER_ENV, then a `python3 verify/dd_traces.py` command that dd_traces.py's own
#          parser accepts and that asks the keys reader for AGENTS.md's profile and region.
# So the record goes stale, and this fails, when the secret, its fields, the run's profile or the reader's flags
# change and the issue is not told.
from __future__ import annotations

import io
import pathlib
import re
import shlex
import sys
from contextlib import redirect_stderr

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "verify"))
import gh_comments  # noqa: E402
import dd_traces  # noqa: E402

fm = dd_traces.fm
AGENTS = REPO / "AGENTS.md"
READER = REPO / "verify" / "dd_traces.py"
ISSUE = "peopleforrester/Unleash_an_Agent_Watch_It_Burn#759"
OWNER_REPO, _, NUMBER = ISSUE.partition("#")
# Who may record it on the issue: the dispatcher that posts each run's report, and the repo's owner.
# gh issue view reads them through GraphQL, which names the hecatongithub app's bot without REST's "[bot]".
AUTHORS = {"hecatongithub", "peopleforrester"}
SOURCE_STEP = '. "$HECATON_CLUSTER_ENV"'

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail and not ok else ""))
    if not ok:
        failures.append(name)


def flat(text: str) -> str:
    return re.sub(r"\s+", " ", text)


# ---- What the tree says: the secret, its fields, the run's profile and region, the reader's command ----
print("== the tree names the secret, its fields and the run's AWS session ==")


class _Run:
    """Stands in for subprocess.run inside fleet_monitors.read_keys, so the secret id is read from its argv."""

    def __init__(self) -> None:
        self.argv: list[str] = []

    def __call__(self, argv, **_kw):
        self.argv = list(argv)
        return type("P", (), {"returncode": 0, "stderr": "",
                              "stdout": '{"api-key": "a", "app-key": "b", "site": "datadoghq.com"}'})()


run = _Run()
fm.read_keys("p", "r", run=run)
secret_id = run.argv[run.argv.index("--secret-id") + 1] if "--secret-id" in run.argv else ""
check("fleet_monitors.read_keys reads its pair with `aws secretsmanager get-secret-value --secret-id <id>`",
      run.argv[:3] == ["aws", "secretsmanager", "get-secret-value"] and bool(secret_id), " ".join(run.argv))
keys_src = flat(pathlib.Path(fm.__file__).read_text(encoding="utf-8"))
fields = [f for f in ("api-key", "app-key", "site") if f'd.get("{f}")' in keys_src]
check("read_keys reads the secret's api-key, app-key and site fields", fields == ["api-key", "app-key", "site"],
      f"found {fields}")

agents = flat(AGENTS.read_text(encoding="utf-8"))
m = re.search(r"a 12-hour session for the `([\w-]+)` AWS profile \(account (\d+), ([a-z]{2}-[a-z]+-\d)\)", agents)
check("AGENTS.md names the AWS profile, account and region of a dispatched run's session", bool(m))
profile, account, region = m.groups() if m else ("", "", "")

doc = dd_traces.__doc__ or ""
doc_cmd = next((ln.strip() for ln in doc.splitlines() if ln.strip().startswith("python3 verify/dd_traces.py")), "")
check("dd_traces.py's docstring gives the command a run reads traces with", bool(doc_cmd))
check(f"and has the run source its session first ({SOURCE_STEP})", SOURCE_STEP in doc)


class _Asked(Exception):
    """Raised by the keys stub, so main stops once it has parsed its flags and asked for the pair."""


def asks_for(cmd: str) -> tuple[str, str] | str:
    """The (profile, region) the command makes dd_traces.main ask the keys reader for, or why it does not."""
    try:
        argv = shlex.split(cmd)
    except ValueError as e:
        return f"not a shell command: {e}"
    if argv[:2] != ["python3", "verify/dd_traces.py"]:
        return f"does not run python3 verify/dd_traces.py: {argv[:2]}"
    asked: list[tuple[str, str]] = []

    def keys(p: str, r: str):
        asked.append((p, r))
        raise _Asked

    err = io.StringIO()
    try:
        with redirect_stderr(err):
            dd_traces.main(argv[2:], env={}, keys=keys, say=lambda *_a, **_k: None)
    except _Asked:
        return asked[0]
    except SystemExit as e:
        return f"dd_traces.py's parser refuses it (exit {e.code}): {flat(err.getvalue()).strip()[:200]}"
    return "dd_traces.main returned without asking for the pair"


got_doc = asks_for(doc_cmd) if doc_cmd else "no command"
check(f"the docstring's command parses and asks for the pair as {profile} in {region}",
      got_doc == (profile, region), str(got_doc))
check("the reader the record names is in the tree", READER.is_file())

# ---- What the issue says ----
print(f"== a comment on {ISSUE} records where the credential lives and how a run uses it ==")
read = gh_comments.read(OWNER_REPO, NUMBER)
gh_comments.check_read(read, ISSUE, check)
got = read.comments
ours = [c for c in got if c["login"] in AUTHORS]
if got:
    check(f"at least one comment is by {' or '.join(sorted(AUTHORS))}", bool(ours),
          ", ".join(sorted({c["login"] for c in got})))


def where_left_out(body: str) -> list[str]:
    """What the comment leaves out of where the pair lives; empty when it names all of it."""
    text = flat(body)
    parts = {
        "Secrets Manager": "secrets manager" in text.lower(),
        f"the secret id {secret_id}": bool(secret_id) and re.search(rf"`?{re.escape(secret_id)}`?(?![\w/-])", text)
        is not None,
        f"the {profile} account": bool(profile) and profile in text,
        f"its fields ({', '.join(fields)})": bool(fields) and all(f in text for f in fields),
    }
    return [name for name, ok in parts.items() if not ok]


def commands(body: str) -> list[str]:
    """Every `python3 verify/dd_traces.py ...` line in the comment, from a code block or an inline code span."""
    found = []
    for ln in body.splitlines():
        for span in re.findall(r"`([^`]*python3 verify/dd_traces\.py[^`]*)`", ln) or [ln]:
            s = span.strip()
            if s.startswith("python3 verify/dd_traces.py"):
                found.append(s)
    return found


def how_left_out(body: str) -> list[str]:
    """What the comment leaves out of how a run uses the pair; empty when it names all of it."""
    left = []
    src = body.find(SOURCE_STEP)
    if src < 0:
        left.append(f"the source step {SOURCE_STEP}")
    cmds = commands(body)
    if not cmds:
        left.append("a `python3 verify/dd_traces.py` command")
        return left
    asked = {c: asks_for(c) for c in cmds}
    good = [c for c, a in asked.items() if a == (profile, region)]
    if not good:
        left.append(f"a dd_traces.py command the parser accepts and that reads as {profile} in {region} "
                    f"({'; '.join(f'{c!r}: {a}' for c, a in asked.items())})")
    elif src >= 0 and not any(body.find(c) > src for c in good):
        left.append(f"the command after {SOURCE_STEP}")
    return left


if ours:
    left = [(c["url"], where_left_out(c["body"]) + how_left_out(c["body"])) for c in ours]
    recorded = [url for url, miss in left if not miss]
    closest = min(left, key=lambda x: len(x[1]))
    check(f"one comment records the pair in Secrets Manager {secret_id} ({', '.join(fields)}) in {profile}, and a run's "
          f"`{SOURCE_STEP}` then `python3 verify/dd_traces.py --profile {profile} ...`", bool(recorded),
          f"closest is {closest[0]}, which leaves out: {'; '.join(closest[1])}")
    if recorded:
        print(f"  the record is at {recorded[0]}")
        if doc_cmd:
            same = [url for url in recorded
                    if doc_cmd in next(c["body"] for c in ours if c["url"] == url)]
            check("a recording comment gives the docstring's own command, word for word", bool(same),
                  f"the docstring's is {doc_cmd!r}")

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All #759 credential record checks passed.")
