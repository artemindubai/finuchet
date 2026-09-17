# -*- coding: utf-8 -*-
"""Карточки бота — дословный формат ARCHITECTURE §7.2 и чистый текст (грабля 1)."""
from __future__ import annotations

import pathlib
import re

from backend.bot import cards

NBSP = " "


def money(amount: int, currency: str = "RUB") -> dict:
    return {"amount": amount, "currency": currency}


def account(acc_id, slug, name, balance, currency="AED", role="asset", frozen=None, natural=None):
    return {"id": acc_id, "slug": slug, "name": name, "role": role,
            "balance": money(balance, currency),
            "natural": money(natural if natural is not None else balance, currency),
            "in_view": money(balance, currency), "frozen": frozen}


def posting(seq, acc_id, slug, name, side, amount, currency):
    return {"seq": seq, "account_id": acc_id, "account_slug": slug, "account_name": name,
            "side": side, "amount": money(amount, currency)}


# ---------------------------------------------------------------- образцы §7.2

def test_expense_card():
    result = {
        "id": 412, "kind": "expense", "amount": money(4300, "AED"), "title": "Кафе и рестораны",
        "status": "posted",
        "postings": [posting(1, 18, "exp_cafe", "Кафе и рестораны", "debit", 4300, "AED"),
                     posting(2, 1, "mashreq_personal", "Mashreq личный", "credit", 4300, "AED")],
        "effects": {"accounts": [account(1, "mashreq_personal", "Mashreq личный", 184250)]},
        "warnings": [],
    }
    assert cards.card_for_entry(result).splitlines() == [
        f"Расход 43{NBSP}AED — Кафе и рестораны",
        "Счёт: Mashreq личный",
        f"Остаток: 1{NBSP}842,50{NBSP}AED",
    ]


def test_expense_on_credit_card_shows_debt():
    result = {
        "id": 413, "kind": "expense", "amount": money(240000, "RUB"), "title": "Продукты",
        "status": "posted",
        "postings": [posting(1, 19, "exp_groceries", "Продукты", "debit", 240000, "RUB"),
                     posting(2, 12, "sber_credit", "Кредитка Сбер", "credit", 240000, "RUB")],
        "effects": {"accounts": [account(12, "sber_credit", "Кредитка Сбер", -240000, "RUB",
                                         role="liability", natural=240000)]},
        "warnings": [],
    }
    text = cards.card_for_entry(result)
    assert text.splitlines()[0] == f"Расход 2{NBSP}400{NBSP}₽ — Продукты"
    assert text.splitlines()[1] == "Счёт: Кредитка Сбер"
    assert text.splitlines()[2] == f"Долг по кредитке: 2{NBSP}400{NBSP}₽"


def test_income_with_npd_tax_and_free_rub():
    result = {
        "id": 420, "kind": "income", "amount": money(9000000, "RUB"), "title": "Проекты",
        "project": "Альфа", "status": "posted",
        "postings": [posting(1, 5, "tbank", "Т-Банк", "debit", 9000000, "RUB"),
                     posting(2, 14, "inc_projects", "Проекты", "credit", 9000000, "RUB"),
                     posting(3, 25, "exp_taxes", "Налоги", "debit", 540000, "RUB"),
                     posting(4, 13, "tax_npd", "Налог НПД", "credit", 540000, "RUB")],
        "effects": {"accounts": [account(5, "tbank", "Т-Банк", 13200000, "RUB",
                                         frozen=money(1225000, "RUB"))]},
        "warnings": [],
    }
    lines = cards.card_for_entry(result).splitlines()
    assert lines[0] == f"Доход 90{NBSP}000{NBSP}₽ — Проекты (Альфа)"
    assert lines[1] == "Счёт: Т-Банк"
    assert lines[2] == f"Налог НПД 6 %: 5{NBSP}400{NBSP}₽ начислено"
    assert lines[3] == f"Остаток: 132{NBSP}000{NBSP}₽, свободно 119{NBSP}750{NBSP}₽"


def test_exchange_rate_from_amounts():
    result = {
        "id": 425, "kind": "exchange", "amount": money(5000000, "RUB"), "status": "posted",
        "postings": [posting(1, 4, "bybit", "Bybit", "debit", 51230, "USDT"),
                     posting(2, 5, "tbank", "Т-Банк", "credit", 5000000, "RUB")],
        "effects": {"accounts": [account(4, "bybit", "Bybit", 92255, "USDT"),
                                 account(5, "tbank", "Т-Банк", 8200000, "RUB")]},
        "warnings": [],
    }
    lines = cards.card_for_entry(result).splitlines()
    assert lines[0] == f"Обмен 50{NBSP}000{NBSP}₽ на 512,30{NBSP}USDT"
    assert lines[1] == f"Курс 97,60{NBSP}₽/USDT (по суммам операции)"
    assert lines[2] == "Со счёта: Т-Банк, на счёт: Bybit"
    assert lines[3] == f"Остатки: Т-Банк 82{NBSP}000{NBSP}₽, Bybit 922,55{NBSP}USDT"


def family_withdrawal_result(warnings=None):
    return {
        "id": 431, "kind": "family_withdrawal", "amount": money(50000, "AED"),
        "title": "Взял из семейного", "status": "posted",
        "postings": [posting(1, 1, "mashreq_personal", "Mashreq личный", "debit", 50000, "AED"),
                     posting(2, 7, "mashreq_family", "Mashreq семейный", "credit", 50000, "AED")],
        "rate": {"pair": "AED/RUB", "rate_e6": 24500000, "source": "bybit_p2p",
                 "at": "2026-09-17T09:20:00Z"},
        "effects": {
            "accounts": [account(1, "mashreq_personal", "Mashreq личный", 184250),
                         account(7, "mashreq_family", "Mashreq семейный", 800000)],
            "net_worth": money(22291642), "free_rub": money(14315000),
            "frozen_rub": money(1225000), "family_debt": money(50000, "AED"),
            "family_direction": "i_owe",
            "tranche": {"id": 3, "aed_taken": money(50000, "AED"), "aed_left": money(50000, "AED"),
                        "rub_frozen": money(1225000), "rub_left": money(1225000),
                        "rate_e6": 24500000, "rate_source": "bybit_p2p", "op_date": "2026-09-17",
                        "account_id": 5, "account_name": "Т-Банк", "status": "open",
                        "label": "заблокировано в счёт взятых 17.09.2026 500 AED по курсу 24,50"},
            "released": [],
        },
        "warnings": warnings or [],
    }


def test_family_withdrawal_card_wording():
    lines = cards.card_for_entry(family_withdrawal_result()).splitlines()
    assert lines[0] == f"Взял из семейного 500{NBSP}AED"
    assert lines[1] == "Со счёта: Mashreq семейный, на счёт: Mashreq личный"
    assert lines[2] == f"Курс 24,50{NBSP}₽/AED (Bybit P2P, 17.09 13:20)"
    assert lines[3] == (f"Заблокировано в счёт взятых 17.09.2026 500 AED по курсу 24,50 — "
                        f"12{NBSP}250{NBSP}₽ на Т-Банке")
    assert lines[4] == f"Долг семье: 500{NBSP}AED"
    assert lines[5] == (f"Остатки: Mashreq личный 1{NBSP}842,50{NBSP}AED, "
                        f"свободно в рублях 143{NBSP}150{NBSP}₽")


def test_freeze_not_covered_warning_before_last_line():
    warning = {"code": "freeze_not_covered", "message": "Не хватает покрытия 4 320 ₽",
               "details": {"shortfall": money(432000), "account": "tbank"}}
    lines = cards.card_for_entry(family_withdrawal_result([warning])).splitlines()
    assert lines[-2] == f"Не хватает покрытия 4{NBSP}320{NBSP}₽ — заморожено больше, чем есть рублей"
    assert lines[-1].startswith("Остатки:")


def test_family_repayment_releases_line():
    result = {
        "id": 440, "kind": "family_repayment", "amount": money(20000, "AED"), "status": "posted",
        "postings": [posting(1, 7, "mashreq_family", "Mashreq семейный", "debit", 20000, "AED"),
                     posting(2, 1, "mashreq_personal", "Mashreq личный", "credit", 20000, "AED")],
        "effects": {
            "accounts": [account(7, "mashreq_family", "Mashreq семейный", 820000),
                         account(1, "mashreq_personal", "Mashreq личный", 164250)],
            "free_rub": money(14805000), "frozen_rub": money(735000),
            "family_debt": money(30000, "AED"), "family_direction": "i_owe",
            "released": [{"tranche_id": 3, "aed": money(20000, "AED"), "rub": money(490000),
                          "op_date": "2026-09-17", "rate_e6": 24500000}],
        },
        "warnings": [],
    }
    lines = cards.card_for_entry(result).splitlines()
    assert lines[0] == f"Вернул в семейный 200{NBSP}AED"
    assert lines[2] == f"Разморожено 4{NBSP}900{NBSP}₽ по траншу от 17.09 (курс 24,50)"
    assert lines[3] == f"Долг семье: 300{NBSP}AED, заморожено 7{NBSP}350{NBSP}₽"
    assert lines[4].endswith(f"свободно в рублях 148{NBSP}050{NBSP}₽")


def test_paid_for_family_when_family_owes():
    result = {
        "id": 441, "kind": "paid_for_family_from_own", "amount": money(10000, "AED"),
        "status": "posted",
        "postings": [posting(1, 9, "family_fund", "Семейный фонд", "debit", 10000, "AED"),
                     posting(2, 1, "mashreq_personal", "Mashreq личный", "credit", 10000, "AED")],
        "effects": {"accounts": [account(1, "mashreq_personal", "Mashreq личный", 174250)],
                    "family_debt": money(-10000, "AED"), "family_direction": "family_owes",
                    "released": []},
        "warnings": [],
    }
    lines = cards.card_for_entry(result).splitlines()
    assert lines[0] == f"Заплатил за семью 100{NBSP}AED со своих"
    assert lines[2] == f"Семья должна вам 100{NBSP}AED"
    assert not any("заморожено" in line for line in lines)


def test_tax_payment_card():
    result = {
        "id": 450, "kind": "tax_payment", "amount": money(1836000), "status": "posted",
        "postings": [posting(1, 13, "tax_npd", "Налог НПД", "debit", 1836000, "RUB"),
                     posting(2, 5, "tbank", "Т-Банк", "credit", 1836000, "RUB")],
        "effects": {"accounts": [account(5, "tbank", "Т-Банк", 11364000, "RUB"),
                                 account(13, "tax_npd", "Налог НПД", 0, "RUB",
                                         role="liability", natural=0)]},
        "warnings": [],
    }
    lines = cards.card_for_entry(result).splitlines()
    assert lines[0] == f"Уплата налога НПД 18{NBSP}360{NBSP}₽"
    assert lines[2] == f"Долг по налогу: 0{NBSP}₽"
    assert lines[3] == f"Остаток: 113{NBSP}640{NBSP}₽"


def test_balance_correction_card():
    result = {
        "id": 460, "kind": "balance_correction", "amount": money(-235000), "status": "posted",
        "postings": [posting(1, 30, "eq_correction", "Корректировка", "debit", 235000, "RUB"),
                     posting(2, 5, "tbank", "Т-Банк", "credit", 235000, "RUB")],
        "effects": {"accounts": [account(5, "tbank", "Т-Банк", 13200000, "RUB")]},
        "warnings": [],
    }
    lines = cards.card_for_entry(result).splitlines()
    assert lines[0] == f"Выровнял остаток: Т-Банк −2{NBSP}350{NBSP}₽"
    assert lines[1] == f"Было в учёте 134{NBSP}350{NBSP}₽, стало 132{NBSP}000{NBSP}₽"


def test_opening_balance_card():
    result = {
        "id": 470, "kind": "opening_balance", "amount": money(15000000), "status": "posted",
        "postings": [posting(1, 5, "tbank", "Т-Банк", "debit", 15000000, "RUB"),
                     posting(2, 29, "eq_opening", "Начальные остатки", "credit", 15000000, "RUB")],
        "effects": {"accounts": [account(5, "tbank", "Т-Банк", 15000000, "RUB")],
                    "net_worth": money(24091642)},
        "warnings": [],
    }
    lines = cards.card_for_entry(result).splitlines()
    assert lines[0] == f"Начальный остаток: Т-Банк 150{NBSP}000{NBSP}₽"
    assert lines[1] == f"Личный итог: 240{NBSP}916,42{NBSP}₽"


# ---------------------------------------------------------------- общие требования

def test_card_is_plain_text():
    text = cards.card_for_entry(family_withdrawal_result())
    assert not re.search(r"[*`#_]", text)
    assert "<" not in text and ">" not in text


def test_plain_tg_strips_markup():
    assert cards.plain_tg("**Расход** `43` AED\n## Счёт") == "Расход 43 AED\nСчёт"


def test_parse_mode_is_never_set():
    """parse_mode не задаётся нигде в коде бота — иначе разметка прилетит в чат."""
    root = pathlib.Path(__file__).resolve().parents[1] / "backend"
    hits = []
    for path in list((root / "bot").glob("*.py")) + list((root / "pipeline").glob("*.py")):
        if re.search(r"parse_mode\s*=", path.read_text(encoding="utf-8")):
            hits.append(path.name)
    assert hits == []


def test_number_format():
    assert cards.format_amount({"amount": 184250, "currency": "AED"}) == f"1{NBSP}842,50{NBSP}AED"
    assert cards.format_amount({"amount": 13200000, "currency": "RUB"}) == f"132{NBSP}000{NBSP}₽"
    assert cards.format_amount({"amount": 41025, "currency": "USDT"}) == f"410,25{NBSP}USDT"
    assert cards.format_amount({"amount": 0, "currency": "RUB"}) == f"0{NBSP}₽"


def test_batch_card_lists_operations():
    def one(kind, amount, title):
        return {"id": 1, "kind": kind, "amount": money(amount, "AED"), "title": title,
                "status": "posted",
                "postings": [posting(2, 1, "mashreq_personal", "Mashreq личный", "credit", amount, "AED")],
                "effects": {"accounts": [account(1, "mashreq_personal", "Mashreq личный", 177950)]},
                "warnings": []}

    text = cards.card_for_batch([one("expense", 4300, "Кафе и рестораны"),
                                 one("expense", 2000, "Транспорт")])
    lines = text.splitlines()
    assert lines[0] == "Записано 2 операции"
    assert lines[1] == f"1. Расход 43{NBSP}AED — Кафе и рестораны, Mashreq личный"
    assert lines[2] == f"2. Расход 20{NBSP}AED — Транспорт, Mashreq личный"
    assert lines[3] == f"Остаток: Mashreq личный 1{NBSP}779,50{NBSP}AED"
