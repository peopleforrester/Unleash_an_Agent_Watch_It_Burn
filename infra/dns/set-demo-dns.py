# ABOUTME: Upserts records on a Namecheap zone (agenticburn.com by default) by read-modify-write, because
# ABOUTME: setHosts replaces the whole zone. Replays EmailType and MXPref, POSTs, backs up, diffs and digs MX.
#
# Namecheap setHosts is a MUTATION (changes live DNS). Default is a dry run: it reads the zone and prints
# the exact record set it WOULD write and changes nothing. Pass --apply only with Michael's go.
# Credentials come from ~/secrets/dns/namecheap.env (never hardcoded).
#
# Usage:
#   python3 set-demo-dns.py [--domain agenticburn.com] [--apply] [TYPE:]name=value ...
#   python3 set-demo-dns.py monitoring=xyz.up.railway.app TXT:_railway-verify.monitoring=railway-verify=abc
#
# TYPE is CNAME (the default), A or TXT. name is relative to the domain ("*" for the wildcard).
#
# --apply follows the four steps of the namecheap skill's dns-safety.md, and refuses to write if it
# cannot do one of them (#581):
#   1. getHosts immediately before the write, saved to --backup-dir before anything is sent.
#   2. Every existing record is replayed with its MXPref, and the zone's EmailType is sent back. An
#      omitted EmailType resets the mail configuration, and agenticburn.com's mail is Namecheap
#      forwarding (EmailType FWD), which keeps no MX in the host list at all.
#   3. setHosts is a url-encoded POST, never a GET query string.
#   4. After the write the zone is read again and diffed, and MX is checked with dig against an
#      authoritative server before and after, once the new records are published.
import argparse
import datetime
import os
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

ENDPOINT = "https://api.namecheap.com/xml.response"
DEFAULT_DOMAIN = "agenticburn.com"
AUTHORITATIVE = "dns1.registrar-servers.com"
TYPES = ("CNAME", "A", "TXT")
TTL = "300"
# The records an upsert of each type replaces at its name. A CNAME must be the only record at its name,
# so it replaces everything there; an A or TXT also replaces a same-name CNAME, which would conflict.
REPLACES = {"CNAME": None, "A": {"A", "CNAME", "ALIAS", "URL", "URL301", "FRAME"}, "TXT": {"TXT", "CNAME"}}
MAIL_TYPES = {"MX", "MXE"}


def load_env(path="~/secrets/dns/namecheap.env"):
    env = {}
    for ln in open(os.path.expanduser(path)):
        ln = ln.strip()
        if ln and not ln.startswith("#") and "=" in ln:
            k, v = ln.split("=", 1)
            env[k] = v
    return env


def post(params):
    # POST, not a hand-built GET: a large zone makes a very long URL, and DKIM values are base64 with
    # + and /, which a query string corrupts silently.
    data = urllib.parse.urlencode(params).encode()
    with urllib.request.urlopen(urllib.request.Request(ENDPOINT, data=data), timeout=90) as r:
        return r.read().decode()


def dig(qtype, fqdn, server=AUTHORITATIVE):
    """The answers an authoritative server gives, normalised; None when dig cannot be run."""
    try:
        p = subprocess.run(["dig", "+short", qtype, fqdn, f"@{server}"],
                           capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if p.returncode != 0:
        return None
    answers = set()
    for line in p.stdout.splitlines():
        line = line.strip()
        if not line or line.startswith(";"):
            continue
        if qtype == "TXT":
            line = "".join(re.findall(r'"((?:[^"\\]|\\.)*)"', line))
        else:
            line = line.rstrip(".").lower()
        answers.add(line)
    return answers


class Namecheap:
    def __init__(self, env, transport=post):
        self.auth = {"ApiUser": env["NAMECHEAP_API_USER"], "ApiKey": env["NAMECHEAP_API_KEY"],
                     "UserName": env["NAMECHEAP_USERNAME"], "ClientIp": env["NAMECHEAP_CLIENT_IP"]}
        self.transport = transport

    def call(self, command, extra):
        raw = self.transport({**self.auth, "Command": command, **extra})
        root = ET.fromstring(raw)
        ns = {"n": root.tag.split("}")[0].strip("{")} if root.tag.startswith("{") else {"n": ""}
        if root.attrib.get("Status") != "OK":
            errs = [e.text for e in root.iter() if e.tag.endswith("Error") and (e.text or "").strip()]
            raise SystemExit(f"Namecheap {command} failed: {errs[0] if errs else raw[:300]}")
        return raw, root, ns

    def get_hosts(self, sld, tld):
        """(raw XML, host records with every attribute, EmailType, IsUsingOurDNS)."""
        raw, root, ns = self.call("namecheap.domains.dns.getHosts", {"SLD": sld, "TLD": tld})
        res = root.find(".//n:DomainDNSGetHostsResult", ns)
        if res is None:
            raise SystemExit("getHosts returned no DomainDNSGetHostsResult; refusing to go on")
        hosts = [dict(h.attrib) for h in res.findall("n:host", ns)]
        return raw, hosts, res.attrib.get("EmailType"), res.attrib.get("IsUsingOurDNS")

    def set_hosts(self, sld, tld, hosts, email_type):
        self.call("namecheap.domains.dns.setHosts", set_hosts_params(sld, tld, hosts, email_type))


def set_hosts_params(sld, tld, hosts, email_type):
    params = {"SLD": sld, "TLD": tld, "EmailType": email_type}
    for i, h in enumerate(hosts, 1):
        params[f"HostName{i}"] = h["Name"]
        params[f"RecordType{i}"] = h["Type"]
        params[f"Address{i}"] = h["Address"]
        params[f"TTL{i}"] = h.get("TTL") or "1800"
        if h["Type"] in MAIL_TYPES:
            if h.get("MXPref") in (None, ""):
                raise SystemExit(f"{h['Type']} record {h['Name']} has no MXPref to replay; refusing to write")
            params[f"MXPref{i}"] = h["MXPref"]
    return params


def split_domain(domain):
    domain = domain.strip().strip(".").lower()
    if "." not in domain:
        raise SystemExit(f"--domain must be a registered domain such as agenticburn.com, not {domain!r}")
    return domain, *domain.split(".", 1)


def parse_records(specs, domain):
    """[TYPE:]name=value -> {name: [(type, value)]}, refusing what the upsert cannot do safely."""
    wanted = {}
    for spec in specs:
        if "=" not in spec:
            raise SystemExit(f"bad record (need [TYPE:]name=value): {spec}")
        lhs, value = spec.split("=", 1)
        rtype, name = lhs.split(":", 1) if ":" in lhs else ("CNAME", lhs)
        rtype, name, value = rtype.upper(), name.strip().lower(), value.strip()
        if rtype not in TYPES:
            raise SystemExit(f"unsupported type {rtype} in {spec} (supported: {', '.join(TYPES)})")
        if name.endswith("." + domain):
            name = name[: -len(domain) - 1]
        if name in ("", "@", domain):
            raise SystemExit("refusing to touch the apex (@): it holds the router, SPF and the mail "
                             "configuration; edit it by hand")
        if not value:
            raise SystemExit(f"empty value in {spec}")
        if rtype == "CNAME":
            value = value.rstrip(".") + "."  # CNAME target must be FQDN-dotted
        wanted.setdefault(name, []).append((rtype, value))
    for name, recs in wanted.items():
        types = {t for t, _ in recs}
        if "CNAME" in types and len(recs) > 1:
            raise SystemExit(f"{name}: a CNAME must be the only record at its name")
    return wanted


def merge(existing, wanted):
    """(the record set to write, the existing records it replaces, the records it adds)."""
    replaced = []
    for r in existing:
        if r["Name"].lower() not in wanted:
            continue
        for rtype, _ in wanted[r["Name"].lower()]:
            kinds = REPLACES[rtype]
            if kinds is None or r["Type"] in kinds:
                replaced.append(r)
                break
    for r in replaced:
        if r["Type"] in MAIL_TYPES:
            raise SystemExit(f"refusing to replace {r['Type']} record at {r['Name']}: it carries mail")
    kept = [r for r in existing if not any(r is x for x in replaced)]
    added = [{"Name": n, "Type": t, "Address": v, "TTL": TTL} for n, recs in wanted.items() for t, v in recs]
    return kept + added, replaced, added


def key(r):
    addr = r["Address"]
    if r["Type"] in ("CNAME", "MX", "ALIAS", "NS"):
        addr = addr.rstrip(".").lower()
    return (r["Type"], r["Name"].lower(), addr, r.get("MXPref") if r["Type"] in MAIL_TYPES else None)


def fqdn(name, domain):
    return domain if name == "@" else f"{name}.{domain}"


def published(wanted, domain, dig_fn):
    for name, recs in wanted.items():
        for rtype in {t for t, _ in recs}:
            want = {v.rstrip(".").lower() if rtype == "CNAME" else v for t, v in recs if t == rtype}
            if dig_fn(rtype, fqdn(name, domain)) != want:
                return False
    return True


def backup(raw, backup_dir, domain, now):
    d = os.path.expanduser(backup_dir)
    os.makedirs(d, mode=0o700, exist_ok=True)
    path = os.path.join(d, f"{domain}-{now.strftime('%Y%m%dT%H%M%SZ')}-getHosts.xml")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(raw)
    return path


def run(argv, transport=post, dig_fn=dig, sleep=time.sleep, env_loader=load_env,
        now=lambda: datetime.datetime.now(datetime.timezone.utc)):
    ap = argparse.ArgumentParser(description="Upsert records on a Namecheap zone without losing the rest.")
    ap.add_argument("records", nargs="+", help="[TYPE:]name=value; TYPE is CNAME (default), A or TXT")
    ap.add_argument("--domain", default=DEFAULT_DOMAIN, help=f"Namecheap domain (default {DEFAULT_DOMAIN})")
    ap.add_argument("--apply", action="store_true", help="actually write DNS (default: dry run)")
    ap.add_argument("--env-file", default="~/secrets/dns/namecheap.env")
    ap.add_argument("--backup-dir", default="~/secrets/dns/backups", help="where the pre-write zone is saved")
    ap.add_argument("--publish-timeout", type=int, default=300,
                    help="seconds to wait for the new records on the authoritative server")
    args = ap.parse_args(argv)

    domain, sld, tld = split_domain(args.domain)
    wanted = parse_records(args.records, domain)
    nc = Namecheap(env_loader(args.env_file), transport)

    # Step 1: read immediately before the write. A zone changes from outside this session, and a
    # payload built from an older copy silently deletes whatever was added in between.
    raw, before, email_type, ours = nc.get_hosts(sld, tld)
    if ours is not None and ours.lower() != "true":
        raise SystemExit(f"{domain} is not on Namecheap DNS (IsUsingOurDNS={ours}); refusing")
    if not email_type:
        # Guessing a value is the reset this script exists to avoid.
        raise SystemExit(f"getHosts for {domain} returned no EmailType; refusing to write")
    merged, replaced, added = merge(before, wanted)

    print(f"=== {domain}: {len(before)} records now, EmailType={email_type} ===")
    for r in replaced:
        print(f"  replace {r['Type']:6} {r['Name']:28} {r['Address']}")
    print(f"=== resulting record set ({len(merged)} records) ===")
    for r in merged:
        flag = "  <- upserted" if any(r is a for a in added) else ""
        pref = f" (pref {r['MXPref']})" if r["Type"] in MAIL_TYPES else ""
        print(f"  {r['Type']:6} {r['Name']:28} -> {r['Address']}{pref}{flag}")
    set_hosts_params(sld, tld, merged, email_type)  # fails here, not after the backup, on a bad record

    if not args.apply:
        print("\n[dry-run] nothing written. Re-run with --apply (and Michael's go) to set these.")
        return 0

    mx_before = dig_fn("MX", domain)
    if mx_before is None:
        raise SystemExit(f"cannot run dig against {AUTHORITATIVE}, so MX cannot be checked; refusing")
    print(f"\nMX before (from {AUTHORITATIVE}): {sorted(mx_before) or 'none'}")
    saved = backup(raw, args.backup_dir, domain, now())
    print(f"backup: {saved}")

    # Steps 2 and 3: every record replayed, EmailType and MXPref included, as a POST.
    nc.set_hosts(sld, tld, merged, email_type)
    print("setHosts accepted. IsSuccess only means the request parsed; checking the zone.")

    # Step 4: diff the zone, then MX on the authoritative server once the change is live there.
    _, after, email_after, _ = nc.get_hosts(sld, tld)
    after_keys = {key(r) for r in after}
    lost = [r for r in before if not any(r is x for x in replaced) and key(r) not in after_keys]
    missing = [r for r in added if key(r) not in after_keys]
    problems = [f"LOST {r['Type']} {r['Name']} {r['Address']}" for r in lost]
    problems += [f"NOT WRITTEN {r['Type']} {r['Name']} {r['Address']}" for r in missing]
    if email_after != email_type:
        problems.append(f"EmailType changed from {email_type} to {email_after}")
    if problems:
        print("\n".join(["", "ZONE CHECK FAILED:"] + [f"  {p}" for p in problems]
                        + [f"  restore from {saved}"]), file=sys.stderr)
        return 1
    spf = sum(1 for r in after if r["Type"] == "TXT" and r["Address"].lower().startswith("v=spf1"))
    dkim = sum(1 for r in after if r["Type"] == "TXT" and "._domainkey" in f".{r['Name'].lower()}")
    print(f"zone: {len(after)} records, nothing lost, EmailType={email_after}, SPF {spf}, DKIM {dkim}")

    waited = 0
    while not published(wanted, domain, dig_fn):
        if waited >= args.publish_timeout:
            print(f"\nUNVERIFIED: the new records are not on {AUTHORITATIVE} after {waited}s, so MX "
                  f"cannot be checked yet. Re-check: dig +short MX {domain} @{AUTHORITATIVE}", file=sys.stderr)
            return 1
        sleep(15)
        waited += 15
    mx_after = dig_fn("MX", domain)
    if mx_after != mx_before:
        print(f"\nMX CHANGED: {sorted(mx_before)} -> {sorted(mx_after or [])}. Mail is affected; "
              f"restore from {saved}", file=sys.stderr)
        return 1
    print(f"published; MX unchanged: {sorted(mx_after) or 'none'}")
    print(f"\nAPPLIED. {len(merged)} records written to {domain}.")
    return 0


def main():
    sys.exit(run(sys.argv[1:]))


if __name__ == "__main__":
    main()
