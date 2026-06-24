# ABOUTME: Serves the self-contained reveal.js Rounds & Challenges deck as a static site on Railway.
# ABOUTME: nginx binds to Railway's $PORT via the envsubst template (default 8080); reveal.js loads from CDN.
FROM nginx:1.27-alpine
ENV PORT=8080
COPY default.conf.template /etc/nginx/templates/default.conf.template
COPY index.html /usr/share/nginx/html/index.html
COPY README.md /usr/share/nginx/html/README.md
EXPOSE 8080
