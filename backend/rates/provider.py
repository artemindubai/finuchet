# -*- coding: utf-8 -*-
"""Поставщик курсов: Bybit P2P → open.er-api.com → cbr-xml-daily.ru → кэш (ARCHITECTURE §8.2).

История (`rate_history`) не перетирается: только по ней можно посчитать баланс на прошлую дату
так же, как его видел экран тогда (грабля 14 журнала)."""
from __future__ import annotations

import logging
import os
import sqlite3

from backend import db, money, settings_store
from backend.contracts import LedgerError, RateQuote
from backend.rates import bybit, fallback
from backend.tz import end_of_day_utc, iso_utc, utc_now

log = logging.getLogger("finuchet.rates")

PAIRS = ("AED/RUB", "USD/RUB", "USDT/RUB", "USDT/AED")
USD_AED_MIN_E6 = 3_600_000     # дирхам жёстко привязан к доллару (3,6725)
USD_AED_MAX_E6 = 3_750_000
DEFAULT_MAX_AGE = 900


def _conn(conn: sqlite3.Connection | None = None) -> sqlite3.Connection:
    return conn or db.get_conn()


def markup_e6(conn: sqlite3.Connection | None = None) -> int:
    value = settings_store.get("rate_markup_rub_per_aed_e6", 2_000_000, conn=_conn(conn))
    try:
        return int(value)
    except (TypeError, ValueError):
        return 2_000_000


def store(pair: str, rate_e6: int, source: str, *, at: int | None = None,
          raw: str | None = None, conn: sqlite3.Connection | None = None) -> None:
    conn = _conn(conn)
    conn.execute(
        "INSERT INTO rate_history (pair, at, rate_e6, source, raw) VALUES (?,?,?,?,?)"
        " ON CONFLICT(pair, at) DO UPDATE SET rate_e6 = excluded.rate_e6, source = excluded.source",
        (pair, int(at or utc_now()), int(rate_e6), source, (raw or "")[:500] or None),
    )


def cached(pair: str, conn: sqlite3.Connection | None = None) -> sqlite3.Row | None:
    return _conn(conn).execute("SELECT * FROM rate_cache WHERE pair = ?", (pair,)).fetchone()


def _quote(row: sqlite3.Row, *, stale: bool) -> RateQuote:
    return RateQuote(pair=row["pair"], rate_e6=int(row["rate_e6"]), source=row["source"],
                     at=int(row["at"]), stale=stale)


def refresh_all(*, conn: sqlite3.Connection | None = None) -> dict[str, RateQuote]:
    """Опрашивает источники по порядку и пишет всё, что получилось, в историю."""
    conn = _conn(conn)
    now = utc_now()
    out: dict[str, RateQuote] = {}

    usdt_rub = bybit.usdt_rub_e6()
    usdt_aed = bybit.usdt_aed_e6()
    if usdt_aed and not (USD_AED_MIN_E6 <= usdt_aed <= USD_AED_MAX_E6):
        log.warning("bybit USDT/AED вне коридора 3,60–3,75: %s — источник считаем сломанным", usdt_aed)
        usdt_aed = None

    legs = {}
    if usdt_rub:
        store("USDT/RUB", usdt_rub, "bybit_p2p", at=now, conn=conn)
        out["USDT/RUB"] = RateQuote("USDT/RUB", usdt_rub, "bybit_p2p", now)
        legs["usdt_rub_e6"] = usdt_rub
    if usdt_aed:
        store("USDT/AED", usdt_aed, "bybit_p2p", at=now, conn=conn)
        out["USDT/AED"] = RateQuote("USDT/AED", usdt_aed, "bybit_p2p", now)
        legs["usdt_aed_e6"] = usdt_aed
    if usdt_rub and usdt_aed:
        aed_rub = money.round_half_up(usdt_rub * 1_000_000, usdt_aed)
        store("AED/RUB", aed_rub, "bybit_p2p", at=now, conn=conn)
        out["AED/RUB"] = RateQuote("AED/RUB", aed_rub, "bybit_p2p", now, legs=dict(legs))

    for source in (fallback.er_api, fallback.cbr):
        if "AED/RUB" in out and "USD/RUB" in out:
            break
        data = source()
        if not data:
            continue
        usd_aed = data.get("aed_per_usd_e6")
        if usd_aed and not (USD_AED_MIN_E6 <= usd_aed <= USD_AED_MAX_E6):
            log.warning("%s: USD/AED вне коридора, пропускаем источник", data.get("source"))
            continue
        name = data["source"]
        if "USD/RUB" not in out:
            store("USD/RUB", data["rub_per_usd_e6"], name, at=now, conn=conn)
            out["USD/RUB"] = RateQuote("USD/RUB", data["rub_per_usd_e6"], name, now)
        if "AED/RUB" not in out:
            rate = data["rub_per_aed_e6"] + markup_e6(conn)
            store("AED/RUB", rate, f"{name}+markup", at=now, conn=conn)
            out["AED/RUB"] = RateQuote("AED/RUB", rate, f"{name}+markup", now,
                                       markup_e6=markup_e6(conn))
        if "USDT/RUB" not in out:                 # USDT держится доллара
            store("USDT/RUB", data["rub_per_usd_e6"], name, at=now, conn=conn)
            out["USDT/RUB"] = RateQuote("USDT/RUB", data["rub_per_usd_e6"], name, now)
    return out


def get(pair: str, *, amount_minor: int | None = None, max_age_sec: int = DEFAULT_MAX_AGE,
        allow_network: bool = True, conn: sqlite3.Connection | None = None) -> RateQuote:
    conn = _conn(conn)
    row = cached(pair, conn)
    now = utc_now()
    if row and now - int(row["at"]) <= max_age_sec:
        return _quote(row, stale=False)
    if allow_network:
        try:
            fresh = refresh_all(conn=conn)
        except Exception as exc:                  # сеть не обязана работать
            log.warning("обновление курсов не удалось: %s", exc)
            fresh = {}
        if pair in fresh:
            return fresh[pair]
        row = cached(pair, conn)
    if row:
        return _quote(row, stale=True)
    raise LedgerError("rate_unavailable", "Курс недоступен: источники молчат, истории нет",
                      {"pair": pair})


def get_many(pairs: list[str], *, conn: sqlite3.Connection | None = None) -> dict[str, RateQuote]:
    conn = _conn(conn)
    out: dict[str, RateQuote] = {}
    for pair in pairs:
        try:
            out[pair] = get(pair, conn=conn)
        except LedgerError:
            continue
    return out


def at_date(pair: str, date: str, *, conn: sqlite3.Connection | None = None) -> RateQuote:
    """Последний курс на конец дубайской даты; истории нет — текущий со stale=True."""
    conn = _conn(conn)
    bound = end_of_day_utc(date)
    row = conn.execute(
        "SELECT pair, rate_e6, source, at FROM rate_history WHERE pair = ? AND at <= ?"
        " ORDER BY at DESC LIMIT 1", (pair, bound)).fetchone()
    if row:
        return _quote(row, stale=False)
    row = conn.execute(
        "SELECT pair, rate_e6, source, at FROM rate_history WHERE pair = ?"
        " ORDER BY at ASC LIMIT 1", (pair,)).fetchone()
    if row:
        return _quote(row, stale=True)
    quote = get(pair, conn=conn)
    quote.stale = True
    return quote


def _pair_rate(pair: str, conn: sqlite3.Connection, *, allow_network: bool) -> RateQuote | None:
    if not allow_network:
        row = cached(pair, conn)
        if row is None:
            return None
        return _quote(row, stale=utc_now() - int(row["at"]) > DEFAULT_MAX_AGE)
    try:
        return get(pair, conn=conn)
    except LedgerError:
        return None


def snapshot(*, conn: sqlite3.Connection | None = None, allow_network: bool = True) -> dict:
    """Снимок курсов в шапку операции (§3.1). Пишется в КАЖДУЮ операцию, включая рублёвую."""
    conn = _conn(conn)
    have_all = all(cached(pair, conn) for pair in ("AED/RUB", "USD/RUB", "USDT/RUB"))
    net = allow_network and not have_all
    aed = _pair_rate("AED/RUB", conn, allow_network=net)
    usd = _pair_rate("USD/RUB", conn, allow_network=net)
    usdt = _pair_rate("USDT/RUB", conn, allow_network=net)
    usdt_aed = _pair_rate("USDT/AED", conn, allow_network=False)
    at = max([q.at for q in (aed, usd, usdt) if q] or [utc_now()])
    out = {
        "at": iso_utc(at),
        "source": (aed or usd or usdt).source if (aed or usd or usdt) else "none",
        "rub_per_aed_e6": aed.rate_e6 if aed else None,
        "rub_per_usd_e6": usd.rate_e6 if usd else None,
        "rub_per_usdt_e6": usdt.rate_e6 if usdt else None,
        "markup_rub_per_aed_e6": markup_e6(conn),
        "legs": {},
    }
    if usdt:
        out["legs"]["usdt_rub_e6"] = usdt.rate_e6
    if usdt_aed:
        out["legs"]["usdt_aed_e6"] = usdt_aed.rate_e6
    return out


def snapshot_at_date(date: str, *, conn: sqlite3.Connection | None = None) -> dict:
    """Снимок курсов на конец указанной даты — для листа «Баланс на дату» и отчётов за период."""
    conn = _conn(conn)
    out = {"at": None, "source": "history", "markup_rub_per_aed_e6": markup_e6(conn), "legs": {}}
    stamps = []
    for pair, key in (("AED/RUB", "rub_per_aed_e6"), ("USD/RUB", "rub_per_usd_e6"),
                      ("USDT/RUB", "rub_per_usdt_e6")):
        try:
            quote = at_date(pair, date, conn=conn)
        except LedgerError:
            out[key] = None
            continue
        out[key] = quote.rate_e6
        stamps.append(quote.at)
        out["source"] = quote.source
    out["at"] = iso_utc(max(stamps)) if stamps else iso_utc()
    return out


def convert(amount: int, src: str, dst: str, *, snapshot: dict | None = None,
            conn: sqlite3.Connection | None = None) -> int:
    if src == dst:
        return int(amount)
    snap = snapshot if snapshot is not None else globals()["snapshot"](conn=conn)
    try:
        return money.convert(amount, src, dst, snapshot=snap)
    except ValueError as exc:
        raise LedgerError("rate_unavailable", "Курс недоступен: пересчитать нечем",
                          {"src": src, "dst": dst, "reason": str(exc)}) from exc


def refresh_interval_sec() -> int:
    try:
        return int(os.environ.get("RATE_REFRESH_SEC", "900"))
    except ValueError:
        return 900
