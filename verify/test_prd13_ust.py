# ABOUTME: PRD #13's locked UST values (deployment.environment.name, service.name, service.version) are the ones
# ABOUTME: the AI-layer manifests emit, in the Locked Decisions table and in the Milestone 3 and 4 criteria.
#
# Why (#590). The PRD locks the UST values every AI-layer pod emits, and the manifests moved under it: the
# service names to the burritobot-* family on 2026-09-06 (#265), agentgateway's span version to v1.5.0 on
# 2026-10-24 (#495), and the env to burritobot-kubecon-na-26 on 2026-10-27 (#629). The PRD went on naming
# kagent/agentgateway/guard-proxy/evil-mcp-shim, v1.3.0 and production. #586 moved only the kagent version, and
# test_kagent_version_pins.py holds that one row to the chart. This holds the rest to the manifests, read from
# the same places test_observability.py reads them. A superseded value may follow the current one, as history.
import pathlib, re, sys

import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
PRD13 = "prds/13-mvp-walking-skeleton.md"
failures = []


def check(n, c, detail=""):
    print(f"  {'PASS' if c else 'FAIL'}  {n}" + (f"\n        {detail}" if (detail and not c) else ""))
    if not c:
        failures.append(n)


def docs(rel):
    return [d for d in yaml.safe_load_all((REPO / rel).read_text(encoding="utf-8")) if d]


def attrs(env):
    value = next((e.get("value", "") for e in env if e["name"] == "OTEL_RESOURCE_ATTRIBUTES"), "")
    return dict(kv.split("=", 1) for kv in value.split(",") if "=" in kv)


def deployment_attrs(rel, name):
    dep = next(d for d in docs(rel) if d.get("kind") == "Deployment" and d.get("metadata", {}).get("name") == name)
    return attrs(dep["spec"]["template"]["spec"]["containers"][0].get("env", []))


def kagent_attrs():
    agent = next(d for d in docs("gitops/workshop-agent/agent.yaml") if d.get("kind") == "Agent")  # its own app (#707)
    return attrs(agent["spec"]["declarative"]["deployment"]["env"])


# The PRD names each component by what it is; the manifests are where its UST comes from.
EMITTED = {
    "kagent": kagent_attrs(),
    "agentgateway": deployment_attrs("gitops/ai-layer/agentgateway.yaml", "agentgateway"),
    "guard-proxy": deployment_attrs("gitops/ai-layer/resources.yaml", "guard-proxy"),
    "evil-mcp-shim": deployment_attrs("gitops/ai-layer/resources.yaml", "evil-mcp-shim"),
}
KEYS = ("service.name", "service.version", "deployment.environment.name")

print("== the manifests give every component all three UST keys and one env ==")
for comp, a in EMITTED.items():
    check(f"{comp} emits {', '.join(KEYS)} (found {sorted(a)})", all(a.get(k) for k in KEYS))
envs = {a.get("deployment.environment.name") for a in EMITTED.values()}
check(f"the four components emit one deployment.environment.name (found {sorted(map(str, envs))})", len(envs) == 1)
ENV = next(iter(envs)) if len(envs) == 1 else None

prd_lines = (REPO / PRD13).read_text(encoding="utf-8").splitlines()


def row_value(label):
    """The value cell of the Locked Decisions row whose first cell is `label`, or None."""
    rows = [l for l in prd_lines if re.match(rf"^\|\s*{re.escape(label)}\s*\|", l)]
    check(f"{PRD13} has one Locked Decisions row for {label}", len(rows) == 1, f"{rows}")
    if len(rows) != 1:
        return None
    cells = [c.strip() for c in rows[0].strip().strip("|").split("|")]
    return cells[1] if len(cells) > 1 else ""


def first_code(cell):
    """The row's current value: the backticked value the cell starts with. Anything after it is history."""
    m = re.match(r"`([^`]*)`", cell or "")
    return m.group(1) if m else None


print("== the Locked Decisions table gives the values the manifests emit ==")
cell = row_value("`deployment.environment.name`")
check(f"{PRD13} locks deployment.environment.name `{ENV}` (found {first_code(cell)})", first_code(cell) == ENV, cell)
for comp, a in EMITTED.items():
    # kagent's service.version row is test_kagent_version_pins.py's: it is held to the chart, not to the manifest.
    for key in ("service.name", "service.version") if comp != "kagent" else ("service.name",):
        cell = row_value(f"`{key}` for {comp}")
        check(f"{PRD13} locks {key} for {comp} `{a.get(key)}` (found {first_code(cell)})",
              first_code(cell) == a.get(key), cell)


def section(heading):
    """The lines between a heading matching `heading` and the next heading."""
    start = next((i for i, l in enumerate(prd_lines) if re.match(rf"^#+\s*{heading}\b", l)), None)
    check(f"{PRD13} has a {heading} heading", start is not None)
    if start is None:
        return []
    end = next((i for i in range(start + 1, len(prd_lines)) if prd_lines[i].startswith("#")), len(prd_lines))
    return prd_lines[start:end]


def given(line, key):
    return [m.group(1) for m in re.finditer(rf"(?<![\w.]){re.escape(key)}=([^`\s,]+)", line)]


print("== Milestone 3's exit criteria name the values the manifests emit ==")
m3 = section("Milestone 3")
for comp, a in EMITTED.items():
    pods = [l for l in m3 if re.match(rf"^\s*-\s*\[[ xX]\]\s*{re.escape(comp)} pod has\b", l)]
    check(f"{PRD13} Milestone 3 has one exit criterion for the {comp} pod", len(pods) == 1, f"{pods}")
    pod = pods[0] if pods else ""
    for key in KEYS:
        check(f"{PRD13} Milestone 3 {comp} pod criterion names `{key}={a.get(key)}` (found {given(pod, key)})",
              given(pod, key) == [a.get(key)], pod)
# Every other line that states an env (the Goal) states the current one. watch-it-burn is the wrong value
# the steps tell the reader to replace, and the exit criteria hold it out of the manifests.
stated = [(l, v) for l in m3 for v in given(l, "deployment.environment.name") if v != "watch-it-burn"]
check(f"{PRD13} Milestone 3 states deployment.environment.name={ENV} wherever it states one",
      bool(stated) and all(v == ENV for _, v in stated), f"{[l for l, v in stated if v != ENV]}")

print("== Milestone 4 names the service names the manifests emit ==")
m4 = section("Milestone 4")
names = {a.get("service.name") for a in EMITTED.values()}
lines = [l for l in m4 if "service name visible in Datadog" in l]
check(f"{PRD13} Milestone 4 has one criterion for the service name visible in Datadog", len(lines) == 1, f"{lines}")
listed = re.search(r"\(([^)]*)\)", lines[0]) if lines else None
listed = set(re.findall(r"`([^`]*)`", listed.group(1))) if listed else set()
check(f"{PRD13} Milestone 4 lists the emitted service names {sorted(names)} (found {sorted(listed)})", listed == names)

print("== the Acceptance Criteria state the current env ==")
ac = [v for l in section("Acceptance Criteria") for v in given(l, "deployment.environment.name")]
check(f"{PRD13} Acceptance Criteria state deployment.environment.name={ENV} (found {ac})", bool(ac) and set(ac) == {ENV})

if failures:
    print(f"\nFAILED: {len(failures)} check(s)")
    sys.exit(1)
print("\nAll PRD #13 UST checks passed.")
