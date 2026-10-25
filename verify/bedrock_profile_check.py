#!/usr/bin/env python3
# ABOUTME: Live check on one attendee cluster that BurritoBot answers through the cluster's own tagged Bedrock
# ABOUTME: application profile (#513, #562), not the untagged system profile. Spends one chat turn (~$0.003).
#
# Usage: python3 verify/bedrock_profile_check.py --context <kube-context> --profile <aws-profile> --region <r>
#            [--cluster <cluster-name>] [--namespace agent] [--event <event>]
#
# #513 was built and tested offline. What it claims only holds on a cluster, and the five claims are checked
# here in the order a call travels:
#
#   1. the cluster root made <cluster>-nova, -haiku, -sonnet, -opus and -tutor, each an ACTIVE APPLICATION
#      profile tagged project=watch-it-burn, event=<fleet/event.sh>, attendee=<cluster> and consumer=agent
#      (tutor: consumer=tutor), and each agent tier routes to the same foundation models as its system profile
#   2. every Bedrock ModelConfig the repo commits has its live .spec.model set to this cluster's ARN for its
#      tier, which is what fleet.sh pin_bedrock_profiles logs as "ModelConfig <n> now calls arn:..."
#   3. kagent rendered the bound ModelConfig's ARN into the workshop-agent config Secret, and every running
#      agent pod started after that Secret last changed, so the runtime is calling the ARN and not the id
#   4. BurritoBot answers one chat turn sent to guard-proxy inside the cluster. With 3 holding, that answer is
#      Bedrock honouring the tag-conditioned grant (aws:ResourceTag/attendee and consumer) at invoke time.
#
# model_pin_check.py holds the account-wide copies of the pinned tier to the pin, as the operator's profile. It
# never asks the cluster what the agent calls, and its Converse call is not made as the agent's role. This is
# that half. The IAM effect suite (infra/org/effect-tests.yaml, test_iam_policy_aws.py) proves the grant's
# scope, which a reply cannot: another cluster's profile and the tutor's are denied.
#
# Every kubectl call names --context and every aws call names --profile and --region; neither ambient default
# is read. Nothing here skips. Exit 0 all green, 1 something failed, 2 a tool, context or credential is missing.
import argparse
import base64
import datetime
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys

import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
RESOURCES = REPO / "gitops" / "ai-layer" / "resources.yaml"
CLUSTER_TF = REPO / "infra" / "terraform" / "aws" / "cluster" / "main.tf"
EVENT_SH = REPO / "infra" / "terraform" / "fleet" / "event.sh"
AGENT = "workshop-agent"
PROJECT = "watch-it-burn"
TUTOR = "tutor"
# The prompt browser-smoke.py sends: [[wib-probe]] marks it in the instructor console as a probe, not a student.
PROMPT = "[[wib-probe]] what proteins do you have?"
# What guard-proxy says when the agent behind it did not answer; a 200 carrying it is not an answer.
KITCHEN_DOWN = "kitchen isn't answering"


def bedrock_tiers(tf_text):
    """The cluster root's bedrock_tiers local: MODEL_TIER name -> system profile id. It names the profiles."""
    m = re.search(r"bedrock_tiers\s*=\s*\{(.*?)\}", tf_text, re.S)
    return dict(re.findall(r'^\s*([a-z0-9]+)\s*=\s*"([^"]+)"', m.group(1), re.M)) if m else {}


def committed_bedrock_configs(resources_text):
    """(name, model id) of each Bedrock ModelConfig in git, and the ModelConfig the workshop-agent is bound to."""
    docs = [d for d in yaml.safe_load_all(resources_text) if isinstance(d, dict)]
    configs = [(d["metadata"]["name"], d["spec"]["model"]) for d in docs
               if d.get("kind") == "ModelConfig" and (d.get("spec") or {}).get("provider") == "Bedrock"]
    agent = next((d for d in docs if d.get("kind") == "Agent" and d["metadata"]["name"] == AGENT), {})
    return configs, ((agent.get("spec") or {}).get("declarative") or {}).get("modelConfig")


def fleet_event(event_sh_text, environ):
    """The event the fleet tags with: WIB_EVENT from the environment, else event.sh's default, as fleet.sh reads it."""
    if environ.get("WIB_EVENT"):
        return environ["WIB_EVENT"]
    m = re.search(r'^WIB_EVENT="\$\{WIB_EVENT:-([a-z0-9-]+)\}"', event_sh_text, re.M)
    return m.group(1) if m else None


def cluster_from_context(context):
    """arn:aws:eks:<region>:<account>:cluster/<name> -> <name>; None for a context that is not an EKS ARN."""
    m = re.fullmatch(r"arn:aws[a-z-]*:eks:[a-z0-9-]+:\d{12}:cluster/(.+)", context or "")
    return m.group(1) if m else None


def judge_profiles(summaries, cluster, tiers, region):
    """list-inference-profiles --type-equals APPLICATION: the five the cluster root makes, ACTIVE in the region.

    Returns the checks and {profile name: summary} for the ones found."""
    by_name = {s.get("inferenceProfileName"): s for s in summaries}
    found, out = {}, []
    for tier in [*tiers, TUTOR]:
        name = f"{cluster}-{tier}"
        s = by_name.get(name)
        out.append((f"{name} exists in {region}", s is not None,
                    "not found: the cluster was applied before #513, or with a different name; re-apply it"))
        if s is None:
            continue
        found[name] = s
        out.append((f"{name} is an ACTIVE application profile",
                    s.get("status") == "ACTIVE" and s.get("type") == "APPLICATION",
                    f"status {s.get('status')!r}, type {s.get('type')!r}"))
    return out, found


def judge_routing(summary, system_profile, system_id):
    """The agent tier's copy routes to the foundation models its system profile routes to."""
    got = sorted(m.get("modelArn", "") for m in summary.get("models", []))
    want = sorted(m.get("modelArn", "") for m in system_profile.get("models", []))
    name = summary.get("inferenceProfileName")
    return [(f"{name} routes to the foundation models of {system_id}", bool(want) and got == want,
             f"it routes to {got}, {system_id} to {want}")]


def judge_tags(resp, name, cluster, consumer, event):
    """list-tags-for-resource: the four tags the spend splits by and the IAM grant is conditioned on."""
    tags = {t.get("key"): t.get("value") for t in resp.get("tags", [])}
    want = {"project": PROJECT, "event": event, "attendee": cluster, "consumer": consumer}
    return [(f"{name} is tagged {k}={v}", v is not None and tags.get(k) == v, f"{k} tag is {tags.get(k)!r}")
            for k, v in want.items()]


def judge_modelconfigs(live, configs, tier_of, arn_of, cluster):
    """The live .spec.model of each committed Bedrock ModelConfig is this cluster's ARN for its model's tier."""
    out = []
    for name, model in configs:
        tier = tier_of.get(model)
        if tier is None:
            out.append((f"ModelConfig {name} pins a model the cluster root makes a profile for", False,
                        f"{model} is not in bedrock_tiers in infra/terraform/aws/cluster/main.tf"))
            continue
        want = arn_of.get(f"{cluster}-{tier}")
        got = live.get(name)
        if got is None:
            detail = "the ModelConfig is not on the cluster"
        elif got == model:
            detail = (f"it still calls the system id {model}, which bills untagged: "
                      "fleet.sh pin_bedrock_profiles did not run or failed (bedrock-profiles)")
        else:
            detail = f"it calls {got!r}, the cluster's {tier} profile is {want!r}"
        out.append((f"ModelConfig {name} calls {cluster}-{tier}", want is not None and got == want, detail))
    return out


def _ts(value):
    return datetime.datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def secret_changed(secret):
    """When the Secret's content last changed: the latest managedFields write, else its creation."""
    meta = secret.get("metadata", {})
    times = [f["time"] for f in meta.get("managedFields", []) if f.get("time")] or [meta.get("creationTimestamp")]
    return max(_ts(t) for t in times if t)


def judge_rendered(secret, pods, arn, system_id):
    """kagent's config Secret carries the ARN, and the agent pods that read it at start started after it changed."""
    raw = (secret.get("data") or {}).get("config.json", "")
    try:
        rendered = base64.b64decode(raw).decode("utf-8") if raw else ""
    except ValueError:
        rendered = ""
    out = [(f"the {AGENT} config Secret names {arn}", bool(arn) and arn in rendered,
            f"config.json names {'the system id ' + system_id if system_id in rendered else 'neither'}: "
            "kagent has not re-rendered the agent since the ModelConfig changed"
            if rendered else "the Secret has no config.json")]
    running = [p for p in pods if p.get("status", {}).get("phase") == "Running"]
    out.append((f"a {AGENT} pod is Running", bool(running), f"{len(pods)} pod(s), none Running"))
    if rendered:
        changed = secret_changed(secret)
        for p in running:
            started = p.get("status", {}).get("startTime")
            name = p.get("metadata", {}).get("name")
            out.append((f"pod {name} started after its config last changed",
                        bool(started) and _ts(started) >= changed,
                        f"it started {started}, the config changed {changed.isoformat()}: it may still call the "
                        f"system id; `kubectl -n agent rollout restart deploy/{AGENT}` and run this again"))
    return out


def judge_reply(resp):
    """guard-proxy /chat: a 200 whose reply has an answer outside any <thinking> block."""
    status = resp.get("status")
    body = resp.get("body") or {}
    reply = str(body.get("reply") or body.get("error") or "")
    visible = re.sub(r"<\s*thinking\s*>.*?<\s*/\s*thinking\s*>", "", reply, flags=re.S | re.I).strip()
    return [("BurritoBot answers a chat turn through guard-proxy", status == 200,
             f"/chat returned {status}: {reply[:200]!r}"),
            ("the answer is not guard-proxy's kitchen-down reply", KITCHEN_DOWN not in reply, reply[:200]),
            ("the answer has visible text", len(visible) >= 20, f"{len(visible)} visible chars in {reply[:200]!r}")]


class ToolError(Exception):
    pass


def run(cmd, timeout=120):
    print(f"  $ {' '.join('<script>' if chr(10) in c else c for c in cmd)}")
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if proc.returncode != 0:
        raise ToolError(f"{cmd[0]} {cmd[1]}: {proc.stderr.strip() or f'exit {proc.returncode}'}")
    return proc.stdout


def aws(profile, region, *args):
    return json.loads(run(["aws", *args, "--profile", profile, "--region", region, "--output", "json"]) or "{}")


def kubectl(context, *args, timeout=120):
    return run(["kubectl", "--context", context, *args], timeout=timeout)


# Sent with `python3 -c` inside the guard-proxy container, so it needs only the standard library and reaches the
# proxy on localhost: no hostname, DNS or load balancer between this check and the agent.
CHAT_PY = """
import json, sys, urllib.error, urllib.request
req = urllib.request.Request('http://localhost:8080/chat', data=json.dumps({'prompt': sys.argv[1]}).encode(),
                             headers={'Content-Type': 'application/json'})
try:
    with urllib.request.urlopen(req, timeout=150) as r:
        status, raw = r.status, r.read()
except urllib.error.HTTPError as e:
    status, raw = e.code, e.read()
try:
    body = json.loads(raw)
except ValueError:
    body = {'error': raw.decode('utf-8', 'replace')[:300]}
print(json.dumps({'status': status, 'body': body}))
"""


def main(argv=None):
    ap = argparse.ArgumentParser(description="Check that BurritoBot answers through its tagged Bedrock profile (#562).")
    ap.add_argument("--context", required=True, help="kube-context of the attendee cluster")
    ap.add_argument("--profile", required=True, help="AWS profile of the account the cluster runs in (accen-dev)")
    ap.add_argument("--region", required=True, help="the cluster's region (us-west-2)")
    ap.add_argument("--cluster", help="cluster name; default: read from the context when it is an EKS cluster ARN")
    ap.add_argument("--namespace", default="agent")
    ap.add_argument("--event", default=fleet_event(EVENT_SH.read_text(), os.environ),
                    help="event tag the profiles must carry (default: fleet/event.sh)")
    a = ap.parse_args(argv)

    for tool in ("kubectl", "aws"):
        if shutil.which(tool) is None:
            print(f"FAIL: {tool} is not on PATH", file=sys.stderr)
            return 2
    cluster = a.cluster or cluster_from_context(a.context)
    if not cluster:
        print(f"FAIL: context {a.context!r} is not an EKS cluster ARN; pass --cluster", file=sys.stderr)
        return 2
    tiers = bedrock_tiers(CLUSTER_TF.read_text())
    tier_of = {model: tier for tier, model in tiers.items()}
    configs, bound = committed_bedrock_configs(RESOURCES.read_text())

    results = []

    def record(checks):
        for name, ok, detail in checks:
            print(f"  {'PASS' if ok else 'FAIL'}  {name}{'' if ok else '  -> ' + detail}")
            results.append(ok)

    print(f"== Bedrock application profiles on {cluster} (#513), {a.context} ==")
    record([("the cluster root names its tiers (bedrock_tiers)", bool(tiers), f"none read from {CLUSTER_TF}"),
            ("git commits Bedrock ModelConfigs", bool(configs), f"none read from {RESOURCES}"),
            (f"the {AGENT} Agent is bound to one of them", bound in dict(configs), f"it is bound to {bound!r}"),
            ("the fleet event is known", a.event is not None, f"none read from {EVENT_SH}")])
    try:
        ident = aws(a.profile, a.region, "sts", "get-caller-identity")
    except ToolError as e:
        print(f"FAIL: profile {a.profile!r} does not resolve ({e})", file=sys.stderr)
        return 2
    try:
        kubectl(a.context, "get", "--raw", "/readyz", timeout=30)
    except ToolError as e:
        print(f"FAIL: cluster for context {a.context!r} is not reachable ({e})", file=sys.stderr)
        return 2
    print(f"  account {ident.get('Account')} as {ident.get('Arn')}")

    try:
        print("\n== 1. the five profiles, routed and tagged ==")
        summaries = aws(a.profile, a.region, "bedrock", "list-inference-profiles",
                        "--type-equals", "APPLICATION").get("inferenceProfileSummaries", [])
        checks, found = judge_profiles(summaries, cluster, tiers, a.region)
        record(checks)
        for tier, system_id in tiers.items():
            s = found.get(f"{cluster}-{tier}")
            if s is not None:
                record(judge_routing(s, aws(a.profile, a.region, "bedrock", "get-inference-profile",
                                            "--inference-profile-identifier", system_id), system_id))
        for name, s in found.items():
            tags = aws(a.profile, a.region, "bedrock", "list-tags-for-resource",
                       "--resource-arn", s.get("inferenceProfileArn", ""))
            record(judge_tags(tags, name, cluster, TUTOR if name == f"{cluster}-{TUTOR}" else "agent", a.event))
        arn_of = {name: s.get("inferenceProfileArn") for name, s in found.items()}

        print("\n== 2. the live ModelConfigs call them ==")
        items = json.loads(kubectl(a.context, "-n", a.namespace, "get", "modelconfig", "-o", "json")).get("items", [])
        live = {i["metadata"]["name"]: (i.get("spec") or {}).get("model") for i in items}
        record(judge_modelconfigs(live, configs, tier_of, arn_of, cluster))

        print(f"\n== 3. the agent runtime was given {bound}'s ARN ==")
        system_id = dict(configs).get(bound, "")
        secret = json.loads(kubectl(a.context, "-n", a.namespace, "get", "secret", AGENT, "-o", "json"))
        deploy = json.loads(kubectl(a.context, "-n", a.namespace, "get", "deploy", AGENT, "-o", "json"))
        selector = ",".join(f"{k}={v}" for k, v in deploy["spec"]["selector"].get("matchLabels", {}).items())
        pods = json.loads(kubectl(a.context, "-n", a.namespace, "get", "pods", "-l", selector, "-o", "json"))
        record(judge_rendered(secret, pods.get("items", []), live.get(bound), system_id))

        print("\n== 4. BurritoBot answers through it ==")
        out = kubectl(a.context, "-n", a.namespace, "exec", "deploy/guard-proxy", "-c", "proxy", "--",
                      "python3", "-c", CHAT_PY, PROMPT, timeout=200)
        resp = json.loads(out.strip().splitlines()[-1])
        record(judge_reply(resp))
        print(f"  reply {str((resp.get('body') or {}).get('reply', ''))[:120]!r}")
    except (ToolError, ValueError, KeyError) as e:
        print(f"  FAIL  the last step failed: {e}")
        results.append(False)

    if all(results):
        print(f"\nBEDROCK PROFILE GREEN: {cluster}'s agent answers through its tagged application profile")
        return 0
    print(f"\nBEDROCK PROFILE RED: {results.count(False)} check(s) failed on {cluster}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
