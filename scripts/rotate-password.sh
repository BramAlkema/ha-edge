#!/bin/bash
# Rotate tunnel password - updates Cloud Run secret and outputs new password for HA
set -e

# Configuration
PROJECT_ID="${GCP_PROJECT_ID:-ha-tunnel-439702}"
SERVICE_NAME="${SERVICE_NAME:-ha-tunnel}"
REGION="${REGION:-us-central1}"
SECRET_NAME="ha-tunnel-auth"

echo "=== GCP Tunnel Password Rotation ==="
echo ""

# Generate new password
NEW_PASS=$(openssl rand -base64 24)
echo "Generated new password"

# Add new secret version
echo "Updating secret..."
echo -n "hauser:${NEW_PASS}" | gcloud secrets versions add "$SECRET_NAME" \
    --project="$PROJECT_ID" \
    --data-file=-

# Redeploy to pick up new secret version
echo "Redeploying Cloud Run service..."
gcloud run services update "$SERVICE_NAME" \
    --project="$PROJECT_ID" \
    --region="$REGION" \
    --update-secrets="AUTH=${SECRET_NAME}:latest"

echo ""
echo "=== Done ==="
echo ""
echo "Update your HA add-on configuration:"
echo ""
echo "  auth_pass: ${NEW_PASS}"
echo ""
echo "Then restart the add-on."
