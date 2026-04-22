#!/usr/bin/env python3
"""
AI-PA CRM Bridge

Connects external channels (Telegram, future: WhatsApp, email) to the Claude AI assistant.

Flow:
  External message in  →  Claude analyses + drafts reply  →  Saved to DB  →  Telegram ping to owner
  Owner approves in web UI  →  Web server sends reply via Telegram  →  Claude updates CRM
  Internal message in Telegram  →  Claude answers  →  Posted back to internal topic
"""

import json
import logging
import os
import re
import subprocess
import sys
import time
import uuid
from datetime import datetime
from typing import Optional

from channels.base import InboundMessage, OutboundMessage
from channels.telegram import TelegramChannel
import db

# ------------------------------------------------------------------
# Config & logging
# ------------------------------------------------------------------

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(PROJECT_DIR, 'config.json')

with open(CONFIG_PATH) as f:
    CONFIG = json.load(f)

logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)


# ------------------------------------------------------------------
# Channel registry
# ------------------------------------------------------------------

CHANNEL_CLASSES = {
    'telegram': TelegramChannel,
    # 'whatsapp': WhatsAppChannel,  # future
    # 'email': EmailChannel,        # future
}


def build_channels() -> list:
    channels = []
    for name, cls in CHANNEL_CLASSES.items():
        if name in CONFIG.get('channels', {}):
            channels.append(cls(CONFIG))
            logger.info(f"Channel loaded: {name}")
    return channels


# ------------------------------------------------------------------
# Claude invocation
# ------------------------------------------------------------------

def call_claude(prompt: str) -> Optional[str]:
    claude_cfg = CONFIG.get('claude', {})
    bin_path = os.path.expanduser(claude_cfg.get('bin', 'claude'))
    model = claude_cfg.get('model', 'claude-sonnet-4-6')
    extra_flags = claude_cfg.get('flags', [])

    cmd = [bin_path] + extra_flags + ['--model', model, '-p', prompt]

    logger.info(f"Calling Claude ({model})...")
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=180, cwd=PROJECT_DIR
        )
        if result.returncode == 0:
            logger.info("Claude responded.")
            return result.stdout.strip()
        else:
            logger.error(f"Claude error (exit {result.returncode}): {result.stderr[:300]}")
            return None
    except subprocess.TimeoutExpired:
        logger.error("Claude timed out.")
        return None
    except FileNotFoundError:
        logger.error(f"Claude binary not found at: {bin_path}")
        return None
    except Exception as e:
        logger.error(f"Claude invocation failed: {e}")
        return None


# ------------------------------------------------------------------
# Prompt builders
# ------------------------------------------------------------------

def build_external_prompt(msg: InboundMessage) -> str:
    return (
        f"[EXTERNAL]\n\n"
        f"channel: {msg.channel}\n"
        f"identifier: {msg.identifier}\n"
        f"identifier_type: {msg.identifier_type}\n"
        f"sender_name: {msg.sender_name}\n"
        f"timestamp: {datetime.now().isoformat()}\n\n"
        f"message:\n{msg.text}"
    )


def build_internal_prompt(msg: InboundMessage) -> str:
    return f"[INTERNAL]\n\n{msg.text}"


def build_post_send_prompt(approval_id: str, identifier: str, identifier_type: str,
                           channel: str, original_message: str, sent_reply: str,
                           is_new: bool, contact_file: Optional[str]) -> str:
    return (
        f"[POST_SEND]\n"
        f"contact_identifier: {identifier}\n"
        f"identifier_type: {identifier_type}\n"
        f"channel: {channel}\n"
        f"is_new_contact: {'true' if is_new else 'false'}\n"
        f"contact_file: {contact_file or 'NONE'}\n"
        f"original_message: {original_message}\n"
        f"sent_reply: {sent_reply}"
    )


# ------------------------------------------------------------------
# Response parsing
# ------------------------------------------------------------------

def parse_claude_response(response: str) -> tuple[str, str]:
    draft_match = re.search(r'===DRAFT===(.*?)===END===', response, re.DOTALL)
    if not draft_match:
        return response.strip(), ''
    draft = draft_match.group(1).strip()
    analysis = response[:draft_match.start()].strip()
    analysis = re.sub(r'^\*?📋\s*ANALYSIS\*?\s*', '', analysis).strip()
    return analysis, draft


# ------------------------------------------------------------------
# Handle external message
# ------------------------------------------------------------------

def handle_external(msg: InboundMessage, channel) -> None:
    # Log incoming event
    db.log_event(msg.identifier or '', msg.identifier_type or '', msg.channel,
                 'in', 'message_received', msg.text[:100])

    prompt = build_external_prompt(msg)
    response = call_claude(prompt)

    if not response:
        channel.post_internal(f"⚠️ Claude did not respond to message from {msg.sender_name} ({msg.identifier}).")
        db.log_event(msg.identifier or '', msg.identifier_type or '', msg.channel,
                     'in', 'error', 'Claude did not respond')
        return

    analysis, draft = parse_claude_response(response)
    if not draft:
        draft = "[No draft generated — see analysis]"

    is_new = 'New contact' in analysis
    approval_id = str(uuid.uuid4())[:8]

    # Save to DB — web UI will show this
    db.create_approval(
        approval_id=approval_id,
        identifier=msg.identifier or '',
        identifier_type=msg.identifier_type or '',
        channel=msg.channel,
        sender_name=msg.sender_name or msg.identifier or 'Unknown',
        original_message=msg.text,
        analysis=analysis,
        draft=draft,
    )

    db.log_event(msg.identifier or '', msg.identifier_type or '', msg.channel,
                 'in', 'draft_created', f'Approval {approval_id} pending')

    # Send a simple notification ping to internal Telegram topic
    business = CONFIG.get('business', {}).get('name', 'CRM')
    label = 'New lead' if is_new else msg.sender_name or msg.identifier
    channel.post_internal(
        f"📩 *New message from {label}*\n"
        f"_{msg.text[:120]}_\n\n"
        f"Open the dashboard to review and approve."
    )

    logger.info(f"Approval {approval_id} saved to DB for {msg.identifier}")


# ------------------------------------------------------------------
# Handle internal message (Telegram ops questions)
# ------------------------------------------------------------------

def handle_internal(msg: InboundMessage, channel) -> None:
    prompt = build_internal_prompt(msg)
    response = call_claude(prompt)
    if response:
        channel.post_internal(response)
    else:
        channel.post_internal("⚠️ Claude did not respond.")


# ------------------------------------------------------------------
# Entry point
# ------------------------------------------------------------------

def run():
    logger.info("=" * 60)
    logger.info("AI-PA CRM Bridge starting")
    logger.info(f"Business: {CONFIG['business']['name']}")
    logger.info(f"Project dir: {PROJECT_DIR}")
    logger.info("=" * 60)

    channels = build_channels()
    if not channels:
        logger.info("No external channels configured — bridge idle (web-only mode).")
        # Stay alive so status checks see the process running
        while True:
            try:
                time.sleep(60)
            except KeyboardInterrupt:
                logger.info("Bridge stopped.")
                return

    while True:
        try:
            for channel in channels:
                messages = channel.poll()
                for msg in messages:
                    if msg.direction == 'external':
                        logger.info(f"[{msg.channel}] External from {msg.identifier}: {msg.text[:60]}")
                        handle_external(msg, channel)
                    elif msg.direction == 'internal':
                        logger.info(f"[{msg.channel}] Internal from {msg.identifier}: {msg.text[:60]}")
                        handle_internal(msg, channel)

            time.sleep(3)

        except KeyboardInterrupt:
            logger.info("Bridge stopped.")
            break
        except Exception as e:
            logger.error(f"Unexpected error: {e}", exc_info=True)
            time.sleep(10)


if __name__ == '__main__':
    run()
