FROM python:3.12-slim

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates git procps \
    && rm -rf /var/lib/apt/lists/*

# Non-root user (Claude CLI blocks --dangerously-skip-permissions as root)
RUN useradd -m -s /bin/bash crm

# Claude CLI — copied from host at build time.
COPY docker/claude-cli /usr/local/bin/claude
RUN chmod +x /usr/local/bin/claude

# Python deps
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# App code
COPY web.py bridge.py db.py CLAUDE.md schema.sql config.example.json /app/
COPY channels/ /app/channels/
COPY static/ /app/static/

# Entrypoint
COPY docker/start.sh /app/start.sh
RUN chmod +x /app/start.sh

RUN chown -R crm:crm /app

WORKDIR /app
USER crm

# Volumes (mounted at runtime):
#   /app/config.json    — tenant config
#   /app/wiki/          — tenant wiki data
#   /app/data/          — tenant SQLite DB
#   /home/crm/.claude/  — Claude CLI auth + project cache

EXPOSE 8080

CMD ["/app/start.sh"]
