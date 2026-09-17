# -*- coding: utf-8 -*-
"""Чужому — тишина (ТЗ 9). Ни ответа, ни «извините, бот личный», ни вызова ИИ."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

from conftest import op, parse_out

OWNER = 100000001
STRANGER = 111222333


def run(coro):
    return asyncio.run(coro)


class FakeMessage:
    def __init__(self, user_id, text="Поел на 43 дирхама"):
        self.from_user = SimpleNamespace(id=user_id)
        self.chat = SimpleNamespace(id=user_id)
        self.text = text
        self.date = None
        self.voice = None
        self.audio = None
        self.photo = None
        self.document = None
        self.sent: list[str] = []
        self.answers: list[str] = []

    async def reply(self, text, **kwargs):
        self.sent.append(text)

    async def answer(self, text, **kwargs):
        self.answers.append(text)


def test_silence_for_other_ids(ledger, llm_answer):
    from backend.bot import handlers

    message = FakeMessage(STRANGER)
    run(handlers.on_text(message))
    assert message.sent == [] and message.answers == []
    assert llm_answer["calls"] == []
    assert ledger.posted == []


def test_owner_gets_an_answer(ledger, llm_answer):
    from backend.bot import handlers

    llm_answer["data"] = parse_out(op(kind="expense", amount=4300, currency="AED",
                                      from_account="mashreq_personal", category="exp_cafe"))
    message = FakeMessage(OWNER)
    run(handlers.on_text(message))
    assert len(message.sent) == 1
    assert "Расход" in message.sent[0]


def test_start_is_silent_for_stranger(ledger):
    from backend.bot import handlers

    message = FakeMessage(STRANGER, text="/start")
    run(handlers.on_start(message))
    assert message.answers == []


def test_start_for_owner_opens_app(ledger):
    from backend.bot import handlers

    message = FakeMessage(OWNER, text="/start")
    run(handlers.on_start(message))
    assert message.answers == ["Готов. Открывайте приложение кнопкой ниже."]


def test_other_commands_are_ignored(ledger, llm_answer):
    from backend.bot import handlers

    message = FakeMessage(OWNER, text="/help")
    run(handlers.on_text(message))
    assert message.sent == []
    assert llm_answer["calls"] == []


def test_callback_from_stranger_does_nothing(ledger):
    from backend.bot import handlers

    answered: list[int] = []

    class FakeQuery:
        from_user = SimpleNamespace(id=STRANGER)
        message = None
        data = "f:u:431"

        async def answer(self):
            answered.append(1)

    run(handlers.on_callback(FakeQuery()))
    assert ledger.voided == []
    assert answered == []
