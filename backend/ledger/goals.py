# -*- coding: utf-8 -*-
"""Цели-накопления: виртуальные конверты за балансом (ARCHITECTURE §5.10). Денег не двигают."""
from __future__ import annotations

import sqlite3

from backend import db
from backend.contracts import LedgerError
from backend.ledger.common import account_row, audit, money_dict
from backend.money import share_bp
from backend.tz import today_dubai, utc_now


def _conn() -> sqlite3.Connection:
    return db.get_conn()


def _view(conn: sqlite3.Connection, row: sqlite3.Row) -> dict:
    allocations = conn.execute(
        "SELECT * FROM goal_allocations WHERE goal_id = ? ORDER BY op_date, id",
        (int(row["id"]),)).fetchall()
    saved = sum(int(a["amount"]) for a in allocations)
    return {
        "id": int(row["id"]), "name": row["name"],
        "target": money_dict(int(row["target"]), row["currency"]),
        "saved": money_dict(saved, row["currency"]),
        "progress_bp": share_bp(saved, int(row["target"])) if int(row["target"]) else 0,
        "due_date": row["due_date"], "account_id": row["account_id"],
        "archived": bool(row["archived"]),
        "allocations": [{"amount": money_dict(int(a["amount"]), a["currency"]),
                         "op_date": a["op_date"], "note": a["note"] or ""} for a in allocations],
    }


def goals_view(*, include_archived: bool = False) -> dict:
    conn = _conn()
    sql = "SELECT * FROM goals" + ("" if include_archived else " WHERE archived = 0") + " ORDER BY id"
    return {"items": [_view(conn, row) for row in conn.execute(sql).fetchall()]}


def create(data: dict) -> dict:
    conn = _conn()
    account = account_row(conn, data.get("account"))
    with db.transaction(conn):
        cur = conn.execute(
            "INSERT INTO goals (name, target, currency, account_id, due_date, archived, created_at)"
            " VALUES (?,?,?,?,?,0,?)",
            (data["name"], int(data["target"]), data["currency"],
             int(account["id"]) if account is not None else None, data.get("due_date"), utc_now()))
        goal_id = int(cur.lastrowid)
        audit(conn, "api", "goal_create", "goal", goal_id, data)
    return _view(conn, conn.execute("SELECT * FROM goals WHERE id = ?", (goal_id,)).fetchone())


def patch(goal_id: int, data: dict) -> dict:
    conn = _conn()
    row = conn.execute("SELECT * FROM goals WHERE id = ?", (goal_id,)).fetchone()
    if row is None:
        raise LedgerError("not_found", "Цель не найдена", {"id": goal_id})
    sets, args = [], []
    for key in ("name", "target", "currency", "due_date", "archived"):
        if key in data and data[key] is not None:
            sets.append(f"{key} = ?")
            args.append(int(data[key]) if key in ("target", "archived") else data[key])
    if sets:
        with db.transaction(conn):
            conn.execute(f"UPDATE goals SET {', '.join(sets)} WHERE id = ?", args + [goal_id])
            audit(conn, "api", "goal_patch", "goal", goal_id, data)
    return _view(conn, conn.execute("SELECT * FROM goals WHERE id = ?", (goal_id,)).fetchone())


def archive(goal_id: int) -> dict:
    return patch(goal_id, {"archived": 1})


def goal_allocate(goal_id: int, amount: int, currency: str, op_date: str | None = None,
                  note: str = "") -> dict:
    conn = _conn()
    row = conn.execute("SELECT * FROM goals WHERE id = ?", (goal_id,)).fetchone()
    if row is None:
        raise LedgerError("not_found", "Цель не найдена", {"id": goal_id})
    if int(amount) == 0:
        raise LedgerError("bad_request", "Нулевое перемещение в цель не записывается",
                          {"field": "amount"})
    with db.transaction(conn):
        conn.execute(
            "INSERT INTO goal_allocations (goal_id, amount, currency, op_date, note, created_at)"
            " VALUES (?,?,?,?,?,?)",
            (goal_id, int(amount), currency, op_date or today_dubai(), note or None, utc_now()))
        audit(conn, "api", "goal_allocate", "goal", goal_id, {"amount": int(amount)})
    return _view(conn, conn.execute("SELECT * FROM goals WHERE id = ?", (goal_id,)).fetchone())
