# -*- coding: utf-8 -*-
"""Адверсариальные сценарии семейного контура: долг, заморозка, FIFO, отмены.

Цель — сломать арифметику долга и заморозки многошаговыми последовательностями,
которых нет в основных тестах (ARCHITECTURE §4.3, §4.4; ТЗ 4.3, 11.2)."""
import pytest

from backend import db, ledger
from backend.contracts import LedgerError, OperationPatch
from tests.conftest import balance, base_state, post

RATE = 24_500_000          # 24,50 ₽ за AED


def take(amount=50_000, rate=RATE, **kwargs):
    return post(kind="family_withdrawal", amount=amount, currency="AED",
                from_account="mashreq_family", to_account="mashreq_personal",
                rate_e6=rate, rate_source="voice", **kwargs)


def repay(amount, **kwargs):
    return post(kind="family_repayment", amount=amount, currency="AED",
                from_account="mashreq_personal", to_account="mashreq_family", **kwargs)


def paid_for_family(amount, **kwargs):
    return post(kind="paid_for_family_from_own", amount=amount, currency="AED",
                from_account="mashreq_personal", **kwargs)


def frozen_total() -> int:
    from backend.ledger.tranches import frozen_total as total
    return total(db.get_conn())


# ---------------------------------------------------------------------------------------
# 1. многошаговый семейный сценарий


def test_full_family_cycle_returns_to_zero():
    """Взял 500, вернул 200, заплатил за семью 100, вернул 300 → долг −100, заморозка 0."""
    base_state()
    free_before = ledger.free_rub()["free"]["amount"]
    net_before = ledger.balances()["net_worth"]["amount"]

    take(50_000)                       # 500 AED, заморожено 12 250 ₽
    assert frozen_total() == 1_225_000
    repay(20_000)                      # −200 AED → разморожено 4 900 ₽
    paid_for_family(10_000)            # −100 AED долга → разморожено 2 450 ₽
    last = repay(30_000)               # −300 AED, а в траншах осталось 200

    assert frozen_total() == 0, "после полного возврата заморозка обязана обнулиться"
    assert ledger.free_rub()["free"]["amount"] == free_before
    assert ledger.balances()["net_worth"]["amount"] == net_before

    debt = ledger.family_debt()
    assert debt["debt"] == {"amount": -10_000, "currency": "AED"}, "семья должна Артёму 100 AED"
    assert debt["direction"] == "family_owes"
    codes = [w["code"] for w in last["warnings"]]
    assert "repaid_more_than_taken" in codes
    assert ledger.check_invariants() == []


def test_void_paid_for_family_does_not_resurrect_frozen_rubles():
    """Отмена «заплатил за семью» после полного погашения не должна воскрешать заморозку.

    Взял 500 → вернул 200 → заплатил за семью 100 → вернул 300 (транш исчерпан на 200).
    Отменяем «заплатил за семью»: долг возвращается к 0 (500 взято, 500 возвращено),
    но транш получает назад 100 AED / 2 450 ₽, которые больше нечем погасить."""
    base_state()
    base_free = ledger.free_rub()["free"]["amount"]
    take(50_000)
    repay(20_000)
    paid = paid_for_family(10_000)
    repay(30_000)
    assert frozen_total() == 0

    ledger.void_entry(paid["id"], actor="test")

    debt = ledger.family_debt()["debt"]["amount"]
    assert debt == 0, "взял 500, вернул 200+300 → долг 0"
    assert frozen_total() == 0, (
        f"долг {debt} AED, а заморожено {frozen_total()} копеек рублей — экран покажет "
        "«долг семье 0» и «заморожено 2 450 ₽» одновременно")
    assert ledger.free_rub()["free"]["amount"] == base_free
    assert ledger.check_invariants() == []


# ---------------------------------------------------------------------------------------
# 2. вернул больше, чем брал


def test_repaid_more_than_taken_screen_is_consistent():
    base_state()
    net_before = ledger.balances()["net_worth"]["amount"]
    take(50_000)
    result = repay(80_000)

    codes = [w["code"] for w in result["warnings"]]
    assert "repaid_more_than_taken" in codes

    home = ledger.balances()
    assert home["family"]["debt"] == {"amount": -30_000, "currency": "AED"}
    assert home["family"]["direction"] == "family_owes"
    assert home["family"]["frozen_rub"]["amount"] == 0
    assert home["family"]["today_repay_rub"] is None
    assert home["family"]["frozen_note"] is None
    assert home["frozen_rub"]["amount"] == 0
    assert home["net_worth"]["amount"] == net_before, "переплата семье не создаёт дохода/расхода"

    screen = ledger.debts()
    assert screen["family"]["debt"]["amount"] == -30_000
    assert screen["family"]["tranches"] == []
    assert ledger.check_invariants() == []


def test_paid_for_family_without_debt_goes_negative_cleanly():
    """Заплатил за семью со своих при нулевом долге: семья должна Артёму, заморозки нет."""
    base_state()
    result = paid_for_family(15_000)
    debt = ledger.family_debt()
    assert debt["debt"]["amount"] == -15_000
    assert debt["direction"] == "family_owes"
    assert frozen_total() == 0
    # разморозить нечего — но код предупреждения про «вернул больше, чем брал» тут неуместен
    codes = [w["code"] for w in result["warnings"]]
    assert "repaid_more_than_taken" not in codes, (
        "«заплатил за семью» — не возврат; текст предупреждения врёт про возврат")
    assert ledger.check_invariants() == []


# ---------------------------------------------------------------------------------------
# 3. amend / void / unvoid вокруг траншей


def test_amend_withdrawal_with_live_release_rejected_and_state_intact():
    base_state()
    taken = take(50_000)
    repay(20_000)
    with pytest.raises(LedgerError) as exc:
        ledger.amend_entry(taken["id"], OperationPatch(amount=40_000), actor="test")
    assert exc.value.code == "tranche_has_releases"
    # состояние не поехало после отказа
    assert frozen_total() == 735_000
    assert ledger.family_debt()["debt"]["amount"] == 30_000
    assert ledger.check_invariants() == []


def test_unvoid_after_void_restores_tranche_exactly():
    base_state()
    taken = take(50_000)
    before = frozen_total()
    ledger.void_entry(taken["id"], actor="test")
    assert frozen_total() == 0
    assert ledger.family_debt()["debt"]["amount"] == 0
    ledger.unvoid_entry(taken["id"], actor="test")
    assert frozen_total() == before
    assert ledger.family_debt()["debt"]["amount"] == 50_000
    assert ledger.check_invariants() == []


def test_void_opening_balance_zeroes_account():
    base_state()
    conn = db.get_conn()
    row = conn.execute(
        "SELECT e.id AS id FROM entries e JOIN postings p ON p.entry_id = e.id"
        " JOIN accounts a ON a.id = p.account_id"
        " WHERE e.kind = 'opening_balance' AND a.slug = 'tbank'").fetchone()
    ledger.void_entry(int(row["id"]), actor="test")
    assert balance("tbank", "RUB") == 0
    assert ledger.check_invariants() == []


def test_amend_changes_kind_expense_to_income():
    """«Это не расход, а доход» — правка со сменой вида не должна ломать остатки."""
    base_state()
    start = balance("mashreq_personal", "AED")
    entry = post(kind="expense", amount=4_300, currency="AED",
                 from_account="mashreq_personal", category="exp_cafe")
    assert balance("mashreq_personal", "AED") == start - 4_300

    ledger.amend_entry(entry["id"], OperationPatch(kind="income", income_source="inc_uae_job",
                                                  to_account="mashreq_personal"), actor="test")
    assert balance("mashreq_personal", "AED") == start + 4_300
    from backend.tz import today_dubai
    month = ledger.analytics_month(today_dubai()[:7])
    names = [c["name"] for c in month["categories"]]
    assert "Кафе и рестораны" not in names, "старая версия расхода не должна остаться в аналитике"
    assert ledger.check_invariants() == []


def test_unfrozen_withdrawal_does_not_disable_freeze_invariant():
    """Одно взятие «без заморозки» не должно глушить проверку «заморозка == долг» навсегда.

    check_invariants() отключает эту проверку целиком, если есть хоть одно взятие без транша,
    — после такой операции сломанная заморозка перестаёт ловиться."""
    base_state()
    take(50_000)
    repay(20_000)
    paid = paid_for_family(10_000)
    repay(30_000)
    ledger.void_entry(paid["id"], actor="test")
    broken = ledger.check_invariants()
    assert broken, "проверка обязана видеть расхождение заморозки и долга"

    post(kind="family_withdrawal", amount=1_000, currency="AED",
         from_account="mashreq_family", to_account="mashreq_personal", freeze=False)
    assert ledger.check_invariants(), (
        "после взятия без заморозки то же расхождение перестало обнаруживаться")


def test_amend_withdrawal_freeze_off_releases_tranche():
    """«Не надо было замораживать» — правка снимает транш, долг остаётся."""
    base_state()
    taken = take(50_000)
    assert frozen_total() == 1_225_000
    ledger.amend_entry(taken["id"], OperationPatch(freeze=False), actor="test")
    assert frozen_total() == 0
    assert ledger.family_debt()["debt"]["amount"] == 50_000
    problems = ledger.check_invariants()
    assert problems == [], problems
