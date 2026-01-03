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

- [ ] **2.2 Health endpoint in add-on**
  - `/health` endpoint for watchdog
  - Expose tunnel status to HA sensors

- [ ] **2.3 Better error messages**
  - Detect common failures (wrong URL, bad auth, HA down)
  - Clear actionable error messages in logs

- [ ] **2.4 Logging improvements**
  - Structured logging
  - Log rotation
  - Debug mode toggle

## Phase 3: Features

- [ ] **3.1 Report state (push updates)**
  - Service account integration
  - Real-time device state sync to Google
  - Reduces latency for status queries

- [ ] **3.2 Entity filtering UI**
  - Add-on web UI to select entities
  - Or use HA's native expose UI
  - Per-entity room assignment

- [ ] **3.3 Auto-update add-on**
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

- [ ] **4.3 HA Dashboard integration**
  - Tunnel status card
  - Connection history
  - Google sync status

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
