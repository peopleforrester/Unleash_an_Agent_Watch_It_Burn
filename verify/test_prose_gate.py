# ABOUTME: Tests verify/prose_gate.py (#796) on a throwaway repo with a stand-in scanner: an added hype word in a
# ABOUTME: prose file fails with its line, the name in backticks passes, a moved hit passes, bad input gives status 2.
"""verify/prose_gate.py reads a branch's prose as hecaton's ai-isms gate does, so a run finds the word that would
fail it before the dispatcher does. The real scanner is on hecaton hosts only, so this drives the script with
`verify/fixtures/prose-gate/fake_aiisms.py`, which has the same interface, and checks the script's own work: which
files it reads, the base it reads them at, the "grew over the whole change" rule, exemptions and its exit codes.
"""
from __future__ import annotations

import os
import pathlib
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
SCRIPT = HERE / "prose_gate.py"
FAKE = HERE / "fixtures" / "prose-gate" / "fake_aiisms.py"
# Sixty plain words, so the stand-in reads the file "major" as decisions.md reads on the real scanner.
FILLER = " ".join(["the platform runs the agent on the cluster"] * 8) + "\n"

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"\n        {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


tmp = pathlib.Path(tempfile.mkdtemp())
repo = tmp / "r"
env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
env.update(HOME=str(tmp), GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL="/dev/null", GIT_AUTHOR_NAME="t",
           GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")


def git(*args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], env=env, check=True, capture_output=True)


def put(path: str, text: str) -> None:
    f = repo / path
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(text, encoding="utf-8")


def run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, "-I", str(SCRIPT), *args], cwd=repo, env=env, capture_output=True,
                          text=True)


def reset() -> None:
    git("reset", "-q", "--hard", "staging")
    git("clean", "-qfdx")


subprocess.run(["git", "-c", "init.defaultBranch=staging", "init", "-q", str(repo)], env=env, check=True)
put("decisions.md", "# Decisions\n\n" + FILLER + "The talk is called Unleash an Agent.\n")
put("notes/short.md", "A short note.\n")
put("tool.py", "# unleash the agent\n")
put("docs/exempt.md", "---\nai-isms-exempt: true\n---\n" + FILLER)
git("add", "-A")
git("commit", "-q", "-m", "base")
git("checkout", "-q", "-b", "agent/796-1")

print("== a change with no public prose passes ==")
put("tool.py", "# unleash the agent, then let's go\n")
r = run(str(FAKE), "staging")
check("exit 0 when only a .py file changed", r.returncode == 0, r.stdout + r.stderr)
check("it says no public-prose file changed", "no public-prose file changed" in r.stdout, r.stdout)
reset()

print("== an added hype word in a file that reads major fails, naming the file, label and line ==")
put("decisions.md", (repo / "decisions.md").read_text() + "\nThe Unleashed repo grew a check.\n")
r = run(str(FAKE), "staging")
check("exit 1", r.returncode == 1, r.stdout + r.stderr)
check("it names decisions.md and the hype-verb label",
      "FAIL  decisions.md" in r.stdout and "vocabulary: hype verbs (+1)" in r.stdout, r.stdout)
check("it names the added line by number and text, not the base's own hit",
      "line 6 (vocabulary: hype verbs): The Unleashed repo grew a check." in r.stdout
      and "line 4" not in r.stdout, r.stdout)
reset()

print("== the same name in backticks, or with its underscores, passes ==")
put("decisions.md", (repo / "decisions.md").read_text()
    + "\nThe `Unleashed` repo, Unleash_an_Agent_Watch_It_Burn, grew a check.\n")
r = run(str(FAKE), "staging")
check("exit 0", r.returncode == 0, r.stdout + r.stderr)
check("it says the gate passes, reading one file", "pass, 1 public-prose file(s) read" in r.stdout, r.stdout)
reset()

print("== a committed change is read as well as an uncommitted one ==")
put("decisions.md", (repo / "decisions.md").read_text() + "\nThe check lets a run see it first.\n")
git("commit", "-qam", "record")
r = run(str(FAKE), "staging")
check("exit 1 on the committed connective", r.returncode == 1 and "connective: let's (+1)" in r.stdout,
      r.stdout + r.stderr)
reset()

print("== a new untracked prose file is read ==")
put("docs/new.md", "Unleash it — now.\n")
r = run(str(FAKE), "staging")
check("exit 1 on the em-dash in a short new file", r.returncode == 1 and "FAIL  docs/new.md: em-dash (+1)" in r.stdout,
      r.stdout + r.stderr)
check("the short file's hype word alone is not a failure, since it does not read major",
      "reads major" not in r.stdout, r.stdout)
reset()

print("== a hit moved from one file to another is not the change's to fix ==")
text = (repo / "decisions.md").read_text().replace("Unleash an Agent", "the workshop")
put("decisions.md", text)
put("notes/short.md", FILLER + "Unleash an Agent is the title.\n")
r = run(str(FAKE), "staging")
check("exit 0 when the label's total over the change did not grow", r.returncode == 0, r.stdout + r.stderr)
reset()

print("== exemptions ==")
put("docs/exempt.md", (repo / "docs" / "exempt.md").read_text() + "Unleash it.\n")
r = run(str(FAKE), "staging")
check("a file exempt at the base and still exempt is not read", r.returncode == 0, r.stdout + r.stderr)
put("notes/short.md", "---\nai-isms-exempt: true\n---\nUnleash it.\n")
r = run(str(FAKE), "staging")
check("a file newly declaring itself exempt is held: exit 1 and HELD",
      r.returncode == 1 and "HELD  notes/short.md newly declares itself exempt" in r.stdout, r.stdout + r.stderr)
reset()

print("== the base is the merge base, so staging moving on does not count against the branch ==")
git("checkout", "-q", "staging")
put("decisions.md", (repo / "decisions.md").read_text() + "\nStaging says Unleashed here.\n")
git("commit", "-qam", "staging moves")
git("checkout", "-q", "agent/796-1")
r = run(str(FAKE), "staging")
check("exit 0 on a branch that changed nothing, though staging added a hit", r.returncode == 0, r.stdout + r.stderr)

print("== it cannot run: status 2 with the reason ==")
r = run(str(tmp / "no-such-scanner.py"), "staging")
check("status 2 and the hecaton path when the scanner is missing",
      r.returncode == 2 and "no scanner at" in r.stderr and "hecaton/run/aiisms.py" in r.stderr, r.stderr)
(tmp / "not_a_scanner.py").write_text("X = 1\n")
r = run(str(tmp / "not_a_scanner.py"), "staging")
check("status 2 when the module is not the gate's scanner",
      r.returncode == 2 and "is not the gate's scanner" in r.stderr, r.stderr)
r = run(str(FAKE), "no-such-ref")
check("status 2 on an unknown base ref", r.returncode == 2 and "no merge base" in r.stderr, r.stderr)
r = run(str(FAKE))
check("status 2 and the usage with one argument", r.returncode == 2 and "usage:" in r.stderr, r.stderr)

subprocess.run(["rm", "-rf", str(tmp)], check=False)
print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All prose gate checks passed.")
