"""
Auto-approval pattern engine.

Derives per-intent eligibility stats from pending_approvals at read time so
there's no cache to drift. Pairs with the response_patterns table in db.py
which stores only the promotion state + timestamps — not the stats.

Promotion lifecycle:
    learning ──(thresholds met)──▶ eligible (computed, not stored)
        ▲                              │
        │ (30d silence or reset)       │ owner enables
        │                              ▼
        └─── manual_locked ◀─(revert)── auto

Thresholds (hardcoded; not tenant-tunable in v1):
    MIN_OCCURRENCES     — 5 accepted approvals with zero edits
    MIN_DISTINCT_DAYS   — across 5 distinct calendar days
    ROLLING_WINDOW_DAYS — within a 30-day rolling window
"""

from __future__ import annotations

import db

MIN_OCCURRENCES = 5
MIN_DISTINCT_DAYS = 5
ROLLING_WINDOW_DAYS = 30


def compute_pattern_stats(intent_label: str) -> dict:
    """
    Compute eligibility stats for a single intent from pending_approvals.

    Returns a dict with:
        total, accepted_no_edit, accepted_with_edit, rejected,
        distinct_days_no_edit, is_eligible,
        last_example_question, last_example_answer
    """
    empty = {
        'total': 0,
        'accepted_no_edit': 0,
        'accepted_with_edit': 0,
        'rejected': 0,
        'distinct_days_no_edit': 0,
        'is_eligible': False,
        'last_example_question': None,
        'last_example_answer': None,
    }
    if not intent_label:
        return empty

    with db.get_db() as conn:
        row = conn.execute(
            f"""
            SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN status = 'accepted' AND was_edited = 0 THEN 1 ELSE 0 END) AS accepted_no_edit,
                SUM(CASE WHEN status = 'accepted' AND was_edited = 1 THEN 1 ELSE 0 END) AS accepted_with_edit,
                SUM(CASE WHEN status = 'rejected' THEN 1 ELSE 0 END) AS rejected,
                COUNT(DISTINCT CASE
                    WHEN status = 'accepted' AND was_edited = 0
                    THEN substr(created_at, 1, 10)
                END) AS distinct_days_no_edit
            FROM pending_approvals
            WHERE intent_label = ?
              AND created_at >= datetime('now', '-{ROLLING_WINDOW_DAYS} days')
            """,
            (intent_label,),
        ).fetchone()

        example = conn.execute(
            """
            SELECT original_message, draft
            FROM pending_approvals
            WHERE intent_label = ? AND status = 'accepted' AND was_edited = 0
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (intent_label,),
        ).fetchone()

    accepted_no_edit = row['accepted_no_edit'] or 0
    accepted_with_edit = row['accepted_with_edit'] or 0
    rejected = row['rejected'] or 0
    distinct_days = row['distinct_days_no_edit'] or 0

    is_eligible = (
        accepted_no_edit >= MIN_OCCURRENCES
        and distinct_days >= MIN_DISTINCT_DAYS
        and accepted_with_edit == 0
        and rejected == 0
    )

    return {
        'total': row['total'] or 0,
        'accepted_no_edit': accepted_no_edit,
        'accepted_with_edit': accepted_with_edit,
        'rejected': rejected,
        'distinct_days_no_edit': distinct_days,
        'is_eligible': is_eligible,
        'last_example_question': example['original_message'] if example else None,
        'last_example_answer': example['draft'] if example else None,
    }


def list_all_patterns() -> list[dict]:
    """
    Return every known pattern joined with its computed stats. Used by the
    Settings UI to render the learning / eligible / auto / manual_locked lists.
    """
    patterns = db.list_patterns()
    out = []
    for p in patterns:
        stats = compute_pattern_stats(p['intent_label'])
        out.append({**p, **stats})
    return out


def should_auto_send(intent_label: str, analysis: str) -> bool:
    """
    Gate used by _analyse_inbox to decide if a new approval should bypass the
    queue. Returns True only if:
      - pattern exists with status='auto'
      - sender is NOT a new contact (R7a safety rail)
      - intent_label is non-empty (defensive)

    Pattern eligibility is NOT re-checked here — the owner explicitly promoted
    to 'auto' and that's authoritative until they revert.
    """
    if not intent_label:
        return False
    if analysis and 'New contact' in analysis:
        return False
    pattern = db.get_pattern(intent_label)
    if not pattern:
        return False
    return pattern.get('status') == 'auto'
