# -*- coding: utf-8 -*-
"""Задание 51 (29.09): свободные рубли за вычетом кредитки, сверка семейной налички с фактом."""
from backend import db, settings_store
from backend.ledger.checks import check_view, enter_fact
from backend.ledger.common import resolve_account
from tests.conftest import balance, opening, post

RATE = 24_500_000


def spend_on_credit(amount):
    return post(kind="expense", amount=amount, currency="RUB", from_account="sber_credit",
                category="exp_cafe", description="кафе с кредитки")


def test_free_rub_minus_credit_debt(ledger):
    opening(("tbank", 1_200_000, "RUB"))
    spend_on_credit(1_351_800)
    free = ledger.free_rub()
    assert free["credit"]["amount"] == 1_351_800
    assert free["free"]["amount"] == 1_200_000 - 1_351_800           # в минус, как на проде 29.09
    assert free["shortfall"] is None                                   # кредитка — не нехватка под семью
    home = ledger.balances()
    assert home["free_rub"]["amount"] == -151_800
    assert home["my_money"]["amount"] == -151_800                      # «Мои деньги» кредитку тоже вычитают


def test_free_rub_with_freeze_and_credit(ledger):
    opening(("tbank", 10_000_000, "RUB"), ("mashreq_family", 100_000, "AED"))
    post(kind="family_withdrawal", amount=10_000, currency="AED", from_account="mashreq_family",
         to_account="mashreq_personal", rate_e6=RATE, rate_source="voice")
    spend_on_credit(500_000)
    free = ledger.free_rub()
    assert free["free"]["amount"] == 10_000_000 - 245_000 - 500_000


def _setup_cash_check():
    opening(("cash_aed_family", 3_600_000, "AED"))
    post(kind="family_withdrawal", amount=30_000, currency="AED", from_account="cash_aed_family",
         to_account="cash_aed", rate_e6=RATE, rate_source="voice")
    conn = db.get_conn()
    first = conn.execute("SELECT MIN(id) AS id FROM entries").fetchone()["id"]
    settings_store.set("account_checks", {"cash_aed_family": {
        "base_amount": 930_000, "base_note": "по словам Артёма 25.09", "base_entry_ids": [first]}},
        conn=conn)
    return conn


def test_check_view_lists_movements_after_base():
    conn = _setup_cash_check()
    view = check_view(conn, resolve_account(conn, "cash_aed_family"))
    assert view["base"]["amount"] == 930_000
    assert [i["amount"]["amount"] for i in view["items"]] == [-30_000]
    assert view["expected"]["amount"] == 900_000
    assert view["ledger"]["amount"] == 3_570_000
    assert view["mismatch"]["amount"] == 2_670_000       # тест без квартиры и взноса — учёт не совпал
    assert view["fact"] is None


def test_enter_fact_aligns_balance():
    conn = _setup_cash_check()
    out = enter_fact("cash_aed_family", 890_000)
    assert balance("cash_aed_family", "AED") == 890_000
    fact = out["check"]["fact"]
    assert fact["amount"]["amount"] == 890_000
    assert fact["ledger_before"]["amount"] == 3_570_000
    assert fact["diff"]["amount"] == 890_000 - 3_570_000
    assert out["entry_id"]
    row = conn.execute("SELECT kind, description FROM entries WHERE id = ?", (out["entry_id"],)).fetchone()
    assert row["kind"] == "balance_correction"
    assert "Сверка" in row["description"]


def test_enter_fact_equal_makes_no_entry():
    _setup_cash_check()
    out = enter_fact("cash_aed_family", 3_570_000)
    assert out["entry_id"] is None
    assert out["check"]["fact"]["diff"]["amount"] == 0


def test_check_fact_api(client):
    _setup_cash_check()
    acc = client.get("/api/accounts/cash_aed_family").json()
    assert acc["check"]["base"]["amount"] == 930_000
    r = client.post("/api/accounts/cash_aed_family/check_fact", json={"amount": 900_000})
    assert r.status_code == 200, r.text
    assert r.json()["check"]["fact"]["amount"]["amount"] == 900_000
    assert client.get("/api/accounts/tbank").json()["check"] is None
    assert client.post("/api/accounts/tbank/check_fact", json={"amount": 1}).status_code == 400
