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
# Helpers
# ------------------------------------------------------------------

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
    db.update_approval(approval_id, draft=body.draft)
    return {"ok": True}


@app.post("/api/approvals/{approval_id}/accept")
async def accept_approval(approval_id: str):
    approval = db.get_approval(approval_id)
    if not approval:
        raise HTTPException(status_code=404, detail="Approval not found")
    if approval['status'] != 'pending':
        raise HTTPException(status_code=400, detail="Approval already actioned")

    # If this approval came from WhatsApp, actually send it via the sidecar.
    # On failure we bail out BEFORE marking accepted so the owner can retry.
    if approval['channel'] == 'whatsapp':
        if not approval.get('identifier'):
            raise HTTPException(status_code=400, detail="Missing recipient identifier")
        try:
            import requests as _r
            resp = _r.post(
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

    # Mark as accepted
    db.update_approval(approval_id, status='accepted')
    db.log_event(approval['identifier'], approval['identifier_type'],
                 approval['channel'], 'out', 'message_sent',
                 approval['draft'][:100])

    # Update CRM via Claude
    is_new = 'New contact' in (approval['analysis'] or '')
    prompt = (
        f"[POST_SEND]\n"
        f"contact_identifier: {approval['identifier']}\n"
        f"identifier_type: {approval['identifier_type']}\n"
        f"channel: {approval['channel']}\n"
        f"is_new_contact: {'true' if is_new else 'false'}\n"
        f"contact_file: NONE\n"
        f"original_message: {approval['original_message']}\n"
        f"sent_reply: {approval['draft']}"
    )
    call_claude(prompt)

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

    db.update_approval(approval_id, draft=new_draft)
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
    analysis = analysis_match.group(1).strip() if analysis_match else ''
    draft = draft_match.group(1).strip() if draft_match else response.strip()
    if not draft:
        draft = "[No draft generated — see analysis]"

    db.update_approval(approval_id, analysis=analysis, draft=draft)


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
# Entry point
# ------------------------------------------------------------------

if __name__ == '__main__':
    import uvicorn
    port = CONFIG.get('web', {}).get('port', 8080)
    uvicorn.run("web:app", host="0.0.0.0", port=port, reload=False)
