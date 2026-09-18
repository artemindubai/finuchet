# -*- coding: utf-8 -*-
"""Новые отказы ядра доходят до Артёма карточкой, а не трассировкой (§7.1, грабли 27, 37).

После адверсариальной правки ядро кидает `bad_request` на кривом обмене и `account_archived`
на операции по архивному счёту. Бот обязан напечатать короткий plain text и остаться живым."""
from __future__ import annotations

import asyncio

from conftest import op, parse_out

CHAT = 100000001
MARKUP = ("*", "_", "`", "#")


def run(coro):
    return asyncio.run(coro)


def _reply_for(ledger, llm_answer, error, operation, phrase):
    from backend.pipeline import text as pipeline

    ledger.raise_on_post = error
    llm_answer["data"] = parse_out(operation)
    return run(pipeline.handle_phrase(CHAT, phrase))


def test_bad_exchange_shows_error_card(ledger, llm_answer):
    """«Обменял 10 000 ₽ и получил 0»: ядро отвечает bad_request, бот — карточкой, не падением."""
    from backend.contracts import LedgerError
    from backend.bot import cards

    reply = _reply_for(
        ledger, llm_answer,
        LedgerError("bad_request", "Полученная сумма должна быть больше нуля",
                    {"field": "amount_to"}),
        op(kind="exchange", amount=1_000_000, currency="RUB", amount_to=0, currency_to="USDT"),
        "обменял десять тысяч рублей и получил ноль usdt")

    assert reply.text == cards.ERROR_TEXT
    assert ledger.posted == []
    assert not any(ch in reply.text for ch in MARKUP), reply.text


def test_archived_account_shows_its_own_text(ledger, llm_answer):
    """Архивный счёт: у кода есть свой человеческий текст, а не общее «не получилось»."""
    from backend.contracts import LedgerError
    from backend.pipeline import text as pipeline

    reply = _reply_for(
        ledger, llm_answer,
        LedgerError("account_archived", "Счёт Сбер в архиве", {"account": "sber"}),
        op(kind="expense", amount=100_000, currency="RUB", from_account="sber",
           category="exp_cafe"),
        "потратил тысячу рублей со сбера")

    assert reply.text == pipeline.ERROR_TEXTS["account_archived"]
    assert "архив" in reply.text.lower()
    assert ledger.posted == []
    assert not any(ch in reply.text for ch in MARKUP), reply.text


def test_error_card_has_no_traceback_words(ledger, llm_answer):
    """Ни кода ошибки, ни имён классов в тексте для человека."""
    from backend.contracts import LedgerError

    reply = _reply_for(
        ledger, llm_answer,
        LedgerError("bad_request", "Сумма указывается в целых минорных единицах (копейки, филсы)",
                    {"field": "amount"}),
        op(kind="expense", amount=4_300, currency="AED", category="exp_cafe"),
        "кофе на сорок три дирхама")

    for forbidden in ("LedgerError", "bad_request", "Traceback", "details"):
        assert forbidden not in reply.text, reply.text


def test_button_error_is_a_card_too(ledger):
    """Кнопка «Отменить» по операции с живым возвратом: карточка отказа, обработчик жив."""
    from backend.contracts import LedgerError
    from backend.pipeline import apply as apply_pipeline
    from backend.pipeline import text as pipeline

    def boom(entry_id, *, actor="bot"):
        raise LedgerError("tranche_has_releases", "сначала отмените возврат", {})

    ledger.void_entry = boom
    reply = run(apply_pipeline.handle_callback(CHAT, "f:u:431"))
    assert reply.text == pipeline.ERROR_TEXTS["tranche_has_releases"]
