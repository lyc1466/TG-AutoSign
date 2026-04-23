from __future__ import annotations

from typing import Any


def message_sender_label(message: Any) -> str:
    from_user = getattr(message, "from_user", None)
    if from_user is not None:
        username = getattr(from_user, "username", None)
        if username:
            return str(username)
        user_id = getattr(from_user, "id", None)
        if user_id is not None:
            return str(user_id)

    sender_chat = getattr(message, "sender_chat", None)
    if sender_chat is not None:
        title = getattr(sender_chat, "title", None)
        if title:
            return str(title)
        username = getattr(sender_chat, "username", None)
        if username:
            return str(username)
        chat_id = getattr(sender_chat, "id", None)
        if chat_id is not None:
            return str(chat_id)

    return "unknown"
