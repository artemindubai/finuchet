# -*- coding: utf-8 -*-
"""Запуск бота и фоновых задач. Пять сигнатур из ARCHITECTURE §1.2 — менять нельзя.

`backend/app.py` (агент A) зовёт ровно их и больше ничего про бота не знает.
"""
from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path

log = logging.getLogger("finuchet.runner")

RESTART_SLEEP_SEC = 15

_bot_instance = None
_dispatcher = None
_polling_ok = False


def polling_alive() -> bool:
    """Правда ли сейчас крутится поллинг (для /healthz). После падения — False до подъёма."""
    return _polling_ok


def bot_token() -> str:
    return (os.getenv("BOT_TOKEN") or "").strip()


def owner_id() -> int:
    try:
        return int(os.getenv("OWNER_TG_ID") or 0)
    except ValueError:
        return 0


def get_bot():
    """Один экземпляр Bot на процесс. Токена нет — None (веб поднимается без бота)."""
    global _bot_instance
    if _bot_instance is not None:
        return _bot_instance
    token = bot_token()
    if not token:
        return None
    from aiogram import Bot

    _bot_instance = Bot(token=token)
    return _bot_instance


def get_dispatcher():
    """Один Dispatcher на процесс: роутер aiogram нельзя включить во второй Dispatcher,
    а вотчдог поднимает поллинг заново — второй раз include_router упал бы навсегда."""
    global _dispatcher
    if _dispatcher is not None:
        return _dispatcher
    from aiogram import Dispatcher

    from backend.bot.handlers import router

    _dispatcher = Dispatcher()
    _dispatcher.include_router(router)
    return _dispatcher


async def run_bot_forever() -> None:
    """Вечный поллинг с вотчдогом: 409 при редеплое не должен убивать сервис насовсем."""
    if os.getenv("NO_BOT") == "1":
        log.info("NO_BOT=1 — поллинг не поднимаем")
        return
    if not bot_token():
        log.warning("BOT_TOKEN не задан — бот не поднят")
        return
    while True:
        try:
            await _polling_once()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.warning("поллинг упал (%s), перезапуск через %s с", exc, RESTART_SLEEP_SEC)
            await asyncio.sleep(RESTART_SLEEP_SEC)


async def _polling_once() -> None:
    global _polling_ok
    from aiogram.types import MenuButtonWebApp, WebAppInfo

    bot = get_bot()
    if bot is None:
        return
    dispatcher = get_dispatcher()

    public_url = (os.getenv("PUBLIC_URL") or "http://localhost:8080").rstrip("/")
    try:
        # не по-https адрес Телеграм не примет — это повод для строки в логе, а не для падения
        await bot.set_chat_menu_button(
            menu_button=MenuButtonWebApp(text="Финучёт", web_app=WebAppInfo(url=public_url))
        )
    except Exception as exc:
        log.warning("кнопку меню поставить не вышло: %s", exc)

    log.info("поллинг поднят")
    _polling_ok = True
    try:
        # drop_pending_updates: после рестарта старые голосовые не запишутся повторно (грабля 7)
        await dispatcher.start_polling(bot, drop_pending_updates=True, handle_signals=False)
    finally:
        _polling_ok = False


async def run_telethon_stt_forever() -> None:
    """No-op, если STT_PROVIDER != telethon или сессия не заведена."""
    from backend.stt.telethon_provider import run_listener_forever

    await run_listener_forever()


async def run_reminders_forever() -> None:
    """Раз в сутки в 09:00 по Дубаю. Напоминать нечего — молчим."""
    from backend.bot import reminders

    while True:
        try:
            await asyncio.sleep(reminders.seconds_until_9am())
            if not reminders.reminders_enabled():
                continue
            text = await reminders.build_text()
            if text:
                await notify_owner(text)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.warning("напоминания упали (%s), продолжаем", exc)
            await asyncio.sleep(RESTART_SLEEP_SEC)


async def send_document_to_owner(path: str, caption: str) -> bool:
    """Выгрузка XLSX уходит Артёму в чат (ТЗ 7)."""
    bot = get_bot()
    owner = owner_id()
    if bot is None or not owner:
        log.warning("файл не отправлен: бот не поднят")
        return False
    from aiogram.types import FSInputFile

    file_path = Path(path)
    if not file_path.exists():
        log.warning("файл не найден: %s", file_path.name)
        return False
    try:
        await bot.send_document(owner, FSInputFile(str(file_path)), caption=(caption or "")[:1024])
        return True
    except Exception as exc:
        log.warning("файл не ушёл в чат: %s", exc)
        return False


async def notify_owner(text: str) -> bool:
    """Системное сообщение Артёму чистым текстом. Не «бот сам пишет» — только по делу."""
    from backend.bot.cards import plain_tg

    bot = get_bot()
    owner = owner_id()
    if bot is None or not owner:
        return False
    try:
        await bot.send_message(owner, plain_tg(text))
        return True
    except Exception as exc:
        log.warning("сообщение не ушло: %s", exc)
        return False
