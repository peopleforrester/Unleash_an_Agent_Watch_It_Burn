# ABOUTME: Render-gate check for the infrastructure properties that are load-bearing but invisible.
# ABOUTME: Every assertion here is currently TRUE; the point is that nothing stopped it from changing.
#
# The manifest contract test next door covers gitops/ and the images. This one covers infra/terraform
# and the fleet driver, which had no assertions at all.
#
# The shared shape of everything below: terraform apply succeeds, the fleet reports green, and the
# damage shows up later as something that looks unrelated. A node that silently dropped to the AL2023
# 20 GiB default hits DiskPressure and evicts the platform mid-workshop. A cluster applied through an
# implicit profile lands in a co-tenant account and is invisible to its own teardown. Neither is
# detectable by reading the run's output, which is what makes them worth a static gate.
import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
CLUSTER_TF = (REPO / "infra/terraform/aws/cluster/main.tf").read_text()
NETWORK_TF = (REPO / "infra/terraform/aws/network/main.tf").read_text()
FLEET_SH = (REPO / "infra/terraform/fleet/fleet.sh").read_text()
PREFLIGHT_SH = (REPO / "infra/terraform/fleet/preflight.sh").read_text()
TEARDOWN_SH = (REPO / "teardown/teardown.sh").read_text()
STORAGECLASS = (REPO / "infra/gp3-storageclass.yaml").read_text()

failures = []


def check(name, condition):
    print(f"  {'PASS' if condition else 'FAIL'}  {name}")
    if not condition:
        failures.append(name)


print("== node shape ==")
# disk_size is SILENTLY IGNORED once cloudinit_pre_nodeadm forces a custom launch template, so a node
# group that sets it instead of block_device_mappings gets AL2023's 20 GiB default and DiskPressure.
check(
    "root volume set via block_device_mappings, not the ignored disk_size",
    "block_device_mappings" in CLUSTER_TF
    and not re.search(r"^\s*disk_size\s*=", CLUSTER_TF, re.M),
)
check(
    "node_disk_size defaults to at least 50 GiB",
    any(
        int(m) >= 50
        for m in re.findall(
            r'variable "node_disk_size".*?default\s*=\s*(\d+)', CLUSTER_TF, re.S
        )
    ),
)
# Prefix delegation alone is not enough: AL2023's nodeadm ignores it when computing max-pods, so both
# the CNI env var and an explicit maxPods are required or ~15 pods per cluster sit Pending forever
# while the cluster itself reports healthy.
check("vpc-cni enables prefix delegation", "ENABLE_PREFIX_DELEGATION" in CLUSTER_TF)
check("nodeadm sets maxPods explicitly (nodeadm ignores prefix delegation)", "maxPods: 110" in CLUSTER_TF)
check("vpc-cni enforces NetworkPolicy (the egress beat is inert without it)",
      'enableNetworkPolicy = "true"' in CLUSTER_TF)

print("== account isolation ==")
# accen-dev is shared with the co-tenant Packt project. A default profile means any path that forgets
# -var profile= applies there silently rather than failing, and those clusters are then invisible to
# the intended account's teardown.
for label, text in (("cluster", CLUSTER_TF), ("network", NETWORK_TF)):
    block = re.search(r'variable "profile"\s*\{(.*?)\n\}', text, re.S)
    check(
        f"{label} root: profile has NO default (an implicit account is unrecoverable)",
        bool(block) and not re.search(r"^\s*default\s*=", block.group(1), re.M),
    )
check(
    "fleet records the account each cluster was built in",
    "record_membership" in FLEET_SH and ".account" in FLEET_SH,
)
check(
    "teardown refuses to destroy through a mismatched account",
    "assert_membership_matches" in FLEET_SH,
)

print("== preflight actually measures the lab VPC ==")
# The shared lab VPC is the one fleet dependency with no in-cluster fallback: without it, all 50 of
# that account's clusters fail at the first apply. preflight.sh is the gate that answers "are we
# ready", and from the 2026-06-27 teardown until 2026-09-02 it answered yes for four accounts that
# had no VPC at all. The check was `[[ -f states/<acct>.tfstate ]]`, and `terraform destroy` leaves
# the state file in place with resources=0 and no outputs, so a destroyed account is indistinguishable
# from a provisioned one. Two months of PREFLIGHT GREEN over an empty fleet, and nothing in the
# output hinted at it. These assertions exist so the file-existence shortcut cannot come back.
check(
    "preflight reads the vpc_id OUTPUT (a destroyed state still has its file)",
    "output" in PREFLIGHT_SH and "-raw vpc_id" in PREFLIGHT_SH,
)
check(
    "preflight confirms the VPC is live (a state can name a VPC deleted out of band)",
    "describe-vpcs" in PREFLIGHT_SH and "--vpc-ids" in PREFLIGHT_SH,
)
# The specific regression: a bare -f test on the state whose only consequence is a pass.
_file_only = re.search(
    r'if\s+\[\[\s+-f\s+"\$\{LAB_VPC_DIR\}/states/\$\{acct\}\.tfstate"\s+\]\];\s*then\s*\n\s*ok\s',
    PREFLIGHT_SH,
)
check("preflight does NOT pass the lab-VPC check on file existence alone", not _file_only)

print("== a provisioned attendee cluster is also REACHABLE and CLAIMABLE ==")
# Provisioning was only ever half the job, and the other half was instructor-only. `up` built attendee
# clusters that were healthy, routable by DNS, and invisible to both the router and the provisioning app:
# a student claiming one was told there were no clusters, and once that was fixed by hand, the URL they
# were handed 404'd. Observed live 2026-09-02 during a rehearsal, twice, on the same five clusters. At 250
# clusters that is the entire room, and neither failure looks like a provisioning bug from the outside.
_up = FLEET_SH[FLEET_SH.index("cmd_up()"):]
_up = _up[:_up.index("\ncmd_", 1)] if "\ncmd_" in _up[1:] else _up
check("cmd_up regenerates the router map (else the friendly hostname 404s)", "cmd_routes" in _up)
check("cmd_up registers with the provisioning app (else the pool reads empty)", "ingest_one" in _up)
check("cmd_up is LOUD when it cannot register (a quiet skip is what hid this)",
      "were NOT registered" in _up and "record_fail" in _up)

print("== attendee hostnames are unique and actually varied ==")
# Two students handed the same hostname is unrecoverable mid-workshop, and the failure is silent: both
# URLs resolve, both consoles work, and they are the same cluster. The generator is a multiplicative
# stride over the word grid, which is collision-free ONLY while the stride is coprime with the grid size.
# Appending a word changes the grid size, so that property has to be asserted rather than assumed.
import math as _math
_A = re.search(r"readonly WIB_ADJECTIVES=\((.*?)\)", FLEET_SH, re.S).group(1).split()
_N = re.search(r"readonly WIB_ANIMALS=\((.*?)\)", FLEET_SH, re.S).group(1).split()
_K = int(re.search(r"readonly WIB_NAME_STRIDE=(\d+)", FLEET_SH).group(1))
_T = len(_A) * len(_N)
_names = [f"{_A[((i-1)*_K % _T)//len(_N)]}-{_N[((i-1)*_K % _T) % len(_N)]}" for i in range(1, 251)]
check(f"name stride {_K} is coprime with the {len(_A)}x{len(_N)}={_T} grid (else hostnames repeat)",
      _math.gcd(_K, _T) == 1)
check(f"grid holds at least 250 names ({_T} available)", _T >= 250)
check("no duplicate hostname across 250 slots", len(set(_names)) == len(_names))
# The scatter is the point: grid order gave the first 24 attendees the same first word.
check("consecutive slots vary the FIRST word too (not 24 in a row of one)",
      len({n.split("-")[0] for n in _names[:12]}) >= 10)
check("every hostname label is DNS-safe and within 63 chars",
      all(re.fullmatch(r"[a-z][a-z-]{0,61}[a-z]", n) for n in _names))

print("== a torn-down cluster does not leave its load balancers billing ==")
# drain_cluster_lbs deletes the Services and Ingresses so the AWS Load Balancer Controller can clean up
# while it is still alive. That is the right order and it is also best-effort in every direction: it skips
# the whole block when the cluster API is unreachable, every kubectl is `|| true`, and the deletes time
# out at 150s. Any of those and the destroy proceeds, the controller dies with the cluster, and the load
# balancer bills forever with nothing left looking for it. Measured 2026-09-01 (#157): five torn-down
# clusters left five NLBs and five ALBs active, each still holding two target groups. At 250 attendees a
# per-cluster leak is ~100 orphaned load balancers, and they hold ENIs in the shared VPC, so a big enough
# pile fails NEW provisioning with subnet IP exhaustion rather than merely costing money.
_down = FLEET_SH[FLEET_SH.index("down_one() {"):]
_down = _down[:_down.index("\n}\n") + 3]
check("teardown sweeps the AWS side after destroy, not only the Kubernetes side",
      "sweep_orphan_lbs" in _down)
_after_fi = _down[_down.rindex("    fi"):]
check("the sweep runs on a FAILED destroy too (that is when leaks happen)",
      "sweep_orphan_lbs" in _after_fi)
check("the sweep matches on the controller's cluster tag, not a name pattern or an age",
      "elbv2.k8s.aws/cluster" in FLEET_SH)
check("a leak is recorded as a failure rather than swept silently",
      'record_fail "lb-leak:' in FLEET_SH)
check("an unreachable cluster API is reported, not skipped in silence",
      "cluster API unreachable, NOTHING drained" in FLEET_SH)
check("a fleet-wide orphan reaper exists and is dry-run by default",
      "cmd_reap_lbs" in FLEET_SH and "reap-lbs)" in FLEET_SH and "reap-lbs: DRY-RUN" in FLEET_SH)
check("the reaper also sweeps orphaned EBS volumes (same cause: the CSI controller dies too)",
      "kubernetes.io/cluster/" in FLEET_SH and "delete-volume" in FLEET_SH)

print("== the stated component count matches what is actually shipped ==")
# The abstract said 34 in one sentence and 35 in another, the run-of-show said 43, and the lab page said
# "roughly forty" (#121). A technical audience counts, and three numbers for one platform is worse than a
# wrong one. Measured on a live full-profile cluster 2026-09-03: 41 Argo CD Applications, of which one is
# the app-of-apps and five are demo filler, leaving 35 platform components. So 35 was right all along and
# the other numbers were drift. This asserts the shipped manifests still add up to what the docs claim,
# so the next component added fails here instead of being discovered on stage.
_app_files = {p.stem for p in (REPO / "gitops/apps").glob("*.yaml")}
_demo = {n for n in _app_files if n.startswith("demo-app-")}
# Not every file is one Application: istio and cert-manager each ship several, which is why the live
# count (41) exceeds the file count (38). The invariant we can assert statically is the demo split.
check(f"exactly 5 demo filler apps ship ({len(_demo)} found)", len(_demo) == 5)
_docs = (REPO / "docs/RUN-OF-SHOW-2026-08.md").read_text(encoding="utf-8")
check("the run-of-show no longer claims 43 apps", "43 ArgoCD apps" not in _docs and "43 apps" not in _docs)
check("the run-of-show states the measured 41", "41 Argo CD apps" in _docs or "41 apps" in _docs)
_lab = (REPO / "gitops/ai-layer/web/lab.html").read_text(encoding="utf-8")
check("the lab page states a number rather than 'roughly forty'",
      "Roughly forty" not in _lab and "35 platform components" in _lab)

print("== teardown ordering and safety ==")
# Ordering is the whole point: the LB Services must go while the LB controller can still remove the
# AWS load balancers, and the PVCs while the EBS CSI controller can still reclaim their volumes.
# Destroy first and both orphan, keep billing, and their ENIs block the VPC delete.
drain_at = FLEET_SH.find("drain_cluster_lbs()")
destroy_at = FLEET_SH.find("terraform -chdir=\"${CLUSTER_DIR}\" destroy")
check("LB services are drained before terraform destroy", 0 < drain_at < destroy_at)
check("PVCs are deleted before terraform destroy (else volumes orphan as 'available')",
      "delete pvc" in FLEET_SH)
check("destructive verbs are dry-run unless WIB_APPLY=1", "require_apply" in FLEET_SH)
check("teardown runs the tag audit (untagged resources survive a tag-scoped sweep)",
      "tag-audit.sh" in TEARDOWN_SH or "TAG_AUDIT" in TEARDOWN_SH)

print("== tagging the resources default_tags cannot reach ==")
# Provider default_tags do not reach managed-node-group instances/volumes, CNI-created ENIs, or
# CSI-provisioned PVC volumes. One 50-cluster account on the sister fleet had 451 untagged resources,
# all invisible to a tag-scoped sweep and all still billing.
check("node group tags instances and volumes via the launch template",
      "launch_template_tags" in CLUSTER_TF and "tag_specifications" in CLUSTER_TF)
check("vpc-cni tags the ENIs it creates", "ADDITIONAL_ENI_TAGS" in CLUSTER_TF)
check("gp3 StorageClass tags CSI-provisioned volumes", "tagSpecification_1" in STORAGECLASS)

print("== console reachability ==")
# The in-tree `nlb` value cannot associate the public subnets on this shared, untagged-per-cluster VPC,
# so it places the load balancer in the PRIVATE subnets and no attendee can reach it. Dropping the
# annotations entirely yields a Classic ELB, whose per-region quota is far below the fleet size. Both
# present identically: "the terminal is down".
CONSOLE = (REPO / "gitops/ai-layer/resources.yaml").read_text()
check("console Service requests an external (not in-tree) load balancer",
      "aws-load-balancer-type: external" in CONSOLE)
check("console Service targets pods by ip", "nlb-target-type: ip" in CONSOLE)
check("console Service is explicitly internet-facing", "aws-load-balancer-scheme: internet-facing" in CONSOLE)

print("== workbench pins ==")
# A floating version means the binary an attendee gets can differ between the rehearsal build and the
# delivery build, with no signal that anything changed.
DOCKERFILE = (REPO / "images/web-terminal/Dockerfile").read_text()
# Match the ASSIGNMENT, not any mention of the URL: the pin's provenance comment cites the same
# stable-N.txt endpoint it was resolved from, and a test that cannot tell a comment from a command
# substitution fails on the documentation rather than the defect.
check("kubectl version is a literal, not a build-time lookup",
      not re.search(r"KVER=\s*\"?\$\(", DOCKERFILE)
      and bool(re.search(r"ARG KUBECTL_VERSION=v\d+\.\d+\.\d+", DOCKERFILE)))
# jupyter-collaboration 5.x requires jupyterlab>=4.6, having previously required <4. The constraint
# inverted once already; pinning the wrong side resolves collaboration back a generation and the
# extension silently refuses to load while pip reports success.
jl = re.search(r'jupyterlab==(\d+)\.(\d+)', DOCKERFILE)
check("jupyterlab pinned at or above the 4.6 collaboration floor",
      bool(jl) and (int(jl.group(1)), int(jl.group(2))) >= (4, 6))
check("jupyter-collaboration pinned to 5.x (a bare pin resolves it backwards)",
      bool(re.search(r"jupyter-collaboration==5\.", DOCKERFILE)))
check("code-server pinned to an exact version", bool(re.search(r"CODE_SERVER_VERSION=\d+\.\d+\.\d+", DOCKERFILE)))

print("== our own manifests must survive our own enforced policies ==")
# Round 2 flips require-resource-limits and restrict-image-registries to Enforce. Any container we ship
# without limits is therefore denied admission ON THE GUARDED ROUNDS ONLY, which is the worst possible
# place for it: Round 1 looks fine, and the rounds that exist to demonstrate guardrails working are the
# ones where the platform quietly loses pods. Found live 2026-08-27, when both MCP servers were absent
# from r2-1 and r3-1 and the agent had no tools at all on those clusters.
import yaml
_missing = []
for _p in (REPO / "gitops").rglob("*.yaml"):
    if "__pycache__" in _p.parts:
        continue
    try:
        _docs = list(yaml.safe_load_all(_p.read_text()))
    except Exception:
        continue
    for _d in _docs:
        if not isinstance(_d, dict) or _d.get("kind") not in ("Deployment", "StatefulSet", "DaemonSet"):
            continue
        for _c in (_d.get("spec", {}).get("template", {}).get("spec", {}).get("containers") or []):
            _r = _c.get("resources") or {}
            if not (_r.get("limits", {}).get("cpu") and _r.get("limits", {}).get("memory")):
                _missing.append(f"{_d['metadata']['name']}/{_c.get('name')} in {_p.relative_to(REPO)}")
check(f"every shipped container declares cpu+memory limits ({len(_missing)} without)", not _missing)
for _x in _missing[:10]:
    print(f"        {_x}")

if failures:
    print(f"\nFAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("\nAll fleet-contract checks passed.")
