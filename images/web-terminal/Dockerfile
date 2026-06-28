# ABOUTME: Browser web-terminal (ttyd) image for the attendee VTT. Glibc base (AWS CLI v2 has no musl
# ABOUTME: build), full cluster/AWS toolset, runs as the scoped `student` user in /home/student.
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

# The scoped student user. Numeric uid 1000 so the pod securityContext can verify runAsNonRoot.
RUN useradd -m -u 1000 -s /bin/bash student \
 && mkdir -p /home/student/.kube /home/student/.aws \
 && chown -R student:student /home/student

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

USER student
WORKDIR /home/student
# ttyd listens on 7681; the console frontend proxies /terminal/ to it.
EXPOSE 7681
ENTRYPOINT ["/entrypoint.sh"]
