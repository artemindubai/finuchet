# -*- coding: utf-8 -*-
"""Запуск бота: кнопка меню, вотчдог поллинга и честный флаг в /healthz (§1.2, §11)."""
from __future__ import annotations

import asyncio

import pytest

from backend.bot import runner


def run(coro):
    return asyncio.run(coro)


class FakeBot:
    def __init__(self) -> None:
        self.menu_calls: list[str] = []

    async def set_chat_menu_button(self, menu_button=None):
        self.menu_calls.append(getattr(getattr(menu_button, "web_app", None), "url", ""))
        return True


class FakeDispatcher:
    """Поллинг, который падает заданное число раз, а потом живёт."""

    def __init__(self, fails: int) -> None:
        self.fails = fails
        self.starts = 0

    async def start_polling(self, bot, **kwargs):
        self.starts += 1
        assert kwargs.get("drop_pending_updates") is True   # грабля 7: старые апдейты не переигрываем
        if self.starts <= self.fails:
            raise RuntimeError("Telegram server says - Unauthorized")
        await asyncio.sleep(3600)


@pytest.fixture
def fake(monkeypatch):
    bot = FakeBot()
    dispatcher = FakeDispatcher(fails=2)
    monkeypatch.setattr(runner, "get_bot", lambda: bot)
    monkeypatch.setattr(runner, "get_dispatcher", lambda: dispatcher)
    monkeypatch.setattr(runner, "RESTART_SLEEP_SEC", 0)
    monkeypatch.setattr(runner, "_polling_ok", False)
    monkeypatch.setenv("BOT_TOKEN", "123:abc")
    monkeypatch.setenv("PUBLIC_URL", "https://example.invalid")
    monkeypatch.delenv("NO_BOT", raising=False)
    return bot, dispatcher


def test_watchdog_restarts_polling_and_sets_menu_button(fake):
    bot, dispatcher = fake
    assert runner.polling_alive() is False

    async def scenario():
        task = asyncio.create_task(runner.run_bot_forever())
        await asyncio.sleep(0.05)
        alive_now = runner.polling_alive()
        done = task.done()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        return alive_now, done

    alive_now, done = run(scenario())
    # два падения подряд не убивают задачу: третий заход поднимает поллинг и держит его
    assert dispatcher.starts >= 3
    assert alive_now is True and done is False
    assert bot.menu_calls and bot.menu_calls[0] == "https://example.invalid"
    assert len(bot.menu_calls) >= 3          # кнопка ставится при каждом подъёме


def test_no_bot_env_keeps_polling_down(monkeypatch):
    monkeypatch.setenv("NO_BOT", "1")
    monkeypatch.setenv("BOT_TOKEN", "123:abc")
    started: list[int] = []

    async def never():
        started.append(1)

    monkeypatch.setattr(runner, "_polling_once", never)
    run(runner.run_bot_forever())
    assert started == []
    assert runner.polling_alive() is False


def test_empty_token_keeps_polling_down(monkeypatch):
    monkeypatch.delenv("NO_BOT", raising=False)
    monkeypatch.setenv("BOT_TOKEN", "")
    started: list[int] = []

    async def never():
        started.append(1)

    monkeypatch.setattr(runner, "_polling_once", never)
    run(runner.run_bot_forever())
    assert started == []


def test_dispatcher_is_one_per_process(monkeypatch):
    """Роутер aiogram включается в Dispatcher один раз — иначе второй заход вотчдога падал бы."""
    monkeypatch.setattr(runner, "_dispatcher", None)
    first = runner.get_dispatcher()
    second = runner.get_dispatcher()
    assert first is second
