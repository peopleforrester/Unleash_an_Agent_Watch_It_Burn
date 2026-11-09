#!/usr/bin/env python3
# ABOUTME: Offline half of #1285: verify/sign-images.sh signs and verifies, by digest, exactly the watch-it-burn
# ABOUTME: digests verify/wib_pins.py reads from images.lock and the manifests, driven with a stub cosign and no network.
"""Why (#1285). Run 19646 on #1282 found the three Kyverno counter-fix builds (gitops/bootstrap/apps/kyverno.yaml) and
the llm-guard zero-shot model pinned with no cosign signature. The signing script then found tags on image: keys and
Dockerfile FROM/ARG lines only, so it never saw kyverno.yaml's Helm repository/tag values or an images.lock-only row,
and it asked the registry which digest a tag served now, so a moved tag got its new digest signed, not the pinned one.

This holds the script to verify/wib_pins.py's reading, the one verify/test_wib_digests_signed.py checks on ghcr.io:

  - `sign-images.sh --list` prints exactly wib_pins' refs (ghcr.io/<package>@sha256:<hex>), each a digest, and the
    four #1282 named are among them: the three kyverno.yaml pins and images.lock's llm-guard-model-zeroshot row
  - signing, with a stub cosign 2.x that logs its arguments, signs each of those refs once, by digest, with the key,
    the password file's contents and --tlog-upload=false, verifies each against policies/cosign/watch-it-burn.pub with
    --insecure-ignore-tlog, and names no other image
  - --check signs nothing and verifies each ref; a ref the stub will not verify fails the run, naming the ref
  - a cosign 3.x is refused before anything is signed, and wib_pins' reader exits 1 on a checkout with nothing pinned
"""
from __future__ import annotations

import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

VERIFY = pathlib.Path(__file__).resolve().parent
REPO = VERIFY.parent
sys.path.insert(0, str(VERIFY))
from wib_pins import merge, ref, repo_pins  # noqa: E402

SCRIPT = VERIFY / "sign-images.sh"
PUB = REPO / "policies/cosign/watch-it-burn.pub"
KYVERNO = "gitops/bootstrap/apps/kyverno.yaml"
ZEROSHOT_TAG = "llm-guard-model-zeroshot-"

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"\n        {detail}" if detail and not ok else ""))
    if not ok:
        failures.append(name)


def run(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(["bash", str(SCRIPT), *args], capture_output=True, text=True, timeout=300,
                          env={**os.environ, **(env or {})})


lock, manifests = repo_pins(REPO)
pinned = merge(lock, manifests)
want = sorted(ref(package, digest) for package, digest in pinned)

print("== --list is wib_pins' list ==")
listed = run("--list")
got = listed.stdout.split()
check("sign-images.sh --list exits 0", listed.returncode == 0, listed.stderr.strip())
check(f"it lists exactly the {len(want)} digests wib_pins reads from images.lock and the manifests", got == want,
      f"only in the script: {sorted(set(got) - set(want))}; only in wib_pins: {sorted(set(want) - set(got))}")
check("wib_pins reads both sources", bool(lock) and bool(manifests), f"lock {len(lock)}, manifests {len(manifests)}")
check("every listed ref is ghcr.io/peopleforrester/watch-it-burn...@sha256:<hex>, never a tag",
      bool(got) and all(re.fullmatch(r"ghcr\.io/peopleforrester/watch-it-burn[\w./-]*@sha256:[0-9a-f]{64}", r)
                        for r in got), str(got))

kyverno = sorted(ref(*k) for k, wheres in pinned.items() if any(w.startswith(f"{KYVERNO}:") for w in wheres))
check(f"the three Kyverno counter-fix builds {KYVERNO} pins as Helm repository and tag values are listed",
      len(kyverno) == 3 and set(kyverno) <= set(got), str(kyverno))
lock_text = (REPO / "images.lock").read_text(encoding="utf-8")
zeroshot = re.search(rf"^ghcr\.io/peopleforrester/watch-it-burn:{ZEROSHOT_TAG}\S*\s+(sha256:[0-9a-f]{{64}})\s",
                     lock_text, re.M)
if not zeroshot:
    check(f"images.lock has a {ZEROSHOT_TAG}* row with a digest (the anchor this test reads)", False,
          f"no ghcr.io/peopleforrester/watch-it-burn:{ZEROSHOT_TAG}* row with a digest in images.lock")
else:
    zref = f"ghcr.io/peopleforrester/watch-it-burn@{zeroshot.group(1)}"
    check("the llm-guard zero-shot model, pinned only in images.lock, is listed", zref in got, zref)

print("== signing, with a stub cosign 2.x ==")
scratch = pathlib.Path(tempfile.mkdtemp(prefix="sign-images-"))
log = scratch / "cosign.log"
key = scratch / "test.key"
pw = scratch / "test.pw"
key.write_text("not a key\n", encoding="utf-8")
pw.write_text("stub-password", encoding="utf-8")
stub = scratch / "cosign-stub"
stub.write_text(r'''#!/usr/bin/env bash
if [[ "$1" == "version" ]]; then echo "GitVersion:    ${STUB_VERSION:-v2.6.5}"; exit 0; fi
printf '%s|%s\n' "${COSIGN_PASSWORD:-}" "$*" >>"${STUB_LOG}"
[[ "$1" == "verify" && -n "${STUB_FAIL_REF:-}" && "${@: -1}" == "${STUB_FAIL_REF}" ]] && exit 1
exit 0
''', encoding="utf-8")
stub.chmod(0o755)
env = {"WIB_COSIGN": str(stub), "WIB_COSIGN_KEY": str(key), "WIB_COSIGN_PW": str(pw), "STUB_LOG": str(log)}


def calls() -> list[tuple[str, list[str]]]:
    if not log.exists():
        return []
    out = []
    for line in log.read_text(encoding="utf-8").splitlines():
        password, _, argv = line.partition("|")
        out.append((password, argv.split()))
    log.unlink()
    return out


signed = run(env=env)
seen = calls()
signs = [(p, a) for p, a in seen if a[:1] == ["sign"]]
verifies = [(p, a) for p, a in seen if a[:1] == ["verify"]]
check("signing exits 0 when every sign and verify succeeds", signed.returncode == 0, signed.stdout + signed.stderr)
check("it signs each listed digest once, and nothing else",
      sorted(a[-1] for _, a in signs) == want, str([a[-1] for _, a in signs]))
check("each sign is `sign --key <key> --tlog-upload=false --yes <ref>` with the password file's contents",
      bool(signs) and all(a == ["sign", "--key", str(key), "--tlog-upload=false", "--yes", a[-1]]
                          and p == "stub-password" for p, a in signs), str(signs[:2]))
check("it verifies each listed digest once, against the committed key with --insecure-ignore-tlog",
      sorted(a[-1] for _, a in verifies) == want
      and all(a[:-1] == ["verify", "--key", str(PUB), "--insecure-ignore-tlog"] for _, a in verifies),
      str(verifies[:2]))
check("cosign is called for sign and verify only", len(seen) == len(signs) + len(verifies), str(seen[:3]))
check(f"it reports all {len(want)} pinned digests signed and verified",
      f"all {len(want)} pinned digests signed and verified" in signed.stdout, signed.stdout[-300:])
check("each line names where the digest is pinned",
      all(any(line.startswith(r) and "(" in line for line in signed.stdout.splitlines()) for r in want),
      signed.stdout[:300])

print("== --check, and a digest that does not verify ==")
checked = run("--check", env=env)
seen = calls()
check("--check signs nothing and verifies each listed digest",
      checked.returncode == 0 and all(a[0] == "verify" for _, a in seen) and sorted(a[-1] for _, a in seen) == want,
      checked.stdout + checked.stderr)
bad = kyverno[0] if kyverno else want[-1]
failed = run("--check", env={**env, "STUB_FAIL_REF": bad})
calls()
check("a digest cosign will not verify fails the run, and the line naming it says NOT VERIFIED",
      failed.returncode == 1 and any(line.startswith(bad) and "NOT VERIFIED" in line
                                     for line in failed.stdout.splitlines()), failed.stdout + failed.stderr)

print("== refusals ==")
v3 = run(env={**env, "STUB_VERSION": "v3.0.2"})
check("a cosign 3.x is refused before anything is signed",
      v3.returncode == 1 and "refusing to sign with cosign v3.0.2" in v3.stderr and not calls(), v3.stderr)
empty = subprocess.run([sys.executable, str(VERIFY / "wib_pins.py"), "refs", str(scratch)], capture_output=True,
                       text=True, timeout=60)
check("wib_pins' reader exits 1 on a checkout that pins nothing, naming both sources",
      empty.returncode == 1 and "images.lock" in empty.stderr and "no manifest pins" in empty.stderr and not empty.stdout,
      empty.stdout + empty.stderr)
check("an unknown argument is refused", run("--sign-tags").returncode == 2)
shutil.rmtree(scratch, ignore_errors=True)

if failures:
    print(f"\nFAILED: {len(failures)} check(s)")
    sys.exit(1)
print("\nsign-images.sh signs and verifies, by digest, exactly the digests verify/wib_pins.py reads.")
