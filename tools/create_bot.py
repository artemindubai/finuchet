# -*- coding: utf-8 -*-
"""Создание телеграм-бота через BotFather с помощью Telethon-сессии Артёма.

Диалог с BotFather: /newbot -> имя -> username -> токен.
Токен и username пишутся в ACCESS.env (ключи BOT_TOKEN, BOT_USERNAME), токен в консоль
печатается только в укороченном виде.
Образец: C:\\Projects\\europass-bot\\create_bot.py
"""
import asyncio
import re
import sys
import io
import os

from telethon import TelegramClient

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# TELETHON_API_ID / TELETHON_API_HASH — из ACCESS.env проекта (не хардкодить)
def _env(name):
    import re as _re, os as _os
    _p = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), 'ACCESS.env')
    _m = _re.search(r'^' + name + r'=(.+)$', open(_p, encoding='utf-8').read(), _re.M)
    return _m.group(1).strip() if _m else ''
API_ID = int(_env('TELETHON_API_ID'))
API_HASH = _env('TELETHON_API_HASH')
SESSION = r'C:\Projects\zoomer-skill\telethon\zoomer_reserve'

BOT_NAME = 'Финучёт'
USERNAME_CANDIDATES = [
    'finuchet_bot',
    'finuchet_artem_bot',
    'artem_finuchet_bot',
    'finuchetapp_bot',
    'moy_finuchet_bot',
]

ENV_PATH = r'C:\Projects\finuchet\ACCESS.env'


async def send_and_wait(client, text, pause=4):
    """Шлёт BotFather сообщение и возвращает его ответ."""
    await client.send_message('BotFather', text)
    await asyncio.sleep(pause)
    msgs = await client.get_messages('BotFather', limit=1)
    return msgs[0].message if msgs else ''


async def main():
    client = TelegramClient(SESSION, API_ID, API_HASH)
    await client.start()
    me = await client.get_me()
    print('Аккаунт: %s (@%s)' % (me.first_name, me.username))

    reply = await send_and_wait(client, '/newbot')
    print('BotFather:', reply[:120].replace('\n', ' '))

    if 'how are we going to call it' not in reply.lower() and 'name for your bot' not in reply.lower():
        print('Неожиданный ответ на /newbot, прерываю.')
        await client.disconnect()
        return 1

    reply = await send_and_wait(client, BOT_NAME)
    print('BotFather:', reply[:120].replace('\n', ' '))

    token = None
    username_used = None
    for candidate in USERNAME_CANDIDATES:
        print('Пробую username: @%s' % candidate)
        reply = await send_and_wait(client, candidate, pause=5)
        short = reply[:150].replace('\n', ' ')
        print('BotFather:', short)
        m = re.search(r'(\d{8,10}:[A-Za-z0-9_-]{30,})', reply)
        if m:
            token = m.group(1)
            username_used = candidate
            break
        if 'taken' in reply.lower() or 'занят' in reply.lower() or 'invalid' in reply.lower():
            continue
        print('Непонятный ответ, пробую следующий вариант.')

    if not token:
        await client.disconnect()
        print('Токен получить не удалось.')
        return 1

    print('\nБот создан: @%s' % username_used)
    print('Токен получен: %s...%s (len=%d)' % (token[:10], token[-4:], len(token)))

    lines = []
    with open(ENV_PATH, encoding='utf-8') as f:
        for line in f.read().split('\n'):
            if line.startswith('BOT_TOKEN='):
                line = 'BOT_TOKEN=' + token
            elif line.startswith('BOT_USERNAME='):
                line = 'BOT_USERNAME=' + username_used
            lines.append(line)
    with open(ENV_PATH, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    print('Токен и username записаны в ACCESS.env')

    # BotFather: описание и about-текст (plain text)
    await send_and_wait(client, '/setdescription', pause=3)
    await send_and_wait(client, '@%s' % username_used, pause=3)
    reply = await send_and_wait(
        client,
        'Учёт личных финансов Артёма. Голосовое или текст — запишу операцию.',
        pause=4,
    )
    print('setdescription:', reply[:120].replace('\n', ' '))

    await send_and_wait(client, '/setabouttext', pause=3)
    await send_and_wait(client, '@%s' % username_used, pause=3)
    reply = await send_and_wait(client, 'Учёт личных финансов Артёма.', pause=4)
    print('setabouttext:', reply[:120].replace('\n', ' '))

    await client.disconnect()
    return 0


sys.exit(asyncio.run(main()))
