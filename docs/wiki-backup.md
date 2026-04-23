# Wiki + SQLite Backup via GitHub

Each tenant's wiki is version-controlled in a private GitHub repo under the `chiefpa-tenant-data` org. Every AI-driven wiki write is a commit; nightly SQLite dumps get committed alongside. Restore is `git checkout <sha>` + reload the SQL dump.

This doc covers initial setup, token rotation, tenant onboarding, and restore procedures.

---

## Architecture

```
┌─────────────────────────┐     ┌──────────────────────────┐
│ crm-<tenant> container  │     │ GitHub org               │
│                         │     │ chiefpa-tenant-data      │
│  /app/wiki (git init)   │────▶│                          │
│  /app/data/crm.db       │     │  <tenant>-wiki.git       │
│                         │     │    ├─ wiki/**            │
│  backup_sync.py         │     │    └─ .db-dumps/         │
└─────────────────────────┘     │        crm-<date>.sql    │
                                └──────────────────────────┘
```

- **One repo per tenant**, named `<tenant-slug>-wiki` (e.g. `hvac-wiki`)
- **Commits from the container** use the `chiefpa-bot` identity
- **Auth:** fine-grained PAT scoped to the org, injected via `GITHUB_BACKUP_TOKEN` env

---

## What gets committed when

| Event | Commit |
|-------|--------|
| Container boot | Initial snapshot if the repo is brand-new; nothing otherwise |
| `accept_approval` (in-window send completes) | `AI: accept: <channel> reply to <sender>` — any wiki changes from POST_SEND |
| `mark_done` (escape-hatch manual send closed) | `AI: done: <channel> reply to <sender>` — same |
| Nightly at 04:XX UTC (staggered per tenant) | `nightly: SQLite dump <date>` with the day's `.db-dumps/crm-<date>.sql` |

Commits that would be empty are no-ops. Pushes that fail are logged and retried on the next commit.

---

## One-time setup (already done, documented for future)

### GitHub side

1. Create the org (once): <https://github.com/organizations/new> → Free tier is fine.
2. Optional: create a bot account (`chiefpa-bot`) and add it as an Org member so commits attribute to the bot, not a human account.
3. Create a **fine-grained PAT** with the bot account (or your admin account):
   - Resource owner: **the org** (not your user)
   - Repository access: **All repositories** (the token covers future tenant repos)
   - Permissions:
     - Administration: Read and write (needed to create new tenant repos at provision time)
     - Contents: Read and write (needed for pushes)
     - Metadata: Read (auto)
   - Expiration: 1 year max — rotate before
4. Copy the `github_pat_...` value. You cannot see it again.

### Container side

The per-tenant `docker-compose.yml` needs three env vars:

```yaml
    environment:
      - GITHUB_BACKUP_ORG=chiefpa-tenant-data
      - GITHUB_BACKUP_TOKEN=github_pat_xxx
      - GITHUB_BACKUP_USER=chiefpa-bot
```

`provision.sh` reads these from host env vars and substitutes them into the generated compose. For existing tenants, edit the compose directly.

---

## Onboarding a new tenant

After `docker/provision.sh` creates the tenant directory and compose file:

1. Confirm the three `GITHUB_BACKUP_*` env vars are present in the generated compose (they're added automatically if the host env has them).
2. Start the tenant: `docker compose up -d` — the startup hook (`backup_sync.ensure_setup`) will:
   - Hit the GitHub API to create `chiefpa-tenant-data/<slug>-wiki` as a private repo (or confirm it exists)
   - Run `git init` in `wiki/`, set remote, set commit identity
   - Make an initial commit of the existing wiki and push
3. Verify: `docker logs crm-<slug> | grep backup_sync` should show `startup setup: ok`.
4. Confirm from GitHub: the repo is visible under the org with one "initial" commit.

Token doesn't need a per-tenant value — same token works for every tenant in the org.

---

## Token rotation

Do this annually (PAT max expiration is 1 year) or immediately if you suspect the token leaked.

1. In GitHub settings, generate a new fine-grained PAT with the same scopes.
2. Don't revoke the old one yet.
3. On the host:
   ```bash
   NEW_TOKEN="github_pat_new_value"
   for slug in hvac chiropractor insurance santhi; do
     sed -i "s|GITHUB_BACKUP_TOKEN=.*|GITHUB_BACKUP_TOKEN=$NEW_TOKEN|" \
       /home/claude/tenants/$slug/docker-compose.yml
     cd /home/claude/tenants/$slug && sudo docker compose up -d crm
   done
   ```
4. Watch logs on at least one tenant to confirm the new token works: `docker logs -f crm-hvac`. You'll see `backup_sync startup setup: ok` on restart.
5. **Only after confirmed working**: revoke the old token in GitHub settings.

Never commit the PAT to git. It lives only in per-tenant docker-compose.yml files (which should be outside any tracked repo — our tenants live under `/home/claude/tenants/` which is not in the ai-pa-crm repo).

---

## Restore procedures

### Scenario 1: Owner asks to revert a specific AI edit

1. Find the commit SHA via `git log` or the GitHub web UI.
2. Revert just that commit without touching subsequent history:
   ```bash
   sudo docker exec crm-<slug> git -C /app/wiki revert <sha> --no-edit
   sudo docker exec crm-<slug> git -C /app/wiki push origin main
   ```
3. The revert itself is a new commit, preserving full audit trail.

### Scenario 2: Full wiki rollback to a known-good state

1. Find the target commit SHA.
2. Inside the container:
   ```bash
   sudo docker exec crm-<slug> bash -c '
     cd /app/wiki
     git fetch origin
     git reset --hard <sha>
     git push --force-with-lease origin main
   '
   ```
3. Force-push *is* destructive — all commits after `<sha>` are lost from GitHub. Alternative: use `revert` over a range if you want to preserve history.

### Scenario 3: SQLite rollback

1. Pick a `.db-dumps/crm-<date>.sql` file from the repo.
2. Stop the container: `sudo docker compose stop crm`
3. Restore:
   ```bash
   cd /home/claude/tenants/<slug>
   cp data/crm.db data/crm.db.bak-$(date +%s)  # safety copy
   rm data/crm.db
   sqlite3 data/crm.db < wiki/.db-dumps/crm-<date>.sql
   sudo docker compose start crm
   ```
4. Verify via dashboard that data (approvals, calendar, channel connections) looks right.

### Scenario 4: Total loss — tenant container + volume gone

1. Re-provision the tenant: `docker/provision.sh <slug> <port>`
2. Instead of starting empty, clone the backup into the newly-created wiki dir before first boot:
   ```bash
   cd /home/claude/tenants/<slug>
   rm -rf wiki
   git clone https://x-access-token:$TOKEN@github.com/chiefpa-tenant-data/<slug>-wiki.git wiki
   ```
3. Restore the most recent SQLite dump as in Scenario 3.
4. `sudo docker compose up -d`.

---

## What isn't backed up

- **Docker volumes other than `wiki/` and `data/crm.db`** — the `whatsapp-sidecar` session credentials (under `data/whatsapp/`) are NOT in the repo. Losing them just means the tenant needs to rescan the QR — not the end of the world.
- **Container logs** — out of scope. If debugging needs access to historical logs, configure docker log rotation separately.
- **`config.json`** — not backed up, but it's static and lives in the tenant directory. A host-level backup of `/home/claude/tenants/` handles this.

---

## Monitoring + failure signals

- Every startup prints `[backup_sync] startup setup: ok|skipped|failed`. Grep logs periodically.
- If a push fails (e.g. GitHub outage), the commit stays local. Next successful commit attempt will push both.
- Nightly backup failures log `[backup_sync] nightly error (non-fatal): ...` but don't crash the container.
- Worth setting up a GitHub Actions workflow on each backup repo that alerts if no commit has landed in N hours — defer for later.

---

## Security notes

- **Token is a high-value secret.** It can create/modify/delete any repo in the org. Treat it like a database password.
- **The repos themselves contain customer data** — customer names, phone numbers, messages. They're private, but if the org admin account is compromised, all tenant data is exposed. Enable 2FA on the bot account and admin account.
- **Backups are not encrypted at rest** beyond GitHub's default. For higher assurance, consider client-side encryption (`age`, `gpg`) before `git add`. Defer until a tenant specifically requires it for compliance.
- **PDPA / GDPR:** having customer data in GitHub means GitHub is a sub-processor. Include this in any customer data processing agreement.
