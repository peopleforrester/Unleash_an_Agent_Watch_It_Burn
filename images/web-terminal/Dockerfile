# ABOUTME: Browser workbench image for the attendee VTT: a shell (ttyd), a browser IDE (code-server) and
# ABOUTME: a notebook (JupyterLab), all sharing /home/student. Runs as the scoped `student` user.
FROM debian:bookworm-slim

# Base utilities the lab leans on. glibc base so AWS CLI v2 installs cleanly (it is not built for musl).
RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates curl wget unzip git jq less vim-tiny gnupg bash procps \
 && rm -rf /var/lib/apt/lists/*

# ttyd (static binary), kubectl (pinned to the cluster minor 1.35), AWS CLI v2, helm, eksctl, k9s, yq.
# Arch-aware so the image builds on amd64 (the t3.2xlarge nodes) or arm64.
RUN set -eux; \
    arch="$(dpkg --print-architecture)"; \
    case "$arch" in \
      amd64) TTYD=x86_64; AWS=x86_64; GOARCH=amd64 ;; \
      arm64) TTYD=aarch64; AWS=aarch64; GOARCH=arm64 ;; \
      *) echo "unsupported arch $arch" >&2; exit 1 ;; \
    esac; \
    curl -fsSL -o /usr/local/bin/ttyd "https://github.com/tsl0922/ttyd/releases/download/1.7.7/ttyd.${TTYD}"; \
    chmod +x /usr/local/bin/ttyd; \
    KVER="$(curl -fsSL https://dl.k8s.io/release/stable-1.35.txt)"; \
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
# Node 22 is here for the notebook's JS extensions and for the tutor's ACP bridge (see tutor/).
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

# The scoped student user. Numeric uid 1000 so the pod securityContext can verify runAsNonRoot.
RUN useradd -m -u 1000 -s /bin/bash student \
 && mkdir -p /home/student/.kube /home/student/.aws /home/student/work \
 && chown -R student:student /home/student

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

USER student
WORKDIR /home/student
# ttyd 7681 (/terminal/), code-server 8443 (/ide/), JupyterLab 8888 (/jupyter/). Only nginx is exposed
# at the Service; these are all loopback from the console frontend's point of view.
EXPOSE 7681 8443 8888
ENTRYPOINT ["/entrypoint.sh"]
