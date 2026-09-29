# -*- coding: utf-8 -*-
"""Сверка счёта с пересчётом по факту (29.09, Артём: «сколько родительских дирхам осталось по факту
и сколько должно было остаться»).

Настройка `account_checks` — словарь slug → {base_amount, base_note, base_entry_ids, fact}.
Отправная точка — сумма со слов Артёма (base_amount), она заменяет операции base_entry_ids.
Всё, что прошло по счёту помимо них, идёт строками «+/−» — живьём из проводок, поэтому новая
операция по наличке сама попадает в сверку. Факт вводит Артём: ядро выравнивает остаток обычной
операцией balance_correction и запоминает, что было по учёту в момент пересчёта."""
from __future__ import annotations

import sqlite3

from backend import db, settings_store
from backend.contracts import LedgerError, ParsedOperation
from backend.ledger.common import account_row, money_dict, resolve_account
from backend.money import fmt_amount
from backend.tz import today_dubai

SETTING = "account_checks"


def _config(conn: sqlite3.Connection, slug: str) -> dict | None:
    checks = settings_store.get(SETTING, {}, conn=conn) or {}
    cfg = checks.get(slug) if isinstance(checks, dict) else None
    return cfg if isinstance(cfg, dict) else None


def _balance(conn: sqlite3.Connection, account_id: int, currency: str) -> int:
    row = conn.execute(
        "SELECT COALESCE(SUM(p.amount), 0) AS s FROM postings p JOIN entries e ON e.id = p.entry_id"
        " WHERE p.account_id = ? AND p.currency = ? AND e.status = 'posted' AND e.sealed = 1",
        (account_id, currency)).fetchone()
    return int(row["s"])


def check_view(conn: sqlite3.Connection, account: sqlite3.Row) -> dict | None:
    cfg = _config(conn, account["slug"])
    if cfg is None:
        return None
    currency = account["currency"] or "AED"
    base = int(cfg.get("base_amount") or 0)
    base_ids = {int(x) for x in cfg.get("base_entry_ids") or []}
    rows = conn.execute(
        "SELECT e.id AS id, e.op_date AS op_date, e.description AS description, e.kind AS kind,"
        " SUM(p.amount) AS amount"
        " FROM postings p JOIN entries e ON e.id = p.entry_id"
        " WHERE p.account_id = ? AND p.currency = ? AND e.status = 'posted' AND e.sealed = 1"
        " GROUP BY e.id ORDER BY e.op_date, e.id", (int(account["id"]), currency)).fetchall()
    items = [{"entry_id": int(r["id"]), "op_date": r["op_date"], "kind": r["kind"],
              "description": r["description"] or "", "amount": money_dict(int(r["amount"]), currency)}
             for r in rows if int(r["id"]) not in base_ids and int(r["amount"]) != 0]
    expected = base + sum(i["amount"]["amount"] for i in items)
    ledger = _balance(conn, int(account["id"]), currency)
    fact = cfg.get("fact") if isinstance(cfg.get("fact"), dict) else None
    return {
        "base": money_dict(base, currency),
        "base_note": cfg.get("base_note") or "",
        "items": items,
        "expected": money_dict(expected, currency),
        "ledger": money_dict(ledger, currency),
        # не ноль — значит, правили операции, которые заменяет стартовая сумма
        "mismatch": money_dict(ledger - expected, currency) if ledger != expected else None,
        "fact": fact,
    }


def enter_fact(account_ref, amount: int, *, actor: str = "api", note: str | None = None) -> dict:
    """Артём пересчитал наличку: выровнять остаток под факт и запомнить пересчёт."""
    from backend.ledger.api import post_operation   # api импортирует balances, а тот — нас: без цикла

    conn = db.get_conn()
    account = resolve_account(conn, account_ref)
    if _config(conn, account["slug"]) is None:
        raise LedgerError("bad_request", "Для этого счёта сверка не настроена",
                          {"account": account["slug"]})
    if amount < 0:
        raise LedgerError("bad_request", "Факт не может быть меньше нуля", {"amount": amount})
    currency = account["currency"] or "AED"
    before = _balance(conn, int(account["id"]), currency)
    delta = int(amount) - before
    entry_id = None
    today = today_dubai()
    if delta:
        text = (f"Сверка: пересчитал {fmt_amount(amount, currency)}, по учёту было "
                f"{fmt_amount(before, currency)}")
        if note:
            text += f" ({note})"
        out = post_operation(ParsedOperation(kind="balance_correction", amount=delta,
                                             currency=currency, to_account=account["slug"],
                                             op_date=today, source="manual", description=text),
                             actor=actor)
        entry_id = out.get("id")
    with db.transaction(conn):
        checks = settings_store.get(SETTING, {}, conn=conn) or {}
        cfg = dict(checks.get(account["slug"]) or {})
        cfg["fact"] = {"amount": money_dict(int(amount), currency), "date": today,
                       "ledger_before": money_dict(before, currency),
                       "diff": money_dict(delta, currency), "entry_id": entry_id}
        checks[account["slug"]] = cfg
        settings_store.set(SETTING, checks, conn=conn)
    fresh = account_row(conn, int(account["id"]))
    return {"check": check_view(conn, fresh), "entry_id": entry_id}
