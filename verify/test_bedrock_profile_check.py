# ABOUTME: Offline test of verify/bedrock_profile_check.py (#562): its judges on pass and fail answers, and whole runs
# ABOUTME: against a stand-in `aws` and `kubectl` on PATH, so the live check is known to fail on an untagged cluster.
#
# The Bedrock answers are shaped from botocore's bedrock service model and the cluster answers from the kagent
# v1alpha2 and core v1 shapes; none is captured from a cluster. The live run is test_bedrock_profile_live.py in
# the E2E suite.
import base64
import importlib.util
import json
import os
import pathlib
import subprocess
import sys
import tempfile

REPO = pathlib.Path(__file__).resolve().parents[1]
CHECK = REPO / "verify" / "bedrock_profile_check.py"
spec = importlib.util.spec_from_file_location("bedrock_profile_check", CHECK)
bpc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bpc)

failures = []


def check(name, cond, detail=""):
    print(f"  {'PASS' if cond else 'FAIL'}  {name}{('  -> ' + detail) if (detail and not cond) else ''}")
    if not cond:
        failures.append(name)


def all_ok(checks):
    return all(ok for _, ok, _ in checks)


CLUSTER = "watch-it-burn-attendee-001"
CONTEXT = f"arn:aws:eks:us-west-2:515966504359:cluster/{CLUSTER}"
EVENT = bpc.fleet_event(bpc.EVENT_SH.read_text(), {})
TIERS = bpc.bedrock_tiers(bpc.CLUSTER_TF.read_text())
CONFIGS, BOUND = bpc.committed_bedrock_configs(bpc.RESOURCES.read_text())
ARN = "arn:aws:bedrock:us-west-2:515966504359:application-inference-profile/{}"
FM = "arn:aws:bedrock:{}::foundation-model/{}"

print("== what the check reads from the repo ==")
check("bedrock_tiers names nova, haiku, sonnet and opus", sorted(TIERS) == ["haiku", "nova", "opus", "sonnet"], str(TIERS))
check("every committed Bedrock ModelConfig pins a tier the cluster root makes a profile for",
      bool(CONFIGS) and all(model in TIERS.values() for _, model in CONFIGS), str(CONFIGS))
check("the workshop-agent is bound to bedrock-nova", BOUND == "bedrock-nova", str(BOUND))
check("the fleet event is read from event.sh", bool(EVENT), str(EVENT))
check("the cluster name is read from an EKS context ARN", bpc.cluster_from_context(CONTEXT) == CLUSTER)
check("a context that is not an EKS ARN gives no cluster name", bpc.cluster_from_context("kind-dev") is None)


def models(system_id):
    fm = system_id.split(".", 1)[1]
    return [{"modelArn": FM.format(r, fm)} for r in ("us-east-1", "us-east-2", "us-west-2")]


def app(tier, system_id):
    return {"inferenceProfileName": f"{CLUSTER}-{tier}", "inferenceProfileArn": ARN.format(f"{tier}0001"),
            "status": "ACTIVE", "type": "APPLICATION", "models": models(system_id)}


TUTOR_ID = "us.anthropic.claude-sonnet-5"
APPS = [app(t, m) for t, m in TIERS.items()] + [app("tutor", TUTOR_ID)]
APP_ARNS = {a["inferenceProfileName"]: a["inferenceProfileArn"] for a in APPS}


def tags(attendee=CLUSTER, consumer="agent", event=EVENT):
    return {"tags": [{"key": "project", "value": "watch-it-burn"}, {"key": "event", "value": event},
                     {"key": "attendee", "value": attendee}, {"key": "consumer", "value": consumer}]}


print("\n== judges ==")
c, found = bpc.judge_profiles(APPS, CLUSTER, TIERS, "us-west-2")
check("the five profiles pass", all_ok(c) and len(found) == 5, str(c))
c, found = bpc.judge_profiles(APPS[:-1], CLUSTER, TIERS, "us-west-2")
check("a missing tutor profile fails", not all_ok(c) and len(found) == 4)
c, _ = bpc.judge_profiles([a for a in APPS if not a["inferenceProfileName"].endswith("-nova")]
                          + [{**APPS[0], "inferenceProfileName": "watch-it-burn-attendee-002-nova"}],
                          CLUSTER, TIERS, "us-west-2")
check("another cluster's nova profile does not stand in for this one's", not all_ok(c))
c, _ = bpc.judge_profiles([{**a, "status": "FAILED"} for a in APPS], CLUSTER, TIERS, "us-west-2")
check("a profile that is not ACTIVE fails", not all_ok(c))

nova = TIERS["nova"]
check("a copy that routes like its system profile passes",
      all_ok(bpc.judge_routing(app("nova", nova), {"models": models(nova)}, nova)))
check("a copy that routes elsewhere fails",
      not all_ok(bpc.judge_routing(app("nova", nova), {"models": models(TIERS["opus"])}, nova)))
check("a system profile with no models fails, it does not match an empty copy",
      not all_ok(bpc.judge_routing({**app("nova", nova), "models": []}, {"models": []}, nova)))

check("the four tags pass", all_ok(bpc.judge_tags(tags(), "p", CLUSTER, "agent", EVENT)))
check("the tutor's tags pass as consumer=tutor", all_ok(bpc.judge_tags(tags(consumer="tutor"), "p", CLUSTER, "tutor", EVENT)))
check("another attendee's tag fails", not all_ok(bpc.judge_tags(tags(attendee="watch-it-burn-attendee-002"), "p", CLUSTER, "agent", EVENT)))
check("an agent profile tagged consumer=tutor fails", not all_ok(bpc.judge_tags(tags(consumer="tutor"), "p", CLUSTER, "agent", EVENT)))
check("a missing event tag fails", not all_ok(bpc.judge_tags({"tags": tags()["tags"][:1]}, "p", CLUSTER, "agent", EVENT)))
check("an unknown event fails, it does not match a missing tag", not all_ok(bpc.judge_tags({"tags": []}, "p", CLUSTER, "agent", None)))

tier_of = {m: t for t, m in TIERS.items()}
pinned = {name: APP_ARNS[f"{CLUSTER}-{tier_of[model]}"] for name, model in CONFIGS}
check("ModelConfigs on their cluster's ARNs pass", all_ok(bpc.judge_modelconfigs(pinned, CONFIGS, tier_of, APP_ARNS, CLUSTER)))
c = bpc.judge_modelconfigs({**pinned, "bedrock-nova": nova}, CONFIGS, tier_of, APP_ARNS, CLUSTER)
check("a ModelConfig still on the system id fails, naming pin_bedrock_profiles",
      not all_ok(c) and any("pin_bedrock_profiles" in d for _, ok, d in c if not ok))
check("a ModelConfig on another tier's ARN fails",
      not all_ok(bpc.judge_modelconfigs({**pinned, "bedrock-nova": APP_ARNS[f"{CLUSTER}-opus"]}, CONFIGS, tier_of, APP_ARNS, CLUSTER)))
check("a ModelConfig missing from the cluster fails",
      not all_ok(bpc.judge_modelconfigs({}, CONFIGS, tier_of, APP_ARNS, CLUSTER)))
check("a committed model with no tier fails",
      not all_ok(bpc.judge_modelconfigs(pinned, CONFIGS + [("bedrock-new", "us.new.model")], tier_of, APP_ARNS, CLUSTER)))

NOVA_ARN = APP_ARNS[f"{CLUSTER}-nova"]


def secret(model, at="2026-11-10T09:00:00Z"):
    cfg = json.dumps({"model": {"type": "bedrock", "model": model, "region": "us-west-2"}})
    return {"metadata": {"creationTimestamp": "2026-11-10T08:00:00Z",
                         "managedFields": [{"manager": "kagent", "time": "2026-11-10T08:00:00Z"},
                                           {"manager": "kagent", "time": at}]},
            "data": {"config.json": base64.b64encode(cfg.encode()).decode()}}


def pod(started="2026-11-10T09:01:00Z", phase="Running"):
    return {"metadata": {"name": "workshop-agent-abc"}, "status": {"phase": phase, "startTime": started}}


check("an ARN in the config and a pod started after it passes",
      all_ok(bpc.judge_rendered(secret(NOVA_ARN), [pod()], NOVA_ARN, nova)))
check("a config still naming the system id fails", not all_ok(bpc.judge_rendered(secret(nova), [pod()], NOVA_ARN, nova)))
c = bpc.judge_rendered(secret(NOVA_ARN), [pod("2026-11-10T08:30:00Z")], NOVA_ARN, nova)
check("a pod started before the config changed fails, naming the restart",
      not all_ok(c) and any("rollout restart" in d for _, ok, d in c if not ok))
check("no Running pod fails", not all_ok(bpc.judge_rendered(secret(NOVA_ARN), [pod(phase="Pending")], NOVA_ARN, nova)))
check("no ARN on the live ModelConfig fails", not all_ok(bpc.judge_rendered(secret(nova), [pod()], None, nova)))
check("a Secret with no config.json fails", not all_ok(bpc.judge_rendered({"metadata": {}}, [pod()], NOVA_ARN, nova)))

ANSWER = "<thinking>they asked</thinking>We have carnitas, chicken tinga, barbacoa and sofritas today."
check("a 200 with an answer passes", all_ok(bpc.judge_reply({"status": 200, "body": {"reply": ANSWER}})))
check("a 200 with only thinking fails", not all_ok(bpc.judge_reply({"status": 200, "body": {"reply": "<thinking>hm</thinking>"}})))
check("the kitchen-down reply fails",
      not all_ok(bpc.judge_reply({"status": 200, "body": {"reply": "Sorry, the kitchen isn't answering right now, try again."}})))
check("a 502 fails", not all_ok(bpc.judge_reply({"status": 502, "body": {"error": "AccessDeniedException"}})))

# Whole runs with a stand-in aws and kubectl, so the plumbing (argv, --context, --profile and --region on every
# call, which ARN each read names, exit codes) is exercised and not just the judges. Each stand-in logs its calls.
FAKE = r'''#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
tool = os.path.basename(sys.argv[0])
with open(os.environ["FAKE_LOG"], "a") as f:
    f.write(json.dumps([tool, *args]) + "\n")
answers = json.loads(open(os.environ["FAKE_ANSWERS"]).read())[tool]
if tool == "kubectl":
    rest = args[2:] if args[:1] == ["--context"] else args
    key = " ".join(a for a in rest if a in ("--raw", "modelconfig", "secret", "deploy", "pods", "exec"))
else:
    key = " ".join(args[:2])
    for flag in ("--resource-arn", "--inference-profile-identifier"):
        if flag in args and key + " " + args[args.index(flag) + 1] in answers:
            key += " " + args[args.index(flag) + 1]
if key not in answers:
    sys.stderr.write(tool + " stand-in: no answer for " + key + "\n")
    sys.exit(1)
a = answers[key]
print(a if isinstance(a, str) else json.dumps(a))
'''


def run_with(aws_answers, kube_answers, extra=()):
    with tempfile.TemporaryDirectory() as d:
        d = pathlib.Path(d)
        for tool in ("aws", "kubectl"):
            (d / tool).write_text(FAKE)
            (d / tool).chmod(0o755)
        (d / "answers.json").write_text(json.dumps({"aws": aws_answers, "kubectl": kube_answers}))
        log = d / "calls.log"
        env = {**os.environ, "PATH": f"{d}{os.pathsep}{os.environ['PATH']}",
               "FAKE_LOG": str(log), "FAKE_ANSWERS": str(d / "answers.json")}
        env.pop("WIB_EVENT", None)  # the stand-in tags carry event.sh's event; an operator's override is not this run's
        p = subprocess.run([sys.executable, str(CHECK), "--context", CONTEXT, "--profile", "delivery",
                            "--region", "us-west-2", *extra], capture_output=True, text=True, env=env, timeout=120)
        calls = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
        return p, calls


GOOD_AWS = {
    "sts get-caller-identity": {"Account": "515966504359", "Arn": "arn:aws:iam::515966504359:user/x"},
    "bedrock list-inference-profiles": {"inferenceProfileSummaries": APPS},
    **{f"bedrock get-inference-profile {m}": {"inferenceProfileId": m, "models": models(m)} for m in TIERS.values()},
    **{f"bedrock list-tags-for-resource {a['inferenceProfileArn']}":
       tags(consumer="tutor" if a["inferenceProfileName"].endswith("-tutor") else "agent") for a in APPS},
}
LIVE = {"items": [{"metadata": {"name": n}, "spec": {"provider": "Bedrock", "model": m}} for n, m in pinned.items()]}
GOOD_KUBE = {
    "--raw": "ok",
    "modelconfig": LIVE,
    "secret": secret(NOVA_ARN),
    "deploy": {"spec": {"selector": {"matchLabels": {"app": "workshop-agent"}}}},
    "pods": {"items": [pod()]},
    "exec": {"status": 200, "body": {"reply": ANSWER}},
}

print("\n== whole run, stand-in aws and kubectl ==")
p, calls = run_with(GOOD_AWS, GOOD_KUBE)
check("a cluster calling its tagged profiles exits 0 and says GREEN",
      p.returncode == 0 and "BEDROCK PROFILE GREEN" in p.stdout, f"exit {p.returncode}\n{p.stdout}\n{p.stderr}")
kube = [c for c in calls if c[0] == "kubectl"]
check("every kubectl call names the context it was given",
      bool(kube) and all(c[1:3] == ["--context", CONTEXT] for c in kube), str(kube))
check("every aws call names --profile and --region",
      all("--profile" in c and "--region" in c for c in calls if c[0] == "aws"), str(calls))
tag_arns = sorted(c[c.index("--resource-arn") + 1] for c in calls if c[1:3] == ["bedrock", "list-tags-for-resource"])
check("the tags are read on all five of the cluster's profiles", tag_arns == sorted(APP_ARNS.values()), str(tag_arns))
chat = [c for c in kube if "exec" in c]
check("one chat turn goes to guard-proxy's proxy container on localhost",
      len(chat) == 1 and "deploy/guard-proxy" in chat[0] and chat[0][chat[0].index("-c") + 1] == "proxy"
      and bpc.PROMPT in chat[0], str(chat))
check("the agent pods are found by the Deployment's own selector",
      any("pods" in c and "app=workshop-agent" in c for c in kube), str(kube))

p, _ = run_with(GOOD_AWS, {**GOOD_KUBE, "modelconfig": {"items": [
    {"metadata": {"name": n}, "spec": {"model": m}} for n, m in CONFIGS]}, "secret": secret(nova)})
check("a cluster still on the system ids exits 1 and says RED",
      p.returncode == 1 and "BEDROCK PROFILE RED" in p.stderr, f"exit {p.returncode}\n{p.stdout}")
p, _ = run_with({**GOOD_AWS, "bedrock list-inference-profiles": {"inferenceProfileSummaries": []}}, GOOD_KUBE)
check("a cluster applied before #513, with no profiles, exits 1", p.returncode == 1, f"exit {p.returncode}")
p, _ = run_with(GOOD_AWS, {**GOOD_KUBE, "exec": {"status": 502, "body": {"error": "AccessDeniedException"}}})
check("an agent that does not answer exits 1", p.returncode == 1, f"exit {p.returncode}")
p, _ = run_with(GOOD_AWS, {k: v for k, v in GOOD_KUBE.items() if k != "exec"})
check("a chat turn that cannot be sent exits 1", p.returncode == 1, f"exit {p.returncode}")
p, _ = run_with({k: v for k, v in GOOD_AWS.items() if k != "sts get-caller-identity"}, GOOD_KUBE)
check("a profile with no credentials exits 2", p.returncode == 2, f"exit {p.returncode}")
p, _ = run_with(GOOD_AWS, {k: v for k, v in GOOD_KUBE.items() if k != "--raw"})
check("an unreachable cluster exits 2", p.returncode == 2, f"exit {p.returncode}")
p, calls = run_with(GOOD_AWS, GOOD_KUBE, ["--context", "kind-dev"])
check("a context that names no cluster exits 2 before any call", p.returncode == 2 and not calls,
      f"exit {p.returncode}, {calls}")

if failures:
    print(f"\nFAILED: {len(failures)} check(s)")
    sys.exit(1)
print("\nAll Bedrock profile check tests passed.")
