# ABOUTME: Pins #998's record criterion (#1058): decisions.md's run 18118 entry names what drops the API server's dial
# ABOUTME: to fake-ticket's pod port 8080 on both clusters, and the root rule it says would admit it is still there.
"""Holds the criterion of #998 that test review run 18129 found no test checked (#1058).

#998's criterion: what drops the API server's connection to fake-ticket's pod port 8080 on both clusters is found and
recorded in decisions.md. Run 18118 found it on 2026-11-07 and wrote it under "**What drops the connection.**" in its
entry; run 18206 (#1038) read both clusters again and wrote the same groups. What stays checkable offline is that
record, read here as literal text, and the root rule it names:

  1. the "## 2026-11-07 · #998 · run 18118" entry, once in decisions.md, says the service proxy dials from the
     control plane's cluster security group, that the node security group admits that group only on 443, 4443, 6443,
     8443, 9443, 10250 and 10251 (so not 8080, and 10250, the port-forward's path, is among them), and that it admits
     8080 only from the load balancer controller's shared group (`elbv2.k8s.aws/targetGroupBinding=shared`);
  2. it has one bullet per cluster, watch-it-burn-community and watch-it-burn-private, each naming fake-ticket's pod,
     its node, the node group and the cluster group as read on 2026-11-07, with the same seven ports;
  3. it rules out the rest of the path (no NetworkPolicy in `agent` selects fake-ticket, no Cilium) and records the
     proxy's `kubectl get --raw` timing out on both;
  4. it names #869's `ingress_cluster_8080_workshop_apps` in infra/terraform/aws/cluster/main.tf as the rule that
     would admit it, and that rule is still in the root, admitting TCP 8080 from the cluster security group;
  5. the #1038 entry (run 18206) names the same node group and cluster group for each cluster and the same ports.

Each cut on repo text first checks the literal is there and exits naming the literal and the file when it is not
("Tests own their inputs"). Every check is also run against a cut copy of the real files with the thing it reads
struck or changed, so a check that could never fail shows up here.
"""
from __future__ import annotations

import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "verify"))
import node_sg_rules  # noqa: E402

DECISIONS = (REPO / "decisions.md").read_text(encoding="utf-8")
MAIN_TF = node_sg_rules.CLUSTER_TF.read_text(encoding="utf-8")
TF_PATH = "infra/terraform/aws/cluster/main.tf"

HEAD_998 = "## 2026-11-07 · #998 · run 18118"
HEAD_1038 = "## 2026-11-07 · #1038 · run 18206"
CAUSE = "**What drops the connection.**"
CAUSE_END = "**The change.**"
CAUSE_1038 = "**Why the proxy cannot reach fake-ticket:8080.**"
CAUSE_1038_END = "**The path step 1 reads, and its offline pin.**"

PORTS = {443, 4443, 6443, 8443, 9443, 10250, 10251}
RULE = "ingress_cluster_8080_workshop_apps"
SHARED = "`elbv2.k8s.aws/targetGroupBinding=shared`"
PROXY = "`kubectl get --raw /api/v1/namespaces/agent/services/fake-ticket:8080/proxy/deployments.json"
TIMEOUT = "Client.Timeout exceeded while awaiting headers"
# Each cluster as run 18118 read it: fake-ticket's pod, its node, the node group, the cluster group.
CLUSTERS = {
    "watch-it-burn-community": ("10.0.24.183", "10.0.31.163", "sg-0b7d2a0cfaed6fecd", "sg-04130d5989d5c1ab1"),
    "watch-it-burn-private": ("10.0.109.213", "10.0.90.162", "sg-011fc555e507cfb40", "sg-0ca9886f5a9d4f6d3"),
}

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"\n        {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def anchor(text: str, literal: str, where: str) -> None:
    """Exit naming the literal and the file when a cut-anchor is not present, so a reword reads as that."""
    if literal not in text:
        sys.exit(f"test_998_sg_cause_record.py: {where} no longer holds the literal {literal!r}; "
                 f"reword the test's anchor to match, do not revert the record")


def flat(text: str) -> str:
    """`text` with each run of whitespace one space, so a line wrapped in the Markdown reads as one line."""
    return " ".join(text.split())


def entries(text: str, head: str) -> list[str]:
    """Each entry under `head`, to the next level-2 heading or EOF."""
    return re.findall(r"^" + re.escape(head) + r".*?(?=^## |\Z)", text, flags=re.M | re.S)


def section(entry: str, start: str, end: str) -> str:
    """The text from `start` to `end` in `entry`; empty when either is absent or out of order."""
    i = entry.find(start)
    j = entry.find(end, i + 1) if i >= 0 else -1
    return entry[i:j] if 0 <= i < j else ""


def port_list(text: str) -> set[int] | None:
    """The ports in "admits the cluster security group (or "that group") only on 443, ..., 10250 and 10251"; None
    when not written."""
    m = re.search(r"admits (?:the cluster security group|that group) only on ((?:\d+, )*\d+ and \d+)", text)
    return {int(p) for p in re.findall(r"\d+", m.group(1))} if m else None


def bullet(text: str, cluster: str) -> str:
    """The flattened `- <cluster>:` bullet, to the next bullet or paragraph; empty when absent."""
    m = re.search(r"^- " + re.escape(cluster) + r":(.*?)(?=^- |^\s*$|\Z)", text, flags=re.M | re.S)
    return flat(m.group(1)) if m else ""


def groups(b: str) -> tuple[str, str]:
    """The node group and cluster group a bullet names, each '' when absent."""
    node = re.search(r"node group `(sg-[0-9a-f]+)`", b)
    clus = re.search(r"cluster group `(sg-[0-9a-f]+)`", b)
    return (node.group(1) if node else "", clus.group(1) if clus else "")


def verdict(decisions: str, main_tf: str) -> list[str]:
    """Why the record does not hold, one reason each; empty when it holds."""
    why: list[str] = []
    found = entries(decisions, HEAD_998)
    if len(found) != 1:
        return [f"{len(found)} entries headed {HEAD_998!r}, not one"]
    cause = section(found[0], CAUSE, CAUSE_END)
    if not cause:
        return [f"the #998 entry has no {CAUSE!r} paragraph before {CAUSE_END!r}"]
    text = flat(cause)

    if "service proxy dials fake-ticket's pod from the EKS control-plane" not in text:
        why.append("it does not say the service proxy dials the pod from the control plane")
    if "carry the cluster root's cluster security group" not in text:
        why.append("it does not say the control plane carries the cluster security group")
    if "the node security group judges the dial" not in text:
        why.append("it does not say the node security group judges the dial")
    ports = port_list(text)
    if ports is None:
        why.append("it does not list the ports the node group admits the cluster group on")
    else:
        if 8080 in ports:
            why.append("its list of admitted ports has 8080 in it, so it explains no drop")
        if ports != PORTS:
            why.append(f"its admitted ports are {sorted(ports)}, not {sorted(PORTS)}")
    if not re.search(r"It admits 8080 only from the load balancer controller's shared group \(" + re.escape(SHARED),
                     text):
        why.append("it does not say 8080 is admitted only from the load balancer controller's shared group")

    seen: dict[str, tuple[str, str]] = {}
    for cluster, (pod, node, node_sg, cluster_sg) in CLUSTERS.items():
        b = bullet(cause, cluster)
        if not b:
            why.append(f"it has no bullet for {cluster}")
            continue
        if f"fake-ticket pod `{pod}`" not in b:
            why.append(f"{cluster}'s bullet does not name fake-ticket's pod {pod}")
        if f"node `{node}`" not in b:
            why.append(f"{cluster}'s bullet does not name the pod's node {node}")
        got = groups(b)
        if got != (node_sg, cluster_sg):
            why.append(f"{cluster}'s bullet names node group and cluster group {got}, not {(node_sg, cluster_sg)}")
        if got[0] and got[0] == got[1]:
            why.append(f"{cluster}'s bullet names one group as both the node group and the cluster group")
        if "seven ports above" not in b and "the same seven ports" not in b:
            why.append(f"{cluster}'s bullet does not hold its cluster group to the seven ports")
        seen[cluster] = got
    if len(set(seen.values())) < len(seen):
        why.append("both clusters' bullets name the same groups")

    if "No NetworkPolicy in `agent` selects fake-ticket" not in text:
        why.append("it does not rule out a NetworkPolicy on fake-ticket")
    if "neither cluster runs Cilium" not in text:
        why.append("it does not rule out Cilium")
    if PROXY not in text or TIMEOUT not in text or "after 15 s on both" not in text:
        why.append("it does not record the service proxy's read timing out on both clusters")

    if f"The rule that would admit it is #869's `{RULE}` in `{TF_PATH}`" not in text:
        why.append(f"it does not name #869's {RULE} in {TF_PATH} as the rule that would admit 8080")
    try:
        admitting = node_sg_rules.rule_for_port(node_sg_rules.rules(main_tf), 8080)
    except node_sg_rules.AnchorMissing as e:
        admitting = []
        why.append(f"the node rules cannot be read from {TF_PATH}: {e}")
    if RULE not in admitting:
        why.append(f"{TF_PATH} has no {RULE} admitting TCP 8080 from the cluster security group "
                   f"(rules that do: {admitting})")

    later = entries(decisions, HEAD_1038)
    if len(later) != 1:
        why.append(f"{len(later)} entries headed {HEAD_1038!r}, not one")
    else:
        reread = section(later[0], CAUSE_1038, CAUSE_1038_END)
        if not reread:
            why.append(f"the #1038 entry has no {CAUSE_1038!r} paragraph before {CAUSE_1038_END!r}")
        else:
            if port_list(flat(reread)) != PORTS:
                why.append("the #1038 entry's reread does not list the same seven ports")
            for cluster, (_, _, node_sg, cluster_sg) in CLUSTERS.items():
                if groups(bullet(reread, cluster)) != (node_sg, cluster_sg):
                    why.append(f"the #1038 entry's reread of {cluster} does not name the same two groups")
    return why


print("== decisions.md records what drops the API server's dial to fake-ticket:8080 on both clusters ==")
REASONS = verdict(DECISIONS, MAIN_TF)
check("the #998 entry and the #1038 reread hold the cause, both clusters' groups and the root's rule",
      not REASONS, "; ".join(REASONS))

ENTRY = entries(DECISIONS, HEAD_998)
if len(ENTRY) != 1:
    sys.exit(f"test_998_sg_cause_record.py: decisions.md has {len(ENTRY)} entries headed {HEAD_998!r}, "
             f"so no cut copy can be made")
ENTRY_998 = ENTRY[0]
LATER = entries(DECISIONS, HEAD_1038)
if len(LATER) != 1:
    sys.exit(f"test_998_sg_cause_record.py: decisions.md has {len(LATER)} entries headed {HEAD_1038!r}, "
             f"so no cut copy can be made")
ENTRY_1038 = LATER[0]


def cut_998(old: str, new: str, count: int = 1) -> str:
    anchor(ENTRY_998, old, f"decisions.md's {HEAD_998!r} entry")
    return DECISIONS.replace(ENTRY_998, ENTRY_998.replace(old, new, count), 1)


def cut_1038(old: str, new: str) -> str:
    anchor(ENTRY_1038, old, f"decisions.md's {HEAD_1038!r} entry")
    return DECISIONS.replace(ENTRY_1038, ENTRY_1038.replace(old, new, 1), 1)


def cut_tf(old: str, new: str) -> str:
    anchor(MAIN_TF, old, TF_PATH)
    return MAIN_TF.replace(old, new, 1)


def refused(name: str, decisions: str = DECISIONS, main_tf: str = MAIN_TF) -> None:
    check(name, bool(verdict(decisions, main_tf)))


print("== each cut of the real records is refused ==")
refused("with the #998 entry struck, nothing is recorded", DECISIONS.replace(ENTRY_998, "", 1))
refused("with the #998 entry doubled, it is ambiguous", DECISIONS.replace(ENTRY_998, ENTRY_998 + ENTRY_998, 1))
refused("with the cause's label renamed, the cause is not found", cut_998(CAUSE, "**What we saw.**"))
refused("with the proxy's origin struck, it is refused",
        cut_998("service proxy dials fake-ticket's pod from the EKS", "service proxy reaches fake-ticket's pod from the"))
refused("with the cluster security group struck, it is refused",
        cut_998("carry the cluster root's cluster security group", "carry an address"))
refused("with the node group not judging the dial, it is refused",
        cut_998("the node security group judges the dial", "the pod answers the dial"))
refused("with 8080 added to the admitted ports, it is refused", cut_998("443, 4443, 6443,", "443, 4443, 6443, 8080,"))
refused("with 10250 struck from the admitted ports, it is refused", cut_998("9443, 10250 and 10251", "9443 and 10251"))
refused("with the admitted ports struck, it is refused",
        cut_998("admits the cluster security group only on", "admits the cluster security group on several ports,"))
refused("with 8080 admitted from the cluster group, it is refused",
        cut_998("It admits 8080 only from the load balancer controller's shared group",
                "It admits 8080 from the cluster security group"))
for cluster, (pod, node, node_sg, cluster_sg) in CLUSTERS.items():
    refused(f"with {cluster}'s bullet struck, it is refused", cut_998(f"- {cluster}:", f"- {cluster} (not read)"))
    refused(f"with {cluster}'s pod changed, it is refused", cut_998(f"`{pod}`", "`10.0.0.1`"))
    refused(f"with {cluster}'s node changed, it is refused", cut_998(f"node `{node}`", "node `10.0.0.2`"))
    refused(f"with {cluster}'s node group changed, it is refused",
            cut_998(f"node group `{node_sg}`", "node group `sg-0123456789abcdef0`"))
    refused(f"with {cluster}'s cluster group changed, it is refused",
            cut_998(f"cluster group `{cluster_sg}`", "cluster group `sg-0123456789abcdef0`"))
    refused(f"with {cluster}'s cluster group the node group, it is refused",
            cut_998(f"cluster group `{cluster_sg}`", f"cluster group `{node_sg}`"))
refused("with community's ports not held to seven, it is refused",
        cut_998("on the seven ports above and no other", "on some ports"))
refused("with private's ports not held to seven, it is refused", cut_998("the same seven ports.", "some ports."))
refused("with both clusters naming community's groups, it is refused",
        cut_998("node group `sg-011fc555e507cfb40`, cluster group `sg-0ca9886f5a9d4f6d3`",
                "node group `sg-0b7d2a0cfaed6fecd`, cluster group `sg-04130d5989d5c1ab1`"))
refused("with the NetworkPolicy not ruled out, it is refused",
        cut_998("No NetworkPolicy in `agent` selects fake-ticket", "A NetworkPolicy in `agent` may select fake-ticket"))
refused("with Cilium not ruled out, it is refused", cut_998("neither cluster runs Cilium", "Cilium was not read"))
refused("with the proxy's timeout struck, it is refused", cut_998(TIMEOUT, "an answer"))
refused("with the timeout read on one cluster only, it is refused", cut_998("after 15 s on both", "after 15 s on one"))
refused("with the admitting rule not named, it is refused", cut_998(f"#869's `{RULE}`", "a rule"))
refused(f"with {RULE} gone from the root, it is refused",
        main_tf=cut_tf(f"    {RULE} = {{", "    ingress_cluster_8080_renamed = {"))
refused(f"with {RULE} on another port, it is refused",
        main_tf=cut_tf("      from_port                     = 8080\n      to_port                       = 8080",
                       "      from_port                     = 8081\n      to_port                       = 8081"))
refused(f"with {RULE} from no cluster group, it is refused",
        main_tf=cut_tf('to node 8080/tcp workshop apps (Service proxy)"\n      protocol                      = "tcp"\n'
                       '      from_port                     = 8080\n      to_port                       = 8080\n'
                       '      type                          = "ingress"\n      source_cluster_security_group = true',
                       'to node 8080/tcp workshop apps (Service proxy)"\n      protocol                      = "tcp"\n'
                       '      from_port                     = 8080\n      to_port                       = 8080\n'
                       '      type                          = "ingress"\n      source_cluster_security_group = false'))
refused("with the #1038 entry struck, the reread is gone", DECISIONS.replace(ENTRY_1038, "", 1))
refused("with the #1038 reread's label renamed, it is refused", cut_1038(CAUSE_1038, "**Why.**"))
refused("with the #1038 reread naming another community node group, it is refused",
        cut_1038("node group `sg-0b7d2a0cfaed6fecd`", "node group `sg-0123456789abcdef0`"))
refused("with the #1038 reread naming another private cluster group, it is refused",
        cut_1038("cluster\n  group `sg-0ca9886f5a9d4f6d3`", "cluster\n  group `sg-0123456789abcdef0`"))
refused("with the #1038 reread listing 8080 too, it is refused", cut_1038("8443, 9443, 10250", "8080, 8443, 9443, 10250"))

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for n in failures:
        print(f"  - {n}")
    sys.exit(1)
print("PASS: decisions.md records what drops the API server's dial to fake-ticket:8080 on both clusters, the #1038 "
      "reread agrees, and the root still holds the rule that would admit it.")
