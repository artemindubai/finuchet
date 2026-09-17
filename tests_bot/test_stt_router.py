# -*- coding: utf-8 -*-
"""Роутер расшифровки и мост Telethon ↔ бот (ARCHITECTURE §8.1)."""
from __future__ import annotations

import asyncio
import time

import pytest

from backend.stt import router as stt_router
from backend.stt.telethon_provider import TelethonProvider, pick_transcript


def run(coro):
    return asyncio.run(coro)


class FakeProvider:
    def __init__(self, name, *, text=None, available=True, error=None, delay=0.0):
        self.name = name
        self.available = available
        self._text = text
        self._error = error
        self._delay = delay
        self.calls = 0

    async def transcribe(self, **kw):
        self.calls += 1
        if self._delay:
            await asyncio.sleep(self._delay)
        if self._error:
            raise self._error
        return self._text


@pytest.fixture
def providers():
    saved = dict(stt_router._PROVIDERS)
    yield stt_router._PROVIDERS
    stt_router._PROVIDERS.clear()
    stt_router._PROVIDERS.update(saved)


def test_fallback_on_timeout(ledger, providers, monkeypatch):
    monkeypatch.setenv("STT_PROVIDER", "openai")
    monkeypatch.setenv("STT_FALLBACK", "groq")
    primary = FakeProvider("openai", error=asyncio.TimeoutError())
    backup = FakeProvider("groq", text="поел на 43 дирхама")
    stt_router.set_provider("openai", primary)
    stt_router.set_provider("groq", backup)

    text, used = run(stt_router.transcribe(file_bytes=b"ogg", chat_id=1))
    assert (text, used) == ("поел на 43 дирхама", "groq")
    assert primary.calls == 1 and backup.calls == 1
    # обе попытки попали в журнал расшифровок через ядро
    assert [t["status"] for t in ledger.transcripts] == ["failed", "ready"]


def test_fallback_on_provider_error(ledger, providers, monkeypatch):
    monkeypatch.setenv("STT_PROVIDER", "openai")
    monkeypatch.setenv("STT_FALLBACK", "groq")
    stt_router.set_provider("openai", FakeProvider("openai", error=RuntimeError("500")))
    stt_router.set_provider("groq", FakeProvider("groq", text="такси 20"))
    text, used = run(stt_router.transcribe(file_bytes=b"ogg", chat_id=1))
    assert (text, used) == ("такси 20", "groq")


def test_telethon_unavailable_without_session(ledger, providers, monkeypatch):
    """Пустой TELETHON_SESSION — сразу запасной, без ожидания таймаута."""
    monkeypatch.setenv("TELETHON_SESSION", "")
    monkeypatch.setenv("STT_PROVIDER", "telethon")
    monkeypatch.setenv("STT_FALLBACK", "openai")
    stt_router.set_provider("telethon", TelethonProvider())
    stt_router.set_provider("openai", FakeProvider("openai", text="поел на 43"))

    started = time.monotonic()
    text, used = run(stt_router.transcribe(file_bytes=b"ogg", chat_id=1))
    assert (text, used) == ("поел на 43", "openai")
    assert time.monotonic() - started < 2  # таймаут Telethon не ждали


def test_no_provider_available(ledger, providers, monkeypatch):
    monkeypatch.setenv("STT_PROVIDER", "openai")
    monkeypatch.setenv("STT_FALLBACK", "groq")
    stt_router.set_provider("openai", FakeProvider("openai", available=False))
    stt_router.set_provider("groq", FakeProvider("groq", available=False))
    text, _ = run(stt_router.transcribe(file_bytes=b"ogg", chat_id=1))
    assert text is None


# ---------------------------------------------------------------- мост Telethon

def rows():
    return [
        {"chat_id": 100000001, "file_unique_id": None, "duration": 4, "sent_at": 1_000_000,
         "text": "поел на 43 дирхама", "status": "ready"},
        {"chat_id": 100000001, "file_unique_id": None, "duration": 9, "sent_at": 1_000_001,
         "text": "такси двадцать", "status": "ready"},
    ]


def test_telethon_bridge_by_time_and_duration():
    """Сопоставление идёт по chat_id, времени ±3 с и длительности ±1 — не по message_id."""
    picked = pick_transcript(rows(), chat_id=100000001, sent_at=1_000_002, duration=9,
                             file_unique_id=None)
    assert picked["text"] == "такси двадцать"

    picked = pick_transcript(rows(), chat_id=100000001, sent_at=1_000_000, duration=4,
                             file_unique_id="AwACAgI")
    assert picked["text"] == "поел на 43 дирхама"   # file_unique_id=None в строке — не ошибка


def test_telethon_bridge_ignores_far_time_and_other_chat():
    assert pick_transcript(rows(), chat_id=100000001, sent_at=1_000_600, duration=4,
                           file_unique_id=None) is None
    assert pick_transcript(rows(), chat_id=42, sent_at=1_000_000, duration=4,
                           file_unique_id=None) is None


def test_telethon_provider_reads_transcript_from_core(ledger, monkeypatch):
    monkeypatch.setenv("TELETHON_SESSION", "stub-session")
    monkeypatch.setenv("TELETHON_API_ID", "1")
    monkeypatch.setenv("TELETHON_API_HASH", "hash")
    ledger.transcripts.extend(rows())
    provider = TelethonProvider()
    assert provider.available is True
    text = run(provider.transcribe(chat_id=100000001, sent_at=1_000_001, duration=9, timeout=2))
    assert text == "такси двадцать"


def test_telethon_provider_gives_up_on_timeout(ledger, monkeypatch):
    monkeypatch.setenv("TELETHON_SESSION", "stub-session")
    monkeypatch.setenv("TELETHON_API_ID", "1")
    monkeypatch.setenv("TELETHON_API_HASH", "hash")
    text = run(TelethonProvider().transcribe(chat_id=1, sent_at=1, duration=1, timeout=1.2))
    assert text is None
