# -*- coding: utf-8 -*-
"""Копилка 10 % (01.10): начисление с каждого поступления и покрытие переводами в копилку."""
from __future__ import annotations

from tests.conftest import base_state, post

from backend import db
from backend.ledger import kopilka
from backend.tz import utc_now


def _make_kopilka() -> None:
    conn = db.get_conn()
    conn.execute(
        "INSERT INTO accounts (slug, name, type, currency, is_money, needs_counterparty, icon, sort,"
        " archived, created_at) VALUES ('kopilka_mashrek', 'Копилка Машрек', 'asset_personal', 'AED',"
        " 1, 0, 'bank', 50, 0, ?)", (utc_now(),))


def _setup() -> None:
    base_state()
    _make_kopilka()
    # Обмен 01.10 через Bybit двумя переводами: 137 800 ₽ → 5 853 AED (23,54 ₽ за дирхам).
    post(kind="exchange", amount=10_000_000, currency="RUB", amount_to=425_500, currency_to="AED",
         from_account="tbank", to_account="mashreq_personal", op_date="2026-10-01")
    post(kind="exchange", amount=3_780_000, currency="RUB", amount_to=159_800, currency_to="AED",
         from_account="tbank", to_account="mashreq_personal", op_date="2026-10-01")


def _view():
    return kopilka.view(db.get_conn())


def test_rate_is_whole_last_exchange_day():
    _setup()
    rate = kopilka.exchange_rate(db.get_conn())
    assert rate["source"] == "exchange"
    assert rate["op_date"] == "2026-10-01"
    assert rate["rub_per_aed_e6"] == 23_543_482          # 137 800 / 5 853


def test_income_accrues_ten_percent_in_aed():
    _setup()
    post(kind="income", amount=500_000, currency="RUB", to_account="tbank",
         income_source="inc_other", op_date="2026-10-01", no_tax=True)
    v = _view()
    assert v["count"] == 1
    item = v["items"][0]
    assert item["accrued"] == {"amount": 50_000, "currency": "RUB"}
    assert item["accrued_aed"]["amount"] == 2_124        # 500 ₽ / 23,543482 = 21,24 AED
    assert v["due"]["amount"] == 2_124
    assert item["status"] == "open"


def test_income_before_start_is_not_counted():
    _setup()
    post(kind="income", amount=3_000_000, currency="RUB", to_account="tbank",
         income_source="inc_other", op_date="2026-09-15", no_tax=True)
    assert _view()["count"] == 0
    assert _view()["due"]["amount"] == 0


def test_transfer_into_kopilka_covers_oldest_first():
    _setup()
    post(kind="income", amount=100_000, currency="AED", to_account="mashreq_personal",
         income_source="inc_uae_job", op_date="2026-09-23")
    post(kind="income", amount=1_000_000, currency="RUB", to_account="tbank",
         income_source="inc_other", op_date="2026-09-30", no_tax=True)
    post(kind="transfer", amount=12_000, currency="AED", from_account="mashreq_personal",
         to_account="kopilka_mashrek", op_date="2026-09-24")
    v = _view()
    old, new = v["items"][1], v["items"][0]              # свежие сверху
    assert old["status"] == "covered" and old["covered"]["amount"] == 10_000
    assert new["status"] == "partial" and new["covered"]["amount"] == 2_000
    assert v["transferred"]["amount"] == 12_000
    assert v["due"]["amount"] == v["accrued"]["amount"] - 12_000
    assert v["due_rub"]["amount"] == round(v["due"]["amount"] * 23.543482)


def test_family_withdrawal_into_kopilka_also_covers_and_surplus_shown():
    _setup()
    post(kind="income", amount=100_000, currency="AED", to_account="mashreq_personal",
         income_source="inc_uae_job", op_date="2026-09-23")
    post(kind="family_withdrawal", amount=15_000, currency="AED", from_account="mashreq_family",
         to_account="kopilka_mashrek", op_date="2026-09-23", freeze=False)
    v = _view()
    assert v["due"]["amount"] == 0
    assert v["surplus"]["amount"] == 5_000


def test_voided_income_drops_accrual(ledger):
    _setup()
    r = post(kind="income", amount=100_000, currency="AED", to_account="mashreq_personal",
             income_source="inc_uae_job", op_date="2026-09-25")
    assert _view()["due"]["amount"] == 10_000
    ledger.void_entry(r["id"], actor="test")
    assert _view()["due"]["amount"] == 0


def test_income_with_npd_tax_accrues_from_gross():
    _setup()
    post(kind="income", amount=1_000_000, currency="RUB", to_account="tbank",
         income_source="inc_projects", op_date="2026-10-01")
    item = _view()["items"][0]
    assert item["amount"]["amount"] == 1_000_000
    assert item["accrued"]["amount"] == 100_000


def test_correction_on_kopilka_does_not_cover():
    _setup()
    post(kind="income", amount=100_000, currency="AED", to_account="mashreq_personal",
         income_source="inc_uae_job", op_date="2026-09-25")
    post(kind="balance_correction", amount=50_000, currency="AED", to_account="kopilka_mashrek",
         op_date="2026-09-26")
    assert _view()["due"]["amount"] == 10_000


def test_post_operation_result_has_kopilka_line():
    _setup()
    r = post(kind="income", amount=300_000, currency="AED", to_account="mashreq_personal",
             income_source="inc_uae_job", op_date="2026-10-01")
    assert r["kopilka"]["accrued"] == {"amount": 30_000, "currency": "AED"}
    assert r["kopilka"]["due"]["amount"] == 30_000
    from backend.bot.cards import card_for_entry
    text = card_for_entry(r)
    assert "+300 AED в копилку, всего перевести 300 AED" in text.replace("\xa0", " ")


def test_expense_result_has_no_kopilka():
    _setup()
    r = post(kind="expense", amount=1_000, currency="AED", from_account="mashreq_personal",
             category="exp_cafe", op_date="2026-10-01")
    assert "kopilka" not in r


def test_start_case_from_eva_reconciliation():
    """Сверка Евы 01.10: 382 AED отложено, не покрыто 7 700 ₽ ≈ 327 AED (± курс)."""
    _setup()
    post(kind="income", amount=100_000, currency="AED", to_account="mashreq_personal",
         income_source="inc_uae_job", op_date="2026-09-23")
    for amount, day in ((3_000_000, "2026-09-23"), (3_710_000, "2026-09-24"), (1_000_000, "2026-09-30"),
                        (3_000_000, "2026-09-30"), (3_200_000, "2026-09-30"), (500_000, "2026-10-01")):
        post(kind="income", amount=amount, currency="RUB", to_account="tbank",
             income_source="inc_other", op_date=day, no_tax=True)
    for amount, day in ((10_000, "2026-09-23"), (12_500, "2026-09-23"), (15_700, "2026-09-24")):
        post(kind="family_withdrawal", amount=amount, currency="AED", from_account="mashreq_family",
             to_account="kopilka_mashrek", op_date=day, freeze=False)
    v = _view()
    assert v["transferred"]["amount"] == 38_200
    # 7 700 ₽ = 327,06 AED + недобор 2,42 и 0,58 AED по двум первым (курс 23,54 вместо ~24)
    assert 32_700 <= v["due"]["amount"] <= 33_100


def test_home_and_account_expose_kopilka(client):
    _setup()
    post(kind="income", amount=100_000, currency="AED", to_account="mashreq_personal",
         income_source="inc_uae_job", op_date="2026-10-01")
    home = client.get("/api/home").json()
    assert home["kopilka"]["due"]["amount"] == 10_000
    assert "items" not in home["kopilka"]
    acc = client.get("/api/accounts/kopilka_mashrek").json()
    assert acc["kopilka"]["items"][0]["accrued"]["amount"] == 10_000
    assert client.get("/api/accounts/tbank").json()["kopilka"] is None
    assert client.get("/api/kopilka").json()["due"]["amount"] == 10_000


def test_rate_through_usdt_chain():
    """01.10 Bybit: рубли → USDT → дирхамы. Курс копилки — рубли за дирхам по всей цепочке."""
    base_state()
    _make_kopilka()
    post(kind="exchange", amount=10_000_000, currency="RUB", amount_to=115_861, currency_to="USDT",
         from_account="tbank", to_account="bybit", op_date="2026-10-01")
    post(kind="exchange", amount=3_780_000, currency="RUB", amount_to=43_513, currency_to="USDT",
         from_account="tbank", to_account="bybit", op_date="2026-10-01")
    post(kind="exchange", amount=115_861, currency="USDT", amount_to=425_500, currency_to="AED",
         from_account="bybit", to_account="mashreq_personal", op_date="2026-10-01")
    post(kind="exchange", amount=43_513, currency="USDT", amount_to=159_800, currency_to="AED",
         from_account="bybit", to_account="mashreq_personal", op_date="2026-10-01")
    rate = kopilka.exchange_rate(db.get_conn())
    assert rate["source"] == "exchange"
    assert abs(rate["rub_per_aed_e6"] - 23_543_482) < 2_000   # 137 800 / 5 853 ± округление USDT
