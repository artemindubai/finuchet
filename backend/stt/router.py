# -*- coding: utf-8 -*-
"""Выбор провайдера расшифровки и запасные варианты (ARCHITECTURE §8.1).

Порядок: STT_PROVIDER → при None, исключении или таймауте — доступные из STT_FALLBACK по порядку.
Каждый результат пишется в voice_transcripts через ядро (бот в БД не ходит).
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

from backend.stt.groq_provider import GroqProvider
from backend.stt.openai_provider import OpenAIProvider
from backend.stt.telethon_provider import TelethonProvider

log = logging.getLogger("finuchet.stt")

_PROVIDERS: dict[str, Any] = {
    "telethon": TelethonProvider(),
    "openai": OpenAIProvider(),
    "groq": GroqProvider(),
}


def set_provider(name: str, provider: Any) -> None:
    """Подмена провайдера в тестах."""
    _PROVIDERS[name] = provider


def get_provider(name: str) -> Any | None:
    return _PROVIDERS.get(name)


def _order() -> list[str]:
    primary = (os.getenv("STT_PROVIDER") or "telethon").strip().lower()
    fallback = [p.strip().lower() for p in (os.getenv("STT_FALLBACK") or "openai,groq").split(",") if p.strip()]
    order = [primary] + [p for p in fallback if p != primary]
    return [name for name in order if name in _PROVIDERS]


async def transcribe(**kw: Any) -> tuple[str | None, str]:
    """(текст, имя провайдера). Текст None — не расшифровал никто."""
    timeout = kw.pop("timeout", None)
    used = "none"
    for name in _order():
        provider = _PROVIDERS[name]
        if not provider.available:
            log.info("провайдер %s недоступен, идём дальше", name)
            continue
        used = name
        try:
            call_kw = dict(kw)
            if timeout is not None:
                call_kw["timeout"] = timeout
            text = await provider.transcribe(**call_kw)
        except asyncio.TimeoutError:
            log.warning("провайдер %s не уложился в таймаут", name)
            text = None
        except Exception as exc:  # падение провайдера не должно ронять конвейер
            log.warning("провайдер %s ответил ошибкой: %s", name, exc)
            text = None
        if text:
            await _store(kw.get("chat_id"), name, text, "ready", kw)
            return text, name
        await _store(kw.get("chat_id"), name, None, "failed", kw)
    return None, used


async def _store(chat_id: Any, provider: str, text: str | None, status: str, kw: dict[str, Any]) -> None:
    """Строка в voice_transcripts. Telethon-провайдер пишет её сам, из слушателя."""
    if provider == "telethon" or chat_id is None:
        return
    from backend.pipeline import ledger_ref

    try:
        await ledger_ref.call(
            "transcript_put",
            chat_id=int(chat_id),
            provider=provider,
            text=text,
            status=status,
            file_unique_id=kw.get("file_unique_id"),
            sent_at=kw.get("sent_at"),
            duration=kw.get("duration"),
        )
    except Exception as exc:
        log.debug("расшифровку не записали в журнал: %s", exc)
