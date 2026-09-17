# -*- coding: utf-8 -*-
"""Отмена и возврат операции (ARCHITECTURE §4.1, §5.5)."""
import pytest

from backend import ledger
from backend.contracts import EntryFilters, LedgerError
from tests.conftest import balance, base_state, post


def test_void_excluded_from_balances():
    base_state()
    entry = post(kind="expense", amount=4_300, currency="AED", from_account="mashreq_personal",
                 category="exp_cafe")
    assert balance("mashreq_personal", "AED") == 179_950

    voided = ledger.void_entry(entry["id"], reason="ошибся")
    assert voided["status"] == "void"
    assert balance("mashreq_personal", "AED") == 184_250

    feed = ledger.list_entries(EntryFilters(status="posted"))
    assert entry["id"] not in [item["id"] for item in feed["items"]]
    journal = ledger.list_entries(EntryFilters(status="all"))
    assert entry["id"] in [item["id"] for item in journal["items"]]
    assert len(ledger.get_entry(entry["id"])["postings"]) == 2

    with pytest.raises(LedgerError) as exc:
        ledger.void_entry(entry["id"])
    assert exc.value.code == "already_void"


def test_unvoid_returns_entry_to_balances():
    base_state()
    entry = post(kind="expense", amount=4_300, currency="AED", from_account="mashreq_personal",
                 category="exp_cafe")
    ledger.void_entry(entry["id"])
    restored = ledger.unvoid_entry(entry["id"])
    assert restored["status"] == "posted"
    assert balance("mashreq_personal", "AED") == 179_950

    with pytest.raises(LedgerError) as exc:
        ledger.unvoid_entry(entry["id"])
    assert exc.value.code == "not_voided"
