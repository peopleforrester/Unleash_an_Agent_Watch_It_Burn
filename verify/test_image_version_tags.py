# ABOUTME: A tag names the version of the software inside (#714, #814): reads mcp, ttyd, nginx and busybox out of
# ABOUTME: workshop-mcp, web-terminal, sample-app and C6's Joker on ghcr.io, and checks each tag serves the pinned digest.
# SUITE: e2e (needs the network: ghcr.io is asked, with no credential, for each image)
# E2E TIER: tools (no cluster, no AWS: run-e2e-tools.sh runs it, #572)
"""Michael, 2026-10-30, on #714: a tag must match the version of the software inside. Five of our images had tags
that named no version (workshop-mcp, web-terminal, joker; sample-app and tool-pin, #814). They are now:

  watch-it-burn:workshop-mcp-mcp-<v>        the MCP Python SDK images/workshop-mcp/Dockerfile bakes in, read from
                                            its installed dist-info METADATA
  watch-it-burn:web-terminal-ttyd-<v>       ttyd, the terminal the pod serves (images/web-terminal/Dockerfile), read
                                            from `ttyd --version` run on the binary taken out of the image. A rebuild
                                            of new source under the same ttyd is web-terminal-ttyd-<v>-<n> (#838):
                                            its image carries the source-tree label the build workflow sets
  watch-it-burn:sample-app-nginx-<v>        the nginx serving Backstage's templated-test-svc (images/sample-app),
                                            read from the version string compiled into usr/sbin/nginx
  watch-it-burn:tool-pin-grpcio-<v>         the #480 spike's processor (images/tool-pin): grpcio, the one package
                                            its Dockerfile adds to python. Never pushed, so there is no image to
                                            read: the tag is held to the Dockerfile's pin and to ghcr.io's 404
  festival-ops/maintenance-shell:busybox-<v>  C6's Joker (images/villains/build.sh), read from its own busybox

The first two are read at the digest gitops/ai-layer/resources.yaml pins, and sample-app at the one
backstage/k8s/templated-test-svc.yaml pins, so what is checked is what a cluster runs, and every reference in the
repo must name that one tag. The Joker is read at whatever its tag serves, since
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
from ghcr_pull import ACCEPT, open_url, read_url, served_digest  # noqa: E402

WIB = "peopleforrester/watch-it-burn"
RESOURCES = (REPO / "gitops/ai-layer/resources.yaml").read_text(encoding="utf-8")
SAMPLE_SVC = (REPO / "backstage/k8s/templated-test-svc.yaml").read_text(encoding="utf-8")
LOCK = (REPO / "images.lock").read_text(encoding="utf-8")
BUILD = (REPO / "images/villains/build.sh").read_text(encoding="utf-8")
# The label build-web-terminal.yml sets and scripts/ghcr_version_tag.py reads (#838).
SOURCE_TREE = "io.github.peopleforrester.watch-it-burn.source-tree"
WORKFLOW = (REPO / ".github/workflows/build-web-terminal.yml").read_text(encoding="utf-8")

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail and not ok else ""))
    if not ok:
        failures.append(name)


def token(package: str) -> str:
    return json.loads(read_url(f"https://ghcr.io/token?scope=repository:{package}:pull"))["token"]


def get(package: str, tok: str, path: str):
    req = urllib.request.Request(f"https://ghcr.io/v2/{package}/{path}",
                                 headers={"Authorization": f"Bearer {tok}", "Accept": ACCEPT})
    return open_url(req, timeout=120)


def amd64_manifest(package: str, tok: str, digest: str) -> dict:
    """The manifest of the linux/amd64 image at digest, an index or a single manifest."""
    with get(package, tok, f"manifests/{digest}") as r:
        m = json.load(r)
    if "manifests" in m:
        d = next(x["digest"] for x in m["manifests"]
                 if x.get("platform", {}).get("os") == "linux" and x["platform"].get("architecture") == "amd64")
        with get(package, tok, f"manifests/{d}") as r:
            m = json.load(r)
    return m


def amd64_layers(package: str, tok: str, digest: str) -> list[str]:
    """The layer digests of the linux/amd64 image at digest, an index or a single manifest."""
    return [layer["digest"] for layer in amd64_manifest(package, tok, digest)["layers"]]


def image_config(package: str, digest: str) -> dict:
    """The config blob (Env, Labels and the rest) of the linux/amd64 image at digest."""
    tok = token(package)
    with get(package, tok, f"blobs/{amd64_manifest(package, tok, digest)['config']['digest']}") as r:
        return json.load(r)


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


def named(image: str) -> set[str]:
    """Every whole watch-it-burn:<image>... reference in the repo's files, the dated records left out."""
    out = set()
    for p in sorted(REPO.rglob("*")):
        # tmp/ is the repo's ignored scratch, where hecaton's TMPDIR sits and other tests write and remove files (#1119).
        if p.relative_to(REPO).parts[0] == "tmp":
            continue
        if p.is_file() and p.suffix in (".yaml", ".yml", ".sh", ".py", ".md", ".lock") and ".tools" not in p.parts \
                and "transcripts" not in p.parts and p.name not in ("decisions.md", "DECISION-LOG.md"):
            # A whole reference only: a template such as web-terminal-ttyd-${v} or -<v> is not one.
            out |= set(re.findall(rf"{re.escape(WIB)}:{re.escape(image)}[\w.-]*(?=[@\s`'\")]|$)",
                                  p.read_text(encoding="utf-8", errors="replace"), re.M))
    return out


def pinned(prefix: str, where: str = "resources.yaml", text: str = RESOURCES,
           rebuild: bool = False) -> tuple[str, str, str] | None:
    """The one (version, rebuild suffix, digest) the file where pins for watch-it-burn:<prefix><version>@sha256:...,
    which must be the only watch-it-burn:<image> tag anything names. With rebuild, a -<n> suffix (#838) is taken."""
    image = prefix.split("-")[0] + "-" + prefix.split("-")[1]  # workshop-mcp, web-terminal, sample-app
    suffix = "(-[1-9][0-9]*)?" if rebuild else "()"
    found = set(re.findall(rf"ghcr\.io/{WIB}:{re.escape(prefix)}([0-9][0-9.]*[0-9]){suffix}@(sha256:[0-9a-f]{{64}})",
                           text))
    check(f"{where} pins one {prefix}<version> digest ({sorted(found)})", len(found) == 1)
    if len(found) != 1:
        return None
    version, n, digest = next(iter(found))
    refs = named(image)
    check(f"every reference to watch-it-burn:{image} names {prefix}{version}{n} ({sorted(refs)})",
          refs == {f"{WIB}:{prefix}{version}{n}"})
    return version, n, digest


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
    version, _, digest = pin
    serves(f"ghcr.io/{WIB}:workshop-mcp-mcp-{version}", digest)
    hit = find(WIB, digest, r"site-packages/mcp-[^/]+\.dist-info/METADATA$")
    meta = re.search(r"^Version: (\S+)$", hit[1].decode(errors="replace"), re.M) if hit else None
    check(f"the image at {digest[:19]}... has mcp installed ({hit[0] if hit else 'no dist-info'})", meta is not None)
    check(f"its mcp is {version}, the tag's ({meta.group(1) if meta else '?'})", bool(meta) and meta.group(1) == version)
    dockerfile = (REPO / "images/workshop-mcp/Dockerfile").read_text(encoding="utf-8")
    check(f"images/workshop-mcp/Dockerfile pins mcp=={version}", f"'mcp=={version}'" in dockerfile)

print("== web-terminal-ttyd-<version>: the ttyd inside ==")
pin = pinned("web-terminal-ttyd-", rebuild=True)
if pin:
    version, n, digest = pin
    serves(f"ghcr.io/{WIB}:web-terminal-ttyd-{version}{n}", digest)
    if n:
        # A -<n> tag is a rebuild of new source under the same ttyd (#838): the build workflow labels its image with
        # the source tree scripts/ghcr_version_tag.py told it apart by.
        labels = image_config(WIB, digest).get("config", {}).get("Labels") or {}
        check(f"the {n} rebuild's image carries a source-tree label ({sorted(labels)})",
              re.fullmatch(r"[0-9a-f]{40}", labels.get(SOURCE_TREE, "")) is not None)
    hit = find(WIB, digest, r"^usr/local/bin/ttyd$")
    check(f"the image at {digest[:19]}... carries usr/local/bin/ttyd", hit is not None)
    if hit:
        out = run_version(hit[1], "ttyd", ["--version"])
        got = re.match(r"ttyd version (\d+\.\d+\.\d+)\b", out)
        check(f"its ttyd reports {version}, the tag's ({out[:60]})", bool(got) and got.group(1) == version)
    check("the build workflow tags the image with the ttyd version it reads from the image it built",
          "--entrypoint /usr/local/bin/ttyd web-terminal:built --version" in WORKFLOW
          and "watch-it-burn:web-terminal-ttyd-${v}" in WORKFLOW
          and f"labels: {SOURCE_TREE}=" in WORKFLOW)

print("== sample-app-nginx-<version>: the nginx inside ==")
pin = pinned("sample-app-nginx-", "backstage/k8s/templated-test-svc.yaml", SAMPLE_SVC)
if pin:
    version, _, digest = pin
    serves(f"ghcr.io/{WIB}:sample-app-nginx-{version}", digest)
    check(f"images.lock pins sample-app-nginx-{version} at the same digest",
          f"ghcr.io/{WIB}:sample-app-nginx-{version}@{digest} {digest} " in LOCK)
    hit = find(WIB, digest, r"^usr/sbin/nginx$")
    check(f"the image at {digest[:19]}... carries usr/sbin/nginx", hit is not None)
    if hit:
        # nginx -v prints "nginx version: nginx/<v>" from this string; the binary is musl's, so it is read, not run.
        got = set(re.findall(rb"nginx/(\d+\.\d+\.\d+)\x00", hit[1]))
        check(f"its nginx is {version}, the tag's ({sorted(g.decode() for g in got)})", got == {version.encode()})
    base = re.search(rf"^FROM ghcr\.io/{WIB}:nginx-[0-9.]+-alpine@(sha256:[0-9a-f]{{64}})$",
                     (REPO / "images/sample-app/Dockerfile").read_text(encoding="utf-8"), re.M)
    check("images/sample-app/Dockerfile builds on our nginx alpine copy by digest", base is not None)
    if base:
        # A rebuild keeps the tag only while its base carries the same nginx: the base's NGINX_VERSION says which.
        env = image_config(WIB, base.group(1))["config"].get("Env", [])
        check(f"the Dockerfile's base carries nginx {version} too ({[e for e in env if e.startswith('NGINX_')]})",
              f"NGINX_VERSION={version}" in env)

print("== tool-pin-grpcio-<version>: the grpcio its Dockerfile installs ==")
row = re.findall(rf"^ghcr\.io/{WIB}:tool-pin-grpcio-([0-9][0-9.]*) - build:images/tool-pin -$", LOCK, re.M)
check(f"images.lock has one tool-pin-grpcio-<version> row, built here with no digest ({row})", len(row) == 1)
if len(row) == 1:
    version = row[0]
    refs = named("tool-pin")
    check(f"every reference to watch-it-burn:tool-pin names tool-pin-grpcio-{version} ({sorted(refs)})",
          refs == {f"{WIB}:tool-pin-grpcio-{version}"})
    dockerfile = (REPO / "images/tool-pin/Dockerfile").read_text(encoding="utf-8")
    check(f"images/tool-pin/Dockerfile installs grpcio=={version} and builds and pushes that tag",
          f"'grpcio=={version}'" in dockerfile
          and f"docker build -t ghcr.io/{WIB}:tool-pin-grpcio-{version} images/tool-pin" in dockerfile
          and f"docker push ghcr.io/{WIB}:tool-pin-grpcio-{version}" in dockerfile)
    # The row's "-" digest says it was never pushed. Once it is, its digest goes in images.lock, and this test
    # reads grpcio's dist-info out of it the way it reads mcp's out of workshop-mcp.
    got, why = served_digest(f"ghcr.io/{WIB}:tool-pin-grpcio-{version}")
    check(f"ghcr.io has no tool-pin-grpcio-{version}, as the row's - digest says", got is None
          and why == "manifest: HTTP 404 Not Found", why or f"it serves {got}: pin it in images.lock and read it")

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
