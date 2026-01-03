#!/usr/bin/env python3
"""
GCP Tunnel Edge Proxy

Smart proxy that adds caching, offline fallback, logging, and rate limiting
to the Google Assistant → Home Assistant tunnel.

Features:
- SYNC caching: Cache device list (5 min TTL)
- QUERY caching: Cache device states for offline fallback
- Offline fallback: Return cached state when HA unreachable
- Request logging: JSON audit trail
- Rate limiting: Protect against abuse
- Custom webhooks: POST to external services on events
"""

import os
import sys
import json
import time
import hashlib
import logging
from datetime import datetime
from collections import defaultdict
from functools import wraps
from threading import Lock

import requests
from flask import Flask, request, jsonify, Response

app = Flask(__name__)

# Configuration
UPSTREAM_URL = os.environ.get("UPSTREAM_URL", "http://127.0.0.1:9001")
SYNC_CACHE_TTL = int(os.environ.get("SYNC_CACHE_TTL", 300))  # 5 minutes
QUERY_CACHE_TTL = int(os.environ.get("QUERY_CACHE_TTL", 60))  # 1 minute
RATE_LIMIT_REQUESTS = int(os.environ.get("RATE_LIMIT_REQUESTS", 100))
RATE_LIMIT_WINDOW = int(os.environ.get("RATE_LIMIT_WINDOW", 60))  # 1 minute
WEBHOOK_URL = os.environ.get("WEBHOOK_URL", "")  # Optional external webhook
LOG_REQUESTS = os.environ.get("LOG_REQUESTS", "true").lower() == "true"

# Caches
sync_cache = {}  # {user_id: {response, expires_at}}
query_cache = {}  # {device_id: {state, updated_at}}
cache_lock = Lock()

# Rate limiting
rate_limits = defaultdict(list)  # {ip: [timestamps]}
rate_lock = Lock()

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format='{"ts":"%(asctime)s","level":"%(levelname)s","msg":"%(message)s"}',
    datefmt='%Y-%m-%dT%H:%M:%SZ'
)
logger = logging.getLogger(__name__)


def get_client_ip():
    """Get client IP from headers or connection."""
    return request.headers.get("X-Forwarded-For", request.remote_addr or "unknown").split(",")[0].strip()


def rate_limit(f):
    """Rate limiting decorator."""
    @wraps(f)
    def decorated(*args, **kwargs):
        ip = get_client_ip()
        now = time.time()

        with rate_lock:
            # Clean old entries
            rate_limits[ip] = [t for t in rate_limits[ip] if now - t < RATE_LIMIT_WINDOW]

            # Check limit
            if len(rate_limits[ip]) >= RATE_LIMIT_REQUESTS:
                logger.warning(f"Rate limit exceeded for {ip}")
                return jsonify({"error": "rate_limit_exceeded"}), 429

            # Record request
            rate_limits[ip].append(now)

        return f(*args, **kwargs)
    return decorated


def get_cache_key(data):
    """Generate cache key from request data."""
    return hashlib.md5(json.dumps(data, sort_keys=True).encode()).hexdigest()


def cache_sync_response(user_id, response):
    """Cache a SYNC response."""
    with cache_lock:
        sync_cache[user_id] = {
            "response": response,
            "expires_at": time.time() + SYNC_CACHE_TTL
        }
    logger.info(f"Cached SYNC for user {user_id[:8]}... (TTL: {SYNC_CACHE_TTL}s)")


def get_cached_sync(user_id):
    """Get cached SYNC response if valid."""
    with cache_lock:
        cached = sync_cache.get(user_id)
        if cached and cached["expires_at"] > time.time():
            logger.info(f"SYNC cache hit for user {user_id[:8]}...")
            return cached["response"]
    return None


def cache_query_states(devices):
    """Cache device states from QUERY response."""
    with cache_lock:
        for device_id, state in devices.items():
            query_cache[device_id] = {
                "state": state,
                "updated_at": time.time()
            }
    logger.info(f"Cached states for {len(devices)} devices")


def get_cached_states(device_ids):
    """Get cached states for devices."""
    states = {}
    with cache_lock:
        for device_id in device_ids:
            cached = query_cache.get(device_id)
            if cached:
                # Add flag indicating this is cached data
                state = cached["state"].copy()
                state["_cached"] = True
                state["_cached_at"] = cached["updated_at"]
                states[device_id] = state
    return states


def log_request(intent, request_data, response_data, duration_ms, cached=False, offline=False):
    """Log request details as structured JSON."""
    if not LOG_REQUESTS:
        return

    log_entry = {
        "type": "request",
        "intent": intent,
        "client_ip": get_client_ip(),
        "duration_ms": duration_ms,
        "cached": cached,
        "offline": offline,
        "request_id": request_data.get("requestId", "unknown"),
        "timestamp": datetime.utcnow().isoformat() + "Z"
    }

    # Add device count for SYNC
    if intent == "action.devices.SYNC" and response_data:
        payload = response_data.get("payload", {})
        log_entry["device_count"] = len(payload.get("devices", []))

    # Add device IDs for QUERY/EXECUTE
    if intent in ["action.devices.QUERY", "action.devices.EXECUTE"]:
        inputs = request_data.get("inputs", [{}])
        if inputs:
            payload = inputs[0].get("payload", {})
            devices = payload.get("devices", [])
            if devices:
                log_entry["device_ids"] = [d.get("id") for d in devices[:5]]  # First 5

    print(json.dumps(log_entry), flush=True)


def call_webhook(event_type, data):
    """Call external webhook if configured."""
    if not WEBHOOK_URL:
        return

    try:
        payload = {
            "event": event_type,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "data": data
        }
        requests.post(WEBHOOK_URL, json=payload, timeout=5)
        logger.info(f"Webhook called: {event_type}")
    except Exception as e:
        logger.error(f"Webhook failed: {e}")


def proxy_to_upstream(path, data, headers):
    """Proxy request to upstream (tunnel)."""
    url = f"{UPSTREAM_URL}{path}"

    # Forward relevant headers
    forward_headers = {
        "Content-Type": "application/json",
        "Authorization": headers.get("Authorization", ""),
    }

    try:
        resp = requests.post(url, json=data, headers=forward_headers, timeout=30)
        return resp.json(), resp.status_code, False
    except requests.exceptions.Timeout:
        logger.error("Upstream timeout")
        return None, 504, True
    except requests.exceptions.ConnectionError:
        logger.error("Upstream connection error")
        return None, 502, True
    except Exception as e:
        logger.error(f"Upstream error: {e}")
        return None, 500, True


@app.route("/api/google_assistant", methods=["POST"])
@rate_limit
def google_assistant():
    """Main Google Assistant endpoint with caching and fallback."""
    start_time = time.time()
    data = request.get_json() or {}

    # Parse intent
    inputs = data.get("inputs", [])
    intent = inputs[0].get("intent", "unknown") if inputs else "unknown"
    user_id = data.get("agentUserId", "default")

    # Handle SYNC with caching
    if intent == "action.devices.SYNC":
        # Check cache first
        cached = get_cached_sync(user_id)
        if cached:
            duration_ms = int((time.time() - start_time) * 1000)
            log_request(intent, data, cached, duration_ms, cached=True)
            return jsonify(cached)

        # Forward to upstream
        response, status, is_error = proxy_to_upstream("/api/google_assistant", data, request.headers)

        if not is_error and response:
            cache_sync_response(user_id, response)
            call_webhook("sync", {"user_id": user_id, "device_count": len(response.get("payload", {}).get("devices", []))})

        duration_ms = int((time.time() - start_time) * 1000)
        log_request(intent, data, response, duration_ms)

        return jsonify(response) if response else (jsonify({"error": "upstream_error"}), status)

    # Handle QUERY with caching and offline fallback
    elif intent == "action.devices.QUERY":
        payload = inputs[0].get("payload", {})
        devices = payload.get("devices", [])
        device_ids = [d.get("id") for d in devices]

        # Try upstream first
        response, status, is_error = proxy_to_upstream("/api/google_assistant", data, request.headers)

        if not is_error and response:
            # Cache the states
            resp_devices = response.get("payload", {}).get("devices", {})
            cache_query_states(resp_devices)

            duration_ms = int((time.time() - start_time) * 1000)
            log_request(intent, data, response, duration_ms)
            return jsonify(response)

        # Offline fallback - return cached states
        cached_states = get_cached_states(device_ids)
        if cached_states:
            logger.warning(f"Returning cached states for {len(cached_states)} devices (offline fallback)")
            fallback_response = {
                "requestId": data.get("requestId"),
                "payload": {"devices": cached_states}
            }
            duration_ms = int((time.time() - start_time) * 1000)
            log_request(intent, data, fallback_response, duration_ms, offline=True)
            call_webhook("offline_fallback", {"device_ids": device_ids})
            return jsonify(fallback_response)

        # No cache, return error
        return jsonify({"error": "upstream_unavailable"}), status

    # Handle EXECUTE - always forward, no caching
    elif intent == "action.devices.EXECUTE":
        response, status, is_error = proxy_to_upstream("/api/google_assistant", data, request.headers)

        if response:
            call_webhook("execute", {
                "commands": inputs[0].get("payload", {}).get("commands", [])
            })

        duration_ms = int((time.time() - start_time) * 1000)
        log_request(intent, data, response, duration_ms)

        if is_error:
            return jsonify({"error": "upstream_error"}), status
        return jsonify(response)

    # Unknown intent - just proxy
    else:
        response, status, is_error = proxy_to_upstream("/api/google_assistant", data, request.headers)
        duration_ms = int((time.time() - start_time) * 1000)
        log_request(intent, data, response, duration_ms)

        if is_error:
            return jsonify({"error": "upstream_error"}), status
        return jsonify(response)


@app.route("/edge/stats", methods=["GET"])
def edge_stats():
    """Get edge proxy statistics."""
    with cache_lock:
        sync_count = len(sync_cache)
        query_count = len(query_cache)

        # Calculate cache ages
        now = time.time()
        sync_ages = [now - c["expires_at"] + SYNC_CACHE_TTL for c in sync_cache.values()]
        query_ages = [now - c["updated_at"] for c in query_cache.values()]

    with rate_lock:
        active_ips = len(rate_limits)

    return jsonify({
        "sync_cache": {
            "count": sync_count,
            "ttl_seconds": SYNC_CACHE_TTL,
            "avg_age_seconds": sum(sync_ages) / len(sync_ages) if sync_ages else 0
        },
        "query_cache": {
            "count": query_count,
            "ttl_seconds": QUERY_CACHE_TTL,
            "avg_age_seconds": sum(query_ages) / len(query_ages) if query_ages else 0
        },
        "rate_limiting": {
            "active_ips": active_ips,
            "limit": RATE_LIMIT_REQUESTS,
            "window_seconds": RATE_LIMIT_WINDOW
        }
    })


@app.route("/edge/cache/clear", methods=["POST"])
def clear_cache():
    """Clear all caches."""
    with cache_lock:
        sync_cache.clear()
        query_cache.clear()
    logger.info("Cache cleared")
    return jsonify({"status": "cleared"})


@app.route("/health", methods=["GET"])
def health():
    """Health check."""
    return jsonify({
        "status": "healthy",
        "service": "edge-proxy",
        "features": ["sync_cache", "query_cache", "offline_fallback", "rate_limit", "logging"]
    })


# Proxy all other requests to upstream
@app.route("/", defaults={"path": ""}, methods=["GET", "POST", "PUT", "DELETE"])
@app.route("/<path:path>", methods=["GET", "POST", "PUT", "DELETE"])
def proxy_all(path):
    """Proxy all other requests to upstream."""
    url = f"{UPSTREAM_URL}/{path}"

    try:
        if request.method == "GET":
            resp = requests.get(url, headers=dict(request.headers), timeout=30)
        else:
            resp = requests.request(
                request.method,
                url,
                headers=dict(request.headers),
                data=request.get_data(),
                timeout=30
            )

        # Return response with headers
        return Response(
            resp.content,
            status=resp.status_code,
            headers=dict(resp.headers)
        )
    except Exception as e:
        logger.error(f"Proxy error: {e}")
        return jsonify({"error": "proxy_error"}), 502


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8081))
    logger.info(f"Edge proxy starting on port {port}")
    logger.info(f"Upstream: {UPSTREAM_URL}")
    logger.info(f"SYNC cache TTL: {SYNC_CACHE_TTL}s")
    logger.info(f"Rate limit: {RATE_LIMIT_REQUESTS} req/{RATE_LIMIT_WINDOW}s")
    app.run(host="0.0.0.0", port=port, threaded=True)
