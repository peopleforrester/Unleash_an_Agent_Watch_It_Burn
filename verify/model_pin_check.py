#!/usr/bin/env python3
# ABOUTME: Live check that the model the workshop-agent is pinned to answers in the delivery account and region,
# ABOUTME: stays Active through the delivery date, and has on-demand quota for a ballroom (#453). Read-only, ~$0.0001.
#
# Usage: python3 verify/model_pin_check.py --profile <aws-profile> --region <delivery-region> [--through YYYY-MM-DD]
#
# Run it at the Night Before step (facilitation/kubecon-na-2026-run-of-show.md). The KubeCon roster lives in
# WIB_DEFAULT_ACCOUNT (accen-dev) in us-west-2, so from the repo root that is:
#   python3 verify/model_pin_check.py --profile accen-dev --region us-west-2
#
# Why this exists. The BurritoBot repo pinned a model its cloud no longer listed in the region, and found out
# when nobody could call it (BurritoBot#69, question 143). A pin that went stale on stage ends the demo, and a
# cost counter pricing a different model than the one answering undercuts the denial-of-wallet point. So the
# pin is read from the manifest the cluster runs (gitops/ai-layer/resources.yaml), never typed in here, and
# every claim about it is checked against the live Bedrock API as the delivery account:
#
#   1. the ModelConfig's bedrock.region is the delivery region, and guard-proxy's MODEL_TIER prices that model
#   2. the inference profile exists and is ACTIVE in the delivery region
#   3. every foundation model the profile routes to is ACTIVE, with no legacy, extended-access or end-of-life
#      time on or before --through (a Legacy model can lose access after 15 days of inactivity)
#   4. one tiny Converse call through the pinned id returns text: this is "the model answers"
#   5. the cross-region requests- and tokens-per-minute quotas cover the room's ceiling, which is guard-proxy's
#      RATE_LIMIT_RPM turns a minute, read from the same manifest
#   6. the clusters' tagged application profiles for the pin (#513) route to the same foundation models, are
#      ACTIVE, carry project and the event from infra/terraform/fleet/event.sh, and answer one Converse call
#
# The pin is still the system profile id in the manifest, and so still the underlying model. What a cluster's
# agent actually calls is its own application inference profile, a tagged copy of that system profile made by
# the cluster root (aws_bedrock_inference_profile.agent, named <cluster>-<MODEL_TIER>) and set on the live
# ModelConfig by fleet.sh pin_bedrock_profiles, because a system profile cannot carry tags and its spend bills
# untagged. Step 6 holds those copies to the pin, so they need the clusters up: run it after the bring-up.
#
# Every aws call names --profile and --region; the ambient AWS default is never used. Nothing here skips: an
# unreadable answer is a failure with the command printed, because an unreadable quota is not a passing quota.
# Exit 0 all green, 1 something failed, 2 the aws CLI or the profile's credentials are missing.
import argparse
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
AGENT_MANIFEST = REPO / "gitops" / "workshop-agent" / "agent.yaml"
PROXY = REPO / "gitops" / "ai-layer" / "guard-proxy" / "proxy.py"
EVENT_SH = REPO / "infra" / "terraform" / "fleet" / "event.sh"

# KubeCon NA 2026 breakout, Sessionize 1249553. The model has to be Active through the end of this day. The
# date comes from conference-knowledge (events/registry.yaml, kubecon-na-2026 schedule), which is the record:
# if the slot moves there, change it here.
DELIVERY_DATE = "2026-11-12"
# What one audience turn costs Bedrock. A turn that calls a tool is two model calls (choose the tool, then
# answer), and C6 on Nova meters ~3,500 tokens a turn (challenges/PROMPT-CATALOG.md). Both are flags so a
# measured number from #450's live run can replace them.
CALLS_PER_TURN = 2
TOKENS_PER_TURN = 3500
# The geo prefixes Bedrock puts on a cross-region inference profile id.
PROFILE_PREFIXES = ("us.", "eu.", "apac.", "global.")


def committed_manifests() -> str:
    """ai-layer's bundle and the Agent's, one YAML stream: the Agent has its own Application since #707."""
    return RESOURCES.read_text() + "\n---\n" + AGENT_MANIFEST.read_text()


def pinned(resources_text):
    """The pin as the cluster runs it: the Agent's ModelConfig, its model and region, and the proxy's env."""
    docs = [d for d in yaml.safe_load_all(resources_text) if isinstance(d, dict)]
    agent = next(d for d in docs if d.get("kind") == "Agent" and d["metadata"]["name"] == "workshop-agent")
    config_name = agent["spec"]["declarative"]["modelConfig"]
    config = next(d for d in docs if d.get("kind") == "ModelConfig" and d["metadata"]["name"] == config_name)
    proxy = next(d for d in docs if d.get("kind") == "Deployment" and d["metadata"]["name"] == "guard-proxy")
    env = {e["name"]: e.get("value") for c in proxy["spec"]["template"]["spec"]["containers"]
           for e in c.get("env", []) if c["name"] == "proxy"}
    return {
        "model_config": config_name,
        "provider": config["spec"]["provider"],
        "model_id": config["spec"]["model"],
        "region": config["spec"].get("bedrock", {}).get("region"),
        "model_tier": (env.get("MODEL_TIER") or "").lower(),
        "rate_limit_rpm": int(env.get("RATE_LIMIT_RPM") or 0),
    }


def is_profile(model_id):
    return model_id.startswith(PROFILE_PREFIXES)


def judge_pin(pin, delivery_region, tier_to_model_id):
    """Offline half: the manifest pins a Bedrock model in the delivery region and the proxy prices that model."""
    out = []
    out.append(("the agent's ModelConfig is a Bedrock one", pin["provider"] == "Bedrock",
                f"{pin['model_config']} has provider {pin['provider']!r}"))
    out.append((f"the ModelConfig calls Bedrock in the delivery region {delivery_region}",
                pin["region"] == delivery_region,
                f"{pin['model_config']} has bedrock.region {pin['region']!r}"))
    out.append((f"guard-proxy MODEL_TIER {pin['model_tier']!r} prices {pin['model_id']}",
                tier_to_model_id.get(pin["model_tier"]) == pin["model_id"],
                f"proxy maps {pin['model_tier']!r} to {tier_to_model_id.get(pin['model_tier'])!r}"))
    out.append(("guard-proxy RATE_LIMIT_RPM sets the room's ceiling", pin["rate_limit_rpm"] > 0,
                "RATE_LIMIT_RPM is 0 or unset, so nothing bounds what the room can send"))
    return out


def judge_profile(resp, model_id, region):
    """get-inference-profile: the pinned id is a live profile, and the foundation models it routes to."""
    status = resp.get("status")
    arns = [m.get("modelArn", "") for m in resp.get("models", [])]
    return [
        (f"inference profile {model_id} is ACTIVE in {region}", status == "ACTIVE",
         f"status is {status!r}"),
        (f"{model_id} routes to at least one foundation model", bool(arns), "the profile lists no models"),
    ], arns


def fleet_event(event_sh_text, environ):
    """The event the fleet tags with: WIB_EVENT from the environment, else event.sh's default, as fleet.sh reads it."""
    if environ.get("WIB_EVENT"):
        return environ["WIB_EVENT"]
    m = re.search(r'^WIB_EVENT="\$\{WIB_EVENT:-([a-z0-9-]+)\}"', event_sh_text, re.M)
    return m.group(1) if m else None


def cluster_profiles(summaries, tier):
    """The clusters' application profiles for this MODEL_TIER: the cluster root names them <cluster>-<tier>."""
    pattern = re.compile(rf"^watch-it-burn-.+-{re.escape(tier)}$")
    return [s for s in summaries if pattern.match(s.get("inferenceProfileName", ""))]


def judge_app_profiles(profiles, tier, pinned_arns, region):
    """list-inference-profiles --type-equals APPLICATION: each cluster's copy routes where the pin routes."""
    out = [(f"at least one cluster has a tagged application profile for {tier} in {region}", bool(profiles),
            f"no profile named watch-it-burn-*-{tier}: the clusters are not up, or were applied before #513")]
    want = sorted(pinned_arns)
    for s in profiles:
        name = s.get("inferenceProfileName")
        got = sorted(m.get("modelArn", "") for m in s.get("models", []))
        out.append((f"{name} is an ACTIVE application profile",
                    s.get("status") == "ACTIVE" and s.get("type") == "APPLICATION",
                    f"status {s.get('status')!r}, type {s.get('type')!r}"))
        out.append((f"{name} routes to the pinned model's foundation models", got == want,
                    f"it routes to {got}, the pin to {want}"))
    return out


def judge_tags(resp, name, event):
    """list-tags-for-resource: the spend carries project and this event, which is the point of the copy."""
    tags = {t.get("key"): t.get("value") for t in resp.get("tags", [])}
    return [(f"{name} is tagged project=watch-it-burn", tags.get("project") == "watch-it-burn",
             f"project tag is {tags.get('project')!r}"),
            (f"{name} is tagged event={event}", event is not None and tags.get("event") == event,
             f"event tag is {tags.get('event')!r}")]


def fm_of(arn):
    """arn:aws:bedrock:us-east-1::foundation-model/amazon.nova-pro-v1:0 -> ('us-east-1', 'amazon.nova-pro-v1:0')."""
    parts = arn.split(":", 5)
    return parts[3], parts[5].split("/", 1)[1]


def _day(ts):
    return datetime.date.fromisoformat(str(ts)[:10])


def judge_lifecycle(resp, where, through):
    """get-foundation-model: Active, and no legacy, extended-access or EOL time on or before `through`."""
    life = resp.get("modelDetails", {}).get("modelLifecycle", {})
    out = [(f"{where} is ACTIVE", life.get("status") == "ACTIVE", f"modelLifecycle.status is {life.get('status')!r}")]
    for field, meaning in (("legacyTime", "goes Legacy"), ("publicExtendedAccessTime", "enters paid extended access"),
                           ("endOfLifeTime", "reaches end of life")):
        when = life.get(field)
        out.append((f"{where} has no {field} on or before {through}",
                    when is None or _day(when) > through,
                    f"it {meaning} on {when}"))
    return out


def judge_converse(resp):
    """converse: the model answered with text. An empty content list is what a dead pin looks like."""
    texts = [c.get("text", "") for c in resp.get("output", {}).get("message", {}).get("content", [])]
    reply = "".join(texts).strip()
    return [("the pinned model answers a Converse call", bool(reply),
             f"stopReason {resp.get('stopReason')!r}, no text in the reply")], reply


def find_quota(quotas, kind, unit, model_name):
    """The quota named '<kind> model inference <unit> per minute for <model name>', or None.

    Matched on the full name, never a substring: 'for Amazon Nova Pro' must not pick up a quota for a
    'Nova Pro Latency Optimized' or a 'Nova 2.0 Pro'."""
    want = f"{kind} model inference {unit} per minute for {model_name}".lower()
    return next((q for q in quotas if q.get("QuotaName", "").strip().lower() == want), None)


def judge_quotas(applied, defaults, cross_region, model_name, need_rpm, need_tpm):
    """Applied value where AWS reports one, else the AWS default (ListServiceQuotas omits unchanged quotas)."""
    kind = "Cross-region" if cross_region else "On-demand"
    out, seen = [], {}
    for unit, need in (("requests", need_rpm), ("tokens", need_tpm)):
        name = f"{kind} model inference {unit} per minute for {model_name}"
        q = find_quota(applied, kind, unit, model_name)
        source = "applied"
        if q is None:
            q = find_quota(defaults, kind, unit, model_name)
            source = "AWS default"
        if q is None:
            near = sorted({x.get("QuotaName", "") for x in applied + defaults
                           if model_name.lower() in x.get("QuotaName", "").lower()})
            out.append((f"quota '{name}' is readable", False,
                        f"not found; quotas naming {model_name}: {near or 'none'}"))
            continue
        have = int(q.get("Value") or 0)
        seen[unit] = (q.get("QuotaCode"), have, source)
        out.append((f"{name} ({q.get('QuotaCode')}, {source}) is {have:,}, need {need:,}", have >= need,
                    f"{have:,} < {need:,}: request an increase in Service Quotas before the day"))
    return out, seen


class AwsError(Exception):
    pass


def aws(profile, region, *args):
    """One read through the aws CLI, as `profile` in `region`, decoded from JSON."""
    cmd = ["aws", *args, "--profile", profile, "--region", region, "--output", "json"]
    print(f"  $ {' '.join(cmd)}")
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if proc.returncode != 0:
        raise AwsError(proc.stderr.strip() or f"exit {proc.returncode}")
    return json.loads(proc.stdout or "{}")


def load_tier_map():
    import importlib.util
    spec = importlib.util.spec_from_file_location("guard_proxy_pin", PROXY)
    proxy = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(proxy)
    return proxy._TIER_TO_MODEL_ID


def main(argv=None):
    ap = argparse.ArgumentParser(description="Check the workshop-agent's model pin against live Bedrock (#453).")
    ap.add_argument("--profile", required=True, help="AWS profile of the delivery account (KubeCon: accen-dev)")
    ap.add_argument("--region", required=True, help="delivery region (KubeCon: us-west-2)")
    ap.add_argument("--through", default=DELIVERY_DATE, help=f"must stay Active through this day (default {DELIVERY_DATE})")
    ap.add_argument("--calls-per-turn", type=int, default=CALLS_PER_TURN)
    ap.add_argument("--tokens-per-turn", type=int, default=TOKENS_PER_TURN)
    ap.add_argument("--event", default=fleet_event(EVENT_SH.read_text(), os.environ),
                    help="event tag the clusters' application profiles must carry (default: fleet/event.sh)")
    a = ap.parse_args(argv)
    through = datetime.date.fromisoformat(a.through)

    results = []

    def record(checks):
        for name, ok, detail in checks:
            print(f"  {'PASS' if ok else 'FAIL'}  {name}{'' if ok else '  -> ' + detail}")
            results.append(ok)

    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    pin = pinned(committed_manifests())
    print(f"== model pin check, {now} ==")
    print(f"  pin: workshop-agent -> {pin['model_config']} -> {pin['model_id']} in {pin['region']}, "
          f"MODEL_TIER={pin['model_tier']}, RATE_LIMIT_RPM={pin['rate_limit_rpm']}")
    record(judge_pin(pin, a.region, load_tier_map()))

    if shutil.which("aws") is None:
        print("FAIL: the aws CLI is not on PATH; the pin cannot be checked against Bedrock", file=sys.stderr)
        return 2
    try:
        ident = aws(a.profile, a.region, "sts", "get-caller-identity")
    except AwsError as e:
        print(f"FAIL: profile {a.profile!r} does not resolve ({e})", file=sys.stderr)
        return 2
    print(f"  account {ident.get('Account')} as {ident.get('Arn')}")

    model_id = pin["model_id"]
    try:
        print("\n== inference profile ==")
        if is_profile(model_id):
            prof = aws(a.profile, a.region, "bedrock", "get-inference-profile",
                       "--inference-profile-identifier", model_id)
            checks, arns = judge_profile(prof, model_id, a.region)
            record(checks)
        else:
            arns = [f"arn:aws:bedrock:{a.region}::foundation-model/{model_id}"]
            print(f"  {model_id} is an in-Region model id, not a profile")

        print(f"\n== lifecycle through {through} ==")
        model_name = None
        for arn in arns:
            fm_region, fm_id = fm_of(arn)
            fm = aws(a.profile, fm_region, "bedrock", "get-foundation-model", "--model-identifier", fm_id)
            details = fm.get("modelDetails", {})
            model_name = model_name or f"{details.get('providerName', '')} {details.get('modelName', '')}".strip()
            record(judge_lifecycle(fm, f"{fm_id} in {fm_region}", through))

        print("\n== the model answers ==")
        conv = aws(a.profile, a.region, "bedrock-runtime", "converse", "--model-id", model_id,
                   "--messages", json.dumps([{"role": "user", "content": [{"text": "Reply with the one word: ready"}]}]),
                   "--inference-config", json.dumps({"maxTokens": 16}))
        checks, reply = judge_converse(conv)
        record(checks)
        usage = conv.get("usage", {})
        print(f"  reply {reply[:60]!r}, {usage.get('inputTokens')} in / {usage.get('outputTokens')} out, "
              f"{conv.get('metrics', {}).get('latencyMs')} ms")

        print("\n== the clusters' tagged application profiles (#513) ==")
        summaries = aws(a.profile, a.region, "bedrock", "list-inference-profiles",
                        "--type-equals", "APPLICATION").get("inferenceProfileSummaries", [])
        profiles = cluster_profiles(summaries, pin["model_tier"])
        record(judge_app_profiles(profiles, pin["model_tier"], arns, a.region))
        for s in profiles:
            tags = aws(a.profile, a.region, "bedrock", "list-tags-for-resource",
                       "--resource-arn", s.get("inferenceProfileArn", ""))
            record(judge_tags(tags, s.get("inferenceProfileName"), a.event))
        if profiles:
            via = profiles[0]
            conv = aws(a.profile, a.region, "bedrock-runtime", "converse", "--model-id", via["inferenceProfileArn"],
                       "--messages", json.dumps([{"role": "user", "content": [{"text": "Reply with the one word: ready"}]}]),
                       "--inference-config", json.dumps({"maxTokens": 16}))
            checks, reply = judge_converse(conv)
            record([(f"{name} through {via['inferenceProfileName']}", ok, detail) for name, ok, detail in checks])

        print("\n== on-demand quota for the room ==")
        turns = pin["rate_limit_rpm"]
        need_rpm, need_tpm = turns * a.calls_per_turn, turns * a.tokens_per_turn
        print(f"  room ceiling {turns} turns/min (RATE_LIMIT_RPM) x {a.calls_per_turn} calls, "
              f"x {a.tokens_per_turn:,} tokens")
        applied = aws(a.profile, a.region, "service-quotas", "list-service-quotas",
                      "--service-code", "bedrock").get("Quotas", [])
        defaults = aws(a.profile, a.region, "service-quotas", "list-aws-default-service-quotas",
                       "--service-code", "bedrock").get("Quotas", [])
        checks, _ = judge_quotas(applied, defaults, is_profile(model_id), model_name or model_id, need_rpm, need_tpm)
        record(checks)
    except AwsError as e:
        print(f"  FAIL  the last command failed: {e}")
        results.append(False)

    if all(results):
        print(f"\nMODEL PIN GREEN: {model_id} answers as {a.profile} ({ident.get('Account')}) in {a.region}, "
              f"Active through {through}, priced as {pin['model_tier']}. Checked {now}.")
        return 0
    print(f"\nMODEL PIN FAILED: {results.count(False)} check(s). Do not go on stage on this pin.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
