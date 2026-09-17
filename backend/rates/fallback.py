# -*- coding: utf-8 -*-
"""Запасные источники курса: open.er-api.com и cbr-xml-daily.ru (ARCHITECTURE §8.2).

К обоим применяется надбавка RATE_MARKUP_RUB_PER_AED — это «середина рынка», по которой
дирхамы за рубли не купить. К Bybit надбавка не применяется никогда."""
from __future__ import annotations

import logging
from decimal import Decimal

import httpx

log = logging.getLogger("finuchet.rates.fallback")

ER_API = "https://open.er-api.com/v6/latest/USD"
CBR = "https://www.cbr-xml-daily.ru/daily_json.js"


def _e6(value) -> int:
    return int((Decimal(str(value)) * 1_000_000).quantize(Decimal(1)))


def er_api(timeout: float = 12.0) -> dict | None:
    """{'rub_per_usd_e6', 'rub_per_aed_e6', 'usd_per_aed_e6'} без надбавки."""
    try:
        with httpx.Client(timeout=timeout) as client:
            data = client.get(ER_API).raise_for_status().json()
        rates = data["rates"]
        usd_rub = Decimal(str(rates["RUB"]))          # рублей за доллар
        usd_aed = Decimal(str(rates["AED"]))          # дирхамов за доллар
        if usd_aed <= 0:
            return None
        return {
            "rub_per_usd_e6": _e6(usd_rub),
            "rub_per_aed_e6": _e6(usd_rub / usd_aed),
            "aed_per_usd_e6": _e6(usd_aed),
            "source": "er_api",
        }
    except Exception as exc:
        log.warning("open.er-api.com недоступен: %s", exc)
        return None


def cbr(timeout: float = 12.0) -> dict | None:
    """ЦБ РФ: рубли за доллар и за дирхам (Valute.AED учитывает Nominal)."""
    try:
        with httpx.Client(timeout=timeout) as client:
            data = client.get(CBR).raise_for_status().json()
        usd = data["Valute"]["USD"]
        aed = data["Valute"]["AED"]
        rub_per_usd = Decimal(str(usd["Value"])) / Decimal(str(usd["Nominal"]))
        rub_per_aed = Decimal(str(aed["Value"])) / Decimal(str(aed["Nominal"]))
        if rub_per_aed <= 0:
            return None
        return {
            "rub_per_usd_e6": _e6(rub_per_usd),
            "rub_per_aed_e6": _e6(rub_per_aed),
            "aed_per_usd_e6": _e6(rub_per_usd / rub_per_aed),
            "source": "cbr",
        }
    except Exception as exc:
        log.warning("cbr-xml-daily.ru недоступен: %s", exc)
        return None
