# ABOUTME: Minimal static sample workload for Watch It Burn (Backstage catalog + templated-test-svc).
# ABOUTME: Tiny nginx serving a branded page; a harmless burn target, no app logic.
# Our ghcr.io copy, by digest, not Docker Hub's nginx:1.27-alpine (#714).
FROM ghcr.io/peopleforrester/watch-it-burn:nginx-1.27-alpine@sha256:65e3e85dbaed8ba248841d9d58a899b6197106c23cb0ff1a132b7bfe0547e4c0
COPY index.html /usr/share/nginx/html/index.html
EXPOSE 80
