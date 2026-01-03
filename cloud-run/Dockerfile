# Home Assistant Edge - Cloud Run Server
# Stateless edge companion: voice control, remote access, smart caching
# nginx on 8080 splits: WebSocket → chisel, HTTP → edge proxy → tunnel

FROM alpine:3.18

# Install dependencies
RUN apk add --no-cache nginx supervisor curl python3 py3-pip \
    && pip3 install --no-cache-dir --break-system-packages \
        flask \
        requests \
        gunicorn

# Download chisel
ARG CHISEL_VERSION=1.9.1
RUN curl -fsSL "https://github.com/jpillora/chisel/releases/download/v${CHISEL_VERSION}/chisel_${CHISEL_VERSION}_linux_amd64.gz" \
    -o /tmp/chisel.gz \
    && gunzip /tmp/chisel.gz \
    && chmod +x /tmp/chisel \
    && mv /tmp/chisel /usr/local/bin/chisel

# nginx config: route WebSocket to chisel, HTTP to edge proxy
RUN mkdir -p /run/nginx /var/www/static
COPY nginx.conf /etc/nginx/nginx.conf
COPY static/ /var/www/static/

# Edge proxy for smart caching and fallback
COPY edge_proxy.py /edge_proxy.py

# Supervisor config to run nginx, chisel, and edge proxy
COPY supervisord.conf /etc/supervisord.conf

# Startup script that sets auth from environment
COPY start.sh /start.sh
RUN chmod +x /start.sh

EXPOSE 8080

CMD ["/start.sh"]
