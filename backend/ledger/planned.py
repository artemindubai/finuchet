# -*- coding: utf-8 -*-
"""Календарь платежей (ARCHITECTURE §5.9): план, отметка «Оплачено», сдвиг даты по повтору."""
from __future__ import annotations

import sqlite3

from backend import db
from backend.contracts import LedgerError, ParsedOperation
from backend.ledger.common import account_row, audit, money_dict, resolve_account
from backend.tz import days_between, days_in_month, today_dubai, utc_now

REPEATS = ("once", "weekly", "monthly", "quarterly", "yearly")


def _conn() -> sqlite3.Connection:
    return db.get_conn()


def _next_date(current: str, repeat: str, day_of_month: int | None) -> str | None:
    from datetime import datetime, timedelta
    day = datetime.strptime(current, "%Y-%m-%d")
    if repeat == "once":
        return None
    if repeat == "weekly":
        return (day + timedelta(days=7)).strftime("%Y-%m-%d")
    months = {"monthly": 1, "quarterly": 3, "yearly": 12}[repeat]
    total = day.year * 12 + (day.month - 1) + months
    year, month = total // 12, total % 12 + 1
    target = day_of_month or day.day
    return f"{year:04d}-{month:02d}-{min(target, days_in_month(year, month)):02d}"


def item_view(conn: sqlite3.Connection, row: sqlite3.Row, *, today: str | None = None) -> dict:
    today = today or today_dubai()
    last_paid = None
    if row["last_paid_entry_id"]:
        last_paid = {"entry_id": int(row["last_paid_entry_id"]), "op_date": row["last_paid_date"]}
    return {
        "id": int(row["id"]), "title": row["title"],
        "amount": money_dict(int(row["amount"]), row["currency"]),
        "next_date": row["next_date"], "days_left": days_between(today, row["next_date"]),
        "repeat": row["repeat"], "day_of_month": row["day_of_month"],
        "account_id": row["account_id"], "category_id": row["category_id"],
        "remind_days_before": int(row["remind_days_before"]), "active": bool(row["active"]),
        "overdue": row["next_date"] < today, "last_paid": last_paid,
    }


def calendar(*, date_from: str | None = None, date_to: str | None = None,
             limit: int | None = None) -> dict:
    conn = _conn()
    where = ["active = 1"]
    args: list = []
    if date_from:
        where.append("next_date >= ?")
        args.append(date_from)
    if date_to:
        where.append("next_date <= ?")
        args.append(date_to)
    sql = f"SELECT * FROM planned_payments WHERE {' AND '.join(where)} ORDER BY next_date, id"
    if limit:
        sql += f" LIMIT {int(limit)}"
    rows = conn.execute(sql, args).fetchall()
    today = today_dubai()
    return {"items": [item_view(conn, row, today=today) for row in rows]}


def upcoming(limit: int = 3) -> list[dict]:
    return calendar(date_from=today_dubai(), limit=limit)["items"]


def create(data: dict) -> dict:
    conn = _conn()
    repeat = data.get("repeat", "once")
    if repeat not in REPEATS:
        raise LedgerError("bad_request", "Неизвестный повтор", {"field": "repeat"})
    account = account_row(conn, data.get("account"))
    category = account_row(conn, data.get("category"))
    with db.transaction(conn):
        cur = conn.execute(
            "INSERT INTO planned_payments (title, amount, currency, account_id, category_id,"
            " counterparty_id, repeat, next_date, day_of_month, remind_days_before, active, created_at)"
            " VALUES (?,?,?,?,?,NULL,?,?,?,?,1,?)",
            (data["title"], int(data["amount"]), data["currency"],
             int(account["id"]) if account is not None else None,
             int(category["id"]) if category is not None else None,
             repeat, data["next_date"], data.get("day_of_month"),
             int(data.get("remind_days_before") or 0), utc_now()))
        planned_id = int(cur.lastrowid)
        audit(conn, "api", "planned_create", "planned", planned_id, data)
    row = conn.execute("SELECT * FROM planned_payments WHERE id = ?", (planned_id,)).fetchone()
    return item_view(conn, row)


def patch(planned_id: int, data: dict) -> dict:
    conn = _conn()
    row = conn.execute("SELECT * FROM planned_payments WHERE id = ?", (planned_id,)).fetchone()
    if row is None:
        raise LedgerError("not_found", "Платёж не найден", {"id": planned_id})
    allowed = {"title", "amount", "currency", "repeat", "next_date", "day_of_month",
               "remind_days_before", "active"}
    sets, args = [], []
    for key, value in data.items():
        if key in allowed:
            sets.append(f"{key} = ?")
            args.append(int(value) if key in ("amount", "day_of_month", "remind_days_before",
                                              "active") and value is not None else value)
    if data.get("account") is not None:
        account = resolve_account(conn, data["account"])
        sets.append("account_id = ?")
        args.append(int(account["id"]))
    if data.get("category") is not None:
        category = resolve_account(conn, data["category"])
        sets.append("category_id = ?")
        args.append(int(category["id"]))
    if sets:
        with db.transaction(conn):
            conn.execute(f"UPDATE planned_payments SET {', '.join(sets)} WHERE id = ?",
                         args + [planned_id])
            audit(conn, "api", "planned_patch", "planned", planned_id, data)
    row = conn.execute("SELECT * FROM planned_payments WHERE id = ?", (planned_id,)).fetchone()
    return item_view(conn, row)


def deactivate(planned_id: int) -> dict:
    return patch(planned_id, {"active": 0})


def mark_planned_paid(planned_id: int, *, op_date: str | None = None, amount: int | None = None,
                      account=None, actor: str = "api", currency_view: str = "RUB") -> dict:
    """«Оплачено» создаёт расход и двигает план на следующую дату (§5.9)."""
    from backend.ledger import api
    conn = _conn()
    row = conn.execute("SELECT * FROM planned_payments WHERE id = ?", (planned_id,)).fetchone()
    if row is None:
        raise LedgerError("not_found", "Платёж не найден", {"id": planned_id})
    op_date = op_date or row["next_date"] or today_dubai()
    op = ParsedOperation(
        kind="expense", amount=int(amount or row["amount"]), currency=row["currency"],
        from_account=row["account_id"], category=row["category_id"], op_date=op_date,
        description=row["title"], source="manual")
    result = api.post_operation(op, actor=actor, currency_view=currency_view)
    next_date = _next_date(row["next_date"], row["repeat"], row["day_of_month"])
    with db.transaction(conn):
        if next_date:
            conn.execute("UPDATE planned_payments SET next_date = ?, last_paid_entry_id = ?,"
                         " last_paid_date = ? WHERE id = ?",
                         (next_date, result["id"], op_date, planned_id))
        else:
            conn.execute("UPDATE planned_payments SET active = 0, last_paid_entry_id = ?,"
                         " last_paid_date = ? WHERE id = ?", (result["id"], op_date, planned_id))
        audit(conn, actor, "planned_paid", "planned", planned_id, {"entry_id": result["id"]})
    row = conn.execute("SELECT * FROM planned_payments WHERE id = ?", (planned_id,)).fetchone()
    result["planned"] = item_view(conn, row)
    return result


def due_reminders(*, today: str | None = None) -> list[dict]:
    """Что напомнить сегодня: только планы с remind_days_before > 0 (бот молчит по умолчанию)."""
    conn = _conn()
    today = today or today_dubai()
    rows = conn.execute(
        "SELECT * FROM planned_payments WHERE active = 1 AND remind_days_before > 0").fetchall()
    out = []
    for row in rows:
        left = days_between(today, row["next_date"])
        if 0 <= left <= int(row["remind_days_before"]) or left < 0:
            out.append(item_view(conn, row, today=today))
    return out
