# Deferred Work

A durable list of things we've agreed to build *later*, with enough context that we don't have to re-decide when the time comes. Sorted by rough readiness-to-ship. Update by moving items out of this file when they land.

---

## Nightly proactive hygiene sweep

**Why deferred:** Claude CLI currently runs on a generous token allowance so cost isn't pressing. Value kicks in meaningfully only after auto-approval patterns (shipped 2026-04-24, commit `1a9a2e0`) have started compounding. Revisit once we have real pattern data to act on.

**What to build when it's time:**

- **Per-container `supercronic` (or similar) cron** firing at 04:00 local time, offset by `hash(tenant_slug) % 60` minutes so tenants in the same timezone don't pile up.
- Local time resolved from `config.json → business.timezone`. For v1 without a tz library, the simpler path is firing at 04:XX UTC plus a compose-level `TZ` env var set from the tenant's timezone.
- **Scope v1 tight** — don't boil the ocean. Start with:
  - Stale contact sweep (60/90 day no-touch → propose archive)
  - Duplicate detection (same phone/email across multiple contact files → propose merge)
  - Past calendar events still marked `scheduled` → propose completion
- **Defer in v1** — wiki consistency checks, cross-tenant patterns, anything that refactors folder structures automatically. Too easy to misfire.
- **UX** — new nav tab "Suggestions" or a section above the inbox. Each item: type badge, description, Approve / Dismiss / Snooze-7-days. Dismissed items stay silent for 30 days so the tenant doesn't see repeats.
- **Cost control** — use the cheapest capable model (links to the model cascade below). Load only `_INDEX.md` files, not every record, to keep the prompt small. Budget cap per tenant per night.

**Risks to handle in design:**
- Bad suggestions erode trust fast. Quality bar matters more than volume.
- Timing (4am local) means the tenant is asleep — if the AI does something borderline it has hours of head-start. Keep it suggestions-only, never auto-executing wiki edits at night.

---

## Model cascade + prompt caching

**Why deferred:** Same Claude CLI allowance. Claude Sonnet is cheap enough at current volume that the payoff isn't urgent. Worth doing before we're paying per token at scale.

### Near-term win (no model swap needed): Prompt caching

Sonnet supports explicit prompt caching with a 5-minute TTL. Our `[EXTERNAL]` calls currently send CLAUDE.md (~13KB) + wiki context as fresh tokens every time. If we restructure the prompt so stable prefix (CLAUDE.md + loaded wiki files) is first and the variable suffix (the specific incoming message) is last, Anthropic caches the prefix. Hot tenants → ~80% cost reduction on repeat inbound.

**Implementation:** wrap CLAUDE.md + wiki context in an Anthropic cache_control block (requires moving from shelling out to `claude` CLI, to using the Anthropic Python SDK directly). Biggest refactor — `call_claude()` today is subprocess-based; caching requires direct API. Separate decision point: do we want to replace the Claude CLI dependency?

### Later: Task-to-model routing

| Task | Frequency | Today | Target |
|------|-----------|-------|--------|
| `[EXTERNAL]` draft | Many per day per tenant | Sonnet | Llama 3.1 70B (via Together/Fireworks) |
| `[INTERNAL]` chat | Few per day per tenant | Sonnet | Llama 3.1 70B |
| `[POST_SEND]` wiki update | Many per day per tenant | Sonnet | Llama 3.1 8B (cheaper, simpler task) |
| `[EDIT_DRAFT]` regenerate | Occasional | Sonnet | Sonnet (user is watching, latency matters) |
| Nightly hygiene sweep | 1 per tenant per day | — | Llama 3.1 70B |
| CLAUDE.md / SOP authoring | Rare, high-stakes | Sonnet | Opus or newer |
| Intent tagging (auto-approval) | Every incoming | Sonnet | Haiku or small open-source |

**Implementation shape:** abstract every AI call behind `ai.call(task_type, prompt)` that routes by task. Per-tenant feature flag `config.json → ai.model_tier = "premium" | "balanced" | "economy"`. New tenants start premium; opt into balanced once stable. A/B edit-rate across models for a tenant before locking in a cheaper tier.

**Quality caveat:** Llama 3.1 70B is ~Sonnet-3.5 for structured wiki-driven drafting. Llama 8B may struggle on subtle business nuance — test each task before committing.

### Measurement

Link to the "is the wiki getting better" question from the brainstorm:
- Primary: `edits_per_100_drafts` per model per task — lower = better
- Secondary: `tokens_per_handled_message` — lower + flat edit-rate = real win
- Tertiary: tenant-facing thumbs up/down — subjective but it catches qualitative drift

---

## "Last backup" dashboard indicator — MOVED to active work

Originally deferred; built in the same arc as the GitHub backup integration. See `docs/wiki-backup.md`.

---

## CLAUDE.md full secrecy (server-side prompt fetch)

**Why deferred:** Current architecture treats CLAUDE.md as the tenant-visible framework, with the expectation that any real proprietary learnings live in a server-side store (not built yet) that the Claude call fetches at runtime. For today, we accept that a tenant with `docker exec` can read CLAUDE.md; the moat is the data flywheel, not the prompt itself.

**When to build:** Once we have our first paying customer who is a direct competitor, or when cross-tenant learnings become a real IP asset worth protecting.

**Shape when the time comes:**
- Thin CLAUDE.md stub ships in the image (framework only: message types, wiki rules, calendar conventions)
- Tenant-specific + cross-tenant learned instructions live server-side in a "prompt overrides store"
- At Claude call time, fetch the current overrides via `GET /prompt/<slug>` from our prompt service and stitch into the prompt in memory only
- Containers never persist the overrides to disk

**Cost:** adds an HTTP call on every AI invocation (~100ms latency), adds a central SPOF (our prompt service), adds operational burden. Not worth it until real IP leakage becomes a concern.

---

## Auto-expire `awaiting_done` Meta escape-hatch approvals

**Why deferred:** Flagged in the Meta connector plan. If an owner clicks "Open Messenger" (copy + open business suite) but never comes back to click "Done", the approval sits in `awaiting_done` forever. Will add a timeout sweeper once we see real usage patterns — the right threshold (24h? 72h? 7d?) depends on how owners actually work.

**Fix:** add to the nightly hygiene sweep above. Status → `expired` with event log entry, ideally with a dashboard nudge next day ("You had 3 manual-sends that never got marked Done — did they actually get sent?").

---

## Proper tests + CI

**Why deferred:** Flagged in the cleanup plan (`docs/plans/2026-04-23-002-refactor-audit-and-cleanup-backlog-plan.md`, U6). We have zero automated tests today; each fast-ships without a safety net.

**When to build:** as part of the cleanup plan's U6 execution. First test files should cover the highest-risk paths: DB migrations idempotence, Meta webhook signature validation, accept-approval state machine (including Meta window + escape hatch).

---

## Fernet key rotation story

**Why deferred:** v1 uses a static key per tenant generated at provision. Losing the key = need to reconnect Meta channels (tokens unreadable, but not catastrophic). No rotation path today.

**Shape when the time comes:** Add a `previous_key` env var, try-both-on-decrypt, re-encrypt everything with the new key on boot, then the previous can be dropped.

---

## Standardise UUID strategy across approval IDs

**Why deferred:** From the cleanup plan — some approvals use `str(uuid.uuid4())[:8]`, others use full UUIDs. No real collisions expected at current scale but the inconsistency is noise. Pick one format and document.

---

## Split `web.py` into route modules

**Why deferred:** From the cleanup plan. Blast radius too wide to do casually. Worth its own dedicated plan once the smaller cleanup units land.

---

## Split `static/app.js` into feature modules

**Why deferred:** Same as above. Requires introducing native ES modules or a build step.
