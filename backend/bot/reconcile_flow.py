# -*- coding: utf-8 -*-
"""Карточки сверки скрина и выписки (ARCHITECTURE §7.4).

Порядок строгий: сначала «Занести новые», и только потом «Выровнять» — расхождение остатка на
момент разбора и есть ещё не занесённые операции (§4.5 п.6).
"""
from __future__ import annotations

from typing import Any

from backend.bot import cards, keyboards
from backend.bot.cards import Reply, format_amount, short_date


def replies_for_batch(result: dict[str, Any], *, account_name: str = "") -> list[Reply]:
    batch_id = result.get("batch_id") or ""
    matched = result.get("matched") or []
    fresh = result.get("new") or []
    ambiguous = result.get("ambiguous") or []
    check = result.get("balance_check") or {}
    total = len(matched) + len(fresh) + len(ambiguous)

    head = [f"Скрин: {account_name}, {total} {_plural_ops(total)}"
            + (f", остаток {format_amount(check.get('bank'))}" if check.get("bank") else "")]
    head.append(f"Совпало с учётом: {len(matched)}")
    head.append(f"Новых: {len(fresh)}")
    if ambiguous:
        head.append(f"Спорных: {len(ambiguous)}")
    diff_line = _diff_line(check)
    if diff_line:
        head.append(diff_line)

    replies = [Reply(cards.plain_tg("\n".join(head)), keyboards.reconcile_batch_buttons(batch_id))]
    for item in ambiguous:
        replies.append(_ambiguous_reply(item, account_name))
    return replies


def _ambiguous_reply(item: dict[str, Any], account_name: str) -> Reply:
    lines = [
        ", ".join(x for x in (
            short_date(item.get("op_date")),
            format_amount(_abs_money(item.get("amount"))),
            (item.get("raw_text") or "").strip(),
        ) if x)
    ]
    candidate = (item.get("candidates") or [{}])[0]
    hint = candidate.get("title") or candidate.get("why") or ""
    if hint:
        lines.append(f"Похоже на уже занесённую: {hint}")
    lines.append("Это она или новая?")
    return Reply(cards.plain_tg("\n".join(lines)), keyboards.ambiguous_buttons(item.get("id")))


def reply_for_applied(result: dict[str, Any], batch_id: str) -> Reply:
    """Итог после разбора пачки: сколько занесли и сходится ли остаток."""
    entered = result.get("entered")
    if entered is None:
        entered = len(result.get("created") or [])
    skipped = result.get("skipped")
    if skipped is None:
        skipped = len(result.get("merged") or []) + len(result.get("skipped_ids") or [])
    check = result.get("balance_check") or {}
    line = f"Занесено {entered}, пропущено {skipped}."
    diff_line = _diff_line(check, short=True)
    if diff_line:
        line += " " + diff_line
    buttons = []
    diff = (check.get("diff") or {}).get("amount")
    if diff:
        buttons = keyboards.align_buttons(batch_id)
    return Reply(cards.plain_tg(line), buttons)


def _diff_line(check: dict[str, Any], *, short: bool = False) -> str:
    if not check.get("bank") or not check.get("ledger"):
        return ""
    diff = check.get("diff") or {}
    amount = int(diff.get("amount") or 0)
    head = f"В учёте {format_amount(check['ledger'])}, в банке {format_amount(check['bank'])}"
    if amount == 0:
        return head + " — сходится."
    shown = {"amount": abs(amount), "currency": diff.get("currency", "RUB")}
    return head + f" — расхождение {format_amount(shown)}"


def _abs_money(money: Any) -> dict[str, Any] | None:
    if not money:
        return None
    return {"amount": abs(int(money.get("amount", 0))), "currency": money.get("currency", "RUB")}


def _plural_ops(n: int) -> str:
    if n % 10 == 1 and n % 100 != 11:
        return "операция"
    if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14):
        return "операции"
    return "операций"
