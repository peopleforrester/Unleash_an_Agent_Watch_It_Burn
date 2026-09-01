# ABOUTME: Browser workbench image for the attendee VTT: a shell (ttyd), a browser IDE (code-server) and
# ABOUTME: a notebook (JupyterLab), all sharing /home/student. Runs as the scoped `student` user.
FROM debian:bookworm-slim

# Base utilities the lab leans on. glibc base so AWS CLI v2 installs cleanly (it is not built for musl).
RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates curl wget unzip git jq less vim-tiny gnupg bash procps \
 && rm -rf /var/lib/apt/lists/*

# ttyd (static binary), kubectl, AWS CLI v2, helm, eksctl, k9s, yq.
# Arch-aware so the image builds on amd64 (the t3.2xlarge nodes) or arm64.
#
# kubectl is pinned to an EXACT version, not resolved from stable-1.35.txt at build time. A floating
# pin means the rehearsal build and the delivery build can ship different binaries with nothing to
# indicate it changed, which is the one class of surprise a live workshop cannot absorb. Bump this
# deliberately, keeping it within one minor of the cluster (var.kubernetes_version).
# Resolved from https://dl.k8s.io/release/stable-1.35.txt on 2026-08-26.
ARG KUBECTL_VERSION=v1.35.8
RUN set -eux; \
    arch="$(dpkg --print-architecture)"; \
    case "$arch" in \
      amd64) TTYD=x86_64; AWS=x86_64; GOARCH=amd64 ;; \
      arm64) TTYD=aarch64; AWS=aarch64; GOARCH=arm64 ;; \
      *) echo "unsupported arch $arch" >&2; exit 1 ;; \
    esac; \
    curl -fsSL -o /usr/local/bin/ttyd "https://github.com/tsl0922/ttyd/releases/download/1.7.7/ttyd.${TTYD}"; \
    chmod +x /usr/local/bin/ttyd; \
    KVER="${KUBECTL_VERSION}"; \
    curl -fsSL -o /usr/local/bin/kubectl "https://dl.k8s.io/release/${KVER}/bin/linux/${GOARCH}/kubectl"; \
    chmod +x /usr/local/bin/kubectl; \
    curl -fsSL -o /tmp/awscli.zip "https://awscli.amazonaws.com/awscli-exe-linux-${AWS}.zip"; \
    unzip -q /tmp/awscli.zip -d /tmp; /tmp/aws/install; rm -rf /tmp/aws /tmp/awscli.zip; \
    curl -fsSL https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash; \
    curl -fsSL "https://github.com/eksctl-io/eksctl/releases/latest/download/eksctl_Linux_${GOARCH}.tar.gz" \
      | tar -xz -C /usr/local/bin eksctl; \
    curl -fsSL "https://github.com/derailed/k9s/releases/latest/download/k9s_Linux_${GOARCH}.tar.gz" \
      | tar -xz -C /usr/local/bin k9s; \
    curl -fsSL -o /usr/local/bin/yq "https://github.com/mikefarah/yq/releases/latest/download/yq_linux_${GOARCH}"; \
    chmod +x /usr/local/bin/yq; \
    kubectl version --client; aws --version; helm version --short; eksctl version; yq --version

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
ARG CODE_SERVER_VERSION=4.133.0
RUN set -eux; \
    arch="$(dpkg --print-architecture)"; \
    curl -fsSL "https://github.com/coder/code-server/releases/download/v${CODE_SERVER_VERSION}/code-server-${CODE_SERVER_VERSION}-linux-${arch}.tar.gz" \
      | tar -xz -C /opt; \
    mv "/opt/code-server-${CODE_SERVER_VERSION}-linux-${arch}" /opt/code-server; \
    ln -s /opt/code-server/bin/code-server /usr/local/bin/code-server; \
    code-server --version

RUN set -eux; \
    curl -fsSL https://deb.nodesource.com/setup_22.x | bash -; \
    apt-get install -y --no-install-recommends nodejs python3 python3-venv python3-pip; \
    rm -rf /var/lib/apt/lists/*; \
    node --version

# Debian bookworm marks its python externally-managed (PEP 668), so the notebook stack lives in its own
# venv rather than fighting the system interpreter.
RUN set -eux; \
    python3 -m venv /opt/jupyter; \
    /opt/jupyter/bin/pip install --no-cache-dir --upgrade pip; \
    /opt/jupyter/bin/pip install --no-cache-dir \
      "jupyterlab==4.6.3" \
      "jupyter-collaboration==5.0.1" \
      jupyter-resource-usage \
      jupyterlab-git \
      jupyterlab_execute_time \
      ipywidgets \
      boto3; \
    /opt/jupyter/bin/jupyter --version

# --- AI coding CLIs, for the student to invoke themselves ------------------------------------------
#
# Michael, 2026-09-01: "all the binaries that we think someone who wants to use AI in these environments
# might want", installed fresh on every deploy. NO launcher button and NO tab: that is what #89/#99
# removed, because a button that auto-started a CLI put a "Trust this folder?" prompt in front of an
# attendee who never asked for one and stranded them. A binary on PATH that a student chooses to type is
# the opposite: invisible until wanted, and the lab already offers extra terminals via the "+" tab.
#
# @latest ON PURPOSE, which is the exact opposite of the mcp pin above, so the difference matters:
# the MCP servers are LOAD-BEARING (a bad version CrashLoops the agent and the workshop stops), and they
# were being resolved at RUNTIME, so a bad publish broke a cluster that had passed every gate. These CLIs
# are optional student tools resolved at BUILD time. Nothing in any challenge depends on them, so a
# regression costs a student one tool rather than costing the room the workshop. If one of them ever does
# become load-bearing, pin it.
#
# Versions at the time of writing (2026-09-01): claude-code 2.1.257, gemini-cli 0.57.0, codex 0.152.0,
# opencode-ai 1.18.25, aider-chat 0.86.2. Each rebuild takes whatever is current.
RUN set -eux; \
    npm install -g --no-fund --no-audit \
      @anthropic-ai/claude-code@latest \
      @google/gemini-cli@latest \
      @openai/codex@latest \
      opencode-ai@latest; \
    npm cache clean --force; \
    claude --version || true; gemini --version || true; codex --version || true; opencode --version || true

# aider is Python, and gets its OWN venv rather than sharing the notebook's: a dependency conflict between
# aider and JupyterLab would otherwise break the notebook, which IS part of the lab.
RUN set -eux; \
    python3 -m venv /opt/aider; \
    /opt/aider/bin/pip install --no-cache-dir --upgrade pip; \
    /opt/aider/bin/pip install --no-cache-dir aider-chat; \
    ln -s /opt/aider/bin/aider /usr/local/bin/aider; \
    aider --version || true

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
