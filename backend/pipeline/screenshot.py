# -*- coding: utf-8 -*-
"""Скриншот банка → зрение ИИ → сверка с учётом (ТЗ 5.2, ARCHITECTURE §4.5, §7.4)."""
from __future__ import annotations

import logging
from typing import Any

from backend import llm
from backend.bot import cards, pending, reconcile_flow
from backend.bot.cards import Reply
from backend.contracts import LedgerError, ScreenBatch, ScreenRow
from backend.pipeline import ledger_ref, text as text_pipeline

log = logging.getLogger("finuchet.pipeline.screenshot")

ACCOUNT_QUESTION = "С какого счёта скрин? Напишите: Т-Банк, Сбер, Машрек, наличные или Bybit."

# слова Артёма → slug счёта; тем же словарём разбирается ответ на вопрос выше
ACCOUNT_WORDS = {
    "тбанк": "tbank", "т-банк": "tbank", "тинькофф": "tbank", "тинёк": "tbank", "тиньк": "tbank",
    "сбер": "sber", "сбербанк": "sber", "кредитка": "sber_credit",
    "машрек": "mashreq_personal", "mashreq": "mashreq_personal", "эмиратский": "mashreq_personal",
    "семейный": "mashreq_family", "bybit": "bybit", "байбит": "bybit", "биржа": "bybit",
    "наличные": "cash_aed", "наличка": "cash_aed",
}


def account_from_words(text: str) -> str | None:
    low = (text or "").strip().lower()
    for word, slug in ACCOUNT_WORDS.items():
        if word in low:
            return slug
    return None


async def handle_screenshot(
    chat_id: int,
    image: bytes,
    media_type: str = "image/jpeg",
    *,
    account_hint: str | None = None,
) -> list[Reply]:
    if not await text_pipeline.quota_ok():
        return [Reply(cards.QUOTA_TEXT)]
    try:
        parsed = await llm.parse_screenshot(
            image, media_type, reference=llm.reference_text(),
            hint=f"Счёт, скорее всего, {account_hint}." if account_hint else "",
        )
    except Exception as exc:
        log.warning("скрин не разобрался: %s", exc)
        return [Reply("Не разобрал скрин. Пришлите картинку целиком, без обрезки.")]
    return await handle_parsed(chat_id, parsed, source="screenshot", account_hint=account_hint)


async def handle_parsed(
    chat_id: int,
    parsed: dict[str, Any],
    *,
    source: str = "screenshot",
    account_hint: str | None = None,
) -> list[Reply]:
    """Разобранные строки → сверка в ядре → карточки."""
    account = account_hint or parsed.get("account_guess")
    if not account:
        await pending.set_state(chat_id, pending.RECONCILE, None, {"parsed": parsed, "source": source})
        return [Reply(ACCOUNT_QUESTION)]
    rows = [
        ScreenRow(
            amount=int(r["amount"]),
            currency=r.get("currency") or parsed.get("currency") or "RUB",
            op_date=r.get("op_date"),
            raw_text=r.get("raw_text") or "",
            suggested_category=r.get("suggested_category"),
            suggested_kind=r.get("suggested_kind"),
        )
        for r in parsed.get("rows") or []
    ]
    if not rows:
        return [Reply("На скрине не видно операций. Пришлите список операций целиком.")]
    batch = ScreenBatch(
        account=account,
        rows=rows,
        balance=parsed.get("balance"),
        currency=parsed.get("currency"),
        source=source,
        period=parsed.get("statement_period"),
    )
    try:
        result = await ledger_ref.call("reconcile", batch)
    except LedgerError as exc:
        return [Reply(text_pipeline.ERROR_TEXTS.get(exc.code, cards.ERROR_TEXT))]
    except Exception as exc:
        log.warning("сверка не прошла: %s", exc)
        return [Reply(cards.ERROR_TEXT)]
    return reconcile_flow.replies_for_batch(result, account_name=_account_name(result, account))


def _account_name(result: dict, fallback: str) -> str:
    return result.get("account_name") or fallback
