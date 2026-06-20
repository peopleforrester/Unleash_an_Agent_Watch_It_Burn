# ABOUTME: The Beat-2 "villain app" image. A tiny nginx serving a page named after the attendee's villain,
# ABOUTME: so each person can tell their own deployed app apart. Pushed to a PUBLIC registry on purpose.
#
# It is deliberately published to docker.io/<user>/villain-* (a public user namespace), which the
# Cluster-2 registry allowlist (policies/kyverno/restrict-image-registries.yaml) does NOT permit, so
# Cluster 1 (no policy) pulls and runs it and Cluster 2 refuses it at admission.
FROM nginx:1.27-alpine
ARG VILLAIN=Villain
ENV VILLAIN=${VILLAIN}
RUN printf '<!doctype html><html><head><title>%s</title>\n' "$VILLAIN" > /usr/share/nginx/html/index.html \
 && printf '<style>body{background:#1a0d1a;color:#ff5577;font-family:system-ui;text-align:center;padding-top:18vh}h1{font-size:8vw}</style>\n' >> /usr/share/nginx/html/index.html \
 && printf '</head><body><h1>%s</h1><p>this app should never have been deployed</p></body></html>\n' "$VILLAIN" >> /usr/share/nginx/html/index.html
EXPOSE 80
