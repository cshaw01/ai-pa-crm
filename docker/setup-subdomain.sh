#!/bin/bash
# setup-subdomain.sh — Add Traefik route + Cloudflare DNS for a CRM tenant
#
# Usage: ./setup-subdomain.sh <tenant-slug> <subdomain> <port>
# Example: ./setup-subdomain.sh hvac hvac.chungsoonhaw.com 9100
#
# Prerequisites:
#   export CF_API_TOKEN="your-cloudflare-api-token"
#   export CF_ZONE_ID="your-zone-id"
#
# To find your Zone ID:
#   Go to Cloudflare dashboard → your domain → Overview → right sidebar → "Zone ID"
#
# To create an API token:
#   Cloudflare dashboard → My Profile → API Tokens → Create Token
#   Use template "Edit zone DNS" → select your zone → Create

set -euo pipefail

if [ $# -lt 3 ]; then
  echo "Usage: $0 <tenant-slug> <subdomain> <port>"
  echo "Example: $0 hvac hvac.chungsoonhaw.com 9100"
  echo ""
  echo "Required env vars:"
  echo "  CF_API_TOKEN  — Cloudflare API token with DNS edit permission"
  echo "  CF_ZONE_ID    — Cloudflare Zone ID for the domain"
  exit 1
fi

SLUG="$1"
SUBDOMAIN="$2"
PORT="$3"

SERVER_IP="$(curl -sf4 ifconfig.me)"
TRAEFIK_DIR="/data/coolify/proxy/dynamic"

# ── Step 1: Add Traefik route ────────────────────────────────────────

echo "Adding Traefik route: $SUBDOMAIN → localhost:$PORT"

sudo tee "$TRAEFIK_DIR/crm-${SLUG}.yaml" > /dev/null <<EOF
# CRM tenant: $SLUG
http:
  routers:
    crm-${SLUG}-http:
      entryPoints:
        - http
      service: crm-${SLUG}
      rule: Host(\`${SUBDOMAIN}\`)
      middlewares:
        - redirect-to-https
    crm-${SLUG}-https:
      entryPoints:
        - https
      service: crm-${SLUG}
      rule: Host(\`${SUBDOMAIN}\`)
      tls:
        certresolver: letsencrypt
  services:
    crm-${SLUG}:
      loadBalancer:
        servers:
          - url: 'http://host.docker.internal:${PORT}'
EOF

echo "  ✅ Traefik config written to $TRAEFIK_DIR/crm-${SLUG}.yaml"
echo "  Traefik auto-reloads dynamic config — no restart needed."

# ── Step 2: Create Cloudflare DNS record ─────────────────────────────

if [ -z "${CF_API_TOKEN:-}" ] || [ -z "${CF_ZONE_ID:-}" ]; then
  echo ""
  echo "  ⚠️  CF_API_TOKEN or CF_ZONE_ID not set — skipping DNS."
  echo "  Set them and re-run, or create the A record manually:"
  echo "    $SUBDOMAIN → $SERVER_IP (proxied)"
  echo ""
  exit 0
fi

echo ""
echo "Creating Cloudflare DNS: $SUBDOMAIN → $SERVER_IP (proxied)"

# Extract just the subdomain part (e.g. "hvac" from "hvac.chungsoonhaw.com")
RECORD_NAME="$SUBDOMAIN"

# Check if record already exists
EXISTING=$(curl -sf -X GET \
  "https://api.cloudflare.com/client/v4/zones/${CF_ZONE_ID}/dns_records?type=A&name=${RECORD_NAME}" \
  -H "Authorization: Bearer ${CF_API_TOKEN}" \
  -H "Content-Type: application/json" \
  | python3 -c "import json,sys; r=json.load(sys.stdin); print(r['result'][0]['id'] if r.get('result') else '')" 2>/dev/null || echo "")

if [ -n "$EXISTING" ]; then
  # Update existing record
  curl -sf -X PUT \
    "https://api.cloudflare.com/client/v4/zones/${CF_ZONE_ID}/dns_records/${EXISTING}" \
    -H "Authorization: Bearer ${CF_API_TOKEN}" \
    -H "Content-Type: application/json" \
    --data "{
      \"type\": \"A\",
      \"name\": \"${RECORD_NAME}\",
      \"content\": \"${SERVER_IP}\",
      \"ttl\": 1,
      \"proxied\": true
    }" | python3 -c "import json,sys; r=json.load(sys.stdin); print('  ✅ Updated' if r.get('success') else '  ❌ Failed:', json.dumps(r.get('errors','')))"
else
  # Create new record
  curl -sf -X POST \
    "https://api.cloudflare.com/client/v4/zones/${CF_ZONE_ID}/dns_records" \
    -H "Authorization: Bearer ${CF_API_TOKEN}" \
    -H "Content-Type: application/json" \
    --data "{
      \"type\": \"A\",
      \"name\": \"${RECORD_NAME}\",
      \"content\": \"${SERVER_IP}\",
      \"ttl\": 1,
      \"proxied\": true
    }" | python3 -c "import json,sys; r=json.load(sys.stdin); print('  ✅ Created' if r.get('success') else '  ❌ Failed:', json.dumps(r.get('errors','')))"
fi

echo ""
echo "Done. $SUBDOMAIN should be live within ~30 seconds."
echo "  Dashboard: https://$SUBDOMAIN"
