#!/bin/bash
# protect-master.sh — Lower OOM score for master processes so the kernel
# kills tenant containers first when memory is tight.
#
# Run once after boot (or add to cron @reboot).
# Tenant containers already have oom_score_adj: 500 in docker-compose.

set -euo pipefail

# Master CRM services (lower = less likely to be killed, range -1000 to 1000)
MASTER_SCORE=-500

for name in "web.py" "bridge.py"; do
  pids=$(pgrep -f "$name" -u claude 2>/dev/null || true)
  for pid in $pids; do
    echo "$MASTER_SCORE" | sudo tee "/proc/$pid/oom_score_adj" > /dev/null
    echo "Protected PID $pid ($name) → oom_score_adj=$MASTER_SCORE"
  done
done

# Also protect the current user's shell and Claude Code sessions
for pid in $(pgrep -u claude bash 2>/dev/null || true); do
  echo "$MASTER_SCORE" | sudo tee "/proc/$pid/oom_score_adj" > /dev/null 2>&1 || true
done

echo ""
echo "Master processes protected (oom_score_adj=$MASTER_SCORE)"
echo "Tenant containers have oom_score_adj=500 (killed first)"
