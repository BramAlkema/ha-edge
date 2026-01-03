#!/usr/bin/env python3
"""
GCP Tunnel Auto-Setup Web UI

Uses service account authentication - fully self-contained in user's project.
"""

import os
import json
import secrets
import time
from pathlib import Path

from flask import Flask, render_template, request, jsonify
import requests
from google.oauth2 import service_account
from google.auth.transport.requests import Request

app = Flask(__name__)
app.secret_key = secrets.token_hex(32)

# Paths
DATA_DIR = Path("/data")
SA_KEY_FILE = DATA_DIR / "service_account.json"
SETUP_FILE = DATA_DIR / "setup_state.json"

# Pre-built tunnel server image
TUNNEL_IMAGE = "ghcr.io/bramalkema/ha-edge/server:latest"

# Required scopes
SCOPES = ["https://www.googleapis.com/auth/cloud-platform"]


def get_ingress_path():
    """Get the ingress base path from environment."""
    return os.environ.get("INGRESS_PATH", "")


def generate_project_name():
    """Generate a unique project name."""
    suffix = secrets.token_hex(3)
    return f"ha-tunnel-{suffix}"


def generate_password():
    """Generate a secure password."""
    return secrets.token_urlsafe(24)


def get_setup_state():
    """Load setup state from file."""
    if SETUP_FILE.exists():
        return json.loads(SETUP_FILE.read_text())
    return {"step": "start", "project_id": None, "password": None}


def save_setup_state(state):
    """Save setup state to file."""
    DATA_DIR.mkdir(exist_ok=True)
    SETUP_FILE.write_text(json.dumps(state, indent=2))


def get_credentials():
    """Load service account credentials."""
    if not SA_KEY_FILE.exists():
        return None

    try:
        creds = service_account.Credentials.from_service_account_file(
            str(SA_KEY_FILE), scopes=SCOPES
        )
        return creds
    except Exception as e:
        print(f"Error loading credentials: {e}")
        return None


def get_access_token():
    """Get a valid access token."""
    creds = get_credentials()
    if not creds:
        return None

    # Refresh if needed
    if not creds.valid:
        creds.refresh(Request())

    return creds.token


def gcp_api(method, url, **kwargs):
    """Make an authenticated GCP API call."""
    token = get_access_token()
    if not token:
        return None

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    resp = requests.request(method, url, headers=headers, **kwargs)
    return resp


@app.route("/")
def index():
    """Main page - shows setup wizard or status."""
    state = get_setup_state()
    has_key = SA_KEY_FILE.exists()

    # Get project ID from service account if available
    project_id = None
    if has_key:
        try:
            sa_data = json.loads(SA_KEY_FILE.read_text())
            project_id = sa_data.get("project_id")
        except:
            pass

    return render_template("index.html",
                         state=state,
                         has_key=has_key,
                         project_id=project_id,
                         ingress_path=get_ingress_path())


@app.route("/entities")
def entities_page():
    """Entity configuration page."""
    return render_template("entities.html", ingress_path=get_ingress_path())


@app.route("/api/upload-key", methods=["POST"])
def upload_key():
    """Upload service account key."""
    try:
        # Handle both file upload and JSON paste
        if request.files.get("keyfile"):
            key_data = request.files["keyfile"].read().decode("utf-8")
        elif request.json and request.json.get("key"):
            key_data = request.json["key"]
        else:
            return jsonify({"error": "No key provided"}), 400

        # Validate JSON
        try:
            key_json = json.loads(key_data)
        except json.JSONDecodeError:
            return jsonify({"error": "Invalid JSON"}), 400

        # Check required fields
        required = ["type", "project_id", "private_key", "client_email"]
        missing = [f for f in required if f not in key_json]
        if missing:
            return jsonify({"error": f"Missing fields: {missing}"}), 400

        if key_json.get("type") != "service_account":
            return jsonify({"error": "Not a service account key"}), 400

        # Save key
        DATA_DIR.mkdir(exist_ok=True)
        SA_KEY_FILE.write_text(json.dumps(key_json, indent=2))
        SA_KEY_FILE.chmod(0o600)

        # Update state
        state = get_setup_state()
        state["step"] = "key_uploaded"
        state["project_id"] = key_json["project_id"]
        save_setup_state(state)

        return jsonify({
            "success": True,
            "project_id": key_json["project_id"]
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/deploy", methods=["POST"])
def run_deploy():
    """Deploy Cloud Run using service account."""
    if not SA_KEY_FILE.exists():
        return jsonify({"error": "No service account key uploaded"}), 400

    state = get_setup_state()

    try:
        sa_data = json.loads(SA_KEY_FILE.read_text())
        project_id = sa_data["project_id"]
    except Exception as e:
        return jsonify({"error": f"Invalid key file: {e}"}), 400

    # Generate password
    password = state.get("password") or generate_password()
    state["password"] = password
    state["project_id"] = project_id

    try:
        # Step 1: Enable APIs
        state["step"] = "enabling_apis"
        save_setup_state(state)

        apis = ["run.googleapis.com", "cloudbuild.googleapis.com"]
        for api in apis:
            resp = gcp_api("POST",
                f"https://serviceusage.googleapis.com/v1/projects/{project_id}/services/{api}:enable")
            # Ignore errors - might already be enabled or just need time

        # Wait for APIs to propagate
        time.sleep(5)

        # Step 2: Deploy Cloud Run
        state["step"] = "deploying"
        save_setup_state(state)

        region = "us-central1"
        service_name = "ha-tunnel"

        # Use the v1 API for Cloud Run
        service_config = {
            "apiVersion": "serving.knative.dev/v1",
            "kind": "Service",
            "metadata": {
                "name": service_name,
                "namespace": project_id,
                "annotations": {
                    "run.googleapis.com/ingress": "all",
                    "run.googleapis.com/launch-stage": "BETA"
                }
            },
            "spec": {
                "template": {
                    "metadata": {
                        "annotations": {
                            "autoscaling.knative.dev/minScale": "0",
                            "autoscaling.knative.dev/maxScale": "1",
                            "run.googleapis.com/cpu-throttling": "true"
                        }
                    },
                    "spec": {
                        "containerConcurrency": 80,
                        "timeoutSeconds": 3600,
                        "containers": [{
                            "image": TUNNEL_IMAGE,
                            "env": [
                                {"name": "AUTH", "value": f"hauser:{password}"}
                            ],
                            "resources": {
                                "limits": {
                                    "cpu": "1",
                                    "memory": "256Mi"
                                }
                            },
                            "ports": [{"containerPort": 8080}]
                        }]
                    }
                }
            }
        }

        # Try to create or replace the service
        resp = gcp_api("POST",
            f"https://{region}-run.googleapis.com/apis/serving.knative.dev/v1/namespaces/{project_id}/services",
            json=service_config)

        if resp and resp.status_code not in [200, 201, 409]:
            # Try update if create fails
            resp = gcp_api("PUT",
                f"https://{region}-run.googleapis.com/apis/serving.knative.dev/v1/namespaces/{project_id}/services/{service_name}",
                json=service_config)

        if not resp or resp.status_code not in [200, 201]:
            error_msg = resp.text if resp else "No response"
            return jsonify({"error": f"Deploy failed: {error_msg}"}), 500

        # Wait for deployment
        time.sleep(10)

        # Step 3: Make service public
        state["step"] = "configuring"
        save_setup_state(state)

        iam_policy = {
            "policy": {
                "bindings": [{
                    "role": "roles/run.invoker",
                    "members": ["allUsers"]
                }]
            }
        }

        gcp_api("POST",
            f"https://run.googleapis.com/v1/projects/{project_id}/locations/{region}/services/{service_name}:setIamPolicy",
            json=iam_policy)

        # Step 4: Get service URL
        resp = gcp_api("GET",
            f"https://run.googleapis.com/v1/projects/{project_id}/locations/{region}/services/{service_name}")

        if resp and resp.status_code == 200:
            service_data = resp.json()
            service_url = service_data.get("status", {}).get("url", "")
            state["server_url"] = service_url
        else:
            # Construct URL from convention
            state["server_url"] = f"https://{service_name}-{project_id}.{region}.run.app"

        state["step"] = "complete"
        save_setup_state(state)

        # Update add-on configuration
        update_addon_config(state)

        return jsonify({
            "success": True,
            "project_id": project_id,
            "server_url": state.get("server_url", ""),
            "password": password
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


def update_addon_config(state):
    """Update the add-on's configuration via Supervisor API."""
    supervisor_token = os.environ.get("SUPERVISOR_TOKEN")
    if not supervisor_token:
        return

    config = {
        "server_url": state.get("server_url", ""),
        "auth_user": "hauser",
        "auth_pass": state.get("password", ""),
        "google_project_id": state.get("project_id", ""),
        "local_port": 8123,
        "keepalive": "25s",
        "log_level": "info",
        "google_secure_devices_pin": ""
    }

    try:
        resp = requests.post(
            "http://supervisor/addons/self/options",
            headers={"Authorization": f"Bearer {supervisor_token}"},
            json={"options": config}
        )

        if resp.status_code == 200:
            # Restart add-on to apply config
            requests.post(
                "http://supervisor/addons/self/restart",
                headers={"Authorization": f"Bearer {supervisor_token}"}
            )
    except Exception as e:
        print(f"Failed to update config: {e}")


@app.route("/api/status")
def get_status():
    """Get current setup status."""
    state = get_setup_state()
    has_key = SA_KEY_FILE.exists()

    project_id = None
    if has_key:
        try:
            sa_data = json.loads(SA_KEY_FILE.read_text())
            project_id = sa_data.get("project_id")
        except:
            pass

    return jsonify({
        "has_key": has_key,
        "project_id": project_id,
        "step": state.get("step", "start"),
        "server_url": state.get("server_url"),
        "has_password": state.get("password") is not None
    })


ENTITY_CONFIG_FILE = DATA_DIR / "entity_config.json"


def get_entity_config():
    """Load entity configuration."""
    if ENTITY_CONFIG_FILE.exists():
        return json.loads(ENTITY_CONFIG_FILE.read_text())
    return {}


def save_entity_config(config):
    """Save entity configuration."""
    DATA_DIR.mkdir(exist_ok=True)
    ENTITY_CONFIG_FILE.write_text(json.dumps(config, indent=2))


@app.route("/api/entities")
def get_entities():
    """Get list of HA entities that can be exposed to Google Assistant."""
    supervisor_token = os.environ.get("SUPERVISOR_TOKEN")
    if not supervisor_token:
        return jsonify({"error": "Not running in HA environment"}), 500

    # Domains we expose to Google Assistant
    exposed_domains = [
        "light", "switch", "input_boolean", "climate", "fan", "humidifier",
        "water_heater", "cover", "valve", "lock", "alarm_control_panel",
        "media_player", "sensor", "binary_sensor", "scene", "script",
        "input_select", "select", "button", "input_button", "vacuum",
        "lawn_mower", "camera"
    ]

    try:
        resp = requests.get(
            "http://supervisor/core/api/states",
            headers={"Authorization": f"Bearer {supervisor_token}"}
        )
        if resp.status_code != 200:
            return jsonify({"error": "Failed to fetch entities"}), 500

        all_states = resp.json()
        entity_config = get_entity_config()

        entities = []
        for state in all_states:
            entity_id = state.get("entity_id", "")
            domain = entity_id.split(".")[0] if "." in entity_id else ""

            if domain in exposed_domains:
                config = entity_config.get(entity_id, {})
                entities.append({
                    "entity_id": entity_id,
                    "friendly_name": state.get("attributes", {}).get("friendly_name", entity_id),
                    "domain": domain,
                    "state": state.get("state"),
                    "expose": config.get("expose", True),
                    "name": config.get("name"),
                    "aliases": config.get("aliases", []),
                    "room": config.get("room")
                })

        # Sort by domain then name
        entities.sort(key=lambda e: (e["domain"], e["friendly_name"]))
        return jsonify({"entities": entities})

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/entities", methods=["POST"])
def save_entities():
    """Save entity configuration."""
    try:
        data = request.json
        if not data or "entities" not in data:
            return jsonify({"error": "No entities provided"}), 400

        # Convert list to dict keyed by entity_id
        config = {}
        for entity in data["entities"]:
            entity_id = entity.get("entity_id")
            if entity_id:
                config[entity_id] = {
                    "expose": entity.get("expose", True),
                    "name": entity.get("name"),
                    "aliases": entity.get("aliases", []),
                    "room": entity.get("room")
                }

        save_entity_config(config)

        # Regenerate the google_assistant package with entity_config
        regenerate_ga_package(config)

        return jsonify({"success": True, "count": len(config)})

    except Exception as e:
        return jsonify({"error": str(e)}), 500


def regenerate_ga_package(entity_config):
    """Regenerate google_assistant package with entity config."""
    state = get_setup_state()
    project_id = state.get("project_id")
    if not project_id:
        return

    package_file = Path("/config/packages/gcp_tunnel_google_assistant.yaml")

    # Build entity_config section
    entity_config_yaml = ""
    for entity_id, config in entity_config.items():
        if not config.get("expose", True) or config.get("name") or config.get("aliases") or config.get("room"):
            entity_config_yaml += f"    {entity_id}:\n"
            if not config.get("expose", True):
                entity_config_yaml += f"      expose: false\n"
            if config.get("name"):
                entity_config_yaml += f"      name: \"{config['name']}\"\n"
            if config.get("aliases"):
                entity_config_yaml += f"      aliases:\n"
                for alias in config["aliases"]:
                    entity_config_yaml += f"        - \"{alias}\"\n"
            if config.get("room"):
                entity_config_yaml += f"      room: \"{config['room']}\"\n"

    # Write the package file
    content = f"""# Auto-generated by GCP Tunnel Client add-on
# Uses Home Assistant's built-in Google Assistant integration
# https://www.home-assistant.io/integrations/google_assistant/

google_assistant:
  project_id: {project_id}
  expose_by_default: true
  exposed_domains:
    - light
    - switch
    - input_boolean
    - climate
    - fan
    - humidifier
    - water_heater
    - cover
    - valve
    - lock
    - alarm_control_panel
    - media_player
    - sensor
    - binary_sensor
    - scene
    - script
    - input_select
    - select
    - button
    - input_button
    - vacuum
    - lawn_mower
    - camera
    - event
"""

    # Add service account if exists
    if SA_KEY_FILE.exists():
        content += """  service_account: !include ../gcp_tunnel_service_account.json
  report_state: true
"""

    # Add entity_config if any
    if entity_config_yaml:
        content += f"  entity_config:\n{entity_config_yaml}"

    package_file.write_text(content)


@app.route("/api/alexa-script")
def alexa_script():
    """Generate AWS CloudShell script for Alexa Lambda deployment."""
    state = get_setup_state()
    server_url = state.get("server_url", "https://YOUR-TUNNEL-URL.run.app")

    # CloudShell script that creates Lambda proxy
    script = f'''#!/bin/bash
# Alexa Smart Home Lambda Proxy for Home Assistant
# Run this in AWS CloudShell: https://console.aws.amazon.com/cloudshell

set -e

TUNNEL_URL="{server_url}"
FUNCTION_NAME="ha-alexa-proxy"
ROLE_NAME="ha-alexa-lambda-role"
REGION="${{AWS_REGION:-us-east-1}}"

echo "=== Creating Alexa Lambda Proxy ==="
echo "Tunnel URL: $TUNNEL_URL"
echo "Region: $REGION"
echo ""

# Step 1: Create IAM role
echo "Creating IAM role..."
TRUST_POLICY='{{
  "Version": "2012-10-17",
  "Statement": [{{
    "Effect": "Allow",
    "Principal": {{"Service": "lambda.amazonaws.com"}},
    "Action": "sts:AssumeRole"
  }}]
}}'

aws iam create-role \\
  --role-name $ROLE_NAME \\
  --assume-role-policy-document "$TRUST_POLICY" \\
  2>/dev/null || echo "Role exists, continuing..."

# Attach basic execution policy
aws iam attach-role-policy \\
  --role-name $ROLE_NAME \\
  --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole \\
  2>/dev/null || true

# Wait for role to propagate
echo "Waiting for role to propagate..."
sleep 10

# Step 2: Create Lambda function code
echo "Creating Lambda function..."

LAMBDA_CODE='
import json
import urllib.request
import urllib.error
import os

TUNNEL_URL = os.environ.get("TUNNEL_URL", "")

def lambda_handler(event, context):
    """Forward Alexa directive to Home Assistant via tunnel."""
    try:
        url = f"{{TUNNEL_URL}}/api/alexa"
        data = json.dumps(event).encode("utf-8")

        headers = {{
            "Content-Type": "application/json",
        }}

        # Forward authorization if present
        if "directive" in event:
            endpoint = event["directive"].get("endpoint", {{}})
            scope = endpoint.get("scope", {{}})
            token = scope.get("token")
            if token:
                headers["Authorization"] = f"Bearer {{token}}"

        req = urllib.request.Request(url, data=data, headers=headers, method="POST")

        with urllib.request.urlopen(req, timeout=25) as resp:
            return json.loads(resp.read().decode("utf-8"))

    except urllib.error.HTTPError as e:
        print(f"HTTP Error: {{e.code}} {{e.reason}}")
        return {{"error": str(e)}}
    except Exception as e:
        print(f"Error: {{e}}")
        return {{"error": str(e)}}
'

# Write code to temp file
echo "$LAMBDA_CODE" > /tmp/lambda_function.py

# Create zip
cd /tmp
zip -j lambda.zip lambda_function.py

# Get account ID
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
ROLE_ARN="arn:aws:iam::$ACCOUNT_ID:role/$ROLE_NAME"

# Create or update function
aws lambda create-function \\
  --function-name $FUNCTION_NAME \\
  --runtime python3.11 \\
  --role $ROLE_ARN \\
  --handler lambda_function.lambda_handler \\
  --zip-file fileb:///tmp/lambda.zip \\
  --timeout 30 \\
  --memory-size 128 \\
  --environment "Variables={{TUNNEL_URL=$TUNNEL_URL}}" \\
  --region $REGION \\
  2>/dev/null || \\
aws lambda update-function-code \\
  --function-name $FUNCTION_NAME \\
  --zip-file fileb:///tmp/lambda.zip \\
  --region $REGION

# Update environment in case URL changed
aws lambda update-function-configuration \\
  --function-name $FUNCTION_NAME \\
  --environment "Variables={{TUNNEL_URL=$TUNNEL_URL}}" \\
  --region $REGION \\
  2>/dev/null || true

# Step 3: Add Alexa trigger permission
echo "Adding Alexa trigger permission..."
aws lambda add-permission \\
  --function-name $FUNCTION_NAME \\
  --statement-id alexa-smart-home \\
  --action lambda:InvokeFunction \\
  --principal alexa-connectedhome.amazon.com \\
  --region $REGION \\
  2>/dev/null || echo "Permission exists, continuing..."

# Get Lambda ARN
LAMBDA_ARN="arn:aws:lambda:$REGION:$ACCOUNT_ID:function:$FUNCTION_NAME"

echo ""
echo "=========================================="
echo "SUCCESS! Lambda deployed."
echo "=========================================="
echo ""
echo "Lambda ARN (copy this):"
echo "$LAMBDA_ARN"
echo ""
echo "Next steps:"
echo "1. Go to Alexa Developer Console"
echo "2. Create Smart Home Skill"
echo "3. Paste the Lambda ARN above"
echo "4. Configure Account Linking"
echo "=========================================="
'''

    return jsonify({"script": script})


@app.route("/health")
def health():
    """Health endpoint for monitoring and HA sensors."""
    import subprocess

    state = get_setup_state()

    # Check if chisel tunnel is running
    tunnel_connected = False
    try:
        result = subprocess.run(["pgrep", "-x", "chisel"], capture_output=True)
        tunnel_connected = result.returncode == 0
    except:
        pass

    # Check if nginx proxy is running
    proxy_running = False
    try:
        result = subprocess.run(["pgrep", "-x", "nginx"], capture_output=True)
        proxy_running = result.returncode == 0
    except:
        pass

    return jsonify({
        "status": "healthy" if tunnel_connected else "disconnected",
        "tunnel_connected": tunnel_connected,
        "proxy_running": proxy_running,
        "server_url": state.get("server_url"),
        "project_id": state.get("project_id"),
        "report_state_enabled": SA_KEY_FILE.exists(),
        "setup_complete": state.get("step") == "complete"
    })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8099, debug=False)
