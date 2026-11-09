# ABOUTME: Holds the Backstage app's two Yarn pins (#1167) offline: the conditional-checksums lock against yarn.lock and
# ABOUTME: the plugin that reads it, packageManager's hash against the committed release, and each install that loads them.
"""verify/yarn_pins.py and the app's yarn-plugins/ close the two unchecked parts of the Backstage install (#1167):

- yarn-plugins/conditional-checksums.lock has one line for each platform-conditional entry of yarn.lock and no other,
  each checksum in yarn.lock's own cacheKey, each line in the form the plugin parses; where yarn.lock records a
  checksum for the same locator (fsevents' npm entries), the two agree.
- the plugin reads that path, with the same line rule as yarn_pins.LOCK_LINE, and wraps the fetch step.
- package.json's packageManager is yarn@<version>+sha512.<hex>, the hex the SHA-512 of the committed release
  yarnPath names (which is what corepack downloads from repo.yarnpkg.com, checked by hand in #1167's run).
- run-e2e.sh runs corepack-check and exports YARN_PLUGINS before `corepack yarn install --immutable`; the Dockerfile
  copies yarn-plugins and sets YARN_PLUGINS before its `yarn workspaces focus`; the README's build step sets it.
- corepack_check() on a made-up COREPACK_HOME: none yet passes, a matching folder passes, a changed yarn.js, a changed
  .corepack bin or hash, and a packageManager with no hash each fail, naming the file and both values.
- parse_lock(), npm_base(), fetch_npm() (with a stub fetch) and the Registry document rules, without node.
verify/test_yarn_pins_e2e.py runs the plugin with the app's own yarn on a loopback registry.
"""
from __future__ import annotations

import base64
import hashlib
import json
import pathlib
import re
import sys
import tempfile

VERIFY = pathlib.Path(__file__).resolve().parent
REPO = VERIFY.parent
sys.path.insert(0, str(VERIFY))
import yarn_pins as yp  # noqa: E402

APP = REPO / "images/watch-it-burn-backstage"
failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"\n        {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def refusal(fn) -> str:
    try:
        fn()
    except yp.YarnPinsError as e:
        return str(e)
    return ""


print("== the conditional-checksums lock against yarn.lock ==")
yarnlock = (APP / "yarn.lock").read_text(encoding="utf-8")
key = yp.cache_key(yarnlock)
conditional = yp.conditional(yarnlock)
lock = yp.parse_lock((APP / yp.LOCK_REL).read_text(encoding="utf-8"))
check(f"yarn.lock has platform-conditional entries ({len(conditional)})", len(conditional) > 50)
check("the lock has a line for each of them and for nothing else",
      set(lock) == set(conditional), f"missing {sorted(set(conditional) - set(lock))[:5]}, "
                                     f"extra {sorted(set(lock) - set(conditional))[:5]}")
check(f"each checksum is in yarn.lock's cacheKey ({key})", all(c.startswith(f"{key}/") for c, _ in lock.values()))
linux_x64 = sorted(loc for loc in lock if re.search(r"linux-x64(-gnu)?@", loc))
check(f"the linux x64 glibc binaries the issue names are among them ({len(linux_x64)})",
      {"@esbuild/linux-x64@npm:0.28.1", "@rollup/rollup-linux-x64-gnu@npm:4.62.0",
       "@swc/core-linux-x64-gnu@npm:1.15.41", "@rspack/binding-linux-x64-gnu@npm:1.7.12"} <= set(linux_x64))
summed = {e["resolution"]: e["checksum"] for e in yp.lock_entries(yarnlock) if e["checksum"]}
both = sorted(set(lock) & set(summed))
check(f"where yarn.lock records a checksum for the same locator ({both}), the two agree",
      bool(both) and all(lock[loc][0] == summed[loc] for loc in both))
bases = {yp.npm_base(loc) for loc in lock}
check(f"each line's integrity is its registry package's, one per package ({len(bases)} packages)",
      all(lock[f"{n}@npm:{v}"][1] == lock[loc][1] for loc in lock for n, v in [yp.npm_base(loc)]
          if f"{n}@npm:{v}" in lock))

print("== the plugin ==")
plugin = (APP / yp.PLUGIN_REL).read_text(encoding="utf-8")
check(f"it reads {yp.LOCK_REL}", f"const LOCK = `{yp.LOCK_REL}`;" in plugin)
line_rule = re.search(r"^const LINE = /(.*)/;$", plugin, re.M)
# A JavaScript regex literal escapes its slashes; Python's pattern does not.
check("its line rule is yarn_pins.LOCK_LINE's",
      bool(line_rule) and line_rule.group(1).replace("\\/", "/") == yp.LOCK_LINE.pattern,
      line_rule.group(1) if line_rule else "no LINE")
check("it wraps Project#fetchEverything, so it runs after the fetch step and before the link step",
      "Project.prototype.fetchEverything = async function" in plugin
      and "await fetchEverything.call(this, opts);\n        checkConditional(this, opts.cache, opts.report);" in plugin)
check("it skips only packages Yarn disabled for this platform, and fails with YN0018",
      "if (project.disabledLocators.has(locatorHash))" in plugin
      and "new ReportError(MessageName.CACHE_CHECKSUM_MISMATCH," in plugin)

print("== corepack's yarn: packageManager carries the committed release's SHA-512 ==")
package = json.loads((APP / "package.json").read_text(encoding="utf-8"))
version, pinned = yp.package_manager(APP)
release = yp.release_of(APP)
check(f"yarnPath names the packageManager release ({release.name})", release.name == f"yarn-{version}.cjs")
actual = hashlib.sha512(release.read_bytes()).hexdigest() if release.is_file() else ""
check(f"the pin is the committed release's SHA-512 ({pinned[:16]}...)", actual == pinned, actual)

print("== each install loads them ==")
rune2e = (VERIFY / "run-e2e.sh").read_text(encoding="utf-8")
body = re.search(r"^backstage_e2e\(\) \{\n(.*?)^\}", rune2e, re.M | re.S)
b = body.group(1) if body else ""
at_check = b.find('python3 "${SCRIPT_DIR}/yarn_pins.py" corepack-check "${PWD}"')
at_plugin = b.find(f'export YARN_PLUGINS="${{PWD}}/{yp.PLUGIN_REL}"')
at_env = b.find('done <<<"${node_env}"')
at_install = b.find("corepack yarn install --immutable")
check("run-e2e.sh checks COREPACK_HOME's yarn, after node-env sets it and before corepack runs",
      0 <= at_env < at_check < at_install, f"{at_env} {at_check} {at_install}")
check("and names the plugin in YARN_PLUGINS before the install", 0 <= at_plugin < at_install)
dockerfile = (APP / "packages/backend/Dockerfile").read_text(encoding="utf-8")
at_copy = dockerfile.find("COPY --chown=node:node yarn-plugins ./yarn-plugins")
at_env = dockerfile.find(f"ENV YARN_PLUGINS=/app/{yp.PLUGIN_REL}")
at_focus = dockerfile.find("yarn workspaces focus")
check("the Dockerfile copies yarn-plugins and sets YARN_PLUGINS before its install",
      0 <= at_copy < at_focus and 0 <= at_env < at_focus, f"{at_copy} {at_env} {at_focus}")
readme = (APP / "README.md").read_text(encoding="utf-8")
check("the README's build step sets YARN_PLUGINS on its install",
      f"YARN_PLUGINS=/src/{yp.PLUGIN_REL} yarn install --immutable" in readme)

print("== corepack_check() on a made-up COREPACK_HOME ==")
with tempfile.TemporaryDirectory() as tmp:
    t = pathlib.Path(tmp)
    app = t / "app"
    app.mkdir()
    js_bytes = b"// yarn\n"
    good = hashlib.sha512(js_bytes).hexdigest()
    (app / "package.json").write_text(json.dumps({"packageManager": f"yarn@4.13.0+sha512.{good}"}))
    home = t / "home"
    check("no folder yet passes, saying corepack checks its download",
          "corepack checks its download" in yp.corepack_check(app, home))
    folder = home / "v1/yarn/4.13.0"
    folder.mkdir(parents=True)
    (folder / "yarn.js").write_bytes(js_bytes)
    meta = {"locator": {"name": "yarn", "reference": f"4.13.0+sha512.{good}"}, "bin": ["yarn", "yarnpkg"],
            "hash": f"sha512.{good}"}
    (folder / ".corepack").write_text(json.dumps(meta))
    check("a matching folder passes", "matches the packageManager pin" in yp.corepack_check(app, home))
    (folder / "yarn.js").write_bytes(js_bytes + b"//\n")
    err = refusal(lambda: yp.corepack_check(app, home))
    check("a changed yarn.js fails, naming the file and both sums",
          str(folder / "yarn.js") in err and good in err and hashlib.sha512(js_bytes + b"//\n").hexdigest() in err, err)
    (folder / "yarn.js").write_bytes(js_bytes)
    (folder / ".corepack").write_text(json.dumps({**meta, "bin": {"yarn": "other.js"}}))
    err = refusal(lambda: yp.corepack_check(app, home))
    check("a .corepack that points the bin elsewhere fails", ".corepack records bin" in err, err)
    (folder / ".corepack").write_text(json.dumps({**meta, "hash": "sha512.00"}))
    check("a .corepack with another hash fails", ".corepack records bin" in refusal(lambda: yp.corepack_check(app, home)))
    (app / "package.json").write_text(json.dumps({"packageManager": "yarn@4.13.0"}))
    err = refusal(lambda: yp.corepack_check(app, home))
    check("a packageManager with no hash fails, naming it", "'yarn@4.13.0'" in err, err)

print("== the lock's rules, without node ==")
s = "10c0/" + "a" * 128
i = "sha512-" + base64.b64encode(b"x" * 64).decode()
check("a well-formed line parses", yp.parse_lock(f"# c\n\n@a/b@npm:1.0.0 {s} {i}\n") == {"@a/b@npm:1.0.0": (s, i)})
check("a short checksum is refused", "line 1" in refusal(lambda: yp.parse_lock(f"a@npm:1.0.0 10c0/ab {i}\n")))
check("two spaces are refused, as the plugin refuses them",
      "line 1" in refusal(lambda: yp.parse_lock(f"a@npm:1.0.0  {s} {i}\n")))
check("a locator twice is refused",
      "a second time" in refusal(lambda: yp.parse_lock(f"a@npm:1.0.0 {s} {i}\na@npm:1.0.0 {s} {i}\n")))
check("render_lock() output parses back", yp.parse_lock(yp.render_lock({"a@npm:1.0.0": (s, i)}, "yarn-x.cjs"))
      == {"a@npm:1.0.0": (s, i)})
check("npm_base() reads a registry locator", yp.npm_base("@esbuild/linux-x64@npm:0.28.1") == ("@esbuild/linux-x64", "0.28.1"))
check("and the package a patch locator patches",
      yp.npm_base("fsevents@patch:fsevents@npm%3A2.3.2#optional!builtin<compat/fsevents>::version=2.3.2&hash=df0bf1")
      == ("fsevents", "2.3.2"))
check("and refuses anything else", "not a registry locator" in refusal(lambda: yp.npm_base("app@workspace:packages/app")))
tgz = b"tarball bytes"
docs = {f"{yp.NPM_REGISTRY}/@a%2fb/1.0.0": json.dumps({"dist": {"tarball": "https://t/b.tgz",
                                                                  "integrity": yp.integrity_of(tgz)}}).encode()}
check("fetch_npm() keeps a tarball that matches dist.integrity",
      yp.fetch_npm("@a/b", "1.0.0", lambda u: docs.get(u, tgz))[1] == tgz)
err = refusal(lambda: yp.fetch_npm("@a/b", "1.0.0", lambda u: docs.get(u, b"other bytes")))
check("and fails on one that does not, naming the package and both values",
      "@a/b@1.0.0" in err and yp.integrity_of(tgz) in err and yp.integrity_of(b"other bytes") in err, err)
reg = yp.Registry({("@a/b", "1.0.0"): ({"os": ["linux"], "dependencies": {"c": "1"}, "gypfile": True,
                                        "scripts": {"install": "node-gyp rebuild"}}, tgz)})
reg.server.server_close()
v = reg.docs["/@a%2fb"]["versions"]["1.0.0"]
check("the loopback registry keeps os and drops what would pull in another package",
      v["os"] == ["linux"] and not set(yp.DROPPED) & set(v) and v["dist"]["integrity"] == yp.integrity_of(tgz)
      and v["dist"]["tarball"].startswith(reg.url + "/@a%2fb/-/b-1.0.0.tgz"), json.dumps(v))

if failures:
    print(f"\nFAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("\nAll yarn pin checks passed.")
