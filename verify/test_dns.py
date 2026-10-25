# ABOUTME: Offline check of the Namecheap DNS tool against a fake zone: EmailType and MXPref replayed, POST,
# ABOUTME: backup before the write, diff and MX check after, conflicting records replaced, unsafe writes refused.
"""Why (#581). set-demo-dns.py called setHosts without the namecheap skill's dns-safety.md steps. It never sent
EmailType, and agenticburn.com's mail is Namecheap forwarding, which an omitted EmailType resets; it dropped
MXPref, wrote with a GET query string, kept no backup, never diffed, and left a same-name A or TXT beside the
CNAME it upserted. The fake zone below behaves the way dns-safety.md says Namecheap does: setHosts replaces
every record, and an omitted EmailType resets mail to plain MX with no MX records."""
import contextlib, importlib.util, io, os, pathlib, stat, sys, tempfile, urllib.parse
from xml.sax.saxutils import quoteattr

REPO = pathlib.Path(__file__).resolve().parents[1]
src = (REPO / "infra/dns/set-demo-dns.py").read_text()
readme = (REPO / "infra/dns/README.md").read_text()
spec = importlib.util.spec_from_file_location("set_demo_dns", REPO / "infra/dns/set-demo-dns.py")
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)  # safe: main() only on __main__
failures = []
def check(n, c, detail=""):
    print(f"  {'PASS' if c else 'FAIL'}  {n}" + (f"  [{detail}]" if detail and not c else ""))
    failures.append(n) if not c else None

ENV = {"NAMECHEAP_API_USER": "u", "NAMECHEAP_API_KEY": "k", "NAMECHEAP_USERNAME": "u", "NAMECHEAP_CLIENT_IP": "1.2.3.4"}
FORWARDING = {"eforward1.registrar-servers.com", "eforward2.registrar-servers.com", "eforward3.registrar-servers.com"}


def host(name, rtype, address, ttl="1800", pref="10"):
    return {"HostId": "1", "Name": name, "Type": rtype, "Address": address, "MXPref": pref, "TTL": ttl,
            "IsActive": "true"}


class FakeNamecheap:
    """A Namecheap zone: getHosts reads it, setHosts replaces it, dig answers from it once published."""
    def __init__(self, hosts, email_type="FWD", emit_email_type=True, drop_on_write=None, reset_mail=False):
        self.hosts, self.email_type = hosts, email_type
        self.emit_email_type, self.drop_on_write, self.reset_mail = emit_email_type, drop_on_write, reset_mail
        self.calls = []

    def transport(self, params):
        self.calls.append(dict(params))
        cmd = params["Command"]
        if cmd.endswith("getHosts"):
            et = f' EmailType="{self.email_type}"' if self.emit_email_type else ""
            rows = "".join("<host " + " ".join(f"{k}={quoteattr(v)}" for k, v in h.items()) + " />" for h in self.hosts)
            return ('<?xml version="1.0" encoding="utf-8"?><ApiResponse Status="OK" '
                    'xmlns="http://api.namecheap.com/xml.response"><CommandResponse Type="namecheap.domains.dns.getHosts">'
                    f'<DomainDNSGetHostsResult Domain="x"{et} IsUsingOurDNS="true">{rows}</DomainDNSGetHostsResult>'
                    '</CommandResponse></ApiResponse>')
        n, new = 1, []
        while f"HostName{n}" in params:
            new.append(host(params[f"HostName{n}"], params[f"RecordType{n}"], params[f"Address{n}"],
                            params[f"TTL{n}"], params.get(f"MXPref{n}", "10")))
            n += 1
        if self.drop_on_write:
            new = [h for h in new if h["Name"] != self.drop_on_write]
        self.hosts = new
        self.email_type = "MX" if ("EmailType" not in params or self.reset_mail) else params["EmailType"]
        return ('<?xml version="1.0"?><ApiResponse Status="OK" xmlns="http://api.namecheap.com/xml.response">'
                '<CommandResponse><DomainDNSSetHostsResult IsSuccess="true" /></CommandResponse></ApiResponse>')

    def dig(self, qtype, fqdn):
        domain = "agenticburn.com"
        if qtype == "MX" and fqdn == domain:
            if self.email_type == "FWD":
                return set(FORWARDING)
            return {h["Address"].rstrip(".").lower() for h in self.hosts if h["Type"] == "MX" and h["Name"] == "@"}
        name = fqdn[: -len(domain) - 1]
        return {h["Address"].rstrip(".").lower() if qtype == "CNAME" else h["Address"]
                for h in self.hosts if h["Type"] == qtype and h["Name"] == name}


def zone():
    return [host("@", "ALIAS", "apex.up.railway.app."), host("*", "CNAME", "wild.up.railway.app."),
            host("_acme-challenge", "CNAME", "authorize.railwaydns.net."),
            host("@", "TXT", "v=spf1 include:spf.efwd.registrar-servers.com ~all"),
            host("resend._domainkey", "TXT", "p=MIGfMA0GCSqGSIb3DQEBAQUAA4+/x=="),
            host("monitoring", "A", "192.0.2.10"), host("monitoring", "TXT", "old-verify")]


def run(fake, argv, backup_dir):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            rc = mod.run(argv + ["--backup-dir", backup_dir], transport=fake.transport, dig_fn=fake.dig,
                         sleep=lambda s: None, env_loader=lambda p: ENV)
        except SystemExit as e:
            rc = e.code if isinstance(e.code, int) else 2
            err.write(str(e.code))
    return rc, out.getvalue() + err.getvalue()


def sets(fake):
    return [c for c in fake.calls if c["Command"].endswith("setHosts")]


tmp = tempfile.mkdtemp()

# Dry run: reads, prints, writes nothing.
fake = FakeNamecheap(zone())
rc, out = run(fake, ["monitoring=svc.up.railway.app"], os.path.join(tmp, "dry"))
check("dry run exits 0 and writes nothing", rc == 0 and not sets(fake), out)
check("dry run shows the A and TXT it would replace", "replace A" in out and "replace TXT" in out, out)
check("dry run keeps no backup", not os.path.exists(os.path.join(tmp, "dry")))

# Apply on a forwarding zone.
fake = FakeNamecheap(zone() + [host("mail", "MX", "mx.example.net.", pref="20")])
before = [dict(h) for h in fake.hosts]
rc, out = run(fake, ["--apply", "monitoring=svc.up.railway.app",
                     "TXT:_railway-verify.monitoring=railway-verify=abc+/=="], os.path.join(tmp, "b1"))
check("apply exits 0", rc == 0, out)
w = sets(fake)
check("exactly one setHosts", len(w) == 1, len(w))
w = w[0] if w else {}
check("EmailType is sent back as read (FWD)", w.get("EmailType") == "FWD", w.get("EmailType"))
check("forwarding survives the write", fake.email_type == "FWD" and fake.dig("MX", "agenticburn.com") == FORWARDING)
mx_i = [k[len("HostName"):] for k, v in w.items() if k.startswith("HostName") and w.get("RecordType" + k[8:]) == "MX"]
check("MXPref is replayed on the MX record", mx_i and w.get(f"MXPref{mx_i[0]}") == "20", mx_i)
sent = {(w[f"RecordType{i}"], w[f"HostName{i}"], w[f"Address{i}"]) for i in range(1, 50) if f"HostName{i}" in w}
kept = {(h["Type"], h["Name"], h["Address"]) for h in before if h["Name"] != "monitoring"}
check("every record not being replaced is sent back verbatim", kept <= sent, kept - sent)
check("the same-name A and TXT are gone, the CNAME is there",
      ("A", "monitoring", "192.0.2.10") not in sent and ("TXT", "monitoring", "old-verify") not in sent
      and ("CNAME", "monitoring", "svc.up.railway.app.") in sent, sent)
check("the base64-ish TXT value is sent intact", ("TXT", "_railway-verify.monitoring", "railway-verify=abc+/==") in sent)
files = os.listdir(os.path.join(tmp, "b1")) if os.path.isdir(os.path.join(tmp, "b1")) else []
check("one backup of the pre-write getHosts response", len(files) == 1 and files[0].startswith("agenticburn.com-"), files)
if files:
    bp = os.path.join(tmp, "b1", files[0])
    check("the backup is mode 0600", stat.S_IMODE(os.stat(bp).st_mode) == 0o600)
    check("the backup holds the old A record", "192.0.2.10" in open(bp).read())
gets = [i for i, c in enumerate(fake.calls) if c["Command"].endswith("getHosts")]
seti = [i for i, c in enumerate(fake.calls) if c["Command"].endswith("setHosts")]
check("getHosts runs right before and again after the write", gets and seti and gets[0] < seti[0] < gets[-1])
check("it reports the MX check", "MX unchanged" in out, out)

# A write that loses a record fails loudly and points at the backup.
fake = FakeNamecheap(zone(), drop_on_write="resend._domainkey")
rc, out = run(fake, ["--apply", "grafana=svc.up.railway.app"], os.path.join(tmp, "b2"))
check("a lost DKIM record fails the run", rc == 1 and "LOST TXT resend._domainkey" in out and "restore from" in out, out)

# A write after which Namecheap resets mail fails loudly.
fake = FakeNamecheap(zone(), reset_mail=True)
rc, out = run(fake, ["--apply", "grafana=svc.up.railway.app"], os.path.join(tmp, "b3"))
check("an EmailType reset fails the run", rc == 1 and "EmailType changed from FWD to MX" in out, out)

# Refusals: nothing is written.
for name, fk, argv in [
    ("the apex", FakeNamecheap(zone()), ["--apply", "@=x.example.net"]),
    ("the apex by full name", FakeNamecheap(zone()), ["--apply", "agenticburn.com=x.example.net"]),
    ("a CNAME over an MX", FakeNamecheap(zone() + [host("mail", "MX", "mx.example.net.")]), ["--apply", "mail=x.example.net"]),
    ("a zone whose getHosts shows no EmailType", FakeNamecheap(zone(), emit_email_type=False), ["--apply", "grafana=x.example.net"]),
    ("a CNAME alongside another record at one name", FakeNamecheap(zone()), ["--apply", "g=x.example.net", "TXT:g=v"]),
    ("an unsupported type", FakeNamecheap(zone()), ["--apply", "MX:g=x.example.net"]),
]:
    rc, out = run(fk, argv, os.path.join(tmp, "refuse"))
    check(f"refuses {name}", rc != 0 and not sets(fk), out)
fk = FakeNamecheap(zone())
fk.dig = lambda q, f: None
rc, out = run(fk, ["--apply", "grafana=x.example.net"], os.path.join(tmp, "nodig"))
check("refuses to write when dig cannot check MX", rc != 0 and not sets(fk) and "dig" in out, out)

# The domain is an argument.
fake = FakeNamecheap(zone())
rc, out = run(fake, ["--domain", "example.co.uk", "g=x.example.net"], os.path.join(tmp, "dom"))
check("--domain sets SLD and TLD", fake.calls and fake.calls[0]["SLD"] == "example" and fake.calls[0]["TLD"] == "co.uk",
      fake.calls[:1])

# The real transport is a url-encoded POST to the bare endpoint.
seen = {}
class _Resp(io.BytesIO):
    def __enter__(self): return self
    def __exit__(self, *a): return False
def _urlopen(req, timeout=None):
    seen["url"], seen["data"] = req.full_url, req.data
    return _Resp(b"<ApiResponse/>")
real = mod.urllib.request.urlopen
mod.urllib.request.urlopen = _urlopen
try:
    mod.post({"Command": "namecheap.domains.dns.setHosts", "Address1": "a+b/c=="})
finally:
    mod.urllib.request.urlopen = real
check("the request is a POST to the endpoint with no query string", seen.get("url") == mod.ENDPOINT and seen.get("data"))
check("the body is url-encoded, so + and / survive",
      urllib.parse.parse_qs((seen.get("data") or b"").decode()).get("Address1") == ["a+b/c=="])

check("credentials read from the env file (not hardcoded)", "namecheap.env" in src)
check("no hardcoded long secret literal", not any(len(w) >= 25 and w.isalnum() for w in src.split('"')))
check("README documents --domain, the record syntax and EmailType",
      all(s in readme for s in ("--domain", "TXT:", "EmailType")))
check("README no longer lists per-cluster CNAMEs to load balancers", "burn.agenticburn.com" not in readme)

if failures: print(f"\nFAILED: {len(failures)}"); sys.exit(1)
print("\nAll DNS-tool checks passed.")
