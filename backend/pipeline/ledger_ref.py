# -*- coding: utf-8 -*-
"""Единственная дверь бота в ядро учёта.

Бот в БД не ходит (ARCHITECTURE §1, правило 1): всё — через `backend.ledger.api` и
`backend.ledger.bot_bridge` (владелец обоих — агент A). Здесь только поиск функции по имени
и запуск синхронного ядра в потоке: ядро на SQLite, функции синхронные (§4 общие правила).

Тесты подменяют ядро целиком: `ledger_ref.set_ledger(FakeLedger())`.
"""
from __future__ import annotations

import asyncio
import inspect
import logging
from typing import Any, Callable

log = logging.getLogger("finuchet.ledger_ref")

_override: Any = None


class LedgerUnavailable(RuntimeError):
    """Ядро ещё не собрано или в нём нет нужной функции."""


def set_ledger(obj: Any) -> None:
    """Подменить ядро объектом с теми же именами функций (тесты, offline_check)."""
    global _override
    _override = obj


def _modules() -> list[Any]:
    mods: list[Any] = []
    if _override is not None:
        return [_override]
    for name in ("backend.ledger.bot_bridge", "backend.ledger.api"):
        try:
            mods.append(__import__(name, fromlist=["*"]))
        except Exception as exc:  # ядро может ещё не существовать — это не падение бота
            log.debug("нет модуля %s: %s", name, exc)
    return mods


def resolve(name: str) -> Callable[..., Any]:
    for mod in _modules():
        fn = getattr(mod, name, None)
        if callable(fn):
            return fn
    raise LedgerUnavailable(f"в ядре нет функции {name}()")


def has(name: str) -> bool:
    try:
        resolve(name)
        return True
    except LedgerUnavailable:
        return False


def call_sync(name: str, *args: Any, **kwargs: Any) -> Any:
    return resolve(name)(*args, **kwargs)


async def call(name: str, *args: Any, **kwargs: Any) -> Any:
    """Ядро синхронное — зовём его в отдельном потоке, чтобы не держать event loop."""
    fn = resolve(name)
    if inspect.iscoroutinefunction(fn):
        return await fn(*args, **kwargs)
    return await asyncio.to_thread(fn, *args, **kwargs)
