# -*- coding: utf-8 -*-
"""Остатки, личный итог, тождество Главной (ARCHITECTURE §4.4, §5.3, §5.4)."""
from backend import db, ledger
from backend.ledger.balances import account_vector
from backend.ledger.common import resolve_account
from tests.conftest import base_state, post


def test_multicurrency_vector():
    base_state()
    post(kind="loan_given", amount=30_000, currency="AED", from_account="mashreq_personal",
         counterparty="Маша")
    post(kind="loan_given", amount=500_000, currency="RUB", from_account="tbank",
         counterparty="Богдан")
    conn = db.get_conn()
    receivable = int(resolve_account(conn, "receivable")["id"])
    assert account_vector(conn, receivable) == {"AED": 30_000, "RUB": 500_000}

    debts = ledger.debts()
    names = {item["name"]: item for item in debts["owed_to_me"]}
    assert names["Маша"]["amounts"] == [{"amount": 30_000, "currency": "AED"}]
    assert names["Богдан"]["amounts"] == [{"amount": 500_000, "currency": "RUB"}]


def test_net_worth_formula():
    base_state()
    post(kind="family_withdrawal", amount=50_000, currency="AED", from_account="mashreq_family",
         to_account="mashreq_personal", rate_e6=24_500_000, rate_source="voice")
    post(kind="income", amount=9_000_000, currency="RUB", to_account="tbank",
         income_source="inc_projects")

    home = ledger.balances()
    personal = 0
    for group in home["groups"]:
        personal += group["total"]["amount"]
    debts = ledger.debts()
    from backend import rates
    from backend.ledger.common import to_view
    snapshot = rates.snapshot(conn=db.get_conn())
    owed = sum(item["in_view"]["amount"] for item in debts["owed_to_me"])
    i_owe = sum(item["in_view"]["amount"] for item in debts["i_owe"])
    tax = to_view(debts["tax"]["amount"]["amount"], "RUB", "RUB", snapshot)
    family = to_view(home["family"]["debt"]["amount"], "AED", "RUB", snapshot)
    # тождество Главной; расхождение допустимо только на копейку округления пересчёта
    assert abs(home["net_worth"]["amount"] - (personal + owed - i_owe - tax - family)) <= 2


def test_as_of_ignores_future_entries():
    base_state()
    post(kind="expense", amount=100_000, currency="RUB", from_account="tbank",
         category="exp_groceries", op_date="2026-09-20")
    early = ledger.balances(as_of="2026-09-19")["net_worth"]["amount"]
    late = ledger.balances(as_of="2026-09-21")["net_worth"]["amount"]
    assert early - late == 100_000


def test_group_total_matches_net_worth_with_credit_debt():
    base_state()
    post(kind="expense", amount=240_000, currency="RUB", from_account="sber_credit",
         category="exp_groceries")
    home = ledger.balances()
    rub_group = next(group for group in home["groups"] if group["key"] == "RUB")
    credit = next(a for a in rub_group["accounts"] if a["slug"] == "sber_credit")
    assert credit["balance"]["amount"] == -240_000
    assert credit["natural"]["amount"] == 240_000
    assert credit["in_view"]["amount"] == -240_000
    assert credit["role"] == "liability"
    # 132 000 + 18 400 + 5 000 − 2 400 = 153 000 ₽
    assert rub_group["total"]["amount"] == 15_300_000

    groups_total = sum(group["total"]["amount"] for group in home["groups"])
    family = home["family"]["debt"]["amount"]
    from backend import rates
    from backend.ledger.common import to_view
    snapshot = rates.snapshot(conn=db.get_conn())
    assert abs(home["net_worth"]["amount"]
               - (groups_total - to_view(family, "AED", "RUB", snapshot))) <= 2


def test_totals_by_view_consistent():
    base_state()
    home = ledger.balances(currency_view="RUB")
    assert set(home["totals_by_view"]["net_worth"]) == {"RUB", "USD", "AED"}
    assert home["totals_by_view"]["net_worth"]["RUB"] == home["net_worth"]
    for key, values in home["totals_by_view"]["groups"].items():
        group = next(g for g in home["groups"] if g["key"] == key)
        assert values["RUB"] == group["total"]

    # тот же итог, запрошенный сразу в дирхамах, считается посчётно и вправе отличаться
    # на один филс от пересчёта рублёвой величины — больше расхождения быть не должно
    in_aed = ledger.balances(currency_view="AED")
    assert in_aed["net_worth"]["currency"] == "AED"
    assert abs(in_aed["net_worth"]["amount"]
               - home["totals_by_view"]["net_worth"]["AED"]["amount"]) <= 1
    assert in_aed["totals_by_view"]["net_worth"]["AED"] == in_aed["net_worth"]
