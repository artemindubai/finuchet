# -*- coding: utf-8 -*-
"""Напоминания — единственный случай, когда бот пишет сам (ТЗ 9, 12).

Только сроки, которые назвал сам Артём: платежи календаря с remind_days_before > 0 и долги
с проставленным сроком. Нечего напомнить — бот молчит.
"""
from __future__ import annotations

import datetime as dt
import logging

from backend.bot import cards
from backend.pipeline import ledger_ref

log = logging.getLogger("finuchet.reminders")

HOUR_DUBAI = 9


def reminders_enabled() -> bool:
    import os

    return (os.getenv("REMIND_ENABLED") or "1").strip() not in ("0", "false", "no")


def seconds_until_9am(now: dt.datetime | None = None) -> float:
    """Сколько спать до ближайших 09:00 по Дубаю."""
    tz = dt.timezone(dt.timedelta(hours=4))
    now = (now or dt.datetime.now(dt.timezone.utc)).astimezone(tz)
    target = now.replace(hour=HOUR_DUBAI, minute=0, second=0, microsecond=0)
    if target <= now:
        target += dt.timedelta(days=1)
    return (target - now).total_seconds()


async def build_text(today: str | None = None) -> str | None:
    """Текст напоминания на сегодня или None, если напоминать нечего."""
    tz = dt.timezone(dt.timedelta(hours=4))
    today = today or dt.datetime.now(tz).date().isoformat()
    lines: list[str] = []

    try:
        calendar = await ledger_ref.call("calendar", date_from=today,
                                         date_to=(dt.date.fromisoformat(today) + dt.timedelta(days=14)).isoformat())
        for item in (calendar or {}).get("items", []):
            remind_days = int(item.get("remind_days_before") or 0)
            if remind_days <= 0 or not item.get("active", True):
                continue
            days_left = int(item.get("days_left") or 0)
            if days_left > remind_days:
                continue
            when = "сегодня" if days_left <= 0 else f"через {days_left} дн."
            lines.append(f"{item.get('title')} — {cards.format_amount(item.get('amount'))}, {when}")
    except Exception as exc:
        log.debug("календарь платежей недоступен: %s", exc)

    try:
        debts = await ledger_ref.call("debts") or {}
        for side, prefix in (("i_owe", "Вернуть"), ("owed_to_me", "Должны вернуть")):
            for row in debts.get(side, []):
                due = row.get("due_date")
                if not due or due > today:
                    continue
                amounts = row.get("amounts") or []
                money = cards.format_amount(amounts[0]) if amounts else ""
                lines.append(f"{prefix}: {row.get('name')} {money}, срок {cards.short_date(due)}")
    except Exception as exc:
        log.debug("долги недоступны: %s", exc)

    if not lines:
        return None
    return cards.plain_tg("Сроки на сегодня\n" + "\n".join(lines))
