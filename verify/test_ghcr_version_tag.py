# ABOUTME: scripts/ghcr_version_tag.py never pushes a build over a version tag (#816): a moved pinned tag goes back on
# ABOUTME: its pinned digest byte for byte. Offline: a fake registry on loopback, and the docker push is a stub.
"""Offline. The live half is verify/test_image_version_tags.py (tools tier): ghcr.io must serve
web-terminal-ttyd-<v> at the digest gitops/ai-layer/resources.yaml pins.

#816: build-web-terminal.yml pushed every rebuild over web-terminal-ttyd-1.7.7, and the build is not reproducible, so
the tag moved off the pinned, signed digest on each push run. Each row of the script's table is a case here, run
against a registry that keeps manifests by digest and tags by name, the way ghcr.io does, and the workflow is held to
calling the script with the pin files and running when the script changes.
"""
from __future__ import annotations

import hashlib
import http.server
import importlib.util
import json
import pathlib
import re
import tempfile
import threading

REPO = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("ghcr_version_tag", REPO / "scripts/ghcr_version_tag.py")
gvt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gvt)

# Not a watch-it-burn reference: test_image_version_tags.py holds every one of those in the repo to the pinned tag.
REPO_NAME = "example/terminal"
REF = f"ghcr.io/{REPO_NAME}:web-terminal-ttyd-9.9.9"
INDEX = "application/vnd.oci.image.index.v1+json"
MANIFEST = "application/vnd.oci.image.manifest.v1+json"

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail and not ok else ""))
    if not ok:
        failures.append(name)


def digest(body: bytes) -> str:
    return "sha256:" + hashlib.sha256(body).hexdigest()


class Fake:
    """A registry: blobs is digest -> (bytes, media type), tags is tag -> digest; puts records each manifest PUT."""

    def __init__(self) -> None:
        self.blobs: dict[str, tuple[bytes, str]] = {}
        self.tags: dict[str, str] = {}
        self.puts: list[tuple[str, str]] = []
        self.scopes: list[str] = []

    def add(self, body: bytes, ctype: str, tag: str | None = None) -> str:
        d = digest(body)
        self.blobs[d] = (body, ctype)
        if tag:
            self.tags[tag] = d
        return d


def serve(fake: Fake) -> http.server.ThreadingHTTPServer:
    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a) -> None:
            pass

        def _target(self):
            m = re.fullmatch(rf"/v2/{re.escape(REPO_NAME)}/manifests/(.+)", self.path)
            if not m or self.headers.get("Authorization") != "Bearer tok":
                self.send_error(401 if m else 404)
                return None
            return m.group(1)

        def _manifest(self, body: bool) -> None:
            ref = self._target()
            if ref is None:
                return
            d = fake.tags.get(ref, ref)
            if d not in fake.blobs:
                self.send_error(404)
                return
            data, ctype = fake.blobs[d]
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Docker-Content-Digest", d)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            if body:
                self.wfile.write(data)

        def do_HEAD(self) -> None:
            self._manifest(False)

        def do_GET(self) -> None:
            if self.path.startswith("/token?"):
                fake.scopes.append(self.path.split("scope=", 1)[1])
                if not (self.headers.get("Authorization") or "").startswith("Basic "):
                    self.send_error(401)
                    return
                data = json.dumps({"token": "tok"}).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return
            self._manifest(True)

        def do_PUT(self) -> None:
            ref = self._target()
            if ref is None:
                return
            data = self.rfile.read(int(self.headers["Content-Length"]))
            d = fake.add(data, self.headers.get("Content-Type", ""), ref)
            fake.puts.append((ref, d))
            self.send_response(201)
            self.send_header("Docker-Content-Digest", d)
            self.send_header("Content-Length", "0")
            self.end_headers()

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def case(title: str, fake: Fake, pins: list[str]):
    """Run keep() for REF against fake with pin files holding pins; return (message or Refused text, pushes)."""
    print(f"== {title} ==")
    pushes: list[tuple[str, str]] = []
    srv = serve(fake)
    with tempfile.TemporaryDirectory() as tmp:
        files = []
        for i, text in enumerate(pins):
            f = pathlib.Path(tmp) / f"pin{i}.yaml"
            f.write_text(text, encoding="utf-8")
            files.append(str(f))
        try:
            reg = gvt.Registry(f"http://127.0.0.1:{srv.server_address[1]}", REPO_NAME, "user", "secret")
            out = gvt.keep("web-terminal:built", REF, files, reg, push=lambda a, b: pushes.append((a, b)))
        except gvt.Refused as e:
            out = f"REFUSED: {e}"
        finally:
            srv.shutdown()
    return out, pushes


def pinned_index(fake: Fake) -> tuple[bytes, str]:
    """An index the way buildx writes one, with bytes json.dumps would not reproduce, so a re-serialised put shows."""
    body = b'{\n  "schemaVersion": 2,\n  "mediaType": "' + INDEX.encode() + b'",\n  "manifests": []\n}'
    return body, fake.add(body, INDEX)


TAG = REF.rsplit(":", 1)[1]

# 1. The tag already serves the pinned digest.
fake = Fake()
body, want = pinned_index(fake)
fake.tags[TAG] = want
out, pushes = case("pinned, and the tag serves the pin", fake, [f"image: {REF}@{want}\n"])
check("nothing is pushed", pushes == [], str(pushes))
check("nothing is put", fake.puts == [], str(fake.puts))
check("it says the tag serves the pin", "serves the pinned" in out, out)
check("the token asks for pull and push on the one repository", fake.scopes == [f"repository:{REPO_NAME}:pull,push"],
      str(fake.scopes))

# 2. A rebuild moved the tag: it goes back on the pinned digest, the same bytes and media type.
fake = Fake()
body, want = pinned_index(fake)
moved = fake.add(b'{"schemaVersion":2,"mediaType":"' + MANIFEST.encode() + b'","layers":[]}', MANIFEST, TAG)
out, pushes = case("pinned, and the tag has moved", fake, [f"image: {REF}@{want} # x\n", f"{REF}@{want} {want} repo:x -\n"])
check("the build is not pushed", pushes == [], str(pushes))
check("the one put is the tag, at the pinned digest", fake.puts == [(TAG, want)], str(fake.puts))
check("the tag serves the pinned digest again", fake.tags.get(TAG) == want, str(fake.tags))
check("the put carried the pinned manifest's own media type", fake.blobs[want] == (body, INDEX))
check("it names the digest the tag had moved to", moved in out and "back on the pinned" in out, out)

# 3. The pinned digest is not in the registry: refuse, touch nothing.
fake = Fake()
moved = fake.add(b'{"moved":1}', MANIFEST, TAG)
gone = "sha256:" + "ab" * 32
out, pushes = case("pinned at a digest the registry lacks", fake, [f"image: {REF}@{gone}\n"])
check("it refuses, naming the missing digest", out.startswith("REFUSED") and gone in out, out)
check("nothing is pushed or put", pushes == [] and fake.puts == [], f"{pushes} {fake.puts}")
check("the tag is left where it was", fake.tags.get(TAG) == moved)

# 4. Two pin files disagree on the digest: refuse before asking anything of the tag.
fake = Fake()
_, want = pinned_index(fake)
other = "sha256:" + "cd" * 32
out, pushes = case("pinned at two digests", fake, [f"{REF}@{want}\n", f"{REF}@{other}\n"])
check("it refuses, naming both digests", out.startswith("REFUSED") and want in out and other in out, out)
check("nothing is pushed or put", pushes == [] and fake.puts == [])

# 5. A new version, never pushed and not yet pinned: the build is pushed.
fake = Fake()
out, pushes = case("not pinned, and the tag is new", fake, [f"image: {REF.replace('9.9.9', '9.9.8')}@{'sha256:' + 'ef' * 32}\n"])
check("the build is pushed to the tag", pushes == [("web-terminal:built", REF)], str(pushes))
check("it asks for the digest to be pinned and signed", "pin its digest" in out and "sign" in out, out)

# 6. That new version was pushed already (the main promotion's run, say): the first push stays.
fake = Fake()
first = fake.add(b'{"first":1}', MANIFEST, TAG)
out, pushes = case("not pinned, and the tag exists", fake, [""])
check("the build is not pushed over it", pushes == [] and fake.puts == [], f"{pushes} {fake.puts}")
check("it names the digest to pin", f"{REF}@{first}" in out, out)

# 7. The workflow runs the script on the pin files, and runs when the script changes.
print("== the workflow ==")
workflow = (REPO / ".github/workflows/build-web-terminal.yml").read_text(encoding="utf-8")
call = "python3 scripts/ghcr_version_tag.py web-terminal:built \"${TAG}\" gitops/ai-layer/resources.yaml images.lock"
check(f"build-web-terminal.yml pushes through the script ({call})", call in workflow)
check("it has no docker push of its own", "docker push" not in workflow)
check("it runs on a change to the script", "- 'scripts/ghcr_version_tag.py'" in workflow)
check("the script's TAG is the tag the version step read", "TAG: ${{ steps.version.outputs.tag }}" in workflow)

# 8. The repo's own pins: the tag the workflow builds today is pinned at one digest across both pin files.
print("== the repo's pins ==")
texts = {p: (REPO / p).read_text(encoding="utf-8") for p in ("gitops/ai-layer/resources.yaml", "images.lock")}
refs = set(re.findall(r"ghcr\.io/peopleforrester/watch-it-burn:web-terminal-ttyd-[0-9.]+(?=@)", texts[
    "gitops/ai-layer/resources.yaml"]))
check(f"resources.yaml pins one web-terminal-ttyd tag ({sorted(refs)})", len(refs) == 1)
if len(refs) == 1:
    ref = next(iter(refs))
    try:
        d = gvt.pinned(ref, texts)
    except gvt.Refused as e:
        d = None
        print(f"    {e}")
    check(f"resources.yaml and images.lock pin {ref.rsplit(':', 1)[1]} at the one digest ({d})",
          d is not None and all(f"{ref}@{d}" in t for t in texts.values()))

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for name in failures:
        print(f"  - {name}")
    raise SystemExit(1)
print("The web-terminal build pushes only a new version tag and keeps a pinned one on its digest.")
