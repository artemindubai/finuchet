# -*- coding: utf-8 -*-
"""Рецепты проводок по каждому виду операции (ТЗ 4.2, ARCHITECTURE §4.2)."""
import sqlite3

import pytest

from backend import db, ledger
from backend.contracts import LedgerError
from tests.conftest import balance, base_state, opening, post


def postings_of(entry: dict) -> list[tuple[str, int, str]]:
    return [(p["account_slug"], p["amount"]["amount"] * (1 if p["side"] == "debit" else -1),
             p["amount"]["currency"]) for p in entry["postings"]]


def test_expense_aed():
    base_state()
    entry = post(kind="expense", amount=4300, currency="AED", from_account="mashreq_personal",
                 category="exp_cafe", description="обед в кафе")
    assert postings_of(entry) == [("exp_cafe", 4300, "AED"), ("mashreq_personal", -4300, "AED")]
    assert entry["title"] == "Кафе и рестораны"
    assert entry["subtitle"] == "Mashreq личный"
    assert entry["direction"] == "out"
    assert balance("mashreq_personal", "AED") == 184_250 - 4_300


def test_income_uae_no_tax():
    base_state()
    entry = post(kind="income", amount=200_000, currency="AED", to_account="mashreq_personal",
                 income_source="inc_uae_job")
    assert postings_of(entry) == [("mashreq_personal", 200_000, "AED"),
                                  ("inc_uae_job", -200_000, "AED")]
    assert balance("mashreq_personal", "AED") == 384_250


def test_income_project_npd_6pct():
    base_state()
    entry = post(kind="income", amount=9_000_000, currency="RUB", to_account="tbank",
                 income_source="inc_projects", project="Альфа")
    assert postings_of(entry) == [("tbank", 9_000_000, "RUB"), ("inc_projects", -9_000_000, "RUB"),
                                  ("exp_taxes", 540_000, "RUB"), ("tax_npd", -540_000, "RUB")]
    assert balance("tax_npd", "RUB") == -540_000        # обязательство держим со знаком минус
    assert ledger.debts()["tax"]["amount"] == {"amount": 540_000, "currency": "RUB"}


def test_income_project_no_tax_flag():
    base_state()
    entry = post(kind="income", amount=9_000_000, currency="RUB", to_account="tbank",
                 income_source="inc_projects", no_tax=True)
    assert len(entry["postings"]) == 2
    assert balance("tax_npd", "RUB") == 0


def test_income_tax_currency_mismatch_warns():
    base_state()
    entry = post(kind="income", amount=50_000, currency="USDT", to_account="bybit",
                 income_source="inc_projects")
    assert len(entry["postings"]) == 2
    assert [w["code"] for w in entry["warnings"]] == ["tax_currency_mismatch"]
    assert balance("tax_npd", "RUB") == 0


def test_transfer_same_currency():
    base_state()
    entry = post(kind="transfer", amount=2_000_000, currency="RUB", from_account="tbank",
                 to_account="sber")
    assert postings_of(entry) == [("sber", 2_000_000, "RUB"), ("tbank", -2_000_000, "RUB")]
    assert entry["subtitle"] == "Т-Банк → Сбер"


def test_transfer_cross_currency_rejected():
    base_state()
    with pytest.raises(LedgerError) as exc:
        post(kind="transfer", amount=2_000_000, currency="RUB", from_account="tbank",
             to_account="mashreq_personal")
    assert exc.value.code == "currency_mismatch"


def test_exchange_rub_usdt_via_service_account():
    base_state()
    entry = post(kind="exchange", amount=5_000_000, currency="RUB", from_account="tbank",
                 amount_to=51_230, currency_to="USDT", to_account="bybit")
    assert postings_of(entry) == [("bybit", 51_230, "USDT"), ("eq_exchange", -51_230, "USDT"),
                                  ("eq_exchange", 5_000_000, "RUB"), ("tbank", -5_000_000, "RUB")]
    assert balance("bybit", "USDT") == 41_025 + 51_230
    assert balance("tbank", "RUB") == 13_200_000 - 5_000_000
    assert entry["rate"]["rate_e6"] == 97_599_063          # 50 000 ₽ / 512,30 USDT
    assert ledger.check_invariants() == []


def test_exchange_no_commission_line():
    base_state()
    entry = post(kind="exchange", amount=5_000_000, currency="RUB", from_account="tbank",
                 amount_to=51_230, currency_to="USDT", to_account="bybit")
    slugs = [p["account_slug"] for p in entry["postings"]]
    assert not any(slug.startswith("exp_") for slug in slugs)


def test_loan_given_requires_counterparty():
    base_state()
    with pytest.raises(LedgerError) as exc:
        post(kind="loan_given", amount=30_000, currency="AED", from_account="mashreq_personal")
    assert exc.value.code == "counterparty_required"

    entry = post(kind="loan_given", amount=30_000, currency="AED",
                 from_account="mashreq_personal", counterparty="Маша")
    assert postings_of(entry) == [("receivable", 30_000, "AED"),
                                  ("mashreq_personal", -30_000, "AED")]
    debts = ledger.debts()
    assert debts["owed_to_me"][0]["name"] == "Маша"
    assert debts["owed_to_me"][0]["amounts"] == [{"amount": 30_000, "currency": "AED"}]


def test_credit_card_purchase_and_repayment():
    base_state()
    purchase = post(kind="expense", amount=240_000, currency="RUB", from_account="sber_credit",
                    category="exp_groceries")
    assert postings_of(purchase) == [("exp_groceries", 240_000, "RUB"),
                                     ("sber_credit", -240_000, "RUB")]
    assert balance("sber_credit", "RUB") == -240_000
    assert ledger.debts()["credit_card"]["amount"]["amount"] == 240_000

    post(kind="transfer", amount=240_000, currency="RUB", from_account="tbank",
         to_account="sber_credit")
    assert balance("sber_credit", "RUB") == 0


def test_tax_payment_closes_npd():
    base_state()
    post(kind="income", amount=9_000_000, currency="RUB", to_account="tbank",
         income_source="inc_projects")
    entry = post(kind="tax_payment", amount=540_000, currency="RUB", from_account="tbank")
    assert postings_of(entry) == [("tax_npd", 540_000, "RUB"), ("tbank", -540_000, "RUB")]
    assert balance("tax_npd", "RUB") == 0


def test_opening_balance_family_goes_to_fund():
    opening(("mashreq_family", 850_000, "AED"))
    conn = db.get_conn()
    rows = conn.execute(
        "SELECT a.slug AS slug, p.amount AS amount FROM postings p"
        " JOIN accounts a ON a.id = p.account_id ORDER BY p.seq").fetchall()
    assert [(r["slug"], int(r["amount"])) for r in rows] == \
        [("mashreq_family", 850_000), ("family_fund", -850_000)]
    assert ledger.family_debt()["debt"]["amount"] == 0


def test_opening_balance_on_family_fund_rejected():
    for slug in ("family_fund", "eq_opening", "exp_cafe", "inc_projects"):
        with pytest.raises(LedgerError) as exc:
            opening((slug, 100_000, "AED"))
        assert exc.value.code == "opening_balance_not_allowed"


def test_posting_currency_must_match_account_currency():
    base_state()
    with pytest.raises(LedgerError) as exc:
        post(kind="expense", amount=5_000, currency="USDT", from_account="tbank",
             category="exp_cafe")
    assert exc.value.code == "currency_mismatch"

    conn = db.get_conn()
    tbank = conn.execute("SELECT id FROM accounts WHERE slug = 'tbank'").fetchone()["id"]
    conn.execute("BEGIN IMMEDIATE")
    cur = conn.execute(
        "INSERT INTO entries (kind, op_date, created_at, description, source, sealed)"
        " VALUES ('expense','2026-09-17',0,'','manual',0)")
    entry_id = int(cur.lastrowid)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO postings (entry_id, seq, account_id, amount, currency)"
                     " VALUES (?,1,?,1000,'USDT')", (entry_id, tbank))
    conn.execute("ROLLBACK")


def test_defaults_for_missing_category_and_account():
    base_state()
    post(kind="expense", amount=10_000, currency="AED", from_account="cash_aed",
         category="exp_transport")
    entry = post(kind="expense", amount=4_300, currency="AED")     # ни счёта, ни категории
    slugs = [p["account_slug"] for p in entry["postings"]]
    assert "exp_other" in slugs
    assert "cash_aed" in slugs      # последний использованный счёт этой валюты


def test_balance_correction_and_family_correction():
    base_state()
    entry = post(kind="balance_correction", amount=-235_000, currency="RUB", to_account="tbank")
    assert postings_of(entry) == [("tbank", -235_000, "RUB"), ("eq_correction", 235_000, "RUB")]
    assert balance("tbank", "RUB") == 13_200_000 - 235_000

    debt_before = ledger.family_debt()["debt"]["amount"]
    family = post(kind="balance_correction", amount=-10_000, currency="AED",
                  to_account="mashreq_family")
    assert postings_of(family) == [("mashreq_family", -10_000, "AED"),
                                   ("family_fund", 10_000, "AED")]
    assert ledger.family_debt()["debt"]["amount"] == debt_before
