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

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import db
from channels.telegram import TelegramChannel

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

def get_channel() -> TelegramChannel:
    return TelegramChannel(CONFIG)


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

    # Send the draft to the customer via Telegram
    channel = get_channel()
    tg_cfg = CONFIG['channels']['telegram']
    external_topic = tg_cfg['topics']['external']

    from channels.base import OutboundMessage
    msg_out = OutboundMessage(text=approval['draft'], metadata={'topic_id': external_topic})

    from channels.base import InboundMessage
    original = InboundMessage(
        channel=approval['channel'],
        direction='external',
        text=approval['original_message'],
        identifier=approval['identifier'],
        identifier_type=approval['identifier_type'],
        sender_name=approval['sender_name'],
        metadata={'topic_id': external_topic}
    )
    channel.send_to_contact(msg_out, original)

    # Update DB
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

    return {"ok": True}


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
        channel='telegram',
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
# Entry point
# ------------------------------------------------------------------

if __name__ == '__main__':
    import uvicorn
    port = CONFIG.get('web', {}).get('port', 8080)
    uvicorn.run("web:app", host="0.0.0.0", port=port, reload=False)
