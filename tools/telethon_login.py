# -*- coding: utf-8 -*-
"""Вход в ОТДЕЛЬНУЮ Telegram-сессию для расшифровки голосовых (ARCHITECTURE §8.1, §13 риск 1).

Зачем: Телеграм умеет расшифровывать голосовые сам (Premium), но только из пользовательской
сессии, не из бота. Сессия нужна отдельная — живую сессию Артёма копировать нельзя: одна и та же
сессия на двух машинах даёт AUTH_KEY_DUPLICATED и слетает (грабля 5 журнала).

Как запускать (Артём вводит код сам, пароли никому не передаются):

    python -X utf8 tools\\telethon_login.py

Скрипт спросит номер телефона, Телеграм пришлёт код, код вводится здесь. В конце строка сессии
печатается ОДИН раз — её нужно скопировать в Railway Variables, переменная TELETHON_SESSION.
В файл строка не сохраняется и в лог не попадает.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / "ACCESS.env")
except ImportError:
    pass

import os


def main() -> int:
    api_id = os.getenv("TELETHON_API_ID")
    api_hash = os.getenv("TELETHON_API_HASH")
    if not api_id or not api_hash:
        print("Нет TELETHON_API_ID / TELETHON_API_HASH. Заполните их в ACCESS.env и запустите снова.")
        return 1

    from telethon import TelegramClient
    from telethon.sessions import StringSession

    print("Вход в отдельную сессию для расшифровки голосовых.")
    print("Телеграм пришлёт код в приложение — введите его здесь. Пароль двухфакторки, если он есть,")
    print("вводите тоже здесь: он никуда не сохраняется.")
    print()

    with TelegramClient(StringSession(), int(api_id), api_hash) as client:
        me = client.get_me()
        session = client.session.save()
        print()
        print(f"Вошли как: {me.first_name} (@{me.username})" if me else "Вошли.")
        print()
        print("=" * 78)
        print("СТРОКА СЕССИИ — показывается один раз. Это полный доступ к аккаунту:")
        print("положите её в Railway Variables, переменная TELETHON_SESSION.")
        print("В файл не сохраняйте, в чат и в git не отправляйте.")
        print("=" * 78)
        print(session)
        print("=" * 78)
        print()
        print("Дальше: в Railway задайте TELETHON_SESSION и STT_PROVIDER=telethon, затем redeploy")
        print("(переменные сами не подхватываются). Проверить — прислать боту голосовое.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
