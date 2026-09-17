# -*- coding: utf-8 -*-
"""Общие фикстуры тестов ядра: временная БД, зафиксированные курсы, помощники записи операций."""
from __future__ import annotations

import os

import pytest

RATES = {
    "AED/RUB": 23_450_000,
    "USD/RUB": 84_173_200,
    "USDT/RUB": 97_150_000,
    "USDT/AED": 3_675_000,
}

OWNER = "100000001"


@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    """Каждому тесту — своя база с прогнанным seed'ом и зафиксированными курсами."""
    monkeypatch.setenv("DB_PATH", str(tmp_path / "finuchet.db"))
    monkeypatch.setenv("BACKUP_DIR", str(tmp_path / "backups"))
    monkeypatch.setenv("TMP_DIR", str(tmp_path / "tmp"))
    monkeypatch.setenv("OWNER_TG_ID", OWNER)
    monkeypatch.setenv("DEV_USER", OWNER)
    monkeypatch.setenv("BOT_TOKEN", "test-token")
    monkeypatch.setenv("NO_BOT", "1")

    from backend import db
    db.close_conn()
    db.init()
    seed_rates()
    yield
    db.close_conn()


def seed_rates(at: int | None = None) -> None:
    from backend import db, rates
    from backend.tz import utc_now
    conn = db.get_conn()
    stamp = at or utc_now()
    for pair, rate in RATES.items():
        rates.provider.store(pair, rate, "test", at=stamp, conn=conn)


@pytest.fixture
def ledger():
    from backend import ledger as module
    return module


@pytest.fixture
def client(monkeypatch):
    """HTTP-клиент без поднятия бота; авторизация — заголовком X-Dev-User.

    Фоновый цикл курсов подменяется заглушкой: тесты не ходят в интернет."""
    import asyncio

    from fastapi.testclient import TestClient

    from backend import app as app_module

    async def no_rates():
        await asyncio.sleep(3600)

    monkeypatch.setattr(app_module, "rates_loop", no_rates)
    with TestClient(app_module.app, headers={"X-Dev-User": OWNER}) as test_client:
        yield test_client


def op(**kwargs):
    from backend.contracts import ParsedOperation
    kwargs.setdefault("source", "manual")
    return ParsedOperation(**kwargs)


def post(**kwargs) -> dict:
    from backend import ledger
    return ledger.post_operation(op(**kwargs), actor="test")


def opening(*items) -> dict:
    """opening('tbank', 13200000, 'RUB') — начальные остатки одной пачкой."""
    from backend import ledger
    from backend.contracts import OpeningBalanceItem
    return ledger.post_opening_balances(
        [OpeningBalanceItem(account=a, amount=amount, currency=currency)
         for a, amount, currency in items], actor="test")


def balance(slug: str, currency: str) -> int:
    from backend import db
    from backend.ledger.balances import account_balance
    from backend.ledger.common import resolve_account
    conn = db.get_conn()
    row = resolve_account(conn, slug)
    return account_balance(conn, int(row["id"]), currency)


def base_state() -> None:
    """Стартовые остатки, на которых считают почти все сценарии."""
    opening(("tbank", 13_200_000, "RUB"), ("sber", 1_840_000, "RUB"),
            ("cash_rub", 500_000, "RUB"), ("mashreq_personal", 184_250, "AED"),
            ("cash_aed", 32_000, "AED"), ("bybit", 41_025, "USDT"),
            ("mashreq_family", 850_000, "AED"), ("cash_aed_family", 120_000, "AED"))


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)
