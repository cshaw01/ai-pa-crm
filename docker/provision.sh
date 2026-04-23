#!/bin/bash
# provision.sh — Create a new CRM tenant
#
# Usage: ./provision.sh <tenant-slug> <port>
# Example: ./provision.sh acme 9100
#
# This creates /home/claude/tenants/<slug>/ with:
#   config.json, wiki/, data/, claude-home/, docker-compose.yml

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
TENANTS_DIR="/home/claude/tenants"

# ── Args ──────────────────────────────────────────────────────────────

if [ $# -lt 2 ]; then
  echo "Usage: $0 <tenant-slug> <port>"
  echo "  slug:  short lowercase name (e.g. acme, bright-dental)"
  echo "  port:  unique external port (e.g. 9100, 9101, ...)"
  echo ""
  echo "Ports in use:"
  for d in "$TENANTS_DIR"/*/docker-compose.yml; do
    if [ -f "$d" ]; then
      grep -oP '"\K\d+(?=:8080")' "$d" | while read p; do
        echo "  $p  $(basename "$(dirname "$d")")"
      done
    fi
  done
  exit 1
fi

SLUG="$1"
PORT="$2"
TENANT_DIR="$TENANTS_DIR/$SLUG"

# ── Validate ──────────────────────────────────────────────────────────

if [ -d "$TENANT_DIR" ]; then
  echo "ERROR: $TENANT_DIR already exists"
  exit 1
fi

if ss -tlnp 2>/dev/null | grep -q ":${PORT} "; then
  echo "ERROR: port $PORT is already in use"
  exit 1
fi

# ── Build image (only once, shared by all tenants) ────────────────────

if ! sudo docker image inspect ai-pa-crm:latest >/dev/null 2>&1; then
  echo "Building ai-pa-crm Docker image..."
  sudo docker build -t ai-pa-crm:latest "$PROJECT_DIR"
else
  echo "Image ai-pa-crm:latest already exists (run 'sudo docker build -t ai-pa-crm:latest $PROJECT_DIR' to rebuild)"
fi

# ── Create tenant directory ───────────────────────────────────────────

echo "Creating tenant: $SLUG (port $PORT)"
mkdir -p "$TENANT_DIR"/{wiki,data,claude-home}

# Config from template
cp "$PROJECT_DIR/config.example.json" "$TENANT_DIR/config.json"

# Patch port in config.json (default to 8080 inside container)
python3 -c "
import json
cfg = json.load(open('$TENANT_DIR/config.json'))
cfg.setdefault('web', {})['port'] = 8080
json.dump(cfg, open('$TENANT_DIR/config.json', 'w'), indent=2)
"

# Generate per-tenant webhook secret (32 hex chars)
WA_SECRET="$(head -c 16 /dev/urandom | xxd -p -c 16)"

# Generate docker-compose.yml from template
sed \
  -e "s/__TENANT__/$SLUG/g" \
  -e "s/__PORT__/$PORT/g" \
  -e "s/__WA_SECRET__/$WA_SECRET/g" \
  "$SCRIPT_DIR/docker-compose.template.yml" \
  > "$TENANT_DIR/docker-compose.yml"

# Ensure whatsapp data subdir exists (volume mount target)
mkdir -p "$TENANT_DIR/data/whatsapp"

# ── Summary ───────────────────────────────────────────────────────────

echo ""
echo "✅ Tenant '$SLUG' provisioned at $TENANT_DIR"
echo ""
echo "Next steps:"
echo ""
echo "  1. Edit config.json with business details + Telegram credentials:"
echo "     nano $TENANT_DIR/config.json"
echo ""
echo "  2. Authenticate Claude CLI in the container:"
echo "     cd $TENANT_DIR && sudo docker compose up -d"
echo "     sudo docker exec -it crm-$SLUG claude"
echo "     (follow the browser auth flow, then Ctrl+C)"
echo ""
echo "  3. Run the wiki + demo data setup (from inside the container):"
echo "     sudo docker exec -it crm-$SLUG claude -p 'set up wiki for this business'"
echo ""
echo "  4. Verify:"
echo "     curl http://localhost:$PORT/api/status"
echo ""
echo "  5. Point Cloudflare subdomain to this server's IP:$PORT"
echo ""
echo "Ports allocated so far:"
for d in "$TENANTS_DIR"/*/docker-compose.yml; do
  if [ -f "$d" ]; then
    grep -oP '"\K\d+(?=:8080")' "$d" | while read p; do
      echo "  $p  $(basename "$(dirname "$d")")"
    done
  fi
done
