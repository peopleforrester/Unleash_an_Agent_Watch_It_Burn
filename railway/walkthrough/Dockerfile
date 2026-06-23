# ABOUTME: Serves the self-contained reveal.js walkthrough as a static site (walkthrough.agenticburn.com).
# ABOUTME: The deck loads reveal.js + mermaid from a CDN, so nginx only needs to serve index.html.
FROM nginx:1.27-alpine
COPY index.html /usr/share/nginx/html/index.html
COPY README.md /usr/share/nginx/html/README.md
EXPOSE 80
