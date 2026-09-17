# -*- coding: utf-8 -*-
"""План счетов при пустой БД (ARCHITECTURE §3.2, ТЗ раздел 3). Идемпотентно по slug."""
from __future__ import annotations

import sqlite3

from backend.tz import utc_now

# slug, имя, тип, валюта, is_money, needs_counterparty, group_key, icon, sort
ACCOUNTS = [
    ("mashreq_personal", "Mashreq личный", "asset_personal", "AED", 1, 0, "AED", "bank", 10),
    ("cash_aed", "Наличные AED", "asset_personal", "AED", 1, 0, "AED", "cash", 20),
    ("cash_rub", "Наличные ₽", "asset_personal", "RUB", 1, 0, "RUB", "cash", 30),
    ("bybit", "Bybit", "asset_personal", "USDT", 1, 0, "USDT", "crypto", 40),
    ("tbank", "Т-Банк", "asset_personal", "RUB", 1, 0, "RUB", "card", 5),
    ("sber", "Сбер", "asset_personal", "RUB", 1, 0, "RUB", "card", 15),
    ("receivable", "Мне должны", "asset_personal", None, 0, 1, None, "person", 60),
    ("mashreq_family", "Mashreq семейный", "asset_family", "AED", 1, 0, "FAMILY", "bank", 70),
    ("cash_aed_family", "Наличные AED семейные", "asset_family", "AED", 1, 0, "FAMILY", "cash", 80),
    ("family_fund", "Семейный фонд", "liability", "AED", 0, 0, "FAMILY", "family", 90),
    ("sber_credit", "Кредитка Сбер", "liability", "RUB", 1, 0, "RUB", "credit", 50),
    ("tax_npd", "Налог НПД", "liability", "RUB", 0, 0, None, "tax", 100),
    ("payable", "Я должен", "liability", None, 0, 1, None, "person", 110),
]

# slug, имя, ставка налога bp, цвет, иконка, sort
INCOME_SOURCES = [
    ("inc_projects", "Проекты", 600, "#3E7BFA", "briefcase", 10),
    ("inc_parents", "Родители", 0, "#34B37E", "home", 20),
    ("inc_uae_job", "Подработка ОАЭ", 0, "#17B0A8", "sun", 30),
    ("inc_other", "Прочее", 0, "#A0A7B0", "dots", 40),
]

# slug, имя, цвет, иконка, sort
CATEGORIES = [
    ("exp_cafe", "Кафе и рестораны", "#FF7A45", "cafe", 10),
    ("exp_groceries", "Продукты", "#EA4C55", "groceries", 20),
    ("exp_transport", "Транспорт", "#FFC531", "car", 30),
    ("exp_housing", "Жильё", "#34B37E", "home", 40),
    ("exp_home", "Дом и быт", "#17B0A8", "sofa", 50),
    ("exp_comm", "Связь и подписки", "#5B6CD9", "wifi", 60),
    ("exp_fun", "Развлечения", "#8E7CE0", "fun", 70),
    ("exp_clothes", "Одежда", "#B455C9", "shirt", 80),
    ("exp_health", "Здоровье", "#2FA8E8", "health", 90),
    ("exp_edu", "Учёба", "#3E7BFA", "edu", 100),
    ("exp_visa", "Виза и документы", "#7B8794", "doc", 110),
    ("exp_travel", "Путешествия", "#00A5C4", "plane", 120),
    ("exp_charity", "Благотворительность", "#EE5FA0", "heart", 130),
    ("exp_gifts", "Подарки", "#FF9F1C", "gift", 140),
    ("exp_taxes", "Налоги", "#6E7781", "tax", 150),
    ("exp_family_contrib", "Взнос в семейный фонд", "#1FA855", "family", 160),
    ("exp_other", "Прочее", "#A0A7B0", "dots", 170),
]

EQUITY = [
    ("eq_opening", "Начальные остатки", "adjust", 200),
    ("eq_exchange", "Обмен валют", "swap", 210),
    ("eq_correction", "Корректировка остатков", "adjust", 220),
]


def _insert_account(conn: sqlite3.Connection, slug, name, type_, currency,
                    is_money, needs_cp, group_key, icon, sort) -> int:
    row = conn.execute("SELECT id FROM accounts WHERE slug = ?", (slug,)).fetchone()
    if row:
        return int(row["id"])
    cur = conn.execute(
        "INSERT INTO accounts (slug, name, type, currency, is_money, needs_counterparty,"
        " group_key, icon, sort, archived, created_at) VALUES (?,?,?,?,?,?,?,?,?,0,?)",
        (slug, name, type_, currency, is_money, needs_cp, group_key, icon, sort, utc_now()),
    )
    return int(cur.lastrowid)


def ensure(conn: sqlite3.Connection) -> None:
    """Заводит план счетов, категории и источники дохода. Повторный вызов ничего не дублирует."""
    for row in ACCOUNTS:
        _insert_account(conn, *row)

    tax_row = conn.execute("SELECT id FROM accounts WHERE slug = 'tax_npd'").fetchone()
    tax_id = int(tax_row["id"]) if tax_row else None

    for slug, name, tax_bp, color, icon, sort in INCOME_SOURCES:
        acc_id = _insert_account(conn, slug, name, "income", None, 0, 0, None, icon, sort)
        exists = conn.execute("SELECT 1 FROM income_sources WHERE account_id = ?", (acc_id,)).fetchone()
        if not exists:
            conn.execute(
                "INSERT INTO income_sources (account_id, tax_rate_bp, tax_account_id, color, icon, sort)"
                " VALUES (?,?,?,?,?,?)",
                (acc_id, tax_bp, tax_id if tax_bp else None, color, icon, sort),
            )

    for slug, name, color, icon, sort in CATEGORIES:
        acc_id = _insert_account(conn, slug, name, "expense", None, 0, 0, None, icon, sort)
        exists = conn.execute("SELECT 1 FROM categories WHERE account_id = ?", (acc_id,)).fetchone()
        if not exists:
            conn.execute(
                "INSERT INTO categories (account_id, parent_id, color, sort) VALUES (?, NULL, ?, ?)",
                (acc_id, color, sort),
            )

    for slug, name, icon, sort in EQUITY:
        _insert_account(conn, slug, name, "equity", None, 0, 0, None, icon, sort)
