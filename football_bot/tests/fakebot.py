"""A Bot whose HTTP session records every API call and returns plausible results (no network)."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from aiogram import Bot
from aiogram.client.session.base import BaseSession
from aiogram.methods import (AnswerCallbackQuery, DeleteWebhook, EditMessageText, PinChatMessage, SendMessage,
                             TelegramMethod)
from aiogram.types import Chat, Message


class RecordingSession(BaseSession):
    def __init__(self):
        super().__init__()
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.pin_error: Exception | None = None
        self._mid = 1000

    async def close(self) -> None: ...

    async def stream_content(self, *a, **k):  # pragma: no cover
        raise NotImplementedError

    async def make_request(self, bot: Bot, method: TelegramMethod, timeout: int | None = None):
        data = method.model_dump(exclude_none=True)
        self.calls.append((type(method).__name__, data))
        if isinstance(method, (SendMessage, EditMessageText)):
            self._mid += 1
            chat_id = data.get("chat_id", 0)
            return Message(message_id=data.get("message_id", self._mid), date=datetime.now(UTC),
                           chat=Chat(id=chat_id if isinstance(chat_id, int) else 0, type="private"),
                           text=data.get("text", "")).as_(bot)
        if isinstance(method, PinChatMessage):
            if self.pin_error:
                raise self.pin_error
            return True
        return True

    # helpers ------------------------------------------------------------------------------------
    def of(self, name: str) -> list[dict]:
        return [d for n, d in self.calls if n == name]

    def last_text(self) -> str:
        msgs = [d for n, d in self.calls if n in ("SendMessage", "EditMessageText")]
        return msgs[-1]["text"]

    def last_markup(self):
        msgs = [d for n, d in self.calls if n in ("SendMessage", "EditMessageText") and d.get("reply_markup")]
        return msgs[-1]["reply_markup"]["inline_keyboard"] if msgs else []

    def callbacks(self) -> list[str]:
        return [b["callback_data"] for row in self.last_markup() for b in row if "callback_data" in b]


def make_bot() -> tuple[Bot, RecordingSession]:
    sess = RecordingSession()
    return Bot("123456:" + "A" * 35, session=sess), sess


_uid = [100]


def msg_update(user_id: int, text: str, update_id: int | None = None) -> dict:
    _uid[0] += 1
    return {"update_id": update_id or _uid[0], "message": {
        "message_id": _uid[0], "date": int(datetime.now(UTC).timestamp()), "chat": {"id": user_id, "type": "private"},
        "from": {"id": user_id, "is_bot": False, "first_name": "T", "username": "t"}, "text": text}}


def cb_update(user_id: int, data: str, update_id: int | None = None) -> dict:
    _uid[0] += 1
    return {"update_id": update_id or _uid[0], "callback_query": {
        "id": str(_uid[0]), "chat_instance": "ci", "data": data,
        "from": {"id": user_id, "is_bot": False, "first_name": "T", "username": "t"},
        "message": {"message_id": 5, "date": int(datetime.now(UTC).timestamp()),
                    "chat": {"id": user_id, "type": "private"}, "text": "x"}}}
