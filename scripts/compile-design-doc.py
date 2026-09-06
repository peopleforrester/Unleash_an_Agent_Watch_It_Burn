# ABOUTME: Build the compiled "design decisions and tech stack" markdown from a fixed list of repo docs
# ABOUTME: and, with --publish, update the Google Doc in place through gdoc-update.py (#257).
"""Compile the design Doc deterministically.

The Doc id and the section list live here, so the Doc is regenerated the same way every time:

    python3 scripts/compile-design-doc.py --out /path/witb-design-and-stack.md
    python3 scripts/compile-design-doc.py --publish     # also updates the Google Doc in place

--publish needs a gog token export in the working directory (gdoc-update.py's contract):
    gog auth tokens export michaelrishiforrester@gmail.com --out tok.json   # delete it afterwards
"""
from __future__ import annotations

import argparse
import datetime as dt
import pathlib
import re
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
DOC_ID = "18xDmjUyA5OYOSMI1-EkHEeG7RLUQTN6Ev_ZTrD7_P04"
GDOC_UPDATE = pathlib.Path.home() / "repos/workflow/llm-coding-workflow/scripts/gdoc-update.py"
TITLE = "Unleash an Agent, Watch It Burn: design decisions and tech stack"
SECTIONS: list[tuple[str, str]] = [
    ("What the workshop is", "README.md"),
    ("Tech stack walkthrough", "docs/STACK-WALKTHROUGH.md"),
    ("Design decisions and reconciliation", "docs/DESIGN-DECISIONS.md"),
    ("Build specification", "docs/BUILD-SPEC.md"),
    ("GitOps reconciliation model", "docs/GITOPS-RECONCILIATION.md"),
    ("Attendee access design", "docs/attendee-access-design.md"),
    ("Sizing, nodes and cost", "infra/SIZING.md"),
    ("Observability priorities", "docs/observability-priorities.md"),
    ("External apps", "docs/external-apps.md"),
    ("Gotchas: fleet operations and live delivery", "docs/GOTCHAS-FLEET-AND-DELIVERY.md"),
    ("Governance map (attack to control)", "facilitation/governance-map.md"),
    ("Self-assessment", "facilitation/self-assessment.md"),
    ("Tech status", "docs/TECH-STATUS.md"),
    ("Roadmap", "docs/ROADMAP.md"),
    ("Decision log and verification corrections", "docs/DECISION-LOG.md"),
    ("Decisions log (lifecycle)", "decisions.md"),
]
GLANCE = (REPO / "docs/DESIGN-GLANCE.md")


def demote(md: str) -> str:
    """Push every heading one level down so each source file nests under its section heading."""
    return re.sub(r"^(#{1,5}) ", lambda m: "#" + m.group(1) + " ", md, flags=re.M)


def compile_doc(repo: pathlib.Path = REPO, sha: str | None = None, today: str | None = None) -> str:
    sha = sha or subprocess.check_output(["git", "-C", str(repo), "rev-parse", "--short", "HEAD"]).decode().strip()
    today = today or dt.date.today().isoformat()
    parts = [f"# {TITLE}\n",
             f"_Compiled {today} from the repository at staging {sha} "
             "(github.com/peopleforrester/Unleash_an_Agent_Watch_It_Burn). Every section below is a repository "
             "document reproduced as written, headed by its path. Nothing is paraphrased; the repo stays the "
             "source of truth._\n",
             "## Contents\n"]
    parts += [f"- {title} (`{path}`)" for title, path in SECTIONS]
    parts += ["", (repo / GLANCE.relative_to(REPO)).read_text().strip(), "", ""]
    for title, path in SECTIONS:
        body = (repo / path).read_text()
        parts += [f"# {title}\n", f"_Source: `{path}`_\n", demote(body).rstrip(), "", ""]
    return "\n".join(parts)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--out", type=pathlib.Path, default=pathlib.Path("witb-design-and-stack.md"))
    p.add_argument("--publish", action="store_true", help="update the Google Doc in place after compiling")
    a = p.parse_args(argv)
    md = compile_doc()
    a.out.write_text(md)
    print(f"compiled {len(md)} bytes to {a.out} ({len(SECTIONS)} sections)", file=sys.stderr)
    if a.publish:
        if not GDOC_UPDATE.exists():
            print(f"missing {GDOC_UPDATE}", file=sys.stderr)
            return 1
        subprocess.run([sys.executable, str(GDOC_UPDATE), f"{DOC_ID}={a.out}"], check=True)
        print(f"published to https://docs.google.com/document/d/{DOC_ID}/edit", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
