# -*- coding: utf-8 -*-
"""Короткая память диалога: «Поправить», уточнение, разбор скрина.

Хранится в таблице bot_pending на стороне ядра (§4.1) — бот в БД не ходит. Просрочка 30 минут
означает, что состояния нет: следующая фраза снова считается новой операцией.
"""
from __future__ import annotations

import logging
from typing import Any

from backend.pipeline import ledger_ref

log = logging.getLogger("finuchet.pending")

TTL_SEC = 1800

AMEND = "amend"
CLARIFY = "clarify"
RECONCILE = "reconcile"


async def get(chat_id: int) -> dict[str, Any] | None:
    try:
        return await ledger_ref.call("pending_get", chat_id)
    except Exception as exc:
        log.debug("pending_get недоступен: %s", exc)
        return None


async def set_state(chat_id: int, state: str, entry_id: int | None, payload: dict[str, Any]) -> None:
    try:
        await ledger_ref.call("pending_set", chat_id, state, entry_id, payload, ttl_sec=TTL_SEC)
    except Exception as exc:
        log.warning("не сохранил состояние диалога: %s", exc)


async def clear(chat_id: int) -> None:
    try:
        await ledger_ref.call("pending_clear", chat_id)
    except Exception as exc:
        log.debug("pending_clear недоступен: %s", exc)
