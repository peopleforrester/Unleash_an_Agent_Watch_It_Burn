# ABOUTME: Offline test of verify/model_pin_check.py (#453): its judges on pass and fail answers, and one whole
# ABOUTME: run against a stand-in `aws` on PATH, so the live check is known to fail when the pin is bad.
#
# The Bedrock answers below are shaped from botocore's bedrock and bedrock-runtime service models (field names
# and the iso8601 timestamps), not captured from the delivery account; the live run is model_pin_check.py
# itself, at the Night Before step, and test_model_pin_live.py in the E2E suite.
import datetime
import importlib.util
import json
import os
import pathlib
import subprocess
import sys
import tempfile

REPO = pathlib.Path(__file__).resolve().parents[1]
CHECK = REPO / "verify" / "model_pin_check.py"
spec = importlib.util.spec_from_file_location("model_pin_check", CHECK)
mpc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mpc)

failures = []


def check(name, cond, detail=""):
    print(f"  {'PASS' if cond else 'FAIL'}  {name}{('  -> ' + detail) if (detail and not cond) else ''}")
    if not cond:
        failures.append(name)


def all_ok(checks):
    return all(ok for _, ok, _ in checks)


THROUGH = datetime.date.fromisoformat(mpc.DELIVERY_DATE)
FM_ARN = "arn:aws:bedrock:{}::foundation-model/amazon.nova-pro-v1:0"
PROFILE_OK = {
    "inferenceProfileId": "us.amazon.nova-pro-v1:0", "inferenceProfileName": "US Nova Pro",
    "inferenceProfileArn": "arn:aws:bedrock:us-west-2:515966504359:inference-profile/us.amazon.nova-pro-v1:0",
    "status": "ACTIVE", "type": "SYSTEM_DEFINED",
    "models": [{"modelArn": FM_ARN.format(r)} for r in ("us-east-1", "us-east-2", "us-west-2")],
}


def fm(status="ACTIVE", **times):
    life = {"status": status, "startOfLifeTime": "2024-12-03T00:00:00+00:00", **times}
    return {"modelDetails": {"modelId": "amazon.nova-pro-v1:0", "providerName": "Amazon", "modelName": "Nova Pro",
                             "modelLifecycle": life}}


CONVERSE_OK = {"output": {"message": {"role": "assistant", "content": [{"text": "ready"}]}},
               "stopReason": "end_turn", "usage": {"inputTokens": 9, "outputTokens": 2, "totalTokens": 11},
               "metrics": {"latencyMs": 412}}
QUOTAS = [
    {"QuotaName": "Cross-region model inference requests per minute for Amazon Nova Pro", "QuotaCode": "L-AAAA0001", "Value": 500.0},
    {"QuotaName": "Cross-region model inference tokens per minute for Amazon Nova Pro", "QuotaCode": "L-AAAA0002", "Value": 2000000.0},
    {"QuotaName": "Cross-region model inference requests per minute for Amazon Nova Pro Latency Optimized", "QuotaCode": "L-AAAA0003", "Value": 1.0},
]

print("== the pin as the manifest declares it ==")
pin = mpc.pinned(mpc.committed_manifests())
tiers = mpc.load_tier_map()
check("the real manifest's pin passes the offline judge", all_ok(mpc.judge_pin(pin, "us-west-2", tiers)),
      str(mpc.judge_pin(pin, "us-west-2", tiers)))
check("the pin is a cross-region inference profile", mpc.is_profile(pin["model_id"]), pin["model_id"])
check("a different delivery region fails the pin",
      not all_ok(mpc.judge_pin(pin, "us-east-1", tiers)))
check("MODEL_TIER pricing another model fails the pin",
      not all_ok(mpc.judge_pin({**pin, "model_tier": "sonnet"}, "us-west-2", tiers)))
check("an unset RATE_LIMIT_RPM fails the pin",
      not all_ok(mpc.judge_pin({**pin, "rate_limit_rpm": 0}, "us-west-2", tiers)))

print("\n== inference profile ==")
c, arns = mpc.judge_profile(PROFILE_OK, "us.amazon.nova-pro-v1:0", "us-west-2")
check("an ACTIVE profile with models passes", all_ok(c))
check("its foundation models are read from the profile", len(arns) == 3 and mpc.fm_of(arns[0]) == ("us-east-1", "amazon.nova-pro-v1:0"),
      str(arns))
check("a profile that is not ACTIVE fails",
      not all_ok(mpc.judge_profile({**PROFILE_OK, "status": "INACTIVE"}, "x", "us-west-2")[0]))
check("a profile with no models fails",
      not all_ok(mpc.judge_profile({**PROFILE_OK, "models": []}, "x", "us-west-2")[0]))

print("\n== the clusters' tagged application profiles (#513) ==")
APP_ARN = "arn:aws:bedrock:us-west-2:515966504359:application-inference-profile/{}"
PINNED_ARNS = [m["modelArn"] for m in PROFILE_OK["models"]]


def app_profile(name, pid, **over):
    return {"inferenceProfileName": name, "inferenceProfileArn": APP_ARN.format(pid), "inferenceProfileId": pid,
            "status": "ACTIVE", "type": "APPLICATION", "models": [{"modelArn": a} for a in reversed(PINNED_ARNS)],
            **over}


APPS = {"inferenceProfileSummaries": [
    app_profile("watch-it-burn-attendee-001-nova", "nova0001"),
    app_profile("watch-it-burn-private-nova", "nova0002"),
    app_profile("watch-it-burn-attendee-001-haiku", "haiku001"),
    app_profile("packt-cluster-nova", "packt001"),
]}
TAGS_OK = {"tags": [{"key": "project", "value": "watch-it-burn"}, {"key": "event", "value": "kubecon-na-2026"},
                    {"key": "attendee", "value": "watch-it-burn-attendee-001"}, {"key": "consumer", "value": "agent"}]}
picked = mpc.cluster_profiles(APPS["inferenceProfileSummaries"], "nova")
check("the clusters' profiles for the pinned tier are picked, by the cluster root's <cluster>-<tier> name",
      [s["inferenceProfileName"] for s in picked] == ["watch-it-burn-attendee-001-nova", "watch-it-burn-private-nova"],
      str(picked))
check("copies that route where the pin routes pass, in any order",
      all_ok(mpc.judge_app_profiles(picked, "nova", PINNED_ARNS, "us-west-2")))
check("no cluster profile at all fails: the agent would be calling an untagged profile, or none",
      not all_ok(mpc.judge_app_profiles([], "nova", PINNED_ARNS, "us-west-2")))
check("a copy that routes to another model fails",
      not all_ok(mpc.judge_app_profiles([app_profile("watch-it-burn-x-nova", "x", models=[
          {"modelArn": "arn:aws:bedrock:us-east-1::foundation-model/amazon.nova-lite-v1:0"}])], "nova", PINNED_ARNS, "us-west-2")))
check("a copy that is not ACTIVE fails",
      not all_ok(mpc.judge_app_profiles([app_profile("watch-it-burn-x-nova", "x", status="INACTIVE")],
                                        "nova", PINNED_ARNS, "us-west-2")))
check("project and the fleet's event pass", all_ok(mpc.judge_tags(TAGS_OK, "p", "kubecon-na-2026")))
check("another event's tag fails", not all_ok(mpc.judge_tags(TAGS_OK, "p", "devopsdays-portland-2026")))
check("no tags fail", not all_ok(mpc.judge_tags({"tags": []}, "p", "kubecon-na-2026")))
check("an event that could not be read fails", not all_ok(mpc.judge_tags(TAGS_OK, "p", None)))
check("the event defaults to fleet/event.sh, as fleet.sh tags with it",
      mpc.fleet_event('WIB_EVENT="${WIB_EVENT:-kubecon-na-2026}"\n', {}) == "kubecon-na-2026"
      and mpc.fleet_event("", {"WIB_EVENT": "other-event"}) == "other-event")

print("\n== lifecycle ==")
check("Active with no scheduled dates passes", all_ok(mpc.judge_lifecycle(fm(), "m", THROUGH)))
check("Active with a legacy date after the talk passes",
      all_ok(mpc.judge_lifecycle(fm(legacyTime="2027-03-01T00:00:00+00:00", endOfLifeTime="2027-09-01T00:00:00+00:00"), "m", THROUGH)))
check("LEGACY fails", not all_ok(mpc.judge_lifecycle(fm("LEGACY"), "m", THROUGH)))
check("a legacy date before the talk fails",
      not all_ok(mpc.judge_lifecycle(fm(legacyTime="2026-11-01T00:00:00+00:00"), "m", THROUGH)))
check("a legacy date ON the talk day fails",
      not all_ok(mpc.judge_lifecycle(fm(legacyTime="2026-11-12T08:00:00+00:00"), "m", THROUGH)))
check("extended access (higher price) before the talk fails",
      not all_ok(mpc.judge_lifecycle(fm(publicExtendedAccessTime="2026-11-10T00:00:00+00:00"), "m", THROUGH)))
check("end of life before the talk fails",
      not all_ok(mpc.judge_lifecycle(fm(endOfLifeTime="2026-11-11T00:00:00+00:00"), "m", THROUGH)))
check("a missing lifecycle block fails", not all_ok(mpc.judge_lifecycle({"modelDetails": {}}, "m", THROUGH)))

print("\n== the model answers ==")
c, reply = mpc.judge_converse(CONVERSE_OK)
check("a text reply passes", all_ok(c) and reply == "ready", reply)
check("an empty content list fails",
      not all_ok(mpc.judge_converse({"output": {"message": {"content": []}}, "stopReason": "end_turn"})[0]))
check("a whitespace-only reply fails",
      not all_ok(mpc.judge_converse({"output": {"message": {"content": [{"text": "  \n"}]}}})[0]))

print("\n== quota ==")
c, seen = mpc.judge_quotas(QUOTAS, [], True, "Amazon Nova Pro", 240, 420000)
check("applied quotas above the room's need pass", all_ok(c), str(c))
check("the exact quota is picked, not the Latency Optimized one", seen.get("requests", (None,))[0] == "L-AAAA0001", str(seen))
check("requests below the need fail", not all_ok(mpc.judge_quotas(QUOTAS, [], True, "Amazon Nova Pro", 501, 1)[0]))
check("tokens below the need fail", not all_ok(mpc.judge_quotas(QUOTAS, [], True, "Amazon Nova Pro", 1, 2000001)[0]))
c, seen = mpc.judge_quotas([], QUOTAS, True, "Amazon Nova Pro", 240, 420000)
check("an unchanged quota is read from the AWS defaults and says so",
      all_ok(c) and seen["tokens"][2] == "AWS default", str(seen))
c, _ = mpc.judge_quotas([], [], True, "Amazon Nova Pro", 1, 1)
check("a quota that cannot be found fails, it does not pass", not all_ok(c))
check("an in-Region pin looks for the On-demand quota, not the cross-region one",
      not all_ok(mpc.judge_quotas(QUOTAS, [], False, "Amazon Nova Pro", 1, 1)[0]))

# One whole run with a stand-in aws CLI, so the plumbing (argv, profile and region on every call, the per-region
# lifecycle lookups, exit codes) is exercised and not just the judges. The stand-in logs each call it gets.
FAKE_AWS = r'''#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
with open(os.environ["FAKE_AWS_LOG"], "a") as f:
    f.write(json.dumps(args) + "\n")
answers = json.loads(open(os.environ["FAKE_AWS_ANSWERS"]).read())
key = " ".join(args[:2])
if key not in answers:
    sys.stderr.write("fake aws: no answer for " + key + "\n")
    sys.exit(254)
print(json.dumps(answers[key]))
'''


def run_with(answers):
    with tempfile.TemporaryDirectory() as d:
        d = pathlib.Path(d)
        (d / "aws").write_text(FAKE_AWS)
        (d / "aws").chmod(0o755)
        (d / "answers.json").write_text(json.dumps(answers))
        log = d / "calls.log"
        env = {**os.environ, "PATH": f"{d}{os.pathsep}{os.environ['PATH']}",
               "FAKE_AWS_LOG": str(log), "FAKE_AWS_ANSWERS": str(d / "answers.json")}
        env.pop("WIB_EVENT", None)  # the stand-in tags carry event.sh's event; an operator's override is not this run's
        p = subprocess.run([sys.executable, str(CHECK), "--profile", "delivery", "--region", "us-west-2"],
                           capture_output=True, text=True, env=env, timeout=120)
        calls = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
        return p, calls


GOOD = {
    "sts get-caller-identity": {"Account": "515966504359", "Arn": "arn:aws:iam::515966504359:user/x"},
    "bedrock get-inference-profile": PROFILE_OK,
    "bedrock get-foundation-model": fm(),
    "bedrock-runtime converse": CONVERSE_OK,
    "bedrock list-inference-profiles": APPS,
    "bedrock list-tags-for-resource": TAGS_OK,
    "service-quotas list-service-quotas": {"Quotas": QUOTAS},
    "service-quotas list-aws-default-service-quotas": {"Quotas": []},
}

print("\n== whole run, stand-in aws ==")
p, calls = run_with(GOOD)
check("a healthy pin exits 0 and says GREEN", p.returncode == 0 and "MODEL PIN GREEN" in p.stdout,
      f"exit {p.returncode}\n{p.stdout}\n{p.stderr}")
check("every aws call names --profile and --region",
      bool(calls) and all("--profile" in c and "--region" in c for c in calls), str(calls))
fm_regions = sorted(c[c.index("--region") + 1] for c in calls if c[:2] == ["bedrock", "get-foundation-model"])
check("the lifecycle is read in every region the profile routes to",
      fm_regions == ["us-east-1", "us-east-2", "us-west-2"], str(fm_regions))
conv = [c for c in calls if c[:2] == ["bedrock-runtime", "converse"]]
check("the first Converse call uses the pinned profile id in the delivery region",
      len(conv) == 2 and conv[0][conv[0].index("--model-id") + 1] == pin["model_id"]
      and conv[0][conv[0].index("--region") + 1] == "us-west-2", str(conv))
check("the second goes through a cluster's tagged application profile, the path the agent takes",
      len(conv) == 2 and conv[1][conv[1].index("--model-id") + 1] == APP_ARN.format("nova0001"), str(conv))
apps_calls = [c for c in calls if c[:2] == ["bedrock", "list-inference-profiles"]]
check("application profiles are listed by type", len(apps_calls) == 1 and "APPLICATION" in apps_calls[0], str(apps_calls))
tag_arns = sorted(c[c.index("--resource-arn") + 1] for c in calls if c[:2] == ["bedrock", "list-tags-for-resource"])
check("the tags are read on each cluster profile for the pin, and only those",
      tag_arns == sorted([APP_ARN.format("nova0001"), APP_ARN.format("nova0002")]), str(tag_arns))

p, _ = run_with({**GOOD, "bedrock-runtime converse": {"output": {"message": {"content": []}}, "stopReason": "end_turn"}})
check("a pin that does not answer exits 1", p.returncode == 1 and "MODEL PIN FAILED" in p.stderr, f"exit {p.returncode}")
p, _ = run_with({**GOOD, "bedrock get-foundation-model": fm("LEGACY")})
check("a Legacy model exits 1", p.returncode == 1, f"exit {p.returncode}")
p, _ = run_with({k: v for k, v in GOOD.items() if k != "bedrock get-inference-profile"})
check("a profile the account cannot see exits 1", p.returncode == 1, f"exit {p.returncode}")
p, _ = run_with({**GOOD, "bedrock list-inference-profiles": {"inferenceProfileSummaries": []}})
check("no cluster profile for the pin exits 1", p.returncode == 1, f"exit {p.returncode}")
p, _ = run_with({**GOOD, "bedrock list-tags-for-resource": {"tags": [{"key": "project", "value": "watch-it-burn"}]}})
check("a cluster profile without the event tag exits 1", p.returncode == 1, f"exit {p.returncode}")
p, _ = run_with({k: v for k, v in GOOD.items() if k != "sts get-caller-identity"})
check("a profile with no credentials exits 2", p.returncode == 2, f"exit {p.returncode}")

if failures:
    print(f"\nFAILED: {len(failures)} check(s)")
    sys.exit(1)
print("\nAll model-pin check tests passed.")
