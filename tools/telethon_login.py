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


def _push_to_railway(session: str) -> int:
    """Кладёт строку сессии в Railway Variables проекта (папка проекта уже привязана `railway link`)
    и включает STT_PROVIDER=telethon. Токен Railway — из C:\\TelegramBotManager\\ACCESS.env."""
    import re
    import shutil
    import subprocess

    token = os.getenv("RAILWAY_API_TOKEN", "")
    if not token:
        tb = Path(r"C:\TelegramBotManager\ACCESS.env")
        if tb.exists():
            m = re.search(r"^RAILWAY_API_TOKEN=(.+)$", tb.read_text(encoding="utf-8", errors="ignore"), re.M)
            token = m.group(1).strip() if m else ""
    if not token:
        print("Не нашёл RAILWAY_API_TOKEN — строку сессии не печатаю; запустите без --railway.")
        return 2
    exe = shutil.which("railway.cmd") or shutil.which("railway")
    if not exe:
        print("Не нашёл railway CLI — запустите без --railway.")
        return 2
    env = {**os.environ, "RAILWAY_API_TOKEN": token, "MSYS_NO_PATHCONV": "1"}
    r = subprocess.run(
        [exe, "variables", "--service", "finuchet", "--skip-deploys",
         "--set", f"TELETHON_SESSION={session}", "--set", "STT_PROVIDER=telethon"],
        cwd=str(ROOT), env=env, capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if r.returncode != 0:
        print("Railway не принял переменные:", (r.stdout + r.stderr).replace(session, "<сессия>")[-400:])
        return 3
    print("Готово: TELETHON_SESSION записана в Railway Variables (сервис finuchet), STT_PROVIDER=telethon.")
    print("Осталось перезапустить: railway redeploy --service finuchet --yes")
    return 0


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

    to_railway = "--railway" in sys.argv

    with TelegramClient(StringSession(), int(api_id), api_hash) as client:
        me = client.get_me()
        session = client.session.save()
        print()
        print(f"Вошли как: {me.first_name} (@{me.username})" if me else "Вошли.")
        print()
        if to_railway:
            # Строка сессии уходит сразу в Railway Variables, на экран не печатается.
            return _push_to_railway(session)
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
