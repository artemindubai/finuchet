# -*- coding: utf-8 -*-
"""Время. В БД — unix UTC, дата операции — отдельным полем по Дубаю (грабля 6 журнала)."""
from __future__ import annotations

import re
import time
from datetime import datetime, timedelta, timezone

DUBAI = timezone(timedelta(hours=4))

MONTHS = {
    "январ": 1, "феврал": 2, "март": 3, "апрел": 4, "ма": 5, "июн": 6,
    "июл": 7, "август": 8, "сентябр": 9, "октябр": 10, "ноябр": 11, "декабр": 12,
}
WEEKDAYS = {
    "понедельник": 0, "вторник": 1, "сред": 2, "четверг": 3,
    "пятниц": 4, "суббот": 5, "воскресень": 6,
}


def utc_now() -> int:
    return int(time.time())


def iso_utc(ts: int | None = None) -> str:
    ts = utc_now() if ts is None else int(ts)
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def now_dubai() -> datetime:
    return datetime.now(DUBAI)


def today_dubai() -> str:
    return now_dubai().strftime("%Y-%m-%d")


def dubai_date_of(ts: int) -> str:
    return datetime.fromtimestamp(int(ts), DUBAI).strftime("%Y-%m-%d")


def end_of_day_utc(date: str) -> int:
    """Последняя секунда дубайской даты в unix UTC — граница для истории курсов."""
    day = datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=DUBAI)
    return int((day + timedelta(days=1)).timestamp()) - 1


def month_of(date: str) -> str:
    return date[:7]


def month_bounds(month: str) -> tuple[str, str]:
    """'2026-09' → ('2026-09-01', '2026-09-30')."""
    year, mon = int(month[:4]), int(month[5:7])
    first = datetime(year, mon, 1)
    nxt = datetime(year + (mon == 12), 1 if mon == 12 else mon + 1, 1)
    return first.strftime("%Y-%m-%d"), (nxt - timedelta(days=1)).strftime("%Y-%m-%d")


def shift_month(month: str, delta: int) -> str:
    year, mon = int(month[:4]), int(month[5:7])
    total = year * 12 + (mon - 1) + delta
    return f"{total // 12:04d}-{total % 12 + 1:02d}"


def days_in_month(year: int, month: int) -> int:
    nxt = datetime(year + (month == 12), 1 if month == 12 else month + 1, 1)
    return (nxt - datetime(year, month, 1)).days


def add_days(date: str, days: int) -> str:
    return (datetime.strptime(date, "%Y-%m-%d") + timedelta(days=days)).strftime("%Y-%m-%d")


def days_between(a: str, b: str) -> int:
    """b − a в днях."""
    return (datetime.strptime(b, "%Y-%m-%d") - datetime.strptime(a, "%Y-%m-%d")).days


def parse_date_phrase(text: str, *, today: str | None = None) -> str | None:
    """«вчера», «позавчера», «в понедельник», «12-го», «12 сентября» → YYYY-MM-DD.
    Ничего не распознали — None (вызывающий подставит сегодня)."""
    if not text:
        return None
    base = datetime.strptime(today or today_dubai(), "%Y-%m-%d")
    low = text.lower()

    exact = re.search(r"(20\d{2})-(\d{2})-(\d{2})", low)
    if exact:
        return exact.group(0)
    if "позавчера" in low:
        return (base - timedelta(days=2)).strftime("%Y-%m-%d")
    if "вчера" in low:
        return (base - timedelta(days=1)).strftime("%Y-%m-%d")
    if "сегодня" in low:
        return base.strftime("%Y-%m-%d")

    day_month = re.search(r"(\d{1,2})\s+([а-яё]+)", low)
    if day_month:
        stem = day_month.group(2)
        for key, num in MONTHS.items():
            if stem.startswith(key):
                day = int(day_month.group(1))
                year = base.year - 1 if num > base.month + 6 else base.year
                try:
                    return datetime(year, num, day).strftime("%Y-%m-%d")
                except ValueError:
                    return None

    ordinal = re.search(r"(\d{1,2})[-\s]?(?:го|ое|ого)\b", low)
    if ordinal:
        day = int(ordinal.group(1))
        year, month = base.year, base.month
        if day > base.day:                       # «12-го» в будущем этого месяца = прошлый месяц
            month -= 1
            if month == 0:
                month, year = 12, year - 1
        try:
            return datetime(year, month, day).strftime("%Y-%m-%d")
        except ValueError:
            return None

    for name, idx in WEEKDAYS.items():
        if name in low:
            back = (base.weekday() - idx) % 7 or 7
            return (base - timedelta(days=back)).strftime("%Y-%m-%d")
    return None


def human_day(date: str, *, today: str | None = None) -> str:
    """Заголовок дня в ленте: «Сегодня», «Вчера», «16 сентября»."""
    today = today or today_dubai()
    if date == today:
        return "Сегодня"
    if date == add_days(today, -1):
        return "Вчера"
    names = ["января", "февраля", "марта", "апреля", "мая", "июня",
             "июля", "августа", "сентября", "октября", "ноября", "декабря"]
    day = datetime.strptime(date, "%Y-%m-%d")
    text = f"{day.day} {names[day.month - 1]}"
    return text if day.year == datetime.strptime(today, "%Y-%m-%d").year else f"{text} {day.year}"


def human_date(date: str) -> str:
    """'2026-09-17' → '17.09.2026' для готовых серверных строк."""
    return datetime.strptime(date, "%Y-%m-%d").strftime("%d.%m.%Y")
