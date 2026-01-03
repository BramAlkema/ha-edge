# GCP Tunnel for Home Assistant - Roadmap

## Phase 1: Polish (Quick Wins)

- [ ] **1.1 Better auth page branding**
  - Add HA logo to OAuth authorize page
  - Custom CSS for tunnel auth flow

- [ ] **1.2 Setup script improvements**
  - Single `gcp-ha-setup.sh` that does everything
  - Interactive prompts for project name, region
  - Output clear next steps

- [ ] **1.3 Documentation**
  - Complete README with screenshots
  - Troubleshooting guide
  - Video walkthrough?

## Phase 2: Technical Improvements

- [x] **2.1 Remove socat dependency**
  - ~~Option A: Configure HA to accept HTTP internally~~
  - Option B: nginx SSL termination to HA ✓
  - Simplify add-on architecture

- [x] **2.2 Health endpoint in add-on**
  - `/health` endpoint for monitoring ✓
  - Returns tunnel_connected, proxy_running, setup status

- [x] **2.3 Better error messages**
  - Detect common failures (wrong URL, bad auth, HA down) ✓
  - Clear actionable error messages in logs ✓
  - analyze_error() function with boxed error output

- [x] **2.4 Logging improvements**
  - Structured JSON logging (debug mode) ✓
  - Log rotation (1MB max) ✓
  - Debug mode toggle via log_level config ✓

## Phase 3: Features

- [x] **3.1 Report state (push updates)**
  - Uses HA's built-in service account integration ✓
  - Leverages HA's JWT generation, token refresh, batching ✓
  - Just configure, don't reinvent

- [x] **3.2 Entity filtering UI**
  - Add-on web UI to configure entities ✓
  - Per-entity aliases, custom names ✓
  - Per-entity room assignment ✓
  - Expose/hide toggle per entity ✓

- [x] **3.3 Local fulfillment support**
  - Documentation for enabling local fulfillment ✓
  - mDNS scan configuration instructions ✓
  - Faster response times via LAN ✓

- [x] **3.4 Expanded entity domains**
  - Support for all 22+ HA domains ✓
  - Cameras, alarm panels, lawn mowers, etc. ✓

- [ ] **3.5 Auto-update add-on**
  - Check GitHub releases
  - Notify user of updates
  - One-click update (or auto)

## Phase 4: Advanced

- [ ] **4.1 Custom domain support**
  - Use your own domain instead of `.run.app`
  - Cloud Run domain mapping
  - Or Cloudflare proxy

- [ ] **4.2 Multi-user support**
  - Multiple Google accounts
  - Per-user device filtering
  - Household sharing

- [x] **4.3 HA Dashboard integration**
  - Auto-created sensors via packages ✓
  - sensor.gcp_tunnel_status with attributes ✓
  - binary_sensor.gcp_tunnel_connected ✓
  - Sample Lovelace card in setup UI ✓

## Phase 5: Enterprise/Scale

- [ ] **5.1 Monitoring & alerting**
  - Cloud Monitoring integration
  - Alert on disconnect
  - Usage metrics

- [ ] **5.2 Rate limiting**
  - Protect against abuse
  - Per-client limits

- [ ] **5.3 Audit logging**
  - Log all Google Assistant commands
  - Security audit trail

---

## Completed

- [x] Basic tunnel (chisel + Cloud Run)
- [x] HA add-on with auto-reconnect
- [x] Google Assistant integration
- [x] OAuth state fix (HA bug workaround)
- [x] Auto-configuration via packages
- [x] X-Forwarded header stripping
- [x] socat SSL proxy for internal HTTPS
