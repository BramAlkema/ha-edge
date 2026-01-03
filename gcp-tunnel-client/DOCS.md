# GCP Tunnel Client

Establishes a secure WebSocket tunnel from your Home Assistant to Google Cloud Run, enabling external access without port forwarding.

## Use Cases

- Google Assistant / Google Home integration
- External access to Home Assistant
- No need for DuckDNS, port forwarding, or VPN

## How It Works

```
Internet → Cloud Run (free tier) → WebSocket Tunnel → This Add-on → Home Assistant
```

The add-on runs a [chisel](https://github.com/jpillora/chisel) client that connects to your Cloud Run server and creates a reverse tunnel.

## Configuration

| Option | Description | Default |
|--------|-------------|---------|
| `server_url` | Your Cloud Run URL (https://...) | Required |
| `auth_user` | Username for tunnel auth | `hauser` |
| `auth_pass` | Password for tunnel auth | Required |
| `local_port` | Local HA port to tunnel | `8123` |
| `keepalive` | WebSocket keepalive interval | `25s` |
| `log_level` | Log verbosity | `info` |
| `google_project_id` | Google Cloud project ID (enables auto-config) | Optional |
| `google_secure_devices_pin` | PIN for secure devices (locks, etc.) | Optional |

## Example Configuration

```yaml
server_url: "https://ha-tunnel-xxxxx.us-central1.run.app"
auth_user: "hauser"
auth_pass: "your-secure-password"
local_port: 8123
keepalive: "25s"
log_level: "info"
# Optional: Auto-configure Google Assistant
google_project_id: "your-gcp-project-id"
google_secure_devices_pin: "1234"
```

## Google Assistant Auto-Configuration

When you provide `google_project_id`, the add-on automatically:
1. Creates `/config/packages/gcp_tunnel_google_assistant.yaml`
2. Adds `packages: !include_dir_named packages` to your `configuration.yaml`
3. Restarts Home Assistant Core to apply changes

**Fully automatic** - just set the project ID and restart the add-on.

## Setup

1. Deploy the Cloud Run server (see main repository README)
2. Install this add-on
3. Configure with your Cloud Run URL and credentials
4. Start the add-on
5. Check logs to confirm connection

## Logs

The add-on logs connection status. Look for:
- `Connected` - Tunnel is active
- `Connecting to...` - Attempting connection
- `Reconnecting in Xs...` - Connection lost, will retry

## Troubleshooting

### Connection keeps dropping
- Check your internet connection
- Verify Cloud Run service is running
- Cloud Run has 60-minute timeout - reconnection is automatic

### Authentication failed
- Verify `auth_user` and `auth_pass` match Cloud Run secret
- Check Cloud Run logs for auth errors

### Can't reach Home Assistant externally
- Ensure `local_port` matches your HA port (usually 8123)
- Check HA is accessible locally first
