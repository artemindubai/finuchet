# -*- coding: utf-8 -*-
"""Расшифровка через OpenAI /v1/audio/transcriptions (ARCHITECTURE §8.1)."""
from __future__ import annotations

import logging
import os

import httpx

from backend.stt.base import STTError

log = logging.getLogger("finuchet.stt.openai")

URL = "https://api.openai.com/v1/audio/transcriptions"
FALLBACK_MODEL = "whisper-1"


class OpenAIProvider:
    name = "openai"

    @property
    def available(self) -> bool:
        return bool(self._key())

    @staticmethod
    def _key() -> str:
        return (os.getenv("STT_API_KEY") or os.getenv("OPENAI_API_KEY") or "").strip()

    @staticmethod
    def _model() -> str:
        return (os.getenv("STT_MODEL") or "gpt-4o-transcribe").strip()

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
        key = self._key()
        if not key:
            raise STTError("нет ключа STT_API_KEY")
        model = self._model()
        text = await self._post(key, model, file_bytes, timeout)
        if text is None and model != FALLBACK_MODEL:
            # 4xx по имени модели — один повтор на whisper-1 (§8.1)
            log.warning("модель %s не принята, повтор на %s", model, FALLBACK_MODEL)
            text = await self._post(key, FALLBACK_MODEL, file_bytes, timeout)
        return text

    @staticmethod
    async def _post(key: str, model: str, blob: bytes, timeout: float) -> str | None:
        files = {"file": ("voice.ogg", blob, "audio/ogg")}
        data = {"model": model, "language": "ru", "response_format": "json"}
        headers = {"Authorization": f"Bearer {key}"}
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(URL, files=files, data=data, headers=headers)
        if 400 <= resp.status_code < 500:
            log.warning("openai stt %s: %s", resp.status_code, resp.text[:200])
            return None
        if resp.status_code >= 500:
            raise STTError(f"openai stt {resp.status_code}")
        return (resp.json().get("text") or "").strip() or None
