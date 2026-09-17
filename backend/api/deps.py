# -*- coding: utf-8 -*-
"""Авторизация мини-аппа: Telegram initData + белый список одного ID (ARCHITECTURE §5.1)."""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
from urllib.parse import parse_qsl

from fastapi import Request

from backend import db
from backend.contracts import LedgerError
from backend.ledger.common import audit
from backend.tz import utc_now

MAX_AUTH_AGE_SEC = 24 * 3600


def owner_id() -> int | None:
    value = os.environ.get("OWNER_TG_ID", "").strip()
    return int(value) if value.isdigit() else None


def check_init_data(init_data: str, bot_token: str) -> dict:
    """HMAC-SHA256 по алгоритму Telegram. Возвращает разобранный user или падает auth_required."""
    if not init_data or not bot_token:
        raise LedgerError("auth_required", "Нет данных авторизации")
    pairs = dict(parse_qsl(init_data, keep_blank_values=True))
    received = pairs.pop("hash", None)
    if not received:
        raise LedgerError("auth_required", "Нет данных авторизации")
    check_string = "\n".join(f"{key}={pairs[key]}" for key in sorted(pairs))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    computed = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(computed, received):
        raise LedgerError("auth_required", "Нет данных авторизации")
    auth_date = pairs.get("auth_date")
    if auth_date and auth_date.isdigit() and utc_now() - int(auth_date) > MAX_AUTH_AGE_SEC:
        raise LedgerError("auth_required", "Нет данных авторизации")
    try:
        return json.loads(pairs.get("user") or "{}")
    except json.JSONDecodeError:
        raise LedgerError("auth_required", "Нет данных авторизации") from None


def authenticate(request: Request) -> int:
    dev_user = os.environ.get("DEV_USER", "").strip()
    header_user = request.headers.get("X-Dev-User", "").strip()
    user_id: int | None = None
    if dev_user and header_user:
        if not header_user.lstrip("-").isdigit():
            raise LedgerError("auth_required", "Нет данных авторизации")
        user_id = int(header_user)
    else:
        authorization = request.headers.get("Authorization", "")
        if not authorization.startswith("tma "):
            raise LedgerError("auth_required", "Нет данных авторизации")
        user = check_init_data(authorization[4:].strip(), os.environ.get("BOT_TOKEN", ""))
        user_id = int(user.get("id") or 0)

    owner = owner_id()
    if owner is not None and user_id != owner:
        try:
            conn = db.get_conn()
            with db.transaction(conn):
                audit(conn, "api", "forbidden", "user", user_id, {"path": str(request.url.path)})
        except Exception:                       # журнал не должен мешать отказу
            pass
        raise LedgerError("forbidden", "Доступ запрещён")
    return user_id


async def require_user(request: Request) -> int:
    return await asyncio.to_thread(authenticate, request)


async def run(func, *args, **kwargs):
    """Ядро синхронное: зовём его из событийного цикла через поток."""
    return await asyncio.to_thread(func, *args, **kwargs)


def currency_param(value: str | None) -> str:
    from backend import settings_store
    if value and value.upper() in ("RUB", "USD", "AED", "USDT"):
        return value.upper()
    return str(settings_store.get("default_currency_view", "RUB") or "RUB")
