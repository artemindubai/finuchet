# -*- coding: utf-8 -*-
"""Мелочь, общая для всех модулей ядра: счета, контрагенты, предупреждения, пересчёт в валюту показа."""
from __future__ import annotations

import json
import re
import sqlite3

from backend import money, rates, settings_store
from backend.contracts import LedgerError
from backend.tz import utc_now

ASSET_TYPES = ("asset_personal", "asset_family")
NEGATIVE_TYPES = ("liability", "income", "equity")   # показываются со сменой знака (§3)
VIEW_CURRENCIES = ("RUB", "USD", "AED")

_INT_TEXT = re.compile(r"^[+-]?\d+$")


def minor_amount(value, *, field: str = "amount"):
    """Сумма в минорных единицах — только целое число (§4.4, грабля 36).

    43,99 копейки не бывает: дробь здесь всегда ошибка клиента, и молча отрезать её нельзя —
    иначе 4300.99 тихо становится 4300 и 99 копеек исчезают из учёта."""
    if value is None:
        return None
    if isinstance(value, bool):
        raise LedgerError("bad_request", "Сумма должна быть числом", {"field": field})
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not value.is_integer():
            raise LedgerError("bad_request",
                              "Сумма указывается в целых минорных единицах (копейки, филсы)",
                              {"field": field, "value": value})
        return int(value)
    text = str(value).strip().replace(" ", "").replace(" ", "")
    if _INT_TEXT.match(text):
        return int(text)
    raise LedgerError("bad_request",
                      "Сумма указывается в целых минорных единицах (копейки, филсы)",
                      {"field": field, "value": value})


def warn(code: str, message: str, details: dict | None = None) -> dict:
    return {"code": code, "message": message, "details": details or {}}


def account_row(conn: sqlite3.Connection, ref) -> sqlite3.Row | None:
    if ref is None:
        return None
    if isinstance(ref, sqlite3.Row):
        return ref
    if isinstance(ref, bool):
        return None
    if isinstance(ref, int):
        return conn.execute("SELECT * FROM accounts WHERE id = ?", (ref,)).fetchone()
    text = str(ref).strip()
    if text.isdigit():
        row = conn.execute("SELECT * FROM accounts WHERE id = ?", (int(text),)).fetchone()
        if row:
            return row
    return conn.execute("SELECT * FROM accounts WHERE slug = ?", (text,)).fetchone()


def resolve_account(conn: sqlite3.Connection, ref, *, field: str = "account") -> sqlite3.Row:
    row = account_row(conn, ref)
    if row is None:
        raise LedgerError("unknown_account", f"Счёт не найден: {ref}", {"field": field, "value": ref})
    return row


def account_id_of(conn: sqlite3.Connection, ref, *, field: str = "account") -> int:
    return int(resolve_account(conn, ref, field=field)["id"])


def role_of(type_: str) -> str:
    return "liability" if type_ in ("liability",) else "asset"


def natural_sign(type_: str) -> int:
    return -1 if type_ in NEGATIVE_TYPES else 1


def ensure_counterparty(conn: sqlite3.Connection, name: str | None, kind: str = "person") -> int | None:
    if not name:
        return None
    name = str(name).strip()
    if not name:
        return None
    row = conn.execute("SELECT id FROM counterparties WHERE name = ?", (name,)).fetchone()
    if row:
        return int(row["id"])
    cur = conn.execute(
        "INSERT INTO counterparties (name, kind, archived, created_at) VALUES (?,?,0,?)",
        (name, kind, utc_now()))
    return int(cur.lastrowid)


def counterparty_name(conn: sqlite3.Connection, cp_id: int | None) -> str | None:
    if not cp_id:
        return None
    row = conn.execute("SELECT name FROM counterparties WHERE id = ?", (cp_id,)).fetchone()
    return row["name"] if row else None


def audit(conn: sqlite3.Connection, actor: str, action: str,
          object_type: str | None = None, object_id: int | None = None,
          payload: dict | None = None) -> None:
    conn.execute(
        "INSERT INTO audit_log (at, actor, action, object_type, object_id, payload)"
        " VALUES (?,?,?,?,?,?)",
        (utc_now(), actor, action, object_type, object_id,
         json.dumps(payload, ensure_ascii=False) if payload else None))


def freeze_account_slug(conn: sqlite3.Connection) -> str:
    return str(settings_store.get("freeze_account", "tbank", conn=conn) or "tbank")


def snapshot_of(conn: sqlite3.Connection, raw: str | None) -> dict:
    if not raw:
        return rates.snapshot(conn=conn)
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return rates.snapshot(conn=conn)


def to_view(amount: int, currency: str, view: str, snapshot: dict) -> int:
    """Пересчёт суммы в валюту показа. Курса нет — это 503 rate_unavailable, а не тихий ноль."""
    if currency == view:
        return int(amount)
    try:
        return money.convert(int(amount), currency, view, snapshot=snapshot)
    except ValueError as exc:
        raise LedgerError("rate_unavailable", "Курс недоступен: пересчитать нечем",
                          {"src": currency, "dst": view, "reason": str(exc)}) from exc


def money_dict(amount: int, currency: str) -> dict:
    return {"amount": int(amount), "currency": currency}
