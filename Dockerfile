FROM python:3.12-slim

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates git procps \
    && rm -rf /var/lib/apt/lists/*

# Claude CLI — copied from host at build time.
# The binary is a single ~230MB ELF executable.
# To update: replace the binary and rebuild the image.
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

WORKDIR /app

# Volumes (mounted at runtime):
#   /app/config.json    — tenant config
#   /app/wiki/          — tenant wiki data
#   /app/data/          — tenant SQLite DB
#   /root/.claude/      — Claude CLI auth + project cache

EXPOSE 8080

CMD ["/app/start.sh"]
