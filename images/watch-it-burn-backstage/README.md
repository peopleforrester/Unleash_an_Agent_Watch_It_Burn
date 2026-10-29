# watch-it-burn-backstage

The Backstage image the clusters run (`ghcr.io/peopleforrester/watch-it-burn:backstage`). A scaffolded
Backstage app on the new frontend system; its frontend already carries the Kubernetes, catalog-graph,
org and api-docs plugins, and its backend the Kubernetes plugin. Everything cluster-specific (the catalog,
guest sign-in, the cluster in the Kubernetes tab, Postgres) comes from `backstage/` at the repo root, not
from this image.

## Rebuild, sign and pin

Node 24 and the repo's `.yarnrc.yml`, from this directory:

```bash
yarn install --immutable
yarn tsc
yarn build:backend
docker build . -f packages/backend/Dockerfile -t ghcr.io/peopleforrester/watch-it-burn:backstage
docker push ghcr.io/peopleforrester/watch-it-burn:backstage
```

Then sign it and pin the new digest:

1. `verify/sign-images.sh` signs the digest the `backstage` tag now points at. An unsigned image of ours
   is denied admission in every namespace (`policies/kyverno/verify-image-signatures.yaml`).
2. Put that digest in `backstage/k8s/backstage.yaml`. The tag alone is never enough
   (`verify/test_image_pins.py`).

The base image is pinned on purpose; see the header of `packages/backend/Dockerfile`.

## Local development

```sh
yarn install
yarn start
```
