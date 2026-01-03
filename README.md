# Home Assistant Edge

*Stateless edge companion for Home Assistant. Voice control, remote access, smart caching — all on Google Cloud free tier.*

[![Open your Home Assistant instance and show the add add-on repository dialog with a specific repository URL pre-filled.](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2FBramAlkema%2Fha-edge)

## Features

- **Google Assistant** — "Hey Google, turn on the lights"
- **Amazon Alexa** — "Alexa, set thermostat to 20"
- **Remote UI** — Access your dashboard from anywhere
- **No port forwarding** — works behind CGNAT, firewalls, whatever
- **Smart edge layer** — caching, rate limiting, offline fallback
- **One-click deploy** — GCP free tier, zero cost

## How It Works

```
┌─────────────────────────────────────┐
│      YOUR GOOGLE CLOUD PROJECT      │
│                                     │
│   ┌─────────┐      ┌─────────┐     │
│   │ BOUNCER │      │ BUTLER  │     │
│   │ Security│      │ Cache   │     │
│   └────┬────┘      └────┬────┘     │
│        └───────┬────────┘          │
└────────────────┼───────────────────┘
                 │ tunnel
         ┌───────▼───────┐
         │ HOME ASSISTANT │
         └───────────────┘
```

Your smart home, your cloud, your rules.

## Quick Start

### 1. Install Add-on

Click the badge above, or:
1. **Settings** → **Add-ons** → **Add-on Store** → ⋮ → **Repositories**
2. Add: `https://github.com/BramAlkema/ha-edge`
3. Install **Home Assistant Edge**

### 2. Setup via Web UI

1. Open the **HA Edge** panel in Home Assistant sidebar
2. Follow the wizard:
   - Create GCP project + service account
   - Upload service account key
   - Click **Deploy** → tunnel auto-deploys

### 3. Connect Voice Assistants

**Google Assistant:**
The UI shows exact URLs to paste into [Google Home Developer Console](https://console.home.google.com).

**Amazon Alexa:**
Click "Setup Alexa" in the UI for guided CloudShell script + Alexa Developer Console setup.

### 4. Enable Remote UI (Optional)

Set `remote_ui_enabled: true` in add-on config to access your HA dashboard from anywhere.

## Edge Features

| Feature | Description |
|---------|-------------|
| **SYNC caching** | Device list cached 5 min — faster responses |
| **Offline fallback** | Returns cached state when HA unreachable |
| **Request logging** | Full JSON audit trail of all requests |
| **Rate limiting** | nginx + Python rate limiting — abuse protection |
| **Remote UI toggle** | Enable/disable dashboard access from add-on config |

## Costs

| Resource | Free Tier | Typical Use |
|----------|-----------|-------------|
| Requests | 2M/month | ~50K |
| CPU | 180K vCPU-sec | ~10K |
| Memory | 360K GiB-sec | ~50K |

**Expected: $0/month**

## Architecture

```
ha-edge/
├── gcp-tunnel-client/     # HA Add-on (client)
│   ├── webapp/            # Setup wizard UI
│   ├── run.sh             # Tunnel + HA config
│   └── nginx.conf         # HTTP→HTTPS proxy
├── cloud-run/             # Edge server
│   ├── edge_proxy.py      # Bouncer + Butler
│   ├── nginx.conf         # Routing + OAuth fixes
│   └── static/            # Privacy policy, Local SDK
└── .github/workflows/     # Builds server image
```

## Health & Monitoring

```bash
# Add-on health
curl http://homeassistant.local:8099/health

# Edge proxy stats
curl https://YOUR-URL/edge/stats

# Clear caches
curl -X POST -u hauser:PASS https://YOUR-URL/edge/cache/clear
```

Dashboard sensors are auto-created:
- `sensor.ha_edge_status`
- `binary_sensor.ha_edge_connected`
- `binary_sensor.ha_edge_report_state`

## Local Fulfillment (Google)

For faster Google Assistant responses, enable Local Home SDK:

1. In [Google Home Developer Console](https://console.home.google.com), enable **Local Home SDK**
2. Enter: `https://YOUR-URL/local-sdk/app.js`
3. Add mDNS: `_home-assistant._tcp.local`
4. Say "OK Google, sync my devices"

## Alternatives

### Nabu Casa ($6.50/mo)
Zero setup, supports everything. If you value your time, this is the answer. **And it funds Home Assistant development.**

### Matter/Matterbridge (100% Local)
If you have Matter-compatible devices and want 100% local control.

---

*Home Assistant is built by amazing people. If this saves you money, consider [supporting them](https://www.nabucasa.com/).*

## License

MIT
