# -*- coding: utf-8 -*-
"""Шесть фраз Артёма из ТЗ 11.1 (ответ №13) плюс обмен и возврат в семейный.

Модель замокана: проверяем схему разбора, приведение к ParsedOperation и запись в ядро.
"""
from __future__ import annotations

import asyncio

from conftest import op, parse_out

CHAT = 100000001


def run(coro):
    return asyncio.run(coro)


def posted(ledger, index: int = 0):
    return ledger.posted[index]


def test_phrase_cafe(ledger, llm_answer):
    from backend.pipeline import text as pipeline

    llm_answer["data"] = parse_out(op(kind="expense", amount=4300, currency="AED",
                                      from_account="mashreq_personal", category="exp_cafe",
                                      description="обед в кафе"))
    run(pipeline.handle_phrase(CHAT, "Сходил в кафе, поел на 43 дирхама", source="text"))
    parsed = posted(ledger)
    assert (parsed.kind, parsed.amount, parsed.currency) == ("expense", 4300, "AED")
    assert parsed.from_account == "mashreq_personal"
    assert parsed.category == "exp_cafe"
    assert parsed.raw_input == "Сходил в кафе, поел на 43 дирхама"


def test_phrase_family_withdrawal_freezes(ledger, llm_answer):
    from backend.pipeline import text as pipeline

    llm_answer["data"] = parse_out(op(kind="family_withdrawal", amount=50000, currency="AED",
                                      from_account="mashreq_family", to_account="mashreq_personal",
                                      freeze=True))
    run(pipeline.handle_phrase(
        CHAT, "Взял с семейного счёта 500 дирхам, заморозь эквивалент в рублях на моём счёте"))
    parsed = posted(ledger)
    assert parsed.kind == "family_withdrawal"
    assert (parsed.amount, parsed.currency) == (50000, "AED")
    assert parsed.from_account == "mashreq_family" and parsed.to_account == "mashreq_personal"
    assert parsed.freeze is True


def test_phrase_salary_income(ledger, llm_answer):
    from backend.pipeline import text as pipeline

    llm_answer["data"] = parse_out(op(kind="income", amount=200000, currency="AED",
                                      to_account="mashreq_personal", income_source="inc_uae_job"))
    run(pipeline.handle_phrase(CHAT, "Получил зарплату 2 тысячи дирхам"))
    parsed = posted(ledger)
    assert (parsed.kind, parsed.amount, parsed.currency) == ("income", 200000, "AED")
    assert parsed.income_source == "inc_uae_job"
    assert parsed.to_account == "mashreq_personal"


def test_phrase_loan_to_masha(ledger, llm_answer):
    from backend.pipeline import text as pipeline

    llm_answer["data"] = parse_out(op(kind="loan_given", amount=30000, currency="AED",
                                      from_account="mashreq_personal", counterparty="Маша"))
    run(pipeline.handle_phrase(CHAT, "Дал в долг Маше 300 дирхам"))
    parsed = posted(ledger)
    assert parsed.kind == "loan_given"
    assert parsed.counterparty == "Маша"
    assert parsed.from_account == "mashreq_personal"


def test_noon_list_is_one_operation(ledger, llm_answer):
    from backend.pipeline import text as pipeline

    llm_answer["data"] = parse_out(op(kind="expense", amount=30000, currency="AED",
                                      from_account="mashreq_personal", category="exp_home",
                                      description="лампа, швабра, мышка"))
    run(pipeline.handle_phrase(CHAT, "Купил лампу, швабру, мышку для ноутбука на Noon за 300 дирхам"))
    assert len(ledger.posted) == 1
    assert ledger.posted[0].category == "exp_home"
    assert ledger.posted[0].amount == 30000


def test_charity_expense(ledger, llm_answer):
    from backend.pipeline import text as pipeline

    llm_answer["data"] = parse_out(op(kind="expense", amount=20000, currency="AED",
                                      from_account="mashreq_personal", category="exp_charity"))
    run(pipeline.handle_phrase(CHAT, "Отдал на благотворительность 200 дирхам"))
    assert ledger.posted[0].category == "exp_charity"


def test_exchange_rub_to_usdt(ledger, llm_answer):
    from backend.pipeline import text as pipeline

    llm_answer["data"] = parse_out(op(kind="exchange", amount=5000000, currency="RUB",
                                      from_account="tbank", amount_to=50000, currency_to="USDT",
                                      to_account="bybit"))
    run(pipeline.handle_phrase(CHAT, "Перевёл 50 тысяч на Bybit, вышло 500 USDT"))
    parsed = posted(ledger)
    assert parsed.kind == "exchange"
    assert (parsed.amount, parsed.currency) == (5000000, "RUB")
    assert (parsed.amount_to, parsed.currency_to) == (50000, "USDT")
    assert parsed.to_account == "bybit"


def test_family_repayment(ledger, llm_answer):
    from backend.pipeline import text as pipeline

    llm_answer["data"] = parse_out(op(kind="family_repayment", amount=20000, currency="AED",
                                      from_account="mashreq_personal", to_account="mashreq_family"))
    run(pipeline.handle_phrase(CHAT, "Вернул 200 дирхам в семейный"))
    parsed = posted(ledger)
    assert parsed.kind == "family_repayment"
    assert parsed.to_account == "mashreq_family"


def test_multi_operation_phrase(ledger, llm_answer):
    from backend.pipeline import text as pipeline

    llm_answer["data"] = parse_out(
        op(kind="expense", amount=4300, currency="AED", from_account="mashreq_personal",
           category="exp_cafe"),
        op(kind="expense", amount=2000, currency="AED", from_account="mashreq_personal",
           category="exp_transport"),
    )
    reply = run(pipeline.handle_phrase(CHAT, "Поел на 43 и такси 20"))
    assert len(ledger.posted) == 2
    assert [p.category for p in ledger.posted] == ["exp_cafe", "exp_transport"]
    assert "Записано 2 операции" in reply.text


def test_rate_named_by_voice_goes_to_operation(ledger, llm_answer):
    from backend.pipeline import text as pipeline

    llm_answer["data"] = parse_out(op(kind="family_withdrawal", amount=50000, currency="AED",
                                      from_account="mashreq_family", to_account="mashreq_personal",
                                      rate=24500000, rate_named_by_voice=True))
    run(pipeline.handle_phrase(CHAT, "Взял 500 дирхам из семейного по 24,50"))
    parsed = posted(ledger)
    assert parsed.rate_e6 == 24500000
    assert parsed.rate_source == "voice"


def test_clarification_question_is_asked_once(ledger, llm_answer):
    from backend.pipeline import text as pipeline

    llm_answer["data"] = parse_out(needs=True, question="Сколько дирхамов? Сумму не расслышал.")
    reply = run(pipeline.handle_phrase(CHAT, "Отдал на благотворительность"))
    assert ledger.posted == []
    assert reply.text == "Сколько дирхамов? Сумму не расслышал."
    assert ledger.pending[CHAT]["state"] == "clarify"

    # ответ на уточнение клеится с исходной фразой и разбирается заново
    llm_answer["data"] = parse_out(op(kind="expense", amount=20000, currency="AED",
                                      from_account="mashreq_personal", category="exp_charity"))
    run(pipeline.handle_phrase(CHAT, "200"))
    assert ledger.posted[0].amount == 20000
    assert "Отдал на благотворительность" in llm_answer["calls"][-1]["user"]


def test_quota_exhausted_stops_before_model(ledger, llm_answer):
    from backend.bot import cards
    from backend.pipeline import text as pipeline

    ledger.quota_left = 0
    reply = run(pipeline.handle_phrase(CHAT, "Поел на 43 дирхама"))
    assert reply.text == cards.QUOTA_TEXT
    assert llm_answer["calls"] == []


def test_prompt_tail_carries_today_and_last_accounts(ledger, llm_answer):
    from backend.pipeline import text as pipeline

    llm_answer["data"] = parse_out(op(kind="expense", amount=4300, currency="AED",
                                      from_account="mashreq_personal", category="exp_cafe"))
    run(pipeline.handle_phrase(CHAT, "Поел на 43 дирхама"))
    user = llm_answer["calls"][-1]["user"]
    assert "2026-09-17" in user
    assert "mashreq_personal" in user
    system = llm_answer["calls"][-1]["system"]
    assert "exp_cafe" in system and "{REFERENCE}" not in system
