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

# Every legacy alias is gone: r1-1 with the round model (#142), a-NNN with #359, the shared roundN with
# #290. Every student is given the memorable name, so a second hostname per cluster was a second thing to
# get wrong. Asserted on the code, not on a comment saying so: the roster loop emits public_host_for and
# the service hosts derived from it, and nothing else.
_routes = re.search(r"^cmd_routes\(\) \{\n(.*?)^\}", src, re.S | re.M)
_routes_code = "\n".join(l for l in (_routes.group(1) if _routes else "").splitlines()
                          if not l.lstrip().startswith("#"))
check("the r1-1 alias is no longer emitted",
      bool(_routes) and "printf 'r%s-%s.agenticburn.com" not in _routes_code
      and not re.search(r"printf '(round|r)[%0-9]", _routes_code))
check("the a-NNN alias is no longer emitted",
      "printf 'a-%s.agenticburn.com" not in src)
# Retiring a hostname must not read to the shrink guard as losing one, or it refuses every publish and
# the only way past it is the flag that also switches the protection off.
check("the shrink guard discounts the retired rows through RETIRED_HOST_RE",
      'grep -Evc "${RETIRED_HOST_RE}"' in src and 'grep -Ev "${RETIRED_HOST_RE}"' in src)
# What counts as retired, asked of fleet.sh itself: the a-NNN and round* aliases, and no live host.
_out = subprocess.run(
    ["bash", "-c", f"source '{FLEET}' >/dev/null 2>&1; printf '%s\\n' \"$RETIRED_HOST_RE\"; "
     "for i in $(seq 1 999); do friendly_attendee_name $i; echo; done"],
    cwd=FLEET.parent, capture_output=True, text=True).stdout.splitlines()
_retired_re = re.compile(_out[0]) if _out and _out[0] else None
_memorable = [f"{n}.agenticburn.com" for n in _out[1:] if n]
check("fleet.sh defines RETIRED_HOST_RE", _retired_re is not None)
if _retired_re:
    check("the a-NNN and round* aliases are retired",
          all(_retired_re.search(h) for h in ("a-007.agenticburn.com", "round1.agenticburn.com",
                                               "roundadmin.agenticburn.com")))
    check("no live roster host is",
          not any(_retired_re.search(h) for h in ("attackme.agenticburn.com", "michael-admin.agenticburn.com",
                                                   "whitney-admin.agenticburn.com")))
    check(f"no memorable attendee host is ({len(_memorable)} checked)",
          len(_memorable) == 999 and not any(_retired_re.search(h) for h in _memorable))
# A comment that still maps a slot to a-NNN is how four sources came to disagree (#359): the next reader
# takes it as the name. The spec has to say the alias is retired, not leave it to a live curl sweep.
check("no fleet.sh comment still maps a cluster to an a-NNN host",
      re.search(r"-> a-(\d{3}|NNN)\.agenticburn\.com", src) is None)
check("BUILD-SPEC records a-NNN as retired, not an alias",
      "is retired, not an alias" in (REPO / "docs" / "BUILD-SPEC.md").read_text())

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
