# ABOUTME: Wires agenticburn.com demo URLs to cluster LoadBalancer hostnames via the Namecheap API.
# ABOUTME: Reads existing records first and MERGES (setHosts replaces all), so parking/apex survive.
#
# Namecheap setHosts is a MUTATION (changes live DNS). Default is --dry-run: it prints the exact
# record set it WOULD write and changes nothing. Pass --apply only with Michael's go, and only once
# the cluster LB hostnames exist. Credentials come from ~/secrets/dns/namecheap.env (never hardcoded).
#
# Usage:
#   python3 set-demo-dns.py burn=<lb-host> wall=<lb-host> haiku=<lb-host> ...
#   python3 set-demo-dns.py --apply burn=k8s-xxx.elb.us-west-2.amazonaws.com
#
# Each pair "sub=target" becomes a CNAME sub.agenticburn.com -> target (an AWS LB hostname).
import argparse
import os
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

ENDPOINT = "https://api.namecheap.com/xml.response"
DOMAIN = "agenticburn.com"


def load_env(path="~/secrets/dns/namecheap.env"):
    env = {}
    for ln in open(os.path.expanduser(path)):
        ln = ln.strip()
        if ln and not ln.startswith("#") and "=" in ln:
            k, v = ln.split("=", 1)
            env[k] = v
    return env


def call(env, command, extra=None):
    params = {
        "ApiUser": env["NAMECHEAP_API_USER"], "ApiKey": env["NAMECHEAP_API_KEY"],
        "UserName": env["NAMECHEAP_USERNAME"], "ClientIp": env["NAMECHEAP_CLIENT_IP"],
        "Command": command,
    }
    if extra:
        params.update(extra)
    raw = urllib.request.urlopen(ENDPOINT + "?" + urllib.parse.urlencode(params), timeout=30).read()
    raw = raw.decode().replace('xmlns="http://api.namecheap.com/xml.response"', "")
    root = ET.fromstring(raw)
    if root.attrib.get("Status") != "OK":
        err = root.find(".//Error")
        raise SystemExit(f"Namecheap {command} failed: {err.text if err is not None else raw[:300]}")
    return root


def get_hosts(env, sld, tld):
    root = call(env, "namecheap.domains.dns.getHosts", {"SLD": sld, "TLD": tld})
    out = []
    for h in root.iter("host"):
        a = h.attrib
        out.append({"Name": a.get("Name"), "Type": a.get("Type"),
                    "Address": a.get("Address"), "TTL": a.get("TTL", "1799")})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pairs", nargs="+", help="sub=target (CNAME sub.agenticburn.com -> target)")
    ap.add_argument("--apply", action="store_true", help="actually write DNS (default: dry-run)")
    args = ap.parse_args()

    sld, tld = DOMAIN.split(".", 1)
    env = load_env()
    existing = get_hosts(env, sld, tld)

    # Merge: upsert a CNAME per requested sub, keep every other existing record untouched.
    wanted = {}
    for p in args.pairs:
        if "=" not in p:
            raise SystemExit(f"bad pair (need sub=target): {p}")
        sub, target = p.split("=", 1)
        wanted[sub] = target.rstrip(".") + "."  # CNAME target must be FQDN-dotted
    merged = [r for r in existing if not (r["Type"] == "CNAME" and r["Name"] in wanted)]
    for sub, target in wanted.items():
        merged.append({"Name": sub, "Type": "CNAME", "Address": target, "TTL": "300"})

    print(f"=== resulting record set for {DOMAIN} ({len(merged)} records) ===")
    for r in merged:
        flag = "  <- demo URL" if r["Type"] == "CNAME" and r["Name"] in wanted else ""
        print(f"  {r['Type']:6} {r['Name']:24} -> {r['Address']}{flag}")

    if not args.apply:
        print("\n[dry-run] nothing written. Re-run with --apply (and Michael's go) to set these.")
        return

    extra = {"SLD": sld, "TLD": tld}
    for i, r in enumerate(merged, 1):
        extra[f"HostName{i}"] = r["Name"]
        extra[f"RecordType{i}"] = r["Type"]
        extra[f"Address{i}"] = r["Address"]
        extra[f"TTL{i}"] = r["TTL"]
    call(env, "namecheap.domains.dns.setHosts", extra)
    print(f"\nAPPLIED. {len(merged)} records written to {DOMAIN}.")


if __name__ == "__main__":
    main()
