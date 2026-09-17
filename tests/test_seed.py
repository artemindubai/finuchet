# -*- coding: utf-8 -*-
"""План счетов при пустой БД (ТЗ раздел 3, ARCHITECTURE §3.2)."""
from backend import db
from backend.seed import accounts as seed_accounts


def test_chart_of_accounts_created():
    conn = db.get_conn()
    slugs = {row["slug"] for row in conn.execute("SELECT slug FROM accounts").fetchall()}
    for slug in ("mashreq_personal", "cash_aed", "cash_rub", "bybit", "tbank", "sber",
                 "receivable", "mashreq_family", "cash_aed_family", "family_fund",
                 "sber_credit", "tax_npd", "payable", "eq_opening", "eq_exchange",
                 "eq_correction"):
        assert slug in slugs

    assert conn.execute("SELECT COUNT(*) AS n FROM categories").fetchone()["n"] == 17
    assert conn.execute("SELECT COUNT(*) AS n FROM income_sources").fetchone()["n"] == 4

    projects = conn.execute(
        "SELECT s.tax_rate_bp AS bp, a2.slug AS tax_slug FROM income_sources s"
        " JOIN accounts a ON a.id = s.account_id"
        " LEFT JOIN accounts a2 ON a2.id = s.tax_account_id WHERE a.slug = 'inc_projects'"
    ).fetchone()
    assert projects["bp"] == 600 and projects["tax_slug"] == "tax_npd"

    cafe = conn.execute(
        "SELECT c.color AS color, a.icon AS icon FROM categories c JOIN accounts a"
        " ON a.id = c.account_id WHERE a.slug = 'exp_cafe'").fetchone()
    assert cafe["color"] == "#FF7A45" and cafe["icon"] == "cafe"

    before = conn.execute("SELECT COUNT(*) AS n FROM accounts").fetchone()["n"]
    seed_accounts.ensure(conn)
    after = conn.execute("SELECT COUNT(*) AS n FROM accounts").fetchone()["n"]
    assert before == after


def test_settings_defaults():
    from backend import settings_store
    assert settings_store.get("freeze_account") == "tbank"
    assert settings_store.get("rate_markup_rub_per_aed_e6") == 2_000_000
    assert settings_store.get("tax_rate_default_bp") == 600
