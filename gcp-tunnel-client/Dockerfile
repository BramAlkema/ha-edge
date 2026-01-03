# Home Assistant Edge - Add-on Client
# Stateless edge companion: voice control, remote access, smart caching

ARG BUILD_FROM
FROM ${BUILD_FROM}

# Chisel version - pin for reproducibility
ARG CHISEL_VERSION=1.9.1

# Target architecture (set by HA build system)
ARG TARGETARCH
ARG TARGETVARIANT

# Install dependencies
RUN apk add --no-cache \
        curl \
        ca-certificates \
        jq \
        nginx \
        python3 \
        py3-pip \
    && pip3 install --no-cache-dir --break-system-packages \
        flask \
        requests \
        google-auth \
        gunicorn \
    && case "${TARGETARCH}${TARGETVARIANT}" in \
        "amd64") CHISEL_ARCH="amd64" ;; \
        "arm64") CHISEL_ARCH="arm64" ;; \
        "armv7") CHISEL_ARCH="armv7" ;; \
        "armv6") CHISEL_ARCH="armv6" ;; \
        "arm"*) CHISEL_ARCH="armv7" ;; \
        *) echo "Unsupported arch: ${TARGETARCH}${TARGETVARIANT}" && exit 1 ;; \
    esac \
    && CHISEL_URL="https://github.com/jpillora/chisel/releases/download/v${CHISEL_VERSION}/chisel_${CHISEL_VERSION}_linux_${CHISEL_ARCH}.gz" \
    && echo "Downloading chisel from: ${CHISEL_URL}" \
    && curl -fsSL "${CHISEL_URL}" -o /tmp/chisel.gz \
    && gunzip /tmp/chisel.gz \
    && mv /tmp/chisel /usr/local/bin/chisel \
    && chmod +x /usr/local/bin/chisel \
    && /usr/local/bin/chisel --version \
    && rm -rf /tmp/*

# Copy files
COPY run.sh /run.sh
COPY nginx.conf /etc/nginx/nginx.conf
COPY webapp /webapp
RUN chmod +x /run.sh && mkdir -p /tmp/nginx-client-body /data

# Health check - verify chisel binary exists and is executable
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD pgrep -x chisel || exit 1

# Run as non-root (HA add-ons run as root by default, but good practice)
# Note: Commented out as bashio requires root for some operations
# USER 1000

# Labels for HA
LABEL \
    io.hass.name="Home Assistant Edge" \
    io.hass.description="Stateless edge companion for voice control and remote access" \
    io.hass.type="addon" \
    io.hass.version="${CHISEL_VERSION}"

CMD ["/run.sh"]
