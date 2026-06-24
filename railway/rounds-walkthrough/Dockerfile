# ABOUTME: Serves the self-contained reveal.js Rounds & Challenges deck as a static site.
# ABOUTME: reveal.js loads from a CDN, so nginx only serves index.html. For Michael + Whitney alignment.
FROM nginx:1.27-alpine
COPY index.html /usr/share/nginx/html/index.html
COPY README.md /usr/share/nginx/html/README.md
EXPOSE 80
