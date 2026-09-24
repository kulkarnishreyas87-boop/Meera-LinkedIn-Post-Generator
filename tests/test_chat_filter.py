from datetime import datetime, timezone

from telegram import Chat, Message, Update

from app.bot.filters import is_allowed_chat, is_allowed_update, note_text
from app.config import parse_chat_id

CHANNEL = -1001234567890
OTHER = -1009999999999


def _msg(chat_id: int, text: str, chat_type: str = Chat.CHANNEL) -> Message:
    return Message(message_id=42, date=datetime.now(timezone.utc), chat=Chat(id=chat_id, type=chat_type), text=text)


def test_is_allowed_chat():
    assert is_allowed_chat(CHANNEL, CHANNEL)
    assert not is_allowed_chat(OTHER, CHANNEL)
    assert not is_allowed_chat(None, CHANNEL)
    assert not is_allowed_chat(CHANNEL, None)  # unset config accepts nothing


def test_channel_post_from_configured_channel_is_accepted():
    update = Update(update_id=1, channel_post=_msg(CHANNEL, "pH note"))
    assert is_allowed_update(update, CHANNEL)
    assert note_text(update) == "pH note"


def test_channel_post_from_other_chat_is_rejected():
    update = Update(update_id=2, channel_post=_msg(OTHER, "spam"))
    assert not is_allowed_update(update, CHANNEL)


def test_plain_message_update_also_handled():
    update = Update(update_id=3, message=_msg(CHANNEL, "group note", chat_type=Chat.SUPERGROUP))
    assert is_allowed_update(update, CHANNEL)
    assert note_text(update) == "group note"


def test_commands_and_edits_are_not_notes():
    assert note_text(Update(update_id=4, channel_post=_msg(CHANNEL, "/draft"))) is None
    assert note_text(Update(update_id=5, edited_channel_post=_msg(CHANNEL, "edited"))) is None


def test_chat_id_parsing_tolerates_whitespace():
    assert parse_chat_id(" -1001234567890") == CHANNEL
    assert parse_chat_id("") is None
    assert parse_chat_id(None) is None
