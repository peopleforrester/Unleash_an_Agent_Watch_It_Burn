# ABOUTME: Builds the agenticburn.com apex landing + wildcard router image (Caddy serving HTTP on $PORT).
# ABOUTME: Railway terminates TLS at the edge; Caddy reverse-proxies by Host from routes.map.
FROM caddy:2-alpine

COPY Caddyfile /etc/caddy/Caddyfile
COPY routes.map /etc/caddy/routes.map
COPY site /srv/site

# Railway injects $PORT; the Caddyfile listens on it (default 8080 locally).
CMD ["caddy", "run", "--config", "/etc/caddy/Caddyfile", "--adapter", "caddyfile"]
