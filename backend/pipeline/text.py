# -*- coding: utf-8 -*-
"""Фраза → разбор ИИ → запись в ядро → карточка (ТЗ 5.1, ARCHITECTURE §6, §7).

Голос попадает сюда же — из voice.py, после расшифровки. Записываем СРАЗУ, вопрос задаём только
когда без ответа операцию записать нельзя.
"""
from __future__ import annotations

import datetime as dt
import logging
from typing import Any

from backend import llm
from backend.bot import cards, keyboards, pending
from backend.bot.cards import Reply
from backend.contracts import LedgerError, OperationPatch, ParsedOperation
from backend.pipeline import ledger_ref

log = logging.getLogger("finuchet.pipeline.text")

# поля ParsedOperation, которые приходят из схемы §6.1 один к одному
_DIRECT_FIELDS = (
    "kind", "amount", "currency", "from_account", "to_account", "category", "income_source",
    "counterparty", "project", "op_date", "amount_to", "currency_to", "no_tax", "freeze",
    "freeze_account", "due_date",
)

ERROR_TEXTS = {
    "tranche_has_releases": "Сначала отмените возврат — он привязан к этому взятию.",
    "counterparty_required": "Скажите, кому именно: без имени долг записать нельзя.",
    "currency_mismatch": "Валюта не сходится со счётом. Скажите счёт и валюту одной фразой.",
    "unknown_account": "Такого счёта нет. Назовите счёт словами: Т-Банк, Сбер, Машрек, наличные.",
    "opening_balance_not_allowed": "На этот счёт начальный остаток не заводится — он считается сам.",
    "account_archived": "Этот счёт в архиве. Назовите другой счёт или верните его из архива.",
    "already_void": "Эта операция уже отменена.",
    "not_voided": "Эта операция не отменена — возвращать нечего.",
    "entry_is_old_version": "Это старая версия операции. Откройте последнюю и правьте её.",
    "rate_unavailable": "Курс сейчас не достать. Назовите курс словами или повторите позже.",
}


def today_dubai() -> str:
    return (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=4)).date().isoformat()


def to_parsed(op: dict[str, Any], *, source: str = "voice", raw_input: str | None = None) -> ParsedOperation:
    """Операция из ответа модели (§6.1) → ParsedOperation (§8.0)."""
    data: dict[str, Any] = {k: op.get(k) for k in _DIRECT_FIELDS}
    if data.get("amount") is None:
        raise ValueError("в разобранной операции нет суммы")
    data["amount"] = int(data["amount"])
    data["no_tax"] = bool(op.get("no_tax"))
    data["freeze"] = bool(op.get("freeze", True))
    if op.get("rate"):
        data["rate_e6"] = int(op["rate"])
        data["rate_source"] = "voice" if op.get("rate_named_by_voice") else None
    data["description"] = op.get("description") or ""
    data["source"] = source
    data["raw_input"] = raw_input
    data["confidence"] = op.get("confidence")
    return ParsedOperation(**data)


def to_patch(op: dict[str, Any], *, raw_input: str | None = None) -> OperationPatch:
    """Операция в режиме правки → OperationPatch: только те поля, что назвали."""
    patch = OperationPatch()
    for field in ("amount", "currency", "kind", "from_account", "to_account", "category",
                  "income_source", "counterparty", "project", "op_date", "amount_to",
                  "currency_to", "due_date", "description"):
        value = op.get(field)
        if value is not None:
            setattr(patch, field, value)
    if op.get("rate"):
        patch.rate_e6 = int(op["rate"])
    if op.get("no_tax"):
        patch.no_tax = True
    if op.get("freeze") is False:
        patch.freeze = False
    if op.get("freeze_account"):
        patch.freeze_account = op["freeze_account"]
    if raw_input:
        patch.raw_input = raw_input
    return patch


async def hints() -> dict[str, Any]:
    try:
        data = await ledger_ref.call("bot_hints")
        if isinstance(data, dict):
            data.setdefault("today", today_dubai())
            return data
    except Exception as exc:
        log.debug("подсказки ядра недоступны: %s", exc)
    return {"today": today_dubai(), "last_account_by_currency": {}, "last_entry": None}


async def quota_ok() -> bool:
    try:
        return bool(await ledger_ref.call("ai_quota_take", 1))
    except Exception as exc:
        log.debug("счётчик вызовов ИИ недоступен (%s) — пропускаем", exc)
        return True


async def handle_phrase(chat_id: int, text: str, *, source: str = "text") -> Reply:
    """Одна фраза Артёма: разобрать, записать, ответить карточкой."""
    text = (text or "").strip()
    if not text:
        return Reply(cards.ERROR_TEXT)

    state = await pending.get(chat_id)
    mode_amend = bool(state and state.get("state") == pending.AMEND)
    payload = (state or {}).get("payload") or {}
    if state and state.get("state") == pending.CLARIFY and payload.get("text"):
        text = f"{payload['text']} {text}".strip()   # ответ на уточнение клеится с исходной фразой
    if state:
        await pending.clear(chat_id)

    if not await quota_ok():
        return Reply(cards.QUOTA_TEXT)

    hint = await hints()
    if mode_amend:
        hint = dict(hint)
        hint["mode"] = "amend"
        if state.get("entry_id"):
            last = dict(hint.get("last_entry") or {})
            last["id"] = state["entry_id"]
            hint["last_entry"] = last

    try:
        data = await llm.parse_phrase(text, today=hint["today"], reference=llm.reference_text(), hints=hint)
    except Exception as exc:
        log.warning("разбор фразы не удался: %s", exc)
        return Reply(cards.ERROR_TEXT)

    if data.get("needs_clarification"):
        question = data.get("clarification_question") or "Сколько и в какой валюте?"
        await pending.set_state(chat_id, pending.CLARIFY, None, {"text": text})
        return Reply(cards.plain_tg(question), keyboards.clarify_buttons())

    operations = data.get("operations") or []
    if not operations:
        return Reply(cards.ERROR_TEXT)

    if mode_amend or data.get("mode") == "amend":
        target = _amend_target(operations[0], state, hint)
        if target is None:
            return Reply("Не понял, какую операцию править. Нажмите «Поправить» под нужной карточкой.")
        return await _do_amend(target, operations[0], text, source)

    return await _do_post(operations, text, source)


def _amend_target(op: dict[str, Any], state: dict | None, hint: dict) -> int | None:
    if state and state.get("entry_id"):
        return int(state["entry_id"])
    if op.get("target_entry_id"):
        return int(op["target_entry_id"])
    last = hint.get("last_entry") or {}
    return int(last["id"]) if last.get("id") else None


async def _do_amend(entry_id: int, op: dict[str, Any], raw: str, source: str) -> Reply:
    patch = to_patch(op, raw_input=raw)
    try:
        result = await ledger_ref.call("amend_entry", entry_id, patch, actor="bot")
    except LedgerError as exc:
        return Reply(ERROR_TEXTS.get(exc.code, cards.ERROR_TEXT))
    except Exception as exc:
        log.warning("правка не прошла: %s", exc)
        return Reply(cards.ERROR_TEXT)
    changes = _changes_of(result)
    return Reply(cards.card_amended(result, changes), keyboards.entry_buttons(result.get("id")))


def _changes_of(result: dict) -> list[str]:
    versions = result.get("versions") or []
    if versions:
        return list(versions[-1].get("changed") or [])
    return []


async def _do_post(operations: list[dict[str, Any]], raw: str, source: str) -> Reply:
    results: list[dict] = []
    for op in operations:
        try:
            parsed = to_parsed(op, source=source, raw_input=raw)
        except ValueError:
            continue
        try:
            results.append(await ledger_ref.call("post_operation", parsed, actor="bot"))
        except LedgerError as exc:
            log.info("ядро отказалось записывать (%s): %s", exc.code, exc.message)
            if not results:
                return Reply(ERROR_TEXTS.get(exc.code, cards.ERROR_TEXT))
        except Exception as exc:
            log.warning("запись операции не прошла: %s", exc)
            if not results:
                return Reply(cards.ERROR_TEXT)
    if not results:
        return Reply(cards.ERROR_TEXT)
    if len(results) == 1:
        entry_id = results[0].get("id")
        return Reply(cards.card_for_entry(results[0]), keyboards.entry_buttons(entry_id))
    ids = [r.get("id") for r in results if r.get("id") is not None]
    return Reply(cards.card_for_batch(results), keyboards.batch_buttons(ids))
