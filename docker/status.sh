#!/bin/bash
# status.sh — Show status of all CRM tenants

TENANTS_DIR="/home/claude/tenants"

printf "%-20s %-8s %-10s %-15s %s\n" "TENANT" "PORT" "STATUS" "MEMORY" "UPTIME"
printf "%-20s %-8s %-10s %-15s %s\n" "------" "----" "------" "------" "------"

for d in "$TENANTS_DIR"/*/docker-compose.yml; do
  [ -f "$d" ] || continue
  dir="$(dirname "$d")"
  slug="$(basename "$dir")"
  port=$(grep -oP '"\K\d+(?=:8080")' "$d" 2>/dev/null || echo "?")

  info=$(sudo docker inspect "crm-$slug" --format '{{.State.Status}} {{.State.StartedAt}}' 2>/dev/null)
  if [ -z "$info" ]; then
    printf "%-20s %-8s %-10s %-15s %s\n" "$slug" "$port" "not found" "-" "-"
    continue
  fi

  status=$(echo "$info" | awk '{print $1}')
  mem=$(sudo docker stats --no-stream --format '{{.MemUsage}}' "crm-$slug" 2>/dev/null | awk -F/ '{print $1}' || echo "-")
  uptime=$(sudo docker inspect "crm-$slug" --format '{{.State.StartedAt}}' 2>/dev/null | cut -dT -f1 || echo "-")

  printf "%-20s %-8s %-10s %-15s %s\n" "$slug" "$port" "$status" "$mem" "since $uptime"
done
