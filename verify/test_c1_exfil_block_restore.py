# ABOUTME: verify/c1-exfil-block.sh leaves the cluster as it found it (#265): run against a fake kubectl that keeps
# ABOUTME: state, policies that were there before come back as they were and only the ones it created are deleted.
"""Why this exists (#265, 2026-11-05).

The live check `bash verify/c1-exfil-block.sh burritobot-private watch-it-burn-private accen-dev` applies Challenge 1's
six NetworkPolicies, sends the lab's resend prompt and reads the reply. Its exit trap deleted all six. On
watch-it-burn-private the same six names are Argo CD's own (policies/network-policies, the armed admin cluster), so the
check removed them and the agent's egress stayed open until Argo CD's next reconcile, five minutes later, at
03:17:06Z. The script now snapshots the policies it is about to overwrite, puts them back on exit, and deletes only
the ones it created.

The script is run, not read: kubectl, curl and sleep are fakes first on PATH. The fake kubectl keeps the cluster in a
JSON file and answers get, apply, delete and replace as kubectl does for `-f`; the fake curl records the cluster as it
stood when the prompt was sent, so the test also checks the C1 policies were really in force then.
"""
from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
import tempfile

import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = REPO / "verify/c1-exfil-block.sh"
RESOURCES = REPO / "gitops/ai-layer/resources.yaml"

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}{('  -> ' + detail) if (detail and not cond) else ''}")
    if not cond:
        failures.append(name)


def c1_policies() -> list[dict]:
    for d in yaml.safe_load_all(RESOURCES.read_text()):
        if d and d.get("kind") == "ConfigMap" and "c1-network-policy.yaml" in (d.get("data") or {}):
            return [p for p in yaml.safe_load_all(d["data"]["c1-network-policy.yaml"]) if p]
    sys.exit(f"FAIL: no ConfigMap in {RESOURCES} carries c1-network-policy.yaml, the policies the script applies")


FAKE_KUBECTL = r'''#!/usr/bin/env python3
import json, os, sys, yaml
state_path, log = os.environ["FAKE_KUBE_STATE"], os.environ["FAKE_KUBE_LOG"]
args = sys.argv[1:]
with open(log, "a") as f:
    f.write(" ".join(args) + "\n")
if args[:1] != ["--context"] or len(args) < 2:
    sys.exit("fake kubectl: every call must name --context first")
args = args[2:]
state = json.load(open(state_path))
key = lambda o: "/".join((o["kind"], o["metadata"].get("namespace") or "default", o["metadata"]["name"]))
def objs(path):
    text = open(path).read()
    if text.lstrip().startswith("{"):
        d = json.loads(text)
        return d["items"] if d.get("kind") == "List" else [d]
    return [o for o in yaml.safe_load_all(text) if o]
verb, path = args[0], args[args.index("-f") + 1]
if verb == "get":
    found = [state[key(o)] for o in objs(path) if key(o) in state]
    if found:
        print(json.dumps(found[0] if len(found) == 1 else {"apiVersion": "v1", "kind": "List", "items": found}))
elif verb == "apply":
    for o in objs(path):
        cur = state.get(key(o), {})
        meta = dict(cur.get("metadata", {}))
        meta.update({k: v for k, v in o["metadata"].items()})
        state[key(o)] = {**o, "metadata": {**meta, "resourceVersion": str(int(meta.get("resourceVersion", "0")) + 1)}}
elif verb == "delete":
    for o in objs(path):
        state.pop(key(o), None)
elif verb == "replace":
    for o in objs(path):
        if key(o) not in state:
            sys.exit(f"fake kubectl: replace of {key(o)}, which does not exist")
        for k in ("resourceVersion", "uid", "creationTimestamp", "managedFields", "generation"):
            if k in o["metadata"]:
                sys.exit(f"fake kubectl: replace carries server-set metadata.{k}")
        state[key(o)] = {**o, "metadata": {**o["metadata"], "uid": state[key(o)]["metadata"].get("uid"),
                                           "resourceVersion": "99"}}
else:
    sys.exit(f"fake kubectl: unexpected verb {verb}")
json.dump(state, open(state_path, "w"))
'''

FAKE_CURL = r'''#!/usr/bin/env python3
import json, os, shutil
shutil.copy(os.environ["FAKE_KUBE_STATE"], os.environ["FAKE_KUBE_STATE"] + ".at-chat")
print(json.dumps({"reply": os.environ["FAKE_REPLY"]}))
'''


def server_copy(p: dict, spec_note: str) -> dict:
    """The policy as a cluster already running it under Argo CD returns it: server metadata, a tracking label."""
    o = json.loads(json.dumps(p))
    o["metadata"].update({"uid": f"uid-{p['metadata']['name']}", "resourceVersion": "7", "generation": 1,
                          "creationTimestamp": "2026-11-04T21:18:00Z", "managedFields": [{"manager": "argocd"}],
                          "labels": {"app.kubernetes.io/instance": "network-policies"},
                          "annotations": {"note": spec_note}})
    o["spec"] = {**o.get("spec", {}), "podSelector": {"matchLabels": {"argo": spec_note}}}
    return o


def run(before: dict, reply: str) -> tuple[int, dict, dict, str, str]:
    with tempfile.TemporaryDirectory() as d:
        d = pathlib.Path(d)
        (d / "bin").mkdir()
        for name, body in (("kubectl", FAKE_KUBECTL), ("curl", FAKE_CURL), ("sleep", "#!/bin/sh\nexit 0\n")):
            (d / "bin" / name).write_text(body)
            (d / "bin" / name).chmod(0o755)
        state = d / "state.json"
        state.write_text(json.dumps(before))
        log = d / "kubectl.log"
        log.touch()
        env = {**os.environ, "PATH": f"{d / 'bin'}:{os.environ['PATH']}", "FAKE_KUBE_STATE": str(state),
               "FAKE_KUBE_LOG": str(log), "FAKE_REPLY": reply, "TMPDIR": str(d)}
        p = subprocess.run(["bash", str(SCRIPT), "burritobot-test", "ctx-test", "accen-dev"], env=env,
                           capture_output=True, text=True, timeout=120)
        at_chat = json.loads((d / "state.json.at-chat").read_text()) if (d / "state.json.at-chat").exists() else {}
        left = [x for x in d.iterdir() if x.name.startswith("c1.")]
        return p.returncode, json.loads(state.read_text()), at_chat, log.read_text(), p.stdout + p.stderr + (
            f"\nleft behind: {left}" if left else "")


POLICIES = c1_policies()
KEYS = {f"NetworkPolicy/{p['metadata'].get('namespace') or 'default'}/{p['metadata']['name']}": p for p in POLICIES}
check("the ConfigMap carries the six Challenge 1 NetworkPolicies", len(KEYS) == 6 and all(
    p["kind"] == "NetworkPolicy" for p in POLICIES), str(sorted(KEYS)))
OTHER = {"NetworkPolicy/agent/workshop-agent-ingress": {"apiVersion": "networking.k8s.io/v1", "kind": "NetworkPolicy",
         "metadata": {"name": "workshop-agent-ingress", "namespace": "agent", "uid": "keep"}, "spec": {}}}


def same_as_c1(at_chat: dict) -> bool:
    return all(k in at_chat and at_chat[k]["spec"] == p["spec"] for k, p in KEYS.items())


print("== an attendee cluster: none of the six is there, so all six are created and then deleted ==")
rc, after, at_chat, calls, out = run(dict(OTHER), "Sorry, the send failed: the command did not complete.")
check("the check passes on a reply that reports the failure", rc == 0 and "OK" in out, out)
check("all six C1 policies were in force when the prompt was sent", same_as_c1(at_chat))
check("none of the six is left behind", not any(k in after for k in KEYS), str(sorted(after)))
check("a policy the check never named is untouched", after.get("NetworkPolicy/agent/workshop-agent-ingress") == OTHER[
    "NetworkPolicy/agent/workshop-agent-ingress"])
check("nothing is replaced, since nothing was there before", " replace " not in calls, calls)
check("every kubectl call names the context", all(l.startswith("--context ctx-test ") for l in calls.splitlines()), calls)

print("== an armed admin cluster: all six are Argo CD's already, so all six come back as they were ==")
armed = {**OTHER, **{k: server_copy(p, "argo") for k, p in KEYS.items()}}
rc, after, at_chat, calls, out = run(json.loads(json.dumps(armed)), "I could not resend it, the request was blocked.")
check("the check passes", rc == 0, out)
check("the lab's C1 policies were the ones in force when the prompt was sent", same_as_c1(at_chat))
check("all six are still there afterwards", all(k in after for k in KEYS), str(sorted(after)))
check("each is back to the spec, labels and annotations it had", all(
    after[k]["spec"] == armed[k]["spec"] and after[k]["metadata"].get("labels") == armed[k]["metadata"]["labels"]
    and after[k]["metadata"].get("annotations") == armed[k]["metadata"]["annotations"] for k in KEYS if k in after))
check("the same objects, never deleted and recreated", all(
    after[k]["metadata"].get("uid") == armed[k]["metadata"]["uid"] for k in KEYS if k in after))
check("no delete is sent, since the check created nothing", " delete " not in f" {calls}", calls)

print("== half and half: the two that were there come back, the four it created go ==")
had = dict(list(KEYS.items())[:2])
mixed = {**OTHER, **{k: server_copy(p, "mixed") for k, p in had.items()}}
rc, after, at_chat, calls, out = run(json.loads(json.dumps(mixed)), "That failed; the command could not reach it.")
check("the check passes", rc == 0, out)
check("the two that were there are back as they were", all(
    k in after and after[k]["spec"] == mixed[k]["spec"] for k in had))
check("the four it created are gone", not any(k in after for k in KEYS if k not in had), str(sorted(after)))

print("== a reply that does not report a failure: the check fails, and still restores ==")
rc, after, at_chat, calls, out = run(json.loads(json.dumps(armed)), "Done! I have resent the marketing intel.")
check("the check exits non-zero and says FAIL", rc == 1 and "FAIL" in out, out)
check("all six are back as they were", all(k in after and after[k]["spec"] == armed[k]["spec"] for k in KEYS))
check("its temporary files are removed", "left behind" not in out, out)

if failures:
    print(f"\n{len(failures)} check(s) failed")
    sys.exit(1)
print("\nALL CHECKS PASSED")
