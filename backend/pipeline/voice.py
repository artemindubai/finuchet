# -*- coding: utf-8 -*-
"""Голосовое → расшифровка → тот же разбор, что у текста (ТЗ 5.1)."""
from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from backend.bot import cards
from backend.bot.cards import Reply
from backend.pipeline import text as text_pipeline
from backend.stt import router as stt_router

log = logging.getLogger("finuchet.pipeline.voice")


async def handle_voice(
    chat_id: int,
    *,
    download: Callable[[], Awaitable[bytes]] | None = None,
    file_unique_id: str | None = None,
    sent_at: int | None = None,
    duration: int | None = None,
) -> Reply:
    """Скачиваем файл, расшифровываем, дальше — обычный конвейер фразы.

    Telethon-провайдеру файл не нужен: он ждёт расшифровку, которую Телеграм делает сам, — поэтому
    скачиваем ленивo, только если провайдер попросит байты.
    """
    blob: bytes | None = None
    if download is not None and _needs_bytes():
        try:
            blob = await download()
        except Exception as exc:
            log.warning("голосовое не скачалось: %s", exc)

    transcript, provider = await stt_router.transcribe(
        file_bytes=blob,
        file_unique_id=file_unique_id,
        chat_id=chat_id,
        sent_at=sent_at,
        duration=duration,
    )
    if not transcript and blob is None and download is not None:
        # запасной провайдер всё-таки требует файл — качаем и пробуем ещё раз
        try:
            blob = await download()
        except Exception as exc:
            log.warning("голосовое не скачалось: %s", exc)
        if blob:
            transcript, provider = await stt_router.transcribe(
                file_bytes=blob, file_unique_id=file_unique_id, chat_id=chat_id,
                sent_at=sent_at, duration=duration,
            )
    if not transcript:
        log.info("расшифровка не получилась, провайдер %s", provider)
        return Reply(cards.NO_VOICE_TEXT)
    return await text_pipeline.handle_phrase(chat_id, transcript, source="voice")


def _needs_bytes() -> bool:
    """Первый доступный провайдер — не Telethon → байты нужны сразу."""
    import os

    primary = (os.getenv("STT_PROVIDER") or "telethon").strip().lower()
    if primary != "telethon":
        return True
    provider: Any = stt_router.get_provider("telethon")
    return not (provider and provider.available)
