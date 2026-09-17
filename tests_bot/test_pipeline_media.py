# -*- coding: utf-8 -*-
"""Голос и скрин: тот же конвейер, что у текста (ТЗ 5.1–5.3)."""
from __future__ import annotations

import asyncio

import pytest

from conftest import op, parse_out

CHAT = 100000001


def run(coro):
    return asyncio.run(coro)


class FakeProvider:
    def __init__(self, text=None, available=True):
        self.name = "openai"
        self.available = available
        self._text = text
        self.got: list[dict] = []

    async def transcribe(self, **kw):
        self.got.append(kw)
        return self._text


@pytest.fixture
def stt(monkeypatch):
    from backend.stt import router as stt_router

    saved = dict(stt_router._PROVIDERS)
    monkeypatch.setenv("STT_PROVIDER", "openai")
    monkeypatch.setenv("STT_FALLBACK", "")
    provider = FakeProvider("Сходил в кафе, поел на 43 дирхама")
    stt_router.set_provider("openai", provider)
    yield provider
    stt_router._PROVIDERS.clear()
    stt_router._PROVIDERS.update(saved)


def test_voice_goes_through_stt_and_ledger(ledger, llm_answer, stt):
    from backend.pipeline import voice

    llm_answer["data"] = parse_out(op(kind="expense", amount=4300, currency="AED",
                                      from_account="mashreq_personal", category="exp_cafe"))

    async def download():
        return b"ogg-bytes"

    reply = run(voice.handle_voice(CHAT, download=download, file_unique_id="AwAC",
                                   sent_at=1_000_000, duration=4))
    assert ledger.posted[0].source == "voice"
    assert ledger.posted[0].raw_input == "Сходил в кафе, поел на 43 дирхама"
    assert "Расход" in reply.text
    assert stt.got[0]["file_bytes"] == b"ogg-bytes"
    assert stt.got[0]["duration"] == 4


def test_voice_without_transcript_asks_to_repeat(ledger, llm_answer, stt):
    from backend.bot import cards
    from backend.pipeline import voice

    stt._text = None

    async def download():
        return b"ogg-bytes"

    reply = run(voice.handle_voice(CHAT, download=download, duration=2))
    assert reply.text == cards.NO_VOICE_TEXT
    assert ledger.posted == []


def test_screenshot_builds_batch_for_core(ledger):
    from backend.pipeline import screenshot

    seen: dict = {}

    def reconcile(batch):
        seen["batch"] = batch
        return {"batch_id": "scr_1", "matched": [{"id": 1}], "new": [{"id": 2}], "ambiguous": [],
                "balance_check": {"bank": {"amount": 13200000, "currency": "RUB"},
                                  "ledger": {"amount": 13200000, "currency": "RUB"},
                                  "diff": {"amount": 0, "currency": "RUB"}}}

    ledger.reconcile = reconcile
    parsed = {
        "account_guess": "tbank", "currency": "RUB", "balance": 13200000,
        "statement_period": None,
        "rows": [
            {"op_date": "2026-09-16", "amount": -235000, "currency": "RUB",
             "raw_text": "ЯНДЕКС ЕДА", "suggested_category": "exp_groceries", "suggested_kind": "expense"},
            {"op_date": "2026-09-16", "amount": 9000000, "currency": "RUB",
             "raw_text": "ПЕРЕВОД Альфа", "suggested_category": None, "suggested_kind": "income"},
        ],
    }
    replies = run(screenshot.handle_parsed(CHAT, parsed))
    batch = seen["batch"]
    assert batch.account == "tbank"
    assert batch.balance == 13200000
    assert [r.amount for r in batch.rows] == [-235000, 9000000]
    assert batch.rows[0].suggested_category == "exp_groceries"
    assert batch.source == "screenshot"
    assert "Скрин: tbank" in replies[0].text


def test_screenshot_without_account_asks_once(ledger):
    from backend.pipeline import screenshot

    parsed = {"account_guess": None, "currency": None, "balance": None, "statement_period": None,
              "rows": [{"op_date": None, "amount": -100, "currency": "RUB", "raw_text": "x",
                        "suggested_category": None, "suggested_kind": None}]}
    replies = run(screenshot.handle_parsed(CHAT, parsed))
    assert replies[0].text == screenshot.ACCOUNT_QUESTION
    assert ledger.pending[CHAT]["state"] == "reconcile"
    assert screenshot.account_from_words("это Сбер") == "sber"
    assert screenshot.account_from_words("с тинька") == "tbank"


def test_statement_table_rows_are_parsed():
    from backend.pipeline import statement

    csv_bytes = ("Дата;Описание;Сумма\n"
                 "16.09.2026;ЯНДЕКС ЕДА;-2350,00\n"
                 "17.09.2026;ПЕРЕВОД Альфа;90000\n").encode("utf-8")
    rows = statement.rows_from_table(csv_bytes, "vypiska.csv")
    assert [r["op_date"] for r in rows] == ["2026-09-16", "2026-09-17"]
    assert [r["amount"] for r in rows] == [-235000, 9000000]
    assert "ЯНДЕКС ЕДА" in rows[0]["raw_text"]
