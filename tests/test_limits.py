# -*- coding: utf-8 -*-
"""Лимиты по категориям (ARCHITECTURE §5.10)."""
from backend import ledger
from backend.tz import today_dubai
from tests.conftest import base_state, post

MONTH = today_dubai()[:7]


def test_limit_usage_bp():
    base_state()
    ledger.set_limit("exp_cafe", 1_500_000, "RUB")
    post(kind="expense", amount=1_180_000, currency="RUB", from_account="tbank",
         category="exp_cafe")

    view = ledger.limits_view(MONTH)["items"]
    assert len(view) == 1
    item = view[0]
    assert item["limit"] == {"amount": 1_500_000, "currency": "RUB"}
    assert item["spent"] == {"amount": 1_180_000, "currency": "RUB"}
    assert item["used_bp"] == 7867

    category = next(c for c in ledger.analytics_month(MONTH)["categories"]
                    if c["category_id"] == item["category_id"])
    assert category["limit_used_bp"] == 7867

    ledger.delete_limit("exp_cafe")
    assert ledger.limits_view(MONTH)["items"] == []
