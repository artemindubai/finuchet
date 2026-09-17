# -*- coding: utf-8 -*-
"""Правка = новая версия операции (ARCHITECTURE §4.1, §5.5)."""
import pytest

from backend import ledger
from backend.contracts import LedgerError, OperationPatch
from tests.conftest import balance, base_state, post


def test_amend_creates_version_and_voids_old():
    base_state()
    entry = post(kind="expense", amount=4_300, currency="AED", from_account="mashreq_personal",
                 category="exp_cafe", description="обед")
    amended = ledger.amend_entry(entry["id"], OperationPatch(amount=3_400,
                                                             from_account="cash_aed"))
    assert amended["id"] != entry["id"]
    assert amended["version"] == 2
    assert amended["replaces_entry_id"] == entry["id"]
    assert amended["amount"]["amount"] == 3_400

    old = ledger.get_entry(entry["id"])
    assert old["status"] == "void"
    assert old["replaced_by_entry_id"] == amended["id"]

    changed = amended["versions"][-1]["changed"]
    assert any("сумма" in line for line in changed)
    assert any("Наличные AED" in line for line in changed)

    assert balance("mashreq_personal", "AED") == 184_250       # старая проводка не в остатках
    assert balance("cash_aed", "AED") == 32_000 - 3_400
    assert ledger.check_invariants() == []


def test_amend_backdated_recalculates_period():
    base_state()
    entry = post(kind="expense", amount=10_000, currency="AED", from_account="mashreq_personal",
                 category="exp_cafe", op_date="2026-09-17")
    september = ledger.analytics_month("2026-09")["expense_total"]["amount"]
    assert september > 0

    ledger.amend_entry(entry["id"], OperationPatch(op_date="2026-08-20"))
    assert ledger.analytics_month("2026-09")["expense_total"]["amount"] == september - 234_500
    assert ledger.analytics_month("2026-08")["expense_total"]["amount"] == 234_500


def test_amend_of_old_version_rejected():
    base_state()
    entry = post(kind="expense", amount=4_300, currency="AED", from_account="mashreq_personal",
                 category="exp_cafe")
    ledger.amend_entry(entry["id"], OperationPatch(amount=3_400))
    with pytest.raises(LedgerError) as exc:
        ledger.amend_entry(entry["id"], OperationPatch(amount=1_000))
    assert exc.value.code == "entry_is_old_version"


def test_amend_keeps_counterparty_and_external_ref():
    base_state()
    entry = post(kind="loan_given", amount=30_000, currency="AED",
                 from_account="mashreq_personal", counterparty="Маша")
    amended = ledger.amend_entry(entry["id"], OperationPatch(amount=25_000))
    assert amended["counterparty"] == "Маша"
    assert ledger.debts()["owed_to_me"][0]["amounts"] == [{"amount": 25_000, "currency": "AED"}]
