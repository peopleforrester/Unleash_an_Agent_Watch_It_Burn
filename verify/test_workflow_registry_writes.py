# ABOUTME: No GitHub workflow writes an image tag except through scripts/ghcr_version_tag.py (#815), so a later workflow
# ABOUTME: edit or a new build workflow (a workshop-mcp one, say) cannot move a pinned, signed tag. Offline, YAML only.
"""Offline.

#815: 4a1a47f (#714) edited build-web-terminal.yml, the workflow rebuilt the image and pushed it over
web-terminal-ttyd-1.7.7, and the tag moved off the digest images.lock and gitops/ai-layer/resources.yaml pin and the
workshop key signs. #816 made that workflow's push go through scripts/ghcr_version_tag.py, which never pushes over a
tag ghcr.io has and puts a pinned tag that moved back on its pin; verify/test_ghcr_version_tag.py holds the script and
the two workflows that call it. This test holds every other workflow: each step of each file in .github/workflows is
read, and a step that writes to a registry by any other means fails it. The issue asked for build-workshop-mcp to be
checked the same way. No such workflow exists (workshop-mcp-mcp-1.29.1 is pushed by hand), and if one is added, this
test makes it push through the script too.

The checker is first run on workflows this test writes itself, one per way to write a tag, so a check that stopped
matching reads as that and not as a pass.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
WORKFLOWS = REPO / ".github" / "workflows"
SCRIPT_CALL = "python3 scripts/ghcr_version_tag.py"

failures: list[str] = []


def check(label: str, ok: bool) -> None:
    print(("PASS " if ok else "FAIL ") + label)
    if not ok:
        failures.append(label)


# Shell commands that put a manifest or a tag in a registry. ghcr_version_tag.py's own crane and docker calls are in
# the script, not the workflow, so a workflow line matching any of these is a write that skips the script's table.
SHELL_WRITES = [
    (r"\bdocker\s+(image\s+)?push\b", "docker push"),
    (r"\bdocker\s+(buildx\s+)?build\b[^\n]*--push\b", "docker build --push"),
    (r"\bdocker\s+buildx\s+imagetools\s+create\b", "docker buildx imagetools create"),
    (r"\bdocker\s+manifest\s+push\b", "docker manifest push"),
    (r"\bcrane\s+(copy|cp|tag|push|append|mutate|rebase|flatten|delete)\b", "crane write"),
    (r"\bskopeo\s+copy\b", "skopeo copy"),
    (r"\boras\s+(push|tag|copy|cp)\b", "oras write"),
    (r"\bregctl\s+(image\s+(copy|mod)|tag|manifest\s+put)\b", "regctl write"),
    (r"\bpodman\s+push\b", "podman push"),
    (r"\bbuildah\s+push\b", "buildah push"),
    (r"\bkaniko\b|/kaniko/executor\b", "kaniko"),
    (r"\bko\s+(build|publish|apply)\b", "ko publish"),
]

# Actions that push on every use. docker/build-push-action and docker/bake-action push only when push is true or an
# output names a registry, so they are read input by input below.
PUSH_ACTIONS = ("redhat-actions/push-to-registry",)


def _falsy(value) -> bool:
    return value is None or value is False or str(value).strip().lower() in ("", "false")


def writes(workflow_text: str) -> list[str]:
    """Each registry write in a workflow that does not go through the script, as 'job/step: how'."""
    doc = yaml.safe_load(workflow_text) or {}
    found: list[str] = []
    for job_name, job in (doc.get("jobs") or {}).items():
        if not isinstance(job, dict):
            continue
        if isinstance(job.get("uses"), str):
            found.append(f"{job_name}: calls a reusable workflow ({job['uses']}), which this test cannot read")
        for i, step in enumerate(job.get("steps") or []):
            where = f"{job_name}/{step.get('name') or step.get('id') or i}"
            uses = str(step.get("uses") or "")
            inputs = step.get("with") or {}
            if uses.startswith("docker/build-push-action") or uses.startswith("docker/bake-action"):
                if not _falsy(inputs.get("push")):
                    found.append(f"{where}: {uses} with push: {inputs.get('push')}")
                outputs = str(inputs.get("outputs") or "")
                if re.search(r"type=registry|push=true", outputs):
                    found.append(f"{where}: {uses} with outputs: {outputs}")
            elif any(uses.startswith(a) for a in PUSH_ACTIONS):
                found.append(f"{where}: {uses}")
            run = str(step.get("run") or "")
            for pattern, how in SHELL_WRITES:
                if re.search(pattern, run):
                    found.append(f"{where}: {how}")
    return found


def calls_script(workflow_text: str) -> bool:
    doc = yaml.safe_load(workflow_text) or {}
    for job in (doc.get("jobs") or {}).values():
        for step in (job or {}).get("steps") or []:
            if SCRIPT_CALL in str(step.get("run") or ""):
                return True
    return False


def holds_registry_write(workflow_text: str) -> bool:
    """A workflow that can write to ghcr.io: it holds the write token or grants packages: write."""
    doc = yaml.safe_load(workflow_text) or {}
    perms = doc.get("permissions")
    granted = isinstance(perms, dict) and str(perms.get("packages", "")).strip() == "write"
    for job in (doc.get("jobs") or {}).values():
        jp = (job or {}).get("permissions")
        if isinstance(jp, dict) and str(jp.get("packages", "")).strip() == "write":
            granted = True
    return granted or "secrets.GHCR_TOKEN" in workflow_text


# 1. The checker on workflows this test writes: each way to write a tag is caught, and a build that only loads is not.
print("== the checker ==")


def wf(steps: str) -> str:
    return "name: t\non: push\njobs:\n  build:\n    runs-on: ubuntu-latest\n    steps:\n" + steps


LOAD_ONLY = wf("      - uses: docker/build-push-action@v6\n        with:\n          context: x\n          load: true\n"
               "          tags: x:built\n"
               "      - run: python3 scripts/ghcr_version_tag.py x:built \"${TAG}\" images.lock\n")
check("a build that only loads, then calls the script, writes nothing", writes(LOAD_ONLY) == [])
check("and it calls the script", calls_script(LOAD_ONLY))

BAD = {
    "build-push-action push: true": wf("      - uses: docker/build-push-action@v6\n        with:\n          push: true\n"
                                       "          tags: ghcr.io/peopleforrester/watch-it-burn:workshop-mcp-mcp-1.29.1\n"),
    "build-push-action push from an expression": wf("      - uses: docker/build-push-action@v6\n        with:\n"
                                                    "          push: ${{ github.ref == 'refs/heads/main' }}\n"),
    "build-push-action outputs type=registry": wf("      - uses: docker/build-push-action@v6\n        with:\n"
                                                  "          outputs: type=registry\n"),
    "bake-action push: true": wf("      - uses: docker/bake-action@v5\n        with:\n          push: true\n"),
    "docker push": wf("      - run: docker push ghcr.io/peopleforrester/watch-it-burn:web-terminal-ttyd-1.7.7\n"),
    "docker image push in a block": wf("      - run: |\n          set -e\n          docker image push \"${TAG}\"\n"),
    "docker buildx build --push": wf("      - run: docker buildx build -t \"${TAG}\" --push images/web-terminal\n"),
    "imagetools create": wf("      - run: docker buildx imagetools create -t \"${TAG}\" \"${SRC}\"\n"),
    "crane copy": wf("      - run: crane copy \"${SRC}\" \"${TAG}\"\n"),
    "crane tag": wf("      - run: crane tag \"${REF}\" web-terminal-ttyd-1.7.7\n"),
    "skopeo copy": wf("      - run: skopeo copy docker-archive:x.tar \"docker://${TAG}\"\n"),
    "oras push": wf("      - run: oras push \"${TAG}\" x.tar\n"),
    "regctl image copy": wf("      - run: regctl image copy \"${SRC}\" \"${TAG}\"\n"),
    "podman push": wf("      - run: podman push \"${TAG}\"\n"),
    "push-to-registry action": wf("      - uses: redhat-actions/push-to-registry@v2\n"),
}
for how, text in BAD.items():
    check(f"catches {how}", len(writes(text)) == 1)
REUSABLE = "name: t\non: push\njobs:\n  build:\n    uses: someone/else/.github/workflows/push.yml@v1\n"
check("catches a job that calls a reusable workflow", len(writes(REUSABLE)) == 1)
check("reads packages: write as a write grant", holds_registry_write(wf("      - run: true\n").replace(
    "jobs:", "permissions:\n  packages: write\njobs:")))
check("reads the GHCR_TOKEN secret as a write grant",
      holds_registry_write(wf("      - env:\n          T: ${{ secrets.GHCR_TOKEN }}\n        run: true\n")))
check("a workflow with neither is no write grant", not holds_registry_write(wf("      - run: true\n")))

# 2. The repo's workflows.
print("== .github/workflows ==")
files = sorted(list(WORKFLOWS.glob("*.yml")) + list(WORKFLOWS.glob("*.yaml")))
check(f"{WORKFLOWS.relative_to(REPO)} has workflows to read", len(files) > 0)
for path in files:
    text = path.read_text(encoding="utf-8")
    rel = path.relative_to(REPO)
    found = writes(text)
    check(f"{rel} writes no image tag except through {SCRIPT_CALL}" + (f" (it does: {found})" if found else ""),
          found == [])
    if holds_registry_write(text):
        check(f"{rel} holds a registry write (packages: write or GHCR_TOKEN), so it calls {SCRIPT_CALL}",
              calls_script(text))

# The three that hold the write today, by name, so a rename that dropped one from the loop above reads here.
for name in ("build-web-terminal.yml", "keep-sample-app-tag.yml", "push-jokers.yml"):
    path = WORKFLOWS / name
    check(f"{name} is there and calls {SCRIPT_CALL}", path.is_file() and calls_script(path.read_text(encoding="utf-8")))

print()
if failures:
    print(f"{len(failures)} check(s) failed:")
    for f in failures:
        print("  - " + f)
    sys.exit(1)
print("all checks passed")
