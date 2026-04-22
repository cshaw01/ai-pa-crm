#!/bin/bash
set -e

# Ensure data directory exists for SQLite
mkdir -p /app/data

# Start bridge in background (Telegram polling)
python3 /app/bridge.py &
BRIDGE_PID=$!

# Start web server in foreground
python3 /app/web.py &
WEB_PID=$!

# If either process exits, stop the other and exit
trap "kill $BRIDGE_PID $WEB_PID 2>/dev/null; exit" SIGTERM SIGINT

wait -n $BRIDGE_PID $WEB_PID
EXIT_CODE=$?

# One process died — kill the other
kill $BRIDGE_PID $WEB_PID 2>/dev/null
exit $EXIT_CODE
