# ABOUTME: Live check of #629's done-when list in Whitney's Datadog sandbox org: metrics, logs and spans carry the env
# ABOUTME: and a burritobot service under distinct cluster names, and the key is the org's one named burritobot. Read-only.
# SUITE: e2e (needs AWS access to watch-it-burn/datadog, and both KubeCon clusters shipping with a recent /chat)
"""The live half of #629. The offline half is test_datadog_sandbox_names.py (the manifests set the names) and
test_datadog_sandbox_live_logic.py (this file judges a payload the way it should).

Whitney's rules for her sandbox org, and what each check below reads, over the last WIB_DD_LOOKBACK_MIN minutes
(default 60):

1. Distinct cluster names. `datadog.agent.running` by kube_cluster_name and env: every cluster in CLUSTERS
   reports, and every Agent series carries the env. The Agent sets env from DD_ENV (datadog-agent.yaml).
2. Every log. The Logs aggregate API (logs_read_data), grouped by kube_cluster_name, service and env, over every
   log whose kube_cluster_name starts with burritobot-. Each group must have a burritobot service and the env.
3. Every span. The collector's span metrics, `traces.span.metrics.calls`, count every span before sampling and keep
   the resource attributes (add_resource_attributes), so grouped by kube_cluster_name, service and env they cover
   the spans an indexed-span search would miss. Each group must have a burritobot service and the env.
4. ml_app. LLM Observability's `ml_obs.trace` carries ml_app and env (docs.datadoghq.com/llm_observability/
   monitoring/metrics, read 2026-10-30). Under the env it must report, and only as ml_app burritobot.
5. The dedicated key. Whitney asked for a new API key named burritobot, used for nothing else. An API key cannot be
   scoped or tagged, so the org side of that is: exactly one key in the org is named burritobot, it is the key in
   watch-it-burn/datadog (the whole value, from the key's own record, GET /api/v2/api_keys/<id>, since the list
   gives only the last four characters), and Datadog saw it used within KEY_USED_HOURS. The list is
   GET /api/v2/api_keys, which needs the api_keys_read permission (Key Management API reference, read 2026-11-02);
   when the secret's read-only application key lacks it, WIB_FLEET_MONITORS_APP_KEY, Michael's own key, reads it.
   The cluster side, that both clusters ship with that key and no other, is test_burritobot_cluster_live.py.

"A burritobot service" is burritobot- followed by a name, or the root service, plain burritobot: Datadog takes the
LLM Observability ml_app from the root span's service, so that one stays unhyphenated (question 868, decisions.md).
ml_obs.* carries no cluster tag, so check 4 is per env, not per cluster.

The keys are watch-it-burn/datadog's (fleet_monitors.read_keys), read as WIB_DEFAULT_ACCOUNT (default accen-dev) in
WIB_REGION (default us-west-2), never the ambient AWS default. Its application key is read-only, which is all this
needs. Nothing skips: no AWS, no key, a refused query, a cluster that is not shipping or no recent /chat is a FAIL
with the reason. Drive one /chat on each cluster within the window before running it.
"""
from __future__ import annotations

import os
import pathlib
import sys
import time

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "infra" / "datadog-fleet"))
import fleet_monitors as fm  # noqa: E402

DD_ENV = "burritobot-kubecon-na-26"
ROOT_SERVICE = "burritobot"
ML_APP = "burritobot"
CLUSTERS = ("burritobot-public", "burritobot-private")
OURS = "kube_cluster_name:burritobot-*"
MISSING = "(none)"
KEY_NAME = "burritobot"
# date_last_used is the newest use Datadog records; the Key Management reference does not say how often it is
# refreshed, so this allows a day rather than the metric window.
KEY_USED_HOURS = 24


def ours(service: str) -> bool:
    return service == ROOT_SERVICE or (service.startswith("burritobot-") and len(service) > len("burritobot-"))


def tags_of(series: dict) -> dict:
    """A /api/v1/query series' group tags as a dict; a group the series does not carry reads MISSING."""
    out = {}
    for tag in series.get("tag_set") or []:
        key, _, value = tag.partition(":")
        out[key] = value
    return out


def query(dd, q: str, minutes: int, now: int) -> list[dict]:
    from urllib.parse import urlencode
    return dd.call("GET", "/api/v1/query?" + urlencode({"from": now - minutes * 60, "to": now, "query": q}))\
        .get("series", [])


def log_groups(dd, minutes: int) -> list[dict]:
    body = {"filter": {"query": OURS, "indexes": ["*"], "from": f"now-{minutes}m", "to": "now"},
            "compute": [{"aggregation": "count", "type": "total"}],
            # The product of the limits may not pass 10000 (Logs aggregate API reference, read 2026-10-30).
            "group_by": [{"facet": "kube_cluster_name", "limit": 5, "missing": MISSING},
                         {"facet": "service", "limit": 200, "missing": MISSING},
                         {"facet": "env", "limit": 10, "missing": MISSING}]}
    return [b.get("by", {}) for b in dd.call("POST", "/api/v2/logs/analytics/aggregate", body)
            .get("data", {}).get("buckets", [])]


def api_keys(dd, name: str) -> list[dict]:
    """Every API key whose name contains `name`, as Datadog's list filter matches it, all pages."""
    from urllib.parse import urlencode
    out, page = [], 0
    while True:
        data = dd.call("GET", "/api/v2/api_keys?" + urlencode({"filter": name, "page[size]": 100, "page[number]": page}))
        rows = data.get("data", [])
        out.extend(rows)
        if len(rows) < 100:
            return out
        page += 1


def used_at(stamp: str | None) -> int | None:
    """An API key's date_last_used as epoch seconds, or None when Datadog has none."""
    import datetime as dt
    if not stamp:
        return None
    return int(dt.datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp())


def run(dd, minutes: int = 60, now: int | None = None, say=print, api_key: str = "", keys_dd=None) -> list[str]:
    """Every rule as a check; returns the names of the ones that failed. api_key is watch-it-burn/datadog's, compared
    in this process with the org key's whole value and never printed; keys_dd reads the keys when dd's application
    key may not (main)."""
    now = int(time.time()) if now is None else now
    failures: list[str] = []

    def check(name: str, cond: bool, bad: list | None = None) -> None:
        say(f"  {'PASS' if cond else 'FAIL'}  {name}")
        if not cond:
            failures.append(name)
            for line in (bad or [])[:20]:
                say(f"        {line}")

    def judge(what: str, groups: list[dict], need_service: bool) -> None:
        seen = {g.get("kube_cluster_name", MISSING) for g in groups}
        for cluster in CLUSTERS:
            check(f"{what}: {cluster} reports in the last {minutes} minutes", cluster in seen)
        wrong_env = sorted({f"{g.get('kube_cluster_name', MISSING)} {g.get('service', MISSING)} env:{g.get('env', MISSING)}"
                            for g in groups if g.get("env", MISSING) != DD_ENV})
        check(f"{what}: every group carries env:{DD_ENV}", not wrong_env, wrong_env)
        if need_service:
            wrong_svc = sorted({f"{g.get('kube_cluster_name', MISSING)} service:{g.get('service', MISSING)}"
                                for g in groups if not ours(g.get("service", MISSING))})
            check(f"{what}: every group's service is {ROOT_SERVICE} or {ROOT_SERVICE}-<name>", not wrong_svc, wrong_svc)

    say("== 1. the Agents report under distinct burritobot- cluster names (datadog.agent.running) ==")
    agents = [tags_of(s) for s in query(dd, f"avg:datadog.agent.running{{{OURS}}} by {{kube_cluster_name,env}}",
                                        minutes, now)]
    judge("Agent", agents, need_service=False)

    say(f"== 2. every log from the clusters (Logs aggregate, {OURS}) ==")
    judge("logs", log_groups(dd, minutes), need_service=True)

    say("== 3. every span from the clusters (traces.span.metrics.calls, counted before sampling) ==")
    spans = [tags_of(s) for s in query(
        dd, f"sum:traces.span.metrics.calls{{{OURS}}} by {{kube_cluster_name,service,env}}.as_count()", minutes, now)]
    judge("spans", spans, need_service=True)

    say(f"== 4. LLM Observability files the interactions under ml_app {ML_APP} (ml_obs.trace) ==")
    apps = sorted({tags_of(s).get("ml_app", MISSING) for s in query(
        dd, f"sum:ml_obs.trace{{env:{DD_ENV}}} by {{ml_app}}.as_count()", minutes, now)})
    check(f"ml_obs.trace reports under env:{DD_ENV} as ml_app {ML_APP}", ML_APP in apps)
    check(f"no other ml_app reports under env:{DD_ENV}", apps in ([], [ML_APP]), [f"ml_app:{a}" for a in apps])

    say(f"== 5. the clusters' key is the org's one API key named {KEY_NAME} (GET /api/v2/api_keys) ==")
    keys = keys_dd or dd
    rows = [k for k in api_keys(keys, KEY_NAME)
            if str(k.get("attributes", {}).get("name", "")).strip().lower() == KEY_NAME]
    named = [k.get("attributes", {}) for k in rows]
    check(f"exactly one API key in the org is named {KEY_NAME}", len(named) == 1,
          [f"name {k.get('name')!r} last4 {k.get('last4')}" for k in named])
    key = named[0] if len(named) == 1 else {}
    # The list gives only the last four characters, which another key can share; the key's own record carries the
    # whole value. It is compared in this process and never printed.
    full = ""
    if len(rows) == 1 and rows[0].get("id"):
        full = (keys.call("GET", f"/api/v2/api_keys/{rows[0]['id']}").get("data", {}).get("attributes", {})
                .get("key") or "")
    check(f"watch-it-burn/datadog's api-key is that key (GET /api/v2/api_keys/<id>, the whole value)",
          bool(api_key) and bool(full) and full == api_key,
          ([f"the {KEY_NAME} key ends {key.get('last4')}"] + ([] if full else ["and its record carries no key value"]))
          if key else [])
    last = used_at(key.get("date_last_used"))
    check(f"Datadog saw the {KEY_NAME} key used in the last {KEY_USED_HOURS} hours",
          last is not None and now - last <= KEY_USED_HOURS * 3600, [f"date_last_used {key.get('date_last_used')}"])
    return failures


def main() -> int:
    profile = os.environ.get("WIB_DEFAULT_ACCOUNT", "accen-dev")
    region = os.environ.get("WIB_REGION", "us-west-2")
    minutes = int(os.environ.get("WIB_DD_LOOKBACK_MIN", "60"))
    try:
        api, app, site = fm.read_keys(profile, region)
        dd = fm.Datadog(site, api, app)
        owner_app = os.environ.get(fm.APP_KEY_ENV, "")
        keys_dd = fm.Datadog(site, api, owner_app) if owner_app else dd
        print(f"== Whitney's sandbox org: {fm.org_name(dd)} ({site}), keys from {fm.SECRET_ID} as {profile} in {region} ==")
        failures = run(dd, minutes, api_key=api, keys_dd=keys_dd)
    except (RuntimeError, OSError, ValueError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    if failures:
        print(f"\nFAILED: {len(failures)} check(s). #629's done-when list does not hold in the sandbox org.")
        return 1
    print("\nBoth KubeCon clusters ship under Whitney's sandbox rules (#629).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
