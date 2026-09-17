# -*- coding: utf-8 -*-
"""Семейный контур: долг, заморозка, FIFO-разморозка, отмены (ТЗ 4.3, 11.2; ARCHITECTURE §4.3)."""
import pytest

from backend import db, ledger
from backend.contracts import LedgerError, OperationPatch
from tests.conftest import balance, base_state, post

RATE = 24_500_000          # 24,50 ₽ за AED — курс из ТЗ


def take(amount=50_000, rate=RATE, **kwargs):
    return post(kind="family_withdrawal", amount=amount, currency="AED",
                from_account="mashreq_family", to_account="mashreq_personal",
                rate_e6=rate, rate_source="voice", **kwargs)


def repay(amount, **kwargs):
    return post(kind="family_repayment", amount=amount, currency="AED",
                from_account="mashreq_personal", to_account="mashreq_family", **kwargs)


def test_withdrawal_keeps_net_worth():
    base_state()
    before = ledger.balances()["net_worth"]["amount"]
    take()
    after = ledger.balances()
    assert after["net_worth"]["amount"] == before          # ТЗ 11.2: итог не изменился
    assert after["family"]["debt"] == {"amount": 50_000, "currency": "AED"}
    assert after["family"]["direction"] == "i_owe"


def test_withdrawal_creates_debt_and_tranche():
    base_state()
    entry = take()
    tranche = entry["tranche"]
    assert tranche["aed_taken"] == {"amount": 50_000, "currency": "AED"}
    assert tranche["rub_frozen"] == {"amount": 1_225_000, "currency": "RUB"}   # 500 × 24,50
    assert tranche["rate_source"] == "voice"
    assert tranche["account_name"] == "Т-Банк"
    assert tranche["label"] == \
        "заблокировано в счёт взятых 17.09.2026 500 AED по курсу 24,50".replace(
            "17.09.2026", tranche["label"].split()[4])
    assert ledger.family_debt()["debt"]["amount"] == 50_000
    assert balance("mashreq_personal", "AED") == 184_250 + 50_000


def test_free_rub_decreases_after_freeze():
    base_state()
    before = ledger.free_rub()
    take()
    after = ledger.free_rub()
    assert after["frozen"]["amount"] == 1_225_000
    assert after["free"]["amount"] == before["free"]["amount"] - 1_225_000
    assert after["rub_total"]["amount"] == before["rub_total"]["amount"]


def test_partial_repayment_fifo():
    base_state()
    take(rate=23_456_789)
    frozen = ledger.tranches()[0]["rub_frozen"]["amount"]
    assert frozen == 1_172_839

    first = repay(33_300)
    assert first["effects"]["released"] == [
        {"tranche_id": 1, "aed": {"amount": 33_300, "currency": "AED"},
         "rub": {"amount": 781_110, "currency": "RUB"}, "op_date": first["op_date"],
         "rate_e6": 23_456_789}]
    open_tranche = ledger.tranches()[0]
    assert open_tranche["aed_left"]["amount"] == 16_700
    assert open_tranche["rub_left"]["amount"] == frozen - 781_110

    second = repay(16_700)
    assert second["effects"]["released"][0]["rub"]["amount"] == frozen - 781_110
    assert ledger.tranches() == []
    assert ledger.family_debt()["debt"]["amount"] == 0


def test_full_repayment_releases_exact_sum():
    base_state()
    take(rate=23_333_333)
    frozen = ledger.tranches()[0]["rub_frozen"]["amount"]
    released = 0
    for part in (10_000, 7_000, 33_000):
        result = repay(part)
        released += sum(r["rub"]["amount"] for r in result["effects"]["released"])
    assert released == frozen                     # копейки не потеряны и не появились
    assert ledger.free_rub()["frozen"]["amount"] == 0


def test_two_tranches_fifo_order():
    base_state()
    first = take(20_000, rate=23_000_000, op_date="2026-09-10")
    second = take(30_000, rate=25_000_000, op_date="2026-09-15")
    assert first["tranche"]["rub_frozen"]["amount"] == 460_000
    assert second["tranche"]["rub_frozen"]["amount"] == 750_000

    result = repay(25_000, op_date="2026-09-16")
    released = result["effects"]["released"]
    assert released[0]["tranche_id"] == first["tranche"]["id"]
    assert released[0]["aed"]["amount"] == 20_000
    assert released[0]["rub"]["amount"] == 460_000
    assert released[1]["tranche_id"] == second["tranche"]["id"]
    assert released[1]["aed"]["amount"] == 5_000
    assert released[1]["rub"]["amount"] == 125_000
    assert [t["aed_left"]["amount"] for t in ledger.tranches()] == [25_000]


def test_void_withdrawal_removes_tranche():
    base_state()
    entry = take()
    ledger.void_entry(entry["id"], reason="ошибся")
    assert ledger.tranches() == []
    assert ledger.free_rub()["frozen"]["amount"] == 0
    assert ledger.family_debt()["debt"]["amount"] == 0
    assert ledger.check_invariants() == []


def test_void_repayment_restores_tranche():
    base_state()
    take()
    repayment = repay(20_000)
    assert ledger.tranches()[0]["rub_left"]["amount"] == 735_000
    ledger.void_entry(repayment["id"])
    tranche = ledger.tranches()[0]
    assert tranche["aed_left"]["amount"] == 50_000
    assert tranche["rub_left"]["amount"] == 1_225_000
    assert ledger.family_debt()["debt"]["amount"] == 50_000
    assert ledger.check_invariants() == []


def test_repaid_more_than_taken_warns():
    base_state()
    take(20_000)
    result = repay(30_000)
    codes = [w["code"] for w in result["warnings"]]
    assert "repaid_more_than_taken" in codes
    detail = next(w for w in result["warnings"] if w["code"] == "repaid_more_than_taken")
    assert detail["details"]["extra"] == {"amount": 10_000, "currency": "AED"}
    assert ledger.family_debt()["debt"]["amount"] == -10_000


def test_freeze_not_covered_warning():
    base_state()
    result = take(600_000)                       # 6 000 AED × 24,50 = 147 000 ₽ при 132 000 ₽
    warning = next(w for w in result["warnings"] if w["code"] == "freeze_not_covered")
    assert warning["details"]["shortfall"] == {"amount": 1_500_000, "currency": "RUB"}
    assert warning["details"]["account"] == "tbank"
    # покрытие считается по счёту привязки: на Т-Банке заморожено больше, чем есть
    tbank = ledger.account_view("tbank")
    assert tbank["balance"]["amount"] - tbank["frozen"]["amount"] < 0
    assert ledger.tranches()[0]["rub_frozen"]["amount"] == 14_700_000   # операция всё равно записана


def test_own_contribution_not_a_repayment():
    base_state()
    take()
    debt_before = ledger.family_debt()["debt"]["amount"]
    post(kind="own_contribution_to_family", amount=50_000, currency="AED",
         from_account="mashreq_personal", to_account="mashreq_family")
    assert ledger.family_debt()["debt"]["amount"] == debt_before
    assert ledger.tranches()[0]["rub_left"]["amount"] == 1_225_000
    assert ledger.check_invariants() == []


def test_paid_for_family_reduces_debt():
    base_state()
    take()
    post(kind="paid_for_family_from_own", amount=20_000, currency="AED",
         from_account="mashreq_personal")
    assert ledger.family_debt()["debt"]["amount"] == 30_000


def test_paid_for_family_releases_tranche():
    base_state()
    take()
    result = post(kind="paid_for_family_from_own", amount=10_000, currency="AED",
                  from_account="mashreq_personal")
    assert result["effects"]["released"][0]["rub"]["amount"] == 245_000
    assert ledger.family_debt()["debt"]["amount"] == 40_000
    assert ledger.free_rub()["frozen"]["amount"] == 980_000
    assert sum(t["aed_left"]["amount"] for t in ledger.tranches()) == 40_000


def test_void_withdrawal_with_releases_rejected():
    base_state()
    entry = take()
    repay(20_000)
    with pytest.raises(LedgerError) as exc:
        ledger.void_entry(entry["id"])
    assert exc.value.code == "tranche_has_releases"
    assert ledger.family_debt()["debt"]["amount"] == 30_000      # долг не ушёл в минус


def test_amend_withdrawal_with_releases_rejected():
    base_state()
    entry = take()
    repay(20_000)
    with pytest.raises(LedgerError) as exc:
        ledger.amend_entry(entry["id"], OperationPatch(amount=40_000))
    assert exc.value.code == "tranche_has_releases"


def test_unvoid_restores_tranche_and_releases():
    base_state()
    take()
    repayment = repay(20_000)
    ledger.void_entry(repayment["id"])
    assert ledger.tranches()[0]["rub_left"]["amount"] == 1_225_000

    ledger.unvoid_entry(repayment["id"])
    tranche = ledger.tranches()[0]
    assert tranche["aed_left"]["amount"] == 30_000
    assert tranche["rub_left"]["amount"] == 735_000
    assert ledger.family_debt()["debt"]["amount"] == 30_000
    assert ledger.check_invariants() == []

    with pytest.raises(LedgerError) as exc:
        ledger.unvoid_entry(repayment["id"])
    assert exc.value.code == "not_voided"


def test_negative_family_debt_direction_and_wording():
    base_state()
    post(kind="paid_for_family_from_own", amount=10_000, currency="AED",
         from_account="mashreq_personal")
    family = ledger.balances()["family"]
    assert family["debt"] == {"amount": -10_000, "currency": "AED"}
    assert family["direction"] == "family_owes"
    assert family["today_repay_rub"] is None
    assert family["frozen_note"] is None
    assert family["frozen_rub"]["amount"] == 0
    debts = ledger.debts()
    assert debts["family"]["tranches"] == []
    assert debts["family"]["today_repay_rub"] is None


def test_frozen_per_account_sums_to_global():
    base_state()
    take(20_000)                                    # заморозка на Т-Банке (умолчание)
    take(10_000, freeze_account="sber")
    orphan = take(5_000)
    conn = db.get_conn()
    conn.execute("UPDATE family_tranches SET account_id = NULL WHERE entry_id = ?",
                 (orphan["id"],))

    home = ledger.balances()
    per_account = {}
    for group in home["groups"]:
        for account in group["accounts"]:
            if account["frozen"]:
                per_account[account["slug"]] = account["frozen"]["amount"]
    assert per_account["sber"] == 245_000
    assert per_account["tbank"] == 20_000 * RATE // 1_000_000 + 5_000 * RATE // 1_000_000
    assert sum(per_account.values()) == home["frozen_rub"]["amount"]

    free_sum = 0
    for group in home["groups"]:
        for account in group["accounts"]:
            if account["currency"] == "RUB" and account["type"] == "asset_personal":
                frozen = account["frozen"]["amount"] if account["frozen"] else 0
                free_sum += account["balance"]["amount"] - frozen
    assert free_sum == home["free_rub"]["amount"]
