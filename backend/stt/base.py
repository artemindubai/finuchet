# -*- coding: utf-8 -*-
"""Общий интерфейс провайдеров расшифровки (ARCHITECTURE §8.1)."""
from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class STTProvider(Protocol):
    name: str          # 'telethon' | 'openai' | 'groq'
    available: bool    # ключ или сессия заданы

    async def transcribe(
        self,
        *,
        file_bytes: bytes | None = None,
        file_unique_id: str | None = None,
        chat_id: int | None = None,
        sent_at: int | None = None,
        duration: int | None = None,
        timeout: float = 45.0,
    ) -> str | None:
        ...


class STTError(RuntimeError):
    """Провайдер ответил ошибкой. Роутер переходит к следующему."""
