#!/bin/bash
#
# GCP Home Assistant Tunnel - Zero-Config Setup
#
# Just run it. No prompts. Outputs exactly what to paste where.
#
set -e

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLOUD_RUN_DIR="$(dirname "$SCRIPT_DIR")/cloud-run"

# Auto-generate everything
PROJECT_ID="${PROJECT_ID:-ha-tunnel-$(date +%s | tail -c 7)}"
REGION="us-central1"
SERVICE_NAME="ha-tunnel"
SECRET_NAME="ha-tunnel-auth"
AUTH_USER="hauser"
AUTH_PASS=$(openssl rand -base64 24)

echo -e "${BLUE}"
echo "╔═══════════════════════════════════════════════════════════════╗"
echo "║          GCP Home Assistant Tunnel - Auto Setup               ║"
echo "╚═══════════════════════════════════════════════════════════════╝"
echo -e "${NC}"

# Check gcloud
if ! command -v gcloud &>/dev/null; then
    echo "Install gcloud first: https://cloud.google.com/sdk/docs/install"
    exit 1
fi

# Ensure logged in
if ! gcloud auth print-access-token &>/dev/null 2>&1; then
    echo "Logging in to Google Cloud..."
    gcloud auth login
fi

echo -e "${YELLOW}Creating project: ${PROJECT_ID}${NC}"

# Create project if it doesn't exist
if ! gcloud projects describe "$PROJECT_ID" &>/dev/null 2>&1; then
    gcloud projects create "$PROJECT_ID" --name="HA Tunnel" 2>/dev/null || true
fi
gcloud config set project "$PROJECT_ID" --quiet

# Link billing
BILLING=$(gcloud billing accounts list --filter="open=true" --format="value(name)" --limit=1 2>/dev/null)
if [ -n "$BILLING" ]; then
    gcloud billing projects link "$PROJECT_ID" --billing-account="$BILLING" 2>/dev/null || true
fi

echo -e "${YELLOW}Enabling APIs...${NC}"
gcloud services enable run.googleapis.com secretmanager.googleapis.com --quiet

echo -e "${YELLOW}Creating secret...${NC}"
if gcloud secrets describe "$SECRET_NAME" &>/dev/null 2>&1; then
    echo -n "${AUTH_USER}:${AUTH_PASS}" | gcloud secrets versions add "$SECRET_NAME" --data-file=- --quiet
else
    echo -n "${AUTH_USER}:${AUTH_PASS}" | gcloud secrets create "$SECRET_NAME" --data-file=- --quiet
fi

# Grant access to Cloud Run SA
PROJECT_NUM=$(gcloud projects describe "$PROJECT_ID" --format="value(projectNumber)")
gcloud secrets add-iam-policy-binding "$SECRET_NAME" \
    --member="serviceAccount:${PROJECT_NUM}-compute@developer.gserviceaccount.com" \
    --role="roles/secretmanager.secretAccessor" --quiet >/dev/null 2>&1 || true

echo -e "${YELLOW}Deploying Cloud Run (this takes ~2 minutes)...${NC}"
gcloud run deploy "$SERVICE_NAME" \
    --source="$CLOUD_RUN_DIR" \
    --region="$REGION" \
    --allow-unauthenticated \
    --set-secrets="AUTH=${SECRET_NAME}:latest" \
    --timeout=3600 \
    --min-instances=0 \
    --max-instances=1 \
    --memory=256Mi \
    --quiet

SERVICE_URL=$(gcloud run services describe "$SERVICE_NAME" --region="$REGION" --format="value(status.url)")

echo ""
echo -e "${GREEN}╔═══════════════════════════════════════════════════════════════╗"
echo -e "║                      SETUP COMPLETE                            ║"
echo -e "╚═══════════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "${CYAN}═══ STEP 1: HA Add-on Configuration ═══${NC}"
echo ""
echo -e "Paste into GCP Tunnel Client add-on settings:"
echo ""
echo -e "${YELLOW}server_url:${NC} ${SERVICE_URL}"
echo -e "${YELLOW}auth_user:${NC} ${AUTH_USER}"
echo -e "${YELLOW}auth_pass:${NC} ${AUTH_PASS}"
echo -e "${YELLOW}google_project_id:${NC} ${PROJECT_ID}"
echo ""
echo -e "${CYAN}═══ STEP 2: Google Actions Console ═══${NC}"
echo ""
echo "1. Go to: https://console.actions.google.com"
echo "2. New Project → Select '${PROJECT_ID}'"
echo "3. Smart Home → Start Building"
echo "4. Actions → Add your first action → Add Action(s)"
echo ""
echo -e "   Fulfillment URL:"
echo -e "   ${YELLOW}${SERVICE_URL}/api/google_assistant${NC}"
echo ""
echo "5. Account Linking → Add:"
echo ""
echo -e "   Client ID:"
echo -e "   ${YELLOW}https://oauth-redirect.googleusercontent.com/r/${PROJECT_ID}${NC}"
echo ""
echo -e "   Client Secret:"
echo -e "   ${YELLOW}anything${NC}"
echo ""
echo -e "   Authorization URL:"
echo -e "   ${YELLOW}${SERVICE_URL}/auth/authorize${NC}"
echo ""
echo -e "   Token URL:"
echo -e "   ${YELLOW}${SERVICE_URL}/auth/token${NC}"
echo ""
echo "6. Test → Simulator → Enable testing"
echo ""
echo -e "${CYAN}═══ STEP 3: Link in Google Home ═══${NC}"
echo ""
echo "Google Home app → + → Set up device → Works with Google"
echo "Search: [test] ${PROJECT_ID}"
echo ""
