---
title: Compounding automation via AI-labelled approval patterns
date: 2026-04-23
category: docs/solutions/architecture-patterns/
module: ai-pa-crm
problem_type: architecture_pattern
component: service_object
severity: high
applies_when:
  - building owner-in-the-loop AI workflows where every AI output today needs human approval
  - the same class of request recurs often enough that manual approval becomes toil
  - an LLM is already inspecting each input and can cheaply emit a stable kebab-case intent label
  - you have an auditable approvals/events table you can derive stats from at read time
  - safety requires explicit owner opt-in before any action bypasses human review
tags: [auto-approval, human-in-the-loop, intent-classification, progressive-automation, audit-trail, sqlite, llm-labeling, compounding-value]
related_components: [database, service_object, frontend_stimulus]
---

# Compounding automation via AI-labelled approval patterns

## Context

Every inbound customer message on this multi-tenant AI CRM lands in an approval queue: Claude drafts a reply from the wiki, and the owner clicks "approve" (or edit + approve) before it goes out. That's fine at three conversations a day. At thirty-plus — for an AC-servicing business getting ten "what's your price for a 2HP install?" messages a week — steps 2 and 3 are pure toil. The owner has already *proved*, by approving the same draft without edits eight times running, that they trust this reply for this type of question. The approval click is no longer adding judgment; it's adding latency.

The plan frames the core observation: *the AI already reads every message with wiki context in order to draft a reply. Teaching it to also label the intent is a small marginal ask.* No embeddings, no taxonomy, no separate classifier pipeline. The model that's already doing the heaviest work is the right place to attach a one-line kebab-case tag.

From that, the compounding loop: once intent labels are attached to approvals, per-intent statistics (counts, distinct days, edit/reject signals) can be computed at read time from `pending_approvals`. When the numbers show the owner trusts a given intent — 5+ clean accepts spread across 5+ distinct days in a rolling 30-day window, zero edits, zero rejects — that pattern becomes *eligible to automate*. The owner then explicitly promotes it, and future matching inbounds bypass the queue.

Two non-negotiables shape everything downstream. First, **nothing auto-fires without an explicit owner click**: at merge time no pattern in any tenant DB has `status='auto'`, so the auto-send branch is unreachable in production until a human turns it on. Second, **eligibility is precision-optimised, not recall-optimised**: zero tolerance for edits or rejects within the window, hardcoded thresholds (not tenant-tunable in v1), and new contacts are always manual regardless of pattern state. The cost of a wrong auto-send (customer gets stale pricing) is far higher than the cost of a click the owner didn't need to make.

## Guidance

**1. Make the already-running AI the classifier. No separate pipeline.**

The prompt gains one small step and one new marker block. From `CLAUDE.md`:

```
===INTENT===
[kebab-case-intent-label]
===END===
```

Step 5 of the `[EXTERNAL]` flow gives the AI consistency guidance rather than a fixed taxonomy:

```
- Be specific when the answer depends on specifics. `pricing-2hp-install`
  and `pricing-5hp-install` are different intents because the answer is
  different. Don't collapse them just because the topic is similar.
- Be consistent. If you've classified this kind of message before, reuse
  the same label. Word order matters.
- New-contact prefix. If this is a new contact, prefix with `new-`.
- Uncertain? Use `unclassified`.
- Format: lowercase letters, digits, and hyphens only. Max ~60 chars.
```

Trust the AI to label consistently; the only defence against label drift is prompt guidance plus owner revert. The plan accepts this explicitly and defers embedding-based similarity + a merge tool to v2.

**2. Parse defensively, sanitise aggressively.** The AI will sometimes miss the marker block. Empty intent is allowed — the approval just doesn't contribute to pattern stats and can't be auto-sent. From `web.py::_analyse_inbox`:

```python
intent_match = re.search(r'===INTENT===(.*?)===END===', response, re.DOTALL)
intent_label = _normalise_intent_label(intent_match.group(1) if intent_match else '')

db.update_approval(approval_id, analysis=analysis, draft=draft, intent_label=intent_label)
if intent_label:
    db.upsert_pattern(intent_label)
```

```python
def _normalise_intent_label(raw: str) -> str:
    """Sanitise AI-generated intent labels to [a-z0-9-], max 80 chars. Empty -> ''."""
    if not raw:
        return ''
    s = raw.strip().lower()
    s = re.sub(r'\s+', '-', s)
    s = re.sub(r'[^a-z0-9-]', '', s)
    s = re.sub(r'-+', '-', s).strip('-')
    return s[:80]
```

Six lines of discipline: strip, lowercase, spaces→hyphens, drop anything outside `[a-z0-9-]`, collapse repeated hyphens, truncate. Free-form AI output becomes a safe primary key without a crash path.

**3. Tiny promotion-state table; compute stats on the fly.**

```sql
CREATE TABLE IF NOT EXISTS response_patterns (
    intent_label    TEXT PRIMARY KEY,
    status          TEXT DEFAULT 'learning',   -- 'learning' | 'auto' | 'manual_locked'
    promoted_at     TEXT,
    demoted_at      TEXT,
    created_at      TEXT DEFAULT (datetime('now')),
    last_seen_at    TEXT
);
```

The table stores *only* promotion state and timestamps. Counts, distinct days, eligibility — all computed from `pending_approvals` at read time. Single source of truth, no cache to drift:

```sql
SELECT
    COUNT(*) AS total,
    SUM(CASE WHEN status='accepted' AND was_edited=0 THEN 1 ELSE 0 END) AS accepted_no_edit,
    SUM(CASE WHEN status='accepted' AND was_edited=1 THEN 1 ELSE 0 END) AS accepted_with_edit,
    SUM(CASE WHEN status='rejected' THEN 1 ELSE 0 END) AS rejected,
    COUNT(DISTINCT CASE
        WHEN status='accepted' AND was_edited=0
        THEN substr(created_at, 1, 10)
    END) AS distinct_days_no_edit
FROM pending_approvals
WHERE intent_label = ?
  AND created_at >= datetime('now', '-30 days')
```

One pass. Distinct-day counting via `substr(created_at, 1, 10)` to extract `YYYY-MM-DD` — no separate date column, no aggregation round-trip. At SMB scale (a few thousand approvals per tenant) this is trivial and avoids a whole class of cache-invalidation bugs.

**4. Promotion is authoritative, not re-derived.**

```python
def should_auto_send(intent_label: str, analysis: str) -> bool:
    if not intent_label:
        return False
    if analysis and 'New contact' in analysis:
        return False
    pattern = db.get_pattern(intent_label)
    if not pattern:
        return False
    return pattern.get('status') == 'auto'
```

`should_auto_send` does not re-check eligibility. Once the owner clicks enable, `status='auto'` is the truth; the pattern stays promoted until the owner explicitly reverts. Eligibility re-checks on every send would introduce a whole new failure mode ("why did auto-send randomly stop working last night?"). Safety rails *compose* here: empty intent → no, new contact → no, no pattern row → no, not promoted → no. Any one of them blocks.

**5. Factor the send path before you need two callers.** Before this work, `accept_approval` inlined all per-channel dispatch. A second caller — the auto-send branch — would have forked that logic. The plan did the extraction as a prerequisite (`_send_outbound(approval)` + `_run_post_send(approval, kind)`), making what was "planned cleanup debt" into load-bearing infrastructure the moment auto-send landed:

```python
# _analyse_inbox, after saving analysis/draft/intent_label
if response_patterns.should_auto_send(intent_label, analysis):
    approval = db.get_approval(approval_id)
    if approval and approval.get('status') == 'pending':
        try:
            _send_outbound(approval)
        except HTTPException as e:
            db.update_approval(approval_id, error_note=f"auto-send failed: {e.detail}")
            return
        except Exception as e:
            db.update_approval(approval_id, error_note=f"auto-send error: {e}")
            return

        db.update_approval(approval_id, status='accepted', kind='auto')
        db.log_event(approval['identifier'], approval['identifier_type'],
                     approval['channel'], 'out', 'auto_sent', approval['draft'][:100])
        _run_post_send(approval, kind='auto')
```

The try/except leaves the approval *pending* on failure with an `error_note` — the owner sees it in the queue with context ("auto-send failed: WhatsApp service is not reachable") and can retry manually. No infinite loop, no silent drop.

**6. Owner-initiated circuit breaker only.** In v1 there is no NLP detection of "customer said that was wrong" signals. Revert is an explicit button (`POST /api/patterns/{intent_label}/disable` → `manual_locked`). The plan calls this out: automatic demotion needs NLP we don't have and would over-fire on edge cases. Keep the control explicit until there's signal to do otherwise.

## Why This Matters

**Skip the AI-as-classifier shortcut** and you end up building a parallel classification pipeline — embeddings, clustering, a taxonomy the owner has to curate. You also lose the wiki-contextual judgement the draft-writing model already has (it can tell `pricing-2hp-install` from `pricing-5hp-install` because it read the pricing page). A separate classifier trained in isolation would miss that context.

**Skip the "stats computed, state stored" split** and you get cache drift. Someone edits a draft retroactively, or an approval gets rejected a day late, and the cached "distinct days" number is now wrong — until you rebuild the cache, on what trigger, after what event? Recomputing is cheap; invalidation is hard.

**Skip the owner-authoritative promotion** and eligibility becomes dynamic. A pattern auto-sends today, then silently stops tomorrow because one stale approval aged out of the window. The owner has no mental model for why. Making promotion a sticky owner action ("you turned this on; it stays on until you turn it off") is legible.

**Skip R7a (new contacts always manual)** and the system will one day auto-reply to a competitor's scouting message with your full pricing, or send a canned answer to a lead that needed the owner's eyes. Lead creation is the highest-stakes moment in the CRM; there is no intent worth automating past the owner.

**Skip zero-tolerance on edits** and a pattern promotes itself on 4 clean accepts + 1 edit out of 5 — but the edit was the owner catching that the draft said "2HP" when it should have been "3HP". You've just automated sending the wrong number. Precision over recall is the right default; the owner can always promote patterns we miss, but we can't unsend a wrong auto-reply.

**Skip the refactor-as-prerequisite** and you'd either duplicate `_send_outbound`'s channel-dispatch logic into `_analyse_inbox`, or — worse — drop in an HTTP self-call. Two send paths means two places to fix every future Meta/WhatsApp/Baileys change.

## When to Apply

- You have an AI already running on every unit of inbound work, and that AI has the context to classify alongside whatever it's doing. Adding a classification output is marginally cheap.
- The human-in-the-loop step is clearly *approval* rather than judgement — the user clicks "yes" without changing anything, most of the time.
- You can identify a cheap-to-compute signal for "this decision is repeat business" (here: same intent label, clean accepts, distinct days, rolling window).
- The cost of a wrong automated action is containable and recoverable (customer gets a reply that might be slightly off → owner catches it in the activity feed → reverts the pattern). Not applicable to irreversible, high-blast-radius actions.
- There is a human owner who is the authority on promotion — not a rules engine, not a threshold-crossing trigger.
- The classification axis is stable enough that the same label reasonably groups "should get the same canonical answer" cases. If your domain has high inbound variability, you may need finer-grained labels or embeddings before this pattern works.
- You can afford to optimise for precision over recall: automating only the crystal-clear cases while happily missing borderline ones.

## Examples

**Week 1, Monday.** HVAC tenant goes live with auto-approval migration. Every inbound now carries an intent label. No patterns exist in `response_patterns` yet.

```
response_patterns: []
pending_approvals: (various rows, intent_label populated)
```

**Week 1, Wednesday.** Three customers ask "price for 2HP install?". Owner approves each draft without edits. After the third:

```
response_patterns:
  ('pricing-2hp-install', 'learning', ..., last_seen_at=<Wed>)

compute_pattern_stats('pricing-2hp-install') ->
  {accepted_no_edit: 3, accepted_with_edit: 0, rejected: 0,
   distinct_days_no_edit: 2, is_eligible: False}
```

Settings modal shows under "Still learning": *"Seen 3 times on 2 distinct days. Needs 2 more to qualify."* No auto-send possible — pattern is `learning`, and `should_auto_send` returns False.

**Week 2, Friday.** Two more clean accepts on Thursday and Friday. Stats now:

```
{accepted_no_edit: 5, accepted_with_edit: 0, rejected: 0,
 distinct_days_no_edit: 4, is_eligible: False}
```

Close — but one short on distinct days. The 5/5-days rule prevents a single busy Wednesday from spoofing consistency.

**Week 2, Saturday.** Fifth distinct day, sixth clean accept:

```
{accepted_no_edit: 6, accepted_with_edit: 0, rejected: 0,
 distinct_days_no_edit: 5, is_eligible: True}
```

Settings modal moves the card to "Ready to automate" with an [Enable auto] button. No state change in the DB yet — eligibility is derived, not cached.

**Week 2, Saturday afternoon.** Owner clicks Enable. `POST /api/patterns/pricing-2hp-install/enable` fires:

```
response_patterns:
  ('pricing-2hp-install', 'auto', promoted_at=<Sat>, ...)
```

**Week 2, Sunday.** Seventh inbound asking "what's the cost for a 2HP aircon?" arrives on WhatsApp:

1. `_analyse_inbox` runs. Claude drafts the reply, labels intent `pricing-2hp-install`.
2. `should_auto_send('pricing-2hp-install', analysis)` → True (status=auto, not a new contact, non-empty label).
3. `_send_outbound(approval)` fires WhatsApp sidecar → customer receives the reply.
4. Approval row: `status='accepted'`, `kind='auto'`, `error_note=NULL`.
5. `event_log` gets an `auto_sent` row.
6. `_run_post_send` fires POST_SEND Claude prompt → wiki interaction log updated → git commit to tenant wiki.
7. Owner sees the auto-sent reply in the Activity feed with a ⚡ badge. Zero clicks.

**Week 3, Tuesday — circuit breaker.** Owner spots an auto-reply that quoted a price from pre-April pricing (the wiki was updated but the canonical answer in the pattern is stale). They click Disable:

```
response_patterns:
  ('pricing-2hp-install', 'manual_locked', demoted_at=<Tue>, ...)
```

Future matches go back to the queue. The pattern will not auto-promote to eligible again from `manual_locked` — the owner must explicitly Reset to `learning` first. This prevents nag loops where a pattern the owner reverted keeps popping back up asking to be re-enabled.

## Related

- `docs/plans/2026-04-23-003-feat-auto-approval-patterns-plan.md` — the forward-looking plan this doc is the retrospective counterpart to (9 implementation units, safety rails, deferred items).
- `docs/plans/2026-04-23-002-refactor-audit-and-cleanup-backlog-plan.md` — U5 flagged `_send_outbound` extraction as cleanup debt; the auto-approval plan consumed that as a prerequisite, turning cleanup into load-bearing infrastructure.
- `docs/deferred-work.md` — captures what was intentionally deferred (wiki-file-change invalidation, cross-tenant pattern sharing, quality ratings, tunable thresholds, model cascade).
- `CLAUDE.md` — the AI behavior contract. Any change to the INTENT block format or Step 5 instructions must land in lockstep with the parser in `web.py::_analyse_inbox`.
- Commit `1a9a2e0` — the as-built implementation.
