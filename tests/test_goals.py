# -*- coding: utf-8 -*-
"""Цели-накопления живут за балансом (ARCHITECTURE §5.10)."""
from backend import ledger
from backend.ledger import goals as goals_mod
from tests.conftest import base_state


def test_allocation_offbalance():
    base_state()
    before = ledger.balances()["net_worth"]["amount"]
    goal = goals_mod.create({"name": "Виза", "target": 900_000, "currency": "AED",
                             "due_date": "2026-12-01", "account": "mashreq_personal"})
    goals_mod.goal_allocate(goal["id"], 320_000, "AED", "2026-09-10", "отложил")

    view = ledger.goals_view()["items"][0]
    assert view["saved"] == {"amount": 320_000, "currency": "AED"}
    assert view["progress_bp"] == 3556
    assert len(view["allocations"]) == 1

    assert ledger.balances()["net_worth"]["amount"] == before     # денег не двигали
    assert ledger.check_invariants() == []

    goals_mod.goal_allocate(goal["id"], -120_000, "AED", "2026-09-12", "снял")
    assert ledger.goals_view()["items"][0]["saved"]["amount"] == 200_000
