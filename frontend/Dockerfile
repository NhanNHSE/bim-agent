FROM nginx:alpine

LABEL maintainer="BIM AI Team"
LABEL description="BIM AI Agent Frontend — Nginx static server"

# Nginx config
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Static files only
COPY index.html /usr/share/nginx/html/
COPY css/ /usr/share/nginx/html/css/
COPY js/ /usr/share/nginx/html/js/

# Health check — 127.0.0.1, not localhost: busybox wget resolves localhost to ::1,
# and nginx.conf only listens on IPv4 (container was reported unhealthy)
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD wget -qO- http://127.0.0.1:80/ || exit 1

EXPOSE 80
