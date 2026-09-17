# -*- coding: utf-8 -*-
"""Инвариант двойной записи и неизменяемость проводок (ТЗ 4.1, ARCHITECTURE §3)."""
import sqlite3

import pytest

from backend import db, ledger
from backend.tz import utc_now
from tests.conftest import base_state, post


def test_every_entry_balanced_by_currency():
    base_state()
    post(kind="expense", amount=4300, currency="AED", from_account="mashreq_personal",
         category="exp_cafe")
    post(kind="income", amount=9_000_000, currency="RUB", to_account="tbank",
         income_source="inc_projects", project="Альфа")
    post(kind="transfer", amount=2_000_000, currency="RUB", from_account="tbank", to_account="sber")
    post(kind="exchange", amount=5_000_000, currency="RUB", from_account="tbank",
         amount_to=50_000, currency_to="USDT", to_account="bybit")
    post(kind="family_withdrawal", amount=50_000, currency="AED", from_account="mashreq_family",
         to_account="mashreq_personal")
    post(kind="loan_given", amount=30_000, currency="AED", from_account="mashreq_personal",
         counterparty="Маша")
    post(kind="tax_payment", amount=1_836_000, currency="RUB", from_account="tbank")

    conn = db.get_conn()
    rows = conn.execute(
        "SELECT entry_id, currency, SUM(amount) AS total FROM postings"
        " GROUP BY entry_id, currency HAVING SUM(amount) <> 0").fetchall()
    assert rows == []
    assert ledger.check_invariants() == []


def test_trigger_rejects_unbalanced():
    conn = db.get_conn()
    account = conn.execute("SELECT id FROM accounts WHERE slug = 'tbank'").fetchone()["id"]
    conn.execute("BEGIN IMMEDIATE")
    cur = conn.execute(
        "INSERT INTO entries (kind, op_date, created_at, description, source, sealed)"
        " VALUES ('expense','2026-09-17',?,'кривая','manual',0)", (utc_now(),))
    entry_id = int(cur.lastrowid)
    conn.execute("INSERT INTO postings (entry_id, seq, account_id, amount, currency)"
                 " VALUES (?,1,?,-1000,'RUB')", (entry_id, account))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE entries SET sealed = 1 WHERE id = ?", (entry_id,))
    conn.execute("ROLLBACK")


def test_postings_immutable():
    base_state()
    result = post(kind="expense", amount=4300, currency="AED", from_account="mashreq_personal",
                  category="exp_cafe")
    conn = db.get_conn()
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE postings SET amount = 1 WHERE entry_id = ?", (result["id"],))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("DELETE FROM postings WHERE entry_id = ?", (result["id"],))


def test_no_unsealed_posted_entries():
    base_state()
    conn = db.get_conn()
    account = conn.execute("SELECT id FROM accounts WHERE slug = 'tbank'").fetchone()["id"]
    conn.execute("BEGIN IMMEDIATE")
    cur = conn.execute(
        "INSERT INTO entries (kind, op_date, created_at, description, source, sealed)"
        " VALUES ('expense','2026-09-17',?,'обрыв','manual',0)", (utc_now(),))
    entry_id = int(cur.lastrowid)
    conn.execute("INSERT INTO postings (entry_id, seq, account_id, amount, currency)"
                 " VALUES (?,1,?,-1000,'RUB')", (entry_id, account))
    conn.execute("COMMIT")

    before = ledger.balances()["net_worth"]["amount"]
    assert any("не запечатана" in problem for problem in ledger.check_invariants())
    # незапечатанная операция в остатки не попадает
    assert ledger.balances()["net_worth"]["amount"] == before
    row = db.get_conn().execute(
        "SELECT COUNT(*) AS n FROM v_balances WHERE account_id = ?", (account,)).fetchone()
    assert row["n"] == 1        # только строка из начальных остатков
