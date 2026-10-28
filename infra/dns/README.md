<!-- ABOUTME: DNS records on agenticburn.com (Namecheap) and the tool that writes them, set-demo-dns.py. -->
<!-- ABOUTME: Cluster hosts need no record; the tool is for the wildcard and Railway service domains. -->

# DNS on agenticburn.com

agenticburn.com is on Namecheap DNS. Its mail is Namecheap email forwarding: MX resolves to
`eforward1-5.registrar-servers.com` (dig, 2026-10-08), which Namecheap synthesizes from the zone's
`EmailType` rather than keeping as host records.

## What needs a record

Cluster hosts need none. `<name>.agenticburn.com` for every cluster, and `grafana-<name>` beside it, is a
line in the apex router's `routes.map` (Caddy on Railway, `peopleforrester/apex-agenticburn`), reached
through the one `*.agenticburn.com` wildcard. See `docs/external-apps.md` and
`docs/MASTER-RECREATION-SPEC.md` (Recreation Steps 6 and 7).

Records are written only for what Railway serves under its own custom domain: the apex and wildcard, the
`_acme-challenge` CNAME that lets Railway issue the wildcard certificate, and a service such as
`monitoring` or `provisioning`. Railway needs a CNAME **and** its `_railway-verify.<label>` TXT for each;
with only the CNAME the domain resolves and returns 404.

The one other record is ACM's: the front door certificate a lab-platform roster cluster's NLB presents (#638)
is validated by one `_<token>` CNAME per domain per AWS account. `infra/front-door-cert.sh <aws-profile>
<region>` prints them as this tool's arguments; leave them in place, since ACM renews against them.

## How to write records (with Michael's go)

```bash
# dry run (default): reads the zone, prints what it would replace and the full record set, changes nothing
python3 infra/dns/set-demo-dns.py monitoring=<service>.up.railway.app \
    TXT:_railway-verify.monitoring=<railway token>
# write it (mutation; only with Michael's explicit go, per the namecheap-api rule)
python3 infra/dns/set-demo-dns.py --apply monitoring=<service>.up.railway.app \
    TXT:_railway-verify.monitoring=<railway token>
```

Each argument is `[TYPE:]name=value`. TYPE is `CNAME` (the default), `A` or `TXT`; name is relative to the
domain, `*` for the wildcard. `--domain` picks another Namecheap domain (default `agenticburn.com`).

An upsert replaces what would conflict at that name: a CNAME replaces every record there, an A replaces A
and CNAME records, a TXT replaces TXT and CNAME records. The dry run lists each record it would replace.
The tool refuses the apex (`@`, which holds the router, SPF and mail) and refuses to replace an MX record;
edit those by hand.

## Why the write is shaped like this

`setHosts` replaces every record in the zone; anything not sent is deleted. `--apply` therefore follows the
namecheap skill's `dns-safety.md`, and refuses to write if it cannot do any step (#581):

1. It reads the zone with `getHosts` immediately before the write and saves that response to
   `~/secrets/dns/backups/agenticburn.com-<UTC time>-getHosts.xml` (mode 0600) before sending anything.
2. It sends every existing record back verbatim, MX records with their `MXPref`, and sends the zone's
   `EmailType` back as read. An omitted EmailType resets the mail configuration, which on agenticburn.com
   would turn forwarding off. A zone whose `getHosts` shows no EmailType is not written.
3. It writes with a url-encoded POST, never a GET query string.
4. It reads the zone again and fails, naming the backup, if any record was lost, a new one is missing, or
   EmailType changed. It checks MX with `dig` against `dns1.registrar-servers.com` before the write and
   again once the new records are published there, and fails if MX changed. With forwarding, MX is not in
   the host list, so only `dig` sees it.

Credentials come from `~/secrets/dns/namecheap.env` (`--env-file` to override); nothing is hardcoded.

## Gotchas / verify-at-build

- **IP allowlist:** the `ClientIp` must be a Namecheap-whitelisted IP that matches where the call runs
  (the netcup VPS `152.53.192.39` and Michael's laptop are whitelisted). Run from there. `dig` must be
  installed there too.
- **Propagation:** Namecheap publishes a minute or two after the write; the tool waits up to
  `--publish-timeout` seconds (default 300) for the new records on the authoritative server. Check with
  `dig +short <host> @dns1.registrar-servers.com`, not a public resolver, which caches the old answer.
- **Mutation safety:** `--apply` changes live DNS; per the namecheap-api rule it needs explicit go.
