# -*- coding: utf-8 -*-
"""Деньги: целые минорные единицы, целочисленное округление, пересчёт по курсу, формат для показа.
Ни одного float в расчётах (ARCHITECTURE §4.4, §5.3)."""
from __future__ import annotations

MINOR = 100                      # у всех четырёх валют два знака
RATE_E6 = 1_000_000
CURRENCIES = ("RUB", "AED", "USDT", "USD")
SYMBOL = {"RUB": "₽", "AED": "AED", "USDT": "USDT", "USD": "$"}
NBSP = " "


def round_half_up(num: int, den: int) -> int:
    """Целочисленное деление с округлением половин от нуля. Симметрично для отрицательных."""
    if den <= 0:
        raise ValueError("den must be > 0")
    if num >= 0:
        return (num + den // 2) // den
    return -((-num + den // 2) // den)


def money(amount: int, currency: str) -> dict:
    return {"amount": int(amount), "currency": currency}


def convert_e6(amount: int, rate_e6: int) -> int:
    """amount в исходной валюте × курс(×1e6) → сумма в целевой валюте."""
    return round_half_up(int(amount) * int(rate_e6), RATE_E6)


def rub_per(currency: str, snapshot: dict) -> int:
    """Сколько рублей за единицу валюты (×1e6) по снимку курсов."""
    if currency == "RUB":
        return RATE_E6
    key = {"AED": "rub_per_aed_e6", "USD": "rub_per_usd_e6", "USDT": "rub_per_usdt_e6"}.get(currency)
    if not key:
        raise ValueError(f"unknown currency {currency}")
    value = snapshot.get(key)
    if not value:
        raise ValueError(f"no rate for {currency} in snapshot")
    return int(value)


def convert(amount: int, src: str, dst: str, *, snapshot: dict | None = None) -> int:
    """Пересчёт между валютами через рубль по снимку курсов (§4.4)."""
    if src == dst:
        return int(amount)
    if snapshot is None:
        raise ValueError("snapshot required")
    src_e6 = rub_per(src, snapshot)
    dst_e6 = rub_per(dst, snapshot)
    if dst == "RUB":
        return round_half_up(int(amount) * src_e6, RATE_E6)
    if src == "RUB":
        return round_half_up(int(amount) * RATE_E6, dst_e6)
    return round_half_up(int(amount) * src_e6, dst_e6)


def fmt_amount(amount: int, currency: str = "RUB") -> str:
    """«1 842,50 AED», «132 000 ₽» — разряды неразрывным пробелом, нулевые копейки скрыты."""
    sign = "-" if amount < 0 else ""
    value = abs(int(amount))
    whole, minor = divmod(value, MINOR)
    groups = f"{whole:,}".replace(",", NBSP)
    text = groups if minor == 0 else f"{groups},{minor:02d}"
    return f"{sign}{text}{NBSP}{SYMBOL.get(currency, currency)}"


def fmt_rate(rate_e6: int) -> str:
    """Курс для текста: 24500000 → «24,50»."""
    value = round_half_up(int(rate_e6), 10_000)   # два знака
    whole, minor = divmod(abs(value), 100)
    text = f"{whole},{minor:02d}"
    return f"-{text}" if rate_e6 < 0 else text


def share_bp(part: int, total: int) -> int:
    """Доля в базисных пунктах, целочисленно."""
    if not total:
        return 0
    return round_half_up(int(part) * 10_000, abs(int(total)))


def spread_shares(parts: list[int], total: int) -> list[int]:
    """Доли в bp так, чтобы сумма была ровно 10000 (разница уходит крупнейшей доле)."""
    if not parts or not total:
        return [0] * len(parts)
    shares = [share_bp(p, total) for p in parts]
    diff = 10_000 - sum(shares)
    if diff and shares:
        biggest = max(range(len(shares)), key=lambda i: parts[i])
        shares[biggest] += diff
    return shares
