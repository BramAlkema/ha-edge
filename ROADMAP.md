# GCP Tunnel Roadmap

## Vision: The Edge Layer for Home Automation

This project provides a **smart edge layer** between the internet and Home Assistant.
Unlike DuckDNS (direct connection), we have an intelligent intermediary.

```
                    ┌─────────────────────────────────────┐
                    │         CLOUD RUN (FREE)            │
   Internet ────────┤                                     │
                    │   ┌─────────┐      ┌─────────┐     │
                    │   │ BOUNCER │      │ BUTLER  │     │
                    │   │         │      │         │     │
                    │   │ - Auth  │      │ - Cache │     │
                    │   │ - Rate  │      │ - Log   │     │
                    │   │ - Block │      │ - Route │     │
                    │   └────┬────┘      └────┬────┘     │
                    │        │                │          │
                    │        └───────┬────────┘          │
                    │                │                   │
                    └────────────────┼───────────────────┘
                                     │ tunnel
                    ┌────────────────┼───────────────────┐
                    │                ▼                   │
                    │         HOME ASSISTANT             │
                    │    (source of truth, media)        │
                    └────────────────────────────────────┘
```

### BOUNCER (Security)
- Rate limiting per IP (nginx + edge proxy)
- Remote UI toggle (on/off from HA config)
- Auth validation
- Request filtering
- Header stripping (prevent trusted_proxies bypass)
- Security headers

### BUTLER (Intelligence)
- SYNC caching (device list, 5 min TTL)
- QUERY caching (offline fallback when HA down)
- Request logging (JSON audit trail)
- Webhook notifications (external integrations)
- Protocol translation (Google → HA)

---

## Current Features (v2.1)

### Core
- [x] Chisel WebSocket tunnel (no port forwarding)
- [x] HTTPS via Cloud Run (free TLS)
- [x] Session affinity (sticky sessions)
- [x] Auto-reconnect with exponential backoff
- [x] gunicorn for production Python

### Google Assistant
- [x] Fulfillment endpoint with caching
- [x] OAuth relay with state fix
- [x] 22 entity domains
- [x] Local Home SDK hosting (/local-sdk/app.js)
- [x] Report state (via HA's built-in service account)

### Remote UI
- [x] Full HA dashboard access
- [x] WebSocket support (real-time updates)
- [x] Toggle via add-on config (remote_ui_enabled)
- [x] Rate limiting (10 req/s per IP)

### Edge Features
- [x] SYNC response caching (5 min TTL)
- [x] QUERY state caching (offline fallback)
- [x] Request logging (structured JSON)
- [x] Rate limiting (nginx zones + Python)
- [x] Custom webhooks (POST on sync/execute/offline)

### Setup
- [x] One-click deploy from add-on UI
- [x] QR code for Google Home linking
- [x] Copy buttons for console URLs
- [x] Entity configuration UI (aliases, rooms)

---

## Future Roadmap

### Phase A: Harden & Polish (Current)
- [x] Add type hints to Python
- [x] Improve documentation (nginx, edge_proxy)
- [x] Add inline TODOs for future features
- [x] Security headers (X-Content-Type-Options, X-Frame-Options)
- [ ] Input validation hardening
- [ ] Error handling improvements
- [ ] Unit tests for edge_proxy

### Phase B: More Voice Assistants
- [ ] **Alexa Smart Home Skill**
  - Same caching pattern as Google
  - Lambda-less (direct to Cloud Run)
- [ ] **Siri Shortcuts webhook**
  - Simple POST → HA service call

### Phase C: Notification Hub
```
HA notification → Edge Proxy → Telegram
                            → Pushover
                            → Discord
                            → Email
                            → Push notification
```
- [ ] Receive notifications from HA via webhook
- [ ] Fan out to multiple services
- [ ] Batching/deduplication ("5 motion events" not 5 alerts)
- [ ] Notification history/search
- [ ] Escalation rules (if not acked in 5 min, call phone)

### Phase D: Presence & Location
```
Phone GPS → Edge Proxy → Compute zones → HA gets "home"/"away"
                      (privacy: exact coords never touch HA)
```
- [ ] Phone location POST endpoint
- [ ] Geofence computation at edge
- [ ] Privacy: only send zone state to HA
- [ ] Multi-user support

### Phase E: External Data Cache
```
Edge Proxy caches: Weather, energy prices, air quality, traffic
HA queries edge, not external APIs (faster, fewer API calls)
```
- [ ] Weather API caching (OpenWeatherMap, etc.)
- [ ] Energy price caching (Nordpool, Octopus)
- [ ] Air quality aggregation
- [ ] Generic webhook → HA bridge (Zapier/IFTTT/Make)

### Phase F: Advanced Features
- [ ] **LLM Gateway** - "Make it cozy" → specific HA calls
- [ ] **Camera thumbnail proxy** (not streaming - too much bandwidth)
- [ ] **Multi-home sync** - Beach house knows main house is "away"
- [ ] **Cloud backup** - Config backup to GCS

---

## Architecture Decisions

### Why Cloud Run?
| Feature | Benefit |
|---------|---------|
| Free tier | 2M requests/month |
| Managed TLS | No cert management |
| Auto-scale | Scales to zero when idle |
| No infra | Google manages everything |

### Why Chisel?
| Feature | Benefit |
|---------|---------|
| WebSocket | Works through firewalls/CGNAT |
| Lightweight | Single binary |
| Reverse tunnel | HA connects out, no port forward |
| Simple auth | user:pass, no PKI |

### Why Edge Proxy (Python)?
| Feature | Benefit |
|---------|---------|
| Complex logic | Caching, fallback, routing |
| TTL management | Per-cache TTLs |
| Easy webhooks | requests library |
| Future ML | Python ecosystem |

### Why not Nabu Casa?
| This Project | Nabu Casa |
|--------------|-----------|
| Free | $6.50/mo |
| Edge features | Direct tunnel |
| Self-hosted | Managed |
| Learning | Zero config |

---

## Free Tier Budget

| Resource | Free/Month | Typical Use | Headroom |
|----------|------------|-------------|----------|
| Requests | 2,000,000 | ~20,000 | 100x |
| CPU | 180,000 vCPU-sec | ~10,000 | 18x |
| Memory | 360,000 GiB-sec | ~50,000 | 7x |
| Egress | 1 GB | ~200 MB | 5x |

### Stay Free By:
1. **Cache aggressively** - SYNC 5 min, QUERY 1 min
2. **No video streaming** - Thumbnails only
3. **min-instances=0** - Cold start OK for home use
4. **Compress responses** - gzip in nginx

---

## Completed Milestones

### v1.0 - Basic Tunnel
- [x] Chisel tunnel (Cloud Run + HA add-on)
- [x] Google Assistant integration
- [x] OAuth relay with state fix
- [x] Auto-reconnect with backoff

### v2.0 - Edge Features
- [x] Edge proxy (caching, logging, webhooks)
- [x] Remote UI support (WebSocket)
- [x] Rate limiting
- [x] Entity configuration UI
- [x] Local Home SDK hosting
- [x] 22 entity domains

### v2.1 - Polish
- [x] gunicorn for production
- [x] Improved documentation
- [x] Type hints and TODOs
- [x] Security headers
- [x] Remote UI toggle

---

## Contributing

### Adding a New Endpoint

```python
# edge_proxy.py
@app.route("/api/new_feature", methods=["POST"])
@rate_limit
def new_feature():
    """Description of what it does.

    TODO: Future improvements.
    """
    data = request.get_json() or {}
    # Implementation
    return jsonify({"status": "ok"})
```

### Code Style
- **Python**: Type hints, docstrings, snake_case
- **Shell**: bashio logging, set -u, error handling
- **nginx**: Section comments, consistent indentation

---

## Links

- [Home Assistant Google Assistant](https://www.home-assistant.io/integrations/google_assistant/)
- [Google Home Developer Console](https://console.home.google.com)
- [Cloud Run Pricing](https://cloud.google.com/run/pricing)
- [Chisel](https://github.com/jpillora/chisel)
