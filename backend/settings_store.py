# -*- coding: utf-8 -*-
"""Настройки: таблица settings (JSON-значения) с умолчаниями (ARCHITECTURE §5.12)."""
from __future__ import annotations

import json
import os
import sqlite3

from backend import db
from backend.tz import utc_now

DEFAULTS: dict = {
    "default_currency_view": "RUB",
    "family_block_visible": True,
    "freeze_account": "tbank",
    "rate_markup_rub_per_aed_e6": 2_000_000,
    "tax_rate_default_bp": 600,
    "remind_enabled": True,
    # 25.09 Артём: личная копилка не входит в «Мои деньги», видна по кнопке.
    "hidden_accounts": ["kopilka_mashrek"],
}

# Наружу отдаются только эти ключи плюс вычисляемые в API; секреты — никогда.
PUBLIC_KEYS = (
    "default_currency_view", "family_block_visible", "freeze_account",
    "rate_markup_rub_per_aed_e6", "tax_rate_default_bp", "remind_enabled", "hidden_accounts",
)
SECRET_KEYS = ("mashreq_pdf_password",)


def _conn(conn: sqlite3.Connection | None = None) -> sqlite3.Connection:
    return conn or db.get_conn()


def ensure_defaults(conn: sqlite3.Connection | None = None) -> None:
    conn = _conn(conn)
    markup_env = os.environ.get("RATE_MARKUP_RUB_PER_AED")
    tax_env = os.environ.get("TAX_RATE_DEFAULT_BP")
    defaults = dict(DEFAULTS)
    if markup_env:
        try:
            defaults["rate_markup_rub_per_aed_e6"] = int(round(float(markup_env) * 1_000_000))
        except ValueError:
            pass
    if tax_env and tax_env.isdigit():
        defaults["tax_rate_default_bp"] = int(tax_env)
    for key, value in defaults.items():
        conn.execute(
            "INSERT INTO settings (key, value, updated_at) VALUES (?,?,?)"
            " ON CONFLICT(key) DO NOTHING",
            (key, json.dumps(value, ensure_ascii=False), utc_now()),
        )


def get(key: str, default=None, *, conn: sqlite3.Connection | None = None):
    row = _conn(conn).execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    if row is None:
        return DEFAULTS.get(key, default)
    try:
        return json.loads(row["value"])
    except json.JSONDecodeError:
        return row["value"]


def set(key: str, value, *, conn: sqlite3.Connection | None = None) -> None:
    _conn(conn).execute(
        "INSERT INTO settings (key, value, updated_at) VALUES (?,?,?)"
        " ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
        (key, json.dumps(value, ensure_ascii=False), utc_now()),
    )


def delete(key: str, *, conn: sqlite3.Connection | None = None) -> None:
    _conn(conn).execute("DELETE FROM settings WHERE key = ?", (key,))


def all_public(*, conn: sqlite3.Connection | None = None) -> dict:
    out = {key: get(key, conn=conn) for key in PUBLIC_KEYS}
    out["mashreq_pdf_password_set"] = bool(get("mashreq_pdf_password", "", conn=conn)) \
        or bool(os.environ.get("MASHREQ_PDF_PASSWORD"))
    out["stt_provider"] = os.environ.get("STT_PROVIDER", "telethon")
    return out
