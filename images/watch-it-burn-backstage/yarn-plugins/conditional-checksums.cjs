// ABOUTME: Checks each platform-conditional package an install fetches against yarn-plugins/conditional-checksums.lock
// ABOUTME: before anything is linked (#1167): Yarn 4 records and checks no checksum for those, so a bad zip failed nothing.
//
// Yarn 4.13.0 treats a package with a `conditions:` line in yarn.lock (an optional native binary such as
// @esbuild/linux-x64) as unstable: its cache zip is never hashed and yarn.lock records no checksum for it, whatever
// checksumBehavior says. This plugin wraps Project#fetchEverything, so after the fetch step and before the link step
// (and so before any package's build script runs) it hashes the cache zip of every conditional package this install
// enabled, in the cache's own `<cacheKey>/<sha512>` form, and compares it with the lock. A zip that does not match, a
// package the lock has no line for, or an enabled package with no cache zip fails the install with YN0018, naming the
// package, the file and both checksums. Nothing is deleted or fetched again. Packages for other platforms are mocked by
// Yarn, never fetched, and so never read here.
//
// verify/yarn_pins.py write records the lock: each conditional tarball checked against npm's dist.integrity, then
// zipped by this app's own yarn release. verify/test_yarn_pins.py holds the lock against yarn.lock, and
// verify/test_yarn_pins_e2e.py runs this plugin on a fixture registry.
const crypto = require(`crypto`);
const fs = require(`fs`);
const path = require(`path`);

const LOCK = `yarn-plugins/conditional-checksums.lock`;
const PATCHED = Symbol.for(`wib.conditionalChecksums.patched`);
const LINE = /^(\S+) ([0-9a-z]+\/[0-9a-f]{128}) (sha512-[A-Za-z0-9+/]+=*)$/;

function readLock(file) {
  let text;
  try {
    text = fs.readFileSync(file, `utf8`);
  } catch (err) {
    throw new Error(`${LOCK} cannot be read (${err.message}); verify/yarn_pins.py write records it`);
  }
  const lock = new Map();
  text.split(`\n`).forEach((raw, i) => {
    if (raw === `` || raw.startsWith(`#`))
      return;
    const m = LINE.exec(raw);
    if (!m)
      throw new Error(`${LOCK} line ${i + 1} is not "<locator> <cacheKey>/<sha512> sha512-<npm integrity>": ${raw}`);
    if (lock.has(m[1]))
      throw new Error(`${LOCK} line ${i + 1} records ${m[1]} a second time`);
    lock.set(m[1], m[2]);
  });
  return lock;
}

function sha512(file) {
  const hash = crypto.createHash(`sha512`);
  const fd = fs.openSync(file, `r`);
  try {
    const buf = Buffer.allocUnsafe(1 << 20);
    let n;
    while ((n = fs.readSync(fd, buf, 0, buf.length, null)) > 0)
      hash.update(n === buf.length ? buf : buf.subarray(0, n));
  } finally {
    fs.closeSync(fd);
  }
  return hash.digest(`hex`);
}

module.exports = {
  name: `plugin-conditional-checksums`,
  factory: require => {
    const {Project, ReportError, MessageName, structUtils} = require(`@yarnpkg/core`);
    if (typeof Project?.prototype?.fetchEverything !== `function`)
      throw new Error(`plugin-conditional-checksums: this yarn has no Project#fetchEverything to check the fetch step after`);

    function checkConditional(project, cache, report) {
      const lock = readLock(path.join(project.cwd, LOCK));
      const seen = new Set();
      const bad = [];
      for (const locatorHash of project.conditionalLocators) {
        if (project.disabledLocators.has(locatorHash))
          continue;
        const pkg = project.storedPackages.get(locatorHash);
        if (!pkg)
          throw new Error(`Assertion failed: conditional locator ${locatorHash} has no stored package`);
        const locator = structUtils.isVirtualLocator(pkg) ? structUtils.devirtualizeLocator(pkg) : pkg;
        if (seen.has(locator.locatorHash))
          continue;
        seen.add(locator.locatorHash);
        const name = structUtils.stringifyLocator(locator);
        const want = lock.get(name);
        if (want === undefined) {
          bad.push(`${name}: ${LOCK} records no checksum for it`);
          continue;
        }
        const file = cache.getLocatorPath(locator, null);
        if (!fs.existsSync(file)) {
          bad.push(`${name}: no cache zip at ${file}`);
          continue;
        }
        const got = `${cache.cacheKey}/${sha512(file)}`;
        if (got !== want) {
          bad.push(`${name}: ${file} is ${got}, but ${LOCK} records ${want}`);
        }
      }
      if (bad.length > 0)
        throw new ReportError(MessageName.CACHE_CHECKSUM_MISMATCH, `A platform-conditional package doesn't match ${LOCK}:\n  ${bad.join(`\n  `)}`);
      report.reportInfo(null, `${seen.size} platform-conditional package(s) match ${LOCK}`);
    }

    if (!Project.prototype[PATCHED]) {
      const fetchEverything = Project.prototype.fetchEverything;
      Project.prototype.fetchEverything = async function (opts) {
        await fetchEverything.call(this, opts);
        checkConditional(this, opts.cache, opts.report);
      };
      Project.prototype[PATCHED] = true;
    }

    return {default: {}};
  },
};
