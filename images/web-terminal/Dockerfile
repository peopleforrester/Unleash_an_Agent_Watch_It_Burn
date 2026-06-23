# ABOUTME: Browser web-terminal (ttyd) image for the attendee console, with kubectl auto-authed to the
# ABOUTME: pod's in-cluster ServiceAccount so the shell opens already pointed at the attendee's cluster.
FROM alpine:3.20

# ttyd (browser terminal over websocket) + bash + kubectl pinned to the cluster's minor (1.35).
RUN apk add --no-cache ttyd bash curl ca-certificates jq \
 && case "$(uname -m)" in x86_64) K=amd64 ;; aarch64) K=arm64 ;; *) K=amd64 ;; esac \
 && VER="$(curl -fsSL https://dl.k8s.io/release/stable-1.35.txt)" \
 && curl -fsSL -o /usr/local/bin/kubectl "https://dl.k8s.io/release/${VER}/bin/linux/${K}/kubectl" \
 && chmod +x /usr/local/bin/kubectl

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh \
 && adduser -D -h /home/term term && mkdir -p /home/term/.kube && chown -R term:term /home/term

USER term
# ttyd listens on 7681; the console frontend proxies /terminal/ to it.
EXPOSE 7681
ENTRYPOINT ["/entrypoint.sh"]
