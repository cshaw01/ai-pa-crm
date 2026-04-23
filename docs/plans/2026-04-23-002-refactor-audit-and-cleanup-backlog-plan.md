---
title: "refactor: Audit of shipped features and cleanup backlog"
type: refactor
status: active
date: 2026-04-23
---

# refactor: Audit of shipped features and cleanup backlog

## Overview

The codebase grew quickly over this session — from a Telegram-only CRM bridge to a multi-tenant dashboard with calendar, feedback form, WhatsApp (Baileys), Messenger/Instagram (official Meta API + hybrid send), and a 24h SLA timer. The result works, but several rough edges have accumulated: duplicated code, dead schema, prompt instructions that reference systems we never built, a growing `web.py` that now handles everything, and zero automated tests.

This plan does two jobs in one document:

1. **Audit** — catalog every shipped feature and briefly describe *how* it's implemented, so future work has a map rather than an archaeology project.
2. **Cleanup backlog** — identify the specific parts that would benefit from tidying, prioritised by impact and risk, broken into units that `/ce-work` can pick off selectively (or skip entirely, since this is a backlog, not a committed release).

The audit is the primary deliverable. The cleanup units are scoped so each one lands as a standalone, commit-sized change with clear tests.

---

## Problem Frame

Fast delivery over ~24 hours created a healthy working product with some predictable hygiene debt:

- **`web.py` is 1330 lines** and touches every feature — approvals, AI, calendar, feedback, WhatsApp sidecar proxy, Meta webhook+OAuth+send, contacts, chat. It's one file that grew by accretion.
- **`static/app.js` is 2065 lines**, same pattern. Every feature module lives inline.
- **`CLAUDE.md` contains 4 `psql` invocations against a `messages` table that doesn't exist in our SQLite.** Every AI call spends tokens reading (and attempting) instructions that silently no-op.
- **POST_SEND prompt is built twice, identically**, in `accept_approval` and `mark_done` — anyone changing the format has to update both.
- **The `feedback` table exists in `db.py` but no code writes to it.** The feedback endpoint writes to a markdown file only. Dead migration.
- **There are zero tests**, anywhere. The Meta plan (001) referenced test files that were aspirational.
- **`channels/base.py` defines an abstract channel interface**, but WhatsApp and Meta both bypass it entirely and go through inline HTTP in `web.py`. The abstraction isn't earning its keep.
- **`bridge.py` hard-codes Telegram only** (`# 'whatsapp': WhatsAppChannel,  # future`), even though WhatsApp now ships via a different path. The comment lies.

None of this is blocking — the product works and new tenants can onboard. But unaddressed, every new feature makes the mess slightly worse.

---

## Feature Inventory

This is what's actually shipped, grouped by domain. Not a requirements doc — a map.

### 1. Multi-tenant infrastructure

| Feature | How it works | Key files |
|---------|-------------|-----------|
| Per-tenant Docker container | Single image `ai-pa-crm:latest`, one container per tenant, different port mapping | `Dockerfile`, `docker/docker-compose.template.yml`, `docker/provision.sh` |
| Cloudflare + Traefik subdomain routing | Wildcard `*.chiefpa.com`, per-tenant Traefik dynamic config routes to the tenant's port | `docker/setup-subdomain.sh` |
| Tenant provisioning script | `provision.sh <slug> <port>` generates docker-compose.yml from template, mkdirs data/wiki/claude-home, substitutes secrets | `docker/provision.sh` |
| Per-tenant secret generation | WA_SECRET (webhook shared secret) + Fernet encryption key, generated at provision time, injected via env vars | `docker/provision.sh` |

### 2. Core CRM dashboard

| Feature | How it works | Key files |
|---------|-------------|-----------|
| FastAPI web server | Serves SPA + JSON API on port 8080 | `web.py` |
| Single-file SPA | Tailwind CDN v4 (`type="text/tailwindcss"`), vanilla JS state machine, no framework | `static/index.html`, `static/app.js`, `static/style.css` |
| Claude CLI integration | `call_claude(prompt)` shells out to the Claude CLI with the per-tenant auth dir mounted | `web.py::call_claude` |
| Pending approvals queue | `pending_approvals` table, each row = one message the AI drafted for owner review | `db.py`, `web.py::list_approvals`, `static/app.js::loadApprovals` |
| Approval state machine | `pending → accepted \| rejected`, plus `awaiting_done` midway state for Meta escape-hatch | `db.py`, `web.py::accept_approval` |
| Edit draft (regenerate) | Owner types instructions, we run `[EDIT_DRAFT]` prompt, update the draft | `web.py::edit_approval`, `static/app.js::editDraft` |
| AI analysis on inbound | `_analyse_inbox` runs `[EXTERNAL]` prompt in a background task, updates the approval row | `web.py::_analyse_inbox` |
| Contact records (wiki) | Markdown files under `wiki/<folder>/`, indexed by per-folder `_INDEX.md` tables | `wiki/`, `CLAUDE.md` wiki rules |
| AI contact create/update | POST_SEND prompt instructs Claude to append to interaction log or create a new lead file | `CLAUDE.md::[POST_SEND]`, `web.py::accept_approval` |

### 3. Channels (ways to receive and send messages)

| Channel | Receive path | Send path | Status |
|---------|-------------|-----------|--------|
| Dashboard inbox submit | `POST /api/inbox/submit` | Manual (owner copies draft to clipboard) | Shipped |
| Telegram (legacy) | `bridge.py` polls Telegram Bot API | Same bridge sends via Bot API | Shipped but stale — the product's message flow moved to `web.py` |
| WhatsApp (Baileys, unofficial) | Node sidecar (per tenant) → HMAC-signed webhook → `/api/webhook/whatsapp` | `accept_approval` POSTs `{to, text}` to sidecar `/send` | Shipped |
| Messenger (Meta Graph API) | `POST /api/webhook/meta` (HMAC-signed) | Inside 24h: Graph API `/me/messages`. Outside: clipboard + open Business Suite + "Done" button | Shipped, env-gated |
| Instagram Direct (Meta Graph API) | Same webhook as Messenger, dispatched by `object=='instagram'` | Same hybrid as Messenger, plus `messaging_product='instagram'` | Shipped, env-gated |

### 4. AI assistant behaviors (defined in `CLAUDE.md`)

| Behavior | Trigger | What the AI does |
|----------|---------|------------------|
| INTERNAL query | Owner asks the AI something via the dashboard Chat tab | Read wiki, answer concisely |
| EXTERNAL inbound | Customer messages come in (any channel) | Identify sender, analyse, draft reply |
| EDIT_DRAFT | Owner provides edit instructions | Revise the draft |
| COMPOSE | Owner initiates outbound | Read contact file, draft proactive message |
| POST_SEND | Owner accepted a draft (or clicked Done) | Update wiki interaction log OR create new lead; create calendar events if the conversation implies a scheduled action |

### 5. Calendar

| Feature | How it works | Key files |
|---------|-------------|-----------|
| Week view | Client-side render, day-grouped event cards, colour-coded by type | `static/app.js::renderCalendar` |
| Event CRUD | `calendar_events` table in SQLite | `db.py`, `web.py` `/api/calendar` routes |
| AI event creation | POST_SEND flow tells the AI to insert scheduled actions into `calendar_events` | `CLAUDE.md::Calendar Events` |

### 6. Feedback form

| Feature | How it works | Key files |
|---------|-------------|-----------|
| PM-framework form | Request + workaround + frequency + importance + contact | `static/index.html::#feedbackModal`, `static/app.js::handleFeedbackSubmit` |
| Append to markdown | `/api/feedback` appends to `/app/data/feedback.md` with tenant host header | `web.py::submit_feedback` |

### 7. SLA + 24h window UX

| Feature | How it works | Key files |
|---------|-------------|-----------|
| Countdown badge | Client-side `formatWindowRemaining`, 30s re-render interval, colour-coded by time-left bucket | `static/app.js` |
| Server-side window enforcement | `_meta_window_open` check in `accept_approval` before Meta Graph API send | `web.py` |
| Escape-hatch flow | Client flips to awaiting_done on 409, opens Business Suite tab, Done endpoint closes loop | `web.py::mark_awaiting_done`, `mark_done`, `static/app.js::acceptViaEscapeHatch` |

### 8. Security posture

| Concern | How it's handled |
|---------|-----------------|
| Meta webhook signature | HMAC-SHA256 against raw body (`_verify_meta_signature`), enforced when Meta env vars are set |
| OAuth CSRF | Signed state with 10-minute TTL (`_sign_state` / `_verify_state`) |
| Meta token at rest | Fernet encryption, key in `TENANT_ENCRYPTION_KEY` env var |
| WhatsApp sidecar auth | Per-tenant shared secret in `X-Webhook-Secret` header |
| Token revocation detection | On Meta error codes 190/200, connection row flips to `needs_reconnect` |

---

## Implementation Map

File-level breakdown of where the complexity actually lives:

| File | LOC | Responsibility | Cleanup temperature |
|------|-----|---------------|---------------------|
| `web.py` | 1330 | Every route, every channel send path, helpers | **Hot** — prime splitting candidate |
| `db.py` | 431 | All tables, all helpers, Fernet | Warm — could extract channel_connections + message_threads |
| `static/app.js` | 2065 | All UI state, all modals | Warm — feature modules could split |
| `static/index.html` | 1005 | SPA shell + Tailwind-CDN styles + all modals | Warm — style block is ~300 lines mixed raw CSS + `@apply` |
| `static/style.css` | 78 | Theme variables only | Fine |
| `CLAUDE.md` | 330 | AI prompt/behaviour doc | Warm — dead `psql` instructions, over-long calendar section |
| `whatsapp-sidecar/src/server.js` | 302 | Baileys + HTTP API + webhook-out | Fine |
| `bridge.py` | ~230 | Legacy Telegram bridge | Cold — under-used, needs a fate decision |
| `channels/base.py` | 88 | Abstract channel interface | Cold — nobody implements it anymore (WhatsApp/Meta bypass) |
| `channels/telegram.py` | ? | Telegram impl of BaseChannel | Cold — only used by bridge.py |

---

## Requirements Trace

This plan's goals:

- **R1.** Produce an up-to-date feature inventory + implementation map readable in one sitting (the Feature Inventory and Implementation Map sections above). No code changes required.
- **R2.** Identify concrete cleanup targets ordered by value/risk.
- **R3.** Scope high-priority cleanups as commit-sized units so `/ce-work` can execute selectively without needing re-planning.
- **R4.** Defer medium/low-priority items to an explicit backlog so they're remembered but not committed to.

---

## Scope Boundaries

- **No rewrites.** This plan does not propose replacing SQLite, moving off FastAPI, changing the Tailwind CDN approach, or rearchitecting the multi-tenant model. The architecture is fine; the hygiene isn't.
- **No feature additions.** Cleanup only. If a cleanup *removes* a feature that isn't being used (e.g., the `feedback` table), that's in scope. If it *adds* a feature to make cleanup easier (e.g., proper migrations framework), that's out of scope.
- **No premature abstractions.** If two things look similar, fine — don't force an abstraction until there's a third.

### Deferred to Follow-Up Work

The following are real cleanup candidates but intentionally left in the backlog below rather than promoted to executable units in this plan:

- **Splitting `web.py` into route modules** (approvals.py, channels.py, calendar.py, etc.). Large refactor, blast radius across every feature. Better as a separate dedicated plan once the smaller units below land.
- **Splitting `static/app.js` into feature modules.** Same rationale; requires introducing a build step or module loading strategy.
- **Migration framework** (e.g. Alembic-style versioned up/down migrations). Currently ad-hoc `try/except sqlite3.OperationalError` suffices for SMB scale. Revisit if we grow past 10 tenants or need zero-downtime schema changes.
- **Asset fingerprinting** (replacing manual `?v=N` bumps with content-hash URLs). Nice-to-have; current pattern is working.
- **Full test harness with CI.** A proper test infrastructure is a separate plan — this plan includes just enough tests to cover the highest-risk paths via U6.

---

## Context & Research

### Relevant Code and Patterns

- **Existing section headers pattern in `web.py`**: `# ---- Routes — <feature> ----` — good split boundary when/if we modularize
- **`_analyse_inbox` as the shared inbound-to-approval entry**: every channel (web submit, WhatsApp webhook, Meta webhook) funnels through it. This is the right abstraction — mirror it for outbound
- **`approval_id = str(uuid.uuid4())[:8]` for short IDs** (inbox submit, Meta webhook) vs full UUID (compose). Minor inconsistency

### Institutional Learnings

No `docs/solutions/` exists yet. Future cleanup PRs that fix non-obvious issues should document them there (separate from this plan).

### Prior plans referenced

- `docs/plans/2026-04-23-001-feat-official-meta-connectors-plan.md` — the Meta connector plan. Its "Known limitations" section already flagged several items that appear in this cleanup backlog.

---

## Key Technical Decisions

- **Keep the backlog in the plan, not issues.** Low/medium items stay in this document under "Cleanup Backlog". If we convert them to GitHub issues later, this plan is the source.
- **High-priority units must include test scenarios.** This is the start of a real test discipline; don't reset the expectation now.
- **Test framework: `pytest`**. Standard, already compatible with FastAPI's `TestClient`. `tests/` at repo root. First unit (U6) introduces it.
- **Feedback table: delete, not wire up.** The markdown-file approach is already working and was the user's explicit preference. The dead table is just noise.
- **Calendar SQL examples in CLAUDE.md: keep as-is.** Verbose, but the AI actually needs them to know the schema. Don't optimize for conciseness at the cost of AI effectiveness. The *psql-against-messages* instructions are a different case — those are actively harmful because they reference non-existent state.

---

## Open Questions

### Resolved During Planning

- **Plan or execute?** — This plan includes both the audit (documentation) and executable cleanup units. Each unit can be picked off by `/ce-work` independently.
- **Refactor scope** — Explicitly limited to hygiene. No architectural changes, no rewrites.
- **Test framework** — pytest, standard FastAPI `TestClient`.

### Deferred to Implementation

- Exact file paths for split modules (if we decide to do that later) — depends on final route groupings.
- How strict to be about type hints / linting — no config today; adding one is its own decision.
- Whether `bridge.py` should be deleted outright or kept as a commented reference — depends on whether any tenant is actually using Telegram today. Investigate when U8 runs.

---

## Implementation Units

Eight high-priority cleanups, ordered by value/risk. Each is commit-sized and independently mergeable. Low/medium items are in the "Cleanup Backlog" appendix after these units.

- [ ] U1. **Remove dead psql/messages-table instructions from CLAUDE.md**

**Goal:** The AI wastes tokens on every `[EXTERNAL]` and `[POST_SEND]` run trying to `psql INSERT INTO messages` against a PostgreSQL DB that doesn't exist. Our SQLite schema has `pending_approvals` + `event_log`; the `messages` table was aspirational and never implemented. Delete those instructions and replace with accurate SQLite-aware guidance (or just remove them entirely since the server-side `web.py` already writes to the correct tables).

**Requirements:** R1, R2 (also addresses a direct user pain: "the `messages` table referenced in CLAUDE.md does not exist in SQLite" flagged in plan 001)

**Dependencies:** None

**Files:**
- Modify: `CLAUDE.md`

**Approach:**
- Delete the psql/messages blocks from `[EXTERNAL] Step 3` and `[POST_SEND] Always — update DB`.
- Replace with a one-line note that the server handles DB writes and the AI should focus on wiki + calendar updates only.
- Verify no other section silently references those tables.

**Patterns to follow:**
- Existing `Calendar Events` section uses `python3 -c "import sqlite3"` style for the things the AI *does* need to do — consistent.

**Test scenarios:**
- Test expectation: none — docs-only change. Verification is: grep CLAUDE.md for `psql`, expect zero hits. Second verification: run `[EXTERNAL]` end-to-end on one tenant, confirm the AI no longer attempts psql and the approval still lands in the queue.

**Verification:**
- `grep -c "psql" CLAUDE.md` returns 0
- A test WhatsApp inbound still produces a correct approval + event_log entry (sanity — no regression)

---

- [ ] U2. **Delete the dead `feedback` table from db.py**

**Goal:** `feedback` table was added in an earlier commit but the endpoint `/api/feedback` was later changed to append to a markdown file instead. The table exists, nothing writes to it, nothing reads it. Remove it.

**Requirements:** R2

**Dependencies:** None

**Files:**
- Modify: `db.py` (remove `CREATE TABLE IF NOT EXISTS feedback` from `init_db`, remove `create_feedback` + `get_feedback` helpers)
- Test: `tests/test_db_schema.py` (will be created in U6; this PR lands without test and U6 backfills)

**Approach:**
- Remove the CREATE TABLE block.
- Remove the two helper functions if they exist.
- No ALTER TABLE needed — SQLite doesn't mind a column/table dropping silently; the existing rows are just orphaned. Since the file is the source of truth and nothing reads from the table, orphaned rows are harmless.
- Optionally add a `DROP TABLE IF EXISTS feedback` for tidiness; weigh vs. risk of accidentally running against a prod DB where someone manually populated it. Default: leave it, add a comment.

**Patterns to follow:**
- Keep the comment cluster at top of `db.py` honest — if someone reads `db.py`, they should see only what's live.

**Test scenarios:**
- Test expectation: none for U2 itself — behavioral no-op since no code path touched the table. U6 will verify by asserting `init_db` runs clean and no `feedback` table exists in a fresh DB.

**Verification:**
- `sqlite3 data/crm.db ".tables"` on a fresh tenant shows 6 tables, not 7 (no `feedback`)
- Grep repo for `create_feedback`, `get_feedback`, `FROM feedback` — zero hits

---

- [ ] U3. **Extract POST_SEND prompt builder**

**Goal:** `web.py::accept_approval` (line ~233) and `web.py::mark_done` (line ~298) both rebuild the same `[POST_SEND]\ncontact_identifier: ...` prompt with 7 identical f-string lines. Any change to the prompt format needs two edits; forgetting one creates subtle POST_SEND drift between channels. Extract one helper.

**Requirements:** R2

**Dependencies:** None

**Files:**
- Modify: `web.py`
- Test: `tests/test_post_send_prompt.py`

**Approach:**
- Add `_build_post_send_prompt(approval: dict) -> str` at the top of web.py near `call_claude`.
- Replace both inline blocks with a call to the helper.
- Behavior-preserving: output bytes are identical.

**Patterns to follow:**
- `call_claude` and `_analyse_inbox` already live in the helpers block — drop the new helper next to them.

**Test scenarios:**
- Happy path: Given a canonical approval dict with all fields set, returned string matches the previous inline f-string exactly (snapshot comparison).
- Edge case: approval where `analysis` is None — 'is_new_contact' defaults to 'false' (current behavior: `'New contact' in (approval['analysis'] or '')` handles None, so snapshot should still match).
- Edge case: approval where `draft` contains newlines — prompt is still correctly formed.

**Verification:**
- Snapshot test passes
- Manual spot check: accept a Messenger approval and a WhatsApp approval, compare what the AI sees — identical format

---

- [ ] U4. **Remove duplicate `import requests` inside `accept_approval`**

**Goal:** `web.py` line 192 has `import requests as _r` inside `accept_approval`, while line ~798 imports `requests as _rq` at module scope. The inline import is a leftover from an earlier edit and shadows the module-level name in that function. Use `_rq` consistently.

**Requirements:** R2

**Dependencies:** None

**Files:**
- Modify: `web.py`

**Approach:**
- Delete the inline `import requests as _r`.
- Change the single call site from `_r.post` to `_rq.post`.
- Verify `_rq` is imported before `accept_approval` is defined (grep confirms it is, at line 798 — which means `accept_approval` at line 178 uses the module-level import anyway; the inline `import` was shadowing). Move the module-level import earlier in the file if needed.

**Patterns to follow:**
- All other Graph API calls use `_rq.` — match that.

**Test scenarios:**
- Test expectation: pure refactor. U6 adds an accept_approval test that verifies the send path still fires (with requests mocked).

**Verification:**
- `grep "import requests" web.py` returns exactly one line
- `grep "_r\\.post\\|_r\\." web.py` returns zero hits (all `_rq`)
- hvac smoke test: accepting a WhatsApp approval still sends to the sidecar

---

- [ ] U5. **Unify outbound send dispatcher**

**Goal:** `accept_approval` currently has three chained `if approval['channel'] == 'x':` branches for WhatsApp and Meta with their own error translation. As more channels arrive (email?), this keeps growing. Extract `_send_outbound(channel, identifier, draft, approval) -> None` that dispatches by channel and raises the appropriate HTTPException. `accept_approval` becomes a short orchestrator: check state → send → mark accepted → log → POST_SEND.

**Requirements:** R2

**Dependencies:** U3 (so the POST_SEND prompt builder is already extracted before this reorganization)

**Files:**
- Modify: `web.py`
- Test: `tests/test_accept_outbound.py`

**Approach:**
- Signature: `_send_outbound(channel: str, approval: dict) -> None`. Raises HTTPException on failure. Caller uses the raised exception as-is.
- Branches: `whatsapp` → sidecar POST; `messenger`/`instagram` → window check + `_meta_send`; default → no-op (web/email/telegram don't send from accept_approval today).
- 24h window check stays inside the meta branch.
- Tests: one per channel, plus one for the "no-op" default case.

**Patterns to follow:**
- `_meta_send` is already a clean helper; this is just the same treatment for the WhatsApp branch.

**Test scenarios:**
- Happy path: `_send_outbound('whatsapp', approval)` with mocked sidecar POST → sidecar gets `{to, text}` with `approval['identifier']` and `approval['draft']`
- Happy path: `_send_outbound('messenger', approval)` with fresh `last_inbound_at` (under 24h) → calls `_meta_send('messenger', ...)` once
- Edge case: `_send_outbound('web', approval)` → returns None, no HTTP calls
- Error path: WhatsApp sidecar unreachable → raises HTTPException(503, "WhatsApp service is not reachable")
- Error path: Meta approval with `last_inbound_at` older than 24h → raises HTTPException(409, "outside_window")
- Error path: Meta error code 190 → raises HTTPException(502) AND flips `channel_connections.status` to `needs_reconnect`
- Integration: `accept_approval` end-to-end happy-path for each channel results in correct `status=accepted`, `event_log` out row, and POST_SEND prompt dispatch

**Verification:**
- `accept_approval` body is now <30 lines and reads linearly
- All existing integration behavior preserved (smoke test each channel)

---

- [ ] U6. **Introduce `tests/` with pytest and cover the high-risk paths**

**Goal:** The plan references test files that don't exist yet. Kickstart the discipline with a minimal but real `tests/` directory covering the three highest-risk paths: DB migrations/schema, Meta webhook signature validation, and the accept→send→POST_SEND state machine. Add `pytest` + `httpx` to `requirements.txt` (`httpx` is the FastAPI `TestClient` dependency). Add `pytest.ini` with minimal config.

**Requirements:** R2, R3

**Dependencies:** U2, U3 (cleaner code to test)

**Files:**
- Create: `tests/__init__.py`
- Create: `tests/conftest.py` (fixtures: isolated DB path, fake env vars for Fernet/Meta, TestClient)
- Create: `tests/test_db_schema.py` (migrations idempotent, all tables present, no `feedback` table)
- Create: `tests/test_fernet.py` (round-trip, wrong-key fails, missing-env-var fails with clear message)
- Create: `tests/test_meta_webhook.py` (GET verify, signed POST, unsigned POST 403, unknown object ignored)
- Create: `tests/test_accept_outbound.py` (depends on U5 — the dispatcher)
- Create: `pytest.ini`
- Modify: `requirements.txt` (add `pytest`, `httpx` — `httpx` for FastAPI's TestClient)
- Modify: `Dockerfile` (optional — install test deps only if we decide to run tests in the container; otherwise skip and run tests outside)

**Approach:**
- Use `TestClient(app)` from `fastapi.testclient` for integration-style tests (no real HTTP, no docker).
- Fernet key + Meta env vars set per-test via `monkeypatch.setenv`.
- DB tests use a `tmp_path` fixture so each test gets a fresh SQLite file; `db.DB_PATH` is monkeypatched before `db.init_db()` is called.
- Mock `requests.post`/`requests.get` with `pytest-mock` or `unittest.mock.patch` for Graph API / sidecar interactions. Don't hit real endpoints.
- No CI wiring in this unit — just `pytest` from the repo root. CI is a follow-up.

**Execution note:** Test-first — write each test file before (or alongside) the extraction/change it covers, so the test actually verifies behavior. U3/U4/U5 bodies get their tests added in this unit.

**Patterns to follow:**
- FastAPI `TestClient` docs — standard pattern.
- Fernet tests: `Fernet.generate_key()` per test, set via `monkeypatch.setenv('TENANT_ENCRYPTION_KEY', key.decode())`, then import `db` fresh (may need `importlib.reload` since `_FERNET` is module-level).

**Test scenarios:**
- Happy path: `db.init_db()` on a fresh DB creates all 6 tables (not 7 — `feedback` gone)
- Happy path: `db.init_db()` on an existing DB (simulate by pre-creating with older schema) is idempotent — no errors, adds missing columns
- Happy path: Fernet round-trip encrypts and decrypts "hello", "", unicode
- Happy path: `POST /api/webhook/meta` with a valid HMAC-signed payload creates an approval
- Edge case: `POST /api/webhook/meta` with missing `X-Hub-Signature-256` returns 403 when `META_APP_SECRET` is set
- Edge case: `POST /api/webhook/meta` with wrong signature returns 403
- Edge case: `POST /api/webhook/meta` with `object=="instagram"` dispatches to IG handler (assert via capturing `_process_meta_entries` calls)
- Edge case: `GET /api/webhook/meta?hub.mode=subscribe&hub.verify_token=RIGHT&hub.challenge=X` returns `X` as plain text
- Edge case: Same GET with wrong token returns 403
- Error path: Fernet decrypt with wrong key raises `InvalidToken`
- Error path: `TENANT_ENCRYPTION_KEY` not set raises clear RuntimeError on first encrypt/decrypt call
- Integration: accept-approval happy path (WhatsApp + Messenger in-window + Messenger out-of-window → 409) with mocks

**Verification:**
- `pytest` from repo root: all green
- Coverage is not enforced; goal is existence of real tests that will catch the regressions we care about

---

- [ ] U7. **Fix or retire `channels/base.py` abstraction**

**Goal:** `channels/base.py` defines an abstract `BaseChannel` with `poll / post_for_approval / send_to_contact / post_internal / acknowledge_approval / delete_approval_message`. Only `channels/telegram.py` implements it, and only `bridge.py` consumes it. Everything else (WhatsApp sidecar, Meta webhook + OAuth + send) happens inline in `web.py`. The abstraction exists but isn't earning its keep. **Decide its fate**:

Option A: Delete `channels/base.py` and `channels/telegram.py`, simplify `bridge.py` to import directly from a slim `telegram.py` module. Rationale: the abstraction pretends to be polymorphic but has only one caller. Remove the indirection.

Option B: Lean in — refactor WhatsApp and Meta send paths to implement `BaseChannel.send_to_contact`, so `accept_approval` becomes channel-type-agnostic. Rationale: now that we have 3+ channels, the abstraction has real payoff.

Recommended: **Option A** for now. The abstraction was designed for bridge.py-style polling channels, but the product moved to webhook-driven channels that don't fit the `poll()` method at all. Forcing Meta and WhatsApp into a shape designed for Telegram polling would add confusion, not remove it.

**Requirements:** R2

**Dependencies:** U5 (the outbound dispatcher gives us channel-agnostic send without needing BaseChannel)

**Files:**
- Delete: `channels/base.py`
- Modify: `channels/__init__.py` (remove imports referring to base)
- Modify: `bridge.py` (adjust imports, use telegram module directly)
- Keep: `channels/telegram.py` (the impl still works, just without the abstract parent)
- Test: `tests/test_bridge_smoke.py` (minimal smoke — bridge.py imports cleanly)

**Approach:**
- Remove `from channels.base import ...` from bridge.py
- Remove `BaseChannel` subclass declaration from `channels/telegram.py` (it becomes a plain class)
- Delete `channels/base.py`
- Verify bridge.py still boots under `python -c "import bridge"` (fails only if Telegram credentials missing — which is also fine, we just need imports to succeed)

**Patterns to follow:**
- Don't introduce a new abstraction to replace it — just use the concrete telegram class directly.

**Test scenarios:**
- Happy path: `python -c "import channels.telegram"` succeeds, loads the Telegram channel class without errors
- Happy path: `python -c "import bridge"` succeeds without credentials being present (config-time errors are OK; import-time errors are not)
- Edge case: `channels/base.py` no longer importable (assert `ImportError` on `from channels import base`)

**Verification:**
- No file under `channels/` other than `__init__.py` and `telegram.py`
- `bridge.py` imports resolve with only telegram.py present
- `grep "BaseChannel\|channels.base" -r .` → zero hits in the source tree

---

- [ ] U8. **Audit bridge.py — is Telegram still used, or retire the bridge?**

**Goal:** `bridge.py` is the legacy Telegram polling bridge. The product's actual channel flow now goes through `web.py` webhooks + the `accept_approval` pipeline. `bridge.py` has an outdated comment (`# 'whatsapp': WhatsAppChannel,  # future` — we shipped WhatsApp via a completely different path). Decide: is any current tenant actually receiving messages via Telegram? If yes, keep and fix the comment. If no, retire it (rename to `.archive/bridge.py` or delete outright, document the decision).

**Requirements:** R2, R4

**Dependencies:** U7 (BaseChannel removed) — this cleanup depends on the channels abstraction decision

**Files:**
- Investigate: `bridge.py`, tenant configs (`tenants/*/config.json` for `telegram` keys)
- Decide outcome: Delete, archive, or update
- If deleting: `bridge.py`, `channels/telegram.py`, remove Telegram section from `CLAUDE.md`, remove `telegram.*` config keys from `config.example.json`
- If keeping: Modify `bridge.py` comment, ensure current config still works

**Approach:**
- Step 1: grep all tenant configs for a non-empty `channels.telegram` section. If all are empty, Telegram is unused today.
- Step 2: Ask the user for the final call (archive vs delete vs keep). This unit is dependent on that choice.

**Patterns to follow:**
- `git log --follow bridge.py` for last-touched dates — if it hasn't changed in months and nothing references it from new code, that's a retirement signal.

**Test scenarios:**
- Test expectation: none — this is an investigation + decision unit. If the decision is to delete, U6's smoke test verifies bridge.py's absence doesn't break the container. If the decision is to keep, no test change.

**Verification:**
- A one-paragraph decision record appended to this plan (under "Cleanup Backlog" resolution) describing what was found and what was done

---

## Cleanup Backlog (Deferred)

Not scoped as units in this plan. Each is still worth doing eventually; surface as its own plan when the time comes.

### Medium priority

- **Split `web.py` into route modules** — `routes/approvals.py`, `routes/channels.py`, `routes/calendar.py`, `routes/chat.py`, `routes/feedback.py`, `routes/webhooks.py`. Use `APIRouter` in each, `app.include_router(...)` in `web.py`. Keep helpers (`call_claude`, `_analyse_inbox`) in a `services/` module. Estimated effort: 4–6 hours; blast radius: every feature.
- **Split `static/app.js` into feature modules** — requires introducing a build step (esbuild / Vite) or native ES modules with `<script type="module">`. Pick native ES modules for simplicity — no build step.
- **Consolidate index.html style block** — the ~300-line `<style type="text/tailwindcss">` block mixes `@apply` directives and raw CSS. Either (a) move all raw CSS into `style.css` and keep `@apply` rules inline, or (b) commit to pure-Tailwind-utility classes in HTML and drop the custom CSS entirely. The recent `.card-sub` bug (raw `display: flex` silently dropped by the CDN parser in plan 001) is evidence this mix is brittle.
- **Calendar section compaction in CLAUDE.md** — the SQL examples are verbose. A reference subsection at the bottom with examples, and a short "when" table above, would reduce read-time for the AI.
- **Standardize UUID strategy** — `str(uuid.uuid4())[:8]` vs full UUID inconsistency. Pick one (8-char is fine if we document it; full is safer). ~20 call sites to audit.

### Low priority

- **Asset fingerprinting** — replace `?v=10` manual bumps with a build-time content hash. Avoids the "hard refresh" toast.
- **Proper migrations framework** — Alembic-compatible up/down migrations instead of `try: ALTER TABLE ... except` patterns. Overkill today.
- **Event log retention** — `event_log` grows unbounded. Add a retention policy (e.g., keep 90 days) as a nightly cron in the container. Not urgent at current volume.
- **Feedback file rotation** — `/app/data/feedback.md` appends forever. Unlikely to matter (feedback is low-volume) but worth a line in the runbook.
- **Structured logging** — currently mixed `print()` and default uvicorn logging. A single logging setup with structured fields would help when we eventually ship monitoring.
- **Error code to reconnect banner wiring** — Meta connector sets `status='needs_reconnect'` on token failures, but the dashboard doesn't prominently surface that yet. The Channels modal shows it; the inbox doesn't.

---

## System-Wide Impact

- **Interaction graph:** U3 (POST_SEND helper) and U5 (outbound dispatcher) touch `accept_approval` and `mark_done` — the two functions that fire POST_SEND. A regression here would silently stop the wiki/calendar from updating. Test coverage in U6 is load-bearing.
- **Error propagation:** U5 preserves the existing HTTPException shapes (502/503/409 codes, detail strings). Clients (`static/app.js`) detect the `outside_window` string to trigger the escape hatch — don't change that string without updating the client.
- **State lifecycle risks:** U2 (dropping the feedback table) leaves orphaned rows in existing tenant DBs. Harmless but worth noting — no `DROP TABLE` is issued. If a future tenant is re-provisioned, their fresh DB won't have the table at all.
- **API surface parity:** None of these units change any HTTP endpoint shapes. Pure internal refactors + doc cleanup.
- **Integration coverage:** U6's `test_accept_outbound.py` is the first real integration test. It proves the full accept → send → POST_SEND chain works for each channel with mocks. Worth its weight.
- **Unchanged invariants:** All shipped features keep working. The dashboard UI doesn't change visually. Tenant configs don't change format. All existing approvals in the DB remain compatible.

---

## Risks & Dependencies

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Refactor breaks one channel's send path | Medium | High — customer messages stop going out | U6 tests must land alongside U5. Smoke-test each channel on a real tenant before closing the PR |
| CLAUDE.md edits cause the AI to misidentify senders | Low | Medium — new contacts might not be created | U1 is scoped tight: only remove dead psql instructions. Don't touch [EXTERNAL] Step 1 identification logic |
| Removing `feedback` table breaks a hidden consumer we forgot about | Low | Low — nothing reads it anyway | Grep before delete; U6 asserts its absence |
| `bridge.py` deletion breaks a tenant still on Telegram | Low | High — tenant silently stops receiving messages | U8 investigation phase answers this before any deletion |
| Test framework introduction creates maintenance drag | Low | Low | Start small in U6; don't enforce coverage thresholds |
| Tenants with existing orphaned `feedback` rows take up disk space | Very Low | Trivial | Row count is ~N feedback submissions across all time. Accept the orphan |

---

## Documentation / Operational Notes

- After this plan lands, consider starting a `docs/solutions/` with the learnings accumulated during this session (Tailwind CDN `@apply`+raw-CSS pitfall, Docker-mounted SQLite WAL quirks, Meta webhook `hub.challenge` dotted-query-param handling, etc.).
- Each unit that lands should get a short `docs/solutions/<date>-<slug>.md` if it catches something non-obvious.
- No operational impact on existing tenants — all units are backwards-compatible.

---

## Sources & References

- **Prior plan:** [docs/plans/2026-04-23-001-feat-official-meta-connectors-plan.md](2026-04-23-001-feat-official-meta-connectors-plan.md) — known-limitations section seeded several items in this backlog
- **Meta App setup runbook:** [docs/meta-app-setup.md](../meta-app-setup.md)
- **CLAUDE.md** — AI behaviour contract
- **Git history:** commits `f3e6baf` (calendar + feedback), `b00dddd` (WhatsApp Baileys), `dc7015e` (Meta connectors), `09fc379` (inbox time + layout fix) — the shipped arc this audit covers
