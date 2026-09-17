# -*- coding: utf-8 -*-
"""Аналитика месяца: доли, источники дохода, курс операции, 12 точек (ARCHITECTURE §5.7)."""
from backend import db, ledger, rates
from backend.tz import shift_month, today_dubai
from tests.conftest import base_state, post

MONTH = today_dubai()[:7]


def test_month_categories_and_shares():
    base_state()
    post(kind="expense", amount=118_000, currency="RUB", from_account="tbank", category="exp_cafe")
    post(kind="expense", amount=82_000, currency="RUB", from_account="tbank",
         category="exp_housing")
    post(kind="expense", amount=4_300, currency="AED", from_account="mashreq_personal",
         category="exp_cafe")

    data = ledger.analytics_month(MONTH)
    assert sum(item["amount"]["amount"] for item in data["categories"]) == \
        data["expense_total"]["amount"]
    assert sum(item["share_bp"] for item in data["categories"]) == 10_000
    cafe = next(item for item in data["categories"] if item["name"] == "Кафе и рестораны")
    assert cafe["amount"]["amount"] == 118_000 + 100_835        # 43 AED по курсу 23,45
    assert cafe["count"] == 2
    assert cafe["color"] == "#FF7A45" and cafe["icon"] == "cafe"


def test_income_sources_sum_equals_total():
    base_state()
    post(kind="income", amount=4_200_000, currency="RUB", to_account="tbank",
         income_source="inc_projects", project="Альфа")
    post(kind="income", amount=2_100_000, currency="RUB", to_account="tbank",
         income_source="inc_parents")
    post(kind="income", amount=36_000, currency="AED", to_account="mashreq_personal",
         income_source="inc_uae_job")

    data = ledger.analytics_month(MONTH)
    assert sum(item["amount"]["amount"] for item in data["income_sources"]) == \
        data["income_total"]["amount"]
    assert sum(item["share_bp"] for item in data["income_sources"]) == 10_000
    projects = next(item for item in data["income_sources"] if item["name"] == "Проекты")
    assert projects["tax_accrued"]["amount"] == 252_000        # 6 % НПД
    assert projects["color"] == "#3E7BFA"


def test_income_by_source_and_project():
    base_state()
    post(kind="income", amount=2_500_000, currency="RUB", to_account="tbank",
         income_source="inc_projects", project="Альфа")
    post(kind="income", amount=1_700_000, currency="RUB", to_account="tbank",
         income_source="inc_projects", project="Бета")

    projects = next(item for item in ledger.analytics_month(MONTH)["income_sources"]
                    if item["name"] == "Проекты")
    assert [p["project"] for p in projects["projects"]] == ["Альфа", "Бета"]
    assert [p["amount"]["amount"] for p in projects["projects"]] == [2_500_000, 1_700_000]
    assert sum(p["share_bp"] for p in projects["projects"]) == 10_000


def test_period_uses_entry_rate_snapshot():
    base_state()
    post(kind="expense", amount=10_000, currency="AED", from_account="mashreq_personal",
         category="exp_cafe")
    before = ledger.analytics_month(MONTH)["expense_total"]["amount"]
    assert before == 234_500                                   # 100 AED × 23,45

    from backend.tz import utc_now
    rates.provider.store("AED/RUB", 30_000_000, "test-new", at=utc_now() + 10, conn=db.get_conn())
    after = ledger.analytics_month(MONTH)["expense_total"]["amount"]
    assert after == before                                     # отчёт считается по курсу операции


def test_rub_only_entry_converts_to_aed_by_snapshot():
    base_state()
    post(kind="expense", amount=234_500, currency="RUB", from_account="tbank",
         category="exp_groceries")
    in_aed = ledger.analytics_month(MONTH, currency_view="AED")["expense_total"]["amount"]
    assert in_aed == 10_000                                    # 2 345 ₽ по 23,45

    from backend.tz import utc_now
    rates.provider.store("AED/RUB", 30_000_000, "test-new", at=utc_now() + 10, conn=db.get_conn())
    assert ledger.analytics_month(MONTH, currency_view="AED")["expense_total"]["amount"] == in_aed


def test_by_month_has_twelve_points():
    base_state()
    post(kind="expense", amount=100_000, currency="RUB", from_account="tbank",
         category="exp_cafe")
    data = ledger.analytics_month(MONTH)
    assert len(data["by_month"]) == 12
    assert data["by_month"][-1]["month"] == MONTH
    assert data["by_month"][0]["month"] == shift_month(MONTH, -11)
    empty = data["by_month"][0]
    assert empty["income"]["amount"] == 0 and empty["expense"]["amount"] == 0
    assert data["prev_month"] == shift_month(MONTH, -1)
    assert data["next_month"] is None


def test_feed_summary_matches_filters():
    base_state()
    post(kind="expense", amount=100_000, currency="RUB", from_account="tbank", category="exp_cafe")
    post(kind="expense", amount=60_000, currency="RUB", from_account="tbank",
         category="exp_transport")
    post(kind="income", amount=1_000_000, currency="RUB", to_account="tbank",
         income_source="inc_parents")

    from backend.contracts import EntryFilters
    page = ledger.list_entries(EntryFilters(limit=2))
    summary = page["summary"]
    assert summary["out"]["amount"] == 160_000
    assert summary["in"]["amount"] == 1_000_000
    assert sum(item["share_bp"] for item in summary["out_breakdown"]) == 10_000
    assert sum(item["share_bp"] for item in summary["in_breakdown"]) == 10_000
