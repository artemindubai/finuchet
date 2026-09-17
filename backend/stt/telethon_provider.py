# -*- coding: utf-8 -*-
"""Расшифровка силами самого Телеграма (messages.transcribeAudio) через отдельную сессию.

ARCHITECTURE §8.1. Два куска:
  * фоновый слушатель `run_listener_forever()` — видит голосовое, отправленное Артёмом боту,
    просит у Телеграма расшифровку, ждёт `updateTranscribedAudio` и кладёт строку в
    `voice_transcripts` (через ядро, бот в БД не ходит);
  * провайдер `TelethonProvider` — со стороны бота ждёт, пока эта строка появится.

Мост между ними — НЕ message_id: у Bot API и у user-сессии идентификаторы разные (грабля recon 03).
Совпадение ищется по chat_id + времени ±3 с + длительности ±1 с; file_unique_id — дополнительная
проверка, а не основа, и его отсутствие ошибкой не считается.

Строка сессии (TELETHON_SESSION) в лог не попадает никогда.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any, Iterable

log = logging.getLogger("finuchet.stt.telethon")

POLL_SEC = 0.5
TIME_TOLERANCE_SEC = 3
DURATION_TOLERANCE_SEC = 1


def session_string() -> str:
    return (os.getenv("TELETHON_SESSION") or "").strip()


def is_configured() -> bool:
    """Сессия и ключи MTProto заданы. Пусто → провайдер недоступен, роутер сразу идёт в fallback."""
    return bool(session_string() and os.getenv("TELETHON_API_ID") and os.getenv("TELETHON_API_HASH"))


def timeout_sec() -> float:
    try:
        return float(os.getenv("STT_TELETHON_TIMEOUT") or 45)
    except ValueError:
        return 45.0


# ---------------------------------------------------------------- правило сопоставления §8.1

def pick_transcript(
    rows: Iterable[dict[str, Any]],
    *,
    chat_id: int | None,
    sent_at: int | None,
    duration: int | None,
    file_unique_id: str | None = None,
) -> dict[str, Any] | None:
    """Выбирает строку расшифровки под конкретное голосовое.

    Образец правила для ядра (`bot_bridge.transcript_find`): если ядро сопоставляет иначе, расходятся
    два голосовых, отправленных в одну секунду.
    """
    best: dict[str, Any] | None = None
    best_key: tuple[int, int, int] | None = None
    for row in rows:
        if row.get("status") == "failed" or not (row.get("text") or "").strip():
            continue
        if chat_id is not None and row.get("chat_id") not in (None, chat_id):
            continue
        exact_id = bool(file_unique_id) and row.get("file_unique_id") == file_unique_id
        if not exact_id:
            if sent_at is not None and row.get("sent_at") is not None:
                if abs(int(row["sent_at"]) - int(sent_at)) > TIME_TOLERANCE_SEC:
                    continue
            if duration is not None and row.get("duration") is not None:
                if abs(int(row["duration"]) - int(duration)) > DURATION_TOLERANCE_SEC:
                    continue
        # приоритет: точный file_unique_id → ближе по длительности → раньше по времени
        d_dur = abs(int(row.get("duration") or 0) - int(duration or 0)) if duration is not None else 0
        key = (0 if exact_id else 1, d_dur, int(row.get("sent_at") or 0))
        if best_key is None or key < best_key:
            best, best_key = row, key
    return best


# ---------------------------------------------------------------- провайдер

class TelethonProvider:
    name = "telethon"

    @property
    def available(self) -> bool:
        return is_configured()

    async def transcribe(
        self,
        *,
        file_bytes: bytes | None = None,
        file_unique_id: str | None = None,
        chat_id: int | None = None,
        sent_at: int | None = None,
        duration: int | None = None,
        timeout: float | None = None,
    ) -> str | None:
        if not self.available:
            return None
        from backend.pipeline import ledger_ref

        deadline = time.monotonic() + (timeout if timeout is not None else timeout_sec())
        while time.monotonic() < deadline:
            row = await ledger_ref.call(
                "transcript_find",
                chat_id=chat_id,
                file_unique_id=file_unique_id,
                sent_at=sent_at,
                duration=duration,
            )
            if row and (row.get("text") or "").strip():
                return row["text"].strip()
            await asyncio.sleep(POLL_SEC)
        log.warning("расшифровка от Телеграма не пришла за отведённое время")
        return None


# ---------------------------------------------------------------- фоновый слушатель

async def run_listener_forever() -> None:
    """Слушает свой диалог с ботом и складывает расшифровки в БД через ядро.

    No-op, пока STT_PROVIDER не telethon или пока сессия не заведена.
    """
    if (os.getenv("STT_PROVIDER") or "telethon").strip().lower() != "telethon":
        return
    if not is_configured():
        log.info("Telethon-расшифровка выключена: сессия не задана")
        return
    while True:
        try:
            await _listen_once()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.warning("слушатель расшифровок упал (%s), перезапуск через 15 с", exc)
            await asyncio.sleep(15)


async def _listen_once() -> None:
    from telethon import TelegramClient, events
    from telethon.sessions import StringSession
    from telethon.tl.functions.messages import TranscribeAudioRequest

    from backend.pipeline import ledger_ref

    client = TelegramClient(
        StringSession(session_string()),
        int(os.getenv("TELETHON_API_ID")),
        os.getenv("TELETHON_API_HASH"),
    )
    bot_username = (os.getenv("BOT_USERNAME") or "").lstrip("@")
    await client.start()
    try:
        bot_entity = await client.get_entity(bot_username) if bot_username else None

        @client.on(events.NewMessage(chats=bot_entity, outgoing=True))
        async def _on_voice(event) -> None:  # pragma: no cover — живой Телеграм
            msg = event.message
            if not getattr(msg, "voice", None) and not _is_voice(msg):
                return
            chat_id = int(getattr(msg, "chat_id", 0) or 0)
            sent_at = int(msg.date.timestamp()) if getattr(msg, "date", None) else int(time.time())
            duration = _duration(msg)
            file_unique_id = _file_unique_id(msg)
            text = None
            try:
                res = await client(TranscribeAudioRequest(peer=await event.get_input_chat(), msg_id=msg.id))
                text = (getattr(res, "text", "") or "").strip() or None
                if getattr(res, "pending", False):
                    text = await _wait_update(client, getattr(res, "transcription_id", None), timeout_sec()) or text
            except Exception as exc:
                log.warning("Телеграм не расшифровал голосовое: %s", exc)
            await ledger_ref.call(
                "transcript_put",
                chat_id=chat_id,
                provider="telethon",
                text=text,
                status="ready" if text else "failed",
                file_unique_id=file_unique_id,
                sent_at=sent_at,
                duration=duration,
            )

        log.info("слушатель расшифровок поднят")
        await client.run_until_disconnected()
    finally:
        try:
            await client.disconnect()
        except Exception:
            pass


async def _wait_update(client, transcription_id, timeout: float):  # pragma: no cover — живой Телеграм
    """Ждём updateTranscribedAudio по id расшифровки."""
    from telethon import events

    fut: asyncio.Future = asyncio.get_running_loop().create_future()

    @client.on(events.Raw)
    async def _raw(update):
        name = type(update).__name__
        if name != "UpdateTranscribedAudio":
            return
        if transcription_id and getattr(update, "transcription_id", None) != transcription_id:
            return
        if getattr(update, "pending", False):
            return
        if not fut.done():
            fut.set_result((getattr(update, "text", "") or "").strip() or None)

    try:
        return await asyncio.wait_for(fut, timeout=timeout)
    except asyncio.TimeoutError:
        return None
    finally:
        client.remove_event_handler(_raw)


def _is_voice(msg) -> bool:  # pragma: no cover — живой Телеграм
    doc = getattr(getattr(msg, "media", None), "document", None)
    if not doc:
        return False
    return any(type(a).__name__ == "DocumentAttributeAudio" for a in getattr(doc, "attributes", []))


def _duration(msg) -> int | None:  # pragma: no cover — живой Телеграм
    doc = getattr(getattr(msg, "media", None), "document", None)
    for attr in getattr(doc, "attributes", []) or []:
        dur = getattr(attr, "duration", None)
        if dur is not None:
            return int(dur)
    return None


def _file_unique_id(msg) -> str | None:  # pragma: no cover — живой Телеграм
    """У MTProto-документа идентификатора Bot API нет — None здесь обычное дело, не ошибка."""
    try:
        from telethon import utils

        return utils.pack_bot_file_id(msg.media)
    except Exception:
        return None
