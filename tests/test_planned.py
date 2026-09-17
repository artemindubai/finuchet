# -*- coding: utf-8 -*-
"""Календарь платежей (ARCHITECTURE §5.9)."""
from backend import ledger
from backend.ledger import planned as planned_mod
from tests.conftest import balance, base_state


def test_mark_paid_creates_entry_and_moves_date():
    base_state()
    plan = planned_mod.create({"title": "Аренда квартиры", "amount": 350_000, "currency": "AED",
                               "repeat": "monthly", "next_date": "2026-10-01", "day_of_month": 1,
                               "account": "mashreq_personal", "category": "exp_housing",
                               "remind_days_before": 2})
    assert plan["title"] == "Аренда квартиры"
    assert plan["overdue"] is False

    result = ledger.mark_planned_paid(plan["id"], op_date="2026-10-01")
    assert result["kind"] == "expense"
    assert result["amount"] == {"amount": 350_000, "currency": "AED"}
    assert balance("mashreq_personal", "AED") == 184_250 - 350_000
    assert result["planned"]["next_date"] == "2026-11-01"
    assert result["planned"]["last_paid"]["entry_id"] == result["id"]
    assert ledger.check_invariants() == []


def test_once_payment_closes_after_paid():
    base_state()
    plan = planned_mod.create({"title": "Виза", "amount": 90_000, "currency": "AED",
                               "repeat": "once", "next_date": "2026-09-20",
                               "account": "mashreq_personal", "category": "exp_visa"})
    ledger.mark_planned_paid(plan["id"], op_date="2026-09-20")
    assert ledger.calendar(date_from="2026-01-01", date_to="2027-01-01")["items"] == []


def test_due_date_of_loan_creates_reminder():
    base_state()
    from tests.conftest import post
    post(kind="loan_given", amount=30_000, currency="AED", from_account="mashreq_personal",
         counterparty="Маша", due_date="2026-09-30")
    items = ledger.calendar(date_from="2026-09-01", date_to="2026-10-31")["items"]
    assert len(items) == 1
    assert items[0]["title"] == "Дал в долг · Маша"
    assert items[0]["remind_days_before"] == 1
    assert ledger.debts()["owed_to_me"][0]["due_date"] == "2026-09-30"
