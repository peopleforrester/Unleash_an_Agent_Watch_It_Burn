# ABOUTME: Guards the attendee hostname scheme: deterministic, collision-free, and computed by ONE
# ABOUTME: function so the routes table and the provisioning hand-out can never publish different names.
import pathlib
import re
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
FLEET = REPO / "infra" / "terraform" / "fleet" / "fleet.sh"
src = FLEET.read_text()

failures = []


def check(name, cond):
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        failures.append(name)


# One source of truth. `routes` publishes the hostname and `ingest` tells provisioning what to hand the
# student; if they computed it separately they would eventually disagree and the student would be given a
# URL the router does not serve.
check("routes and ingest both derive the hostname from public_host_for()",
      src.count("public_host_for") >= 3)  # definition + routes + ingest

check("the attendee URL handed out is https (the console terminates TLS)",
      'console_url="https://${pub_host}"' in src and 'arg cu "http://' not in src)

# The legacy alias emission is gone, but a-NNN survives as an alias so older links resolve.
check("the r1-1 alias is no longer emitted",
      "The raw \"r1-1\" alias is NO LONGER emitted" in src)
check("a-NNN is kept as a compatibility alias",
      "printf 'a-%s.agenticburn.com" in src)

# Determinism and collision-freedom, executed rather than assumed.
harness = r"""
%s
%s
for n in $(seq 1 384); do friendly_attendee_name "$n"; echo; done
""" % (
    re.search(r"readonly WIB_ADJECTIVES=\(.*?\)\n", src, re.S).group(0).replace("readonly ", ""),
    re.search(r"readonly WIB_ANIMALS=\(.*?\)\n.*?^friendly_attendee_name\(\) \{.*?^\}", src, re.S | re.M)
       .group(0).replace("readonly ", ""),
)
out = subprocess.run(["bash", "-c", harness], capture_output=True, text=True)
names = [n for n in out.stdout.split("\n") if n.strip()]
check("the generator runs", len(names) == 384)
check("384 slots produce 384 distinct names (no collisions)", len(set(names)) == len(names) == 384)
check("names are DNS-safe single labels", all(re.fullmatch(r"[a-z]+-[a-z]+", n) for n in names))
# Determinism: the same slot must always give the same name, or routes and ingest drift apart between runs.
out2 = subprocess.run(["bash", "-c", harness], capture_output=True, text=True)
check("generation is deterministic across runs", out2.stdout == out.stdout)

if failures:
    print(f"\nFAILED: {len(failures)} check(s)")
    sys.exit(1)
print("\nAll friendly-hostname checks passed.")
