# -*- coding: utf-8 -*-
"""Обработчики Телеграма: голос, текст, скрин, файл, кнопки (ТЗ 5, 9; ARCHITECTURE §7.5).

Бот отвечает ТОЛЬКО Артёму (OWNER_TG_ID). Чужой апдейт — молча мимо, без «извините, бот личный».
Никакой разметки: parse_mode не задаётся ни в одном вызове.
"""
from __future__ import annotations

import logging
import os
from typing import Any

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from backend.bot import cards, keyboards, pending
from backend.bot.cards import Reply
from backend.pipeline import apply as apply_pipeline
from backend.pipeline import screenshot as screenshot_pipeline
from backend.pipeline import statement as statement_pipeline
from backend.pipeline import text as text_pipeline
from backend.pipeline import voice as voice_pipeline

log = logging.getLogger("finuchet.bot")

router = Router(name="finuchet")

STATEMENT_SUFFIXES = (".pdf", ".xlsx", ".xls", ".csv", ".txt")


def owner_id() -> int:
    try:
        return int(os.getenv("OWNER_TG_ID") or 0)
    except ValueError:
        return 0


def is_owner(user_id: int | None) -> bool:
    owner = owner_id()
    return bool(owner) and user_id == owner


async def send(message: Message, reply: Reply) -> None:
    """Ответ реплаем на исходное сообщение, чистым текстом, без parse_mode."""
    await message.reply(
        cards.plain_tg(reply.text),
        reply_markup=keyboards.to_markup(reply.buttons),
        disable_web_page_preview=True,
    )


@router.message(Command("start"))
async def on_start(message: Message) -> None:
    if not is_owner(message.from_user.id if message.from_user else None):
        return
    await message.answer(
        cards.START_TEXT,
        reply_markup=keyboards.to_markup([keyboards.Button("Финучёт", web_app=keyboards.public_url())]),
    )


@router.message(F.voice | F.audio)
async def on_voice(message: Message) -> None:
    if not is_owner(message.from_user.id if message.from_user else None):
        return
    media = message.voice or message.audio

    async def download() -> bytes:
        buf = await message.bot.download(media)
        return buf.read()

    reply = await voice_pipeline.handle_voice(
        message.chat.id,
        download=download,
        file_unique_id=getattr(media, "file_unique_id", None),
        sent_at=int(message.date.timestamp()) if message.date else None,
        duration=getattr(media, "duration", None),
    )
    await send(message, reply)


@router.message(F.photo)
async def on_photo(message: Message) -> None:
    if not is_owner(message.from_user.id if message.from_user else None):
        return
    photo = message.photo[-1]
    buf = await message.bot.download(photo)
    replies = await screenshot_pipeline.handle_screenshot(message.chat.id, buf.read(), "image/jpeg")
    for reply in replies:
        await send(message, reply)


@router.message(F.document)
async def on_document(message: Message) -> None:
    if not is_owner(message.from_user.id if message.from_user else None):
        return
    doc = message.document
    name = (doc.file_name or "").lower()
    buf = await message.bot.download(doc)
    blob = buf.read()
    if name.endswith((".png", ".jpg", ".jpeg", ".webp")):
        media_type = "image/png" if name.endswith(".png") else "image/jpeg"
        replies = await screenshot_pipeline.handle_screenshot(message.chat.id, blob, media_type)
    elif name.endswith(STATEMENT_SUFFIXES):
        replies = await statement_pipeline.handle_statement(message.chat.id, blob, name)
    else:
        replies = [Reply("Не знаю, что делать с этим файлом. Нужен скрин, PDF, XLSX или CSV.")]
    for reply in replies:
        await send(message, reply)


@router.message(F.text)
async def on_text(message: Message) -> None:
    if not is_owner(message.from_user.id if message.from_user else None):
        return
    text = message.text or ""
    if text.startswith("/"):
        return  # других команд нет (§7.5)
    state = await pending.get(message.chat.id)
    if state and state.get("state") == pending.RECONCILE:
        reply_list = await _resume_reconcile(message.chat.id, state, text)
        if reply_list is not None:
            for reply in reply_list:
                await send(message, reply)
            return
    await send(message, await text_pipeline.handle_phrase(message.chat.id, text, source="text"))


async def _resume_reconcile(chat_id: int, state: dict, text: str) -> list[Reply] | None:
    """Ответ на вопрос «с какого счёта скрин» — продолжаем прерванную сверку."""
    slug = screenshot_pipeline.account_from_words(text)
    if not slug:
        return None
    payload: dict[str, Any] = state.get("payload") or {}
    parsed = payload.get("parsed")
    if not parsed:
        return None
    await pending.clear(chat_id)
    return await screenshot_pipeline.handle_parsed(
        chat_id, parsed, source=payload.get("source", "screenshot"), account_hint=slug
    )


@router.callback_query()
async def on_callback(query: CallbackQuery) -> None:
    if not is_owner(query.from_user.id if query.from_user else None):
        return
    reply = await apply_pipeline.handle_callback(query.message.chat.id if query.message else 0, query.data or "")
    await query.answer()
    if reply is None or query.message is None:
        return
    try:
        # кнопка-действие исчезает: карточка переписывается на месте (§7.1)
        await query.message.edit_text(
            cards.plain_tg(reply.text), reply_markup=keyboards.to_markup(reply.buttons)
        )
    except Exception:
        await query.message.answer(
            cards.plain_tg(reply.text), reply_markup=keyboards.to_markup(reply.buttons)
        )
