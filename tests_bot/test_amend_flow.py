# -*- coding: utf-8 -*-
"""Кнопка «Поправить» и фраза-правка (ARCHITECTURE §7.3)."""
from __future__ import annotations

import asyncio

from conftest import op, parse_out

CHAT = 100000001


def run(coro):
    return asyncio.run(coro)


def test_correction_phrase_patches_entry(ledger, llm_answer):
    from backend.pipeline import apply as apply_pipeline
    from backend.pipeline import text as pipeline

    reply = run(apply_pipeline.handle_callback(CHAT, "f:e:431"))
    assert "Что поправить?" in reply.text
    assert ledger.pending[CHAT]["state"] == "amend"
    assert ledger.pending[CHAT]["entry_id"] == 431

    llm_answer["data"] = parse_out(op(kind="expense", amount=3400, currency="AED"), mode="amend")
    reply = run(pipeline.handle_phrase(CHAT, "не 43, а 34"))

    assert ledger.posted == []
    assert len(ledger.amended) == 1
    entry_id, patch = ledger.amended[0]
    assert entry_id == 431
    assert patch.amount == 3400
    assert patch.from_account is None       # менялась только сумма
    assert "Поправлено: сумма 43 → 34 AED" in reply.text
    assert CHAT not in ledger.pending       # состояние снято


def test_amend_account_only(ledger, llm_answer):
    from backend.pipeline import text as pipeline

    ledger.pending_set(CHAT, "amend", 412, {})
    llm_answer["data"] = parse_out(op(kind="expense", from_account="cash_aed"), mode="amend")
    run(pipeline.handle_phrase(CHAT, "это с налички"))
    entry_id, patch = ledger.amended[0]
    assert entry_id == 412
    assert patch.from_account == "cash_aed"
    assert patch.amount is None


def test_amend_without_button_uses_last_entry(ledger, llm_answer):
    """Модель сама решила, что это правка: цель — последняя операция из подсказок ядра."""
    from backend.pipeline import text as pipeline

    llm_answer["data"] = parse_out(op(kind="expense", category="exp_gifts"), mode="amend")
    run(pipeline.handle_phrase(CHAT, "это были подарки, не еда"))
    entry_id, patch = ledger.amended[0]
    assert entry_id == 431
    assert patch.category == "exp_gifts"


def test_void_and_unvoid(ledger):
    from backend.pipeline import apply as apply_pipeline

    reply = run(apply_pipeline.handle_callback(CHAT, "f:u:431"))
    assert ledger.voided == [431]
    assert "Операция отменена" in reply.text
    assert [b.label for b in reply.buttons] == ["Вернуть", "Открыть"]

    reply = run(apply_pipeline.handle_callback(CHAT, "f:r:431"))
    assert ledger.unvoided == [431]
    assert [b.label for b in reply.buttons] == ["Отменить", "Поправить", "Открыть"]


def test_ledger_error_becomes_human_text(ledger, llm_answer):
    from backend.contracts import LedgerError
    from backend.pipeline import text as pipeline

    ledger.raise_on_post = LedgerError("counterparty_required", "нужен контрагент")
    llm_answer["data"] = parse_out(op(kind="loan_given", amount=30000, currency="AED"))
    reply = run(pipeline.handle_phrase(CHAT, "дал в долг 300 дирхам"))
    assert reply.text == pipeline.ERROR_TEXTS["counterparty_required"]
    assert "LedgerError" not in reply.text and "code" not in reply.text
