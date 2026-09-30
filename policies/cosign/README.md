# Image signing for this workshop

Every image we publish to `ghcr.io/peopleforrester/watch-it-burn` is signed with cosign, and
`policies/kyverno/verify-image-signatures.yaml` requires a valid signature at admission.

## The public key

`watch-it-burn.pub` is the verification key. It is public by design and is embedded verbatim in the
Kyverno policy, so the two must not drift; `verify/test_image_signing.py` fails if they do.

## The private key

`~/secrets/cosign/watch-it-burn.key` plus `watch-it-burn.pw`, in the mrf-secrets key store. It is never
in this repo. Losing it costs a re-key and a re-sign of every tag, which is an afternoon, so it is not
a disaster; leaking it would let someone sign an image this fleet then admits, which is.

## Why a key rather than keyless

Keyless attestation binds a signature to a CI identity, which is the better model when CI does the
building. Six of the eight images here are built by hand on netcup, so a keyless subject would have to
name an identity that does not sign them.

The second reason is the load-bearing one. **Challenge 1 has attendees apply a default-deny egress
NetworkPolicy**, so anything Kyverno needs to reach at admission time after that point is a control
that stops working halfway through the workshop. Key-based verification needs only the registry, and
the signature bundles carry an offline transparency-log inclusion proof, so verification holds with no
Sigstore access at all. Verified: `cosign verify --insecure-ignore-tlog` passes on all eight.

Signatures ARE uploaded to the public Rekor log, because these are public images and a public audit
trail is worth having. The policy sets `rekor.ignoreTlog: true` so admission does not depend on it.

## cosign 3.x signatures do not verify under Kyverno

**Sign with cosign 2.x.** Measured 2026-09-30:

| | Result |
|---|---|
| cosign 3.1.3 signs, `cosign verify` checks | passes |
| the same signature, Kyverno 1.19.1 | **`no signatures found`** |
| cosign 2.6.5 signs, Kyverno 1.19.1 | passes |

cosign 3.x writes the new Sigstore bundle unconditionally: the signature lands on a
`sha256-<digest>` tag with no suffix, and v3 has no `--new-bundle-format` flag left to opt out of it.
Kyverno 1.19.1 looks for the legacy `sha256-<digest>.sig` tag. So a v3 signature verifies perfectly on
a laptop and is invisible at admission, which is the worst shape a security control can take.

The first reading of this came from Kyverno CLI 1.17.1 and was not trusted, because the cluster runs
1.19.1; the matching CLI was downloaded and gave the same answer, which is what made it a finding
rather than an instrument artifact.

`verify/sign-images.sh` refuses to run under cosign 3.x rather than producing signatures that look
fine and fail in the cluster. Revisit when Kyverno reads the new format.

## Signing a new or rebuilt image

```bash
export COSIGN_PASSWORD="$(cat ~/secrets/cosign/watch-it-burn.pw)"
# Sign the DIGEST, never the tag: a tag is a moving pointer and the signature belongs to the artifact.
cosign sign --key ~/secrets/cosign/watch-it-burn.key --yes \
  ghcr.io/peopleforrester/watch-it-burn@sha256:<digest>
cosign verify --key policies/cosign/watch-it-burn.pub --insecure-ignore-tlog \
  ghcr.io/peopleforrester/watch-it-burn@sha256:<digest>
```

`verify/sign-images.sh` does both for every tag the manifests reference, and is the thing to run after
any image build.

**An unsigned image is now denied at admission.** Sign before you deploy, not after the pod fails.
