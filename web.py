#!/usr/bin/env python3
"""
AI-PA CRM — Web Server
FastAPI backend serving the internal team dashboard.
"""

import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

import asyncio
import uuid

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import db
import backup_sync
import response_patterns

# ------------------------------------------------------------------
# Config
# ------------------------------------------------------------------

PROJECT_DIR = Path(__file__).parent
CONFIG = json.loads((PROJECT_DIR / 'config.json').read_text())
WIKI_DIR = PROJECT_DIR / 'wiki'
BUSINESS_NAME = CONFIG.get('business', {}).get('name', 'CRM')

# Contact folders — read from config, fallback to AC-servicing defaults
CONTACTS_CONFIG = CONFIG.get('contacts', [
    {"type": "corporate",   "label": "Corporate",   "path": "wiki/clients/corporate"},
    {"type": "residential", "label": "Residential", "path": "wiki/clients/residential"},
    {"type": "lead",        "label": "Lead",        "path": "wiki/leads"},
])

app = FastAPI(title=f"{BUSINESS_NAME} — Internal Dashboard")
app.mount("/static", StaticFiles(directory=str(PROJECT_DIR / "static")), name="static")


# ------------------------------------------------------------------
# Gateway secret middleware — require Traefik-injected header on dashboard
# traffic, so a direct hit to the container port (bypassing Traefik) fails.
# Webhook endpoints are exempt (called by external systems, not via Traefik).
# Opt-in: if INTERNAL_SECRET env is unset, no check runs (backward compat).
# ------------------------------------------------------------------

_INTERNAL_SECRET = os.environ.get('INTERNAL_SECRET', '')
_EXEMPT_PATH_PREFIXES = ('/api/webhook/',)


@app.middleware("http")
async def _require_gateway_secret(request: Request, call_next):
    if not _INTERNAL_SECRET:
        return await call_next(request)
    path = request.url.path or ''
    if any(path.startswith(p) for p in _EXEMPT_PATH_PREFIXES):
        return await call_next(request)
    provided = request.headers.get('X-Internal-Secret', '')
    if provided != _INTERNAL_SECRET:
        return JSONResponse(status_code=403, content={"detail": "gateway secret missing or invalid"})
    return await call_next(request)


@app.on_event("startup")
async def _startup_hooks():
    # Set up GitHub-backed wiki backup if configured. Non-blocking —
    # if GitHub is unreachable, we log and continue booting.
    try:
        if backup_sync.is_configured():
            ok = backup_sync.ensure_setup(WIKI_DIR)
            print(f"[backup_sync] startup setup: {'ok' if ok else 'skipped/failed'}", flush=True)
        else:
            print("[backup_sync] not configured — wiki changes will not be pushed to GitHub", flush=True)
    except Exception as e:
        print(f"[backup_sync] startup error (non-fatal): {e}", flush=True)

    # Nightly SQLite dump scheduler: spreads across tenants by hashing
    # the slug, fires once/day ~04:00 local time.
    asyncio.create_task(_nightly_backup_loop())


async def _nightly_backup_loop():
    """Fire nightly_backup once per day, offset by tenant hash so tenants don't pile up."""
    if not backup_sync.is_configured():
        return
    from datetime import timedelta
    import hashlib
    slug = os.environ.get('TENANT_SLUG', 'default')
    tz_name = CONFIG.get('business', {}).get('timezone', 'UTC')
    # Spread across [04:00, 05:00) local time by hash
    offset_min = int(hashlib.md5(slug.encode()).hexdigest(), 16) % 60
    while True:
        now_utc = datetime.utcnow()
        # Compute next fire time: 04:<offset> local → UTC. We keep it
        # simple and don't fetch tz libs; instead the host/compose should
        # set TZ env or we fire at a fixed UTC time. For v1, just fire
        # at 04:XX UTC (adequate until we add tz handling).
        target = now_utc.replace(hour=4, minute=offset_min, second=0, microsecond=0)
        if target <= now_utc:
            target = target + timedelta(days=1)
        sleep_secs = (target - now_utc).total_seconds()
        print(f"[backup_sync] next nightly backup in {int(sleep_secs)}s", flush=True)
        try:
            await asyncio.sleep(sleep_secs)
            print("[backup_sync] running nightly backup", flush=True)
            backup_sync.nightly_backup(WIKI_DIR, db.DB_PATH)
        except asyncio.CancelledError:
            return
        except Exception as e:
            print(f"[backup_sync] nightly error (non-fatal): {e}", flush=True)
            await asyncio.sleep(3600)


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _sync_wiki_after_post_send(approval: dict, kind: str = 'accept'):
    """
    Push wiki changes produced by a POST_SEND to GitHub (best-effort).

    Called after call_claude() returns from an accept/done flow. Claude may
    have added an interaction log row, created a lead file, or updated a
    contact record. We commit whatever diff is present, with a message
    describing the approval that caused it.
    """
    try:
        sender = (approval.get('sender_name') or approval.get('identifier') or 'unknown')[:60]
        channel = approval.get('channel') or 'unknown'
        summary = f"{kind}: {channel} reply to {sender}"
        backup_sync.sync_wiki(WIKI_DIR, summary)
    except Exception as e:
        print(f"[backup_sync] sync error (non-fatal): {e}", flush=True)


def call_claude(prompt: str) -> Optional[str]:
    claude_cfg = CONFIG.get('claude', {})
    bin_path = os.path.expanduser(claude_cfg.get('bin', 'claude'))
    model = claude_cfg.get('model', 'claude-sonnet-4-6')
    flags = claude_cfg.get('flags', [])
    cmd = [bin_path] + flags + ['--model', model, '-p', prompt]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=180, cwd=str(PROJECT_DIR)
        )
        return result.stdout.strip() if result.returncode == 0 else None
    except Exception:
        return None


def parse_md_table(content: str) -> list[dict]:
    """Parse the first markdown table in a file into a list of dicts."""
    lines = content.split('\n')
    headers = []
    rows = []
    found_header = False

    for line in lines:
        if not line.strip().startswith('|'):
            if found_header:
                break
            continue
        cells = [c.strip() for c in line.split('|')[1:-1]]
        if not cells:
            continue
        if not found_header:
            headers = cells
            found_header = True
        elif all(c.startswith('-') or c.startswith(':') for c in cells if c):
            continue  # separator row
        else:
            if len(cells) == len(headers):
                rows.append(dict(zip(headers, cells)))

    return rows


def extract_md_link_file(cell: str) -> Optional[str]:
    """Extract filename from a markdown link like [name.md](name.md)"""
    m = re.search(r'\[.*?\]\((.*?)\)', cell)
    return m.group(1) if m else None


def strip_emoji_status(text: str) -> str:
    return re.sub(r'[🔴🟡🟢⚠️]', '', text).strip()


def time_ago(dt_str: str) -> str:
    try:
        dt = datetime.strptime(dt_str, '%Y-%m-%d %H:%M:%S')
        diff = int((datetime.utcnow() - dt).total_seconds())
        if diff < 60:
            return f"{diff}s ago"
        elif diff < 3600:
            return f"{diff // 60}m ago"
        elif diff < 86400:
            return f"{diff // 3600}h ago"
        else:
            return f"{diff // 86400}d ago"
    except Exception:
        return dt_str


# ------------------------------------------------------------------
# Routes — shell
# ------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def root():
    return (PROJECT_DIR / "static" / "index.html").read_text()


# ------------------------------------------------------------------
# Routes — status
# ------------------------------------------------------------------

@app.get("/api/status")
async def status():
    import subprocess as sp
    result = sp.run(['pgrep', '-f', 'bridge.py'], capture_output=True, text=True)
    bridge_running = result.returncode == 0
    pending_count = len(db.get_approvals('pending'))
    return {
        "bridge": "running" if bridge_running else "stopped",
        "pending_approvals": pending_count,
        "business": BUSINESS_NAME,
    }


# ------------------------------------------------------------------
# Routes — approvals
# ------------------------------------------------------------------

@app.get("/api/approvals")
async def list_approvals():
    approvals = db.get_approvals('pending')
    for a in approvals:
        a['time_ago'] = time_ago(a['created_at'])
    return approvals


@app.get("/api/approvals/{approval_id}")
async def get_approval(approval_id: str):
    approval = db.get_approval(approval_id)
    if not approval:
        raise HTTPException(status_code=404, detail="Approval not found")
    approval['time_ago'] = time_ago(approval['created_at'])
    return approval


class DraftUpdate(BaseModel):
    draft: str


@app.post("/api/approvals/{approval_id}/draft")
async def update_draft(approval_id: str, body: DraftUpdate):
    approval = db.get_approval(approval_id)
    if not approval:
        raise HTTPException(status_code=404, detail="Approval not found")
    db.update_approval(approval_id, draft=body.draft, was_edited=1)
    return {"ok": True}


def _send_outbound(approval: dict) -> None:
    """
    Dispatch an approved draft to the external channel.

    Raises HTTPException on failure with the same status codes the UI depends on:
      - 400 missing identifier
      - 409 outside_window (Meta channels only; client switches to escape-hatch)
      - 502 send failed (upstream API error)
      - 503 WhatsApp sidecar unreachable

    Returns None silently for channels where there's no API to call (web,
    telegram, email) — those rely on the owner to relay the message manually.
    """
    channel = approval.get('channel')

    if channel == 'whatsapp':
        if not approval.get('identifier'):
            raise HTTPException(status_code=400, detail="Missing recipient identifier")
        try:
            resp = _rq.post(
                f"{WA_SIDECAR_URL}/send",
                json={"to": approval['identifier'], "text": approval['draft']},
                timeout=20,
            )
            if not resp.ok:
                try:
                    err = resp.json().get('error') or resp.text
                except Exception:
                    err = resp.text
                raise HTTPException(status_code=502, detail=f"WhatsApp send failed: {err}")
        except _rq.exceptions.ConnectionError:
            raise HTTPException(status_code=503, detail="WhatsApp service is not reachable")
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"WhatsApp send error: {e}")
        return

    if channel in ('messenger', 'instagram'):
        if not approval.get('identifier'):
            raise HTTPException(status_code=400, detail="Missing recipient identifier")
        if not _meta_window_open(approval.get('last_inbound_at')):
            raise HTTPException(status_code=409, detail="outside_window")
        _meta_send(channel, approval['identifier'], approval['draft'])
        return

    # web / telegram / email — nothing to send; caller relays manually.
    return


def _run_post_send(approval: dict, kind: str) -> None:
    """
    Fire the POST_SEND Claude prompt and sync the resulting wiki diff to GitHub.

    Always best-effort: errors inside the POST_SEND flow never surface to the
    caller, because the message has already been sent by the time we get here.
    The worst case is a missed wiki interaction-log row, which the owner can
    add by hand later.
    """
    try:
        is_new = 'New contact' in (approval.get('analysis') or '')
        prompt = (
            f"[POST_SEND]\n"
            f"contact_identifier: {approval.get('identifier')}\n"
            f"identifier_type: {approval.get('identifier_type')}\n"
            f"channel: {approval.get('channel')}\n"
            f"is_new_contact: {'true' if is_new else 'false'}\n"
            f"contact_file: NONE\n"
            f"original_message: {approval.get('original_message')}\n"
            f"sent_reply: {approval.get('draft')}"
        )
        call_claude(prompt)
    except Exception as e:
        print(f"[post_send] Claude error (non-fatal): {e}", flush=True)
    _sync_wiki_after_post_send(approval, kind=kind)


@app.post("/api/approvals/{approval_id}/accept")
async def accept_approval(approval_id: str):
    approval = db.get_approval(approval_id)
    if not approval:
        raise HTTPException(status_code=404, detail="Approval not found")
    if approval['status'] != 'pending':
        raise HTTPException(status_code=400, detail="Approval already actioned")

    # Dispatch via the channel's API (WhatsApp sidecar / Meta Graph).
    # Raises HTTPException on failure, BEFORE we mark accepted, so the owner
    # can retry or fall through to the escape-hatch flow.
    _send_outbound(approval)

    db.update_approval(approval_id, status='accepted')
    db.log_event(approval['identifier'], approval['identifier_type'],
                 approval['channel'], 'out', 'message_sent',
                 approval['draft'][:100])

    _run_post_send(approval, kind='accept')

    return {"ok": True, "draft": approval['draft']}


@app.post("/api/approvals/{approval_id}/reject")
async def reject_approval(approval_id: str):
    approval = db.get_approval(approval_id)
    if not approval:
        raise HTTPException(status_code=404, detail="Approval not found")
    db.update_approval(approval_id, status='rejected')
    db.log_event(approval['identifier'], approval['identifier_type'],
                 approval['channel'], 'in', 'rejected', 'Draft rejected by owner')
    return {"ok": True}


@app.post("/api/approvals/{approval_id}/mark-awaiting-done")
async def mark_awaiting_done(approval_id: str):
    """
    Client-initiated flip into the manual-send (escape-hatch) flow. The client
    has already copied the draft to clipboard and opened the platform's chat
    in a new tab; this marks the approval so it stays visible with a Done
    button instead of being treated as unactioned.
    """
    approval = db.get_approval(approval_id)
    if not approval:
        raise HTTPException(status_code=404, detail="Approval not found")
    if approval['status'] != 'pending':
        raise HTTPException(status_code=400, detail="Approval already actioned")
    db.update_approval(approval_id, manual_send_state='awaiting_done')
    return {"ok": True, "state": "awaiting_done"}


@app.post("/api/approvals/{approval_id}/done")
async def mark_done(approval_id: str):
    """
    Owner has manually sent the message in the external platform. Close the
    loop: mark accepted, log outbound, run POST_SEND for wiki/calendar updates.
    """
    approval = db.get_approval(approval_id)
    if not approval:
        raise HTTPException(status_code=404, detail="Approval not found")
    if approval['status'] == 'accepted':
        return {"ok": True, "already": True}
    if approval.get('manual_send_state') != 'awaiting_done':
        raise HTTPException(status_code=400, detail="Approval is not awaiting Done")

    db.update_approval(approval_id, status='accepted', manual_send_state=None)
    db.log_event(
        approval['identifier'], approval['identifier_type'], approval['channel'],
        'out', 'message_sent_manual', approval['draft'][:100],
    )

    _run_post_send(approval, kind='done')

    return {"ok": True}


class EditRequest(BaseModel):
    instructions: str


@app.post("/api/approvals/{approval_id}/edit")
async def edit_approval(approval_id: str, body: EditRequest):
    approval = db.get_approval(approval_id)
    if not approval:
        raise HTTPException(status_code=404, detail="Approval not found")

    prompt = (
        f"[EDIT_DRAFT]\n"
        f"contact_identifier: {approval['identifier']}\n"
        f"original_message: {approval['original_message']}\n"
        f"previous_draft: {approval['draft']}\n"
        f"edit_instructions: {body.instructions}"
    )
    response = call_claude(prompt)
    if not response:
        raise HTTPException(status_code=500, detail="Claude did not respond")

    draft_match = re.search(r'===DRAFT===(.*?)===END===', response, re.DOTALL)
    new_draft = draft_match.group(1).strip() if draft_match else response.strip()

    db.update_approval(approval_id, draft=new_draft, was_edited=1)
    return {"draft": new_draft}


# ------------------------------------------------------------------
# Routes — submit external message via web
# ------------------------------------------------------------------

class InboxSubmit(BaseModel):
    sender_name: str
    identifier: str = ''
    identifier_type: str = 'phone'
    channel: str = 'web'
    message: str


@app.post("/api/inbox/submit")
async def inbox_submit(body: InboxSubmit):
    """Staff enters an incoming customer message — queues it and runs Claude analysis in background."""
    approval_id = str(uuid.uuid4())[:8]

    # Create a placeholder approval immediately
    db.create_approval(
        approval_id=approval_id,
        identifier=body.identifier or body.sender_name,
        identifier_type=body.identifier_type,
        channel=body.channel,
        sender_name=body.sender_name,
        original_message=body.message,
        analysis='Analysing...',
        draft='Generating draft...',
    )
    db.log_event(body.identifier, body.identifier_type, body.channel,
                 'in', 'message_received', body.message[:100])

    # Run Claude analysis in background
    asyncio.create_task(_analyse_inbox(approval_id, body))

    return {"id": approval_id, "status": "analysing"}


async def _analyse_inbox(approval_id: str, body: InboxSubmit):
    """Background task: call Claude to analyse the message and update the approval."""
    prompt = (
        f"[EXTERNAL]\n\n"
        f"channel: {body.channel}\n"
        f"identifier: {body.identifier}\n"
        f"identifier_type: {body.identifier_type}\n"
        f"sender_name: {body.sender_name}\n"
        f"timestamp: {datetime.now().isoformat()}\n\n"
        f"message:\n{body.message}"
    )

    claude_cfg = CONFIG.get('claude', {})
    bin_path = os.path.expanduser(claude_cfg.get('bin', 'claude'))
    model = claude_cfg.get('model', 'claude-sonnet-4-6')
    flags = claude_cfg.get('flags', [])
    cmd = [bin_path] + flags + ['--model', model, '-p', prompt]

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=str(PROJECT_DIR),
    )
    stdout, _ = await proc.communicate()
    response = stdout.decode('utf-8', errors='replace').strip()

    if not response:
        db.update_approval(approval_id, analysis='Claude did not respond', draft='[No draft]')
        return

    analysis_match = re.search(r'\*📋 ANALYSIS\*(.*?)===DRAFT===', response, re.DOTALL)
    draft_match = re.search(r'===DRAFT===(.*?)===END===', response, re.DOTALL)
    intent_match = re.search(r'===INTENT===(.*?)===END===', response, re.DOTALL)
    analysis = analysis_match.group(1).strip() if analysis_match else ''
    draft = draft_match.group(1).strip() if draft_match else response.strip()
    if not draft:
        draft = "[No draft generated — see analysis]"
    intent_label = _normalise_intent_label(intent_match.group(1) if intent_match else '')

    db.update_approval(approval_id, analysis=analysis, draft=draft, intent_label=intent_label)
    if intent_label:
        db.upsert_pattern(intent_label)

    # Auto-approval bypass: if this intent has been promoted to 'auto' AND the
    # sender is a known contact, send the draft immediately instead of queueing
    # for owner review. Safety rails live in response_patterns.should_auto_send.
    if response_patterns.should_auto_send(intent_label, analysis):
        approval = db.get_approval(approval_id)
        if approval and approval.get('status') == 'pending':
            try:
                _send_outbound(approval)
            except HTTPException as e:
                # Send failed — leave pending, attach note for the owner.
                db.update_approval(
                    approval_id,
                    error_note=f"auto-send failed: {e.detail}",
                )
                return
            except Exception as e:
                db.update_approval(approval_id, error_note=f"auto-send error: {e}")
                return

            db.update_approval(approval_id, status='accepted', kind='auto')
            db.log_event(
                approval['identifier'], approval['identifier_type'],
                approval['channel'], 'out', 'auto_sent',
                approval['draft'][:100],
            )
            _run_post_send(approval, kind='auto')


def _normalise_intent_label(raw: str) -> str:
    """Sanitise AI-generated intent labels to [a-z0-9-], max 80 chars. Empty → ''."""
    if not raw:
        return ''
    s = raw.strip().lower()
    # Collapse whitespace to single hyphen
    s = re.sub(r'\s+', '-', s)
    # Drop anything outside the allowed character set
    s = re.sub(r'[^a-z0-9-]', '', s)
    # Collapse repeated hyphens, trim leading/trailing
    s = re.sub(r'-+', '-', s).strip('-')
    return s[:80]


# ------------------------------------------------------------------
# Routes — AI chat
# ------------------------------------------------------------------

class ChatRequest(BaseModel):
    message: str


@app.post("/api/chat")
async def chat(body: ChatRequest):
    prompt = f"[INTERNAL]\n\n{body.message}"
    response = call_claude(prompt)
    if not response:
        raise HTTPException(status_code=500, detail="Claude did not respond")
    db.save_chat(body.message, response)
    return {"response": response}


@app.get("/api/chat/stream")
async def chat_stream(message: str):
    """SSE stream that runs claude as a subprocess and pipes stdout chunks to client."""
    async def event_gen():
        claude_cfg = CONFIG.get('claude', {})
        bin_path = os.path.expanduser(claude_cfg.get('bin', 'claude'))
        model = claude_cfg.get('model', 'claude-sonnet-4-6')
        flags = claude_cfg.get('flags', [])
        prompt = f"[INTERNAL]\n\n{message}"
        cmd = [bin_path] + flags + ['--model', model, '-p', prompt]

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(PROJECT_DIR),
        )
        full = []
        try:
            assert proc.stdout is not None
            while True:
                chunk = await proc.stdout.read(256)
                if not chunk:
                    break
                text = chunk.decode('utf-8', errors='replace')
                full.append(text)
                # SSE: each event = "data: <json>\n\n"
                payload = json.dumps({"chunk": text})
                yield f"data: {payload}\n\n"
            await proc.wait()
        except asyncio.CancelledError:
            proc.kill()
            raise
        # Persist completed exchange + tell client we're done
        answer = ''.join(full).strip()
        if answer:
            db.save_chat(message, answer)
        yield f"data: {json.dumps({'done': True})}\n\n"

    return StreamingResponse(event_gen(), media_type='text/event-stream')


@app.get("/api/chat/history")
async def chat_history():
    return db.get_chat_history(limit=50)


# ------------------------------------------------------------------
# Routes — compose (proactive outbound)
# ------------------------------------------------------------------

class ComposeRequest(BaseModel):
    contact_type: str
    slug: str
    intent: str


@app.post("/api/compose")
async def compose(body: ComposeRequest):
    """Generate a proactive outbound draft for a contact and queue it for approval."""
    type_to_path = {c["type"]: PROJECT_DIR / c["path"] for c in CONTACTS_CONFIG}
    folder = type_to_path.get(body.contact_type)
    if not folder:
        raise HTTPException(status_code=404, detail="Unknown contact type")

    md_file = folder / f"{body.slug}.md"
    if not md_file.exists():
        raise HTTPException(status_code=404, detail="Contact not found")

    content = md_file.read_text()

    # Try to extract identifier from the file
    identifier = ''
    identifier_type = 'unknown'
    sender_name = body.slug.replace('-', ' ').title()
    for line in content.splitlines():
        l = line.strip().lstrip('-').strip()
        if l.lower().startswith('**phone'):
            identifier = l.split(':', 1)[-1].strip(' *')
            identifier_type = 'phone'
            break
        if l.lower().startswith('**whatsapp'):
            identifier = l.split(':', 1)[-1].strip(' *')
            identifier_type = 'whatsapp'
            break
        if l.lower().startswith('**email'):
            identifier = l.split(':', 1)[-1].strip(' *')
            identifier_type = 'email'
            break

    # Match a name line if present
    for line in content.splitlines():
        if line.startswith('# '):
            sender_name = line[2:].strip()
            break

    prompt = (
        f"[COMPOSE]\n"
        f"contact_file: {md_file.relative_to(PROJECT_DIR)}\n"
        f"intent: {body.intent}\n\n"
        f"Read the contact file, then output:\n"
        f"*📋 ANALYSIS*\n"
        f"[Brief context on this contact and what we're proactively reaching out about]\n\n"
        f"===DRAFT===\n"
        f"[Friendly outbound message — plain text, 3-5 sentences. Sign off as \"— {BUSINESS_NAME}\"]\n"
        f"===END==="
    )
    response = call_claude(prompt)
    if not response:
        raise HTTPException(status_code=500, detail="Claude did not respond")

    analysis_match = re.search(r'\*📋 ANALYSIS\*(.*?)===DRAFT===', response, re.DOTALL)
    draft_match = re.search(r'===DRAFT===(.*?)===END===', response, re.DOTALL)
    analysis = analysis_match.group(1).strip() if analysis_match else ''
    draft = draft_match.group(1).strip() if draft_match else response.strip()

    approval_id = str(uuid.uuid4())
    db.create_approval(
        approval_id=approval_id,
        identifier=identifier or body.slug,
        identifier_type=identifier_type,
        channel='web',
        sender_name=sender_name,
        original_message=f"[Compose intent] {body.intent}",
        analysis=analysis,
        draft=draft,
        kind='outbound',
    )
    return {"id": approval_id, "draft": draft, "analysis": analysis}


# ------------------------------------------------------------------
# Routes — CRM contacts
# ------------------------------------------------------------------

def load_contacts_from_index(index_path: Path, contact_type: str) -> list[dict]:
    if not index_path.exists():
        return []
    rows = parse_md_table(index_path.read_text())
    contacts = []
    for row in rows:
        # Find the file column (first column with a markdown link)
        file_col = None
        for val in row.values():
            fname = extract_md_link_file(val)
            if fname and fname.endswith('.md') and not fname.startswith('_'):
                file_col = fname
                break
        if not file_col:
            continue

        # Build a clean display record
        clean = {k: strip_emoji_status(v) for k, v in row.items()}
        clean['_file'] = file_col
        clean['_type'] = contact_type
        clean['_path'] = str(index_path.parent / file_col)

        # Status from any column containing status keywords
        status_raw = next((v for v in row.values()
                          if any(w in v for w in ['OVERDUE', 'Due', 'TODAY', 'Upcoming', 'New Lead'])), '')
        if 'OVERDUE' in status_raw or 'TODAY' in status_raw:
            clean['_status'] = 'urgent'
        elif 'Due' in status_raw:
            clean['_status'] = 'warning'
        else:
            clean['_status'] = 'ok'

        contacts.append(clean)
    return contacts


@app.get("/api/meta")
async def meta():
    """Returns business config needed by the frontend — contact types, labels, quick questions."""
    return {
        "business": BUSINESS_NAME,
        "contacts": [{"type": c["type"], "label": c["label"]} for c in CONTACTS_CONFIG],
        "quick_questions": CONFIG.get("quick_questions", [
            "Any urgent matters?",
            "Who needs follow-up?",
            "Today's schedule",
            "Stock levels",
            "Recent leads",
            "Overdue clients",
        ]),
    }


@app.get("/api/contacts")
async def list_contacts():
    contacts = []
    for c in CONTACTS_CONFIG:
        index_path = PROJECT_DIR / c["path"] / "_INDEX.md"
        contacts += load_contacts_from_index(index_path, c["type"])
    return contacts


@app.get("/api/contacts/{contact_type}/{slug}")
async def get_contact(contact_type: str, slug: str):
    type_to_path = {c["type"]: PROJECT_DIR / c["path"] for c in CONTACTS_CONFIG}
    folder = type_to_path.get(contact_type)
    if not folder:
        raise HTTPException(status_code=404, detail="Unknown contact type")

    md_file = folder / f"{slug}.md"
    if not md_file.exists():
        raise HTTPException(status_code=404, detail="Contact not found")

    content = md_file.read_text()

    # Render markdown to HTML
    try:
        import markdown
        html = markdown.markdown(content, extensions=['tables'])
    except ImportError:
        # Fallback: wrap in pre tag
        html = f"<pre>{content}</pre>"

    return {"slug": slug, "type": contact_type, "html": html, "raw": content}


# ------------------------------------------------------------------
# Routes — event log
# ------------------------------------------------------------------

@app.get("/api/events")
async def events():
    return db.get_event_log(limit=100)


# ------------------------------------------------------------------
# Routes — calendar
# ------------------------------------------------------------------

class CalendarEventCreate(BaseModel):
    title: str
    start_at: str
    end_at: str = None
    event_type: str = 'meeting'
    client_name: str = ''
    client_identifier: str = ''
    location: str = ''
    notes: str = ''


class CalendarEventUpdate(BaseModel):
    title: str = None
    start_at: str = None
    end_at: str = None
    event_type: str = None
    client_name: str = None
    client_identifier: str = None
    location: str = None
    notes: str = None
    status: str = None


@app.get("/api/calendar")
async def list_calendar_events(
    from_date: str = None,
    to_date: str = None,
):
    if not from_date:
        from_date = datetime.utcnow().strftime('%Y-%m-%d')
    if not to_date:
        # Default to 7 days from from_date
        from datetime import timedelta
        d = datetime.strptime(from_date, '%Y-%m-%d')
        to_date = (d + timedelta(days=7)).strftime('%Y-%m-%d')
    return db.get_calendar_events(from_date, to_date)


@app.post("/api/calendar")
async def create_calendar_event(body: CalendarEventCreate):
    event_id = str(uuid.uuid4())[:8]
    db.create_calendar_event(
        event_id=event_id,
        title=body.title,
        start_at=body.start_at,
        end_at=body.end_at,
        event_type=body.event_type,
        client_name=body.client_name,
        client_identifier=body.client_identifier,
        location=body.location,
        notes=body.notes,
    )
    return {"id": event_id, "status": "created"}


@app.put("/api/calendar/{event_id}")
async def update_calendar_event(event_id: str, body: CalendarEventUpdate):
    existing = db.get_calendar_event(event_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Event not found")
    updates = {k: v for k, v in body.dict().items() if v is not None}
    if not updates:
        return {"status": "no changes"}
    db.update_calendar_event(event_id, **updates)
    return {"status": "updated"}


@app.delete("/api/calendar/{event_id}")
async def delete_calendar_event(event_id: str):
    existing = db.get_calendar_event(event_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Event not found")
    db.delete_calendar_event(event_id)
    return {"status": "cancelled"}


# ------------------------------------------------------------------
# Routes — feedback
# ------------------------------------------------------------------

class FeedbackSubmit(BaseModel):
    request: str
    workaround: str = ''
    frequency: str = ''
    importance: str = ''
    contact: str = ''

FEEDBACK_FILE = Path('/app/data/feedback.md')


@app.post("/api/feedback")
async def submit_feedback(body: FeedbackSubmit, req: Request):
    host = req.headers.get('host', 'unknown')
    ts = datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')

    freq_labels = {
        'daily': 'Every day', 'weekly': 'A few times a week',
        'occasionally': 'Occasionally', 'rarely': 'Rarely',
    }
    imp_labels = {
        'very_disappointed': 'Very disappointed',
        'somewhat_disappointed': 'Somewhat disappointed',
        'not_bothered': 'Not bothered',
    }

    entry = (
        f"\n---\n\n"
        f"### {ts} — {host}\n\n"
        f"**Request:** {body.request}\n\n"
        f"**Current workaround:** {body.workaround or '—'}\n\n"
        f"**Frequency:** {freq_labels.get(body.frequency, body.frequency or '—')}  \n"
        f"**Importance:** {imp_labels.get(body.importance, body.importance or '—')}\n\n"
        f"**Contact:** {body.contact or '—'}\n"
    )

    # Append to feedback.md
    if not FEEDBACK_FILE.exists():
        FEEDBACK_FILE.write_text('# Feature Requests & Feedback\n')
    with open(FEEDBACK_FILE, 'a') as f:
        f.write(entry)

    return {"status": "saved"}


# ------------------------------------------------------------------
# Routes — WhatsApp (Baileys sidecar integration)
# ------------------------------------------------------------------

import requests as _rq

WA_SIDECAR_URL = os.environ.get('WHATSAPP_SIDECAR_URL', 'http://whatsapp:3000')
WA_WEBHOOK_SECRET = os.environ.get('WHATSAPP_WEBHOOK_SECRET', '')


def _sidecar(method: str, path: str, **kwargs):
    try:
        resp = _rq.request(method, f"{WA_SIDECAR_URL}{path}", timeout=10, **kwargs)
        return JSONResponse(status_code=resp.status_code, content=resp.json())
    except _rq.exceptions.ConnectionError:
        return JSONResponse(status_code=503, content={
            "state": "unreachable",
            "error": "WhatsApp service is not running",
        })
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/api/whatsapp/status")
async def wa_status():
    return _sidecar('GET', '/status')


@app.get("/api/whatsapp/qr")
async def wa_qr():
    return _sidecar('GET', '/qr')


@app.post("/api/whatsapp/connect")
async def wa_connect():
    return _sidecar('POST', '/connect')


@app.post("/api/whatsapp/disconnect")
async def wa_disconnect():
    return _sidecar('POST', '/disconnect')


class WhatsAppInbound(BaseModel):
    channel: str = 'whatsapp'
    identifier: str
    identifier_type: str = 'whatsapp'
    sender_name: str = ''
    text: str
    timestamp: Optional[int] = None
    raw_id: Optional[str] = None


@app.post("/api/webhook/whatsapp")
async def wa_webhook(body: WhatsAppInbound, req: Request):
    """
    Inbound message from the Baileys sidecar. Creates a pending approval
    and kicks off the Claude analysis (same path as the in-dashboard inbox
    submit — both end up in the approval queue).
    """
    # Shared-secret check. Sidecar is only reachable on the tenant network,
    # but the secret adds defence-in-depth and prevents replay from a
    # misconfigured CRM_WEBHOOK_URL.
    provided = req.headers.get('X-Webhook-Secret', '')
    if WA_WEBHOOK_SECRET and provided != WA_WEBHOOK_SECRET:
        raise HTTPException(status_code=403, detail="invalid webhook secret")

    approval_id = str(uuid.uuid4())[:8]
    db.create_approval(
        approval_id=approval_id,
        identifier=body.identifier,
        identifier_type=body.identifier_type,
        channel=body.channel,
        sender_name=body.sender_name or body.identifier,
        original_message=body.text,
        analysis='Analysing...',
        draft='Generating draft...',
    )
    db.log_event(body.identifier, body.identifier_type, body.channel,
                 'in', 'message_received', body.text[:100])

    inbox_body = InboxSubmit(
        sender_name=body.sender_name or body.identifier,
        identifier=body.identifier,
        identifier_type=body.identifier_type,
        channel=body.channel,
        message=body.text,
    )
    asyncio.create_task(_analyse_inbox(approval_id, inbox_body))

    return {"id": approval_id, "status": "queued"}


# ------------------------------------------------------------------
# Routes — Meta (Messenger + Instagram) connectors
# ------------------------------------------------------------------
# Shared env:
#   META_APP_ID / META_APP_SECRET — from Meta App Dashboard
#   META_VERIFY_TOKEN — arbitrary string, must match what you configure
#       in the Meta App's webhook subscription
#   META_REDIRECT_URI — must match the OAuth redirect URI registered
#       in the Meta App (e.g. https://hvac.chiefpa.com/api/channels/meta/callback)
#   META_GRAPH_VERSION — defaults to v18.0

import hashlib
import hmac
import time
import secrets as _secrets
from datetime import timedelta

META_APP_ID = os.environ.get('META_APP_ID', '')
META_APP_SECRET = os.environ.get('META_APP_SECRET', '')
META_VERIFY_TOKEN = os.environ.get('META_VERIFY_TOKEN', '')
META_GRAPH_VERSION = os.environ.get('META_GRAPH_VERSION', 'v18.0')
META_REDIRECT_URI = os.environ.get('META_REDIRECT_URI', '')

META_GRAPH_BASE = f"https://graph.facebook.com/{META_GRAPH_VERSION}"
META_OAUTH_SCOPES = [
    'pages_messaging',
    'pages_manage_metadata',
    'pages_show_list',
    'instagram_basic',
    'instagram_manage_messages',
    'business_management',
]

# 24h window constant (Meta's free-form customer-service window)
META_WINDOW_SECONDS = 24 * 60 * 60


def _meta_configured() -> bool:
    return bool(META_APP_ID and META_APP_SECRET and META_VERIFY_TOKEN)


def _verify_meta_signature(raw_body: bytes, signature_header: str) -> bool:
    """Verify X-Hub-Signature-256 = sha256=<hex> against the raw request body."""
    if not signature_header or not signature_header.startswith('sha256='):
        return False
    if not META_APP_SECRET:
        return False
    expected = hmac.new(
        META_APP_SECRET.encode(),
        raw_body,
        hashlib.sha256,
    ).hexdigest()
    provided = signature_header.split('=', 1)[1]
    return hmac.compare_digest(expected, provided)


def _extract_text(message: dict) -> Optional[str]:
    """Extract a displayable text from a Messenger/Instagram message payload."""
    if not message:
        return None
    text = message.get('text')
    if text:
        return text
    attachments = message.get('attachments') or []
    if attachments:
        kinds = {a.get('type', 'file') for a in attachments}
        if 'image' in kinds:
            return '[image]'
        if 'video' in kinds:
            return '[video]'
        if 'audio' in kinds:
            return '[voice note]'
        if 'location' in kinds:
            return '[location]'
        return f"[{next(iter(kinds))}]"
    return None


# ----- Webhook receiver -----------------------------------------------------

@app.get("/api/webhook/meta")
async def meta_webhook_verify(req: Request):
    """
    Meta's webhook verification handshake (one-time on setup).
    Meta sends dotted query params (hub.mode, hub.challenge, hub.verify_token)
    which FastAPI cannot map via regular parameter binding — read them raw.
    """
    q = req.query_params
    mode = q.get('hub.mode')
    token = q.get('hub.verify_token')
    challenge = q.get('hub.challenge')
    if mode == 'subscribe' and token and token == META_VERIFY_TOKEN:
        from fastapi.responses import PlainTextResponse
        return PlainTextResponse(challenge or '')
    raise HTTPException(status_code=403, detail="verify token mismatch")


@app.post("/api/webhook/meta")
async def meta_webhook_receive(req: Request):
    raw = await req.body()

    # Signature check — skip if Meta isn't configured yet (dev)
    if _meta_configured():
        sig = req.headers.get('X-Hub-Signature-256', '')
        if not _verify_meta_signature(raw, sig):
            raise HTTPException(status_code=403, detail="invalid signature")

    try:
        payload = json.loads(raw.decode('utf-8') or '{}')
    except Exception:
        raise HTTPException(status_code=400, detail="malformed json")

    obj = payload.get('object')
    if obj == 'page':
        asyncio.create_task(_process_meta_entries(payload.get('entry') or [], channel='messenger'))
    elif obj == 'instagram':
        asyncio.create_task(_process_meta_entries(payload.get('entry') or [], channel='instagram'))
    else:
        # Unknown object — acknowledge to avoid Meta retrying forever
        print(f"[meta_webhook] ignoring object={obj}")

    # Must 200 within ~20s
    return {"received": True}


async def _process_meta_entries(entries: list, channel: str):
    """Convert Meta webhook entries into approvals + kick AI analysis."""
    for entry in entries:
        page_id = entry.get('id')
        for msg_event in (entry.get('messaging') or []):
            try:
                await _ingest_meta_message(channel, page_id, msg_event)
            except Exception as e:
                print(f"[meta_ingest] failed: {e}")


async def _ingest_meta_message(channel: str, page_id: str, msg_event: dict):
    """Single message event → pending_approval + async AI analysis."""
    sender_id = (msg_event.get('sender') or {}).get('id')
    message = msg_event.get('message') or {}

    # Skip echoes (Meta replaying our own sends) and read/delivery events
    if message.get('is_echo'):
        return
    if not sender_id or not message:
        return

    text = _extract_text(message)
    if not text:
        return

    # Timestamp — Meta sends ms since epoch
    ts_ms = msg_event.get('timestamp') or int(time.time() * 1000)
    last_inbound_at = datetime.utcfromtimestamp(ts_ms / 1000).strftime('%Y-%m-%d %H:%M:%S')

    # Try to resolve a nicer sender name (best-effort; don't block on failure)
    sender_name = await _resolve_meta_sender_name(channel, page_id, sender_id) or sender_id

    # Upsert the thread anchor
    db.upsert_message_thread(
        channel=channel,
        identifier=sender_id,
        last_inbound_at=last_inbound_at,
        page_id=page_id,
        thread_id=msg_event.get('thread_id'),
    )

    approval_id = str(uuid.uuid4())[:8]
    db.create_approval(
        approval_id=approval_id,
        identifier=sender_id,
        identifier_type=channel,
        channel=channel,
        sender_name=sender_name,
        original_message=text,
        analysis='Analysing...',
        draft='Generating draft...',
        last_inbound_at=last_inbound_at,
        thread_id=msg_event.get('thread_id'),
    )
    db.log_event(sender_id, channel, channel, 'in', 'message_received', text[:100])

    # Kick AI analysis via the existing inbox pipeline
    inbox_body = InboxSubmit(
        sender_name=sender_name,
        identifier=sender_id,
        identifier_type=channel,
        channel=channel,
        message=text,
    )
    asyncio.create_task(_analyse_inbox(approval_id, inbox_body))


async def _resolve_meta_sender_name(channel: str, page_id: str, sender_id: str) -> Optional[str]:
    """Best-effort display-name lookup via the Page's access token."""
    try:
        conn = db.get_channel_connection(channel, decrypt_token=True)
        if not conn or not conn.get('access_token'):
            return None
        # Messenger: GET /{PSID}?fields=name — supported with pages_messaging
        # Instagram: not reliably supported on basic scope; return None to fall back
        if channel == 'messenger':
            resp = _rq.get(
                f"{META_GRAPH_BASE}/{sender_id}",
                params={'fields': 'name', 'access_token': conn['access_token']},
                timeout=5,
            )
            if resp.ok:
                return (resp.json() or {}).get('name')
    except Exception:
        pass
    return None


# ----- OAuth (Facebook Login) -----------------------------------------------

def _sign_state(payload: str) -> str:
    """Sign the CSRF state with the app secret so we can verify on callback."""
    sig = hmac.new(
        (META_APP_SECRET or 'dev').encode(),
        payload.encode(),
        hashlib.sha256,
    ).hexdigest()[:32]
    return f"{payload}.{sig}"


def _verify_state(state: str) -> bool:
    try:
        payload, sig = state.rsplit('.', 1)
        expected = hmac.new(
            (META_APP_SECRET or 'dev').encode(),
            payload.encode(),
            hashlib.sha256,
        ).hexdigest()[:32]
        if not hmac.compare_digest(expected, sig):
            return False
        # Payload format: "<nonce>:<issued_at>"
        issued_at = int(payload.split(':')[-1])
        if time.time() - issued_at > 600:  # 10 min
            return False
        return True
    except Exception:
        return False


@app.get("/api/channels/meta/login-url")
async def meta_login_url():
    if not _meta_configured():
        raise HTTPException(status_code=503, detail="Meta App not configured on this tenant")
    if not META_REDIRECT_URI:
        raise HTTPException(status_code=503, detail="META_REDIRECT_URI not set")
    state = _sign_state(f"{_secrets.token_urlsafe(16)}:{int(time.time())}")
    url = (
        f"https://www.facebook.com/{META_GRAPH_VERSION}/dialog/oauth"
        f"?client_id={META_APP_ID}"
        f"&redirect_uri={META_REDIRECT_URI}"
        f"&scope={','.join(META_OAUTH_SCOPES)}"
        f"&state={state}"
        f"&response_type=code"
    )
    return {"url": url, "state": state}


@app.get("/api/channels/meta/callback")
async def meta_callback(code: str = None, state: str = None, error: str = None, error_description: str = None):
    """Facebook OAuth redirect lands here. Exchange code, save tokens, redirect to UI."""
    from fastapi.responses import RedirectResponse
    if error:
        return RedirectResponse(url=f"/?meta_error={error}")
    if not code or not state or not _verify_state(state):
        raise HTTPException(status_code=403, detail="invalid state")
    if not _meta_configured() or not META_REDIRECT_URI:
        raise HTTPException(status_code=503, detail="Meta App not configured")

    # 1) Exchange code → short-lived user token
    token_resp = _rq.get(
        f"{META_GRAPH_BASE}/oauth/access_token",
        params={
            'client_id': META_APP_ID,
            'client_secret': META_APP_SECRET,
            'redirect_uri': META_REDIRECT_URI,
            'code': code,
        },
        timeout=15,
    )
    if not token_resp.ok:
        raise HTTPException(status_code=502, detail=f"token exchange failed: {token_resp.text}")
    short_token = token_resp.json().get('access_token')

    # 2) Exchange short-lived → long-lived user token (60 day)
    ll_resp = _rq.get(
        f"{META_GRAPH_BASE}/oauth/access_token",
        params={
            'grant_type': 'fb_exchange_token',
            'client_id': META_APP_ID,
            'client_secret': META_APP_SECRET,
            'fb_exchange_token': short_token,
        },
        timeout=15,
    )
    long_user_token = (ll_resp.json() or {}).get('access_token') or short_token

    # 3) List the user's Pages
    pages_resp = _rq.get(
        f"{META_GRAPH_BASE}/me/accounts",
        params={'access_token': long_user_token, 'fields': 'id,name,username,access_token,instagram_business_account'},
        timeout=15,
    )
    pages = (pages_resp.json() or {}).get('data') or []
    if not pages:
        return RedirectResponse(url="/?meta_error=no_pages")

    # For v1: take the first Page. (Multi-page picker is a later enhancement.)
    page = pages[0]
    page_id = page.get('id')
    page_name = page.get('name', '')
    page_username = page.get('username', '')
    page_token = page.get('access_token')
    ig_id = (page.get('instagram_business_account') or {}).get('id', '')

    # 4) Subscribe the Page to our app's webhook
    try:
        _rq.post(
            f"{META_GRAPH_BASE}/{page_id}/subscribed_apps",
            params={
                'subscribed_fields': 'messages,messaging_postbacks,messaging_optins',
                'access_token': page_token,
            },
            timeout=10,
        )
    except Exception as e:
        print(f"[meta_oauth] subscribe failed: {e}")
        # Non-fatal — user can re-subscribe later

    # 5) Save both Messenger and (if present) Instagram connections
    db.save_channel_connection(
        channel='messenger',
        page_id=page_id,
        page_name=page_name,
        page_username=page_username,
        access_token=page_token,
        scopes=','.join(META_OAUTH_SCOPES),
    )
    if ig_id:
        db.save_channel_connection(
            channel='instagram',
            page_id=page_id,
            page_name=page_name,
            page_username=page_username,
            ig_business_account_id=ig_id,
            access_token=page_token,
            scopes=','.join(META_OAUTH_SCOPES),
        )

    return RedirectResponse(url="/?meta_connected=1")


@app.get("/api/channels/meta/status")
async def meta_status():
    return {
        "configured": _meta_configured(),
        "connections": db.list_channel_connections(),
    }


@app.post("/api/channels/meta/disconnect")
async def meta_disconnect(body: dict):
    channel = body.get('channel')
    if channel not in ('messenger', 'instagram'):
        raise HTTPException(status_code=400, detail="channel must be messenger|instagram")
    conn = db.get_channel_connection(channel, decrypt_token=True)
    if conn and conn.get('page_id') and conn.get('access_token'):
        try:
            _rq.delete(
                f"{META_GRAPH_BASE}/{conn['page_id']}/subscribed_apps",
                params={'access_token': conn['access_token']},
                timeout=10,
            )
        except Exception as e:
            print(f"[meta_disconnect] unsubscribe failed: {e}")
    db.delete_channel_connection(channel)
    return {"status": "disconnected"}


# ------------------------------------------------------------------
# Routes — backup status
# ------------------------------------------------------------------

@app.get("/api/backup/status")
async def backup_status():
    """Return info about the most recent wiki commit, for dashboard surfacing."""
    return backup_sync.last_commit_info(WIKI_DIR)


# ------------------------------------------------------------------
# Routes — response patterns (auto-approval)
# ------------------------------------------------------------------

@app.get("/api/patterns")
async def list_patterns():
    """Return every known intent pattern with computed eligibility stats."""
    return {"patterns": response_patterns.list_all_patterns()}


@app.post("/api/patterns/{intent_label}/enable")
async def enable_pattern(intent_label: str):
    """Promote a pattern to 'auto'. Allowed from 'learning' (if eligible) or 'manual_locked'."""
    pattern = db.get_pattern(intent_label)
    if not pattern:
        raise HTTPException(status_code=404, detail="Pattern not found")
    current = pattern.get('status', 'learning')
    if current == 'auto':
        return {"ok": True, "status": "auto", "already": True}
    if current == 'learning':
        stats = response_patterns.compute_pattern_stats(intent_label)
        if not stats['is_eligible']:
            raise HTTPException(status_code=400, detail="Pattern is not yet eligible")
    db.set_pattern_status(intent_label, 'auto')
    return {"ok": True, "status": "auto"}


@app.post("/api/patterns/{intent_label}/disable")
async def disable_pattern(intent_label: str):
    """Revert a pattern from 'auto' to 'manual_locked' so future matches queue again."""
    pattern = db.get_pattern(intent_label)
    if not pattern:
        raise HTTPException(status_code=404, detail="Pattern not found")
    if pattern.get('status') != 'auto':
        raise HTTPException(status_code=400, detail="Pattern is not currently auto")
    db.set_pattern_status(intent_label, 'manual_locked')
    return {"ok": True, "status": "manual_locked"}


@app.post("/api/patterns/{intent_label}/reset")
async def reset_pattern(intent_label: str):
    """Clear any lock/promotion and put the pattern back into 'learning'."""
    pattern = db.get_pattern(intent_label)
    if not pattern:
        raise HTTPException(status_code=404, detail="Pattern not found")
    db.set_pattern_status(intent_label, 'learning')
    return {"ok": True, "status": "learning"}


# ----- Outbound send (Graph API) --------------------------------------------

def _meta_send(channel: str, recipient_id: str, text: str) -> dict:
    """
    Send a free-form message via Graph API. Caller must have already
    verified we're inside the 24h window. Returns Meta's response dict
    on success or raises HTTPException on failure.
    """
    conn = db.get_channel_connection(channel, decrypt_token=True)
    if not conn or not conn.get('access_token'):
        raise HTTPException(status_code=503, detail=f"{channel} not connected")

    payload = {
        'recipient': {'id': recipient_id},
        'message': {'text': text},
        'messaging_type': 'RESPONSE',
    }
    if channel == 'instagram':
        payload['messaging_product'] = 'instagram'

    resp = _rq.post(
        f"{META_GRAPH_BASE}/me/messages",
        params={'access_token': conn['access_token']},
        json=payload,
        timeout=15,
    )
    if resp.ok:
        return resp.json()

    # Error handling: detect token-expired (code 190/200) and flip status
    try:
        err = resp.json().get('error') or {}
        code = err.get('code')
        if code in (190, 200):
            db.update_channel_connection(channel, status='needs_reconnect')
        detail = err.get('message') or resp.text
    except Exception:
        detail = resp.text
    raise HTTPException(status_code=502, detail=f"{channel} send failed: {detail}")


def _meta_window_open(last_inbound_at_str: str) -> bool:
    """Check whether the 24h window is still open."""
    if not last_inbound_at_str:
        return False
    try:
        last_in = datetime.strptime(last_inbound_at_str, '%Y-%m-%d %H:%M:%S')
    except ValueError:
        return False
    return (datetime.utcnow() - last_in) < timedelta(seconds=META_WINDOW_SECONDS)


# ------------------------------------------------------------------
# Entry point
# ------------------------------------------------------------------

if __name__ == '__main__':
    import uvicorn
    port = CONFIG.get('web', {}).get('port', 8080)
    uvicorn.run("web:app", host="0.0.0.0", port=port, reload=False)
