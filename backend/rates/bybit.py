# -*- coding: utf-8 -*-
"""Bybit P2P — рыночная связка через USDT (ARCHITECTURE §8.2, recon 03 §2.1).

Эндпоинт недокументированный, поэтому: обязательный параметр amount для рубля (без него в топе
мошеннические объявления), медиана первых пяти отфильтрованных цен, отсев по тексту объявления."""
from __future__ import annotations

import logging
import os
from decimal import Decimal, InvalidOperation

import httpx

log = logging.getLogger("finuchet.rates.bybit")

URL = "https://api2.bybit.com/fiat/otc/item/online"
BAD_WORDS = ("схема", "арбитраж", "обучение", "scheme", "курс обучения")
HEADERS = {
    "Content-Type": "application/json",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Accept": "application/json",
}


def _to_e6(price: str) -> int | None:
    try:
        return int((Decimal(str(price)) * 1_000_000).quantize(Decimal(1)))
    except (InvalidOperation, ValueError, TypeError):
        return None


def _median(values: list[int]) -> int:
    values = sorted(values)
    mid = len(values) // 2
    if len(values) % 2:
        return values[mid]
    return (values[mid - 1] + values[mid]) // 2


def fetch_price_e6(currency_id: str, side: str, *, amount: str | None = None,
                   timeout: float = 12.0) -> int | None:
    """Медиана цен первых пяти живых объявлений. side: '0' — покупка USDT, '1' — продажа."""
    payload = {
        "userId": "", "tokenId": "USDT", "currencyId": currency_id, "payment": [],
        "side": side, "size": "20", "page": "1", "amount": amount or "",
        "authMaker": False, "canTrade": False,
    }
    try:
        with httpx.Client(timeout=timeout, headers=HEADERS) as client:
            response = client.post(URL, json=payload)
            response.raise_for_status()
            data = response.json()
    except Exception as exc:                       # сеть/формат — не роняем сервис
        log.warning("bybit %s/%s недоступен: %s", currency_id, side, exc)
        return None

    items = ((data or {}).get("result") or {}).get("items") or []
    prices: list[int] = []
    for item in items:
        remark = f"{item.get('remark') or ''} {item.get('nickName') or ''}".lower()
        if any(word in remark for word in BAD_WORDS):
            continue
        price = _to_e6(item.get("price"))
        if price:
            prices.append(price)
        if len(prices) >= 5:
            break
    if len(prices) < 3:
        log.warning("bybit %s/%s: слишком мало объявлений (%d)", currency_id, side, len(prices))
        return None
    return _median(prices)


def usdt_rub_e6() -> int | None:
    amount = os.environ.get("BYBIT_AMOUNT_RUB", "40000")
    return fetch_price_e6("RUB", "0", amount=amount)


def usdt_aed_e6() -> int | None:
    return fetch_price_e6("AED", "1")
