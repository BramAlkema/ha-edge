/**
 * GCP Tunnel - Local Home SDK Bundle
 *
 * Enables Google devices to control Home Assistant directly on LAN.
 * Falls back to cloud tunnel if local connection fails.
 *
 * Usage: Upload this URL to Google Home Developer Console:
 *   https://your-tunnel.run.app/static/local-sdk/app.js
 */

const App = smarthome.App;
const Constants = smarthome.Constants;
const DataFlow = smarthome.DataFlow;
const Execute = smarthome.Execute;
const Intents = smarthome.Intents;

const VERSION = "1.0.0";
const HA_CLOUD_VERSION = "2.1.6";

class HomeAssistantApp {
  constructor() {
    this.app = new App(VERSION);
    this.setupHandlers();
  }

  setupHandlers() {
    // IDENTIFY: Discover Home Assistant via mDNS
    this.app
      .onIdentify(this.handleIdentify.bind(this))
      .onExecute(this.handleExecute.bind(this))
      .onQuery(this.handleQuery.bind(this))
      .onReachableDevices(this.handleReachableDevices.bind(this))
      .listen();
  }

  /**
   * IDENTIFY: Called when mDNS discovers _home-assistant._tcp.local
   */
  handleIdentify(request) {
    console.log("[GCP-Tunnel] IDENTIFY request:", JSON.stringify(request));

    const device = request.inputs[0].payload.device;

    if (!device.mdnsScanData) {
      console.error("[GCP-Tunnel] No mDNS data in identify request");
      return Promise.reject(new Error("No mDNS data"));
    }

    const mdnsData = device.mdnsScanData;

    // Verify it's a Home Assistant instance
    if (!mdnsData.serviceName.endsWith("._home-assistant._tcp.local")) {
      console.error("[GCP-Tunnel] Not a Home Assistant mDNS service");
      return Promise.reject(new Error("Not Home Assistant"));
    }

    // Extract info from mDNS TXT records
    const txt = this.parseTxtRecords(mdnsData.txt);
    console.log("[GCP-Tunnel] mDNS TXT records:", JSON.stringify(txt));

    return {
      intent: Intents.IDENTIFY,
      requestId: request.requestId,
      payload: {
        device: {
          id: txt.uuid || device.id,
          isProxy: true,
          isLocalOnly: false,
        },
      },
    };
  }

  /**
   * EXECUTE: Run commands on devices
   */
  async handleExecute(request) {
    console.log("[GCP-Tunnel] EXECUTE request:", JSON.stringify(request));

    const command = request.inputs[0].payload.commands[0];
    const device = command.devices[0];

    try {
      const response = await this.sendToHA(request, device);
      return response;
    } catch (error) {
      console.error("[GCP-Tunnel] EXECUTE failed:", error);
      // Return error response - cloud will retry
      return {
        intent: Intents.EXECUTE,
        requestId: request.requestId,
        payload: {
          commands: [{
            ids: command.devices.map(d => d.id),
            status: "ERROR",
            errorCode: "deviceOffline",
          }],
        },
      };
    }
  }

  /**
   * QUERY: Get device states
   */
  async handleQuery(request) {
    console.log("[GCP-Tunnel] QUERY request:", JSON.stringify(request));

    const devices = request.inputs[0].payload.devices;
    const device = devices[0];

    try {
      const response = await this.sendToHA(request, device);
      return response;
    } catch (error) {
      console.error("[GCP-Tunnel] QUERY failed:", error);
      // Return offline status
      const states = {};
      devices.forEach(d => {
        states[d.id] = { online: false, status: "ERROR", errorCode: "deviceOffline" };
      });
      return {
        intent: Intents.QUERY,
        requestId: request.requestId,
        payload: { devices: states },
      };
    }
  }

  /**
   * REACHABLE_DEVICES: List devices reachable via this hub
   */
  handleReachableDevices(request) {
    console.log("[GCP-Tunnel] REACHABLE_DEVICES request");

    // HA handles this - just acknowledge
    return {
      intent: Intents.REACHABLE_DEVICES,
      requestId: request.requestId,
      payload: {
        devices: [],
      },
    };
  }

  /**
   * Send request to Home Assistant via local webhook
   */
  async sendToHA(request, device) {
    const customData = device.customData;

    if (!customData || !customData.webhookId) {
      throw new Error("No webhook configuration in device customData");
    }

    const httpPort = customData.httpPort || 8123;
    const webhookId = customData.webhookId;

    // Build local URL
    // The device's local address comes from the proxy device info
    const proxyDevice = this.app.getDeviceManager().getProxyDevice();

    if (!proxyDevice) {
      throw new Error("No proxy device available");
    }

    const localUrl = `http://${proxyDevice.proxyAddress}:${httpPort}/api/webhook/${webhookId}`;

    console.log("[GCP-Tunnel] Sending to HA:", localUrl);

    const response = await fetch(localUrl, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "HA-Cloud-Version": HA_CLOUD_VERSION,
      },
      body: JSON.stringify(request),
    });

    if (!response.ok) {
      throw new Error(`HTTP ${response.status}: ${response.statusText}`);
    }

    const data = await response.json();
    console.log("[GCP-Tunnel] HA response:", JSON.stringify(data));

    return data;
  }

  /**
   * Parse mDNS TXT records
   */
  parseTxtRecords(txt) {
    const result = {};
    if (txt && typeof txt === "object") {
      Object.entries(txt).forEach(([key, value]) => {
        result[key] = value;
      });
    }
    return result;
  }
}

// Initialize the app
console.log("[GCP-Tunnel] Local Home SDK v" + VERSION + " loading...");
const haApp = new HomeAssistantApp();
console.log("[GCP-Tunnel] Local Home SDK initialized");
