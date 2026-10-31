# ABOUTME: Pulls lab-platform's web image by the pinned digest with no credential (#668), runs its binary on each demo
# ABOUTME: app's web.yaml on loopback, and checks the page, /healthz and the 404s, and that :8080 needs the sandbox env.
# SUITE: e2e (needs the network: ghcr.io is asked for the image's manifest and layers)
# E2E TIER: tools (no cluster, no AWS: run-e2e-tools.sh runs it with the pinned tools, #572)
#
# Why. A node pulls web with no pull secret, so the pinned digest must answer an anonymous pull, or all five party
# hosts sit in ImagePullBackOff. And web refuses a routes file whole, by line, and the pod exits at start, so the
# file in each ConfigMap is run by the binary the cluster will run, not judged against a copy of its parser.
# The listen address and root are the two lines changed for the run: the routes are served as written.
from __future__ import annotations

import hashlib
import io
import json
import os
import pathlib
import socket
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from ghcr_pull import ACCEPT  # noqa: E402
from web_image import DEMO_APPS, DIGEST, GHCR, REPO, demo_files  # noqa: E402

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail and not ok else ""))
    if not ok:
        failures.append(name)


def done() -> None:
    print()
    if failures:
        print(f"FAILED: {len(failures)} check(s)")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    print("All demo app web serve checks passed.")
    sys.exit(0)


host, _, repo = GHCR.partition("/")


def get(url: str, token: str, accept: str = "") -> bytes:
    headers = {"Authorization": f"Bearer {token}"} | ({"Accept": accept} if accept else {})
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=120) as r:
        return r.read()


print(f"== {GHCR}@{DIGEST[:19]}... answers an anonymous pull ==")
try:
    with urllib.request.urlopen(f"https://{host}/token?scope=repository:{repo}:pull", timeout=30) as r:
        token = json.load(r)["token"]
    manifest = get(f"https://{host}/v2/{repo}/manifests/{DIGEST}", token, ACCEPT)
except (urllib.error.URLError, TimeoutError, KeyError, ValueError) as e:
    check("ghcr.io gives an anonymous token and the pinned manifest", False,
          f"{type(e).__name__}: {e}; a 401 on the token is a private package")
    done()
check("the manifest ghcr.io serves hashes to the pinned digest",
      "sha256:" + hashlib.sha256(manifest).hexdigest() == DIGEST)
layers = json.loads(manifest).get("layers") or []
binary = None
for layer in layers:
    blob = get(f"https://{host}/v2/{repo}/blobs/{layer['digest']}", token)
    check(f"layer {layer['digest'][:19]}... hashes to its digest",
          "sha256:" + hashlib.sha256(blob).hexdigest() == layer["digest"])
    with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tf:
        for m in tf.getmembers():
            if m.isfile() and m.name.lstrip("/") == "ko-app/web":
                binary = tf.extractfile(m).read()
check("one layer carries the image's entrypoint, /ko-app/web", binary is not None)
if binary is None:
    done()


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def fetch(url: str) -> tuple[int, str, bytes]:
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            return r.status, r.headers.get("Content-Type", ""), r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get("Content-Type", ""), e.read()


(REPO / "tmp").mkdir(exist_ok=True)
with tempfile.TemporaryDirectory(dir=REPO / "tmp") as tmp:
    # The binary in a directory of its own, run from another, so nothing beside it is read as code or config.
    bindir = pathlib.Path(tmp) / "bin"
    bindir.mkdir()
    web = bindir / "web"
    web.write_bytes(binary)
    web.chmod(0o755)
    env0 = {k: v for k, v in os.environ.items() if k != "NETWORK_BOUNDARY"}
    for app in DEMO_APPS:
        print(f"== demo-app-{app}: the pinned binary serves its web.yaml ==")
        files = demo_files(app)
        run = pathlib.Path(tmp) / app
        (run / "www").mkdir(parents=True)
        (run / "www/index.html").write_text(files["index.html"], encoding="utf-8")
        as_written = run / "as-written.yaml"
        as_written.write_text(files["web.yaml"], encoding="utf-8")
        r = subprocess.run([str(web)], env=env0 | {"WEB_CONFIG": str(as_written)}, capture_output=True, text=True,
                           timeout=20, cwd=run)
        check("as written, with no NETWORK_BOUNDARY, it parses and then refuses the all-interfaces bind",
              r.returncode == 1 and "every interface" in r.stdout and "NETWORK_BOUNDARY=sandbox" in r.stdout,
              (r.stdout + r.stderr).strip()[:300])
        port = free_port()
        text = files["web.yaml"]
        check("the file's listen and root are the two lines this run replaces",
              text.count('listen: ":8080"\n') == 1 and text.count("root: /srv/www\n") == 1)
        loop = run / "web.yaml"
        loop.write_text(text.replace('listen: ":8080"\n', f'listen: "127.0.0.1:{port}"\n')
                        .replace("root: /srv/www\n", f"root: {run / 'www'}\n"), encoding="utf-8")
        p = subprocess.Popen([str(web)], env=env0 | {"WEB_CONFIG": str(loop)}, stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, text=True, cwd=run)
        try:
            base = f"http://127.0.0.1:{port}"
            for _ in range(50):
                try:
                    socket.create_connection(("127.0.0.1", port), timeout=1).close()
                    break
                except OSError:
                    if p.poll() is not None:
                        break
                    time.sleep(0.1)
            status, ctype, body = fetch(base + "/")
            check("/ is the page, as text/html", status == 200 and ctype.startswith("text/html")
                  and body.decode() == files["index.html"], f"{status} {ctype}")
            status, _, body = fetch(base + "/healthz")
            check("/healthz answers ok, the liveness probe's path", status == 200 and body == b"ok\n", f"{status} {body!r}")
            for path in ("/index.html", "/web.yaml", "/..data/index.html", "/nope"):
                status, _, _ = fetch(base + path)
                check(f"{path} is a 404: nothing the routes do not name is served", status == 404, str(status))
        finally:
            p.terminate()
            out, _ = p.communicate(timeout=10)
        check("it logged no error", '"level":"ERROR"' not in out, out.strip()[:300])

done()
