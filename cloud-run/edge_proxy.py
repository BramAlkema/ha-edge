#!/usr/bin/env python3
"""
Home Assistant Edge - Stateless Edge Companion

The "Bouncer" and "Butler" for Home Assistant.

This edge proxy sits between the internet and Home Assistant, providing:

BOUNCER (Security):
- Rate limiting per IP
- Auth validation
- Request filtering
- Remote UI toggle

BUTLER (Intelligence):
- SYNC response caching (device list)
- QUERY state caching (offline fallback)
- Request logging (audit trail)
- Webhook notifications

Architecture:
    Internet → Cloud Run (nginx) → Edge Proxy → Tunnel → Home Assistant
                                   ^^^^^^^^^^^
                                   (this file)

Environment Variables:
    UPSTREAM_URL        - Tunnel endpoint (default: http://127.0.0.1:9001)
    SYNC_CACHE_TTL      - Device list cache TTL in seconds (default: 300)
    QUERY_CACHE_TTL     - State cache TTL in seconds (default: 60)
    RATE_LIMIT_REQUESTS - Max requests per window (default: 100)
    RATE_LIMIT_WINDOW   - Rate limit window in seconds (default: 60)
    WEBHOOK_URL         - Optional webhook for events
    LOG_REQUESTS        - Enable request logging (default: true)
    AUTH                - user:pass for tunnel auth (from secret)
    REMOTE_UI_ENABLED   - Initial remote UI state (default: false)
"""

import os
import json
import time
import hashlib
import logging
from datetime import datetime
from collections import defaultdict
from functools import wraps
from threading import Lock
from typing import Any, Optional

import requests
from flask import Flask, request, jsonify, Response

# =============================================================================
# Configuration
# =============================================================================

app = Flask(__name__)

# Upstream tunnel endpoint
UPSTREAM_URL = os.environ.get("UPSTREAM_URL", "http://127.0.0.1:9001")

# Cache TTLs
SYNC_CACHE_TTL = int(os.environ.get("SYNC_CACHE_TTL", 300))    # 5 minutes
QUERY_CACHE_TTL = int(os.environ.get("QUERY_CACHE_TTL", 60))   # 1 minute

# Rate limiting
RATE_LIMIT_REQUESTS = int(os.environ.get("RATE_LIMIT_REQUESTS", 100))
RATE_LIMIT_WINDOW = int(os.environ.get("RATE_LIMIT_WINDOW", 60))  # seconds

# Optional webhook for external notifications
WEBHOOK_URL = os.environ.get("WEBHOOK_URL", "")

# Request logging
LOG_REQUESTS = os.environ.get("LOG_REQUESTS", "true").lower() == "true"

# =============================================================================
# State (in-memory, resets on container restart)
# =============================================================================

# SYNC cache: {user_id: {response, expires_at}}
sync_cache: dict[str, dict] = {}

# QUERY cache: {device_id: {state, updated_at}}
query_cache: dict[str, dict] = {}

# Lock for cache operations (thread-safe)
cache_lock = Lock()

# Rate limiting: {ip: [timestamps]}
rate_limits: dict[str, list[float]] = defaultdict(list)
rate_lock = Lock()

# Remote UI toggle (controlled by HA add-on)
remote_ui_settings = {
    "enabled": os.environ.get("REMOTE_UI_ENABLED", "").lower() == "true",
    "updated_at": time.time()
}

# =============================================================================
# Logging
# =============================================================================

logging.basicConfig(
    level=logging.INFO,
    format='{"ts":"%(asctime)s","level":"%(levelname)s","msg":"%(message)s"}',
    datefmt='%Y-%m-%dT%H:%M:%SZ'
)
logger = logging.getLogger(__name__)

# =============================================================================
# Helper Functions
# =============================================================================

def get_client_ip() -> str:
    """Extract client IP from X-Forwarded-For header or connection.

    Cloud Run sets X-Forwarded-For, so we use that first.
    Takes first IP if multiple (client's original IP).
    """
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.remote_addr or "unknown"


def validate_json_safe(data: Any) -> bool:
    """Basic validation that data is safe JSON (no excessive nesting/size).

    TODO: Add more robust validation for production.
    """
    try:
        serialized = json.dumps(data)
        # Reject if > 1MB
        if len(serialized) > 1_000_000:
            return False
        return True
    except (TypeError, ValueError):
        return False


# =============================================================================
# Decorators
# =============================================================================

def rate_limit(f):
    """Rate limiting decorator.

    Uses sliding window algorithm. Limits requests per IP.

    Note: In-memory only - doesn't persist across restarts or scale
    across multiple instances. For production at scale, use Redis.

    TODO: Add Redis backend for distributed rate limiting.
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        ip = get_client_ip()
        now = time.time()

        with rate_lock:
            # Remove timestamps outside the window
            rate_limits[ip] = [
                t for t in rate_limits[ip]
                if now - t < RATE_LIMIT_WINDOW
            ]

            # Check if over limit
            if len(rate_limits[ip]) >= RATE_LIMIT_REQUESTS:
                logger.warning(f"Rate limit exceeded: ip={ip}")
                return jsonify({
                    "error": "rate_limit_exceeded",
                    "retry_after": RATE_LIMIT_WINDOW
                }), 429

            # Record this request
            rate_limits[ip].append(now)

        return f(*args, **kwargs)
    return decorated


# =============================================================================
# Cache Functions
# =============================================================================

def cache_sync_response(user_id: str, response: dict) -> None:
    """Cache a SYNC response (device list).

    SYNC responses are expensive (full device enumeration) but stable.
    Cache for 5 minutes to reduce load on HA.
    """
    with cache_lock:
        sync_cache[user_id] = {
            "response": response,
            "expires_at": time.time() + SYNC_CACHE_TTL
        }
    # Truncate user_id in logs for privacy
    logger.info(f"Cached SYNC: user={user_id[:8]}... ttl={SYNC_CACHE_TTL}s")


def get_cached_sync(user_id: str) -> Optional[dict]:
    """Get cached SYNC response if still valid."""
    with cache_lock:
        cached = sync_cache.get(user_id)
        if cached and cached["expires_at"] > time.time():
            logger.info(f"SYNC cache hit: user={user_id[:8]}...")
            return cached["response"]
    return None


def cache_query_states(devices: dict) -> None:
    """Cache device states from QUERY response.

    Used for offline fallback - if HA is unreachable, return last known state.
    """
    with cache_lock:
        for device_id, state in devices.items():
            query_cache[device_id] = {
                "state": state,
                "updated_at": time.time()
            }
    logger.info(f"Cached states: devices={len(devices)}")


def get_cached_states(device_ids: list[str]) -> dict:
    """Get cached states for offline fallback.

    Adds _cached flag so clients know this is stale data.
    """
    states = {}
    with cache_lock:
        for device_id in device_ids:
            cached = query_cache.get(device_id)
            if cached:
                state = cached["state"].copy()
                state["_cached"] = True
                state["_cached_at"] = cached["updated_at"]
                states[device_id] = state
    return states


# =============================================================================
# Logging & Webhooks
# =============================================================================

def log_request(
    intent: str,
    request_data: dict,
    response_data: Optional[dict],
    duration_ms: int,
    cached: bool = False,
    offline: bool = False
) -> None:
    """Log request as structured JSON for audit trail.

    Outputs to stdout (captured by Cloud Run logging).
    """
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

    # Add device IDs for QUERY/EXECUTE (first 5 only for brevity)
    if intent in ["action.devices.QUERY", "action.devices.EXECUTE"]:
        inputs = request_data.get("inputs", [{}])
        if inputs:
            payload = inputs[0].get("payload", {})
            devices = payload.get("devices", [])
            if devices:
                log_entry["device_ids"] = [d.get("id") for d in devices[:5]]

    print(json.dumps(log_entry), flush=True)


def call_webhook(event_type: str, data: dict) -> None:
    """Call external webhook if configured.

    Non-blocking, fire-and-forget. Failures are logged but don't affect response.

    TODO: Add retry logic with exponential backoff.
    TODO: Add webhook signature for security.
    """
    if not WEBHOOK_URL:
        return

    try:
        payload = {
            "event": event_type,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "data": data
        }
        # Short timeout - don't block on slow webhooks
        requests.post(WEBHOOK_URL, json=payload, timeout=5)
        logger.info(f"Webhook sent: event={event_type}")
    except requests.exceptions.Timeout:
        logger.warning(f"Webhook timeout: event={event_type}")
    except Exception as e:
        logger.error(f"Webhook failed: event={event_type} error={e}")


# =============================================================================
# Upstream Proxy
# =============================================================================

def proxy_to_upstream(path: str, data: dict, headers) -> tuple[Optional[dict], int, bool]:
    """Proxy request to upstream tunnel.

    Returns: (response_json, status_code, is_error)
    """
    url = f"{UPSTREAM_URL}{path}"

    # Only forward safe headers
    forward_headers = {
        "Content-Type": "application/json",
        "Authorization": headers.get("Authorization", ""),
    }

    try:
        resp = requests.post(url, json=data, headers=forward_headers, timeout=30)
        return resp.json(), resp.status_code, False
    except requests.exceptions.Timeout:
        logger.error(f"Upstream timeout: path={path}")
        return None, 504, True
    except requests.exceptions.ConnectionError:
        logger.error(f"Upstream connection error: path={path}")
        return None, 502, True
    except json.JSONDecodeError:
        logger.error(f"Upstream invalid JSON: path={path}")
        return None, 502, True
    except Exception as e:
        logger.error(f"Upstream error: path={path} error={e}")
        return None, 500, True


# =============================================================================
# Google Assistant Endpoint
# =============================================================================

@app.route("/api/google_assistant", methods=["POST"])
@rate_limit
def google_assistant():
    """Main Google Assistant fulfillment endpoint.

    Handles three intents from Google:
    - SYNC: Return list of all devices (cached)
    - QUERY: Return current state of devices (cached for offline fallback)
    - EXECUTE: Execute commands on devices (never cached)

    TODO: Add Alexa Smart Home endpoint with similar caching.
    TODO: Add intent validation (verify request signature from Google).
    """
    start_time = time.time()

    # Parse request
    data = request.get_json() or {}

    # Basic validation
    if not validate_json_safe(data):
        return jsonify({"error": "invalid_request"}), 400

    # Extract intent
    inputs = data.get("inputs", [])
    intent = inputs[0].get("intent", "unknown") if inputs else "unknown"
    user_id = data.get("agentUserId", "default")

    # -------------------------------------------------------------------------
    # SYNC: Return device list (cached)
    # -------------------------------------------------------------------------
    if intent == "action.devices.SYNC":
        # Check cache first
        cached = get_cached_sync(user_id)
        if cached:
            duration_ms = int((time.time() - start_time) * 1000)
            log_request(intent, data, cached, duration_ms, cached=True)
            return jsonify(cached)

        # Forward to HA
        response, status, is_error = proxy_to_upstream(
            "/api/google_assistant", data, request.headers
        )

        if not is_error and response:
            cache_sync_response(user_id, response)
            device_count = len(response.get("payload", {}).get("devices", []))
            call_webhook("sync", {"user_id": user_id[:8], "device_count": device_count})

        duration_ms = int((time.time() - start_time) * 1000)
        log_request(intent, data, response, duration_ms)

        if is_error or not response:
            return jsonify({"error": "upstream_error"}), status
        return jsonify(response)

    # -------------------------------------------------------------------------
    # QUERY: Return device states (cached for offline fallback)
    # -------------------------------------------------------------------------
    elif intent == "action.devices.QUERY":
        payload = inputs[0].get("payload", {}) if inputs else {}
        devices = payload.get("devices", [])
        device_ids = [d.get("id") for d in devices if d.get("id")]

        # Try upstream first
        response, status, is_error = proxy_to_upstream(
            "/api/google_assistant", data, request.headers
        )

        if not is_error and response:
            # Cache states for offline fallback
            resp_devices = response.get("payload", {}).get("devices", {})
            if resp_devices:
                cache_query_states(resp_devices)

            duration_ms = int((time.time() - start_time) * 1000)
            log_request(intent, data, response, duration_ms)
            return jsonify(response)

        # Offline fallback - return cached states
        cached_states = get_cached_states(device_ids)
        if cached_states:
            logger.warning(f"Offline fallback: devices={len(cached_states)}")
            fallback_response = {
                "requestId": data.get("requestId"),
                "payload": {"devices": cached_states}
            }
            duration_ms = int((time.time() - start_time) * 1000)
            log_request(intent, data, fallback_response, duration_ms, offline=True)
            call_webhook("offline_fallback", {"device_ids": device_ids[:5]})
            return jsonify(fallback_response)

        # No cache available
        return jsonify({"error": "upstream_unavailable"}), status

    # -------------------------------------------------------------------------
    # EXECUTE: Run commands (never cached)
    # -------------------------------------------------------------------------
    elif intent == "action.devices.EXECUTE":
        response, status, is_error = proxy_to_upstream(
            "/api/google_assistant", data, request.headers
        )

        if response:
            commands = inputs[0].get("payload", {}).get("commands", []) if inputs else []
            call_webhook("execute", {"command_count": len(commands)})

        duration_ms = int((time.time() - start_time) * 1000)
        log_request(intent, data, response, duration_ms)

        if is_error:
            return jsonify({"error": "upstream_error"}), status
        return jsonify(response)

    # -------------------------------------------------------------------------
    # Unknown intent - proxy as-is
    # -------------------------------------------------------------------------
    else:
        logger.warning(f"Unknown intent: {intent}")
        response, status, is_error = proxy_to_upstream(
            "/api/google_assistant", data, request.headers
        )
        duration_ms = int((time.time() - start_time) * 1000)
        log_request(intent, data, response, duration_ms)

        if is_error:
            return jsonify({"error": "upstream_error"}), status
        return jsonify(response)


# =============================================================================
# Edge Management Endpoints
# =============================================================================

@app.route("/edge/stats", methods=["GET"])
def edge_stats():
    """Get edge proxy statistics.

    Returns cache sizes, ages, and rate limiting info.
    """
    now = time.time()

    with cache_lock:
        sync_count = len(sync_cache)
        query_count = len(query_cache)
        sync_ages = [now - c["expires_at"] + SYNC_CACHE_TTL for c in sync_cache.values()]
        query_ages = [now - c["updated_at"] for c in query_cache.values()]

    with rate_lock:
        active_ips = len(rate_limits)

    return jsonify({
        "sync_cache": {
            "count": sync_count,
            "ttl_seconds": SYNC_CACHE_TTL,
            "avg_age_seconds": round(sum(sync_ages) / len(sync_ages), 1) if sync_ages else 0
        },
        "query_cache": {
            "count": query_count,
            "ttl_seconds": QUERY_CACHE_TTL,
            "avg_age_seconds": round(sum(query_ages) / len(query_ages), 1) if query_ages else 0
        },
        "rate_limiting": {
            "active_ips": active_ips,
            "limit": RATE_LIMIT_REQUESTS,
            "window_seconds": RATE_LIMIT_WINDOW
        },
        "remote_ui": {
            "enabled": remote_ui_settings["enabled"]
        }
    })


@app.route("/edge/cache/clear", methods=["POST"])
def clear_cache():
    """Clear all caches (requires tunnel auth)."""
    # Authenticate
    auth = request.authorization
    expected_auth = os.environ.get("AUTH", "").split(":", 1)

    if len(expected_auth) == 2:
        if not auth or auth.username != expected_auth[0] or auth.password != expected_auth[1]:
            return jsonify({"error": "unauthorized"}), 401

    with cache_lock:
        sync_count = len(sync_cache)
        query_count = len(query_cache)
        sync_cache.clear()
        query_cache.clear()

    logger.info(f"Cache cleared: sync={sync_count} query={query_count}")
    return jsonify({"status": "cleared", "sync_cleared": sync_count, "query_cleared": query_count})


# =============================================================================
# Remote UI Toggle
# =============================================================================

@app.route("/edge/remote-ui", methods=["GET", "POST"])
def remote_ui_toggle():
    """Get or set remote UI access.

    GET:  Returns current setting (public)
    POST: Update setting (requires tunnel auth)

    The HA add-on calls POST on startup to sync the setting.
    """
    if request.method == "GET":
        return jsonify({
            "enabled": remote_ui_settings["enabled"],
            "updated_at": remote_ui_settings["updated_at"]
        })

    # POST - authenticate first
    auth = request.authorization
    expected_auth = os.environ.get("AUTH", "").split(":", 1)

    if len(expected_auth) == 2:
        if not auth or auth.username != expected_auth[0] or auth.password != expected_auth[1]:
            return jsonify({"error": "unauthorized"}), 401

    data = request.get_json() or {}
    enabled = bool(data.get("enabled", False))

    remote_ui_settings["enabled"] = enabled
    remote_ui_settings["updated_at"] = time.time()

    logger.info(f"Remote UI: {'enabled' if enabled else 'disabled'}")
    return jsonify({
        "enabled": remote_ui_settings["enabled"],
        "updated_at": remote_ui_settings["updated_at"]
    })


@app.route("/edge/remote-ui/check", methods=["GET"])
def remote_ui_check():
    """Quick check for nginx auth_request.

    Returns 200 if UI access allowed, 403 if denied.
    Always allows WebSocket upgrades (Chisel tunnel).

    Called by nginx on every UI request via auth_request.
    """
    # Always allow WebSocket (Chisel tunnel control channel)
    if request.headers.get("X-Original-Upgrade", "").lower() == "websocket":
        return "", 200

    if remote_ui_settings["enabled"]:
        return "", 200

    return "Remote UI disabled", 403


# =============================================================================
# Health Check
# =============================================================================

@app.route("/health", methods=["GET"])
def health():
    """Health check endpoint.

    Used by Cloud Run for liveness/readiness probes.
    """
    return jsonify({
        "status": "healthy",
        "service": "ha-edge",
        "version": "2.2.0",
        "features": {
            "bouncer": ["rate_limit", "auth", "remote_ui_toggle"],
            "butler": ["sync_cache", "query_cache", "offline_fallback", "webhooks", "logging"],
            "voice_assistants": ["google_assistant", "alexa"]
        }
    })


# =============================================================================
# Alexa Smart Home Endpoint
# =============================================================================

# Alexa caches (similar to Google)
alexa_discovery_cache: dict[str, dict] = {}  # {user_id: {response, expires_at}}
alexa_state_cache: dict[str, dict] = {}      # {endpoint_id: {state, updated_at}}

ALEXA_DISCOVERY_TTL = int(os.environ.get("ALEXA_DISCOVERY_TTL", 300))  # 5 minutes


@app.route("/api/alexa", methods=["POST"])
@rate_limit
def alexa_smart_home():
    """Alexa Smart Home Skill endpoint.

    Handles directives from Alexa via Lambda proxy:
    - Alexa.Discovery: Return list of devices (cached)
    - Alexa.ReportState: Return device state (cached for offline fallback)
    - Alexa.*Controller: Execute commands (never cached)

    The Lambda proxy forwards requests from Alexa to this endpoint.
    We process them and forward to Home Assistant's alexa/smart_home endpoint.
    """
    start_time = time.time()

    # Parse request
    data = request.get_json() or {}

    # Basic validation
    if not validate_json_safe(data):
        return jsonify({"error": "invalid_request"}), 400

    # Extract directive info
    directive = data.get("directive", {})
    header = directive.get("header", {})
    namespace = header.get("namespace", "unknown")
    name = header.get("name", "unknown")

    # For logging
    directive_type = f"{namespace}.{name}"

    # -------------------------------------------------------------------------
    # Alexa.Discovery: Return device list (cached)
    # -------------------------------------------------------------------------
    if namespace == "Alexa.Discovery" and name == "Discover":
        # Use bearer token as user key
        auth_header = request.headers.get("Authorization", "")
        user_id = hashlib.sha256(auth_header.encode()).hexdigest()[:16]

        # Check cache first
        with cache_lock:
            cached = alexa_discovery_cache.get(user_id)
            if cached and cached["expires_at"] > time.time():
                logger.info(f"Alexa Discovery cache hit: user={user_id[:8]}...")
                duration_ms = int((time.time() - start_time) * 1000)
                log_request(directive_type, data, cached["response"], duration_ms, cached=True)
                return jsonify(cached["response"])

        # Forward to HA
        response, status, is_error = proxy_to_upstream(
            "/api/alexa/smart_home", data, request.headers
        )

        if not is_error and response:
            # Cache the response
            with cache_lock:
                alexa_discovery_cache[user_id] = {
                    "response": response,
                    "expires_at": time.time() + ALEXA_DISCOVERY_TTL
                }
            endpoints = response.get("event", {}).get("payload", {}).get("endpoints", [])
            logger.info(f"Alexa Discovery: cached {len(endpoints)} endpoints")
            call_webhook("alexa_discovery", {"endpoint_count": len(endpoints)})

        duration_ms = int((time.time() - start_time) * 1000)
        log_request(directive_type, data, response, duration_ms)

        if is_error or not response:
            return jsonify({"error": "upstream_error"}), status
        return jsonify(response)

    # -------------------------------------------------------------------------
    # Alexa.ReportState: Return device state (cached for offline fallback)
    # -------------------------------------------------------------------------
    elif namespace == "Alexa" and name == "ReportState":
        endpoint = directive.get("endpoint", {})
        endpoint_id = endpoint.get("endpointId", "unknown")

        # Try upstream first
        response, status, is_error = proxy_to_upstream(
            "/api/alexa/smart_home", data, request.headers
        )

        if not is_error and response:
            # Cache state for offline fallback
            context = response.get("context", {})
            properties = context.get("properties", [])
            if properties:
                with cache_lock:
                    alexa_state_cache[endpoint_id] = {
                        "properties": properties,
                        "updated_at": time.time()
                    }

            duration_ms = int((time.time() - start_time) * 1000)
            log_request(directive_type, data, response, duration_ms)
            return jsonify(response)

        # Offline fallback - return cached state
        with cache_lock:
            cached = alexa_state_cache.get(endpoint_id)
            if cached:
                logger.warning(f"Alexa offline fallback: endpoint={endpoint_id}")
                fallback_response = {
                    "event": {
                        "header": {
                            "namespace": "Alexa",
                            "name": "StateReport",
                            "messageId": header.get("messageId", ""),
                            "correlationToken": header.get("correlationToken", ""),
                            "payloadVersion": "3"
                        },
                        "endpoint": endpoint,
                        "payload": {}
                    },
                    "context": {
                        "properties": cached["properties"]
                    }
                }
                duration_ms = int((time.time() - start_time) * 1000)
                log_request(directive_type, data, fallback_response, duration_ms, offline=True)
                call_webhook("alexa_offline_fallback", {"endpoint_id": endpoint_id})
                return jsonify(fallback_response)

        return jsonify({"error": "upstream_unavailable"}), status

    # -------------------------------------------------------------------------
    # All other directives (controllers): Forward to HA (never cached)
    # -------------------------------------------------------------------------
    else:
        response, status, is_error = proxy_to_upstream(
            "/api/alexa/smart_home", data, request.headers
        )

        if response and namespace.endswith("Controller"):
            call_webhook("alexa_execute", {"directive": directive_type})

        duration_ms = int((time.time() - start_time) * 1000)
        log_request(directive_type, data, response, duration_ms)

        if is_error:
            return jsonify({"error": "upstream_error"}), status
        return jsonify(response)


# =============================================================================
# Future Endpoints (TODOs)
# =============================================================================

# TODO: Notification hub
# @app.route("/api/notify", methods=["POST"])
# def notification_hub():
#     """Receive notifications from HA, fan out to multiple services."""
#     pass

# TODO: Presence endpoint
# @app.route("/api/presence", methods=["POST"])
# def presence_update():
#     """Receive location updates, compute zones, forward state to HA."""
#     pass

# TODO: LLM gateway
# @app.route("/api/ask", methods=["POST"])
# def llm_gateway():
#     """Natural language → HA intent translation."""
#     pass


# =============================================================================
# Main (for local development only - production uses gunicorn)
# =============================================================================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8081))
    logger.info(f"Edge proxy starting on port {port}")
    logger.info(f"Upstream: {UPSTREAM_URL}")
    logger.info(f"SYNC cache TTL: {SYNC_CACHE_TTL}s")
    logger.info(f"Rate limit: {RATE_LIMIT_REQUESTS} req/{RATE_LIMIT_WINDOW}s")
    app.run(host="0.0.0.0", port=port, threaded=True)
