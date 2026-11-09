# ABOUTME: Holds verify/image_cache.py (#1122) offline: a miss builds an OCI layout keyed by the manifest digest, a hit
# ABOUTME: reads no registry, and a blob that does not match its digest fails naming both sums, never fetched again.
"""A fake registry stands in for ghcr.io: a dict of URL to bytes behind the cache's Fetcher hook, and for the
registry fetcher itself a server on 127.0.0.1 that asks for a Bearer token and redirects blobs, as ghcr.io does. Each
cache root is a scratch directory outside every worktree (artifact_cache.scratch_dir)."""
from __future__ import annotations

import hashlib
import http.server
import json
import os
import pathlib
import shutil
import subprocess
import sys
import threading

VERIFY = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(VERIFY))
import artifact_cache as ac  # noqa: E402
import image_cache as ic  # noqa: E402

for var in ("ARTIFACT_FETCH_LOG", "HECATON_TOOLS_CACHE", "WIB_ARTIFACT_CACHE"):
    os.environ.pop(var, None)

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail and not ok else ""))
    if not ok:
        failures.append(name)


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def desc(media: str, b: bytes, **extra) -> dict:
    return {"mediaType": media, "digest": f"sha256:{sha(b)}", "size": len(b), **extra}


HOST, REPO = "registry.invalid", "lab/mirror/busybox"
BASE = f"https://{HOST}/v2/{REPO}"
config = json.dumps({"os": "linux", "architecture": "amd64"}).encode()
layer = b"layer bytes " * 100
manifest = json.dumps({"schemaVersion": 2, "mediaType": ic.MANIFEST_TYPES[0],
                       "config": desc("application/vnd.oci.image.config.v1+json", config),
                       "layers": [desc("application/vnd.oci.image.layer.v1.tar+gzip", layer)]}).encode()
arm_manifest = json.dumps({"schemaVersion": 2, "mediaType": ic.MANIFEST_TYPES[0],
                           "config": desc("application/vnd.oci.image.config.v1+json", b"arm"),
                           "layers": []}).encode()
index = json.dumps({"schemaVersion": 2, "mediaType": ic.INDEX_TYPES[0], "manifests": [
    desc(ic.MANIFEST_TYPES[0], arm_manifest, platform={"os": "linux", "architecture": "arm64"}),
    desc(ic.MANIFEST_TYPES[0], manifest, platform={"os": "linux", "architecture": "amd64"})]}).encode()
REF = f"{HOST}/{REPO}:1.38.0@sha256:{sha(manifest)}"
INDEX_REF = f"{HOST}/{REPO}:1.38.0@sha256:{sha(index)}"


def served(extra: dict[str, bytes] | None = None) -> dict[str, bytes]:
    out = {f"{BASE}/manifests/sha256:{sha(manifest)}": manifest, f"{BASE}/manifests/sha256:{sha(index)}": index,
           f"{BASE}/blobs/sha256:{sha(config)}": config, f"{BASE}/blobs/sha256:{sha(layer)}": layer}
    return {**out, **(extra or {})}


class Registry:
    """A Fetcher that serves a dict and counts what it was asked for."""

    def __init__(self, urls: dict[str, bytes]):
        self.urls, self.asked = urls, []

    def __call__(self, url: str, out) -> None:
        self.asked.append(url)
        if url not in self.urls:
            raise OSError(f"404 {url}")
        out.write(self.urls[url])


def never(url: str, out) -> None:
    raise AssertionError(f"a hit fetched {url}")


def raises(fn, kind: type) -> str:
    try:
        fn()
    except kind as e:
        return str(e)
    except Exception as e:  # noqa: BLE001 - the case reports what came instead
        return f"WRONG {type(e).__name__}: {e}"
    return "NO ERROR"


def log_lines(root: pathlib.Path) -> list[str]:
    p = root / "fetch.log"
    return p.read_text().splitlines() if p.exists() else []


base = ac.scratch_dir("image-cache-test-")
try:
    print("== a reference must be pinned by digest ==")
    for bad in (f"{HOST}/{REPO}:1.38.0", f"{HOST}/{REPO}@sha256:abc", "busybox@sha256:" + "0" * 64):
        check(f"{bad[:40]}... is refused", "not a pinned image reference" in raises(lambda: ic.parse_ref(bad),
                                                                                    ic.ImageCacheError))
    check("host, repository and digest are read from a tagged reference",
          ic.parse_ref(REF) == (HOST, REPO, sha(manifest)))

    print("== a miss builds an OCI layout keyed by the manifest digest, each blob by its own sha256 ==")
    root = base / "cache"
    reg = Registry(served())
    dest = ic.layout(REF, root=root, fetch=reg)
    check("the layout is <root>/oci/sha256/<manifest digest>", dest == root / "oci" / "sha256" / sha(manifest), str(dest))
    check("it is an OCI layout: oci-layout and index.json",
          json.loads((dest / "oci-layout").read_text()) == {"imageLayoutVersion": "1.0.0"}
          and json.loads((dest / "index.json").read_text())["manifests"][0]["digest"] == f"sha256:{sha(manifest)}")
    check("its index names the reference", json.loads((dest / "index.json").read_text())["manifests"][0]
          ["annotations"][ic.REF_NAME] == REF)
    blobs = sorted(p.name for p in (dest / "blobs" / "sha256").iterdir())
    check("its blobs are the manifest, the config and the layer, each named by its sha256",
          blobs == sorted([sha(manifest), sha(config), sha(layer)]), str(blobs))
    check("the manifest and each blob were fetched once, by digest", sorted(reg.asked) == sorted(
        [f"{BASE}/manifests/sha256:{sha(manifest)}", f"{BASE}/blobs/sha256:{sha(config)}",
         f"{BASE}/blobs/sha256:{sha(layer)}"]), str(reg.asked))
    lines = log_lines(root)
    check("each fetch is one ok line in the artifact cache's fetch log", len(lines) == 3
          and all(x.endswith("\tok") for x in lines), str(lines))
    check("no temp layout is left beside it", not [p for p in dest.parent.iterdir() if p.name.endswith(".part")])
    got = ic.image(dest)
    check("image() reads back the manifest, the config and the layer", got["manifest"] == json.loads(manifest)
          and got["config"] == json.loads(config) and [p.read_bytes() for p in got["layers"]] == [layer])

    print("== a hit reads no registry ==")
    check("the same layout is served", ic.layout(REF, root=root, fetch=never) == dest)
    check("the fetch log is unchanged", log_lines(root) == lines)
    r = subprocess.run([sys.executable, str(VERIFY / "image_cache.py"), "layout", REF], capture_output=True, text=True,
                       env={**os.environ, "WIB_ARTIFACT_CACHE": str(root), "HTTPS_PROXY": "http://127.0.0.1:9"})
    check("the command line prints it, with every proxy a closed port", r.returncode == 0 and r.stdout.strip() == str(dest),
          r.stdout + r.stderr)

    print("== a layout blob that does not match its digest fails, naming both sums, and is not fetched again ==")
    bad_root = base / "cache-bad"
    bad = ic.layout(REF, root=bad_root, fetch=Registry(served()))
    lf = bad / "blobs" / "sha256" / sha(layer)
    lf.unlink()
    lf.write_bytes(b"other bytes")
    before = log_lines(bad_root)
    msg = raises(lambda: ic.layout(REF, root=bad_root, fetch=never), ic.LayoutMismatch)
    check("it fails naming the blob, its pin and what it hashes to", str(lf) in msg and sha(layer) in msg
          and sha(b"other bytes") in msg, msg)
    check("it is a mismatch, so get_retrying would not retry it", isinstance(ic.LayoutMismatch("x"), ac.ArtifactMismatch))
    check("the layout is left in place, still wrong, and the fetch log is unchanged",
          lf.read_bytes() == b"other bytes" and log_lines(bad_root) == before)
    lf.unlink()
    msg = raises(lambda: ic.layout(REF, root=bad_root, fetch=never), ic.LayoutMismatch)
    check("a layout that lacks a blob its manifest names fails by name, not fetched", sha(layer) in msg
          and "lacks" in msg, msg)
    (bad / "index.json").write_text(json.dumps({"manifests": [{"digest": f"sha256:{sha(index)}"}]}))
    msg = raises(lambda: ic.layout(REF, root=bad_root, fetch=never), ic.LayoutMismatch)
    check("a layout whose index names another manifest fails, naming both", sha(index) in msg and sha(manifest) in msg,
          msg)

    print("== a registry that serves other bytes for a digest: nothing is kept ==")
    wrong_root = base / "cache-wrong"
    msg = raises(lambda: ic.layout(REF, root=wrong_root, fetch=Registry(served(
        {f"{BASE}/blobs/sha256:{sha(layer)}": b"tampered"}))), ac.ArtifactMismatch)
    check("it fails naming the URL and both sums", sha(layer) in msg and sha(b"tampered") in msg and BASE in msg, msg)
    check("no layout was made", not ic.layout_path(sha(manifest), wrong_root).exists())
    check("the fetch log says mismatch", any("\tmismatch " in x for x in log_lines(wrong_root)), str(log_lines(wrong_root)))

    print("== an index: the platform's image is taken, and no other platform is fetched ==")
    ix_root = base / "cache-index"
    reg = Registry(served())
    ixd = ic.layout(INDEX_REF, root=ix_root, fetch=reg)
    check("the layout is keyed by the index digest", ixd.name == sha(index))
    check("it holds the index, the amd64 manifest and its blobs, and not arm64's",
          sorted(p.name for p in (ixd / "blobs" / "sha256").iterdir())
          == sorted([sha(index), sha(manifest), sha(config), sha(layer)]))
    check("arm64's manifest was never asked for", f"{BASE}/manifests/sha256:{sha(arm_manifest)}" not in reg.asked)
    check("image() follows the index to the amd64 image", ic.image(ixd)["manifest"] == json.loads(manifest))
    check("a hit on it reads no registry", ic.layout(INDEX_REF, root=ix_root, fetch=never) == ixd)
    msg = raises(lambda: ic.layout(INDEX_REF, "linux/s390x", root=base / "cache-s390x", fetch=Registry(served())),
                 ic.ImageCacheError)
    check("a platform the index lacks fails, naming the ones it has", "linux/s390x" in msg and "linux/amd64" in msg, msg)

    print("== platform_layout: the platform's image of an index as a layout of its own, to push (#1216) ==")
    out = base / "platform-out"
    got = ic.platform_layout(INDEX_REF, out, root=ix_root, fetch=never)
    check("it returns the amd64 image manifest's digest, not the index's", got == f"sha256:{sha(manifest)}", got)
    named = json.loads((out / "index.json").read_text())["manifests"]
    check("its index.json names only that manifest, with its media type and size",
          [(d["digest"], d["mediaType"], d["size"]) for d in named]
          == [(f"sha256:{sha(manifest)}", ic.MANIFEST_TYPES[0], len(manifest))], str(named))
    check("it is an OCI layout", json.loads((out / "oci-layout").read_text()) == {"imageLayoutVersion": "1.0.0"})
    check("its blobs are the cached layout's, linked and not copied",
          (out / "blobs").is_symlink() and (out / "blobs").resolve() == (ixd / "blobs").resolve())
    check("image() reads it back as the amd64 image", ic.image(out)["manifest"] == json.loads(manifest)
          and [p.read_bytes() for p in ic.image(out)["layers"]] == [layer])
    msg = raises(lambda: ic.platform_layout(INDEX_REF, out, root=ix_root, fetch=never), ic.ImageCacheError)
    check("it refuses to write over a directory that is already there", str(out) in msg and "already" in msg, msg)
    img_out = base / "platform-image"
    check("for a pin that names an image, it is that image",
          ic.platform_layout(REF, img_out, root=root, fetch=never) == f"sha256:{sha(manifest)}"
          and [d["digest"] for d in json.loads((img_out / "index.json").read_text())["manifests"]]
          == [f"sha256:{sha(manifest)}"])
    cli_out = base / "platform-cli"
    r = subprocess.run([sys.executable, str(VERIFY / "image_cache.py"), "platform-layout", INDEX_REF, str(cli_out),
                        "linux/amd64"], capture_output=True, text=True,
                       env={**os.environ, "WIB_ARTIFACT_CACHE": str(ix_root), "HTTPS_PROXY": "http://127.0.0.1:9"})
    check("the command line prints the digest on a hit, with every proxy a closed port",
          r.returncode == 0 and r.stdout.strip() == f"sha256:{sha(manifest)}", r.stdout + r.stderr)
    (ixd / "blobs" / "sha256" / sha(manifest)).unlink()
    msg = raises(lambda: ic.platform_layout(INDEX_REF, base / "platform-gone", root=ix_root, fetch=never),
                 ic.LayoutMismatch)
    check("a cached layout that lost the platform's manifest fails by name and fetches nothing", sha(manifest) in msg,
          msg)

    print("== the registry fetcher: an anonymous Bearer token, and a blob's redirect followed without it ==")
    seen: list[tuple[str, str | None]] = []

    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):  # noqa: N802 - http.server's name
            auth = self.headers.get("Authorization")
            seen.append((self.path, auth))
            port = self.server.server_address[1]
            if self.path.startswith("/token?"):
                body = json.dumps({"token": "anon"}).encode()
            elif self.path.startswith("/store/"):
                body = layer if auth is None else b"two credentials"
            elif auth != "Bearer anon":
                self.send_response(401)
                self.send_header("WWW-Authenticate", f'Bearer realm="http://127.0.0.1:{port}/token",'
                                                     f'service="test",scope="repository:{REPO}:pull"')
                self.end_headers()
                return
            elif "/blobs/" in self.path:
                self.send_response(307)
                self.send_header("Location", f"http://127.0.0.1:{port}/store/{sha(layer)}?signed=1")
                self.end_headers()
                return
            else:
                body = manifest
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        url = f"http://127.0.0.1:{srv.server_address[1]}/v2/{REPO}"
        fr = base / "cache-http"
        m = ac.get(sha(manifest), f"{url}/manifests/sha256:{sha(manifest)}", root=fr, fetch=ic.registry_fetch)
        check("a manifest is served after a 401 names the realm", m.read_bytes() == manifest, str(seen))
        tok = [p for p, _ in seen if p.startswith("/token?")]
        check("the token is asked for the challenge's service and scope", len(tok) == 1 and "service=test" in tok[0]
              and "scope=repository%3A" in tok[0], str(tok))
        b = ac.get(sha(layer), f"{url}/blobs/sha256:{sha(layer)}", root=fr, fetch=ic.registry_fetch)
        check("a blob is read through its redirect, which gets no Authorization header", b.read_bytes() == layer
              and [a for p, a in seen if p.startswith("/store/")] == [None], str(seen))
        check("the token is asked for once", len([p for p, _ in seen if p.startswith("/token?")]) == 1)
    finally:
        srv.shutdown()
        srv.server_close()
finally:
    shutil.rmtree(base, ignore_errors=True)

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    raise SystemExit(1)
print("All image cache checks passed.")
