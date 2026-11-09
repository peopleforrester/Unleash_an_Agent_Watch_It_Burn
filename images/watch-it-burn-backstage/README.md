# [Backstage](https://backstage.io)

The image behind the workshop's developer portal (#244). Everything the portal shows on a cluster (the
catalog, guest sign-in, the cluster in the Kubernetes tab, Postgres) comes from `backstage/` at the repo root,
not from this image.

## Rebuild, push, sign and pin

The tag names what is inside: `backstage-<backstage.json version>-node<base Node version>`, for example
`backstage-1.52.0-node24.22.2`. `verify/test_backstage_catalog.py` fails if the pinned tag and those two
disagree.

The host steps run on Node 24, so on a machine with another Node run them inside the base image. Rootless
buildah, from this directory:

```bash
# 1. install, type-check and build the backend bundle, on the image's own Node
ctr=$(buildah from ghcr.io/peopleforrester/lab-platform/mirror/library/node:24.22.2-trixie-slim-e053394f1551@sha256:e053394f15519046270b637f0655c284d2fc844e013451fcb36e02dcfba29280)
buildah run --network=host -v "$PWD":/src --workingdir /src "$ctr" -- bash -c \
  'apt-get update -qq && apt-get install -y -qq python3 g++ build-essential libsqlite3-dev &&
   YARN_PLUGINS=/src/yarn-plugins/conditional-checksums.cjs yarn install --immutable && yarn tsc && yarn build:backend'
buildah rm "$ctr"
# 2. build and push the image
buildah bud --layers --network=host -f packages/backend/Dockerfile \
  -t ghcr.io/peopleforrester/watch-it-burn:backstage-<version>-node<node> .
buildah push --digestfile ../../tmp/backstage.digest \
  ghcr.io/peopleforrester/watch-it-burn:backstage-<version>-node<node>
```

Then:

1. Put `<tag>@<digest>` in `backstage/k8s/backstage.yaml` and a row for it in `images.lock`. The tag alone is
   never enough (`verify/test_image_pins.py`).
2. `verify/sign-images.sh` signs that digest under the workshop key (cosign 2.x). An unsigned image of ours is
   denied admission in every namespace (`policies/kyverno/verify-image-signatures.yaml`).

The base image is pinned on purpose; see the header of `packages/backend/Dockerfile`. Both steps pull it from
lab-platform's ghcr.io copy, by digest, never from Docker Hub (#714).

## Dependency pins

`package.json` `resolutions` hold transitive packages at a patched version where the Backstage packages still
ask for a vulnerable range. Two came from Dependabot alerts:

- `@azure/msal-node` 7.1.2 (GHSA-xcx6-jx8p-x3h5, fixed in 7.1.0), with `@azure/identity` 4.14.0. Backstage
  pulls `@azure/identity` ^4, whose 4.13 line asks for msal-node ^5.
- `node-forge` 1.4.2 (GHSA-86w9-cpqp-85rv, CVE-2026-85393, fixed in 1.4.1 per forge's changelog).

`.yarnrc.yml` refuses a release younger than three days (`npmMinimalAgeGate`), so a fix newer than that waits.

## Hash pins Yarn does not keep

`yarn.lock` records a checksum for every package except the platform-conditional ones, the native binaries such as
`@esbuild/linux-x64` that carry a `conditions:` line: Yarn 4 neither writes nor checks one for those (#1167).
`yarn-plugins/conditional-checksums.lock` records each one's cache checksum, and
`yarn-plugins/conditional-checksums.cjs`, loaded through `YARN_PLUGINS` (`verify/run-e2e.sh`, the Dockerfile and
step 1 above set it), fails an install whose zip for one of them differs, before anything is linked. After a change
to `yarn.lock`, rewrite the lock with `python3 verify/yarn_pins.py write` (it needs the network: each tarball is
checked against npm's `dist.integrity` and then zipped by the committed yarn).

`package.json`'s `packageManager` carries the SHA-512 of the yarn release corepack downloads, which is
`.yarn/releases/yarn-4.13.0.cjs` byte for byte, so corepack refuses a download that differs. On a version change,
put the new release's `sha512sum` there.

## Local development

```sh
yarn install
yarn start
```
