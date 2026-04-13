"""
Telegram channel implementation.

Two-topic group structure:
  External topic — receives messages from customers/leads
  Internal topic — owner sees AI analysis + approval buttons

Topic IDs and bot credentials come from config['channels']['telegram'].
"""

import json
import logging
import requests
from typing import Optional

from channels.base import BaseChannel, InboundMessage, OutboundMessage

logger = logging.getLogger(__name__)


class TelegramChannel(BaseChannel):

    def __init__(self, config: dict):
        super().__init__(config)
        cfg = config['channels']['telegram']
        self.token = cfg['bot_token']
        self.chat_id = cfg['chat_id']
        self.external_topic = cfg['topics']['external']
        self.internal_topic = cfg['topics']['internal']
        self.owner_ids = set(str(uid) for uid in cfg['owners'])
        self.api = f"https://api.telegram.org/bot{self.token}"
        self._last_update_id = 0

    # ------------------------------------------------------------------
    # BaseChannel implementation
    # ------------------------------------------------------------------

    def poll(self) -> list[InboundMessage]:
        """Fetch new updates from Telegram. Returns parsed InboundMessages."""
        updates = self._get_updates()
        messages = []

        for update in updates:
            self._last_update_id = update['update_id']

            if 'message' in update:
                msg = update['message']
                chat_id = str(msg.get('chat', {}).get('id', ''))
                topic_id = msg.get('message_thread_id')
                text = msg.get('text', '').strip()

                if not text or chat_id != str(self.chat_id):
                    continue

                from_user = msg.get('from', {})
                sender_id = str(from_user.get('id', ''))
                sender_name = from_user.get('first_name', 'Unknown')

                if topic_id == self.external_topic:
                    messages.append(InboundMessage(
                        channel='telegram',
                        direction='external',
                        text=text,
                        identifier=sender_id,
                        identifier_type='telegram_id',
                        sender_name=sender_name,
                        metadata={
                            'update_id': update['update_id'],
                            'message_id': msg['message_id'],
                            'chat_id': chat_id,
                            'topic_id': topic_id,
                            'raw': msg,
                        }
                    ))

                elif topic_id == self.internal_topic:
                    messages.append(InboundMessage(
                        channel='telegram',
                        direction='internal',
                        text=text,
                        identifier=sender_id,
                        identifier_type='telegram_id',
                        sender_name=sender_name,
                        metadata={
                            'update_id': update['update_id'],
                            'message_id': msg['message_id'],
                            'chat_id': chat_id,
                            'topic_id': topic_id,
                        }
                    ))

            # Callback queries (button presses) are handled separately
            # by the bridge via get_callbacks()

        return messages

    def get_callbacks(self) -> list[dict]:
        """Return pending callback queries (button presses) from the last poll."""
        # Callbacks are collected during _get_updates and stored for retrieval
        return self._pending_callbacks

    def post_for_approval(self, analysis: str, draft: str, original: InboundMessage, message_ref: str) -> str:
        """Post analysis + draft to internal topic with ACCEPT/EDIT/REJECT buttons."""
        text = (
            f"*📋 ANALYSIS*\n\n"
            f"From: {original.sender_name} ({original.identifier})\n\n"
            f"{analysis}\n\n"
            f"━━━━━━━━━━━━━━━\n"
            f"*DRAFT TO SEND:*\n\n"
            f"{draft}"
        )

        markup = {
            'inline_keyboard': [
                [
                    {'text': '✅ ACCEPT', 'callback_data': f'accept:{message_ref}'},
                    {'text': '✏️ EDIT',   'callback_data': f'edit:{message_ref}'},
                ],
                [
                    {'text': '❌ REJECT',     'callback_data': f'reject:{message_ref}'},
                    {'text': '📞 CALL FIRST', 'callback_data': f'call:{message_ref}'},
                ],
            ]
        }

        result = self._send_message(text, topic_id=self.internal_topic, reply_markup=markup)
        if result:
            return str(result['message_id'])
        return message_ref

    def send_to_contact(self, message: OutboundMessage, original: InboundMessage):
        """Send an approved message back to the external topic."""
        self._send_message(message.text, topic_id=self.external_topic)

    def post_internal(self, text: str):
        """Post a plain response to the internal topic."""
        self._send_message(text, topic_id=self.internal_topic)

    def acknowledge_approval(self, callback_id: str, text: str):
        """Acknowledge a button press so Telegram removes the loading spinner."""
        try:
            requests.post(
                f"{self.api}/answerCallbackQuery",
                json={'callback_query_id': callback_id, 'text': text},
                timeout=5
            )
        except Exception as e:
            logger.warning(f"Failed to acknowledge callback: {e}")

    def delete_approval_message(self, message_ref: str):
        """Delete the internal approval message after it's been acted on."""
        try:
            requests.post(
                f"{self.api}/deleteMessage",
                json={'chat_id': self.chat_id, 'message_id': int(message_ref)},
                timeout=5
            )
        except Exception as e:
            logger.warning(f"Failed to delete message {message_ref}: {e}")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_updates(self) -> list[dict]:
        self._pending_callbacks = []
        try:
            resp = requests.get(
                f"{self.api}/getUpdates",
                params={'offset': self._last_update_id + 1, 'timeout': 30},
                timeout=35
            )
            data = resp.json()
            if not data.get('ok'):
                logger.error(f"Telegram API error: {data.get('description')}")
                return []

            updates = data.get('result', [])

            # Separate callback queries out for the bridge to handle
            for u in updates:
                if 'callback_query' in u:
                    self._last_update_id = u['update_id']
                    self._pending_callbacks.append(u['callback_query'])

            return updates

        except Exception as e:
            logger.error(f"Error fetching updates: {e}")
            return []

    def _send_message(self, text: str, topic_id: Optional[int] = None, reply_markup: Optional[dict] = None) -> Optional[dict]:
        payload = {
            'chat_id': self.chat_id,
            'text': text[:4096],  # Telegram message limit
            'parse_mode': 'Markdown',
            'disable_web_page_preview': True,
        }
        if topic_id:
            payload['message_thread_id'] = topic_id
        if reply_markup:
            payload['reply_markup'] = json.dumps(reply_markup)

        try:
            resp = requests.post(f"{self.api}/sendMessage", json=payload, timeout=10)
            result = resp.json()
            if result.get('ok'):
                return result.get('result')
            logger.error(f"Send failed: {result.get('description')}")
            return None
        except Exception as e:
            logger.error(f"Error sending message: {e}")
            return None
