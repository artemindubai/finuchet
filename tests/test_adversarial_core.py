# -*- coding: utf-8 -*-
"""Адверсариальные сценарии ядра: обмен, налог НПД, кредитка, границы дат, курсы.

Проверяется арифметика, а не форма ответа (ARCHITECTURE §4.2, §4.4, §5.3, §8.2)."""
import pytest

from backend import db, ledger, money
from backend.contracts import LedgerError
from tests.conftest import balance, base_state, post, seed_rates

RATE = 24_500_000


def acc_vector(slug: str) -> dict:
    from backend.ledger.balances import account_vector
    from backend.ledger.common import resolve_account
    conn = db.get_conn()
    return account_vector(conn, int(resolve_account(conn, slug)["id"]))


# ---------------------------------------------------------------------------------------
# 4. обмен валют


def test_double_exchange_leaves_only_fx_result_on_service_account():
    """RUB → USDT → AED двумя операциями с некруглыми суммами.

    «Обмен валют» обязан обнулиться по USDT (валюта прошла насквозь) и держать
    разницу по RUB и AED — это курсовая разница, а не доход и не расход."""
    base_state()
    post(kind="exchange", amount=987_654, currency="RUB", from_account="tbank",
         amount_to=101_79, currency_to="USDT", to_account="bybit")
    post(kind="exchange", amount=101_79, currency="USDT", from_account="bybit",
         amount_to=374_11, currency_to="AED", to_account="mashreq_personal")

    swap = acc_vector("eq_exchange")
    assert swap.get("USDT", 0) == 0, "USDT прошёл насквозь — на служебном счёте нуля нет"
    assert swap.get("RUB") == 987_654
    assert swap.get("AED") == -374_11

    from backend.tz import today_dubai
    month = ledger.analytics_month(today_dubai()[:7])
    assert month["expense_total"]["amount"] == 0, "обмен не расход"
    assert month["income_total"]["amount"] == 0, "обмен не доход"
    assert ledger.check_invariants() == []


def test_exchange_with_zero_received_is_rejected():
    """«Обменял 10 000 ₽ и получил 0» — деньги исчезают в служебном счёте."""
    base_state()
    with pytest.raises(LedgerError) as exc:
        post(kind="exchange", amount=1_000_000, currency="RUB", from_account="tbank",
             amount_to=0, currency_to="USDT", to_account="bybit")
    assert exc.value.code == "bad_request"


def test_exchange_with_negative_received_is_rejected():
    """Отрицательная полученная сумма обязана быть отвергнута, а не списать деньги дважды."""
    base_state()
    bybit_before = balance("bybit", "USDT")
    with pytest.raises(LedgerError) as exc:
        post(kind="exchange", amount=1_000_000, currency="RUB", from_account="tbank",
             amount_to=-10_000, currency_to="USDT", to_account="bybit")
    assert exc.value.code == "bad_request"
    assert balance("bybit", "USDT") == bybit_before


def test_exchange_negative_received_to_rub_destroys_money():
    """Та же дыра в ветке «получил рубли»: операция ЗАПИСЫВАЕТСЯ и сжигает обе стороны.

    100 USDT «обменяны» на −5 000 ₽: с Bybit ушло 100 USDT, с Т-Банка ушло 5 000 ₽,
    инвариант «сумма по валюте = 0» при этом сходится — учёт молча теряет деньги."""
    base_state()
    tbank_before = balance("tbank", "RUB")
    bybit_before = balance("bybit", "USDT")
    with pytest.raises(LedgerError) as exc:
        post(kind="exchange", amount=10_000, currency="USDT", from_account="bybit",
             amount_to=-500_000, currency_to="RUB", to_account="tbank")
    assert exc.value.code == "bad_request"
    assert balance("tbank", "RUB") == tbank_before
    assert balance("bybit", "USDT") == bybit_before


def test_exchange_one_kopeck_is_exact():
    base_state()
    rub_before = balance("tbank", "RUB")
    usdt_before = balance("bybit", "USDT")
    post(kind="exchange", amount=1, currency="RUB", from_account="tbank",
         amount_to=1, currency_to="USDT", to_account="bybit")
    assert balance("tbank", "RUB") == rub_before - 1
    assert balance("bybit", "USDT") == usdt_before + 1
    assert ledger.check_invariants() == []


# ---------------------------------------------------------------------------------------
# 5. налог НПД


def test_income_in_aed_on_taxed_source_does_not_accrue_rub_tax():
    base_state()
    result = post(kind="income", amount=200_000, currency="AED", to_account="mashreq_personal",
                  income_source="inc_projects", project="Альфа")
    codes = [w["code"] for w in result["warnings"]]
    assert "tax_currency_mismatch" in codes
    assert balance("tax_npd", "RUB") == 0
    assert balance("tax_npd", "AED") == 0
    assert ledger.check_invariants() == []


def test_income_without_tax_and_zero_rate_source():
    base_state()
    post(kind="income", amount=9_000_000, currency="RUB", to_account="tbank",
         income_source="inc_projects", no_tax=True)
    assert balance("tax_npd", "RUB") == 0
    post(kind="income", amount=200_000, currency="AED", to_account="mashreq_personal",
         income_source="inc_uae_job")
    assert balance("tax_npd", "RUB") == 0
    assert balance("tax_npd", "AED") == 0


def test_backdated_income_lands_in_previous_month():
    """Доход задним числом попадает в прошлый месяц, а не в текущий."""
    base_state()
    from backend.tz import month_bounds, shift_month, today_dubai
    this_month = today_dubai()[:7]
    prev_month = shift_month(this_month, -1)
    prev_last_day = month_bounds(prev_month)[1]

    post(kind="income", amount=9_000_000, currency="RUB", to_account="tbank",
         income_source="inc_projects", op_date=prev_last_day)

    prev = ledger.analytics_month(prev_month)
    now = ledger.analytics_month(this_month)
    assert prev["income_total"]["amount"] == 9_000_000
    assert now["income_total"]["amount"] == 0
    # налог 6 % начислен той же операцией и виден в расходах прошлого месяца
    assert prev["expense_total"]["amount"] == 540_000
    assert now["expense_total"]["amount"] == 0
    assert balance("tax_npd", "RUB") == -540_000     # обязательство: сырой остаток отрицательный


def test_tax_payment_larger_than_accrued_shows_overpay():
    base_state()
    post(kind="income", amount=9_000_000, currency="RUB", to_account="tbank",
         income_source="inc_projects")
    assert balance("tax_npd", "RUB") == -540_000
    post(kind="tax_payment", amount=800_000, currency="RUB", from_account="tbank")
    assert balance("tax_npd", "RUB") == 260_000
    screen = ledger.debts()
    assert screen["tax"]["amount"]["amount"] == -260_000, (
        "переплата налога должна читаться как «минус долг», а не как долг 2 600 ₽")
    assert ledger.check_invariants() == []


# ---------------------------------------------------------------------------------------
# 6. границы суток и месяца по Дубаю


def test_dubai_date_of_utc_evening_is_next_day():
    from backend.tz import dubai_date_of
    import calendar
    ts = calendar.timegm((2026, 9, 17, 23, 30, 0, 0, 0, 0))    # 23:30 UTC
    assert dubai_date_of(ts) == "2026-09-18"
    ts_early = calendar.timegm((2026, 9, 17, 19, 59, 0, 0, 0, 0))
    assert dubai_date_of(ts_early) == "2026-09-17"


def test_yesterday_phrase_at_ten_past_midnight():
    from backend.tz import parse_date_phrase
    assert parse_date_phrase("вчера поел на 43 дирхама", today="2026-09-01") == "2026-08-31"
    assert parse_date_phrase("12-го заплатил", today="2026-09-01") == "2026-08-12"


def test_entry_on_month_boundary_belongs_to_its_own_month():
    base_state()
    post(kind="expense", amount=4_300, currency="AED", from_account="mashreq_personal",
         category="exp_cafe", op_date="2026-08-31")
    post(kind="expense", amount=2_000, currency="AED", from_account="mashreq_personal",
         category="exp_cafe", op_date="2026-09-01")
    aug = ledger.analytics_month("2026-08")
    sep = ledger.analytics_month("2026-09")
    assert aug["categories"][0]["amount"]["currency"] == "RUB"
    assert aug["expense_total"]["amount"] > 0
    assert sep["expense_total"]["amount"] > 0
    assert aug["expense_total"]["amount"] != sep["expense_total"]["amount"]


# ---------------------------------------------------------------------------------------
# 7. кредитка


def test_credit_card_overpay_keeps_home_identity():
    """Погасили кредитку больше долга: на ней плюс, тождество Главной обязано сойтись."""
    base_state()
    from backend.contracts import OpeningBalanceItem
    ledger.post_opening_balances([OpeningBalanceItem(account="sber_credit", amount=240_000,
                                                    currency="RUB")], actor="test")
    assert balance("sber_credit", "RUB") == -240_000
    post(kind="expense", amount=100_000, currency="RUB", from_account="sber_credit",
         category="exp_groceries")
    assert balance("sber_credit", "RUB") == -340_000
    post(kind="transfer", amount=500_000, currency="RUB", from_account="tbank",
         to_account="sber_credit")
    assert balance("sber_credit", "RUB") == 160_000

    home = ledger.balances()
    groups = sum(g["total"]["amount"] for g in home["groups"])
    screen = ledger.debts()
    owed = sum(i["in_view"]["amount"] for i in screen["owed_to_me"])
    i_owe = sum(i["in_view"]["amount"] for i in screen["i_owe"])
    tax = screen["tax"]["amount"]["amount"]
    from backend.ledger.common import to_view
    from backend import rates
    snapshot = rates.snapshot(conn=db.get_conn())
    family = to_view(home["family"]["debt"]["amount"], "AED", "RUB", snapshot)
    identity = groups + owed - i_owe - tax - family
    assert abs(home["net_worth"]["amount"] - identity) <= 2, (
        f"net_worth {home['net_worth']['amount']} против тождества {identity}")

    rub_group = next(g for g in home["groups"] if g["key"] == "RUB")
    card = next(a for a in rub_group["accounts"] if a["slug"] == "sber_credit")
    assert card["in_view"]["amount"] == 160_000
    assert card["natural"]["amount"] == -160_000, "natural обязан быть зеркалом balance"
    assert ledger.check_invariants() == []


# ---------------------------------------------------------------------------------------
# 10. курсы


def test_operation_rate_snapshot_is_frozen_after_rate_update():
    base_state()
    entry = post(kind="expense", amount=4_300, currency="AED", from_account="mashreq_personal",
                 category="exp_cafe")
    snap_before = ledger.get_entry(entry["id"])["rates_snapshot"]["rub_per_aed_e6"]

    from backend import rates
    from backend.tz import utc_now
    rates.provider.store("AED/RUB", 40_000_000, "test2", at=utc_now() + 5, conn=db.get_conn())
    snap_after = ledger.get_entry(entry["id"])["rates_snapshot"]["rub_per_aed_e6"]
    assert snap_after == snap_before, "снимок курсов в операции неизменен"


def test_past_month_analytics_stable_when_current_rate_moves():
    base_state()
    from backend.tz import month_bounds, shift_month, today_dubai
    prev_month = shift_month(today_dubai()[:7], -1)
    post(kind="expense", amount=1_000_000, currency="RUB", from_account="tbank",
         category="exp_housing", op_date=month_bounds(prev_month)[1])
    before = ledger.analytics_month(prev_month, currency_view="AED")["expense_total"]["amount"]

    from backend import rates
    from backend.tz import utc_now
    rates.provider.store("AED/RUB", 40_000_000, "test2", at=utc_now() + 5, conn=db.get_conn())
    after = ledger.analytics_month(prev_month, currency_view="AED")["expense_total"]["amount"]
    assert after == before, "аналитика прошлого месяца поехала от смены текущего курса"


def test_stale_cache_warns_rate_from_cache_on_freeze(monkeypatch):
    """Живые источники молчат, кэш протух → предупреждение rate_from_cache, а не отказ."""
    base_state()
    from backend import rates
    from backend.tz import utc_now
    conn = db.get_conn()
    conn.execute("DELETE FROM rate_history")
    old = utc_now() - 10 * 3600
    for pair, rate in (("AED/RUB", 23_450_000), ("USD/RUB", 84_173_200),
                       ("USDT/RUB", 97_150_000), ("USDT/AED", 3_675_000)):
        rates.provider.store(pair, rate, "test", at=old, conn=conn)
    monkeypatch.setattr(rates.provider, "refresh_all", lambda **kw: {})

    result = post(kind="family_withdrawal", amount=50_000, currency="AED",
                  from_account="mashreq_family", to_account="mashreq_personal")
    codes = [w["code"] for w in result["warnings"]]
    assert "rate_from_cache" in codes, codes
    tranche = result["effects"]["tranche"]
    assert tranche["rate_e6"] == 23_450_000
    assert tranche["rub_frozen"]["amount"] == money.round_half_up(50_000 * 23_450_000, 1_000_000)
