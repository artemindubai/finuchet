# -*- coding: utf-8 -*-
"""Лимиты по категориям. В v1 лимит только месячный (ARCHITECTURE §3, §5.10)."""
from __future__ import annotations

import sqlite3

from backend import db
from backend.contracts import LedgerError
from backend.ledger.common import audit, resolve_account
from backend.tz import today_dubai, utc_now


def _conn() -> sqlite3.Connection:
    return db.get_conn()


def limits_view(month: str | None = None) -> dict:
    from backend.ledger.analytics import analytics_month
    month = month or today_dubai()[:7]
    return {"items": analytics_month(month)["limits"], "month": month}


def set_limit(category, amount: int, currency: str, active: bool = True) -> dict:
    conn = _conn()
    row = resolve_account(conn, category, field="category")
    if row["type"] != "expense":
        raise LedgerError("bad_request", "Лимит ставится на категорию расходов",
                          {"field": "category"})
    with db.transaction(conn):
        conn.execute(
            "INSERT INTO limits (category_id, period, amount, currency, active, created_at)"
            " VALUES (?, 'month', ?, ?, ?, ?)"
            " ON CONFLICT(category_id, period) DO UPDATE SET amount = excluded.amount,"
            " currency = excluded.currency, active = excluded.active",
            (int(row["id"]), int(amount), currency, 1 if active else 0, utc_now()))
        audit(conn, "api", "limit_set", "account", int(row["id"]),
              {"amount": int(amount), "currency": currency})
    return limits_view()


def delete_limit(category) -> dict:
    conn = _conn()
    row = resolve_account(conn, category, field="category")
    with db.transaction(conn):
        conn.execute("DELETE FROM limits WHERE category_id = ?", (int(row["id"]),))
        audit(conn, "api", "limit_delete", "account", int(row["id"]), None)
    return limits_view()
