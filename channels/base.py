"""
Base channel interface. All channel implementations must subclass this.
A channel is any external communication surface: Telegram, WhatsApp, email, etc.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class InboundMessage:
    """A message received from an external contact or from the internal owner."""
    channel: str                        # 'telegram', 'whatsapp', 'email'
    direction: str                      # 'external' or 'internal'
    text: str                           # raw message text
    identifier: Optional[str] = None   # phone, email, telegram_id, etc.
    identifier_type: Optional[str] = None  # 'phone', 'email', 'telegram_id', 'ip'
    sender_name: Optional[str] = None
    metadata: dict = field(default_factory=dict)  # channel-specific raw data


@dataclass
class OutboundMessage:
    """A message to be sent via the channel."""
    text: str
    metadata: dict = field(default_factory=dict)  # channel-specific routing info


class BaseChannel(ABC):
    """
    Abstract base for all channel implementations.

    Each channel must:
    - Poll or listen for inbound messages
    - Route internal messages to the owner approval interface
    - Route external messages to the owner for approval before sending
    - Send approved outbound messages to the external contact
    """

    def __init__(self, config: dict):
        self.config = config

    @abstractmethod
    def poll(self) -> list[InboundMessage]:
        """
        Check for new messages. Returns a list of InboundMessage objects.
        Called repeatedly by the bridge main loop.
        """
        raise NotImplementedError

    @abstractmethod
    def post_for_approval(self, analysis: str, draft: str, original: InboundMessage, message_ref: str) -> str:
        """
        Post the AI analysis and draft to the owner's internal interface for approval.
        Returns a reference ID for this pending approval (used to match button callbacks).
        """
        raise NotImplementedError

    @abstractmethod
    def send_to_contact(self, message: OutboundMessage, original: InboundMessage):
        """
        Send an approved message to the external contact.
        """
        raise NotImplementedError

    @abstractmethod
    def post_internal(self, text: str):
        """
        Post a message to the owner's internal interface (no approval needed).
        Used for [INTERNAL] query responses.
        """
        raise NotImplementedError

    @abstractmethod
    def acknowledge_approval(self, callback_id: str, text: str):
        """
        Acknowledge an owner action (button click, etc.) on the approval interface.
        """
        raise NotImplementedError

    @abstractmethod
    def delete_approval_message(self, message_ref: str):
        """
        Remove the approval message from the internal interface after action is taken.
        """
        raise NotImplementedError
