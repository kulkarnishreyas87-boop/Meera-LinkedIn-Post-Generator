"""Only accept updates from the configured TELEGRAM_CHAT_ID (a channel, group or DM)."""

from __future__ import annotations

from telegram import Update


def is_allowed_chat(chat_id: int | None, allowed_chat_id: int | None) -> bool:
    return chat_id is not None and allowed_chat_id is not None and int(chat_id) == int(allowed_chat_id)


def update_chat_id(update: Update) -> int | None:
    """Chat ID for message, channel_post and callback_query updates alike."""
    chat = update.effective_chat
    return chat.id if chat else None


def is_allowed_update(update: Update, allowed_chat_id: int | None) -> bool:
    return is_allowed_chat(update_chat_id(update), allowed_chat_id)


def note_text(update: Update) -> str | None:
    """Text of a new message or channel post (captions count too). Edits are ignored."""
    msg = update.message or update.channel_post
    if msg is None:
        return None
    text = msg.text or msg.caption
    if not text or text.lstrip().startswith("/"):
        return None
    return text
