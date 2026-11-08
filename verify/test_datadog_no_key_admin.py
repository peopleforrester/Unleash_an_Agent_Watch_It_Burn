# ABOUTME: Offline sweep for #1082: nothing fleet.sh runs, and nothing in infra/datadog-fleet, creates, rotates or
# ABOUTME: revokes a Datadog API or application key, or edits a user, a role or a service account.
"""Whitney's sandbox org is shared (#629): its users, roles and keys are hers and other teams'. BurritoBot's tooling
reads its own keys from Secrets Manager and writes only monitors, dashboards and downtimes (fleet_monitors.py, whose
every call test_fleet_monitors.py holds to an allowlist). This test reads the source of fleet.sh and each script it
runs that talks to Datadog, and fails on:

  - a Datadog key, user, role, permission, service-account or invitation endpoint (/api/v1/api_key,
    /api/v2/api_keys, /api/v2/application_keys, /api/v2/current_user/application_keys, /api/v2/users, /api/v1/user,
    /api/v2/roles, /api/v2/permissions, /api/v2/service_accounts, /api/v2/user_invitations), in code or comment;
  - a curl to a Datadog API that writes (-X POST/PUT/PATCH/DELETE, --request, -d, --data): the shell scripts only read;
  - a Terraform datadog_api_key, datadog_application_key, datadog_user, datadog_role, datadog_service_account or
    datadog_user_role resource in the Terraform that fleet.sh or the dashboards apply.

It also builds each case to show the sweep would catch it.
"""
from __future__ import annotations

import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
FLEET = REPO / "infra/terraform/fleet/fleet.sh"
sys.path.insert(0, str(REPO / "verify"))

# Offline means offline (#859): this test only reads fleet.sh, but any subprocess gets aws, kubectl, eksctl,
# terraform and helm as stubs that log the call and fail (verify/no_cloud.py). The last check reads the log.
import no_cloud  # noqa: E402
no_cloud.setup()

failures: list[str] = []


def check(name: str, cond: bool) -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        failures.append(name)


# What is swept: fleet.sh and its directory's scripts (providers included), infra/datadog-fleet, and the scripts
# fleet.sh runs that hold or check Datadog keys. Each is named, so a moved file fails here, not silently.
SWEPT = sorted({*(REPO / "infra/terraform/fleet").rglob("*.sh"), *(REPO / "infra/terraform/fleet").rglob("*.py"),
                *(p for p in (REPO / "infra/datadog-fleet").iterdir() if p.is_file()),
                REPO / "infra/datadog-cluster-identity.sh", REPO / "infra/reload-datadog-consumers.sh",
                REPO / "verify/datadog-orgs.sh"})
TERRAFORM = sorted({*(REPO / "infra/terraform").rglob("*.tf")} - {*(REPO / "infra/terraform").rglob(".terraform/**/*.tf")})

ENDPOINT = re.compile(r"/api/v\d+/(?:[a-z_]+/)*(api_keys?|application_keys?|users?|roles|permissions|"
                      r"service_accounts|user_invitations|authn_mappings)\b")
DD_CURL = re.compile(r"\bcurl\b[^\n]*datadoghq|datadoghq[^\n]*\bcurl\b")
CURL_WRITE = re.compile(r"(?:^|\s)(-X\s*(POST|PUT|PATCH|DELETE)|--request\b|-d\b|--data(-raw|-binary)?\b)")
TF_RESOURCE = re.compile(r'resource\s+"datadog_(api_key|application_key|user|role|service_account|user_role|'
                         r'service_account_application_key)"')


def endpoint_hits(text: str) -> list[str]:
    return [m.group(0) for m in ENDPOINT.finditer(text)]


def curl_write_hits(text: str) -> list[str]:
    # A curl's options can run over continued lines; join them first, then read each command whole.
    joined = re.sub(r"\\\n\s*", " ", text)
    return [line.strip()[:120] for line in joined.splitlines() if DD_CURL.search(line) and CURL_WRITE.search(line)]


def tf_hits(text: str) -> list[str]:
    return [m.group(0) for m in TF_RESOURCE.finditer(text)]


print("== the files swept are there ==")
for need in (FLEET, REPO / "infra/datadog-fleet/fleet_monitors.py", REPO / "verify/datadog-orgs.sh",
             REPO / "infra/datadog-cluster-identity.sh", REPO / "infra/terraform/dashboards/main.tf"):
    check(f"{need.relative_to(REPO)} exists and is swept", need.is_file() and (need in SWEPT or need in TERRAFORM))
fleet_src = FLEET.read_text()
for script in ("datadog-orgs.sh", "datadog-cluster-identity.sh", "fleet_monitors.py", "reload-datadog-consumers.sh"):
    check(f"fleet.sh runs {script}, which is swept", script in fleet_src)

print("== no key, user or role endpoint, no Datadog write from a shell, no key or user resource ==")
for p in SWEPT:
    text = p.read_text(errors="replace")
    rel = p.relative_to(REPO)
    hits = endpoint_hits(text)
    check(f"{rel}: no key, user or role endpoint {hits if hits else ''}".rstrip(), not hits)
    if p.suffix == ".sh":
        writes = curl_write_hits(text)
        check(f"{rel}: every curl to Datadog reads {writes if writes else ''}".rstrip(), not writes)
for p in TERRAFORM:
    hits = tf_hits(p.read_text(errors="replace"))
    check(f"{p.relative_to(REPO)}: no Datadog key, user or role resource {hits if hits else ''}".rstrip(), not hits)

print("== the sweep catches each case it is for ==")
for bad in ('dd.call("POST", "/api/v2/api_keys", body)', 'dd.call("DELETE", f"/api/v2/application_keys/{kid}")',
            'curl https://api.datadoghq.com/api/v2/current_user/application_keys',
            'dd.call("PATCH", f"/api/v2/users/{uid}", body)', 'dd.call("POST", "/api/v1/user", body)',
            'dd.call("POST", f"/api/v2/roles/{rid}/users", body)', 'dd.call("POST", "/api/v2/service_accounts", b)',
            'dd.call("POST", "/api/v1/api_key", {"name": "x"})', 'dd.call("POST", "/api/v2/user_invitations", b)'):
    check(f"caught: {bad}", bool(endpoint_hits(bad)))
for ok in ('dd.call("GET", "/api/v2/current_user")', 'dd.call("POST", "/api/v1/monitor", body)',
           'dd.call("PUT", f"/api/v1/dashboard/{did}", dash)', 'dd.call("POST", "/api/v2/downtime", d)'):
    check(f"not caught: {ok}", not endpoint_hits(ok))
check("caught: a curl that POSTs to Datadog",
      bool(curl_write_hits('curl -s -X POST -H "DD-API-KEY: $k" https://api.datadoghq.com/api/v1/monitor')))
check("caught: a curl whose --data is on a continued line",
      bool(curl_write_hits('curl -s https://api.datadoghq.com/api/v1/x \\\n    --data \'{"a":1}\'')))
check("not caught: the read datadog-orgs.sh makes",
      not curl_write_hits('curl -s --max-time 20 -H "DD-API-KEY: $api" https://api.datadoghq.com/api/v2/current_user'))
check("caught: a Terraform datadog_api_key", bool(tf_hits('resource "datadog_api_key" "x" {\n  name = "y"\n}')))
check("caught: a Terraform datadog_user_role", bool(tf_hits('resource "datadog_user_role" "x" {}')))
check("not caught: the dashboards' own resource", not tf_hits('resource "datadog_dashboard_json" "fleet" {}'))

print()
print("== offline means offline ==")
_calls = no_cloud.calls()
check("no check above called aws, kubectl, eksctl, terraform or helm", not _calls)
if _calls:
    print("".join(f"        {line}\n" for line in _calls.splitlines()), end="")

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All no-key, no-user checks passed.")
