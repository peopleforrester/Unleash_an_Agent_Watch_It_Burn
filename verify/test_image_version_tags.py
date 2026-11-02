# ABOUTME: A tag names the version of the software inside (#714): reads mcp from workshop-mcp, ttyd from web-terminal
# ABOUTME: and busybox from C6's Joker, out of the images on ghcr.io, and checks each tag serves the pinned digest.
# SUITE: e2e (needs the network: ghcr.io is asked, with no credential, for each image)
# E2E TIER: tools (no cluster, no AWS: run-e2e-tools.sh runs it, #572)
"""Michael, 2026-10-30, on #714: a tag must match the version of the software inside. Three of our images had tags
that named no version (workshop-mcp, web-terminal, joker). They are now:

  watch-it-burn:workshop-mcp-mcp-<v>        the MCP Python SDK images/workshop-mcp/Dockerfile bakes in, read from
                                            its installed dist-info METADATA
  watch-it-burn:web-terminal-ttyd-<v>       ttyd, the terminal the pod serves (images/web-terminal/Dockerfile), read
                                            from `ttyd --version` run on the binary taken out of the image
  festival-ops/maintenance-shell:busybox-<v>  C6's Joker (images/villains/build.sh), read from its own busybox

The first two are read at the digest gitops/ai-layer/resources.yaml pins, so what is checked is what a cluster runs,
and every reference in the repo must name that one tag. The Joker is read at whatever its tag serves, since
HC-7731's ticket names it by tag. Each tag must serve, anonymously, the digest the repo pins: that is what a node
with no pull secret gets. lab-platform's own tags are its #330.
"""
from __future__ import annotations

import json
import pathlib
import re
import subprocess
import sys
import tarfile
import tempfile
import urllib.error
import urllib.request

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "verify"))
from ghcr_pull import ACCEPT, served_digest  # noqa: E402

WIB = "peopleforrester/watch-it-burn"
RESOURCES = (REPO / "gitops/ai-layer/resources.yaml").read_text(encoding="utf-8")
BUILD = (REPO / "images/villains/build.sh").read_text(encoding="utf-8")
WORKFLOW = (REPO / ".github/workflows/build-web-terminal.yml").read_text(encoding="utf-8")

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail and not ok else ""))
    if not ok:
        failures.append(name)


def token(package: str) -> str:
    with urllib.request.urlopen(f"https://ghcr.io/token?scope=repository:{package}:pull", timeout=30) as r:
        return json.load(r)["token"]


def get(package: str, tok: str, path: str):
    req = urllib.request.Request(f"https://ghcr.io/v2/{package}/{path}",
                                 headers={"Authorization": f"Bearer {tok}", "Accept": ACCEPT})
    return urllib.request.urlopen(req, timeout=120)


def amd64_layers(package: str, tok: str, digest: str) -> list[str]:
    """The layer digests of the linux/amd64 image at digest, an index or a single manifest."""
    with get(package, tok, f"manifests/{digest}") as r:
        m = json.load(r)
    if "manifests" in m:
        d = next(x["digest"] for x in m["manifests"]
                 if x.get("platform", {}).get("os") == "linux" and x["platform"].get("architecture") == "amd64")
        with get(package, tok, f"manifests/{d}") as r:
            m = json.load(r)
    return [layer["digest"] for layer in m["layers"]]


def find(package: str, digest: str, pattern: str) -> tuple[str, bytes] | None:
    """The first file whose path matches pattern, streamed out of the image's layers, last layer first. A hard link
    is followed to its file: busybox's layer stores bin/busybox as a link to bin/[."""
    tok = token(package)
    rx = re.compile(pattern)
    for layer in reversed(amd64_layers(package, tok, digest)):
        with get(package, tok, f"blobs/{layer}") as r, tarfile.open(fileobj=r, mode="r|*") as tar:
            for member in tar:
                if not rx.search(member.name.lstrip("./")):
                    continue
                if member.isfile():
                    return member.name, tar.extractfile(member).read()
                if member.islnk():
                    return find(package, digest, "^" + re.escape(member.linkname.lstrip("./")) + "$")
    return None


def run_version(binary: bytes, name: str, args: list[str]) -> str:
    """Run a binary taken out of one of our images and return what it prints: the version it reports of itself."""
    with tempfile.TemporaryDirectory() as tmp:
        exe = pathlib.Path(tmp) / name
        exe.write_bytes(binary)
        exe.chmod(0o755)
        p = subprocess.run([str(exe), *args], capture_output=True, text=True, timeout=20)
        return (p.stdout + p.stderr).strip()


def pinned(prefix: str) -> tuple[str, str] | None:
    """The one (version, digest) the repo pins for watch-it-burn:<prefix><version>@sha256:..., which must be the only
    watch-it-burn:<image> tag anything names."""
    image = prefix.split("-")[0] + "-" + prefix.split("-")[1]  # workshop-mcp, web-terminal
    named = set()
    for p in sorted(REPO.rglob("*")):
        if p.is_file() and p.suffix in (".yaml", ".yml", ".sh", ".py", ".md", ".lock") and ".tools" not in p.parts \
                and "transcripts" not in p.parts and p.name not in ("decisions.md", "DECISION-LOG.md"):
            # A whole reference only: a template such as web-terminal-ttyd-${v} or -<v> is not one.
            named |= set(re.findall(rf"{re.escape(WIB)}:{re.escape(image)}[\w.-]*(?=[@\s`'\")]|$)",
                                    p.read_text(encoding="utf-8", errors="replace"), re.M))
    found = set(re.findall(rf"ghcr\.io/{WIB}:{re.escape(prefix)}([0-9][0-9.]*)@(sha256:[0-9a-f]{{64}})", RESOURCES))
    check(f"resources.yaml pins one {prefix}<version> digest ({sorted(found)})", len(found) == 1)
    if len(found) != 1:
        return None
    version, digest = next(iter(found))
    check(f"every reference to watch-it-burn:{image} names {prefix}{version} ({sorted(named)})",
          named == {f"{WIB}:{prefix}{version}"})
    return version, digest


def serves(ref: str, want: str | None) -> str | None:
    got, why = served_digest(ref)
    if want is None:
        check(f"ghcr.io serves {ref} anonymously", got is not None, why)
    else:
        check(f"ghcr.io serves {ref} at the pinned {want[:19]}..., anonymously", got == want,
              why or f"it serves {got}")
    return got


try:
    token(WIB)
except (urllib.error.URLError, OSError, KeyError, ValueError) as e:
    print(f"FAIL  ghcr.io gave no anonymous token for {WIB}: {type(e).__name__}: {e}", file=sys.stderr)
    sys.exit(1)

print("== workshop-mcp-mcp-<version>: the MCP SDK inside ==")
pin = pinned("workshop-mcp-mcp-")
if pin:
    version, digest = pin
    serves(f"ghcr.io/{WIB}:workshop-mcp-mcp-{version}", digest)
    hit = find(WIB, digest, r"site-packages/mcp-[^/]+\.dist-info/METADATA$")
    meta = re.search(r"^Version: (\S+)$", hit[1].decode(errors="replace"), re.M) if hit else None
    check(f"the image at {digest[:19]}... has mcp installed ({hit[0] if hit else 'no dist-info'})", meta is not None)
    check(f"its mcp is {version}, the tag's ({meta.group(1) if meta else '?'})", bool(meta) and meta.group(1) == version)
    dockerfile = (REPO / "images/workshop-mcp/Dockerfile").read_text(encoding="utf-8")
    check(f"images/workshop-mcp/Dockerfile pins mcp=={version}", f"'mcp=={version}'" in dockerfile)

print("== web-terminal-ttyd-<version>: the ttyd inside ==")
pin = pinned("web-terminal-ttyd-")
if pin:
    version, digest = pin
    serves(f"ghcr.io/{WIB}:web-terminal-ttyd-{version}", digest)
    hit = find(WIB, digest, r"^usr/local/bin/ttyd$")
    check(f"the image at {digest[:19]}... carries usr/local/bin/ttyd", hit is not None)
    if hit:
        out = run_version(hit[1], "ttyd", ["--version"])
        got = re.match(r"ttyd version (\d+\.\d+\.\d+)\b", out)
        check(f"its ttyd reports {version}, the tag's ({out[:60]})", bool(got) and got.group(1) == version)
    check("the build workflow tags the image with the ttyd version it reads from the image it built",
          "--entrypoint /usr/local/bin/ttyd web-terminal:built --version" in WORKFLOW
          and "watch-it-burn:web-terminal-ttyd-${v}" in WORKFLOW)

print("== maintenance-shell:busybox-<version>: the BusyBox C6's Joker runs on ==")
m = re.search(r'^JOKER_REF="(ghcr\.io/(peopleforrester/festival-ops/maintenance-shell):busybox-([0-9.]+))"$', BUILD, re.M)
check("build.sh names the Joker maintenance-shell:busybox-<version>", m is not None)
if m:
    ref, package, version = m.groups()
    digest = serves(ref, None)
    if digest:
        hit = find(package, digest, r"^bin/busybox$")
        out = run_version(hit[1], "busybox", []) if hit else ""
        got = re.match(r"BusyBox v(\d+\.\d+\.\d+)\b", out)
        check(f"the pushed Joker's busybox reports {version}, the tag's ({out[:50]})",
              bool(got) and got.group(1) == version)

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for name in failures:
        print(f"  - {name}")
    sys.exit(1)
print("Every watch-it-burn tag names the version inside its image.")
