# ABOUTME: scripts/ghcr_version_tag.py never pushes a build over a version tag (#816), puts a pinned tag on its digest (#828),
# ABOUTME: pushes new source to web-terminal-ttyd-<v>-<n> (#838), and a Joker build only to its pin (#775). Offline, docker stubbed.
"""Offline. The live half is verify/test_image_version_tags.py (tools tier): ghcr.io must serve
web-terminal-ttyd-<v> at the digest gitops/ai-layer/resources.yaml pins.

#816: build-web-terminal.yml pushed every rebuild over web-terminal-ttyd-1.7.7, and the build is not reproducible, so
the tag moved off the pinned, signed digest on each push run. Each row of the script's table is a case here, run
against a registry that keeps manifests by digest and tags by name, the way ghcr.io does, and the workflow is held to
calling the script with the pin files and running when the script changes.

#828: #814 pinned sample-app-nginx-1.27.5 at a digest ghcr.io had under the old sample-app tag only, so the tag answered
404. keep-sample-app-tag.yml runs the script with no build ("-"); its cases and the workflow are held here too.

#838: a change to images/web-terminal under the same ttyd version had no tag to go to. ship() finds the tag whose image
carries the build's source-tree label, or the first free web-terminal-ttyd-<v>[-<n>]; its cases are run here, with the
build's labels stubbed, against images whose config blobs the fake registry serves.
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
            m = re.fullmatch(rf"/v2/{re.escape(REPO_NAME)}/(?:manifests|blobs)/(.+)", self.path)
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


def case(title: str, fake: Fake, pins: list[str], local: str | None = "web-terminal:built", run=None):
    """Run keep() for REF against fake with pin files holding pins (or run(reg, files, push), for ship()); return
    (message or Refused text, pushes)."""
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
            push = lambda a, b: pushes.append((a, b))  # noqa: E731
            out = run(reg, files, push) if run else gvt.keep(local, REF, files, reg, push=push)
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

# 6b. Pinned, and ghcr.io has no such tag (sample-app-nginx-1.27.5 after #814): the tag is put on the pin.
fake = Fake()
body, want = pinned_index(fake)
out, pushes = case("pinned, and the tag is missing", fake, [f"image: {REF}@{want}\n"])
check("the build is not pushed", pushes == [], str(pushes))
check("the one put is the tag, at the pinned digest", fake.puts == [(TAG, want)], str(fake.puts))
check("the put carried the pinned manifest's bytes and media type", fake.blobs[want] == (body, INDEX))
check("it says the tag was missing and now serves the pin", "was not on the registry" in out and want in out, out)

# 6c. No build ("-", keep-sample-app-tag.yml): a pinned tag that is missing or moved is put on the pin, as with one.
for title, moved in (("no build, pinned, and the tag is missing", False), ("no build, pinned, and the tag has moved", True)):
    fake = Fake()
    body, want = pinned_index(fake)
    if moved:
        fake.add(b'{"moved":1}', MANIFEST, TAG)
    out, pushes = case(title, fake, [f"image: {REF}@{want}\n", f"{REF}@{want} {want} repo:x -\n"], local=None)
    check("nothing is pushed", pushes == [], str(pushes))
    check("the one put is the tag, at the pinned digest", fake.puts == [(TAG, want)], str(fake.puts))
    check("the tag serves the pinned digest", fake.tags.get(TAG) == want, str(fake.tags))

# 6d. No build, and nothing pins the tag: refuse, whether ghcr.io has it or not, and touch nothing.
for title, present in (("no build, not pinned, and the tag is new", False), ("no build, not pinned, and the tag exists", True)):
    fake = Fake()
    if present:
        fake.add(b'{"first":1}', MANIFEST, TAG)
    before = dict(fake.tags)
    out, pushes = case(title, fake, [""], local=None)
    check("it refuses, saying there is no build", out.startswith("REFUSED") and "no build" in out, out)
    check("nothing is pushed or put", pushes == [] and fake.puts == [] and fake.tags == before,
          f"{pushes} {fake.puts}")

# 6e. The command line: "-" is no build, and goes to keep(); a local image goes to ship().
print("== the command line ==")
seen: list = []
real_keep, real_ship, real_registry = gvt.keep, gvt.ship, gvt.Registry
gvt.keep = lambda local, ref, files, reg: seen.append(("keep", local, ref, files)) or "ok"
gvt.ship = lambda local, ref, files, reg: seen.append(("ship", local, ref, files)) or "ok"
gvt.Registry = lambda *a: None
import os
os.environ["GHCR_USER"], os.environ["GHCR_TOKEN"] = "u", "t"
try:
    rc = gvt.main(["-", REF, "a.yaml", "images.lock"])
    rc2 = gvt.main(["web-terminal:built", REF, "a.yaml", "images.lock"])
finally:
    gvt.keep, gvt.ship, gvt.Registry = real_keep, real_ship, real_registry
check("\"-\" reaches keep() as no build, with the ref and the pin files",
      rc == 0 and seen[:1] == [("keep", None, REF, ["a.yaml", "images.lock"])], f"{rc} {seen}")
check("a local image reaches ship(), with the ref and the pin files",
      rc2 == 0 and seen[1:] == [("ship", "web-terminal:built", REF, ["a.yaml", "images.lock"])], f"{rc2} {seen}")

# 6f. #838: a build under a version that already has a tag. Each image here is a config blob carrying labels, a
# manifest naming it, and, when index=True, an OCI index over that manifest the way buildx writes one.
TREE, OTHER = "a" * 40, "b" * 40


def image(fake: Fake, tree: str | None, index: bool = False, tag: str | None = None) -> str:
    labels = {gvt.SOURCE_TREE: tree} if tree else None
    config = json.dumps({"architecture": "amd64", "os": "linux", "config": {"Labels": labels}}).encode()
    cd = fake.add(config, "application/vnd.oci.image.config.v1+json")
    m = fake.add(json.dumps({"schemaVersion": 2, "mediaType": MANIFEST, "layers": [],
                             "config": {"mediaType": "application/vnd.oci.image.config.v1+json", "digest": cd,
                                        "size": len(config)}}).encode(), MANIFEST, None if index else tag)
    if not index:
        return m
    return fake.add(json.dumps({"schemaVersion": 2, "mediaType": INDEX, "manifests": [
        {"mediaType": MANIFEST, "digest": m, "platform": {"architecture": "amd64", "os": "linux"}},
        {"mediaType": MANIFEST, "digest": "sha256:" + "0" * 64,
         "platform": {"architecture": "unknown", "os": "unknown"}}]}).encode(), INDEX, tag)


def shipping(title: str, fake: Fake, pins: list[str], tree: str | None = TREE):
    labels = {gvt.SOURCE_TREE: tree} if tree else {}
    seen_local: list[str] = []

    def run(reg, files, push):
        return gvt.ship("web-terminal:built", REF, files, reg, push=push,
                        labels_of=lambda local: seen_local.append(local) or labels)
    out, pushes = case(title, fake, pins, run=run)
    print("    " + out.replace("\n", "\n    "))
    return out, pushes, seen_local


# A new ttyd version: nothing of it on ghcr.io, nothing pinned. The build goes to the bare version tag.
fake = Fake()
out, pushes, seen_local = shipping("#838: a new version", fake, [""])
check("its labels are read from the local build", seen_local == ["web-terminal:built"], str(seen_local))
check("the build is pushed to the bare version tag", pushes == [("web-terminal:built", REF)], str(pushes))

# The version's tag is pinned and was built from other source (or carries no label, as 68004fb5 does): -1.
for title, tree in (("#838: the pinned tag was built from other source", OTHER),
                    ("#838: the pinned tag carries no source label", None)):
    fake = Fake()
    want = image(fake, tree, index=True, tag=TAG)
    out, pushes, _ = shipping(title, fake, [f"image: {REF}@{want}\n", f"{REF}@{want} {want} repo:x -\n"])
    check("the build is pushed to <tag>-1", pushes == [("web-terminal:built", f"{REF}-1")], str(pushes))
    check("nothing is put, and the pinned tag still serves its pin", fake.puts == [] and fake.tags[TAG] == want,
          f"{fake.puts} {fake.tags}")
    check("it says -1 is the first free tag", f"{REF}-1 is the first free one" in out, out)

# The main promotion's run of a source staging's run already pushed to -1: found by its label, not pushed again.
fake = Fake()
want = image(fake, None, index=True, tag=TAG)
first = image(fake, TREE, tag=f"{TAG}-1")
out, pushes, _ = shipping("#838: <tag>-1 already carries this source", fake, [f"image: {REF}@{want}\n"])
check("the build is not pushed", pushes == [] and fake.puts == [], f"{pushes} {fake.puts}")
check("it names <tag>-1's digest to pin", f"{REF}-1@{first}" in out and "Pin" in out, out)
check("it does not touch <tag>-2", f"{TAG}-2" not in fake.tags, str(fake.tags))

# The pinned tag carries this source (a workflow-only edit): it serves its pin, so nothing happens.
fake = Fake()
want = image(fake, TREE, index=True, tag=TAG)
out, pushes, _ = shipping("#838: the pinned tag carries this source", fake, [f"image: {REF}@{want}\n"])
check("nothing is pushed or put", pushes == [] and fake.puts == [], f"{pushes} {fake.puts}")
check("it says the tag serves the pin", "serves the pinned" in out, out)

# The pinned tag has moved, and its pinned image is other source: it goes back on its pin, the build goes to -1.
fake = Fake()
want = image(fake, OTHER, index=True)
moved = image(fake, TREE, tag=TAG)
out, pushes, _ = shipping("#838: the pinned tag has moved, and the build is new source", fake, [f"image: {REF}@{want}\n"])
check("the pinned tag is put back on its pin", fake.puts == [(TAG, want)] and fake.tags[TAG] == want,
      f"{fake.puts} {fake.tags}")
check("the pin's labels decide, not the moved image's: the build is pushed to -1",
      pushes == [("web-terminal:built", f"{REF}-1")], str(pushes))

# Pinned at -1, -2 on ghcr.io from other source, unpinned: the build goes to -3.
fake = Fake()
image(fake, None, index=True, tag=TAG)
want = image(fake, OTHER, tag=f"{TAG}-1")
image(fake, "c" * 40, tag=f"{TAG}-2")
out, pushes, _ = shipping("#838: -1 pinned, -2 other source", fake, [f"image: {REF}-1@{want}\n"])
check("the build is pushed to <tag>-3", pushes == [("web-terminal:built", f"{REF}-3")], str(pushes))
check("nothing is put", fake.puts == [], str(fake.puts))

# A build without the label cannot be told from any tag's: refuse, touch nothing.
fake = Fake()
image(fake, OTHER, tag=TAG)
before = dict(fake.tags)
out, pushes, _ = shipping("#838: the build carries no source label", fake, [""], tree=None)
check("it refuses, naming the label", out.startswith("REFUSED") and gvt.SOURCE_TREE in out, out)
check("nothing is pushed or put", pushes == [] and fake.puts == [] and fake.tags == before, f"{pushes} {fake.puts}")

# A pinned digest the registry lacks: its labels cannot be read, so refuse.
fake = Fake()
gone = "sha256:" + "ab" * 32
out, pushes, _ = shipping("#838: pinned at a digest the registry lacks", fake, [f"image: {REF}@{gone}\n"])
check("it refuses, naming the missing digest", out.startswith("REFUSED") and gone in out, out)
check("nothing is pushed or put", pushes == [] and fake.puts == [], f"{pushes} {fake.puts}")

# 6g. #775: a reproducible build ("crane:<ref>", push-jokers.yml). A pinned digest the registry lacks is pushed from the
# build only when the build's digest is that pin; every other row acts as it does with any build.
LOCAL = "127.0.0.1:5000/festival-ops/maintenance-shell:busybox-9.9.9-internal"


def reproducible(fake: Fake, body: bytes, digest_of_build: str, lands: bytes | None = None):
    """keep() with a crane build whose digest is digest_of_build; a push lands `lands` (default: body) at the tag."""
    def run(reg, files, push):
        def landing(a, b):
            push(a, b)
            fake.add(lands if lands is not None else body, MANIFEST, TAG)
        return gvt.keep(LOCAL, REF, files, reg, push=landing, built=lambda local: digest_of_build)
    return run


built_body = b'{"schemaVersion":2,"mediaType":"' + MANIFEST.encode() + b'","layers":[{"joker":"internal"}]}'
pin = digest(built_body)
for title, moved in (("#775: pinned, the registry lacks the pin, and the build is the pin", False),
                     ("#775: pinned, the tag has moved, the registry lacks the pin, and the build is the pin", True)):
    fake = Fake()
    if moved:
        fake.add(b'{"moved":1}', MANIFEST, TAG)
    out, pushes = case(title, fake, [f"{REF}@{pin} {pin} repo:x -\n"], run=reproducible(fake, built_body, pin))
    check("the build is pushed to the tag, once", pushes == [(LOCAL, REF)], str(pushes))
    check("no manifest is put by hand", fake.puts == [], str(fake.puts))
    check("the tag serves the pin", fake.tags.get(TAG) == pin, str(fake.tags))
    check("it says the build at the pin was pushed", "is pushed to it" in out and pin in out, out)

fake = Fake()
other_build = "sha256:" + "12" * 32
out, pushes = case("#775: pinned, the registry lacks the pin, and the build is another digest", fake,
                   [f"{REF}@{pin} {pin} repo:x -\n"], run=reproducible(fake, built_body, other_build))
check("it refuses, naming the pin and the build's digest", out.startswith("REFUSED") and pin in out and other_build in out,
      out)
check("nothing is pushed or put", pushes == [] and fake.puts == [] and fake.tags == {}, f"{pushes} {fake.puts}")

fake = Fake()
out, pushes = case("#775: the push lands a digest other than the pin", fake, [f"{REF}@{pin} {pin} repo:x -\n"],
                   run=reproducible(fake, built_body, pin, lands=b'{"recompressed":1}'))
check("it refuses, saying what the tag serves", out.startswith("REFUSED") and "it serves" in out, out)

fake = Fake()
fake.add(built_body, MANIFEST, TAG)
out, pushes = case("#775: the tag already serves the pin (the workshop Joker)", fake, [f"{REF}@{pin} {pin} repo:x -\n"],
                   run=reproducible(fake, built_body, "sha256:" + "34" * 32))
check("nothing is pushed or put, and the build is not even compared", pushes == [] and fake.puts == [], str(pushes))
check("it says the tag serves the pin", "serves the pinned" in out, out)

fake = Fake()
body, want = pinned_index(fake)
fake.add(b'{"moved":1}', MANIFEST, TAG)
out, pushes = case("#775: the tag moved and the registry has the pin", fake, [f"{REF}@{want}\n"],
                   run=reproducible(fake, built_body, pin))
check("the pinned manifest is put back, and the build is not pushed", pushes == [] and fake.puts == [(TAG, want)],
      f"{pushes} {fake.puts}")

fake = Fake()
out, pushes = case("#775: a build with no digest reader (docker) and a pin the registry lacks still refuses", fake,
                   [f"{REF}@{pin}\n"])
check("it refuses, naming the missing digest, and pushes nothing", out.startswith("REFUSED") and pin in out
      and pushes == [], out)

# The command line: "crane:<ref>" reaches keep() with crane's push and digest reader, not ship().
seen = []
gvt.keep = lambda local, ref, files, reg, **kw: seen.append(("keep", local, ref, files, kw)) or "ok"
gvt.ship = lambda *a, **kw: seen.append(("ship",)) or "ok"
gvt.Registry = lambda *a: None
try:
    rc = gvt.main([f"crane:{LOCAL}", REF, "images.lock"])
finally:
    gvt.keep, gvt.ship, gvt.Registry = real_keep, real_ship, real_registry
check("\"crane:<ref>\" reaches keep() with the ref behind the prefix, crane_push and crane_digest",
      rc == 0 and seen == [("keep", LOCAL, REF, ["images.lock"], {"push": gvt.crane_push, "built": gvt.crane_digest})],
      f"{rc} {seen}")

# 7. The workflow runs the script on the pin files, and runs when the script changes.
print("== the workflow ==")
workflow = (REPO / ".github/workflows/build-web-terminal.yml").read_text(encoding="utf-8")
call = "python3 scripts/ghcr_version_tag.py web-terminal:built \"${TAG}\" gitops/ai-layer/resources.yaml images.lock"
check(f"build-web-terminal.yml pushes through the script ({call})", call in workflow)
check("it has no docker push of its own", "docker push" not in workflow)
check("it runs on a change to the script", "- 'scripts/ghcr_version_tag.py'" in workflow)
check("the script's TAG is the tag the version step read", "TAG: ${{ steps.version.outputs.tag }}" in workflow)
check("the build labels the image with the source tree, under the key the script reads",
      f"labels: {gvt.SOURCE_TREE}=${{{{ steps.tree.outputs.tree }}}}" in workflow)
check("the tree step reads the git tree id of images/web-terminal",
      'echo "tree=$(git rev-parse HEAD:images/web-terminal)" >> "${GITHUB_OUTPUT}"' in workflow)
check("one build runs at a time, so two runs cannot take one -<n>",
      re.search(r"^concurrency:\n  group: build-web-terminal\n  cancel-in-progress: false$", workflow, re.M) is not None)

# 7b. keep-sample-app-tag.yml runs the script with no build, on the pins, when the pins, the script or it changes.
print("== keep-sample-app-tag.yml ==")
keeper_text = (REPO / ".github/workflows/keep-sample-app-tag.yml").read_text(encoding="utf-8")
call = ('python3 scripts/ghcr_version_tag.py - "${TAG}" backstage/k8s/templated-test-svc.yaml images.lock')
check(f"it calls the script with no build on both pin files ({call})", call in keeper_text)
for path in ("backstage/k8s/templated-test-svc.yaml", "images.lock", ".github/workflows/keep-sample-app-tag.yml",
             "scripts/ghcr_version_tag.py"):
    check(f"it runs on a change to {path}", f"- '{path}'" in keeper_text)
check("it runs on pushes to staging and main", "branches: [staging, main]" in keeper_text)
check("it builds and pushes nothing of its own", not re.search(r"docker (push|build)|build-push-action|crane", keeper_text))
check("the script's TAG is the tag the pin step read", "TAG: ${{ steps.pin.outputs.tag }}" in keeper_text)
# The pin step's shell, run here on the repo's templated-test-svc.yaml, reads the one tag the test below reads.
import subprocess
step = re.search(r"id: pin\n\s+run: \|\n((?:\s{10}.+\n)+)", keeper_text)
check("the workflow has a pin step whose shell this test can run", step is not None)
if step:
    script = "\n".join(line[10:] for line in step.group(1).splitlines())
    with tempfile.TemporaryDirectory() as tmp:
        outf = pathlib.Path(tmp) / "out"
        r = subprocess.run(["bash", "-euo", "pipefail", "-c", script], cwd=REPO, capture_output=True, text=True,
                           env={**os.environ, "GITHUB_OUTPUT": str(outf)})
        read = outf.read_text() if outf.exists() else ""
    svc = (REPO / "backstage/k8s/templated-test-svc.yaml").read_text(encoding="utf-8")
    pins = sorted(set(re.findall(r"ghcr\.io/peopleforrester/watch-it-burn:sample-app-nginx-[0-9.]+(?=@)", svc)))
    check(f"the pin step reads tag={pins[0] if len(pins) == 1 else pins}",
          r.returncode == 0 and len(pins) == 1 and read == f"tag={pins[0]}\n", f"{r.returncode} {read!r} {r.stderr}")
    # A second tag, built from the pinned one: a literal watch-it-burn reference here would be one
    # test_image_version_tags.py holds to the pinned tag.
    with tempfile.TemporaryDirectory() as tmp:
        (pathlib.Path(tmp) / "backstage/k8s").mkdir(parents=True)
        (pathlib.Path(tmp) / "backstage/k8s/templated-test-svc.yaml").write_text(
            svc + f"\n# image: {pins[0].rsplit('-', 1)[0]}-9.9.9@sha256:" + "0" * 64 + "\n")
        r = subprocess.run(["bash", "-euo", "pipefail", "-c", script], cwd=tmp, capture_output=True, text=True,
                           env={**os.environ, "GITHUB_OUTPUT": str(pathlib.Path(tmp) / "out")})
    check("with two sample-app-nginx tags pinned, the pin step fails", r.returncode != 0 and "not one" in r.stderr,
          f"{r.returncode} {r.stderr}")

# 7c. push-jokers.yml (#775): builds both Jokers on loopback with no credential, then hands each tag to the script.
print("== push-jokers.yml ==")
import yaml
jokers_text = (REPO / ".github/workflows/push-jokers.yml").read_text(encoding="utf-8")
jokers = yaml.safe_load(jokers_text)
steps = jokers["jobs"]["jokers"]["steps"]
for path in ("images/villains/**", "images.lock", "verify/e2e-tools.lock", ".github/workflows/push-jokers.yml",
             "scripts/ghcr_version_tag.py"):
    check(f"it runs on a change to {path}", f"- '{path}'" in jokers_text)
check("it runs on pushes to staging and main", "branches: [staging, main]" in jokers_text)
check("one run at a time", re.search(r"^concurrency:\n  group: push-jokers\n  cancel-in-progress: false$", jokers_text,
                                     re.M) is not None)
build_steps = [s for s in steps if "build-loopback.sh" in str(s.get("run", ""))]
check("one step builds with images/villains/build-loopback.sh on 127.0.0.1:5000",
      len(build_steps) == 1 and "bash images/villains/build-loopback.sh 127.0.0.1:5000" in build_steps[0]["run"])
holders = [s.get("name") for s in steps if "GHCR_TOKEN" in str(s.get("env", ""))]
check("only the step that calls the script holds GHCR_TOKEN, and the build step does not",
      len(holders) == 1 and build_steps and "GHCR_TOKEN" not in str(build_steps[0]) and
      "python3 scripts/ghcr_version_tag.py" in next(str(s["run"]) for s in steps if s.get("name") == holders[0]),
      str(holders))
fetch = next((str(s["run"]) for s in steps if "e2e-tools.lock" in str(s.get("run", ""))), "")
check("it fetches crane from e2e-tools.lock's row and checks its SHA-256 before running it",
      "grep -E '^crane[[:space:]]' verify/e2e-tools.lock" in fetch and "sha256sum -c -" in fetch)
loop = re.search(r"for tag in ([^;]+); do\n\s+(python3 scripts/ghcr_version_tag\.py .+)\n", jokers_text)
call = ('python3 scripts/ghcr_version_tag.py "crane:127.0.0.1:5000/festival-ops/maintenance-shell:${tag}" '
        '"ghcr.io/peopleforrester/festival-ops/maintenance-shell:${tag}" images.lock')
check(f"each tag goes to the script as a crane: build, pinned by images.lock ({call})", bool(loop) and loop.group(2) == call)
build_sh = (REPO / "images/villains/build.sh").read_text(encoding="utf-8")
joker_ref = re.search(r'^JOKER_REF="([^"]+)"$', build_sh, re.M)
internal_suffix = re.search(r'^JOKER_INTERNAL_REF="\$\{JOKER_REF\}(-[a-z0-9.-]+)"$', build_sh, re.M)
if joker_ref and internal_suffix:
    ref_tags = [joker_ref.group(1).rsplit(":", 1)[1], joker_ref.group(1).rsplit(":", 1)[1] + internal_suffix.group(1)]
else:
    ref_tags = []
check(f"the tags it keeps are the two build.sh builds ({ref_tags})", bool(loop) and loop.group(1).split() == ref_tags,
      loop.group(1) if loop else "no loop")
lock_text = (REPO / "images.lock").read_text(encoding="utf-8")
for tag in ref_tags:
    ref = f"ghcr.io/peopleforrester/festival-ops/maintenance-shell:{tag}"
    try:
        d = gvt.pinned(ref, {"images.lock": lock_text})
    except gvt.Refused:
        d = None
    check(f"images.lock pins {tag} at one digest, so the script has a pin to keep", d is not None)

# 8. The repo's own pins: the tag the workflow builds today is pinned at one digest across both pin files.
print("== the repo's pins ==")
texts = {p: (REPO / p).read_text(encoding="utf-8") for p in ("gitops/ai-layer/resources.yaml", "images.lock")}
refs = set(re.findall(r"ghcr\.io/peopleforrester/watch-it-burn:web-terminal-ttyd-[0-9.]+(?:-[1-9][0-9]*)?(?=@)", texts[
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
texts = {p: (REPO / p).read_text(encoding="utf-8") for p in ("backstage/k8s/templated-test-svc.yaml", "images.lock")}
refs = set(re.findall(r"ghcr\.io/peopleforrester/watch-it-burn:sample-app-nginx-[0-9.]+(?=@)", "".join(texts.values())))
check(f"templated-test-svc.yaml and images.lock name one sample-app-nginx tag ({sorted(refs)})", len(refs) == 1)
if len(refs) == 1:
    ref = next(iter(refs))
    try:
        d = gvt.pinned(ref, texts)
    except gvt.Refused as e:
        d = None
        print(f"    {e}")
    check(f"both pin {ref.rsplit(':', 1)[1]} at the one digest ({d}), so keep-sample-app-tag has one to put",
          d is not None and all(f"{ref}@{d}" in t for t in texts.values()))

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for name in failures:
        print(f"  - {name}")
    raise SystemExit(1)
print("The web-terminal build pushes new source to a tag ghcr.io lacks and keeps a pinned one on its digest; keep-sample-app-tag")
print("puts sample-app's pinned tag on its digest with no build; push-jokers pushes a reproducible Joker only to its pin.")
