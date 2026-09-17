# -*- coding: utf-8 -*-
"""Сверка скрина и выписки с учётом (ТЗ 5.2, 11.3; ARCHITECTURE §4.5)."""
import pytest

from backend import ledger
from backend.contracts import LedgerError, OperationPatch, ReconcileDecision, ScreenBatch, ScreenRow
from backend.ledger.reconcile import align
from tests.conftest import balance, base_state, post

TODAY = "2026-09-16"


def screen(rows, *, account="tbank", balance_value=None, currency="RUB"):
    return ScreenBatch(account=account, currency=currency, balance=balance_value,
                       rows=[ScreenRow(**row) for row in rows])


def test_matched_within_two_days():
    base_state()
    post(kind="expense", amount=235_000, currency="RUB", from_account="tbank",
         category="exp_groceries", op_date="2026-09-16")
    result = ledger.reconcile(screen([
        {"amount": -235_000, "currency": "RUB", "op_date": "2026-09-17", "raw_text": "ЯНДЕКС ЕДА"}]))
    assert len(result["matched"]) == 1 and not result["new"]
    assert result["matched"][0]["match_status"] == "matched"


def test_five_rows_three_known_two_new():
    base_state()
    post(kind="expense", amount=235_000, currency="RUB", from_account="tbank",
         category="exp_groceries", op_date=TODAY)
    post(kind="expense", amount=120_000, currency="RUB", from_account="tbank",
         category="exp_transport", op_date=TODAY)
    post(kind="income", amount=1_000_000, currency="RUB", to_account="tbank",
         income_source="inc_parents", op_date=TODAY)
    entries_before = ledger.list_entries.__self__ if False else None

    result = ledger.reconcile(screen([
        {"amount": -235_000, "currency": "RUB", "op_date": TODAY, "raw_text": "ЯНДЕКС ЕДА"},
        {"amount": -120_000, "currency": "RUB", "op_date": TODAY, "raw_text": "ЯНДЕКС GO"},
        {"amount": 1_000_000, "currency": "RUB", "op_date": TODAY, "raw_text": "ПЕРЕВОД ОТ МАМЫ"},
        {"amount": -48_000, "currency": "RUB", "op_date": TODAY, "raw_text": "ПЯТЁРОЧКА"},
        {"amount": -19_900, "currency": "RUB", "op_date": TODAY, "raw_text": "ЯНДЕКС ПЛЮС"},
    ]))
    assert len(result["matched"]) == 3
    assert len(result["new"]) == 2
    assert not result["ambiguous"]

    decisions = [ReconcileDecision(inbox_id=item["id"], decision="new") for item in result["new"]]
    applied = ledger.apply_reconcile(decisions, actor="test")
    assert len([a for a in applied["applied"] if a["status"] == "accepted"]) == 2
    assert balance("tbank", "RUB") == 13_200_000 - 235_000 - 120_000 + 1_000_000 - 48_000 - 19_900
    assert ledger.check_invariants() == []


def test_ambiguous_two_candidates():
    base_state()
    for _ in range(2):
        post(kind="expense", amount=150_000, currency="RUB", from_account="tbank",
             category="exp_cafe", op_date=TODAY)
    result = ledger.reconcile(screen([
        {"amount": -150_000, "currency": "RUB", "op_date": TODAY, "raw_text": "КОФЕ"}]))
    assert len(result["ambiguous"]) == 1
    assert len(result["ambiguous"][0]["candidates"]) == 2


def test_two_identical_rows_one_known_one_entered():
    base_state()
    post(kind="expense", amount=1_500, currency="AED", from_account="mashreq_personal",
         category="exp_cafe", op_date=TODAY)
    result = ledger.reconcile(screen([
        {"amount": -1_500, "currency": "AED", "op_date": TODAY, "raw_text": "COFFEE"},
        {"amount": -1_500, "currency": "AED", "op_date": TODAY, "raw_text": "COFFEE"},
    ], account="mashreq_personal", currency="AED"))
    assert len(result["matched"]) == 1
    assert len(result["new"]) == 1

    ledger.apply_reconcile([ReconcileDecision(inbox_id=result["new"][0]["id"], decision="new")],
                           actor="test")
    assert balance("mashreq_personal", "AED") == 184_250 - 1_500 - 1_500


def test_near_amount_goes_ambiguous():
    base_state()
    post(kind="expense", amount=3_400, currency="AED", from_account="mashreq_personal",
         category="exp_cafe", op_date=TODAY)
    result = ledger.reconcile(screen([
        {"amount": -4_300, "currency": "AED", "op_date": TODAY, "raw_text": "CAFE"}],
        account="mashreq_personal", currency="AED"))
    assert len(result["ambiguous"]) == 1
    assert result["ambiguous"][0]["candidates"][0]["score"] == 60
    assert not result["new"] and not result["matched"]


def test_balance_diff_and_align():
    base_state()
    batch = ledger.reconcile(screen([
        {"amount": -235_000, "currency": "RUB", "op_date": TODAY, "raw_text": "ЯНДЕКС ЕДА"}],
        balance_value=12_965_000))
    assert batch["balance_check"]["diff"] == {"amount": -235_000, "currency": "RUB"}

    ledger.apply_reconcile([ReconcileDecision(inbox_id=batch["new"][0]["id"], decision="new")],
                           actor="test")
    aligned = align(batch["batch_id"], actor="test")
    assert [w["code"] for w in aligned["warnings"]] == ["already_aligned"]
    assert aligned["entry_id"] is None


def test_align_after_new_entries_is_noop():
    base_state()
    batch = ledger.reconcile(screen([
        {"amount": -50_000, "currency": "RUB", "op_date": TODAY, "raw_text": "АПТЕКА"}],
        balance_value=13_150_000))
    with pytest.raises(LedgerError) as exc:
        align(batch["batch_id"], actor="test")
    assert exc.value.code == "batch_has_pending"

    ledger.apply_reconcile([ReconcileDecision(inbox_id=batch["new"][0]["id"], decision="new")],
                           actor="test")
    result = align(batch["batch_id"], actor="test")
    assert result["entry_id"] is None
    assert [w["code"] for w in result["warnings"]] == ["already_aligned"]
    assert balance("tbank", "RUB") == 13_150_000


def test_align_creates_correction_when_diff_remains():
    base_state()
    batch = ledger.reconcile(screen([], balance_value=12_965_000))
    result = align(batch["batch_id"], actor="test")
    assert result["entry_id"] is not None
    assert balance("tbank", "RUB") == 12_965_000
    entry = ledger.get_entry(result["entry_id"])
    assert entry["kind"] == "balance_correction"
    assert entry["amount"]["amount"] == -235_000


def test_same_screenshot_twice_is_idempotent():
    base_state()
    rows = [{"amount": -48_000, "currency": "RUB", "op_date": TODAY, "raw_text": "ПЯТЁРОЧКА"}]
    first = ledger.reconcile(screen(rows))
    ledger.apply_reconcile([ReconcileDecision(inbox_id=first["new"][0]["id"], decision="new")],
                           actor="test")
    after_first = balance("tbank", "RUB")

    second = ledger.reconcile(screen(rows))
    assert len(second["matched"]) == 1 and not second["new"]
    assert balance("tbank", "RUB") == after_first


def test_amended_entry_matches_screen_row():
    base_state()
    rows = [{"amount": -48_000, "currency": "RUB", "op_date": TODAY, "raw_text": "ПЯТЁРОЧКА"}]
    first = ledger.reconcile(screen(rows))
    applied = ledger.apply_reconcile(
        [ReconcileDecision(inbox_id=first["new"][0]["id"], decision="new")], actor="test")
    entry_id = applied["applied"][0]["entry_id"]
    ledger.amend_entry(entry_id, OperationPatch(category="exp_groceries"))

    second = ledger.reconcile(screen(rows))
    assert len(second["matched"]) == 1 and not second["new"]


def test_align_family_account_keeps_debt():
    base_state()
    post(kind="family_withdrawal", amount=50_000, currency="AED", from_account="mashreq_family",
         to_account="mashreq_personal", rate_e6=24_500_000, rate_source="voice")
    debt_before = ledger.family_debt()["debt"]["amount"]

    batch = ledger.reconcile(screen([], account="mashreq_family", currency="AED",
                                    balance_value=790_000))
    result = align(batch["batch_id"], actor="test")
    assert result["entry_id"] is not None
    assert balance("mashreq_family", "AED") == 790_000
    assert ledger.family_debt()["debt"]["amount"] == debt_before
    assert ledger.check_invariants() == []
