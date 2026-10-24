# ABOUTME: Every Terraform root pins each registry module to its minor (~> X.Y.Z) and commits a lock that
# ABOUTME: records the root's own provider constraints, so a fresh `terraform init` resolves what was locked.
#
# .terraform.lock.hcl locks providers, not modules. With `~> 21.0` on the EKS module a fresh init picked up
# 21.29.0, whose aws floor (>= 6.59.0) the committed lock (aws 6.51.0) did not meet, and init failed on any
# machine without an older module cached in .terraform/modules (#468). A minor pin keeps the module, and so
# its provider floor, where the lock was generated. The fresh init itself is test_terraform_lock_init.py
# (E2E: it needs terraform and the registry).
import pathlib, re, subprocess, sys

REPO = pathlib.Path(__file__).resolve().parents[1]
failures = []


def check(n, c, detail=""):
    print(f"  {'PASS' if c else 'FAIL'}  {n}" + (f"\n        {detail}" if (detail and not c) else ""))
    if not c:
        failures.append(n)


MODULE = re.compile(r'^module\s+"([^"]+)"\s*\{(.*?)^\}', re.S | re.M)
SOURCE = re.compile(r'^\s*source\s*=\s*"([^"]+)"', re.M)
VERSION = re.compile(r'^\s*version\s*=\s*"([^"]+)"', re.M)
MINOR_PIN = re.compile(r"^~> \d+\.\d+\.\d+$")


def registry_modules(tf):
    """(name, source, version-or-None) for every module sourced from a registry, not a local path or git."""
    out = []
    for name, body in MODULE.findall(tf):
        src = SOURCE.search(body)
        if not src or src.group(1).startswith(("./", "../", "git::", "github.com/", "s3::", "http")):
            continue
        ver = VERSION.search(body)
        out.append((name, src.group(1), ver.group(1) if ver else None))
    return out


def required_providers(tf):
    """{source: constraint} from the terraform { required_providers { ... } } block."""
    m = re.search(r"required_providers\s*\{(.*?)\n  \}", tf, re.S)
    if not m:
        return {}
    return dict(re.findall(r'source\s*=\s*"([^"]+)"\s*\n\s*version\s*=\s*"([^"]+)"', m.group(1)))


def locked_constraints(lock):
    """{source: constraints-string} for every provider block in a .terraform.lock.hcl."""
    out = {}
    for src, body in re.findall(r'^provider\s+"registry\.terraform\.io/([^"]+)"\s*\{(.*?)^\}', lock, re.S | re.M):
        c = re.search(r'constraints\s*=\s*"([^"]*)"', body)
        out[src.lower()] = c.group(1) if c else ""
    return out


# The checker must reject the range that caused #468, or every PASS below means nothing.
print("the checker itself")
check("a `~> 21.0` module range is not a minor pin", not MINOR_PIN.match("~> 21.0"))
check("a `~> 21.29.0` module range is a minor pin", bool(MINOR_PIN.match("~> 21.29.0")))
check("a module without a version is found as unpinned",
      registry_modules('module "x" {\n  source = "terraform-aws-modules/vpc/aws"\n}\n') == [("x", "terraform-aws-modules/vpc/aws", None)])

tracked = subprocess.run(["git", "-C", str(REPO), "ls-files", "*.tf"], capture_output=True, text=True, check=True).stdout.split()
roots = sorted({str(pathlib.Path(f).parent) for f in tracked if not f.startswith(("images/", "gitops/"))})
check("found the Terraform roots", {"infra/terraform/aws/cluster", "infra/terraform/aws/network"} <= set(roots), roots)

for root in roots:
    d = REPO / root
    tf = "\n".join(p.read_text() for p in sorted(d.glob("*.tf")))
    print(root)
    mods = registry_modules(tf)
    for name, src, ver in mods:
        check(f"module {name} ({src}) is pinned to its minor", ver is not None and bool(MINOR_PIN.match(ver)),
              f"version = {ver!r}; use \"~> X.Y.Z\" and regenerate the lock with `terraform init -upgrade`")
    provs = required_providers(tf)
    if not (mods or provs):
        continue
    lock_path = d / ".terraform.lock.hcl"
    check("commits a .terraform.lock.hcl", lock_path.exists())
    if not lock_path.exists():
        continue
    locked = locked_constraints(lock_path.read_text())
    for src, want in provs.items():
        got = locked.get(src.lower())
        check(f"lock records {src} with the root's own constraint {want!r}",
              got is not None and want in [c.strip() for c in got.split(",")],
              f"lock constraints = {got!r}; regenerate with `terraform init -upgrade`")

if failures:
    print(f"\n{len(failures)} FAILED", file=sys.stderr)
    sys.exit(1)
print("\nALL TERRAFORM MODULE-PIN CHECKS GREEN")
