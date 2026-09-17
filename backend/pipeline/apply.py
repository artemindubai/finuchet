# -*- coding: utf-8 -*-
"""Кнопки под карточками: отменить, поправить, вернуть, решения по сверке (§7.1, §7.4)."""
from __future__ import annotations

import logging
from typing import Any

from backend.bot import cards, keyboards, pending, reconcile_flow
from backend.bot.cards import Reply
from backend.contracts import LedgerError, ReconcileDecision
from backend.pipeline import ledger_ref
from backend.pipeline.text import ERROR_TEXTS

log = logging.getLogger("finuchet.pipeline.apply")


async def handle_callback(chat_id: int, data: str) -> Reply | None:
    """Нажатие кнопки → действие в ядре → новая карточка. None — кнопка не наша."""
    parsed = keyboards.parse_cb(data)
    if not parsed:
        return None
    letter, ident = parsed
    try:
        if letter == "u":
            return await _void(int(ident))
        if letter == "U":
            return await _void_many([int(x) for x in ident.split(",") if x])
        if letter == "r":
            return await _unvoid(int(ident))
        if letter == "e":
            await pending.set_state(chat_id, pending.AMEND, int(ident), {})
            return Reply(cards.AMEND_PROMPT)
        if letter == "c":
            await pending.clear(chat_id)
            return Reply("Отменил вопрос.")
        if letter in ("s", "n", "k"):
            return await _resolve_inbox(letter, int(ident))
        if letter == "N":
            return await _enter_new(ident)
        if letter == "D":
            return await _one_by_one(ident)
        if letter == "a":
            return await _align(ident)
    except LedgerError as exc:
        return Reply(ERROR_TEXTS.get(exc.code, cards.ERROR_TEXT))
    except Exception as exc:
        log.warning("кнопка %s не отработала: %s", data, exc)
        return Reply(cards.ERROR_TEXT)
    return None


async def _void(entry_id: int) -> Reply:
    result = await ledger_ref.call("void_entry", entry_id, actor="bot")
    return Reply(cards.card_voided(result), keyboards.voided_buttons(entry_id))


async def _void_many(entry_ids: list[int]) -> Reply:
    ok = 0
    for entry_id in entry_ids:
        try:
            await ledger_ref.call("void_entry", entry_id, actor="bot")
            ok += 1
        except Exception as exc:
            log.info("операция %s не отменилась: %s", entry_id, exc)
    return Reply(f"Отменено операций: {ok}", keyboards.voided_buttons(entry_ids[-1]) if entry_ids else [])


async def _unvoid(entry_id: int) -> Reply:
    result = await ledger_ref.call("unvoid_entry", entry_id, actor="bot")
    return Reply(cards.card_for_entry(result), keyboards.entry_buttons(entry_id))


async def _resolve_inbox(letter: str, inbox_id: int) -> Reply:
    decision = {"s": "same", "n": "new", "k": "skip"}[letter]
    result = await ledger_ref.call("apply_reconcile", [ReconcileDecision(inbox_id=inbox_id, decision=decision)],
                                   actor="bot")
    created = (result or {}).get("created") or []
    if decision == "new" and created:
        entry = created[0] if isinstance(created[0], dict) else None
        if entry and entry.get("kind"):
            return Reply(cards.card_for_entry(entry), keyboards.entry_buttons(entry.get("id")))
        return Reply("Занёс операцию.")
    return Reply({"same": "Отметил как уже занесённую.", "skip": "Пропустил."}[decision])


async def _enter_new(batch_id: str) -> Reply:
    """«Занести новые»: все строки со статусом new разом, потом итог с пересчитанным расхождением."""
    ids = await _pending_ids(batch_id, "new")
    decisions = [ReconcileDecision(inbox_id=i, decision="new") for i in ids]
    result = await ledger_ref.call("apply_reconcile", decisions, actor="bot") if decisions else {}
    result = dict(result or {})
    result.setdefault("entered", len(decisions))
    return reconcile_flow.reply_for_applied(result, batch_id)


async def _one_by_one(batch_id: str) -> Reply:
    """«Разобрать по одной»: спорные и новые строки идут вопросами."""
    batch = await _batch(batch_id)
    items = [i for i in (batch.get("items") or []) if i.get("status", "pending") == "pending"]
    if not items:
        return Reply("Разбирать нечего: все строки закрыты.")
    item = items[0]
    return reconcile_flow._ambiguous_reply(item, batch.get("account_name") or "")


async def _align(batch_id: str) -> Reply:
    result = await ledger_ref.call("apply_reconcile",
                                   [ReconcileDecision(inbox_id=0, decision="align")], actor="bot")
    warnings = (result or {}).get("warnings") or []
    if any(w.get("code") == "already_aligned" for w in warnings):
        return Reply(cards.ALREADY_ALIGNED_TEXT)
    created = (result or {}).get("created") or []
    if created and isinstance(created[0], dict) and created[0].get("kind"):
        return Reply(cards.card_for_entry(created[0]), keyboards.entry_buttons(created[0].get("id")))
    return Reply("Остаток выровнен.")


async def _batch(batch_id: str) -> dict[str, Any]:
    try:
        data = await ledger_ref.call("inbox_batch", batch_id)
        if data:
            return data
    except Exception:
        pass
    try:
        data = await ledger_ref.call("inbox")
        for batch in (data or {}).get("batches", []):
            if batch.get("batch_id") == batch_id:
                return batch
    except Exception as exc:
        log.debug("пачка сверки не читается: %s", exc)
    return {}


async def _pending_ids(batch_id: str, status: str) -> list[int]:
    batch = await _batch(batch_id)
    return [int(i["id"]) for i in (batch.get("items") or [])
            if i.get("match_status") == status and i.get("status", "pending") == "pending"]
