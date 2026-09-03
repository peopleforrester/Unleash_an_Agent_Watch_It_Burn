# ABOUTME: Render-gate check for the five manifest defect classes that recurred across deliveries. All
# ABOUTME: are statically decidable, so they are assertions here rather than a failure on a live cluster.
#
# Each class below cost real debugging time at least once, on this fleet or the sister Packt fleet, and
# each presents as something other than what it is. That is why they are worth a test: an unsubstituted
# placeholder reads as an ArgoCD sync problem, and a directory the container cannot traverse reads as a
# missing build. The cheapest place to catch them is before a cluster exists.
import pathlib, re, sys

REPO = pathlib.Path(__file__).resolve().parents[1]
failures = []

def check(n, c):
    print(f"  {'PASS' if c else 'FAIL'}  {n}")
    if not c:
        failures.append(n)

# Manifests that ArgoCD applies, plus the images they refer to.
#
# challenges/, games/ and security/ are in scope even though ArgoCD does not own them: they are applied
# BY HAND during the live run, which makes them the manifests a defect hurts most. An unsubstituted
# placeholder or an unpullable image in a challenge fixture fails on stage, in front of the room, with
# no chance to fix it quietly.
MANIFEST_DIRS = [
    REPO / "gitops",
    REPO / "policies",
    REPO / "observability-idp",
    REPO / "challenges",
    REPO / "games",
    REPO / "security",
]
manifests = sorted(
    p for d in MANIFEST_DIRS if d.is_dir()
    for p in d.rglob("*.yaml")
    if "__pycache__" not in p.parts
)
check("found manifests to audit", len(manifests) > 0)
blobs = [(p, p.read_text()) for p in manifests]

# --- 1. Unsubstituted placeholders --------------------------------------------------------------
# A REPLACE_WITH_* token that no provisioning step substitutes leaves an Application Degraded forever,
# and it looks like a sync failure rather than a typo. Any placeholder that survives into git must be
# one some step is proven to fill in; there are currently none, so the allow-list is empty.
SUBSTITUTED = set()
placeholders = []
for p, txt in blobs:
    for m in re.finditer(r"REPLACE_WITH_[A-Z0-9_]+", txt):
        if m.group(0) not in SUBSTITUTED:
            placeholders.append(f"{p.relative_to(REPO)}: {m.group(0)}")
check(f"no unsubstituted REPLACE_WITH_* placeholders ({len(placeholders)} found)", not placeholders)
for x in placeholders[:10]:
    print(f"        {x}")

# --- 2. runAsNonRoot without a numeric runAsUser -------------------------------------------------
# runAsNonRoot: true on an image whose USER is a NAME rather than a uid gives CreateContainerConfigError:
# the kubelet cannot verify non-root before start. Hit on vLLM, llm-guard, and two seed Jobs on the
# sister fleet. Whether it is a defect depends on the image, which cannot be read from a manifest, so a
# pod-level runAsNonRoot with no runAsUser is allowed only when the image's USER has been VERIFIED
# numeric by running `id` and reading the config. Recording the uid here is what makes an image swap
# fail this test instead of failing on a cluster.
VERIFIED_NUMERIC_USER = {
    # deployment -> (image tag, verified uid, how)
    "chat-ui": ("nginx-1.27-alpine", 101, "docker image inspect .Config.User == '101', 2026-08-24"),
    "console": ("nginx-1.27-alpine", 101, "docker image inspect .Config.User == '101', 2026-08-24"),
}
missing_uid = []
try:
    import yaml
    for p_, txt in blobs:
        for doc in yaml.safe_load_all(txt):
            if not isinstance(doc, dict) or doc.get("kind") not in ("Deployment", "StatefulSet", "DaemonSet", "Job"):
                continue
            name = doc.get("metadata", {}).get("name", "?")
            spec = doc.get("spec", {}).get("template", {}).get("spec", {})
            psc = spec.get("securityContext") or {}
            if not psc.get("runAsNonRoot"):
                continue
            if "runAsUser" in psc:
                continue
            # Every container may still carry its own numeric runAsUser.
            containers = spec.get("containers") or []
            if containers and all("runAsUser" in (c.get("securityContext") or {}) for c in containers):
                continue
            if name in VERIFIED_NUMERIC_USER:
                continue
            missing_uid.append(f"{p_.relative_to(REPO)}: {name} (verify the image USER is numeric, then allow-list it)")
except ImportError:
    print("  SKIP  runAsNonRoot check (pyyaml unavailable)")
check(f"every runAsNonRoot resolves to a numeric uid ({len(missing_uid)} unverified)", not missing_uid)
for x in missing_uid[:10]:
    print(f"        {x}")

# --- 3. Image repository that repeats the registry host ------------------------------------------
# `registry: ghcr.io` plus `repository: ghcr.io/...` yields a doubled path and an unpullable image.
doubled = []
for p, txt in blobs:
    for m in re.finditer(r"repository:\s*['\"]?([^\s'\"]+)", txt):
        repo = m.group(1)
        if re.match(r"^(ghcr\.io|docker\.io|quay\.io|registry\.k8s\.io|public\.ecr\.aws)/", repo):
            # Only a defect when a sibling `registry:` key also carries the host.
            idx = txt[: m.start()].count("\n")
            window = "\n".join(txt.splitlines()[max(0, idx - 8): idx + 8])
            if re.search(r"registry:\s*['\"]?(ghcr\.io|docker\.io|quay\.io)", window):
                doubled.append(f"{p.relative_to(REPO)}: {repo}")
check(f"no image repository repeats its registry host ({len(doubled)} found)", not doubled)
for x in doubled[:10]:
    print(f"        {x}")

# --- 4. A directory the container cannot traverse ------------------------------------------------
# `Cannot find module '/app/...'` for a path that demonstrably contains the module is an ownership
# problem, not a missing build. Any image that sets a non-root USER must also make its app tree
# readable by that user, so a COPY as root followed by USER <name> needs an explicit chown.
dockerfiles = sorted(p for p in (REPO / "images").rglob("Dockerfile") if "__pycache__" not in p.parts)
check("found Dockerfiles to audit", len(dockerfiles) > 0)
untraversable = []
for p in dockerfiles:
    txt = p.read_text()
    user = re.search(r"^USER\s+(\S+)", txt, re.M)
    if not user or user.group(1) == "root":
        continue
    # COPY/ADD lines that land before the USER switch and set no ownership.
    upto = txt[: user.start()]
    for line in upto.splitlines():
        if re.match(r"^\s*(COPY|ADD)\s", line) and "--chown" not in line:
            # Fine if a later chown covers the tree; look for any chown of the workdir or app path.
            if not re.search(r"chown\s+-R", txt):
                untraversable.append(f"{p.relative_to(REPO)}: {line.strip()[:80]}")
check(f"non-root images chown what they COPY ({len(untraversable)} suspect)", not untraversable)
for x in untraversable[:10]:
    print(f"        {x}")

# --- 5. Credentials that drift between copies ----------------------------------------------------
# The defect is DUPLICATION, not the existence of a literal: a shared credential copied into a second
# manifest drifts from the first and fails at the worst moment. So this looks for the same literal
# value appearing in more than one place, which is what makes it drift. A single generator literal is
# a different question (whether it should come from a secret store), tracked by its verify-at-build
# note rather than failed here.
LITERAL = re.compile(
    r"(?i)\b(?:password|passwd|secret[-_]?key|token|api[-_]?key)\b\s*[:=]\s*['\"]?([A-Za-z0-9+/=_-]{12,})",
)
ALLOW = re.compile(r"(?i)(valueFrom|secretKeyRef|configMapKeyRef|\$\(|\$\{|REPLACE_WITH|changeme|example|<[^>]+>)")
seen = {}
for p_, txt in blobs:
    for line in txt.splitlines():
        if ALLOW.search(line):
            continue
        m = LITERAL.search(line)
        if m:
            seen.setdefault(m.group(1), set()).add(str(p_.relative_to(REPO)))
dupes = {v: sorted(f) for v, f in seen.items() if len(f) > 1}
check(f"no credential literal is duplicated across manifests ({len(dupes)} duplicated)", not dupes)
for v, files in list(dupes.items())[:5]:
    print(f"        {v[:12]}... in {', '.join(files)}")

# --- The terminal credential must stay wired -----------------------------------------------------
# Regression guard for the finding that an attendee reached the instructor's cluster. Enforcement has
# to be at ttyd, because the NLB answers on its bare IP and anything upstream is routed around.
entry = (REPO / "images" / "web-terminal" / "entrypoint.sh").read_text()
res = (REPO / "gitops" / "ai-layer" / "resources.yaml").read_text()
check("ttyd enforces TTYD_CREDENTIAL when one is supplied",
      "TTYD_CREDENTIAL" in entry and re.search(r"ttyd .*-c \"\$\{TTYD_CREDENTIAL\}\"", entry) is not None)
check("an absent credential is logged loudly rather than passing silently",
      "UNAUTHENTICATED" in entry)
check("the terminal-auth Secret is mounted into the terminal",
      "terminal-auth" in res)
check("the fleet bootstrap creates a terminal credential per cluster",
      "bootstrap_terminal_auth" in (REPO / "infra" / "terraform" / "fleet" / "fleet.sh").read_text())

# --- No coding-agent CLI may be exposed to an attendee ------------------------------------------
#
# These assertions replace a block that checked the in-workbench tutor was keyless, read-only, and did
# not publish the terminal transcript. All of that was true and it did not matter: clicking the tab put
# Claude Code's "Trust this folder?" prompt in front of an attendee. Suppressing that relies on
# undocumented per-project keys inside the CLI's own config, so a release can bring it back and it
# would appear live, in the room. The surface was removed rather than patched (issue #89), and these
# guard the removal, because the pieces are individually reasonable and easy to reintroduce.
entry = (REPO / "images" / "web-terminal" / "entrypoint.sh").read_text()
dockerfile = (REPO / "images" / "web-terminal" / "Dockerfile").read_text()
console_conf = (REPO / "gitops" / "ai-layer" / "console.conf").read_text()
lab_html = (REPO / "gitops" / "ai-layer" / "web" / "lab.html").read_text()

# REVERSED 2026-09-01 for the BINARY only, on Michael's explicit instruction: the AI coding CLIs are now
# installed on purpose so a student can invoke them. What stranded an attendee was never the binary being
# on disk, it was the BUTTON that started one unasked (the comment above says as much). So the guard now
# asserts the dangerous half and nothing else: the CLIs must be reachable only by someone typing a
# command, never auto-started and never given a surface.
check("the AI CLIs are installed for the student to invoke",
      "@anthropic-ai/claude-code@latest" in dockerfile)
check("no CLI is auto-started by the entrypoint",
      not re.search(r"(run_service|exec|nohup|&\s*$).*\b(claude|gemini|codex|opencode|aider)\b", entry, re.M))
check("no CLI is given a tab or a launcher in the lab page",
      not re.search(r'data-i="(tutor|claude|gemini|codex|opencode|aider)"', lab_html)
      and not re.search(r'onclick="[^"]*(showTutor|launch(Claude|Gemini|Codex|Agent))', lab_html))
check("the entrypoint starts no tutor service",
      not re.search(r"run_service\s+tutor", entry))
check("nginx exposes no /tutor/ route", "location /tutor/" not in console_conf)
check("the lab page has no tutor tab", 'data-i="tutor"' not in lab_html)
# The transcript existed only so the tutor could read what the attendee typed. With no reader, a
# verbatim keystroke log of every session is a liability, not a feature.
check("the shell is not wrapped in a transcript recorder",
      "/.session/transcript" not in entry)

# --- The terminal memory limit must stay above the level that OOM-killed one --------------------
# The sister fleet OOM-killed a student terminal at 2Gi. Anything at or below that is a regression.
# Parsed from YAML, not matched with a regex: "name: ttyd" also appears as a PORT name and as a Service
# port, and a regex anchored on it silently reads the wrong container's limits. That exact mistake
# reported 8Gi here while the file said 4Gi.
def _mib(v):
    v = str(v)
    if v.endswith("Gi"):
        return int(v[:-2]) * 1024
    if v.endswith("Mi"):
        return int(v[:-2])
    return int(v) // (1024 * 1024)

term_limit = None
try:
    import yaml as _y
    for doc in _y.safe_load_all(res):
        if isinstance(doc, dict) and doc.get("kind") == "Deployment" \
           and doc.get("metadata", {}).get("name") == "web-terminal":
            for c in doc["spec"]["template"]["spec"]["containers"]:
                if c.get("name") == "ttyd":
                    term_limit = c.get("resources", {}).get("limits", {}).get("memory")
except ImportError:
    pass
check("web-terminal ttyd container declares a memory limit", term_limit is not None)
if term_limit:
    check(f"web-terminal memory limit exceeds the 2Gi that OOM-killed a shell (is {term_limit})",
          _mib(term_limit) > 2048)

print("== the OTel Instrumentation CR pins its injected images ==")
# An unpinned autoinstrumentation image defaulted to EMPTY, which the Operator rejected with
# "spec.initContainers[0].image: Required value" and which SILENTLY REMOVED guard-proxy: BurritoBot lost
# its /chat backend on a cluster whose pages all still returned 200 and whose Argo apps looked healthy
# (#154). The pin removes the race and the silent-failure mode together, and this asserts it stays pinned.
_instr = (REPO / "gitops/ai-layer-otel/instrumentation.yaml").read_text(encoding="utf-8")
import re as _re
_img = _re.search(r"python:\s*\n\s*image:\s*(\S+)", _instr)
check("the python autoinstrumentation image is set at all", bool(_img))
check("...and pinned to an explicit version, not a floating tag",
      bool(_img) and ":" in _img.group(1).rsplit("/", 1)[-1]
      and not _img.group(1).endswith((":latest", ":main")))

if failures:
    print(f"\nFAILED: {len(failures)}")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print(f"\nAll manifest-contract checks passed ({len(manifests)} manifests, {len(dockerfiles)} Dockerfiles).")

# --- every volumeMount must have a matching volume, in the SAME pod spec -------------------------------
# Caught live 2026-08-31: a tls volumeMount was added to the console container while the volume itself
# landed in a different Deployment's volumes block (the first "- name: web" in the file). ArgoCD rejected
# the Deployment as invalid and retried forever; the symptom was "app OutOfSync" with no obvious cause.
# A mount without its volume is always a bug and is cheap to detect.
def _check_mounts_have_volumes():
    import yaml as _yaml
    bad = []
    for doc in _yaml.safe_load_all(open(REPO / "gitops" / "ai-layer" / "resources.yaml")):
        if not isinstance(doc, dict) or doc.get("kind") not in ("Deployment", "StatefulSet", "DaemonSet"):
            continue
        spec = doc.get("spec", {}).get("template", {}).get("spec", {})
        declared = {v.get("name") for v in (spec.get("volumes") or [])}
        name = doc.get("metadata", {}).get("name", "?")
        for c in (spec.get("containers") or []) + (spec.get("initContainers") or []):
            for m in (c.get("volumeMounts") or []):
                if m.get("name") not in declared:
                    bad.append(f"{name}/{c.get('name')} mounts {m.get('name')!r} with no such volume")
    return bad


_bad_mounts = _check_mounts_have_volumes()
if _bad_mounts:
    print("  detail:", "; ".join(_bad_mounts[:3]))
check("every volumeMount resolves to a volume in the same pod spec", not _bad_mounts)
