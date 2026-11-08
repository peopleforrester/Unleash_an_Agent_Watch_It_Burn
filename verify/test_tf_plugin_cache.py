# ABOUTME: Offline check of verify/tf_plugin_cache.py (#1114, #1119): the provider mirror is filled through the artifact
# ABOUTME: cache by each lock's zh: SHA-256 and refuses what the lock does not vouch for, and every terraform init uses it.
"""Offline: no network and no terraform. The real inits against the mirror are test_terraform_lock_init.py,
test_terraform_plugin_cache_lock.py and test_terraform_mirror_lock.py in the tools tier.

#1114 moved the plugin cache out of the checkout. #1119 serves the providers themselves from the host artifact cache:
tf_plugin_cache.fill() reads each lock, looks up this platform's zip once (the registry's answer is used only when its
SHA-256 is a zh: hash the lock records), fetches it through artifact_cache.get(), and links it into a filesystem mirror
that the CLI config makes terraform's only source for registry.terraform.io. The registry and the download are stubs
here, with a made-up provider whose zip bytes this test makes, so each refusal is shown with nothing fetched.

It also holds the call sites: every file under verify/ that runs a real terraform init goes through
tf_plugin_cache.terraform_env, every workflow that runs one fills the mirror outside the workspace first, and none sets
a plugin cache of its own.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import pathlib
import re
import subprocess
import sys
import zipfile

import yaml

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(HERE))
import artifact_cache  # noqa: E402
import tf_plugin_cache as tpc  # noqa: E402

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail and not ok else ""))
    if not ok:
        failures.append(name)


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def zip_of(body: bytes) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(zipfile.ZipInfo("terraform-provider-x_v1", date_time=(2026, 11, 8, 0, 0, 0)), body)
    return buf.getvalue()


PLAT = "linux_amd64"
ONE, TWO, OTHER = zip_of(b"one\n"), zip_of(b"two\n"), zip_of(b"other platform\n")
LOCK_A = (f'provider "registry.terraform.io/wib-test/one" {{\n  version     = "1.0.0"\n  constraints = "1.0.0"\n'
          f'  hashes = [\n    "h1:AAAA=",\n    "zh:{sha(OTHER)}",\n    "zh:{sha(ONE)}",\n  ]\n}}\n\n'
          f'provider "registry.terraform.io/wib-test/two" {{\n  version = "2.0.0"\n'
          f'  hashes = [\n    "zh:{sha(TWO)}",\n  ]\n}}\n')
# A second lock pinning one of the same versions: filled once.
LOCK_B = f'provider "registry.terraform.io/wib-test/two" {{\n  version = "2.0.0"\n  hashes = [\n    "zh:{sha(TWO)}",\n  ]\n}}\n'
ZIPS = {"one": ONE, "two": TWO}


class Stubs:
    def __init__(self, answers: dict[str, str] | None = None, serve: dict[str, bytes] | None = None):
        self.lookups: list[str] = []
        self.fetches: list[str] = []
        self.answers = answers if answers is not None else {k: sha(v) for k, v in ZIPS.items()}
        self.serve = serve if serve is not None else ZIPS

    def meta(self, url: str) -> dict:
        self.lookups.append(url)
        typ, version = url.split("/")[-5], url.split("/")[-4]
        return {"shasum": self.answers[typ], "filename": f"terraform-provider-{typ}_{version}_{PLAT}.zip",
                "download_url": f"https://dl.example.invalid/{typ}/{version}.zip"}

    def fetch(self, url: str, out) -> None:
        self.fetches.append(url)
        out.write(self.serve[url.split("/")[-2]])


def no_network(*_a):
    raise AssertionError("went to the network")


def refusal(fn) -> str:
    try:
        fn()
    except tpc.CacheError as e:
        return str(e)
    return ""


def locks(tmp: pathlib.Path, **texts: str) -> list[pathlib.Path]:
    out = []
    for name, text in texts.items():
        p = tmp / name / ".terraform.lock.hcl"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
        out.append(p)
    return out


with tpc.scratch("tf-plugin-cache-test-") as td:
    out = pathlib.Path(td)

    print("== the plugin cache and the mirror sit in the host artifact cache, outside every worktree ==")
    for var, want in (("HECATON_TOOLS_CACHE", out / "hecaton"), ("WIB_ARTIFACT_CACHE", out / "wib"),
                      ("XDG_CACHE_HOME", out / "xdg/wib-artifacts"), ("HOME", out / "home/.cache/wib-artifacts")):
        env = {"HECATON_TOOLS_CACHE": {"HECATON_TOOLS_CACHE": str(out / "hecaton")},
               "WIB_ARTIFACT_CACHE": {"WIB_ARTIFACT_CACHE": str(out / "wib")},
               "XDG_CACHE_HOME": {"XDG_CACHE_HOME": str(out / "xdg")},
               "HOME": {"HOME": str(out / "home")}}[var]
        got = tpc.ensure(env)
        check(f"from {var}: <root>/terraform-plugin-cache, created", got == (want / "terraform-plugin-cache").resolve()
              and got.is_dir(), str(got))
    check("TF_PLUGIN_CACHE_DIR no longer names it: the cache is the artifact root's",
          tpc.ensure({"TF_PLUGIN_CACHE_DIR": str(out / "given"), "WIB_ARTIFACT_CACHE": str(out / "wib")})
          == (out / "wib/terraform-plugin-cache").resolve())
    err = refusal(lambda: tpc.ensure({"WIB_ARTIFACT_CACHE": str(REPO / "tmp" / "artifacts-test-1119")}))
    check("a root inside the worktree is refused, naming the worktree", f"inside the git worktree {REPO}" in err, err)
    check("and nothing is created there", not (REPO / "tmp" / "artifacts-test-1119").exists())
    check("a HOME inside the worktree is refused, not passed over",
          "inside the git worktree" in refusal(lambda: tpc.ensure({"HOME": str(REPO / "tmp" / "home")})))
    check("with nothing set there is no cache", "no cache root" in refusal(lambda: tpc.ensure({})))
    ro = out / "readonly"
    (ro / tpc.PLUGIN_SUBDIR).mkdir(parents=True)
    (ro / tpc.PLUGIN_SUBDIR).chmod(0o555)
    try:
        err = refusal(lambda: tpc.ensure({"WIB_ARTIFACT_CACHE": str(ro)}))
    finally:
        (ro / tpc.PLUGIN_SUBDIR).chmod(0o755)
    check("a plugin cache that is not writable is refused", "is not writable" in err, err)
    r = subprocess.run([sys.executable, str(HERE / "tf_plugin_cache.py")], capture_output=True, text=True,
                       env={"PATH": os.environ["PATH"], "WIB_ARTIFACT_CACHE": str(out / "cli")})
    check("as a script it prints the plugin cache it created",
          r.returncode == 0 and r.stdout == f"{(out / 'cli/terraform-plugin-cache').resolve()}\n", r.stdout + r.stderr)
    r = subprocess.run([sys.executable, str(HERE / "tf_plugin_cache.py")], capture_output=True, text=True,
                       env={"PATH": os.environ["PATH"], "WIB_ARTIFACT_CACHE": str(REPO / "tmp" / "cli-1119")})
    check("and exits 1 with one line of reason when it cannot", r.returncode == 1 and r.stdout == ""
          and r.stderr.startswith("TERRAFORM PROVIDER CACHE UNUSABLE: ") and r.stderr.count("\n") == 1,
          r.stdout + r.stderr)

    print("== a cold fill looks up and fetches each locked zip once, through the artifact cache ==")
    root = out / "artifacts"
    a, b = locks(out / "locks", a=LOCK_A, b=LOCK_B)
    s = Stubs()
    env = {"WIB_ARTIFACT_CACHE": str(root), "TF_PLUGIN_CACHE_MAY_BREAK_DEPENDENCY_LOCK_FILE": "true"}
    got = tpc.terraform_env(env, [a, b], fetch_meta=s.meta, fetch=s.fetch, plat=PLAT)
    check("one lookup and one fetch per provider version, the shared one once",
          len(s.lookups) == 2 and len(s.fetches) == 2, f"{s.lookups} {s.fetches}")
    check("the lookup is the registry's download API for this platform",
          s.lookups[0] == "https://registry.terraform.io/v1/providers/wib-test/one/1.0.0/download/linux/amd64",
          s.lookups[0])
    for typ, ver in (("one", "1.0.0"), ("two", "2.0.0")):
        link = tpc.mirror_dir(root) / "registry.terraform.io/wib-test" / typ / f"terraform-provider-{typ}_{ver}_{PLAT}.zip"
        check(f"{typ}: the mirror's zip links to the artifact cache entry for its SHA-256",
              link.is_symlink() and link.resolve() == root / "sha256" / sha(ZIPS[typ]), str(link))
    log = artifact_cache.fetch_log_path(root, {})
    check("each fetch is a line in the artifact cache's fetch log", len(log.read_text().splitlines()) == 2)
    check("the env names the config and the root's plugin cache",
          got["TF_CLI_CONFIG_FILE"] == str(tpc.config_path(root))
          and got["TF_PLUGIN_CACHE_DIR"] == str(tpc.plugin_cache(root).resolve()))
    check("and drops TF_PLUGIN_CACHE_MAY_BREAK_DEPENDENCY_LOCK_FILE", "TF_PLUGIN_CACHE_MAY_BREAK_DEPENDENCY_LOCK_FILE"
          not in got)
    cfg = pathlib.Path(got["TF_CLI_CONFIG_FILE"]).read_text()
    check("the config installs registry.terraform.io providers from the mirror and from nowhere else",
          f'path    = "{tpc.mirror_dir(root)}"' in cfg and cfg.count('["registry.terraform.io/*/*"]') == 2
          and re.search(r'filesystem_mirror \{[^}]*include = \["registry\.terraform\.io/\*/\*"\]', cfg)
          and re.search(r'direct \{\s*exclude = \["registry\.terraform\.io/\*/\*"\]', cfg)
          and "plugin_cache_dir" not in cfg, cfg)

    print("== a warm fill makes no lookup and no fetch ==")
    tpc.terraform_env({"WIB_ARTIFACT_CACHE": str(root)}, [a, b], fetch_meta=no_network, fetch=no_network, plat=PLAT)
    check("no lookup, no fetch, the fetch log unchanged", len(log.read_text().splitlines()) == 2)

    print("== what the lock does not vouch for is refused, and nothing is fetched for it ==")
    lone = locks(out / "locks-lone", c=LOCK_B)
    r2 = out / "refuse-registry"
    s = Stubs(answers={"two": sha(OTHER)})
    err = refusal(lambda: tpc.fill(lone, r2, plat=PLAT, fetch_meta=s.meta, fetch=s.fetch))
    check("a registry answer whose SHA-256 the lock does not record", f"has SHA-256 {sha(OTHER)}, which is not one of "
          "the 1 zh: hashes" in err and "so it is not fetched" in err, err)
    check("nothing fetched, no index entry, no mirror link", not s.fetches and not (r2 / "sha256").exists()
          and not (r2 / tpc.PROVIDERS_SUBDIR).exists())
    r3 = out / "refuse-download"
    s = Stubs(serve={"two": OTHER})
    err = refusal(lambda: tpc.fill(lone, r3, plat=PLAT, fetch_meta=s.meta, fetch=s.fetch))
    check("a download whose bytes do not match the lock's zh:", f"expected SHA-256 {sha(TWO)}, got {sha(OTHER)}" in err
          and "wib-test/two 2.0.0" in err, err)
    check("nothing in the cache or the mirror for it", not (r3 / "sha256" / sha(TWO)).exists()
          and not tpc.mirror_dir(r3).exists())
    entry = root / "sha256" / sha(ONE)
    entry.write_bytes(ONE + b"changed")
    err = refusal(lambda: tpc.fill([a], root, plat=PLAT, fetch_meta=no_network, fetch=no_network))
    check("a cache entry whose bytes changed, naming both sums, with no download",
          f"expected SHA-256 {sha(ONE)}, got {sha(ONE + b'changed')}" in err, err)
    check("the changed entry is left for a person to look at", entry.read_bytes() == ONE + b"changed")
    entry.write_bytes(ONE)
    idx = root / tpc.PROVIDERS_SUBDIR / "index/registry.terraform.io/wib-test/two" / f"terraform-provider-two_2.0.0_{PLAT}.zip.json"
    saved = idx.read_text()
    idx.write_text(json.dumps({"sha256": sha(OTHER), "url": "https://dl.example.invalid/two/2.0.0.zip"}))
    err = refusal(lambda: tpc.fill(lone, root, plat=PLAT, fetch_meta=no_network, fetch=no_network))
    check("an index entry naming a SHA-256 the lock does not record", f"names SHA-256 {sha(OTHER)}" in err
          and "nothing is served from it" in err, err)
    idx.write_text(saved)
    nozh = locks(out / "locks-nozh", d='provider "registry.terraform.io/wib-test/three" {\n  version = "3.0.0"\n'
                                        '  hashes = [\n    "h1:AAAA=",\n  ]\n}\n')
    err = refusal(lambda: tpc.fill(nozh, out / "nozh", plat=PLAT, fetch_meta=no_network, fetch=no_network))
    check("a lock with no zh: hashes, which nothing can be checked against", "records no zh: hashes" in err, err)
    other_host = [tpc.Locked("registry.opentofu.org/hashicorp/aws", "6.0.0", frozenset({sha(ONE)}), "x")]
    err = refusal(lambda: tpc.fill(other_host, out / "host", plat=PLAT, fetch_meta=no_network, fetch=no_network))
    check("a provider on another host is not mirrored", "only registry.terraform.io providers are mirrored" in err, err)
    bad = Stubs()
    bad.meta = lambda url: {"shasum": sha(TWO), "filename": "terraform-provider-two_2.0.0_darwin_arm64.zip",
                            "download_url": "https://dl.example.invalid/two/2.0.0.zip"}
    err = refusal(lambda: tpc.fill(lone, out / "wrong-name", plat=PLAT, fetch_meta=bad.meta, fetch=no_network))
    check("a registry answer for another platform's zip", "want terraform-provider-two_2.0.0_linux_amd64.zip" in err, err)

    print("== a caller's prepared config is checked, never filled again ==")
    prepared = {"TF_CLI_CONFIG_FILE": str(tpc.config_path(root)), "TF_PLUGIN_CACHE_DIR": str(out / "pc")}
    got = tpc.terraform_env(prepared, [a], fetch_meta=no_network, fetch=no_network, plat=PLAT)
    check("one this module wrote is taken as it is", got["TF_CLI_CONFIG_FILE"] == prepared["TF_CLI_CONFIG_FILE"]
          and got["TF_PLUGIN_CACHE_DIR"] == str(out / "pc"))
    foreign = out / "foreign.tfrc"
    foreign.write_text('provider_installation {\n  direct {}\n}\n')
    err = refusal(lambda: tpc.terraform_env({**prepared, "TF_CLI_CONFIG_FILE": str(foreign)}))
    check("a config this module did not write is refused", "is not a config verify/tf_plugin_cache.py wrote" in err, err)
    inside = out / "inside.tfrc"
    inside.write_text(tpc.render_config(REPO / "tmp" / "mirror-1119"))
    err = refusal(lambda: tpc.terraform_env({**prepared, "TF_CLI_CONFIG_FILE": str(inside)}))
    check("a config whose mirror is inside the worktree is refused", "provider mirror" in err
          and "inside the git worktree" in err, err)
    err = refusal(lambda: tpc.terraform_env({"TF_CLI_CONFIG_FILE": prepared["TF_CLI_CONFIG_FILE"]}))
    check("a config with no TF_PLUGIN_CACHE_DIR beside it is refused", "TF_PLUGIN_CACHE_DIR is not" in err, err)
    err = refusal(lambda: tpc.terraform_env({**prepared, "TF_PLUGIN_CACHE_DIR": str(REPO / "tmp" / "pc-1119")}))
    check("a plugin cache inside the worktree is refused", "inside the git worktree" in err, err)
check("the scratch directory is gone when the test is done with it", not out.exists())

print("== every committed lock can fill the mirror ==")
listed = subprocess.run(["git", "-C", str(REPO), "ls-files", "*.terraform.lock.hcl"], capture_output=True, text=True,
                        check=True).stdout.split()
check("committed_locks() is every lock git tracks", [str(p.relative_to(REPO)) for p in tpc.committed_locks()]
      == sorted(listed), f"{tpc.committed_locks()} vs {listed}")
for p in tpc.read_locks(tpc.committed_locks()):
    check(f"{p.lock}: {p.address} {p.version} is on registry.terraform.io and records zh: hashes",
          p.parts[0] == "registry.terraform.io" and len(p.zh) > 0)

print("== every terraform init under verify/ takes its providers from the mirror ==")
# The files that run a real terraform init, each through tf_plugin_cache.terraform_env.
REAL = ["iam_plan_render.py", "test_control_plane_app_ports_module.py", "test_lab_platform_operator_entry.py",
        "test_plan_policy_e2e.py", "test_terraform_lock_init.py", "test_terraform_mirror_lock.py",
        "test_terraform_plugin_cache_lock.py"]
# The ones whose terraform is a stub that installs nothing, or that only name an init in a message.
STUBBED = ["test_audit_import_state.py", "test_drift_report.py", "test_event_tag.py", "test_iam_plan_render_cache.py",
           "test_terraform_lock_init_retry.py", "test_terraform_module_pins.py", "test_tf_plugin_cache.py"]
# test_preflight_boundary.sh holds the command text fleet.sh prints for a person to run; it runs no terraform.
SHELL_TEXT_ONLY = ["test_preflight_boundary.sh"]
RUNS_TERRAFORM = re.compile(r'TERRAFORM|terraform_binary\(|which\("terraform"\)|"terraform"')
INIT = re.compile(r'"init"|\binit -')
found = sorted(p.name for p in HERE.glob("*.py") if RUNS_TERRAFORM.search(t := p.read_text()) and INIT.search(t))
unknown = [n for n in found if n not in REAL + STUBBED]
check("no file runs terraform init that this test does not know of", not unknown,
      f"{unknown}: add it to REAL (and give its terraform tf_plugin_cache.terraform_env) or STUBBED")
for name in REAL:
    text = (HERE / name).read_text()
    check(f"{name}: its terraform env comes from tf_plugin_cache.terraform_env", "tf_plugin_cache.terraform_env(" in text
          or "tpc.terraform_env(" in text)
    # The two that tamper with a plugin cache use a scratch one of their own, outside the checkout.
    if name not in ("test_terraform_plugin_cache_lock.py", "test_terraform_mirror_lock.py"):
        check(f"{name}: it sets no plugin cache of its own", '"TF_PLUGIN_CACHE_DIR"' not in text)
shells = [p.name for p in HERE.glob("*.sh") if re.search(r"^[^#]*\bterraform\b.*\binit\b", p.read_text(), re.M)
          and p.name not in SHELL_TEXT_ONLY]
check("no verify/ shell script runs terraform init", not shells, str(shells))
lock_init = (HERE / "test_terraform_lock_init.py").read_text()
check("the lock-init test fills exactly the locks it inits against",
      'tf_plugin_cache.terraform_env(env, [REPO / r / ".terraform.lock.hcl" for r in ROOTS])' in lock_init)
check("each of its inits is still -lockfile=readonly in a new empty directory",
      '"init", "-lockfile=readonly"' in lock_init and "tempfile.TemporaryDirectory(" in lock_init)
check("and it fails an init in which terraform downloaded a provider", '"(signed by" not in r.stdout' in lock_init)
check("nothing under verify/ sets TF_PLUGIN_CACHE_MAY_BREAK_DEPENDENCY_LOCK_FILE but the lock-less IAM renders",
      sorted(p.name for p in HERE.glob("*.py") if '"TF_PLUGIN_CACHE_MAY_BREAK_DEPENDENCY_LOCK_FILE": "true"'
             in p.read_text() and p.name != "test_tf_plugin_cache.py") == ["iam_plan_render.py"])

print("== the tools tier names the plugin cache in the artifact root ==")
runner = (HERE / "run-e2e-tools.sh").read_text()
code = "\n".join(ln for ln in runner.splitlines() if not ln.lstrip().startswith("#"))
check("run-e2e-tools.sh takes its cache from tf_plugin_cache.py",
      'TF_CACHE="$(python3 "${SCRIPT_DIR}/tf_plugin_cache.py")"' in code)
check("and keeps none in verify/.tools", ".tools/plugin-cache" not in code)
check("with TF_PLUGIN_CACHE_MAY_BREAK_DEPENDENCY_LOCK_FILE unset for every tier test",
      "-u TF_PLUGIN_CACHE_MAY_BREAK_DEPENDENCY_LOCK_FILE" in code)
check("a terraform test holds the cache's lock while it runs",
      'TF_CACHE_LOCK="${TF_CACHE}.lock"' in code and 'flock -w "${TF_CACHE_LOCK_WAIT}"' in code)

print("== every workflow that runs terraform init fills the mirror outside the workspace first ==")
WF = REPO / ".github/workflows"
# The step that runs an init, by workflow, and whether the workflow itself must prepare the mirror (a script outside
# verify/, plan-fleet.py, takes the prepared env) or the tests prepare it themselves.
INITS = {"iam-policy.yml": "python verify/test_iam_policy_structural.py",
         "plan-policy.yml": "python infra/policy/plan/plan-fleet.py",
         "verify-suites.yml": "bash verify/run-e2e-tools.sh"}
for wf in sorted(WF.glob("*.yml")):
    text = wf.read_text()
    check(f"{wf.name}: sets no TF_PLUGIN_CACHE_DIR of its own", "TF_PLUGIN_CACHE_DIR" not in text)
    doc = yaml.safe_load(text)
    for job, spec in (doc.get("jobs") or {}).items():
        env_text = json.dumps(spec.get("env") or {})
        check(f"{wf.name} {job}: its job env names no runner context, which Actions refuses there",
              "runner." not in env_text, env_text)
    runs_init = any(re.search(r"terraform|plan-fleet|iam_plan_render|test_iam_policy_structural|run-e2e-tools",
                              str(s.get("run", ""))) for j in (doc.get("jobs") or {}).values()
                    for s in j.get("steps", []))
    if wf.name in INITS:
        steps = [s for j in doc["jobs"].values() for s in j.get("steps", [])]
        runs = [str(s.get("run", "")) for s in steps]
        first = next(i for i, r in enumerate(runs) if INITS[wf.name] in r)
        cache = next((i for i, r in enumerate(runs) if r.strip() == "bash verify/ci-artifact-cache.sh"), None)
        check(f"{wf.name}: WIB_ARTIFACT_CACHE is set by verify/ci-artifact-cache.sh before the first init (#1123)",
              cache is not None and cache < first, str(runs[:first + 1]))
        if wf.name != "verify-suites.yml":
            prep = next((i for i, r in enumerate(runs) if 'tf_plugin_cache.py prepare >> "$GITHUB_ENV"' in r), None)
            check(f"{wf.name}: it fills the mirror into the job's env before the first init",
                  prep is not None and cache <= prep < first, str(runs[:first + 1]))
    else:
        check(f"{wf.name}: runs no terraform init this test does not know of", not runs_init)

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All terraform provider cache checks passed.")
