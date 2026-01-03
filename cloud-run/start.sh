#!/bin/sh
# Startup script for Cloud Run chisel tunnel server
# Sets up environment and starts supervisor

set -e

# Validate AUTH environment variable
if [ -z "$AUTH" ]; then
    echo "ERROR: AUTH environment variable is required"
    echo "Format: username:password"
    exit 1
fi

# Export for supervisor
export AUTH

echo "=== GCP Tunnel Server Starting ==="
echo "nginx listening on :8080 (external)"
echo "edge proxy on :8081 (internal)"
echo "chisel listening on :9000 (internal)"
echo "reverse tunnel on :9001 (internal)"
echo "Remote UI: controlled via /edge/remote-ui"
echo "=================================="

# Start supervisor (runs nginx + chisel + edge proxy)
exec /usr/bin/supervisord -c /etc/supervisord.conf
