# ABOUTME: Offline gate that the IAM policy pipeline runs on every PR (#207): .github/workflows/iam-policy.yml
# ABOUTME: triggers on each root the pipeline reads, runs check 3 with the pinned tools, and holds no AWS credential.
#
# Why. The pipeline's checks only stop a change if something runs them on the PR. This holds the workflow that does:
# its paths cover every root in pipeline.ROOTS and the pipeline's own files, so a PR that adds an unconditioned
# Allow cannot skip the job by where it puts it; it runs the offline, coverage and structural tests, with conftest and
# terraform from verify/e2e-tools.lock; and it stays credential-free on a GitHub-hosted runner (question 592), so a
# fork PR is safe to check.
import pathlib, re, sys

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "infra/org"))
import pipeline as p  # noqa: E402

import yaml  # noqa: E402

WORKFLOW = REPO / ".github/workflows/iam-policy.yml"
failures = []


def check(n, c, detail=""):
    print(f"  {'PASS' if c else 'FAIL'}  {n}" + (f"\n        {detail}" if (detail and not c) else ""))
    if not c:
        failures.append(n)


def glob_re(pattern):
    # GitHub's path filters: ** crosses directories, * does not.
    out = ""
    for part in re.split(r"(\*\*|\*)", pattern):
        out += ".*" if part == "**" else "[^/]*" if part == "*" else re.escape(part)
    return re.compile(out + r"\Z")


def covered(path, patterns):
    return any(glob_re(pat).match(path) for pat in patterns)


if not WORKFLOW.is_file():
    print(f"FAIL: {WORKFLOW.relative_to(REPO)} is missing; nothing runs the IAM policy pipeline on a PR", file=sys.stderr)
    sys.exit(1)
text = WORKFLOW.read_text(encoding="utf-8")
wf = yaml.safe_load(text)
on = wf.get("on", wf.get(True))  # YAML 1.1 reads a bare `on:` key as True

print("when it runs")
check("it runs on pull requests", isinstance(on, dict) and "pull_request" in on, on)
check("it runs on pushes to staging and main", sorted(((on or {}).get("push") or {}).get("branches", [])) == ["main", "staging"], on)
pr_paths = ((on or {}).get("pull_request") or {}).get("paths", [])
push_paths = ((on or {}).get("push") or {}).get("paths", [])
check("pull_request and push watch the same paths", pr_paths == push_paths, (pr_paths, push_paths))
for name, root in sorted(p.ROOTS.items()):
    rel = root.relative_to(REPO).as_posix()
    check(f"a change to the {name} root ({rel}) triggers it", covered(f"{rel}/main.tf", pr_paths), pr_paths)
check("a change to any Terraform root triggers it, so a root new to pipeline.ROOTS is watched too",
      "infra/terraform/**" in pr_paths, pr_paths)
watched = ["infra/org/pipeline.py", "infra/org/policy/iam.rego", "infra/org/exceptions.md",
           "infra/org/permissions-boundary.json.tftpl", "infra/org/effect-tests.yaml",
           "verify/iam_plan_render.py", "verify/e2e-tools.lock", "verify/fetch-e2e-tools.sh",
           ".github/workflows/iam-policy.yml"]
watched += [t.relative_to(REPO).as_posix() for t in sorted((REPO / "verify").glob("test_iam_policy_*.py"))]
for path in watched:
    check(f"a change to {path} triggers it", covered(path, pr_paths), pr_paths)

print("what it holds")
check("its token can only read the repo", wf.get("permissions") == {"contents": "read"}, wf.get("permissions"))
jobs = wf.get("jobs") or {}
check("it has one job", len(jobs) == 1, list(jobs))
job = next(iter(jobs.values()), {}) or {}
check("it runs on a GitHub-hosted runner, never a self-hosted one (question 592)", job.get("runs-on") == "ubuntu-latest",
      job.get("runs-on"))
check("no job widens the token's permissions", all("permissions" not in (j or {}) for j in jobs.values()))
for bad, why in (("secrets.", "a secret"), ("id-token", "an OIDC token"), ("configure-aws-credentials", "AWS credentials"),
                 ("AWS_PROFILE", "an AWS profile"), ("self-hosted", "a self-hosted runner")):
    check(f"it asks for no {why}", bad not in text)
steps = job.get("steps") or []
uses = [s["uses"] for s in steps if "uses" in s]
check("it uses actions", len(uses) > 0)
for u in uses:
    check(f"{u.split('@')[0]} is pinned to a commit SHA", re.fullmatch(r"[\w.-]+/[\w.-]+@[0-9a-f]{40}", u) is not None, u)

print("what it runs")
runs = "\n".join(s.get("run", "") for s in steps)
check("it fetches the pinned tools with verify/fetch-e2e-tools.sh", "bash verify/fetch-e2e-tools.sh" in runs, runs)
check("it puts the fetched tools on PATH", '"$GITHUB_WORKSPACE/verify/.tools/bin" >> "$GITHUB_PATH"' in runs, runs)
for t in ("test_iam_policy_pipeline.py", "test_iam_policy_coverage.py", "test_iam_policy_structural.py"):
    check(f"it runs verify/{t}", f"python verify/{t}" in runs and (REPO / "verify" / t).is_file(), runs)
check("it does not run test_iam_policy_aws.py, which needs an AWS profile", "test_iam_policy_aws" not in runs)
check("it installs PyYAML at a pinned version", re.search(r"pip install .*PyYAML==\d+\.\d+\.\d+", runs) is not None, runs)

lock = (REPO / "verify/e2e-tools.lock").read_text(encoding="utf-8")
structural = (REPO / "verify/test_iam_policy_structural.py").read_text(encoding="utf-8")
want = re.search(r'WANT_CONFTEST = "([\d.]+)"', structural)
check("the lock fetches the conftest the structural test requires",
      want is not None and re.search(rf"^conftest\s+v{re.escape(want.group(1))}\s", lock, re.M) is not None)
check("the lock fetches terraform", re.search(r"^terraform\s+v\d", lock, re.M) is not None)

print(f"\n{len(failures)} failure(s)")
sys.exit(1 if failures else 0)
