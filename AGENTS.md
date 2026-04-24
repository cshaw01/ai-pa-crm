# AI-PA CRM — Engineer / Agent Instructions

Notes for future engineers and AI coding agents working on this repo. The product-facing AI contract that runs on every customer message lives in `CLAUDE.md`, not here — don't put engineering meta-content there.

## Project shape

Multi-tenant AI-powered CRM. Each tenant runs as an isolated FastAPI + SQLite container behind Traefik + Cloudflare, with a shared Baileys sidecar for unofficial WhatsApp and Meta Graph for Messenger/Instagram. Each tenant owns a private GitHub-backed wiki repo where Claude reads and writes.

```
web.py            # FastAPI app: routes, inbox, approvals, Meta/WhatsApp send paths
db.py             # SQLite schema + helpers (per-tenant DB at data/crm.db)
bridge.py         # Webhook dispatch to the AI (calls claude CLI with CLAUDE.md)
response_patterns.py  # Auto-approval pattern engine (promotion state + stats)
backup_sync.py    # GitHub-backed wiki sync (per-tenant repos)
CLAUDE.md         # AI product contract — what the AI does per message type
static/           # SPA (vanilla JS + Tailwind CDN v4)
docker/           # Per-tenant compose template, provision scripts, Traefik config
wiki/             # Per-tenant knowledge base (markdown, git-backed)
docs/
  plans/          # Forward-looking plan docs per feature
  solutions/      # Retrospective learnings (see below)
  deferred-work.md  # Intentionally deferred items with rationale
```

## Documented solutions

`docs/solutions/` — retrospective learnings and documented solutions to past problems (bugs, architecture patterns, design patterns, conventions, workflow practices). Organised by category subdirectory with YAML frontmatter including `module`, `tags`, `problem_type`, `component`. Relevant when implementing or debugging in documented areas — the knowledge compounds: first time a problem is solved is research, next time is a quick lookup.

Add new entries via `/ce-compound` after shipping something non-trivial that future-you will want to remember. Refresh stale entries via `/ce-compound-refresh` when code evolves.

## Running locally

One tenant at a time. Provisioning scripts live in `docker/`. Each tenant gets its own Fernet encryption key, GitHub backup repo, and gateway secret injected by Traefik.

See `docs/wiki-backup.md` for the GitHub-backed backup architecture and onboarding steps.
