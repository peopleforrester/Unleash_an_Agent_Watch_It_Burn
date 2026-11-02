# ABOUTME: The cluster half of #629's live check: the cluster ships to Whitney's sandbox org with the dedicated burritobot
# ABOUTME: key and no other, and every running container names a burritobot- service and the env its logs carry. Read-only.
# SUITE: e2e (needs kubectl, CONTEXT naming a KubeCon cluster, and AWS access to watch-it-burn/datadog)
"""test_datadog_sandbox_live.py reads Whitney's org and sees what arrived. This one reads the cluster and sees what
each container will send, so it can run right after a helm upgrade instead of 30 minutes later, and it names the pod
to fix rather than a service in a log search.

1. The key. Whitney asked for a new API key named burritobot, used for nothing else (#629). datadog-secret's api-key
   in every namespace that reads it (datadog, monitoring, security: verify/datadog-secret-fields.sh) equals
   watch-it-burn/datadog's, the key test_datadog_sandbox_live.py finds named burritobot in the org. The values are
   compared in this process and never printed.
2. No other key. No datadog-admin-secret in datadog, monitoring or agent, so the Agent and the collector have no
   second destination (infra/datadog-cluster-identity.sh removes it on an instructor cluster). Every container env
   that carries a Datadog API key (DD_API_KEY, DATADOG_APIKEY) reads it from datadog-secret's api-key, and no
   additional-endpoints variable holds a literal value.
3. Every log. Each container of each Running pod, in every namespace, logs under a burritobot service and
   env:burritobot-kubecon-na-26, from one of the three places the Agent reads them: a file-based log config in the
   live DatadogAgent's extraConfd matching the container's short image name (it wins over labels), the pod's own
   ad.datadoghq.com/<container>.logs config for the service, the container's DD_SERVICE and DD_ENV, or the pod's
   tags.datadoghq.com/<container>.service or tags.datadoghq.com/service and
   tags.datadoghq.com/env labels (docs.datadoghq.com/getting_started/tagging/unified_service_tagging, read
   2026-10-28). This is the check that DD_ENV reached argocd, kubearmor and aws-load-balancer-controller.

Usage, per cluster (CLAUDE.md: an explicit context, a per-command kubeconfig, never the current-context):
    KUBECONFIG=/tmp/watch-it-burn-private.kubeconfig CONTEXT=<that cluster's context> \\
        WIB_DEFAULT_ACCOUNT=accen-dev WIB_REGION=us-west-2 python3 verify/test_burritobot_cluster_live.py
Nothing skips: no CONTEXT, no AWS, an unreachable cluster or a missing object is a FAIL with the reason.
"""
from __future__ import annotations

import base64
import json
import os
import pathlib
import subprocess
import sys

import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "infra" / "datadog-fleet"))
import fleet_monitors as fm  # noqa: E402

DD_ENV = "burritobot-kubecon-na-26"
ROOT_SERVICE = "burritobot"
SECRET_NAMESPACES = ("datadog", "monitoring", "security")
ADMIN_SECRET_NAMESPACES = ("datadog", "monitoring", "agent")
KEY_VARS = ("DD_API_KEY", "DATADOG_APIKEY")
ENDPOINT_VARS = ("DD_ADDITIONAL_ENDPOINTS", "DD_LOGS_CONFIG_ADDITIONAL_ENDPOINTS",
                 "DD_PROCESS_CONFIG_ADDITIONAL_ENDPOINTS", "DD_ORCHESTRATOR_EXPLORER_ORCHESTRATOR_ADDITIONAL_ENDPOINTS")
MISSING = "(none)"


def ours(service: str) -> bool:
    """The root service, plain burritobot (question 868, decisions.md), or burritobot-<name>."""
    return service == ROOT_SERVICE or (service.startswith("burritobot-") and len(service) > len("burritobot-"))


def short_image(image: str) -> str:
    """What an Autodiscovery ad_identifier matches: the image's last path segment, no tag or digest."""
    return image.split("@", 1)[0].rsplit("/", 1)[-1].split(":", 1)[0]


def kubectl_json(context: str, *args: str, run=subprocess.run) -> dict:
    out = run(["kubectl", "--context", context, *args, "-o", "json"], capture_output=True, text=True, timeout=120)
    if out.returncode != 0:
        raise RuntimeError(f"kubectl {' '.join(args)} on {context}: {out.stderr.strip()[:300]}")
    return json.loads(out.stdout)


def log_configs(agent: dict) -> dict[str, tuple[str, str]]:
    """{short image: (service, env)} from the live DatadogAgent's file-based log configs."""
    cmap = ((((agent.get("spec") or {}).get("override") or {}).get("nodeAgent") or {}).get("extraConfd") or {}) \
        .get("configDataMap") or {}
    out = {}
    for text in cmap.values():
        conf = yaml.safe_load(text) or {}
        for log in conf.get("logs") or []:
            env = next((t.split(":", 1)[1] for t in log.get("tags") or [] if t.startswith("env:")), MISSING)
            for ident in conf.get("ad_identifiers") or []:
                out[ident] = (log.get("service") or MISSING, env)
    return out


def container_tags(pod: dict, container: dict, confs: dict) -> tuple[str, str, str]:
    """(service, env, where they came from) for one container's logs."""
    hit = confs.get(short_image(container.get("image", "")))
    if hit:
        return hit[0], hit[1], f"log config for image {short_image(container.get('image', ''))}"
    meta = pod.get("metadata") or {}
    labels = meta.get("labels") or {}
    env_vars = {e.get("name"): e.get("value") for e in container.get("env") or [] if "value" in e}
    service = env_vars.get("DD_SERVICE") or labels.get(f"tags.datadoghq.com/{container['name']}.service") \
        or labels.get("tags.datadoghq.com/service") or MISSING
    env = env_vars.get("DD_ENV") or labels.get(f"tags.datadoghq.com/{container['name']}.env") \
        or labels.get("tags.datadoghq.com/env") or MISSING
    # A pod's own log config, ad.datadoghq.com/<container>.logs, names the service over the labels (Backstage's).
    annotated = ((meta.get("annotations") or {}).get(f"ad.datadoghq.com/{container['name']}.logs") or "").strip()
    if annotated:
        try:
            service = (json.loads(annotated) or [{}])[0].get("service") or service
        except (ValueError, AttributeError, IndexError):
            return f"unreadable ad.datadoghq.com/{container['name']}.logs", env, "pod annotation"
        return service, env, "pod annotation and labels"
    return service, env, "env and labels"


def secret_key(secret: dict) -> str:
    raw = (secret.get("data") or {}).get("api-key", "")
    return base64.b64decode(raw).decode() if raw else ""


def run(context: str, want_key: str, get=None, say=print) -> list[str]:
    """Every rule as a check; returns the names of the ones that failed. get(*kubectl args) returns the JSON object,
    raising RuntimeError when kubectl fails; the default runs kubectl against `context`."""
    get = get or (lambda *a: kubectl_json(context, *a))
    failures: list[str] = []

    def check(name: str, cond: bool, bad: list | None = None) -> None:
        say(f"  {'PASS' if cond else 'FAIL'}  {name}")
        if not cond:
            failures.append(name)
            for line in (bad or [])[:30]:
                say(f"        {line}")

    say(f"== 1. datadog-secret holds watch-it-burn/datadog's api-key on {context} ==")
    for ns in SECRET_NAMESPACES:
        try:
            have = secret_key(get("-n", ns, "get", "secret", "datadog-secret"))
        except RuntimeError as exc:
            check(f"{ns}/datadog-secret is readable", False, [str(exc)])
            continue
        check(f"{ns}/datadog-secret's api-key is the burritobot key", bool(want_key) and have == want_key,
              ["empty" if not have else "a different key"])

    say("== 2. no second key: no admin secret, and every key variable reads datadog-secret ==")
    for ns in ADMIN_SECRET_NAMESPACES:
        items = get("-n", ns, "get", "secret", "--field-selector", "metadata.name=datadog-admin-secret").get("items", [])
        check(f"no datadog-admin-secret in {ns}", not items)
    pods = [p for p in get("get", "pods", "-A").get("items", []) if (p.get("status") or {}).get("phase") == "Running"]
    check("the cluster has Running pods to read", bool(pods))
    stray_keys = []
    for p in pods:
        where = f"{p['metadata']['namespace']}/{p['metadata']['name']}"
        for c in (p.get("spec") or {}).get("containers") or []:
            for e in c.get("env") or []:
                ref = ((e.get("valueFrom") or {}).get("secretKeyRef") or {})
                if e.get("name") in KEY_VARS and (ref.get("name"), ref.get("key")) != ("datadog-secret", "api-key"):
                    stray_keys.append(f"{where} {c['name']}: {e['name']} from {ref.get('name') or 'a literal value'}")
                if e.get("name") in ENDPOINT_VARS and e.get("value"):
                    stray_keys.append(f"{where} {c['name']}: {e['name']} is a literal value")
    check("every Datadog API key variable reads datadog-secret's api-key", not stray_keys, sorted(stray_keys))

    say("== 3. every running container logs under a burritobot service and the env ==")
    confs = log_configs(get("-n", "datadog", "get", "datadogagent", "datadog"))
    check("the DatadogAgent carries file-based log configs", bool(confs))
    wrong = []
    for p in pods:
        for c in (p.get("spec") or {}).get("containers") or []:
            service, env, source = container_tags(p, c, confs)
            if not ours(service) or env != DD_ENV:
                wrong.append(f"{p['metadata']['namespace']}/{p['metadata']['name']} {c['name']} "
                             f"({short_image(c.get('image', ''))}): service {service}, env {env}, from {source}")
    check(f"every container's logs carry a burritobot service and env:{DD_ENV}", not wrong, sorted(wrong))
    return failures


def main() -> int:
    context = os.environ.get("CONTEXT", "")
    if not context:
        print("FAIL: set CONTEXT to the cluster's kube context; there is no current-context fallback (CLAUDE.md)",
              file=sys.stderr)
        return 1
    profile = os.environ.get("WIB_DEFAULT_ACCOUNT", "accen-dev")
    region = os.environ.get("WIB_REGION", "us-west-2")
    try:
        api, _, _ = fm.read_keys(profile, region)
        failures = run(context, api)
    except (RuntimeError, OSError, ValueError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    if failures:
        print(f"\nFAILED: {len(failures)} check(s) on {context}.")
        return 1
    print(f"\n{context} ships with the burritobot key alone, and every container names its service and env (#629).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
