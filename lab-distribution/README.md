<!-- ABOUTME: Per-attendee credential distributor for Watch It Burn: console URL + Datadog + AWS keys. -->
<!-- ABOUTME: Code + placeholder pool only; the real pool (live secrets) is gitignored, dropped at deploy. -->

# Watch It Burn: lab/credential distribution (v2)

A small Flask app that hands each attendee their workshop access from a pool, claimed atomically by
email (idempotent: re-entering the same email returns the same assignment). EKS/console-only — the
inherited KodeKloud `/browser` path has been removed.

## How it works

- Attendee opens the URL (QR at the door), enters their email, and is assigned one row from `pool.csv`.
- The success page (and optional Resend email) delivers, in priority order:
  1. **Open your console** — `console_url` (`a-<id>.agenticburn.com`): the chat + in-browser terminal where the workshop happens.
  2. **Your Datadog** — `datadog_dashboard_url` + login (`datadog_email`/`datadog_password`) to view the org, plus `datadog_api_key`/`datadog_app_key`/`datadog_site` for the cluster's Agent.
  3. **AWS keys** — `access_key`/`secret_key` + `aws configure` / `aws eks update-kubeconfig` / `kubectl get nodes`, for the optional local-kubectl path only.

## Pool schema (`pool.csv`)

```
name,region,access_key,secret_key,console_url,
datadog_org,datadog_email,datadog_password,datadog_api_key,datadog_app_key,datadog_site,datadog_dashboard_url
```

The committed `pool.csv` is a PLACEHOLDER (AKIAEXAMPLE / FAKE-pw / EXAMPLE keys). Optional columns
(console/datadog) may be blank — the success page omits those sections gracefully. Schema migrations
are additive (`init_schema` adds any missing columns to an existing `pool.db`).

## Building the real pool (two sources, joined by row)

The real pool is assembled at deploy from two provisioning outputs and is **never committed**:

1. **AWS-cluster pool** (from the Terraform fleet): `name,region,access_key,secret_key,console_url`.
2. **Datadog accounts** (from Tara's tooling): clone `github.com/DataDog/learning-center-lambdas`,
   run `scripts/generate_accounts_csv.sh <pool> <count> --stage prod` (needs the 1Password CLI) → a CSV
   with `orgName,datadogEmail,password,apiKey,appKey,…`. **Trial orgs expire ~14 days** — mint near the event.

Join them row-by-row into `pool.csv`:

```bash
python3 scripts/merge_pool.py --aws aws-pool.csv --datadog wib-pool-accounts.csv --out pool.csv \
    --dashboard-url-template "https://app.datadoghq.com/dashboard/lists?q={org}"
```

## What is here vs not

- HERE (code): `app.py`, `scripts/merge_pool.py`, `templates/`, `static/`, `Procfile`, `railway.json`,
  `pyproject.toml`, `test_app.py`, and the PLACEHOLDER `pool.csv`.
- NOT here (gitignored): `pool.db` (claims), the real credential pool, any `.env`. The real pool holds
  live secrets — keep it in the secrets vault (`~/secrets/`), drop it in at deploy (see `~/.claude/rules/env-vault.md`).

## Adapt-before-use (verify-at-build)

- Confirm cluster naming (`watch-it-burn-attendee-<id>`), region, and the `a-<id>.agenticburn.com`
  console scheme match the provisioning output (`infra/terraform/`, `infra/dns/`, the apex router in `railway/apex/`).
- Set `ADMIN_TOKEN` and (optional) `RESEND_API_KEY` via env, never hardcoded.
- 2-hour lab tool: provision the pool before doors, tear it down after.

## Run locally / test

```bash
cd lab-distribution
uv run --with flask --with requests --with pytest pytest -q   # tests
uv run --with flask --with requests python app.py             # serve (ADMIN_TOKEN auto-generated if unset)
```
