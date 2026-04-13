#!/usr/bin/env python3
"""
AI-PA CRM Bridge

Connects external channels (Telegram, future: WhatsApp, email) to the Claude AI assistant.

Flow:
  External message in  →  Claude analyses + drafts reply  →  Owner approves/edits/rejects
  Owner approves       →  Reply sent to contact           →  Claude updates CRM + DB
  Internal message in  →  Claude answers directly         →  Response posted to owner
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
    handlers=[
        logging.StreamHandler(sys.stdout),
    ]
)
logger = logging.getLogger(__name__)


# ------------------------------------------------------------------
# Channel registry — add new channels here
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
    """
    Invoke Claude CLI in print mode with the project CLAUDE.md as context.
    Working directory is set to the project root so CLAUDE.md is auto-loaded.
    """
    claude_cfg = CONFIG.get('claude', {})
    bin_path = os.path.expanduser(claude_cfg.get('bin', 'claude'))
    model = claude_cfg.get('model', 'claude-sonnet-4-6')
    extra_flags = claude_cfg.get('flags', [])

    cmd = [bin_path] + extra_flags + ['--model', model, '-p', prompt]

    logger.info(f"Calling Claude ({model})...")
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=180,
            cwd=PROJECT_DIR,
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


def build_edit_prompt(original_msg: InboundMessage, previous_draft: str, edit_instructions: str) -> str:
    return (
        f"[EDIT_DRAFT]\n"
        f"contact_identifier: {original_msg.identifier}\n"
        f"original_message: {original_msg.text}\n"
        f"previous_draft: {previous_draft}\n"
        f"edit_instructions: {edit_instructions}"
    )


def build_post_send_prompt(msg: InboundMessage, sent_reply: str, is_new: bool, contact_file: Optional[str]) -> str:
    return (
        f"[POST_SEND]\n"
        f"contact_identifier: {msg.identifier}\n"
        f"identifier_type: {msg.identifier_type}\n"
        f"channel: {msg.channel}\n"
        f"is_new_contact: {'true' if is_new else 'false'}\n"
        f"contact_file: {contact_file or 'NONE'}\n"
        f"original_message: {msg.text}\n"
        f"sent_reply: {sent_reply}"
    )


# ------------------------------------------------------------------
# Response parsing
# ------------------------------------------------------------------

def parse_claude_response(response: str) -> tuple[str, str]:
    """
    Extract analysis and draft from Claude's response.
    Returns (analysis, draft). Draft is empty string if not found.
    """
    draft_match = re.search(r'===DRAFT===(.*?)===END===', response, re.DOTALL)
    if not draft_match:
        return response.strip(), ''

    draft = draft_match.group(1).strip()
    analysis = response[:draft_match.start()].strip()

    # Strip the *📋 ANALYSIS* header if present
    analysis = re.sub(r'^\*?📋\s*ANALYSIS\*?\s*', '', analysis).strip()

    return analysis, draft


# ------------------------------------------------------------------
# Pending approval store (in-memory)
# Keys: message_ref (str uuid)
# Values: { 'original': InboundMessage, 'draft': str, 'approval_msg_ref': str, 'channel': BaseChannel }
# ------------------------------------------------------------------

PENDING = {}


# ------------------------------------------------------------------
# Main bridge logic
# ------------------------------------------------------------------

def handle_external(msg: InboundMessage, channel) -> None:
    prompt = build_external_prompt(msg)
    response = call_claude(prompt)

    if not response:
        channel.post_internal(f"⚠️ Claude did not respond to external message from {msg.sender_name} ({msg.identifier}).")
        return

    analysis, draft = parse_claude_response(response)

    if not draft:
        # Claude returned analysis only (e.g. new contact note) — still show for approval
        draft = "[No draft generated — see analysis above]"

    message_ref = str(uuid.uuid4())[:8]
    approval_msg_ref = channel.post_for_approval(analysis, draft, msg, message_ref)

    PENDING[message_ref] = {
        'original': msg,
        'draft': draft,
        'approval_msg_ref': approval_msg_ref,
        'channel': channel,
        'is_new_contact': 'New contact' in analysis,
        'contact_file': None,  # Claude will determine this in POST_SEND
    }

    logger.info(f"Pending approval created: {message_ref} for {msg.identifier}")


def handle_internal(msg: InboundMessage, channel) -> None:
    prompt = build_internal_prompt(msg)
    response = call_claude(prompt)

    if response:
        channel.post_internal(response)
    else:
        channel.post_internal("⚠️ Claude did not respond.")


def handle_callback(callback: dict, channel) -> None:
    """Process a button press on an approval message."""
    callback_id = callback['id']
    data = callback.get('data', '')
    from_user = callback.get('from', {})
    user_id = str(from_user.get('id', ''))

    if not data or ':' not in data:
        return

    action, message_ref = data.split(':', 1)
    pending = PENDING.get(message_ref)

    if not pending:
        channel.acknowledge_approval(callback_id, "Session expired — please resend the message.")
        return

    original: InboundMessage = pending['original']
    draft: str = pending['draft']
    approval_msg_ref: str = pending['approval_msg_ref']

    if action == 'accept':
        channel.acknowledge_approval(callback_id, "Sending...")
        channel.send_to_contact(OutboundMessage(text=draft, metadata=original.metadata), original)
        channel.delete_approval_message(approval_msg_ref)

        # Update CRM + DB
        prompt = build_post_send_prompt(original, draft, pending['is_new_contact'], pending.get('contact_file'))
        call_claude(prompt)

        del PENDING[message_ref]
        logger.info(f"ACCEPTED and sent: {message_ref}")

    elif action == 'edit':
        channel.acknowledge_approval(callback_id, "Send your edit instructions in the internal chat.")
        # Store state so next internal message from this owner is treated as edit instructions
        PENDING[message_ref]['awaiting_edit_from'] = user_id
        logger.info(f"EDIT requested: {message_ref}")

    elif action == 'reject':
        channel.acknowledge_approval(callback_id, "Rejected.")
        channel.delete_approval_message(approval_msg_ref)
        channel.post_internal(f"❌ Draft rejected for message from {original.sender_name}. No reply sent.")
        del PENDING[message_ref]
        logger.info(f"REJECTED: {message_ref}")

    elif action == 'call':
        channel.acknowledge_approval(callback_id, "Noted.")
        channel.post_internal(
            f"📞 *Call reminder*\n\n"
            f"Contact: {original.sender_name}\n"
            f"Identifier: {original.identifier}\n"
            f"Message: {original.text}"
        )
        channel.delete_approval_message(approval_msg_ref)
        del PENDING[message_ref]
        logger.info(f"CALL FIRST: {message_ref}")


def handle_edit_instruction(msg: InboundMessage, channel, message_ref: str) -> None:
    """Owner sent edit instructions for a pending draft."""
    pending = PENDING[message_ref]
    original: InboundMessage = pending['original']
    previous_draft: str = pending['draft']

    prompt = build_edit_prompt(original, previous_draft, msg.text)
    response = call_claude(prompt)

    if not response:
        channel.post_internal("⚠️ Claude did not respond to edit request.")
        return

    _, new_draft = parse_claude_response(response)
    if not new_draft:
        new_draft = response.strip()

    pending['draft'] = new_draft
    pending.pop('awaiting_edit_from', None)

    # Re-post for approval with updated draft
    approval_msg_ref = channel.post_for_approval(
        "*(Revised draft)*", new_draft, original, message_ref
    )
    pending['approval_msg_ref'] = approval_msg_ref
    logger.info(f"Revised draft posted for approval: {message_ref}")


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
        logger.error("No channels configured. Check config.json.")
        sys.exit(1)

    while True:
        try:
            for channel in channels:
                # Check for new messages
                messages = channel.poll()
                for msg in messages:
                    if msg.direction == 'external':
                        logger.info(f"[{msg.channel}] External from {msg.identifier}: {msg.text[:60]}")
                        handle_external(msg, channel)
                    elif msg.direction == 'internal':
                        # Check if this is an edit instruction for a pending draft
                        edit_ref = next(
                            (ref for ref, p in PENDING.items()
                             if p.get('awaiting_edit_from') == msg.identifier),
                            None
                        )
                        if edit_ref:
                            logger.info(f"[{msg.channel}] Edit instruction for {edit_ref}: {msg.text[:60]}")
                            handle_edit_instruction(msg, channel, edit_ref)
                        else:
                            logger.info(f"[{msg.channel}] Internal from {msg.identifier}: {msg.text[:60]}")
                            handle_internal(msg, channel)

                # Check for button callbacks (Telegram-specific, no-op on other channels)
                if hasattr(channel, 'get_callbacks'):
                    for callback in channel.get_callbacks():
                        handle_callback(callback, channel)

            time.sleep(3)

        except KeyboardInterrupt:
            logger.info("Bridge stopped.")
            break
        except Exception as e:
            logger.error(f"Unexpected error: {e}", exc_info=True)
            time.sleep(10)


if __name__ == '__main__':
    run()
