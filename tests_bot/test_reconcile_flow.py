# -*- coding: utf-8 -*-
"""Карточки сверки скрина (ARCHITECTURE §7.4) и порядок «сначала занести, потом выровнять»."""
from __future__ import annotations

import asyncio

from backend.bot import reconcile_flow

NBSP = " "


def run(coro):
    return asyncio.run(coro)


def money(amount, currency="RUB"):
    return {"amount": amount, "currency": currency}


BATCH = {
    "batch_id": "scr_20260917_1",
    "matched": [{"id": 1}, {"id": 2}, {"id": 3}],
    "new": [{"id": 4}, {"id": 5}],
    "ambiguous": [],
    "balance_check": {"bank": money(13200000), "ledger": money(13435000), "diff": money(-235000)},
}


def test_screen_card_has_no_align_button():
    replies = reconcile_flow.replies_for_batch(BATCH, account_name="Т-Банк")
    lines = replies[0].text.splitlines()
    assert lines[0] == f"Скрин: Т-Банк, 5 операций, остаток 132{NBSP}000{NBSP}₽"
    assert lines[1] == "Совпало с учётом: 3"
    assert lines[2] == "Новых: 2"
    assert lines[3] == (f"В учёте 134{NBSP}350{NBSP}₽, в банке 132{NBSP}000{NBSP}₽ — "
                        f"расхождение 2{NBSP}350{NBSP}₽")
    labels = [b.label for b in replies[0].buttons]
    assert labels == ["Занести новые", "Разобрать по одной"]
    assert "Выровнять" not in labels          # до заноса выравнивать нечего (§4.5 п.6)


def test_ambiguous_row_asks_question():
    batch = dict(BATCH)
    batch["ambiguous"] = [{
        "id": 11, "op_date": "2026-09-16", "amount": money(-235000), "raw_text": "ЯНДЕКС ЕДА",
        "candidates": [{"entry_id": 412, "score": 100,
                        "title": "16.09 Расход 2 350 ₽ — Продукты, Т-Банк"}],
    }]
    replies = reconcile_flow.replies_for_batch(batch, account_name="Т-Банк")
    lines = replies[1].text.splitlines()
    assert lines[0] == f"16.09, 2{NBSP}350{NBSP}₽, ЯНДЕКС ЕДА"
    assert lines[1] == "Похоже на уже занесённую: 16.09 Расход 2 350 ₽ — Продукты, Т-Банк"
    assert lines[2] == "Это она или новая?"
    assert [b.label for b in replies[1].buttons] == ["Это она", "Новая", "Пропустить"]
    assert [b.data for b in replies[1].buttons] == ["f:s:11", "f:n:11", "f:k:11"]


def test_final_message_shows_align_when_diff_left():
    reply = reconcile_flow.reply_for_applied(
        {"entered": 2, "skipped": 3,
         "balance_check": {"bank": money(12965000), "ledger": money(13200000),
                           "diff": money(235000)}},
        "scr_20260917_1")
    assert reply.text == (f"Занесено 2, пропущено 3. В учёте 132{NBSP}000{NBSP}₽, "
                          f"в банке 129{NBSP}650{NBSP}₽ — расхождение 2{NBSP}350{NBSP}₽")
    assert [b.label for b in reply.buttons] == ["Выровнять"]
    assert reply.buttons[0].data == "f:a:scr_20260917_1"


def test_final_message_without_diff_has_no_button():
    reply = reconcile_flow.reply_for_applied(
        {"entered": 2, "skipped": 3,
         "balance_check": {"bank": money(13200000), "ledger": money(13200000), "diff": money(0)}},
        "scr_20260917_1")
    assert reply.text.endswith("— сходится.")
    assert reply.buttons == []


def test_align_answers_already_aligned(ledger):
    from backend.pipeline import apply as apply_pipeline

    ledger.apply_reconcile = lambda decisions, actor="bot": {
        "created": [], "warnings": [{"code": "already_aligned", "message": "уже сходится"}]}
    reply = run(apply_pipeline.handle_callback(100000001, "f:a:scr_20260917_1"))
    assert reply.text == "Уже сходится, корректировка не нужна."


def test_inbox_decision_goes_to_core(ledger):
    from backend.pipeline import apply as apply_pipeline

    seen = []

    def apply_reconcile(decisions, actor="bot"):
        seen.extend(decisions)
        return {"created": []}

    ledger.apply_reconcile = apply_reconcile
    run(apply_pipeline.handle_callback(100000001, "f:s:11"))
    run(apply_pipeline.handle_callback(100000001, "f:k:12"))
    assert [(d.inbox_id, d.decision) for d in seen] == [(11, "same"), (12, "skip")]
