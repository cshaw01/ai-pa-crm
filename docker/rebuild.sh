#!/bin/bash
# rebuild.sh — Rebuild the shared Docker image and restart all tenants
#
# Usage: ./rebuild.sh [--restart]
#   --restart  also restart all running tenant containers

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
TENANTS_DIR="/home/claude/tenants"

echo "Building ai-pa-crm:latest from $PROJECT_DIR..."
sudo docker build -t ai-pa-crm:latest "$PROJECT_DIR"
echo "✅ Image rebuilt"

if [ "${1:-}" = "--restart" ]; then
  echo ""
  echo "Restarting all tenant containers..."
  for d in "$TENANTS_DIR"/*/docker-compose.yml; do
    [ -f "$d" ] || continue
    dir="$(dirname "$d")"
    slug="$(basename "$dir")"
    echo "  Restarting $slug..."
    (cd "$dir" && sudo docker compose up -d)
  done
  echo "✅ All tenants restarted"
fi
