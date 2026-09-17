# -*- coding: utf-8 -*-
"""Запасная расшифровка через Groq whisper-large-v3 (ARCHITECTURE §8.1)."""
from __future__ import annotations

import logging
import os

import httpx

from backend.stt.base import STTError

log = logging.getLogger("finuchet.stt.groq")

URL = "https://api.groq.com/openai/v1/audio/transcriptions"
MODEL = "whisper-large-v3"


class GroqProvider:
    name = "groq"

    @property
    def available(self) -> bool:
        return bool((os.getenv("STT_API_KEY_GROQ") or "").strip())

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
        if not file_bytes:
            return None
        key = (os.getenv("STT_API_KEY_GROQ") or "").strip()
        if not key:
            raise STTError("нет ключа STT_API_KEY_GROQ")
        files = {"file": ("voice.ogg", file_bytes, "audio/ogg")}
        data = {"model": MODEL, "language": "ru", "response_format": "json"}
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(URL, files=files, data=data, headers={"Authorization": f"Bearer {key}"})
        if resp.status_code >= 400:
            log.warning("groq stt %s: %s", resp.status_code, resp.text[:200])
            if resp.status_code >= 500:
                raise STTError(f"groq stt {resp.status_code}")
            return None
        return (resp.json().get("text") or "").strip() or None
