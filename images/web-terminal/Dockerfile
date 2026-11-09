# ABOUTME: Browser workbench image for the attendee VTT: a shell (ttyd), a browser IDE (code-server) and
# ABOUTME: a notebook (JupyterLab), all sharing /home/student. Runs as the scoped `student` user.
# The base is lab-platform's ghcr.io copy of Docker Hub's debian:bookworm-slim (lab-platform#353), the linux/amd64
# image Docker Hub's index sha256:99c0b25c... served on 2026-11-02, pinned by digest: nothing here is pulled from
# Docker Hub (#714). The copy is amd64 only, which is what the nodes run and what the workflow builds.
FROM ghcr.io/peopleforrester/lab-platform/mirror/library/debian:bookworm-slim-a3bba7dc7dbc@sha256:a3bba7dc7dbcc1f37c2856c51fc9a7fac96608f50cb87b1b4e4d8b8c85ae988e

# Every fetch below names a version and a sha256 and fails the build on a mismatch, so a rebuild with nothing in the
# repo changed ships the same bytes (#1273). Before it, helm came from its get-helm-3 script on main, eksctl, k9s and
# yq from their latest release, the AWS CLI from a URL that names no version, Node from NodeSource's setup script and
# pip and five notebook packages from PyPI as it stood that day. To bump one, change its version and its sha256
# together, each read from the publisher's own checksum file; the AWS CLI publishes none, so its sha256 is taken from a
# download whose PGP signature checked against the AWS CLI Team key, FB5D B77F D5C1 18B8 0511 ADA8 A631 0ACC 4672 475C.
#
# Debian packages come from snapshot.debian.org at the time the base image was built from (its debian.sources names
# 20261027T000000Z), not from the live archive: the snapshot fixes each package's version, and apt checks every .deb
# against the sha256 in the snapshot's Packages index, which the base image's Debian archive keyring signs. The
# snapshot's Release files are past their Valid-Until, which is what a fixed point in time means, so apt is told not
# to check it. glibc base so AWS CLI v2 installs cleanly (it is not built for musl). xz-utils unpacks Node's tarball.
ARG DEBIAN_SNAPSHOT=20261027T000000Z
RUN set -eux; \
    rm -f /etc/apt/sources.list; \
    printf '%s\n' \
      'Types: deb' \
      "URIs: http://snapshot.debian.org/archive/debian/${DEBIAN_SNAPSHOT}" \
      'Suites: bookworm bookworm-updates' \
      'Components: main' \
      'Signed-By: /usr/share/keyrings/debian-archive-keyring.gpg' \
      '' \
      'Types: deb' \
      "URIs: http://snapshot.debian.org/archive/debian-security/${DEBIAN_SNAPSHOT}" \
      'Suites: bookworm-security' \
      'Components: main' \
      'Signed-By: /usr/share/keyrings/debian-archive-keyring.gpg' \
      > /etc/apt/sources.list.d/debian.sources; \
    apt-get -o Acquire::Check-Valid-Until=false -o Acquire::Retries=3 update; \
    apt-get -o Acquire::Retries=3 install -y --no-install-recommends \
      ca-certificates curl wget unzip git jq less vim-tiny gnupg bash procps xz-utils \
      python3 python3-venv python3-pip; \
    rm -rf /var/lib/apt/lists/*

# ttyd (static binary), kubectl, AWS CLI v2, helm, eksctl, k9s, yq. linux/amd64 only: the pinned base above is the
# amd64 image the t3.2xlarge nodes run and the workflow builds, and each sha256 is the amd64 artifact's.
#
# kubectl is pinned to an EXACT version, not resolved from stable-1.35.txt at build time. A floating
# pin means the rehearsal build and the delivery build can ship different binaries with nothing to
# indicate it changed, which is the one class of surprise a live workshop cannot absorb. Bump this
# deliberately, keeping it within one minor of the cluster (var.kubernetes_version).
# Resolved from https://dl.k8s.io/release/stable-1.35.txt on 2026-08-26; its sha256 is the release's kubectl.sha256.
# ttyd's sha256 is its release's SHA256SUMS line for ttyd.x86_64, the same pin verify/e2e-tools.lock holds.
# helm stays on 3.x, the line get-helm-3 installed; helm, eksctl, k9s, yq and the AWS CLI are their latest
# releases on 2026-11-09, each sha256 checked against the release's checksum file (helm's .sha256sum,
# eksctl_checksums.txt, k9s's checksums.sha256, yq's checksums-bsd) that day.
ARG TTYD_SHA256=8a217c968aba172e0dbf3f34447218dc015bc4d5e59bf51db2f2cd12b7be4f55
ARG KUBECTL_VERSION=v1.35.8
ARG KUBECTL_SHA256=874d5e72dbb819f43cff16bcd1e4f8bac5b7f2361fe1e55049b0a6c676fb0cbf
ARG AWSCLI_VERSION=2.39.6
ARG AWSCLI_SHA256=7a121264f2637a3b90767aaf5bdd43ee88b8c925a931d0479fa2ce22b1a2fa76
ARG HELM_VERSION=v3.22.1
ARG HELM_SHA256=896cf63684a42a723d61c980369d6e588330927deb13676ca0d85006dd6da0ea
ARG EKSCTL_VERSION=v0.231.0
ARG EKSCTL_SHA256=13cd1c4ae6ad3f74ea27aa1117c72e34ffa4ca8ff6d709261f7b1d7f411dc435
ARG K9S_VERSION=v0.51.0
ARG K9S_SHA256=c3752ad51a5a4015a113819c4eeb6e55a4d0e4b8e652494797532f6fc8161dd7
ARG YQ_VERSION=v4.54.3
ARG YQ_SHA256=129534601871538efe0ba4c5e62a34fb1d5f469bcb975c4fddeb467d82974973
RUN set -eux; \
    arch="$(dpkg --print-architecture)"; \
    [ "$arch" = amd64 ] || { echo "the pinned sha256s are linux/amd64's; this build is $arch" >&2; exit 1; }; \
    d="$(mktemp -d)"; \
    curl -fsSL -o "$d/ttyd" "https://github.com/tsl0922/ttyd/releases/download/1.7.7/ttyd.x86_64"; \
    echo "${TTYD_SHA256}  $d/ttyd" | sha256sum -c -; \
    install -m 0755 "$d/ttyd" /usr/local/bin/ttyd; \
    curl -fsSL -o "$d/kubectl" "https://dl.k8s.io/release/${KUBECTL_VERSION}/bin/linux/amd64/kubectl"; \
    echo "${KUBECTL_SHA256}  $d/kubectl" | sha256sum -c -; \
    install -m 0755 "$d/kubectl" /usr/local/bin/kubectl; \
    curl -fsSL -o "$d/awscli.zip" "https://awscli.amazonaws.com/awscli-exe-linux-x86_64-${AWSCLI_VERSION}.zip"; \
    echo "${AWSCLI_SHA256}  $d/awscli.zip" | sha256sum -c -; \
    unzip -q "$d/awscli.zip" -d "$d"; "$d/aws/install"; \
    curl -fsSL -o "$d/helm.tgz" "https://get.helm.sh/helm-${HELM_VERSION}-linux-amd64.tar.gz"; \
    echo "${HELM_SHA256}  $d/helm.tgz" | sha256sum -c -; \
    tar -xzf "$d/helm.tgz" -C "$d" linux-amd64/helm; \
    install -m 0755 "$d/linux-amd64/helm" /usr/local/bin/helm; \
    curl -fsSL -o "$d/eksctl.tgz" "https://github.com/eksctl-io/eksctl/releases/download/${EKSCTL_VERSION}/eksctl_Linux_amd64.tar.gz"; \
    echo "${EKSCTL_SHA256}  $d/eksctl.tgz" | sha256sum -c -; \
    tar -xzf "$d/eksctl.tgz" -C /usr/local/bin eksctl; \
    curl -fsSL -o "$d/k9s.tgz" "https://github.com/derailed/k9s/releases/download/${K9S_VERSION}/k9s_Linux_amd64.tar.gz"; \
    echo "${K9S_SHA256}  $d/k9s.tgz" | sha256sum -c -; \
    tar -xzf "$d/k9s.tgz" -C /usr/local/bin k9s; \
    curl -fsSL -o "$d/yq" "https://github.com/mikefarah/yq/releases/download/${YQ_VERSION}/yq_linux_amd64"; \
    echo "${YQ_SHA256}  $d/yq" | sha256sum -c -; \
    install -m 0755 "$d/yq" /usr/local/bin/yq; \
    rm -rf "$d"; \
    kubectl version --client; aws --version; helm version --short; eksctl version; k9s version --short; yq --version

# --- Browser IDE and notebook -------------------------------------------------------------------
#
# Why these run as processes in ONE container rather than as separate containers: all three surfaces
# have to see the SAME working tree. A file the agent writes in the shell must appear in the IDE and
# the notebook immediately, and that shared tree is the entire point of the workbench. Everything binds
# to loopback; only nginx is exposed.
#
# VERSIONS VERIFIED 2026-08-24 against the live sources, NOT carried over from the sister repo, and one
# of them had already gone stale:
#
#   code-server 4.133.0        (github.com/coder/code-server latest, published 2026-08-17)
#   JupyterLab  4.6.3          (PyPI latest)
#   jupyter-collaboration 5.0.1
#
# The Packt lineage pinned JupyterLab to 4.5 on the grounds that 4.6 shipped @jupyter/ydoc 4.x while
# jupyter-collaboration required <4. THAT CONSTRAINT HAS INVERTED. jupyter-collaboration 5.0.1 now
# requires jupyterlab>=4.6.0, so pinning 4.5 today resolves collaboration back to 4.4.2 and holds both
# packages a generation behind. Verified by resolving both sets: 4.5.10 forces collaboration 4.4.2;
# 4.6.3 takes 5.0.1 with every extension below resolving cleanly. Re-check before changing either pin.
#
# Node 22 is here for the notebook's JS extensions.
# code-server's sha256 is the digest GitHub's release API gives its linux-amd64 tarball, read 2026-11-09. Node is
# the 22.x release current on 2026-11-09, from nodejs.org with the sha256 its SHASUMS256.txt gives, in place of
# NodeSource's setup_22.x script and the apt repository it added.
ARG CODE_SERVER_VERSION=4.133.0
ARG CODE_SERVER_SHA256=a4e0f8f8c76e7de8e7424289f74e507af4c97bfe104c3e8ee272b8cc7b46c6f1
ARG NODE_VERSION=v22.23.4
ARG NODE_SHA256=1805bcd35e6815559bd2eb97db438d3fdb0eb3a5e6a977b7c1badca76337e9ce
RUN set -eux; \
    d="$(mktemp -d)"; \
    curl -fsSL -o "$d/code-server.tgz" "https://github.com/coder/code-server/releases/download/v${CODE_SERVER_VERSION}/code-server-${CODE_SERVER_VERSION}-linux-amd64.tar.gz"; \
    echo "${CODE_SERVER_SHA256}  $d/code-server.tgz" | sha256sum -c -; \
    tar -xzf "$d/code-server.tgz" -C /opt; \
    mv "/opt/code-server-${CODE_SERVER_VERSION}-linux-amd64" /opt/code-server; \
    ln -s /opt/code-server/bin/code-server /usr/local/bin/code-server; \
    curl -fsSL -o "$d/node.tar.xz" "https://nodejs.org/dist/${NODE_VERSION}/node-${NODE_VERSION}-linux-x64.tar.xz"; \
    echo "${NODE_SHA256}  $d/node.tar.xz" | sha256sum -c -; \
    tar -xJf "$d/node.tar.xz" -C /usr/local --strip-components=1 --no-same-owner \
      "node-${NODE_VERSION}-linux-x64/bin" "node-${NODE_VERSION}-linux-x64/lib" "node-${NODE_VERSION}-linux-x64/include"; \
    rm -rf "$d"; \
    code-server --version; node --version

# Debian bookworm marks its python externally-managed (PEP 668), so the notebook stack lives in its own
# venv rather than fighting the system interpreter. requirements.txt is the whole stack, pip included, each package by
# version and the sha256 of its wheels (requirements.in holds the top-level list and the command that locks it).
# --require-hashes fails on any package the lock does not name, and --only-binary keeps an sdist's build backend from
# being fetched unhashed.
COPY requirements.txt /opt/jupyter-requirements.txt
RUN set -eux; \
    python3 -m venv /opt/jupyter; \
    /opt/jupyter/bin/pip install --no-cache-dir --require-hashes --only-binary :all: -r /opt/jupyter-requirements.txt; \
    /opt/jupyter/bin/jupyter --version

# --- No AI coding CLIs -----------------------------------------------------------------------------
# Whitney, 2026-09-08 review: "coding CLIs, uninstall." claude, gemini, codex, opencode and aider were
# installed for a student to type if they wanted one; they are removed. Nothing in any challenge used
# them (this file said so when they were added), and the workshop's own rule already forbids any surface
# invoking or advertising a coding-agent CLI (#89). Not installing them is the same rule at the image
# layer, and it drops the npm/pip build weight with it. Re-add here, pinned, only if a challenge ever
# needs one.

# --- No workshop tutor -----------------------------------------------------------------------------
#
# This image used to install the Claude Code CLI and a tutor/ directory to run it as an in-workbench
# helper on a second ttyd. Both are gone: clicking that tab showed an attendee the CLI's
# "Trust this folder?" first-run prompt, and suppressing it depends on undocumented per-project keys in
# the CLI's own config, so a release can reintroduce it live. See issue #89.
#
# Removing it also drops a globally-installed npm CLI from an image that runs on a cluster the workshop
# deliberately attacks, which is a smaller attack surface for free.

# The scoped student user. Numeric uid 1000 so the pod securityContext can verify runAsNonRoot.
RUN useradd -m -u 1000 -s /bin/bash student \
 && mkdir -p /home/student/.kube /home/student/.aws /home/student/work \
 && chown -R student:student /home/student

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

USER student
WORKDIR /home/student
# ttyd 7681 (/terminal/), code-server 8443 (/ide/), Jupyter 8888 (/jupyter/). Only nginx is exposed at
# the Service; these are all loopback from the console frontend's point of view.
EXPOSE 7681 8443 8888
ENTRYPOINT ["/entrypoint.sh"]
