#!/usr/bin/with-contenv bashio
#
# GCP Tunnel Client - connects to Cloud Run chisel server
#
# Features:
# - Exponential backoff on reconnect
# - Graceful shutdown handling
# - Connection monitoring
#

# Exit on undefined variables
set -u

# Configuration
MAX_BACKOFF=300  # 5 minutes max
INITIAL_BACKOFF=5
BACKOFF_MULTIPLIER=2

# State
current_backoff=$INITIAL_BACKOFF
consecutive_failures=0
chisel_pid=""

# Graceful shutdown handler
shutdown() {
    bashio::log.info "Received shutdown signal, stopping tunnel..."
    if [ -n "$chisel_pid" ] && kill -0 "$chisel_pid" 2>/dev/null; then
        kill -TERM "$chisel_pid" 2>/dev/null || true
        wait "$chisel_pid" 2>/dev/null || true
    fi
    bashio::log.info "Tunnel stopped"
    exit 0
}

# Set up signal handlers
trap shutdown SIGTERM SIGINT SIGHUP

# Validate URL format
validate_url() {
    local url="$1"
    if [[ ! "$url" =~ ^https?:// ]] && [[ ! "$url" =~ ^wss?:// ]]; then
        bashio::log.fatal "Invalid server URL format: $url"
        bashio::log.fatal "URL must start with https:// or wss://"
        exit 1
    fi
}

# Read and validate configuration
read_config() {
    SERVER_URL=$(bashio::config 'server_url')
    AUTH_USER=$(bashio::config 'auth_user')
    AUTH_PASS=$(bashio::config 'auth_pass')
    LOCAL_PORT=$(bashio::config 'local_port')
    KEEPALIVE=$(bashio::config 'keepalive')
    LOG_LEVEL=$(bashio::config 'log_level')

    # Validate required config
    if bashio::var.is_empty "$SERVER_URL"; then
        bashio::log.fatal "Configuration error: server_url is required"
        exit 1
    fi

    if bashio::var.is_empty "$AUTH_PASS"; then
        bashio::log.fatal "Configuration error: auth_pass is required"
        exit 1
    fi

    # Validate URL
    validate_url "$SERVER_URL"

    # Use the URL as-is - chisel handles https->wss conversion internally
    TUNNEL_URL="$SERVER_URL"

    # Set defaults
    AUTH_USER="${AUTH_USER:-hauser}"
    LOCAL_PORT="${LOCAL_PORT:-8123}"
    KEEPALIVE="${KEEPALIVE:-25s}"
    LOG_LEVEL="${LOG_LEVEL:-info}"
}

# Build chisel command arguments
build_chisel_args() {
    CHISEL_ARGS=(
        "client"
        "--keepalive" "$KEEPALIVE"
    )

    # Add auth (mask password in logs by building args array)
    CHISEL_ARGS+=("--auth" "${AUTH_USER}:${AUTH_PASS}")

    # Set verbosity based on log level
    case "$LOG_LEVEL" in
        debug)
            CHISEL_ARGS+=("-v")
            ;;
        info|warning|error)
            # Default verbosity
            ;;
    esac

    # Add server URL
    CHISEL_ARGS+=("$TUNNEL_URL")

    # Add reverse tunnel specification
    # nginx on Cloud Run listens on :8080, proxies HTTP to :9001
    # chisel listens on :9000 for WebSocket control
    # Format: R:remote_port:local_host:local_port
    # Reverse tunnel: server listens on 9001, forwards to client's 127.0.0.1:LOCAL_PORT
    # Use 127.0.0.1 explicitly (not localhost) to avoid IPv6 resolution issues
    CHISEL_ARGS+=("R:9001:127.0.0.1:${LOCAL_PORT}")
}

# Calculate backoff with jitter
calculate_backoff() {
    # Exponential backoff
    current_backoff=$((current_backoff * BACKOFF_MULTIPLIER))

    # Cap at max
    if [ "$current_backoff" -gt "$MAX_BACKOFF" ]; then
        current_backoff=$MAX_BACKOFF
    fi

    # Add jitter (±20%)
    local jitter=$((current_backoff / 5))
    local random_jitter=$((RANDOM % (jitter * 2 + 1) - jitter))
    local backoff_with_jitter=$((current_backoff + random_jitter))

    # Ensure minimum of 1 second
    if [ "$backoff_with_jitter" -lt 1 ]; then
        backoff_with_jitter=1
    fi

    echo "$backoff_with_jitter"
}

# Reset backoff on successful connection
reset_backoff() {
    current_backoff=$INITIAL_BACKOFF
    consecutive_failures=0
}

# Run chisel and monitor
run_tunnel() {
    bashio::log.info "Starting chisel client..."

    # Log connection details (without password)
    bashio::log.info "Server: $TUNNEL_URL"
    bashio::log.info "User: $AUTH_USER"
    bashio::log.info "Local port: $LOCAL_PORT"
    bashio::log.info "Keepalive: $KEEPALIVE"
    bashio::log.info "Tunnel: R:9001:127.0.0.1:${LOCAL_PORT}"

    # Start chisel in background
    /usr/local/bin/chisel "${CHISEL_ARGS[@]}" &
    chisel_pid=$!

    bashio::log.info "Chisel started with PID: $chisel_pid"

    # Wait for process
    wait "$chisel_pid"
    local exit_code=$?

    chisel_pid=""
    return $exit_code
}

# Main loop
main() {
    bashio::log.info "========================================"
    bashio::log.info "GCP Tunnel Client starting"
    bashio::log.info "========================================"

    # Verify chisel binary
    if ! command -v /usr/local/bin/chisel &>/dev/null; then
        bashio::log.fatal "Chisel binary not found at /usr/local/bin/chisel"
        exit 1
    fi

    local chisel_version
    chisel_version=$(/usr/local/bin/chisel --version 2>&1 || echo "unknown")
    bashio::log.info "Chisel version: $chisel_version"

    # Read configuration
    read_config
    build_chisel_args

    # Main reconnect loop
    while true; do
        bashio::log.info "Connecting to tunnel..."

        # Track connection start time
        local start_time
        start_time=$(date +%s)

        # Run tunnel (blocks until disconnect)
        if run_tunnel; then
            # Clean exit (shouldn't happen normally)
            bashio::log.warning "Tunnel exited cleanly"
        else
            local exit_code=$?
            bashio::log.warning "Tunnel disconnected (exit code: $exit_code)"
        fi

        # Calculate connection duration
        local end_time
        end_time=$(date +%s)
        local duration=$((end_time - start_time))

        # If connection lasted more than 60 seconds, reset backoff
        if [ "$duration" -gt 60 ]; then
            bashio::log.info "Connection was stable for ${duration}s, resetting backoff"
            reset_backoff
        else
            ((consecutive_failures++))
            bashio::log.warning "Quick disconnect (${duration}s), failure #${consecutive_failures}"
        fi

        # Calculate wait time
        local wait_time
        wait_time=$(calculate_backoff)

        bashio::log.info "Reconnecting in ${wait_time}s..."

        # Interruptible sleep
        local waited=0
        while [ "$waited" -lt "$wait_time" ]; do
            sleep 1
            ((waited++))
        done
    done
}

# Run main
main "$@"
