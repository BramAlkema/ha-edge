# GCP Tunnel for Home Assistant

[![Open your Home Assistant instance and show the add add-on repository dialog with a specific repository URL pre-filled.](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2FBramAlkema%2Fgcp-ha-tunnel)

Secure tunnel to Google Cloud Run for external Home Assistant access. No port forwarding required.

## Why Use This?

| Method | Cost | Port Forward | Complexity |
|--------|------|--------------|------------|
| Nabu Casa | $6.50/mo | No | Zero |
| DuckDNS | Free | **Yes** | Medium |
| **This** | Free* | **No** | Medium |

*Free tier covers typical home use

**Best for:** CGNAT, apartments, corporate networks - anywhere port forwarding isn't possible.

## How It Works

```
Google Assistant  →  Cloud Run (free)  →  Tunnel  →  Home Assistant
                         ↑                   ↑
                    Public HTTPS        chisel WebSocket
```

Uses [Home Assistant's built-in Google Assistant integration](https://www.home-assistant.io/integrations/google_assistant/) - we just provide the network path.

## Quick Start

### 1. Install Add-on

Click the badge above, or:
1. **Settings** → **Add-ons** → **Add-on Store** → ⋮ → **Repositories**
2. Add: `https://github.com/BramAlkema/gcp-ha-tunnel`
3. Install **GCP Tunnel Client**

### 2. Setup via Web UI

1. Open the **GCP Tunnel** panel in Home Assistant sidebar
2. Follow the 3-step wizard:
   - Create GCP project + service account
   - Upload service account key
   - Click **Deploy** → tunnel auto-deploys

### 3. Connect Google Assistant

After deploy, the UI shows exact URLs to paste into [Google Home Developer Console](https://console.home.google.com):

```
Fulfillment URL:   https://YOUR-URL/api/google_assistant
Authorization URL: https://YOUR-URL/auth/authorize
Token URL:         https://YOUR-URL/auth/token
Client ID:         https://oauth-redirect.googleusercontent.com/r/YOUR-PROJECT
```

### 4. Link in Google Home

Google Home app → + → **Set up device** → **Works with Google** → Search `[test] your-project`

## Features

- **One-click deploy** - Web UI deploys Cloud Run automatically
- **Auto-config** - Configures HA's google_assistant integration
- **Entity configuration** - UI to set aliases, rooms, and exposure per entity
- **Report state** - Push updates to Google (via HA's built-in batching)
- **Local fulfillment** - Optional: Google devices command HA directly on LAN
- **Health endpoint** - `/health` for monitoring
- **Dashboard sensors** - Auto-created sensors for tunnel status
- **Auto-reconnect** - Exponential backoff on disconnect
- **22 entity domains** - Lights, switches, climate, covers, locks, cameras, and more

### Edge Features (What Makes Us Different)

| Feature | Description |
|---------|-------------|
| **SYNC caching** | Device list cached 5 min - faster responses |
| **Offline fallback** | Returns cached state when HA unreachable |
| **Request logging** | Full JSON audit trail of all requests |
| **Rate limiting** | 100 req/min per IP - abuse protection |
| **Custom webhooks** | POST to external services on events |
| **Multi-region** | Deploy to multiple Cloud Run regions |

## Architecture

```
gcp-ha-tunnel/
├── gcp-tunnel-client/     # HA Add-on
│   ├── webapp/            # Setup wizard UI
│   ├── run.sh             # Tunnel + HA config
│   └── nginx.conf         # HTTP→HTTPS proxy
├── cloud-run/             # Tunnel server
│   ├── nginx.conf         # Routing + OAuth fixes
│   └── static/            # Privacy policy
└── .github/workflows/     # Builds tunnel-server image
```

## Costs

| Resource | Free Tier | Your Usage |
|----------|-----------|------------|
| Requests | 2M/month | ~50K |
| CPU | 180K vCPU-sec | ~10K |
| Memory | 360K GiB-sec | ~50K |

**Expected: $0/month**

## Health Endpoint

```bash
curl http://homeassistant.local:8099/health
```

Returns:
```json
{
  "status": "healthy",
  "tunnel_connected": true,
  "proxy_running": true,
  "report_state_enabled": true
}
```

## Local Fulfillment (Faster Responses)

After cloud setup, enable local fulfillment so Google devices command HA directly on your LAN:

1. In [Google Home Developer Console](https://console.home.google.com), go to your project
2. Enable **Local Home SDK**
3. For both Node.js and Chrome, enter this URL:
   ```
   https://YOUR-URL/local-sdk/app.js
   ```
4. Add mDNS scan config:
   - Service: `_home-assistant._tcp.local`
   - Name: `*\._home-assistant\._tcp\.local`
5. Check **Support local query**
6. Wait 30 minutes or restart Google devices
7. Say "OK Google, sync my devices"

The Local SDK bundle is hosted on your Cloud Run instance - no file upload needed.

## Entity Configuration

Click **Configure Entities** in the add-on UI to:
- Set custom names (e.g., "the lamp" instead of "Living Room Light")
- Add aliases (alternative names Google will recognize)
- Assign rooms (auto-maps to Google Home rooms)
- Hide entities from Google Assistant

## Alternatives

### Nabu Casa ($6.50/mo)
Zero setup, supports everything. If you value your time, this is the answer.

### Matter/Matterbridge (100% Local)

If you have Matter-compatible Google devices (Nest Hub, Nest Mini 2nd gen+), consider **Matterbridge** instead:

| Feature | GCP Tunnel | Matterbridge |
|---------|------------|--------------|
| Cloud required | Yes (GCP) | No |
| Works offline | No | Yes |
| Port forwarding | No | No |
| Setup complexity | Medium | Medium |
| Response time | ~500ms | ~100ms |
| Cost | Free | Free |

**When to use Matterbridge:**
- You have Matter-compatible Google devices
- You want 100% local control
- You don't need cloud access to HA

**Install Matterbridge:**
1. Install the [Matterbridge add-on](https://github.com/Luligu/matterbridge-hass)
2. Scan the QR code in Google Home
3. All HA entities appear as native Matter devices

Links:
- [Matterbridge for HA](https://github.com/Luligu/matterbridge-hass)
- [Home Assistant Matter Hub](https://github.com/t0bst4r/home-assistant-matter-hub)

## Edge Proxy Stats

Monitor your edge proxy:

```bash
# Get cache and rate limit stats
curl https://YOUR-URL/edge/stats

# Clear all caches (forces fresh data)
curl -X POST https://YOUR-URL/edge/cache/clear
```

Response:
```json
{
  "sync_cache": {"count": 5, "ttl_seconds": 300, "avg_age_seconds": 120},
  "query_cache": {"count": 42, "ttl_seconds": 60, "avg_age_seconds": 30},
  "rate_limiting": {"active_ips": 3, "limit": 100, "window_seconds": 60}
}
```

## Multi-Region Deployment

Deploy to multiple regions for lower latency:

```bash
# Deploy to multiple regions
for REGION in us-central1 europe-west1 asia-east1; do
  gcloud run deploy ha-tunnel \
    --region=$REGION \
    --image=ghcr.io/bramalkema/gcp-ha-tunnel/tunnel-server:latest \
    --allow-unauthenticated \
    --set-env-vars=AUTH=hauser:YOUR_PASS
done
```

Then use Cloud Run's global load balancing or set up regional URLs in Actions Console.

## Custom Webhooks

Get notified of events by setting the `WEBHOOK_URL` environment variable:

```bash
gcloud run services update ha-tunnel \
  --set-env-vars=WEBHOOK_URL=https://your-webhook.example.com/events
```

Events sent:
- `sync` - Device list synchronized
- `execute` - Command executed
- `offline_fallback` - Returned cached data (HA unreachable)

## Troubleshooting

**Tunnel won't connect:**
- Check add-on logs for specific error messages
- Verify Cloud Run: `curl https://YOUR-URL/health`
- Check auth credentials match

**Google Assistant errors:**
- Ensure tunnel shows "Connected" in logs
- Re-link account in Google Home app
- Check HA logs for `google_assistant` errors

**Report state not working:**
- Upload service account key via web UI
- Restart add-on after upload
- Check HA logs for HomeGraph errors

**Local fulfillment not working:**
- Ensure HA and Google device are on same network
- Check mDNS config in Actions Console
- Restart Google devices after enabling

## License

MIT
