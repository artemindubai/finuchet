# -*- coding: utf-8 -*-
"""Дыры, названные критиком в разделе «Что осталось непокрытым», и края новых правок.

Файл фиксера: тесты критика (`test_adversarial_*.py`) здесь не дублируются и не ослабляются."""
import pytest

from backend import db, ledger
from backend.contracts import LedgerError, OperationPatch, ParsedOperation, ScreenBatch, ScreenRow
from tests.conftest import balance, base_state, post

RATE = 24_500_000


def take(amount=50_000, rate=RATE, **kwargs):
    return post(kind="family_withdrawal", amount=amount, currency="AED",
                from_account="mashreq_family", to_account="mashreq_personal",
                rate_e6=rate, rate_source="voice", **kwargs)


def repay(amount, **kwargs):
    return post(kind="family_repayment", amount=amount, currency="AED",
                from_account="mashreq_personal", to_account="mashreq_family", **kwargs)


def frozen_on(slug: str) -> int:
    account = ledger.account_view(slug)
    return account["frozen"]["amount"] if account["frozen"] else 0


# ---------------------------------------------------------------------------------------
# заморозка на втором рублёвом счёте


def test_freeze_on_sber_releases_from_sber():
    """Заморозка привязана к Сберу: возврат размораживает там же, Т-Банк не задет."""
    base_state()
    take(20_000, freeze_account="sber")
    assert frozen_on("sber") == 490_000
    assert frozen_on("tbank") == 0

    repay(20_000)
    assert frozen_on("sber") == 0
    assert ledger.free_rub()["frozen"]["amount"] == 0
    assert ledger.check_invariants() == []


def test_two_freeze_accounts_release_fifo_across_accounts():
    """Два транша на разных счетах: FIFO гасит сначала ранний, независимо от счёта заморозки."""
    base_state()
    take(20_000, op_date="2026-09-10", freeze_account="sber")
    take(20_000, op_date="2026-09-15", freeze_account="tbank")
    assert frozen_on("sber") == 490_000 and frozen_on("tbank") == 490_000

    repay(30_000, op_date="2026-09-16")
    assert frozen_on("sber") == 0, "ранний транш на Сбере обязан гаситься первым"
    assert frozen_on("tbank") == 245_000
    assert ledger.check_invariants() == []


def test_amend_freeze_account_with_live_release_rejected():
    """«Заморозь на Сбере» по взятию, которое уже частично вернули, — отказ, состояние цело."""
    base_state()
    taken = take(20_000, freeze_account="sber")
    repay(5_000)
    assert frozen_on("sber") == 367_500

    with pytest.raises(LedgerError) as exc:
        ledger.amend_entry(taken["id"], OperationPatch(freeze_account="tbank"), actor="test")
    assert exc.value.code == "tranche_has_releases"
    assert frozen_on("sber") == 367_500 and frozen_on("tbank") == 0
    assert ledger.check_invariants() == []


# ---------------------------------------------------------------------------------------
# as_of и операции задним числом


def test_as_of_ignores_later_backdated_entry():
    """Остаток на дату не должен видеть операцию, занесённую позже, но датированную позже даты."""
    base_state()
    post(kind="expense", amount=100_000, currency="RUB", from_account="tbank",
         category="exp_cafe", op_date="2026-09-10")
    post(kind="expense", amount=700_000, currency="RUB", from_account="tbank",
         category="exp_cafe", op_date="2026-09-20")

    def on(date: str) -> int:
        return next(a for a in ledger.balances(as_of=date)["accounts"]
                    if a["slug"] == "tbank")["balance"]["amount"]

    # начальные остатки датированы сегодняшним днём, в сентябрьские срезы они ещё не входят
    assert on("2026-09-15") == -100_000, "трата от 20-го попала в остаток на 15-е"
    assert on("2026-09-25") == 13_200_000 - 800_000
    assert balance("tbank", "RUB") == 13_200_000 - 800_000


def test_as_of_picks_up_backdated_entry_added_later():
    """Операция задним числом, занесённая сегодня, входит в остаток на свою дату."""
    base_state()
    before = next(a for a in ledger.balances(as_of="2026-09-12")["accounts"]
                  if a["slug"] == "tbank")["balance"]["amount"]
    post(kind="expense", amount=250_000, currency="RUB", from_account="tbank",
         category="exp_cafe", op_date="2026-09-11")
    after = next(a for a in ledger.balances(as_of="2026-09-12")["accounts"]
                 if a["slug"] == "tbank")["balance"]["amount"]
    assert after == before - 250_000


# ---------------------------------------------------------------------------------------
# края правок фиксера


def test_exchange_fractional_received_is_rejected():
    """Дробь запрещена и в полученной сумме обмена, а не только в основной."""
    base_state()
    bybit_before = balance("bybit", "USDT")
    with pytest.raises(LedgerError) as exc:
        post(kind="exchange", amount=1_000_000, currency="RUB", from_account="tbank",
             amount_to=10_179.5, currency_to="USDT", to_account="bybit")
    assert exc.value.code == "bad_request"
    assert exc.value.details["field"] == "amount_to"
    assert balance("bybit", "USDT") == bybit_before


def test_amount_as_string_with_kopecks_is_rejected():
    """«4300.99» строкой — та же ошибка ввода, что и числом 4300.99."""
    base_state()
    with pytest.raises(LedgerError) as exc:
        post(kind="expense", amount="4300.99", currency="AED",
             from_account="mashreq_personal", category="exp_cafe")
    assert exc.value.code == "bad_request"
    post(kind="expense", amount="4300", currency="AED",
         from_account="mashreq_personal", category="exp_cafe")
    assert balance("mashreq_personal", "AED") == 184_250 - 4_300


def test_archived_category_is_rejected_too():
    """Архив закрывает не только денежный счёт, но и категорию расхода."""
    base_state()
    conn = db.get_conn()
    conn.execute("UPDATE accounts SET archived = 1 WHERE slug = 'exp_cafe'")
    with pytest.raises(LedgerError) as exc:
        post(kind="expense", amount=4_300, currency="AED",
             from_account="mashreq_personal", category="exp_cafe")
    assert exc.value.code == "account_archived"


def test_screenshot_into_archived_account_warns_but_passes():
    """Занос истории со скрина — это прошлое: пропускаем с предупреждением, а не отказом (§5.11)."""
    base_state()
    conn = db.get_conn()
    conn.execute("UPDATE accounts SET archived = 1 WHERE slug = 'sber'")
    result = ledger.post_operation(
        ParsedOperation(kind="expense", amount=100_000, currency="RUB", from_account="sber",
                        category="exp_cafe", source="screenshot"), actor="test")
    assert [w["code"] for w in result["warnings"]] == ["archived_account_used"]
    assert balance("sber", "RUB") == 1_840_000 - 100_000


def test_reconcile_batch_with_unknown_category_writes_nothing():
    """Плохая строка в середине пачки: ни одной записи, ни одной строки в статусе accepted."""
    base_state()
    batch = ScreenBatch(account="mashreq_personal", currency="AED", rows=[
        ScreenRow(amount=-4_300, currency="AED", op_date="2026-09-17", raw_text="CAFE"),
        ScreenRow(amount=-2_000, currency="AED", op_date="2026-09-17", raw_text="SHOP")])
    result = ledger.reconcile(batch)
    ids = [item["id"] for item in result["new"]]
    assert len(ids) == 2
    conn = db.get_conn()
    before = int(conn.execute("SELECT COUNT(*) AS n FROM entries").fetchone()["n"])

    from backend.contracts import ReconcileDecision
    decisions = [ReconcileDecision(inbox_id=ids[0], decision="new"),
                 ReconcileDecision(inbox_id=ids[1], decision="new", category="нет-такой-категории")]
    with pytest.raises(LedgerError) as exc:
        ledger.apply_reconcile(decisions, actor="test")
    assert exc.value.code == "unknown_account"
    assert int(conn.execute("SELECT COUNT(*) AS n FROM entries").fetchone()["n"]) == before
    statuses = [r["status"] for r in conn.execute(
        "SELECT status FROM inbox ORDER BY id").fetchall()]
    assert statuses == ["pending", "pending"], statuses
    assert ledger.check_invariants() == []
