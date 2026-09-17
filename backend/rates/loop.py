# -*- coding: utf-8 -*-
"""Фоновое обновление курсов (ARCHITECTURE §1.1): раз в RATE_REFRESH_SEC, падение не роняет сервис."""
from __future__ import annotations

import asyncio
import logging

from backend import db
from backend.rates import provider

log = logging.getLogger("finuchet.rates.loop")


def refresh_once() -> dict:
    return provider.refresh_all(conn=db.get_conn())


async def rates_loop() -> None:
    while True:
        try:
            quotes = await asyncio.to_thread(refresh_once)
            if quotes:
                log.info("курсы обновлены: %s",
                         ", ".join(f"{pair} {quote.rate_e6 / 1_000_000:.4f} ({quote.source})"
                                   for pair, quote in sorted(quotes.items())))
            else:
                log.warning("курсы не обновились: источники молчат")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.error("цикл курсов: %s", exc)
        await asyncio.sleep(provider.refresh_interval_sec())
